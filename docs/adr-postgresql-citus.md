# ADR: migración de SQLite a PostgreSQL + Citus (distribución por `tenant_id`)

Estado: **fases 0 a 6 completadas (… modelo del despacho, esquema Citus y la aplicación sobre él)**. Aún no se ha cambiado código de la aplicación. Plan por fases: [plan-migracion-postgresql-citus.md](plan-migracion-postgresql-citus.md). Clasificación tabla a tabla: [migracion-clasificacion-tablas.csv](migracion-clasificacion-tablas.csv). Scripts: `scripts/migracion/` (solo lectura).

## Decisiones tomadas (2026-10-23)

| # | Decisión |
|---|---|
| D1 | **Un usuario puede pertenecer a varios despachos** (incluso a varios tenants). Hoy `usuarios.tenant_id` admite uno solo; se mantiene como «despacho predeterminado» y se añade una tabla de pertenencia usuario↔despacho (fase 6). Todo dato de despacho lleva el `tenant_id` del contexto en el que se creó. |
| D2 | **SQLite se retira tras estabilizar** (fase 12). No se mantiene el modo local con SQLite. |
| D3 | **Mismo VPS** por ahora (4 vCPU, 7 GB, ~25 contenedores). Citus en **un solo nodo**; los workers se añaden cuando haya más máquinas. |
| D4 | **RLS activada** como segunda barrera de aislamiento. |
| D5 | **Fechas como texto ISO 8601** durante la migración; conversión a `timestamptz` en una fase posterior independiente. |

## Estado medido del sistema

- Esquema limpio (`init_db()` en copia aislada) y producción son **idénticos**: 224 tablas (3 FTS5), 276 índices, 27 triggers, 1 vista. No hay divergencia entre migraciones y esquema nuevo.
- Producción es pequeña: **34.312 filas en total** (15.570 son fragmentos jurídicos), 1 despacho, 4 usuarios (2 sin despacho), `integrity_check` ok y `foreign_key_check` vacío. Esto reduce mucho el riesgo del corte.
- 24 claves primarias compuestas, 1 tabla sin PK (`tenants_herramientas_ocultas`), 19 tablas con columnas BLOB.
- 1.633 sentencias SQL tocan tablas que se van a distribuir; **986 no mencionan `tenant_id`** (heurística estática: filtran por `id` o `usuario_id`). Concentradas en `db_correo.py` (169), `db_tareas.py` (166), `db_plataforma.py` (65), `tareas_trabajo.py` (56) y `db_proyectos.py` (51).

## Clasificación para Citus (224 tablas)

| Clase | Tablas | Qué implica |
|---|---:|---|
| distribuida (ya lleva `tenant_id`) | 105 | PK `(tenant_id, id)`, FK compuestas |
| distribuida + hija | 59 | Se les añade `tenant_id` copiado del padre |
| distribuida + usuario | 23 | Datos personales (correo, IA, notas, tareas…): se les añade el `tenant_id` del contexto de creación |
| referencia | 14 | `tenants`, `usuarios`, planes, catálogos fiscales/laborales, `tokens_api`, `usuario_perfil`… replicadas en cada nodo |
| local (solo coordinador) | 20 | Corpus jurídico compartido (`jur_*` sin despacho), registros técnicos globales |
| virtual (FTS5) | 3 | Sustituidas por columnas `tsvector` + GIN |

## Hallazgos que condicionan el diseño

1. **Datos de producción rellenables**: los 13 `fichajes` sin `tenant_id` pertenecen a usuarios que sí tienen despacho (se rellenan desde `usuarios.tenant_id`). Los 7 `jur_auditoria` sin `tenant_id` son eventos de plataforma (`politica.registrar`, `fuente.habilitar`) y quedan sin despacho. Ninguna fila de las tablas «usuario» con datos pertenece a un usuario sin despacho.
2. **35 `UNIQUE` sin `tenant_id`** en tablas a distribuir. Dos tipos:
   - *Con clave del padre* (`vencimientos_fiscales(cliente_fiscal_id, modelo, periodo)`, `contabilidad_plan`…): basta añadir `tenant_id` al índice.
   - *Búsquedas globales por token o identificador externo* (`clientes_fiscales_accesos.token`, `facturacion_accesos.token`, `abogados_enlaces.token_hash`, `inmobiliaria_enlaces.token_hash`, `vencimientos_fiscales_pagos.stripe_checkout_session_id`, `fichajes.cliente_uuid`, `notas.cliente_uuid`, `tareas_outlook.outlook_entry_id`): se resuelven con una **tabla de referencia de búsqueda** (token → `tenant_id`, id) o incluyendo el `tenant_id` en el enlace.
3. **Cifrado en reposo del correo y de los documentos** (`correo_cifrado.py`, `almacen_documentos.py`): hoy se apoya en `PRAGMA secure_delete` y `wal_checkpoint(TRUNCATE)` para que no quede texto en claro en el fichero ni en el WAL. En PostgreSQL esas garantías no existen (versiones muertas de filas, WAL archivado, réplicas). Requisito nuevo: **cifrar antes de insertar** y no guardar nunca el claro; las filas hoy en claro se sellarán antes del corte y se eliminará su rastro con `VACUUM FULL` en la fase 11.
4. **`writable_schema`/`schema_version`** (`tareas_trabajo.py`) reescriben un `CHECK` de SQLite: en PostgreSQL pasa a un `ALTER TABLE … DROP/ADD CONSTRAINT`.
5. **27 triggers** (auditoría inmutable, historial de cambios, sellado de FTS, versionado de tareas) y **1 vista** (`tareas_participantes_todos`) que se reescriben en PL/pgSQL. La inmutabilidad de `auditoria_eventos` debe conservarse (trigger que rechaza `UPDATE`/`DELETE` más permisos de rol).
6. **Las 986 sentencias sin `tenant_id`** son correctas en Citus pero se reparten por todos los shards; con RLS hace falta que cada conexión fije `app.tenant_id`. Pendiente de verificar en la fase 1 si Citus poda shards a partir del filtro de la política RLS; si no, el filtro explícito `tenant_id = %s` pasa a ser obligatorio en el acceso a datos de la fase 6c.
7. **Datos sensibles en `tenants`**: columnas `*_pass` y `*_api_key` (FacturaScripts, Cal.com, Paperless, Stalwart…). Comprobar en la fase 4 si están cifradas; si no lo están, cifrarlas al migrar y excluirlas de los volcados.
8. **`usuarios` como tabla de referencia**: la identidad es global y un usuario puede tener datos en varios despachos. `tokens_api` y `ver_como_tokens` quedan también como referencia; las llamadas con token deben resolver el despacho en cada petición.

## Riesgos añadidos a los del plan

| Riesgo | Mitigación |
|---|---|
| Cifrado en reposo del correo/documentos pierde garantías | Cifrar antes de insertar, sellar todo antes del corte, `VACUUM FULL` y rotación del WAL archivado |
| RLS no permite podar shards | Prueba en la fase 1; filtro explícito obligatorio si hace falta |
| Un usuario en varios despachos rompe supuestos de `usuarios.tenant_id` | Tabla de pertenencia + despacho activo en sesión; test de aislamiento con un usuario de dos despachos |
| Triggers de auditoría inmutable | Reimplementar con trigger y permisos de rol; test de inmutabilidad en ambos motores |

## Criterios de salida de la fase 0 (cumplidos)

- [x] 224 tablas clasificadas (CSV) y esquema limpio = producción.
- [x] Decisiones D1-D5 cerradas.
- [x] Puntos delicados identificados (cifrado, triggers, UNIQUE, tokens).
- [x] Datos de producción verificados para el relleno de `tenant_id`.
- [ ] Línea base de rendimiento de las consultas críticas (se mide en la fase 1 sobre una copia de producción, con `scripts/probar.sh --perfil`).

## Fase 1: resultados del ensayo (2026-10-23)

Entorno: PostgreSQL 17.10 + Citus 14.2.0 + pgvector 0.8.7 (`unaccent`, `pg_trgm`), un solo nodo, imagen `deploy/postgres-citus/`, experimentos en `deploy/postgres-citus/experimentos/` y informes en `data/pg-ensayo/` (no versionados).

### Qué funciona

| Prueba | Resultado |
|---|---|
| Tablas de referencia + distribuidas colocalizadas, PK `(tenant_id, id)`, FK compuestas con `ON DELETE CASCADE` | Correcto; ids de identidad únicos globalmente |
| Consulta con `tenant_id` | 1 tarea (un solo shard); join colocalizado también 1 |
| Consulta sin `tenant_id` | Se reparte por todos los shards (correcta, más lenta) |
| Transacción que toca dos despachos | Correcta |
| Tabla local del coordinador unida a una distribuida | Correcta (sirve para el corpus jurídico compartido) |
| FTS: `tsvector` generado con `unaccent` + configuración `spanish` + GIN sobre tabla distribuida | Correcto («jurisdiccion» ↔ «jurisdicción») |
| pgvector (HNSW) sobre tabla distribuida | Correcto |
| RLS con `app.tenant_id`: sin contexto 0 filas; con contexto solo su despacho; escribir en otro despacho viola la política; `UPDATE` ajeno 0 filas | Correcto |
| Trigger de auditoría inmutable (creado con `citus.enable_unsafe_triggers = on`) | Creado en coordinador y en los 32 shards; bloquea `UPDATE`/`DELETE`; **sigue funcionando con el ajuste apagado** (solo hace falta al crearlo) |
| Trigger de historial que escribe en otra tabla distribuida colocalizada | Correcto, también sin el ajuste en ejecución |
| Inmutabilidad por permisos (rol con solo `SELECT`/`INSERT`) | `UPDATE`, `DELETE` y `TRUNCATE` denegados |
| Clonado de bases con plantilla | Funciona **solo** tras `ALTER DATABASE … ALLOW_CONNECTIONS false` y terminar sesiones (el demonio de mantenimiento de Citus mantiene una conexión) |

### Qué NO funciona o requiere cuidado

1. `GENERATED … AS IDENTITY` + clave foránea a tabla de referencia en el mismo `CREATE TABLE`: la tabla se convierte en «local de Citus» y `create_distributed_table` falla («cannot complete operation on a table with identity column»). Soluciones probadas: `SET citus.enable_local_reference_table_foreign_keys = off` al crear el esquema, distribuir primero y añadir la FK después, o `bigserial`.
2. **La política RLS no poda shards**: sin filtro explícito la consulta va a los 32 shards (usando el índice por despacho dentro de cada uno). El filtro `tenant_id = X` en la propia consulta sigue siendo necesario para el rendimiento.
3. **El contexto de despacho solo viaja con `SET LOCAL`** y `citus.propagate_set_commands = 'local'`. Un `SET` de sesión no llega a los shards y con `propagate_set_commands = none` tampoco: el resultado es 0 filas (fallo seguro, nunca datos de otro despacho).
4. Un `EXPLAIN` entre una consulta repartida y un `INSERT` en la misma transacción provoca «cannot switch local execution status…». No ocurre sin `EXPLAIN`; evitar `EXPLAIN` dentro de transacciones con escrituras.
5. Los roles de la aplicación necesitan `LOGIN` (Citus abre conexiones internas con el mismo rol).
6. Coste de shards (190 tablas): 8 shards → 2,2 s y +43 MB; 16 → 4,0 s y +79 MB; 32 → 7,5 s y +171 MB. Proporcional al número de shards. El clonado y borrado de una base con ~6.000 shards tarda ~2 s + ~2,5 s.

### Decisiones nuevas

| # | Decisión |
|---|---|
| D6 | **`citus.shard_count = 16`** (≈3.000 shards con 190 tablas). Se puede cambiar después con `alter_distributed_table`. |
| D7 | **Auditoría inmutable con dos barreras**: trigger (creado con `citus.enable_unsafe_triggers = on` durante la migración) y permisos (el rol de la aplicación solo tiene `SELECT`/`INSERT` sobre esas tablas). |
| D8 | **Contexto de despacho**: cada transacción empieza con `SET LOCAL app.tenant_id = X`; `ALTER DATABASE … SET citus.propagate_set_commands = 'local'`; `SET` de sesión prohibido. Compatible con PgBouncer en modo transacción. |
| D9 | **Esquema**: durante la creación del esquema se desactiva `citus.enable_local_reference_table_foreign_keys` para mantener el DDL actual (identidad + FK). |
| D10 | **Roles**: propietario/migraciones (con `BYPASSRLS`) distinto del rol de la aplicación (`LOGIN`, sin `SUPERUSER`, sin `BYPASSRLS`, no propietario). |
| D11 | **Consultas**: el filtro explícito `tenant_id` es obligatorio en el acceso a datos (RLS es la red de seguridad, no el índice). Test que detecta consultas sin filtro. |
| D12 | **Tests**: la suite principal corre contra PostgreSQL **sin distribuir** (clon de plantilla por test, rápido); una suite específica corre contra Citus (plantilla con `shard_count` bajo y `ALLOW_CONNECTIONS false` al clonar). |

### Línea base de rendimiento

Pendiente: se medirá en la fase 9 con una copia de producción cargada (la base actual tiene 34.312 filas y no permite medir nada significativo).

### Criterios de salida de la fase 1 (cumplidos)

- [x] `SELECT citus_version()` correcto y extensiones instaladas.
- [x] Clonado y borrado de una base de ensayo medidos (≈2 s con ~6.000 shards).
- [x] RLS, SET LOCAL, triggers, FTS y pgvector comprobados sobre tablas realmente distribuidas.

## Fase 2: capa de acceso a datos de dos motores (2026-10-23)

Paquete `app/bd/`; `db.get_connection(despacho=None)` delega en PostgreSQL con `GUILDA_DB_ENGINE=postgres` (+ `GUILDA_DATABASE_URL`). Por defecto sigue siendo SQLite y **nada cambia** para la aplicación: suite completa (`probar.sh -n 3`) en verde. Dependencias opcionales en `requirements-postgres.txt` (`psycopg[binary]`, `psycopg_pool`).

| Pieza | Qué hace |
|---|---|
| `bd/__init__.py`, `errores.py` | Selector de motor. `ErrorIntegridad`, `ErrorOperacional`, `ErrorBD`: tuplas válidas en `except` para ambos motores (19 `except sqlite3.*` sustituidos) |
| `bd/fila.py` | `Fila`: interfaz de `sqlite3.Row` (por nombre sin distinguir mayúsculas, por posición, `keys()`, `dict()`, desempaquetado) |
| `bd/traduccion.py` | `?`→`%s`, `:nombre`→`%(nombre)s`, `%` literal, `BEGIN IMMEDIATE`, `INSERT OR IGNORE`→`ON CONFLICT DO NOTHING`, PRAGMAs inofensivos. `REPLACE`, `INSERT OR REPLACE` y PRAGMAs sin equivalente **fallan con `NoPortable`** (nunca ejecutan algo distinto) |
| `bd/postgres.py` | `ConexionPG` + pool: transacción implícita antes de escribir, `SAVEPOINT` por escritura (una sentencia fallida no invalida la transacción), `lastrowid` vía `RETURNING` de la columna de identidad, `BEGIN IMMEDIATE` con bloqueo asesor global, `close()` devuelve al pool, contexto de despacho (`SET LOCAL`/`set_config(..., true)` al abrir cada transacción, también para lecturas), sin sentencias preparadas (compatible con PgBouncer) |

Pruebas: `tests/test_bd_capa.py` (21, sin servidor, con conexión falsa) y `tests/test_bd_postgres_real.py` (se salta sin `GUILDA_TEST_PG_URL`; cubre identidad con PK compuesta, errores de integridad sin invalidar la transacción, nombrados, `table_info` y RLS con despacho).

### Lo que la capa NO resuelve (entra en la fase 3)

- `INSERT OR REPLACE`/`REPLACE` (1 caso), `PRAGMA integrity_check|foreign_key_check|schema_version|writable_schema`, `create_function("plano")` (nucleo.py), fechas SQLite (`strftime`, `date('now')`, `julianday`), `rowid` (149), `GROUP_CONCAT`, FTS5 y `executescript` con DDL de SQLite.
- Los 13 `sqlite3.connect` directos (copias de seguridad, migraciones, `db.py`:1581-1718, 2329-2339): copias en la fase 10, migraciones en las fases 3-4.
- `BEGIN IMMEDIATE` se traduce a un bloqueo global; los usos en fichajes (cadena de hashes GLOBAL), consumo de IA, soporte y enlaces fiscales hay que revisarlos en la fase 6 para que serialicen por despacho (la cadena de fichajes global no escala con Citus).
- Un fallo de SELECT dentro de una transacción SÍ invalida la transacción en PostgreSQL (solo las escrituras llevan SAVEPOINT).

## Fase 3: SQL portable (2026-10-23)

`scripts/migracion/auditar_sql.py` lee todo el SQL embebido (1.986 sentencias DML) y `tests/test_sql_portable.py` falla si reaparece una construcción solo-SQLite. Medido: mucho menos de lo estimado al empezar (los `strftime` eran de Python, no de SQL).

| Construcción | Antes | Ahora (válido en SQLite ≥3.44 y PostgreSQL) |
|---|---:|---|
| `INSERT OR IGNORE` | 36 | `INSERT … ON CONFLICT DO NOTHING` (`WHERE true` en los `INSERT … SELECT` sin WHERE) |
| `INSERT OR REPLACE` | 1 | `ON CONFLICT (tenant_id) DO UPDATE SET … excluded.…` |
| `col IS ?` | 6 | `col IS NOT DISTINCT FROM ?` |
| `group_concat` | 1 | `string_agg` |
| `COLLATE NOCASE` | 1 | `LOWER()` |
| `LIKE` que dependía de ser insensible | 3 | `LOWER(col) LIKE …` |
| `julianday` / `date('now', …)` | 3 | cálculo en Python (parámetro con la fecha) |
| `sqlite_master` | 4 | `bd.existe_tabla(conn, nombre)` |
| Migraciones que reconstruyen tablas viejas (`foreign_key_check`, `writable_schema`…) | 5 | solo con `GUILDA_DB_ENGINE=sqlite` |

Diferencias de semántica a vigilar: `ON CONFLICT DO NOTHING` solo ignora conflictos de UNICIDAD (`OR IGNORE` ignoraba también NOT NULL/CHECK); en PostgreSQL `\` es el carácter de escape por defecto de `LIKE` (en SQLite no hay); `test_sql_portable.py::test_las_sentencias_dml_se_parsean_como_postgresql` analiza la sintaxis con `pglast` (opcional, en `requirements-postgres.txt`) y se salta si falta.

Pendiente para las fases 4-5 (permitido por el auditor): DDL de SQLite (201 apariciones), triggers, `plano()` como función SQL, FTS5/`rowid` (10), `PRAGMA secure_delete`/`wal_checkpoint` (sin efecto en PostgreSQL: ver hallazgo 3). Los errores de TIPOS, `GROUP BY` laxo, orden de NULL y booleanos solo aparecen ejecutando contra PostgreSQL (fases 4 y 7).

## Fase 4: esquema de PostgreSQL (2026-10-23)

`scripts/migracion/generar_esquema_pg.py` convierte el esquema FINAL de SQLite (tras `init_db()`) en `app/bd/esquema_pg/`: `01_tablas.sql` (221 tablas), `02_indices.sql` (137), `03_claves_foraneas.sql` (345, aparte para poder distribuir con Citus antes de añadirlas: D9) y `04_vistas.sql`. `00_funciones.sql` (`f_unaccent`, `plano`, extensiones) y `05_triggers.sql` (15 funciones/triggers: historial `api_cambios`, auditoría de solo anexado, versión de tareas, cliente principal, estado «en revisión») son manuales. `app/bd/esquema.py::crear_si_falta` lo crea una sola vez en una transacción (0,6 s) y registra la versión en `bd_esquema_version`; a partir de ahí, migraciones numeradas.

| Decisión | Detalle |
|---|---|
| Tipos | INTEGER→bigint, TEXT→text, REAL→double precision, BLOB→bytea; fechas ISO y banderas 0/1 se mantienen (D5) |
| Identidad | `id INTEGER PRIMARY KEY [AUTOINCREMENT]` → `GENERATED BY DEFAULT AS IDENTITY`. Las 21 claves `*_id` que son a la vez PK (`usuario_id`, `tenant_id`…) quedan SIN identidad. Al cargar datos hay que sincronizar las secuencias (`setval`) — fase 8 |
| Defaults | `datetime('now','localtime')` → `to_char(localtimestamp, …)` (la base usa `timezone = Europe/Madrid`) |
| Triggers | `RAISE(ABORT, …)` → `RAISE EXCEPTION … ERRCODE integrity_constraint_violation` (psycopg lo da como `IntegrityError`); el `DELETE` de auditoría comprueba `permitir_borrado` dentro de la función (PostgreSQL no admite subconsultas en `WHEN`) |
| Fuera de esta fase | FTS5 y sus triggers (fase 5), `tenant_id` y distribución con Citus (fase 6), RLS (fase 6) |

Comprobaciones (todas automáticas): `tests/test_esquema_pg.py` (ficheros al día frente al generador; esquema equivalente al de SQLite tabla a tabla —columnas, nulos, PK, UNIQUE, FK y acciones—; triggers; `plano()`; y **todo el SQL de la aplicación se acepta con `PREPARE` contra el esquema real**) y `tests/test_bd_postgres_real.py`. `ConexionPG.executescript` ignora los scripts que son solo DDL idempotente de SQLite (los `crear_esquema` de cada módulo) y `ejecutar_script` ejecuta sin filtrar.

### SQL que PostgreSQL rechazó y se reescribió de forma portable (34 sentencias de 1.758)

`SUM(<comparación>)` → `SUM(CASE WHEN … THEN 1 ELSE 0 END)` (19); `ON CONFLICT … DO UPDATE SET c = c + 1` → `tabla.c + 1` (6) y `MAX(a, b)` escalar → `CASE`; `GROUP BY` completo en 5 consultas con `LEFT JOIN` a `usuario_perfil` y 1 de la biblioteca jurídica; `ORDER BY lower(alias)` → la expresión (3); parámetros sin tipo (`? IS NULL`) → `CAST(? AS BIGINT)` (4); `activa = (id = ?)` → `CASE`; `date(?, '-7 days')` → Python.

### Lo que sigue sin comprobarse (fases 5-7)

`PREPARE` valida nombres, funciones y tipos de columnas, no los TIPOS de los parámetros que envía Python (texto frente a entero en una comparación real), el orden de NULL (SQLite los pone primero en ASC; PostgreSQL al final), ni la semántica de `LIKE` con `\`. Eso solo aparece ejecutando la suite completa contra PostgreSQL (fase 7); mientras tanto, `ORDER BY` sobre columnas anulables hay que revisarlos.

## Fase 5: búsqueda de texto y vectores (2026-10-23)

| SQLite | PostgreSQL |
|---|---|
| Tablas FTS5 `correo_fts`, `jur_fragmentos_fts`, `jur_fragmentos_privados_fts` + triggers | Columna **`busqueda tsvector` GENERADA** (`ALTER TABLE … ADD COLUMN … GENERATED ALWAYS AS (…) STORED`) + índice GIN: sin triggers que mantener (`app/bd/esquema_pg/06_busqueda.sql`) |
| Tokenizador `unicode61 remove_diacritics 2` | Configuración `es_simple` (copia de `simple` con el diccionario `unaccent`) y `texto_buscable()`, que convierte en separador todo lo que no sea letra o cifra: «1.101», «BOE-A-2023-1234» y «acme.com» se parten igual. **Sin raíces (stemming)**, para medir la recuperación contra el comportamiento de SQLite; activarlo es una mejora aparte |
| `MATCH`, `bm25()`, `snippet()` | `@@ to_tsquery('es_simple', …)`, `ts_rank_cd(…, 2)` (normalizado por longitud: lo más parecido a bm25 que hay en PostgreSQL), `ts_headline()` |
| Correo: prefijo `fact*`, frase `"a b"`, todas las palabras | `consulta_tsquery()`: `(fact:*) & (a <-> b)`; solo letras y cifras pasan, nada del texto del usuario es sintaxis de tsquery |
| Mensaje «entrando, por sellar» (`cifrado = 2`) no se indexa | La expresión generada devuelve NULL mientras `cifrado = 2` y se recalcula sola al sellar; `_depurar_indice` hace `VACUUM correo_mensajes` (mejor esfuerzo) para retirar versiones antiguas de la fila |
| Embeddings en BLOB y coseno en Python | **Sin cambios** (bytea). `pgvector` queda para cuando `LEGAL_EMBEDDINGS` se use de verdad: columna `vector(N)` + índice HNSW (D13) |

Requisito de la base de datos: **LC_CTYPE UTF-8 (no «C»)**; con «C» las letras acentuadas no cuentan como letras y `lower()` no las pasa a minúsculas. Comprobado en la instancia de ensayo (`en_US.utf8`).

Otras correcciones: los `LIKE` sobre texto escrito por personas ahora usan `LOWER(col) LIKE LOWER(?)` (en SQLite no distinguen mayúsculas y en PostgreSQL sí): correo, notas, tareas, historial, clientes fiscales y filtros de la biblioteca; `COLLATE NOCASE` y `IS ?` de `busqueda.py` reescritos. El auditor (`likes_sin_normalizar`) y `tests/test_sql_portable.py` lo vigilan, y ahora detecta también fragmentos de SQL que no empiezan por SELECT (el auditor anterior los pasaba por alto).

Pruebas (`tests/test_busqueda_pg.py`, contra el servidor de ensayo): las 16 consultas jurídicas del corpus sintético devuelven los mismos documentos, totales, modos, huecos y avisos en SQLite y PostgreSQL (el MEJOR fragmento de un documento puede cambiar de uno a otro cuando varios coinciden: bm25 frente a ts_rank_cd); 18 búsquedas de correo idénticas (acentos, mayúsculas, prefijo, frase, números con punto, `50%`); el mensaje por sellar no se encuentra y sí tras sellarlo; la evaluación de recuperación del repositorio da el mismo resultado; los fragmentos privados respetan el despacho; el modo híbrido con embeddings funciona.

**Lo que SÍ cambia para quien busca:** el orden de los resultados dentro de un mismo documento y entre documentos con puntuaciones parecidas puede variar respecto a SQLite. Con un corpus real y casos anotados por un profesional (hito 5 del piloto) conviene repetir la medición antes del corte.

## Fase 6a: modelo multitenant, en una copia aislada (2026-10-24)

**Cambio respecto al plan.** Se pensaba desplegar el relleno de `tenant_id` en producción sobre SQLite antes del corte. Se descarta: obligaría a triggers de SQLite que chocan con los que ya llevan `tareas_outlook`, `notas`, `categorias` y `tareas` (cada `UPDATE` generaría historial en `api_cambios` y subiría `version`). El `tenant_id` se calcula **al cargar los datos en PostgreSQL** (fase 8), donde la carga no dispara triggers y cada inserción toma el despacho de la conexión (`app.tenant_id`). La 6a queda en: el modelo como dato, su verificación sobre una copia de producción, y la pertenencia de una persona a varios despachos.

### `app/bd/tenant.py` + `app/bd/tenant_modelo.json` (222 tablas)

| Clase | Tablas | De dónde sale el despacho |
|---|---:|---|
| propio | 105 | ya lleva `tenant_id` (en `fichajes` y `auditoria_eventos`, las filas sin él se rellenan desde la persona) |
| hija | 55 | hereda de su padre por clave foránea OBLIGATORIA (`correo_mensajes` → `correo_cuentas`, `notas_adjuntos` → `notas`…); si el padre no lo resuelve, de la persona |
| usuario | 27 | datos personales (`notas`, `tareas_outlook`, correo, IA…): el despacho en que se crearon; hoy el principal de la persona |
| referencia | 15 | catálogo global replicado: `tenants`, `usuarios`, `usuarios_tenants`, planes, reglas, perfiles y credenciales de la persona |
| local | 20 | solo en el coordinador: corpus jurídico compartido y registros técnicos globales |

`tests/test_tenant_modelo.py` obliga a clasificar cualquier tabla nueva (falla si el JSON se queda atrás) y comprueba que no hay ciclos y que cada hija tiene camino.

**Verificación sobre una copia de producción** (`sqlite3.backup` desde una conexión de solo lectura): 229 filas rellenadas, **segunda pasada 0**, sin discrepancias entre padres (`padres_en_desacuerdo` y `distinto_del_padre` a 0), triggers restaurados, `api_cambios` y `version` sin tocar. 42 de las 43 tablas con datos quedan con despacho en TODAS sus filas; la restante es `jur_auditoria` (7 de 9 eventos de plataforma: registrar políticas, habilitar fuentes), que se admite sin despacho. Las dos personas sin despacho de producción no tienen datos propios hoy.

### Una persona en varios despachos (y en varios tenants)

Tabla `usuarios_tenants (usuario_id, tenant_id)`, de referencia. **`usuarios.tenant_id` sigue siendo el despacho PRINCIPAL** y la aplicación entera sigue leyéndolo: no hay cambio de comportamiento. El principal figura siempre en la tabla (se rellena en `init_db`). Funciones nuevas en `db`: `tenants_de_usuario`, `es_miembro_de_tenant`, `anadir_usuario_a_tenant`, `quitar_usuario_de_tenant` (si era el principal pasa al siguiente) y `fijar_tenant_principal`. `asignar_tenant` sigue MOVIENDO a la persona (su único despacho) y `desasignar_tenant` la saca de todos; `borrar_tenant` pasa a los miembros al siguiente despacho que tengan.

Lo que **todavía no** existe (6c): el despacho ACTIVO de la sesión (selector), que `get_connection(despacho)` lo use en cada petición, y mover a la tabla de pertenencia los atributos que hoy son de la persona pero en realidad son del despacho (`supervisor_tenant`, `gestor_fichajes`, `custodio_certificados`, `tarifa_hora_centimos`).

### Decisiones que quedan para la 6b/6c

- **D14 (decidida 2026-10-24). Personas sin despacho** (operador de plataforma, usuario local) y eventos de plataforma: Citus no admite `NULL` en la columna de distribución, así que van al despacho reservado **`id = 0`, «Plataforma»**. Existe en el esquema de PostgreSQL (`app/bd/esquema_pg/07_semillas.sql`, `tenant.TENANT_PLATAFORMA`), no se puede borrar (`borrar_tenant(0)` lo rechaza) y ningún despacho nuevo puede tomar ese id (la identidad empieza en 1). `tenant.rellenar(por_defecto=TENANT_PLATAFORMA)` le asigna lo que no se deduce de la persona ni del padre. **No se crea en SQLite/producción**: aparecería en el listado de despachos del backoffice; en la 6c, los listados de despachos de PostgreSQL deben excluir el 0.
- Las inserciones llevarán `tenant_id bigint NOT NULL DEFAULT current_setting('app.tenant_id')::bigint` (Citus evalúa la función en el coordinador); RLS lo comprueba con `WITH CHECK`. Pendiente de probar en la 6b.

## Fase 6b: esquema multitenant y Citus (2026-10-24)

`scripts/migracion/generar_esquema_pg.py <base.db> --multitenant` genera, desde el esquema de SQLite y `tenant_modelo.json`, la variante `app/bd/esquema_pg/mt/`: `01_tablas` (+`tenant_id bigint NOT NULL DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint` en las 186 tablas distribuidas; PK `(tenant_id, …)`; todo UNIQUE con `tenant_id` delante), `02_indices`, `03_claves_foraneas` (compuestas entre distribuidas; simples hacia referencia), `04_vistas`, `05b_set_null`, `08_distribuir` y `09_rls`. `10_roles` y `05_triggers` (variante con `tenant_id`) son manuales. `esquema.crear_si_falta(conn, modo)`: `simple` (como hasta ahora), `multitenant` (sin Citus; sirve para el grueso de los tests, D12) y `citus` (distribuido, 16 shards). Construcción en Citus: ≈ 35 s; base vacía de 166 MB y 3.004 shards.

**Resultado**: 186 tablas distribuidas (todas colocalizadas), 18 de referencia, 10 locales; 186 políticas RLS; FK, triggers y vista creados; 10 pruebas en `tests/test_citus.py` sobre Citus real, todas en verde.

### Lo que Citus obligó a cambiar

| Problema | Solución |
|---|---|
| «cannot execute multiple utility events»: un mensaje con varias sentencias de definición | `ConexionPG.ejecutar_script(por_sentencias=True)` con `traduccion.dividir_sentencias` (respeta literales, comentarios y `$$…$$`) |
| `ON DELETE SET NULL` no se admite si la clave foránea incluye la columna de distribución (ni con lista de columnas) | clave foránea sin acción + trigger `BEFORE DELETE` generado en el padre que anula la columna de los hijos (`05b_set_null.sql`, 14 relaciones) |
| Triggers en tablas distribuidas | `SET citus.enable_unsafe_triggers = on` al crearlos (D7); sus consultas filtran por `tenant_id`; el historial `api_cambios` lleva el despacho de la fila |
| `comunicados` (destinatario opcional), `jur_fuentes` (catálogo) y `auditoria_control` (la leen los triggers en cada shard) | pasan a tablas de **referencia**; así `comunicados_cerrados` y `jur_fuente_despacho` no quedan apuntando a una tabla local o distribuida |
| Claves foráneas antes de distribuir (identidad + FK) | las FK van después de `create_distributed_table` (D9) |

**Roles** (`mt/10_roles.sql`, sin contraseñas: las fija quien despliega): `guilda_app` (NOBYPASSRLS: cada conexión ve y escribe solo su despacho) y `guilda_plataforma` (BYPASSRLS: backoffice, trabajadores, borrado de despachos). La aplicación no puede modificar ni borrar `auditoria_eventos`/`jur_auditoria` ni escribir en `tenants` y los catálogos.

### Viabilidad de las consultas existentes (el hallazgo principal)

`scripts/migracion/validar_sql_citus.py` planifica (PREPARE + EXPLAIN, sin ejecutar) las 1.747 sentencias de la aplicación contra Citus: **1.635 se planifican bien** (799 a un solo shard) y **112 (6 %)** no, en 33 ficheros (ya resueltas en la 6c): 61 «join requires repartitioning» y 45 «complex joins» —joins o subconsultas entre dos tablas distribuidas que no incluyen la igualdad de `tenant_id`—, 3 `UPDATE … SET tenant_id` (borrado de un despacho, mover una vista guardada) y 2 `INSERT … SELECT` entre distribuidas. 94 INSERT dejan que `tenant_id` lo ponga el valor por defecto de la conexión (funciona: Citus evalúa `current_setting` en el coordinador, probado). Un test (`PENDIENTES_CITUS = 112`) impide que aparezcan más.

**Cómo se arreglan (6c)**: añadir `AND a.tenant_id = b.tenant_id` a esos joins. SQLite no tiene `tenant_id` en la mayoría de esas tablas, así que el SQL no puede escribirse tal cual: o un ayudante `_bd.mismo_despacho('a', 'b')` que devuelva la condición en PostgreSQL y vacío en SQLite, o reescritura automática en `ConexionPG`. Se prefiere el ayudante (explícito, sin magia, lo verifica el validador).

### Pendiente
- 6c: despacho activo en la sesión y `get_connection(despacho)` por petición (sin él, las inserciones fallan por `tenant_id` NULL y las lecturas no ven nada: fallo seguro), las 112 consultas, los 3 `UPDATE tenant_id`, atributos por despacho (supervisor, gestor de fichajes, custodio, tarifa), listados de despachos sin el 0.
- `usuarios` y `tenants` (referencia) no tienen RLS: las ve cualquier conexión. Decidir en 6c qué ve cada despacho de las personas de otros.
- Prueba con Citus de varios nodos (fase 9).

## Fase 6c: la aplicación sobre el esquema multitenant (2026-10-24)

### Qué se ha hecho

| Pieza | Detalle |
|---|---|
| **Despacho de la conexión** (`app/bd/contexto.py`) | `en_despacho(t)`, `como_plataforma()` y, por petición, `fijar_para_la_peticion(tenant, persona)`. `db.get_connection()` lo lee: con despacho, conexión del rol de la aplicación (sujeto a RLS) y `set_config('app.tenant_id'/'app.usuario_id', …, true)` al abrir cada transacción; sin él, la de la plataforma (`BYPASSRLS`). Dos pools (`GUILDA_DATABASE_URL`, `GUILDA_DATABASE_URL_PLATAFORMA`). Las peticiones autenticadas SIEMPRE fijan un despacho (el 0 si la persona no tiene) |
| **Despacho activo y selector** | `session["tenant_activo"]`, ruta `POST /despacho/activo/<id>` (solo uno suyo), selector en el panel de cuenta solo si la persona tiene más de uno, cabecera `X-Despacho` para tokens de API. `usuarios_tenants` lleva `gestor_fichajes`, `supervisor_tenant`, `custodio_certificados` y `tarifa_hora_centimos` de cada despacho que no es el principal (`db.atributos_en_despacho`, `fijar_atributos_en_despacho`) |
| **RLS de personas** | `tenants`: solo el activo; `usuarios_tenants`: solo las del activo; `usuarios` y todo lo que cuelga de una persona (perfil, credenciales API, dispositivos…): se ve a quien pertenece al despacho activo y a uno mismo. Funciones `SECURITY DEFINER` (`usuario_visible`, `token_visible`) porque Citus no admite subconsultas en `CREATE POLICY` |
| **Reescritura de consultas** (`app/bd/citus.py`, necesita `pglast`) | Cuando `GUILDA_PG_CITUS=1`: añade `a.tenant_id = b.tenant_id` a los joins y subconsultas entre tablas distribuidas, completa los `INSERT … SELECT`, y en las conexiones con despacho añade `tenant_id = <despacho>` a CADA consulta (también subconsultas): Citus las resuelve en un solo shard. Un `INSERT … VALUES` sin `tenant_id` lo lleva explícito; en un trabajo sin despacho se deduce de la persona o del padre de la fila (modelo) |
| **Código cambiado** | listados de despachos sin el 0; `INSERT … SELECT` entre distribuidas → leer y reinsertar (2 sitios); la visión global del backoffice sin subconsultas correlacionadas; vistas guardadas (el despacho no cambia al editarlas); `SUM(<condición>)` en el backoffice; `COLLATE NOCASE`/`LIKE` del backoffice |
| **Borrado de un despacho** | en PostgreSQL se borra TODO lo suyo, también lo personal (`tenant.borrar_filas_de_tenant`): Citus no deja cambiar el `tenant_id` de una fila, así que ya no puede quedar «sin despacho» como en SQLite. Transacción en modo secuencial (`ConexionPG.modo_secuencial`) |
| **Vista** `tareas_participantes_todos` | lleva `tenant_id` y sus joins unidos por él; constantes de texto con tipo |

### Resultado medido

- Planificando contra Citus las **1.778 sentencias** de la aplicación y el backoffice (`validar_sql_citus.py --con-valores --con-despacho`), como las envía una conexión con despacho: **1.752 se resuelven en UN solo shard, 0 repartidas, 0 rechazadas**. Con una conexión de la plataforma (sin filtro de despacho) quedan 4 consultas de «participantes» (OR con una vista): se usan siempre desde peticiones con despacho.
- 13 pruebas sobre Citus real (`tests/test_citus.py`): aislamiento, claves compuestas, `SET NULL`/`CASCADE` por trigger, historial y auditoría, privilegios, visibilidad de personas, la aplicación entera con sus dos pools (rol sujeto a RLS y rol de plataforma), un trabajo que inserta sin despacho, y `db.borrar_tenant` completo.
- 5 pruebas de Flask+Kratos del selector (`tests/test_despacho_activo.py`) y 6 de la reescritura (`tests/test_bd_citus_reescritor.py`).

### Limitaciones conocidas

1. **Personas en varios despachos y listados de compañeros.** Unas 80 consultas que escogen «las personas de un despacho» filtran por `usuarios.tenant_id` (el despacho PRINCIPAL). Quien trabaja en un despacho que no es el suyo principal ve y escribe todo lo de ese despacho, pero no aparece en los selectores de responsable/compañeros de él (sí en el principal). No es un fallo de seguridad (la RLS manda), sino de integridad funcional; se arregla cambiando esas consultas por una pertenencia a `usuarios_tenants`.
2. **`backoffice.db` sigue siendo SQLite aparte.** Es la base PROPIA del backoffice (10 tablas: administradores, intentos de acceso, cobros, notas, seguimiento…), con `sqlite3` directo, que no pasa por esta capa. Migrarla es un trabajo pequeño pero distinto (otra base, sin `tenant_id`); queda en el plan para antes de retirar SQLite.
3. Las 89 inserciones que toman el despacho del contexto, en un trabajo en segundo plano, se atribuyen al despacho PRINCIPAL de la persona.
4. Pendiente de la fase 7: ejecutar la suite funcional completa contra PostgreSQL con el esquema multitenant (hoy se ha probado la capa, las consultas planificadas y los flujos clave).
