# Retirada de SQLite: plan ejecutable

Completa el punto 3 de `docs/fase12-estabilizacion.md`. **No se ejecuta antes de la decisión del 2026-11-07** (todos los criterios de la sección 2 de esa página, incluida la decisión escrita de las personas responsables): quitar la rama SQLite elimina también la vuelta atrás.

Las cifras salen de `python scripts/migracion/inventario_sqlite.py` (se repite al empezar cada paso): hoy **266** usos de `sqlite3`, **122** de `PRAGMA`/`sqlite_master`, **46** ramas por motor y **108** de FTS5/`MATCH` repartidos en **93** ficheros, y **37** ficheros de test marcados `solo_sqlite`.

## Orden de los pasos (cada uno, un commit con las suites en verde; se puede parar tras cualquiera)

| # | Paso | Qué toca | Cómo se comprueba |
|---|---|---|---|
| 1 | Congelar el esquema como fuente de verdad | `app/bd/esquema_pg/` pasa a ser la versión 1 a mano; se archivan `scripts/migracion/generar_esquema_pg.py` y `test_esquema_pg.py::test_los_ficheros_generados_estan_al_dia`. Desde aquí, los cambios de esquema SOLO como migración (`app/bd/migraciones/`) | `scripts/migrar_esquema_pg.py --estado` y la suite PG |
| 2 | PostgreSQL como motor por defecto | `bd.MOTOR` sin variable = `postgres`; `tests/conftest.py` y `scripts/probar.sh` levantan el PostgreSQL de ensayo siempre (hoy solo con `GUILDA_TEST_MOTOR=postgres`). La suite deja de funcionar sin Docker: hay que decirlo en `CLAUDE.md`/README | suite completa en PG |
| 3 | Quitar lo operativo de SQLite | `deploy/litestream.*`, copia diaria de `registro.db` (HOSTING §9.1), paso de SQLite en `scripts/backup_restic.sh`, `scripts/exportar_a_sqlite.py`, `app/bd/exportar_sqlite.py`, `scripts/ensayo_corte_postgres.py` | panel Salud en verde; Restic limpio |
| 4 | Quitar la rama SQLite del código | de más a menos usos: `app/db.py` (`SCHEMA`, `init_db`, `_asegurar_columna`, 27 PRAGMA), `db_correo`, `db_plataforma`, `db_tareas`, `db_fiscal`, `backoffice/auth.py` y el resto del inventario; `sqlite3.IntegrityError` → `ErrorIntegridad`. FTS5 (`app/bd/traduccion.py`, `app/juridico/busqueda.py`) queda solo con la ruta PostgreSQL | inventario a cero; suite PG |
| 5 | Borrar los tests `solo_sqlite` y los de migración de esquemas viejos | 37 ficheros (ver `--json`); las migraciones de esquema pasan a probarse con `tests/test_*migracion*_pg.py` | `pytest -m solo_sqlite` sin resultados |
| 6 | Archivar los SQLite congelados | `data/pre-corte/`, `registro.db`, `backoffice.db`: copia cifrada fuera del servidor y borrado del disco a los 30 días del corte | anotado en la bitácora |

## Riesgos conocidos
* **El desarrollo local deja de funcionar sin Docker.** Los pasos 2 y 4 suben la barrera de entrada; conviene una imagen de PostgreSQL ya construida (`guilda-work-citus:ensayo`) y documentarlo.
* **`app/db.py` mezcla esquema y migraciones SQLite viejas** (`_asegurar_columna`): antes del paso 4 hay que comprobar que ninguna base real depende de ellas (`SELECT max(version) FROM bd_esquema_version` debe ser ≥ 12 en producción).
* **Las 46 ramas por motor** a veces son una traducción de SQL (`app/bd/traduccion.py`): al quitar SQLite se puede escribir el SQL ya en dialecto PostgreSQL, pero hay que mantener `tests/test_sql_portable.py` mientras exista cualquier ruta SQLite.
* **No hay vuelta atrás tras el paso 4**: la exportación inversa (`exportar_sqlite.py`) desaparece en el 3.
