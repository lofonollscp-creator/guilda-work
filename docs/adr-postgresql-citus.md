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
4. (Resuelto en la fase 7: la suite completa pasa contra PostgreSQL multitenant.)

## Fase 7: la suite completa contra PostgreSQL (2026-10-24)

`GUILDA_TEST_MOTOR=postgres GUILDA_TEST_PG_URL=postgresql://…/postgres scripts/probar.sh -n 3` ejecuta los 4.356 tests con el esquema **multitenant** (PostgreSQL sin distribuir, decisión D12). `tests/conftest.py` crea UNA plantilla por proceso (esquema + los datos de la plantilla de SQLite cargados con `app/bd/migrar_datos.py`) y cada test trabaja en un clon (`CREATE DATABASE … TEMPLATE`). Evolución: 956 fallos en la primera pasada → 243 → 104 → 19 → 1 → 0 (41 tests saltados, ver abajo).

### Causas encontradas y arreglos (todos válidos también en SQLite)

| Causa | Arreglo |
|---|---|
| `ON CONFLICT (a, b)` sin `tenant_id`: las claves únicas del esquema multitenant lo llevan delante (347 fallos) | `citus.reescribir_conflicto` lo antepone al objetivo (se aplica en `traduccion.preparar`) |
| `INSERT OR IGNORE` no se podía reescribir (pglast no lo entiende) y la fila se quedaba sin `tenant_id` | `traduccion._ignorar_a_on_conflict` lo convierte antes de los reescritores |
| `tenant_id` NULL = «de toda la plataforma» en SQLite; en PostgreSQL es el despacho 0 «Plataforma» | los parámetros `tenant_id` de un INSERT pasan por `COALESCE(?, 0)`; los lectores comparan con `COALESCE(tenant_id, 0) = 0` (webhooks, comunicados, mantenimiento, fichajes); `crear_webhook` devuelve `None` |
| `executemany` con lista vacía / despacho deducido de la primera fila | vacía no ejecuta; la primera fila decide el despacho |
| `NUMERIC` llegaba como `Decimal` | cargador psycopg: float si tiene decimales, entero si no (`SUM(entero)`) |
| `create_function("plano")` | no-op si la función existe en PostgreSQL |
| `GROUP BY` incompleto (SQLite lo admite) en 4 consultas, ordenaciones con empates | columnas añadidas; desempate por `id` |
| `except sqlite3.IntegrityError` en `backoffice/datos.py` | `ErrorIntegridad` (tupla de ambos motores); tests con `ErrorIntegridad`/`ErrorBD` |
| Fugas de contexto (despacho activo) de un test al siguiente | `conftest` lo reinicia por test |
| `PRAGMA table_info` en `openapi.py` | `bd.columnas_de_tabla` (equivalente con `information_schema`) |
| Borrado de un despacho: orden de las tablas | orden por las claves foráneas reales (`tenant._orden_de_borrado`) |

### Tests marcados `solo_sqlite` (41, se saltan en el modo PostgreSQL)

Comprueban algo propio de SQLite: migraciones de su esquema (`DROP TRIGGER`, `sqlite_master`, `BLOB`), `EXPLAIN QUERY PLAN`, el archivo `.db` (backup, cifrado), el pool de conexiones de SQLite, `set_trace_callback`, FTS5 directo (`… MATCH`; la búsqueda en PostgreSQL la cubre `tests/test_busqueda_pg.py`), y tres que fijan una diferencia deliberada: en PostgreSQL la clave foránea compuesta impide enlazar un cliente de otro despacho, y borrar un despacho borra también lo personal creado en él. Tres más trabajan con su propia base de PostgreSQL (esquema simple) y se ejecutan en el modo normal con `GUILDA_TEST_PG_URL`.

### Pendiente

- Aislamiento sobre Citus real: `tests/test_citus.py` (13) sigue pasando; la suite principal NO se ejecuta distribuida (D12).
- CI: falta un `scripts/probar_pg.sh` que levante el contenedor de ensayo y lance la suite en ambos motores.

## Fase 8: herramienta de migración de datos (2026-10-24)

`scripts/migrar_a_postgres.py --origen data/registro.db --url postgresql://…/gw_ensayo1 --esquema citus --recrear-base --informe informe.json` (código en `app/bd/migrar_datos.py` y `app/bd/verificar_migracion.py`, tests en `tests/test_migracion_datos.py`).

### Qué hace
- **Solo lee SQLite**: abre `registro.db` en modo de solo lectura, la copia con la API de copia de SQLite (coherente aunque haya WAL) y trabaja sobre esa copia temporal, a la que añade el `tenant_id` que falta (`tenant.rellenar`, lo no deducible va al despacho 0 «Plataforma»).
- **Carga con `COPY`** por lotes de 5.000, en el orden de las claves foráneas REALES de la base de destino (`orden_de_carga`; el del modelo no bastaba: `certificados` → `clientes_fiscales`). Reinicia las secuencias de identidad (máximo + 1).
- **Triggers**: en PostgreSQL llano basta `session_replication_role = replica`; en Citus ese ajuste no llega a los fragmentos (el registro de cambios duplicaba `api_cambios`), así que se desactivan los triggers de usuario tabla a tabla (`citus.enable_unsafe_triggers`) y se reactivan en un `finally`.
- **Bytes NUL**: PostgreSQL no los admite en `text`. Se quitan al cargar y se anotan (`nul_eliminados`; en la copia de producción: 2 filas de `correo_mensajes.cuerpo_html`). La suma de control compara contra lo que se carga.
- **Pertenencias**: una base anterior a `usuarios_tenants` no la trae rellena; se crea la fila del despacho principal de cada persona (lo que hace `init_db` en SQLite). Sin ello el RLS de `usuarios` no deja ver a los compañeros.
- **Re-ejecutable**: `--recrear-base` borra y crea la base (solo nombres `gw_*`/`ensayo*`, o `--forzar`); sin él se niega si ya hay despachos. Código de salida 0 / 1 (discrepancias) / 2 (error). El informe JSON (0600) lleva recuentos, no datos.

### Controles (todos tras la carga)
Recuento por tabla y por despacho · suma de control por columna (hash de 64 bits sumado: no depende del orden; dice tabla y columna) · tamaño total de los BLOB · filas huérfanas (claves foráneas) · secuencias por detrás del máximo · pertenencias · **RLS**: con el rol `guilda_app` y un despacho fijado cada tabla devuelve exactamente sus filas (159 comprobaciones) · **búsqueda**: 25 palabras reales por índice dan las mismas filas en FTS5 y en tsvector. Los tests provocan un valor cambiado, una fila perdida y un hijo sin padre, y comprueban que se delatan.

### Ensayos con una copia de producción (dentro del VPS, sin sacar datos)
`registro.db` de 68,9 MB (221 tablas, 18.635 filas, 1 despacho con datos + 7 filas de «Plataforma»), sobre el contenedor de ensayo con **Citus**: 3 ensayos seguidos con `--recrear-base`, todos «todo cuadra» (≈56 s cada uno: 31 s de esquema Citus, 24 s de carga —`jur_fragmentos` 9 s—, 13 s de controles); además una pasada sobre el esquema multitenant llano (15 s). Informes en `data/pg-ensayo/fase8-ensayo*.json`. Las bases de ensayo se borraron al terminar (llevaban una copia de datos reales).

### Pendiente
- **`backoffice.db`** (10 tablas, `sqlite3` directo) no se migra: hay que pasar su código por la capa `app/bd` o decidir que sigue siendo SQLite (D2 lo retira).
- La copia de producción es pequeña (un despacho): los tiempos para muchos despachos se medirán en la fase 9 con datos sintéticos.
- La exportación inversa (`scripts/exportar_a_sqlite.py`) es de la fase 11.

## Fase 9: rendimiento, concurrencia y escalado (2026-10-24)

Herramienta: `scripts/probar.sh --carga --motor postgres --url postgresql://guilda:ensayo@127.0.0.1:55432/postgres --despachos 30 --usuarios 90 --vencimientos 30000 --segundos 60 --pausa 3 --fondo [--procesos 3] [--explicar] [--esquema multitenant]` (`scripts/prueba_carga.py`). Siembra los datos en SQLite, los **migra con la herramienta de la fase 8** a una base Citus, y recorre la aplicación real (Flask, mismas pantallas y 15 % de escrituras) con el rol **sin privilegios** `guilda_app` (RLS activa) y 30 despachos; además, el trabajador del BOE (normas y fragmentos), la sincronización de correo y las pasadas de automatizaciones/tareas recurrentes. Vigila las esperas de bloqueo y los interbloqueos, recoge de `pg_stat_statements` el tiempo que ve el servidor y hace `EXPLAIN (ANALYZE)` de las 30 consultas más costosas.

### Hallazgos que la carga destapó (los cuatro eran invisibles con una sola conexión y los tests de la fase 7)
1. **RLS + unión con `usuarios` = error 500.** La política de `usuarios` llama a `usuario_visible()`, que lee `usuarios_tenants`; al unir una tabla distribuida con `usuarios` la función se evalúa DENTRO de la consulta del fragmento y Citus la rechazaba («cannot execute a distributed query from a query on a shard»). Las funciones solo leen tablas de **referencia**, así que se les permite la ejecución anidada (`SET citus.allow_nested_distributed_execution = on` en la propia función, no en el rol). Generador y `09_rls.sql` actualizados; test de regresión en `tests/test_citus.py`.
2. **`BEGIN IMMEDIATE` global.** En PostgreSQL se traducía a un bloqueo consultivo ÚNICO: todos los escritores de todos los despachos hacían cola (657 esperas «advisory» y 59 interbloqueos en un minuto). Ahora el bloqueo es **por despacho** (`pg_advisory_xact_lock(clave, despacho)`).
3. **Escribir en tablas de referencia serializa a todos los escritores.** Citus toma un bloqueo exclusivo del fragmento replicado en cada escritura (`usuario_perfil`, `usuarios.ultimo_acceso`…) y lo mantiene hasta el commit: en el arranque en frío (90 primeras visitas a la vez) la media de un `INSERT` en `usuario_perfil` fue de **1,0 s** y hubo interbloqueos distribuidos. En régimen estable no hay escrituras en tablas de referencia (medido: 0 por minuto; solo el alta de una fuente jurídica), pero **la regla queda escrita: nada en la ruta caliente de una petición debe escribir en una tabla de referencia**. La herramienta ahora cuenta esas escrituras y calienta la primera visita (`--sin-calentar` mide el arranque en frío).
4. **Sin índice en `usuarios(tenant_id)`, la política evalúa una función por CADA persona de la plataforma** antes de filtrar por despacho (cada llamada ≈ 50–100 µs: lectura de compañeros 21,8 ms de media con 90 personas; con 50.000 serían segundos). Con `idx_usuarios_tenant` el plan usa el índice y la función se evalúa solo en las filas del despacho (3,6 ms). Índice creado en `init_db` y regenerados los ficheros del esquema.

### Cifras (90 personas, 30 despachos, 60 s, 15 % de escrituras, trabajos de fondo; VPS de 4 núcleos compartido con ~25 contenedores)
| Configuración | Peticiones/s | Peor p95 de pantalla | Errores | Esperas de bloqueo / interbloqueos |
|---|---|---|---|---|
| SQLite, 1 proceso (la instalación actual) | 19 | 6,9 s | 0 | – |
| SQLite, 3 procesos | 28 | 0,12 s | 0 | – |
| Citus, 1 proceso, sin los arreglos 1–2 (prueba corta de 10 personas: 33 de 69 peticiones con HTTP 500) | – | – | 33 × HTTP 500 | – |
| Citus, 1 proceso, con el hallazgo 1 corregido y sin los demás | 22 | 5,7 s | 0 | 18 de 248 muestras (hasta 39 sesiones esperando) / 40 |
| **Citus, 1 proceso, con los arreglos** | 23 | **2,2 s** | **0** | **0 / 0** |
| **Citus, 3 procesos, con los arreglos** | 26 | **1,2 s** | **0** | **0 / 0** |
| PostgreSQL llano (multitenant sin distribuir), 1 proceso | 25 | 2,1 s | 0 | 0 / 0 |

Cómo leerlo: con un proceso de Python (como hoy, 16 hilos de waitress) el límite es el GIL, no la base de datos: SQLite y PostgreSQL se parecen, y PostgreSQL gana en la cola larga porque no serializa escritores. Con varios procesos SQLite es más rápido en latencia pura (consultas en el mismo proceso) y PostgreSQL ya no se satura. **El servidor ve ≈ 2.200 sentencias/s (≈ 95 por petición) con 0,64 ms de media y 100 % de aciertos de caché**; en PostgreSQL llano la media es 0,12 ms: **Citus de un nodo cuesta ≈ 5× más CPU de servidor por sentencia** (el planificador distribuido), a cambio de la vía de crecimiento. Las sentencias preparadas (`GUILDA_PG_PREPARAR=3`) no lo compensan (−6 % de tiempo de servidor) y quedan desactivadas por defecto (PgBouncer).

### Consultas (EXPLAIN de las 30 más costosas, ya con RLS)
Todas las de la aplicación van a **un solo fragmento** (`Task Count: 1`) y ninguna recorre en secuencial una tabla grande; el tiempo de ejecución en el servidor es ≈ 1 ms (el resto de lo que ve Python es espera del GIL). La única con 16 fragmentos era una llamada de la propia herramienta sin despacho. Candidatas a mejorar (no urgentes): ≈ 95 sentencias por pantalla, con la misma fila leída varias veces (`usuarios` por id ×1,5, `tenants`, `usuario_perfil`, idioma, `onboarding_visible`); una memoización por petición ahorraría ≈ 8 por pantalla.

### Dimensionado del pool
Con 90 personas en un proceso: pool 4 → p95 2,9 s; 8 → 2,6 s; 16 → 2,5 s; 20 → 2,2 s; el servidor llegó a 9, 14, 20 y 19 sesiones activas. Recomendación: **`GUILDA_PG_POOL_MAX = hilos de waitress (16) − 4 = 12` por proceso y rol**, y `max_connections` ≥ suma de los pools de todos los procesos (web, MCP, backoffice, trabajos) + 20. **PgBouncer no hace falta todavía** (≈ 25 sesiones activas); el cliente ya es compatible (sin sentencias preparadas, `SET LOCAL` dentro de la transacción).

### Ensayo con un segundo nodo (la vía de crecimiento funciona)
Contenedor `guilda-pg-ensayo-worker` (misma imagen, 1 GB) unido a la base de la prueba de carga (3.000 fragmentos de 30 despachos): `scripts/pg_ensayo_worker.sh unir|reequilibrar|drenar|estado` y `scripts/pg_ensayo_rebalanceo.py`, que mantiene 12 hilos leyendo y escribiendo con el rol `guilda_app` (RLS) mientras el coordinador mueve fragmentos.
| Operación bajo tráfico | Duración | Errores | Escrituras confirmadas / perdidas | p95 durante (máx.) |
|---|---|---|---|---|
| Reequilibrar 3.000 fragmentos hacia el worker (1.516 / 1.506) | 150–200 s | **0** | 42.229 / **0** | 10 ms (1,5 s) |
| Drenar el worker (todo vuelve al coordinador) | 146 s | **0** | 41.111 / **0** | 9 ms (1,8 s) |
Las uniones con `usuarios` (política con función) funcionan con el fragmento en el worker (30 de 30 despachos). Tres hallazgos operativos:
1. **Los nodos necesitan autenticarse entre sí con el MISMO rol de la sesión** (`guilda_app`, `guilda_plataforma`, el de las migraciones): Citus no admite `password` en `citus.node_conninfo`. Sin ello, en cuanto un fragmento se mueve, 27.418 de 99.297 operaciones fallaron con «ConnectionFailure … no password supplied». En el ensayo se resolvió con un `.pgpass` del usuario `postgres` en cada nodo; en producción, `.pgpass` o `pg_hba` por red privada/certificados. **Runbook de la fase 10: añadir un nodo = crear la base y las extensiones, `.pgpass` con los tres roles, `citus_add_node`, `citus_rebalance_start`.**
2. **Toda tabla distribuida necesita clave primaria** (la replicación lógica con la que se mueven los fragmentos): `tenants_herramientas_ocultas` solo tenía `UNIQUE`. Ahora es `PRIMARY KEY` (SQLite y esquemas regenerados) y un test lo vigila.
3. Un nodo drenado queda con `shouldhaveshards=false`; para reutilizarlo hay que ponerlo a `true` antes de reequilibrar.

### Pendiente de la fase 9
- PgBouncer sin probar (haría falta descargar su imagen); no hace falta hoy.
- Limpieza del ensayo: `scripts/pg_ensayo_worker.sh destruir` y `scripts/pg_ensayo.sh borrar gw_carga` cuando no se necesiten.

## Fase 10: operación (2026-10-24)

### Qué se ha hecho
| Pieza | Fichero | Para qué |
|---|---|---|
| Contenedor de producción | `docker-compose.postgres-app.yml` | PostgreSQL 17 + Citus de un nodo con la configuración probada: archivo continuo de WAL (`archive_timeout=300` → RPO ≤ 5 min), `wal_level=logical`, `data-checksums`, registro de esperas de bloqueo, `max_connections=200`; escucha solo en `127.0.0.1:5433`; se une a la red del stack para que Grafana lo vea. Nombre `guilda-work-postgres-app`: Restic lo encuentra y le hace su `pg_dumpall`. |
| Copias físicas | `scripts/backup_postgres.sh` (`base`, `limpiar`, `estado`, `todo`) + `deploy/postgres-backup.{service,timer}` (02:15) | `pg_basebackup` + `citus_create_restore_point` + comprobación de lectura, retención de 7 copias y del WAL desde la más antigua (`pg_archivecleanup`), estado para el panel Salud. Se niega a escribir en el disco principal. |
| Restauración | `scripts/restaurar_postgres.sh` (`instancia`, `volumen`, `quitar`) | Recupera a un instante (hora o punto con nombre) o hasta el final del WAL en una **instancia aparte** o en un **volumen nuevo**; nunca toca producción. |
| Un solo despacho | `app/bd/despacho_copia.py` + `scripts/copia_despacho.py` | Exporta/importa un despacho (COPY binario por tabla + manifiesto con sumas de control); `--reemplazar` borra solo ese despacho; la auditoría se completa sin borrar. Probado en PostgreSQL llano y en Citus. |
| Monitorización | `app/salud_postgres.py` → panel Salud (correo con el vigilante de siempre) · `deploy/grafana-{datasource,dashboard}-postgres` | Conexiones, archivo de WAL, copia base, esperas de bloqueo, transacciones olvidadas, nodos de Citus, ranuras de replicación. Rol de solo lectura `guilda_monitor` (`pg_monitor`) para Grafana; `guilda_plataforma` también tiene `pg_monitor`. Las 18 consultas del panel de Grafana se probaron con ese rol. |
| Documentación | `HOSTING.md` §3 (variables) y §9.4, `docs/runbooks-postgresql.md` | Puesta en marcha, RPO/RTO, 9 runbooks. Las unidades systemd esperan a `docker.service`. |
| Simulacro | `scripts/simulacro_restauracion_pg.py` (informe en `data/pg-ensayo/simulacro-restauracion.json`) | Todo lo anterior de extremo a extremo en contenedores desechables. |

### Resultado del simulacro (datos sintéticos de 3 despachos, ≈ 10 MB)
Instancia con la configuración de producción → copia base (4,7 s, 17 MB) → dos copias más y retención a 2 (WAL 8 → 6 segmentos, la más antigua conservada sigue siendo restaurable) → actividad, punto de restauración `antes_del_desastre` → **desastre** (se borra todo lo del despacho 1 y las notas del 3; el 2 sigue escribiendo) → recuperación a un instante **por punto, por hora y desde la copia base más antigua**: las tres dejan los tres despachos exactamente como estaban (5,4–5,8 s) → se exportan el 1 y el 3 de la instancia recuperada y se importan en la viva (1,5 s + 2,9 s): los dos vuelven, **el 2 conserva sus 30 notas posteriores**, y la comprobación de sumas de control del importador no ve diferencias → alertas con el rol real de la plataforma: sin tocar nada todo está verde; con el destino del WAL ilegible el panel pone **rojo** el archivo de WAL («falló hace 0 s, 1 segmento esperando») y vuelve a **verde** al arreglarlo; una copia base de hace 4 días sale **roja**.

### Decisiones y hallazgos
1. **Sin pgBackRest/WAL-G.** El plan los citaba; se ha hecho con `pg_basebackup` + archivo de WAL nativo + `pg_archivecleanup` porque no añade ninguna dependencia que descargar ni imagen que reconstruir, y todo se pudo probar de extremo a extremo hoy. Lo que pgBackRest daría de más (copias incrementales/diferenciales, cifrado propio, verificación de páginas, paralelismo) se vuelve relevante con bases de varias decenas de GB; el cambio sería sustituir `backup_postgres.sh`/`restaurar_postgres.sh` y el `archive_command`, sin tocar el resto.
2. **Lo dado con `-c` en la línea de órdenes manda sobre `ALTER SYSTEM`** (además, `pg_reload_conf` avisa de que `shared_preload_libraries` no se puede cambiar en caliente, porque la imagen lo fija en su postgresql.conf): para cambiar `archive_command` en caliente no sirve `ALTER SYSTEM`; hay que cambiar el compose y recrear el contenedor (el simulacro rompe el archivado quitando permisos al destino).
3. **`pg_dump`/`pg_dumpall` sobre Citus** vuelcan los datos de las tablas distribuidas (vía COPY por el coordinador) pero no su distribución: sirven de red de seguridad lógica, no de recuperación rápida. Por eso la recuperación es física (WAL) + por despacho.
4. **Citus y la recuperación a un instante**: en un nodo basta el WAL; con varios nodos hay que recuperar todos hasta el mismo punto de restauración de Citus, que cada copia base crea (`base_AAAAMMDD-HHMMSS`). Con varios nodos el simulacro no se ha ejecutado (un nodo).
5. **Pendiente de la fase 11:** crear de verdad el contenedor y la carpeta de copias en el servidor (acción de administración), fijar las contraseñas de los roles fuera del repositorio, y decidir qué pasa con `backoffice.db` (sigue en SQLite: su copia sigue siendo la de §9.1/9.2). El RPO frente a la pérdida del servidor entero sigue siendo el de Restic (24 h) mientras no haya un destino externo para el WAL.

## Fase 11: corte a producción — preparación y ensayo general (2026-10-24)

La ejecución del corte la hace una persona del equipo cuando decida (sin hora fijada): aquí queda todo lo que hace falta, ensayado. **Runbook: `docs/runbook-corte-postgres.md`.**

### `backoffice.db` migrada
Las 10 tablas del backoffice (administradores con 2FA, intentos de acceso, auditoría de sus acciones, cobros, notas, seguimiento…) pasan al **esquema `backoffice`** de la misma base de datos (`app/bd/esquema_pg/11_backoffice.sql`), no distribuido. Solo las toca un rol propio, **`guilda_backoffice`** (sin acceso a los datos de los despachos; ni `guilda_app` ni `guilda_plataforma` ven el esquema; la auditoría del backoffice es de solo anexado). `backoffice/auth.py:conectar()` devuelve la conexión de ese rol con `search_path = backoffice, public`, así que el código del backoffice no cambió una línea de SQL; los 11 ficheros de tests del backoffice pasan contra PostgreSQL sin modificar. `migrar_datos.copiar_backoffice` carga la base (con recuentos y sumas de control) y la herramienta de migración la toma de la carpeta de `registro.db`.

### Vuelta atrás: exportación inversa PostgreSQL → SQLite
`scripts/exportar_a_sqlite.py` (`app/bd/exportar_sqlite.py`) crea `registro.db` y `backoffice.db` **nuevos** con el esquema de SQLite (`init_db`: índices, triggers, FTS5) y les carga lo que hay en PostgreSQL, comprobando cada tabla (filas y suma de control por columna), `integrity_check` y `foreign_key_check`. Detalles: el `tenant_id` que PostgreSQL añadió se descarta donde SQLite no lo tenía; el despacho 0 «Plataforma» vuelve a ser NULL; los triggers de SQLite alimentan los índices FTS5 al insertar y las tablas que otros triggers rellenan (`api_cambios`, `tarea_clientes`) se vacían y recargan al final. **Test de ida y vuelta**: SQLite → PostgreSQL → SQLite devuelve exactamente lo mismo, tabla por tabla, y lo escrito en PostgreSQL entre medias llega a SQLite (incluida la búsqueda de texto).

### Herramientas del corte
`scripts/corte_preflight.sh` (comprobaciones previas de solo lectura, sin contraseñas en pantalla; ya delata lo que falta en este servidor) · `scripts/humo_postgres.py` (pantallas de cada persona sin 5xx, escritura de prueba deshecha por despacho, búsqueda, backoffice, nodos de Citus, archivo de WAL, aislamiento por despacho con el rol de la aplicación, y recuentos por tabla comparables entre motores) · `scripts/migrar_a_postgres.py` (ahora también prepara una base existente: extensiones y coordinador de Citus; la URL del superusuario puede venir de `GUILDA_PG_ADMIN_URL`).
La contraseña del superusuario va en `/etc/guilda-pg-admin.env` (modo 600), no en `/etc/guilda-work.env`: los 8 servicios que leen este último no deben verla. Las herramientas se lanzan con `guilda_py` (entorno de producción + usuario `guilda`).

### Ensayo general (`scripts/ensayo_corte_postgres.py`)
Siete pasos por pasada, con una copia de los datos reales y en una base de ensayo con Citus (`gw_corte`, borrada al terminar): copia final → humo SQLite → migración (con controles) → humo PostgreSQL con recuentos iguales a SQLite → «el día después» (la aplicación escribe notas, tareas y una nota de administración sobre PostgreSQL) → **vuelta atrás** (exportación inversa) → humo sobre el SQLite recuperado (mismos recuentos que PostgreSQL y las escrituras presentes).

| | Datos reales (69 MB, 1 despacho) — 2 pasadas | Sintético (90 personas, 30 despachos, 100.000 filas) |
|---|---|---|
| Migración con controles | 56 s / 55 s | 68 s |
| **Ventana con la plataforma parada** | **63 s / 63 s** | 150 s |
| **Vuelta atrás (exportar a SQLite)** | **10,4 s / 10,6 s** | 21 s |
| Resultado | todo correcto, 0 discrepancias | todo correcto |

Informes en `data/pg-ensayo/ensayo-corte-*.json`.

### Hallazgos
1. **El corte exige desplegar antes el código nuevo con SQLite** (paso 0 del runbook): la `registro.db` de producción aún no tiene `usuarios_tenants` ni el resto del esquema nuevo, que crea `init_db()` al arrancar; el preflight lo comprueba. (La herramienta de migración también cubre una base antigua rellenando las pertenencias.)
2. **Las herramientas que importan la aplicación necesitan la clave del llavero de correo** (`GUILDA_SECRET_KEY`, solo legible por root): sin ella `init_db()` falla con «MAC check failed». De ahí la función `guilda_py` del runbook (entorno de producción + `runuser` como `guilda`), comprobada en este servidor sin imprimir ningún secreto.
3. **Un `tenant_id` NULL en SQLite es el despacho 0 en PostgreSQL**: ya tratado en la fase 7; la exportación inversa lo devuelve a NULL donde la columna lo admite (ninguna fila queda en «Plataforma» en la copia real).

### Pendiente (acciones tuyas, sin fecha)
Ejecutar el runbook: desplegar el código nuevo con SQLite, crear la carpeta de copias en el otro disco y el fichero `/etc/guilda-pg-admin.env`, levantar el contenedor, `sudo scripts/corte_preflight.sh` (0 fallos), y el corte. La fase 12 (estabilización y retirada de SQLite) empieza cuando el corte esté hecho.
