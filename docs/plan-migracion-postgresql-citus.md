# Plan de migración a PostgreSQL + Citus (distribución por `tenant_id`)

Estado: **fases 0 a 4 completadas** (2026-10-23). Resultados en `docs/adr-postgresql-citus.md`.
Ejecutor: Claude (código, scripts, tests, documentación). Usuario: acciones de sistema, aprobaciones y ventana de corte.

## 0. Punto de partida (medido en el código)

- 210 tablas con `CREATE TABLE`; ~2.100 sentencias SQL, ~2.070 `.execute()` en 78 ficheros; 35 ficheros importan `sqlite3`.
- **Cobertura de `tenant_id`:** 103 tablas lo llevan, 47 solo tienen `usuario_id` y 60 no tienen ninguno (unas son catálogos globales —`jur_*`, `reglas_fiscales`, `planes_guilda`, `tenants`, `usuarios`— y otras son hijas que se aíslan a través de su padre: `correo_mensajes`, `correo_adjuntos`, `pausas`, `tarea_checklist`…).
- 95 `UNIQUE` y 345 `REFERENCES`. Citus exige que toda clave única/primaria de una tabla distribuida incluya la columna de distribución, y que las claves foráneas entre tablas distribuidas la incluyan también.
- 3 tablas FTS5 (`correo_fts`, `jur_fragmentos_fts`, `jur_fragmentos_privados_fts`), 149 usos de `rowid`, 131 de `lastrowid`, 44 `PRAGMA`.
- Pool de conexiones propio por hilo (`_ConexionCompartida` en `app/db.py`) y semántica de transacciones heredada (transacción implícita antes de DML).
- Hay modo empaquetado con PyInstaller (`sys._MEIPASS`) que usa SQLite local. Decisión abierta (D3).
- Servidor actual: 4 vCPU, 7 GB RAM, ya con ~25 contenedores. Citus **multinodo no cabe aquí**; se despliega **de un solo nodo** (todos los shards locales) y se añaden workers cuando haya más máquinas (el reequilibrado de shards no requiere reescribir la app).

## 1. Principios de ejecución

1. **Nada se corta hasta que todo esté verde en ensayo.** SQLite sigue siendo el motor de producción hasta la fase 11.
2. **Cada fase deja la suite completa en verde en SQLite**; desde la fase 3 también en PostgreSQL (matriz de dos motores). Se puede parar tras cualquier fase sin dejar el sistema roto.
3. **Los cambios de modelo para Citus (fase 6) se despliegan primero en SQLite**, en producción y antes del corte. Así se verifican con la app real y con vuelta atrás fácil.
4. Reglas de la sesión que se mantienen: pytest solo sobre copias aisladas (`scripts/probar.sh`), nunca contra el repo real; sin `git checkout` ni `stash` con otra sesión activa; commit y push solo cuando lo pidas; cambios de sistema (docker, systemd, env, paquetes) los ejecutas tú con comandos que te doy; nunca se muestran secretos de `/etc/guilda-work.env`.
5. Cada fase termina con: criterios de salida comprobables, entrada en la bitácora y actualización de `docs/` y `HOSTING.md`.

## 2. Fases

### Fase 0 — Inventario y decisiones (≈ 3-4 días)
- Script que clasifica las 210 tablas en: **distribuida** (propietaria de datos de un despacho), **de referencia** (catálogo pequeño y global), **local** (solo coordinador: corpus jurídico compartido, logs globales) e **hija a la que falta `tenant_id`**.
- Averiguar cómo se relacionan usuarios y despachos (¿un usuario puede estar en varios despachos?) porque decide el `tenant_id` de las 47 tablas con solo `usuario_id`.
- Lectura a fondo de `correo_cifrado.py`, `almacen_documentos.py`, `writable_schema`, `schema_version`, `secure_delete` y del flujo de borrado de datos del despacho.
- Línea base: tiempos de las 30 consultas más frecuentes, esperas de bloqueo, tamaño por tabla.
- **Entregables:** `docs/adr-postgresql-citus.md`, `docs/migracion-clasificacion-tablas.csv`, lista de consultas críticas.
- **Salida:** todas las tablas clasificadas y las decisiones D1-D5 cerradas.

### Fase 1 — Entorno de ensayo (COMPLETADA 2026-10-23; ver ADR)
- Imagen Docker propia: Citus + `pgvector` + `unaccent` + `pg_trgm`, con `Dockerfile` y `docker-compose.pg.yml` que escribo yo.
- Contenedor aislado (red y puerto propios, límite de memoria), sin tocar `guilda-work-postgres-*` existentes.
- `scripts/probar_pg.sh`: levanta una base de datos de plantilla, clona una por proceso de test y la destruye.
- **Salida:** `SELECT citus_version()` correcto y un clon de BD creado y borrado en menos de 2 s.

### Fase 2 — Capa de acceso a datos de dos motores (COMPLETADA 2026-10-23; ver ADR)
- Nuevo paquete `app/bd/`: conexión, pool, transacciones y fila tipo diccionario, con `DB_ENGINE=sqlite|postgres` (por defecto `sqlite`).
- Adaptador de parámetros `?` → `%s`, emulación de `lastrowid` mediante `RETURNING id`, equivalente de `executescript` y del `sqlite3.Row`.
- Se reproduce la semántica actual: transacción implícita antes de DML, cierre que devuelve al pool, aislamiento por hilo.
- Las 8 llamadas a `sqlite3.connect` y las 35 importaciones de `sqlite3` pasan a usar la capa.
- **Salida:** suite completa en verde en SQLite sin cambiar resultados; rendimiento sin regresión.

### Fase 3 — Dialecto SQL portable (COMPLETADA 2026-10-23, ver ADR; los errores de tipos y GROUP BY salen en las fases 4 y 7)
Barrido por módulos (`db.py`, `db_correo.py`, cada vertical, rutas, MCP y API), con funciones de apoyo en `app/bd/dialecto.py`:
- `INSERT OR IGNORE/REPLACE` → `ON CONFLICT`; `GROUP_CONCAT` → `string_agg`; `strftime`/`date('now')`/`julianday` → helpers de fecha (las fechas siguen guardadas como texto ISO para no tocar la lógica).
- `rowid` (149) → id explícito.
- Tipos estrictos: comparaciones texto/entero, `GROUP BY` completo, comillas, `LIKE` sin distinción de mayúsculas, `CAST`.
- `PRAGMA`: `foreign_keys` (siempre activo en PostgreSQL), `integrity_check`, `foreign_key_check`, `table_info` → `information_schema`; `secure_delete` y `wal_checkpoint` se eliminan o sustituyen.
- **Salida:** el 100 % de las consultas se ejecutan en los dos motores; suite en verde en ambos (matriz).

### Fase 4 — Esquema PostgreSQL (COMPLETADA 2026-10-23, ver ADR)
- Conversión de los 217 `CREATE TABLE` e índices: `INTEGER PRIMARY KEY` → `bigint GENERATED BY DEFAULT AS IDENTITY`, `BLOB` → `bytea`, `CHECK` y `DEFAULT` equivalentes. Se mantienen los 0/1 de las banderas.
- Migraciones aditivas idempotentes de las verticales (`esquema`) portadas y probadas dos veces seguidas.
- Comprobador que compara el esquema SQLite con el de PostgreSQL (tablas, columnas, nulos, únicos, FK).
- **Salida:** `crear_esquema()` en PostgreSQL deja el mismo modelo que en SQLite.

### Fase 5 — Búsqueda de texto y vectores (≈ 1,5-2 semanas)
- FTS5 → `tsvector` con configuración `spanish` + `unaccent`, índice GIN y columnas generadas; `bm25` → `ts_rank_cd`; mantener la estrategia AND con respaldo OR y la búsqueda por identificadores exactos.
- Correo y corpus jurídico (compartido y privado). Embeddings → `pgvector` con índice HNSW, filtrado por modelo.
- Evaluación comparada con `scripts/evaluar_juridico.py`: la calidad de recuperación no puede bajar respecto a SQLite.
- **Salida:** tests de búsqueda en verde en ambos motores y evaluación sin regresión.

### Fase 6 — Modelo multitenant para Citus (≈ 2-3 semanas)
- **6a (en SQLite, se despliega antes del corte):** añadir `tenant_id` a las 47 tablas con solo `usuario_id` y a las hijas que lo necesiten, con relleno desde el padre, y comprobaciones de que no hay filas huérfanas ni cruzadas entre despachos.
- **6b (esquema PostgreSQL/Citus):**
  - Claves primarias `(tenant_id, id)` y claves foráneas compuestas entre tablas distribuidas.
  - Los `UNIQUE` globales (token, email, etc.) se revisan uno a uno: incluir `tenant_id`, moverlos a tabla de referencia o resolverlos con una tabla de búsqueda.
  - Tablas de referencia: `tenants`, `usuarios`, catálogos. Corpus jurídico compartido: tabla local del coordinador (esquema `corpus`) para no replicar GB en cada nodo.
  - `create_distributed_table(..., 'tenant_id', colocate_with => 'tenants')` en todas las propias, con 16 shards (D6).
- **6c:** todas las consultas deben llevar el filtro de `tenant_id` para ser de un solo shard. Test automático que ejecuta las rutas principales y falla si una consulta toca varios shards sin motivo.
- **6d (opcional, recomendado): RLS** con `app.tenant_id` por conexión, como segunda barrera de aislamiento, sumada a los tests de `test_aislamiento`.
- **Salida:** `tenant_id` en toda tabla de datos de despacho, suite de aislamiento ampliada en verde y todas las tablas distribuidas colocalizadas.

### Fase 7 — Tests y CI (≈ 1,5 semanas, en paralelo con 5-6)
- Suite principal contra PostgreSQL **sin distribuir** (clon de plantilla por test); suite específica de Citus con plantilla de pocos shards y `ALLOW_CONNECTIONS false` al clonar (decisión D12). Objetivo de tiempo no peor que el 150 % del actual con `-n 3`.
- Pruebas específicas: bloqueos y concurrencia, transacciones entre tablas colocalizadas, reequilibrado.
- **Salida:** `scripts/probar.sh` y `scripts/probar_pg.sh` en verde en ambos motores.

### Fase 8 — Herramienta de migración de datos (≈ 1,5 semanas)
- `scripts/migrar_a_postgres.py`: lee `registro.db` y `backoffice.db`, convierte tipos, carga por lotes con `COPY`, reinicia las secuencias y ejecuta controles.
- Controles: recuento por tabla y por despacho, suma de control por columna, claves foráneas, huérfanos, tamaños de BLOB, búsqueda de texto equivalente.
- Re-ejecutable, con informe y sin escribir nunca en SQLite.
- **Ensayo con una copia de producción dentro del mismo servidor** (mismos permisos, sin sacar datos del VPS).
- **Salida:** migración de la copia completa sin discrepancias en 3 ensayos seguidos.

### Fase 9 — Rendimiento, concurrencia y escalado (≈ 1 semana)
- Prueba de carga con escritores concurrentes, el trabajador del BOE, correo y automatizaciones; dimensionado de pool y PgBouncer.
- Revisión de `EXPLAIN` de las 30 consultas críticas y de planes distribuidos.
- Ensayo local con **un worker adicional** y reequilibrado de shards para demostrar la vía de crecimiento (en contenedores).
- **Salida:** informe con latencias p95 y sin esperas de bloqueo relevantes.

### Fase 10 — Operación (≈ 1 semana)
- Copias: `pgBackRest` o WAL-G con archivado continuo (recuperación a un instante) más `pg_dump` cifrado en el flujo de Restic; **restauración de un solo despacho** y simulacro de restauración completa documentado.
- Monitorización: `postgres_exporter` hacia el Grafana/Loki existentes, alertas de retraso, espacio, bloqueos y conexiones.
- `HOSTING.md`, runbooks, variables (`DATABASE_URL`…), adaptación de las unidades `guilda-work`, `guilda-work-mcp` y `guilda-backoffice`.
- **Salida:** restauración probada y alertas disparando en un simulacro.

### Fase 11 — Corte a producción (ventana de unas horas, con tu aprobación)
1. Ensayo general completo (2 pasadas) con tiempos medidos.
2. Aviso a los despachos y modo mantenimiento (solo lectura).
3. Copia final de SQLite, exportación, importación, controles automáticos y pruebas de humo (acceso, tareas, correo, fichajes, facturación, asistente jurídico).
4. Cambio de `DB_ENGINE=postgres` y `DATABASE_URL` por ti, y reinicio de servicios.
5. **Vuelta atrás:** hasta 48 h con `scripts/exportar_a_sqlite.py` (exportación inversa PostgreSQL → SQLite) para no perder las escrituras posteriores al corte; SQLite original intacto como copia de seguridad.

### Fase 12 — Estabilización y retirada (≈ 2 semanas de observación)
- Vigilancia reforzada, ajuste de índices y parámetros.
- Retirada de la ruta SQLite del código de producción (sujeto a D3) y limpieza de adaptadores.
- Cierre del ADR, bitácora y hoja de ruta.

## 3. Calendario orientativo

Trabajando yo con tu revisión por fases: **entre 7 y 10 semanas de calendario** hasta el corte, más 2 de estabilización. Las fases 3, 5 y 6 son las que más pueden variar; el primer resultado de la matriz de tests (fase 3) permite afinar la estimación con datos reales. Cifra mía a partir de recuentos de código, no medida con un intento real.

## 4. Lo que solo puedes hacer tú

- Construir y arrancar la imagen Docker de Citus (fase 1) y, más adelante, los contenedores de producción.
- Cambios de `/etc/guilda-work.env` y de las unidades systemd; reinicios.
- Reservar disco y memoria (los 7 GB actuales son justos con ~25 contenedores: recomiendo asignar al menos 3 GB al contenedor de PostgreSQL o mover la base de datos a otra máquina).
- Aprobar la ventana de corte y avisar a los despachos.

## 5. Decisiones (cerradas el 2026-10-23, ver `docs/adr-postgresql-citus.md`)

- **D1.** Un usuario puede estar en varios despachos: tabla de pertenencia usuario↔despacho y despacho activo en sesión (fase 6).
- **D2.** SQLite se retira tras estabilizar (fase 12).
- **D3.** Mismo VPS, Citus de un solo nodo.
- **D4.** RLS activada como segunda barrera.
- **D5.** Fechas en texto ISO; conversión a `timestamptz` en una fase posterior independiente.

## 6. Riesgos principales

| Riesgo | Mitigación |
|---|---|
| Errores de tipo que solo aparecen al ejecutar cada consulta | Matriz de dos motores y barrido por módulos |
| Consultas sin `tenant_id` que se reparten por todos los shards | Test automático de planes y RLS |
| `UNIQUE` globales incompatibles con Citus | Revisión caso por caso en la fase 6 |
| Pérdida de calidad de búsqueda al dejar FTS5 | Evaluación comparada antes y después |
| Datos sucios en SQLite (tipos laxos) | Controles de la fase 8 y 3 ensayos |
| Falta de RAM en el VPS | Límites explícitos, medir en la fase 9, D4 |
| Pérdida de datos en el corte | Copia previa, exportación inversa 48 h, SQLite intacto |
