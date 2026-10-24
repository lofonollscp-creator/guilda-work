# Fase 12 — Estabilización y retirada de SQLite

Corte hecho el **2026-10-24 (12:34)**. Esta página es el calendario, los criterios y el plan de retirada. Contexto: `docs/adr-postgresql-citus.md`; operación: `docs/runbooks-postgresql.md`.

## 1. Mientras dure la observación (≥ 14 días: hasta el 2026-11-07)

| Cuándo | Qué | Cómo |
|---|---|---|
| Cada día | Panel *Salud* del backoffice en verde (sección «Base de datos»); correos de alerta | automático; los rojos llegan por correo |
| Cada noche | Copia base (02:15) y Restic (03:00) | `postgres-backup.timer`, `restic-backup.timer`; el panel Salud los vigila |
| **Cada lunes** | Revisión de estabilización | `postgres-revision.timer` (07:30) → correo si hay hallazgos; a mano: `scripts/revision_postgres.py` |
| Tras cada despliegue | Barridos de lectura: `scripts/humo_postgres.py` (web), `scripts/barrido_mcp.py` (MCP) y la API (token de solo lectura) — en el ensayo con `--rutas-get`; en producción solo lo de solo lectura | `scripts/probar.sh --ejecutar …` |
| Día 3 (2026-10-27) | Primera revisión a mano con tráfico de entre semana; mirar consultas por tiempo total y las que tocan todos los fragmentos | `guilda_py`-style (ver cabecera del script) |
| Día 7 (2026-10-31) | Simulacro de restauración con la configuración real y revisión de índices sin uso | `scripts/probar.sh --ejecutar scripts/simulacro_restauracion_pg.py` |
| Día 14 (2026-11-07) | **Decisión de retirada** (criterios abajo) | esta página |

**Reglas mientras tanto**
* **Nada de cambios de esquema** hasta cerrar la ventana de vuelta atrás (2026-10-26 12:34): la exportación inversa asume el esquema del corte. Después, los cambios van como migraciones (`app/bd/migraciones/`, `scripts/migrar_esquema_pg.py`).
* Al cerrar la ventana (≥ 48 h): borrar `data/vuelta/` si existe y anotar «vuelta atrás B cerrada». `data/pre-corte/` y los `registro.db`/`backoffice.db` congelados se conservan **30 días más** como último recurso.
* Los hallazgos de la revisión son orientaciones: no se borra un índice con menos de un ciclo completo de uso (un mes: cierres trimestrales y anuales aparte).

## 2. Criterios para retirar la ruta SQLite (todos)
1. ≥ 14 días desde el corte sin incidente de datos ni vuelta atrás.
2. Copia base diaria en verde 14 de 14 días y Restic limpio; **un simulacro de restauración posterior al corte en verde**.
3. Revisión semanal sin hallazgos abiertos (o con decisión escrita de aceptarlos).
4. Ningún error 5xx atribuible a la base de datos en los últimos 7 días.
5. Un mecanismo de migraciones probado en producción (al menos una migración real aplicada con `migrar_esquema_pg.py`) — hoy el mecanismo existe y está probado en pruebas, pero no ha corrido en producción.
6. Decisión de las personas responsables.

## 3. Plan de retirada (cada paso, un commit con las suites en verde)
1. **Congelar el esquema como fuente de verdad**: los ficheros de `app/bd/esquema_pg/` (hoy generados desde SQLite) pasan a ser la versión 1 a mano; el generador (`scripts/migracion/generar_esquema_pg.py`) y `tests/test_esquema_pg.py::test_los_ficheros_generados_estan_al_dia` se archivan. Desde aquí los cambios de esquema SOLO van como migración.
2. **El motor por defecto es PostgreSQL**: `bd.MOTOR` sin variable = `postgres`; los tests, igual (hoy `GUILDA_TEST_MOTOR=postgres` es la excepción).
3. **Quitar la rama SQLite** de `app/db.py` (`get_connection`, `init_db`, `SCHEMA`, `_asegurar_columna`…), de los módulos `app/db_*.py`, `backoffice/auth.py` y de la capa `app/bd/` (los `sqlite3.IntegrityError` pasan a `psycopg`); los **46 tests `solo_sqlite`** se borran (los de migración de esquemas viejos ya no tienen sentido).
4. **Retirar lo operativo**: Litestream (`deploy/litestream.*`), la copia diaria de `registro.db` (HOSTING §9.1), el paso de SQLite en `backup_restic.sh`, `scripts/exportar_a_sqlite.py` y `scripts/ensayo_corte_postgres.py` (la vuelta atrás ya no existe).
5. **Archivar** los SQLite congelados fuera del servidor (cifrados) y borrarlos del disco a los 30 días.

Tamaño del trabajo (medido hoy): **220** referencias a `sqlite3` y **83** a `PRAGMA`/`sqlite_master` en `app/`, 22 ficheros de `app/` que importan `sqlite3`, 27 ramas por motor (`bd.MOTOR`/`es_postgres`) y 17.859 líneas en `app/db*.py` + `app/bd/`.

## 4. Pendientes conocidos de la migración (no bloquean la retirada)
* **Personas en varios despachos y listados de compañeros**: ~80 consultas filtran por `usuarios.tenant_id` (el despacho principal); quien trabaja también en un segundo despacho no aparece en los selectores de ese segundo. No afecta mientras nadie esté en varios.
* Las 89 inserciones de trabajos en segundo plano se atribuyen al despacho principal de la persona.
* El RPO frente a la pérdida del servidor entero sigue siendo el de Restic (24 h) hasta que haya un destino externo para el WAL.
* PgBouncer sin probar (no hace falta con ~25 sesiones activas).
