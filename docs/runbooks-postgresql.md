# Runbooks de la base de datos PostgreSQL + Citus

Para quien opera el servidor. Todo lo de aquí está **probado** con `scripts/simulacro_restauracion_pg.py` (contenedores desechables; informe de referencia en
`data/pg-ensayo/simulacro-restauracion.json`) y con la prueba de un segundo nodo de la fase 9 (ADR). Variables: `GUILDA_PG_BACKUPS` (carpeta de copias, otro disco),
`PG_IMAGEN` (por defecto `guilda-work-citus:ensayo`). Los comandos `docker`/`systemctl` los ejecuta una persona con permisos; nada de aquí toca producción salvo donde dice «EN PRODUCCIÓN».

Cifras del simulacro (datos sintéticos, 3 despachos, ≈ 10 MB; el WAL a reproducir crece con la actividad desde la copia base, no con el tamaño de la base):
copia base 4,7 s (17 MB) · instancia recuperada a un instante en 5,5 s · exportar un despacho 0,7 s · importarlo 1,5 s.

---

## 0. Qué tengo y qué RPO/RTO

| Pérdida | Recuperación | RPO | RTO típico |
|---|---|---|---|
| Un error de aplicación/persona (se borró algo de un despacho) | Runbook 2 (un despacho desde una instancia a un instante anterior) | hasta el instante elegido | minutos |
| Corrupción o borrado general de la base | Runbook 1 + 3 (instancia a un instante → sustituir el volumen) | ≤ 5 min | minutos + reproducir WAL |
| Pérdida del disco de datos | Runbook 3 con las copias del otro disco | ≤ 5 min (si el otro disco sobrevive) | ≈ copia base + WAL |
| Pérdida del servidor entero | Restic (`docs` §9.2) + `pg_dumpall` lógico → Runbook 6 | hasta la última pasada de Restic (24 h) | horas |

**El punto débil conocido**: las copias y el WAL están en el *otro disco del mismo servidor*; si el servidor desaparece, solo queda lo que Restic haya sacado. Para bajar el RPO de ese
caso hay que apuntar Restic (o `rclone` sobre `$GUILDA_PG_BACKUPS/wal`) a un destino externo.

## 1. Recuperar a un instante en una instancia aparte (inspección; NO toca producción)

```bash
scripts/restaurar_postgres.sh instancia --hasta "2026-10-25 09:41:00" --puerto 55441      # hora del servidor; o --punto base_AAAAMMDD-HHMMSS / antes_del_cambio
# …imprime "Instancia lista en N s" y la URL: postgresql://guilda:<contraseña de producción>@127.0.0.1:55441/postgres
scripts/restaurar_postgres.sh quitar                                                       # cuando ya no haga falta
```
Elige solo la copia base **anterior** al instante pedido y reproduce el WAL hasta él. Sin opciones reproduce todo el WAL. Antes de una operación de riesgo (migración, borrado masivo),
crea un punto con nombre: `docker exec guilda-work-postgres-app psql -U guilda -d guilda -c "select citus_create_restore_point('antes_de_X')"` y úsalo con `--punto antes_de_X`.

## 2. Recuperar UN despacho (lo habitual)

1. Instancia a un instante **anterior al error** (Runbook 1), p. ej. en el puerto 55441.
2. Exportar de ella:
   `.venv/bin/python scripts/copia_despacho.py exportar --url postgresql://guilda:…@127.0.0.1:55441/guilda --despacho 12 --salida /var/tmp/despacho-12.tar.gz`
3. Mirar qué lleva: `scripts/copia_despacho.py ver --entrada /var/tmp/despacho-12.tar.gz`
4. **EN PRODUCCIÓN**: importar en la base viva (solo toca ese despacho; lo que tenga ahora se sustituye con `--reemplazar`):
   `.venv/bin/python scripts/copia_despacho.py importar --url postgresql://guilda:…@127.0.0.1:5433/guilda --entrada /var/tmp/despacho-12.tar.gz --reemplazar`
5. Comprueba la salida («importado… » y ninguna `DISCREPANCIA`), borra el `.tar.gz` (lleva datos del despacho) y retira la instancia.

Qué NO lleva un despacho: la configuración global, el corpus jurídico compartido y las filas de las mismas personas en *otros* despachos. La auditoría (solo de anexado) no se borra ni se
duplica: se completa con lo que falte. Importa solo copias del mismo esquema (`--otra-version` lo salta bajo tu responsabilidad). Lo escrito en ese despacho DESPUÉS del instante elegido se pierde.

## 3. Restaurar TODA la base (sustituir el volumen de producción)

Con la aplicación parada para que nadie escriba (`sudo systemctl stop guilda-work guilda-work-mcp guilda-backoffice`):
```bash
scripts/restaurar_postgres.sh volumen guilda-pg-recuperado --hasta "2026-10-25 09:41:00"     # prepara un volumen NUEVO (no sobrescribe nada)
docker compose -f docker-compose.postgres-app.yml stop
# EN PRODUCCIÓN: apuntar el contenedor al volumen recuperado (cambia `postgres-app-data` por `guilda-pg-recuperado` en el compose, como volumen externo) y arrancar
docker compose -f docker-compose.postgres-app.yml up -d --wait
docker exec guilda-work-postgres-app psql -U guilda -d guilda -c "select count(*) from tenants" -c "select pg_is_in_recovery()"   # debe ser f (ya promovida)
sudo systemctl start guilda-work guilda-work-mcp guilda-backoffice
scripts/backup_postgres.sh todo        # copia base nueva sobre la línea de tiempo nueva, ANTES de seguir
```
El volumen anterior se conserva (no se borra) hasta que verifiques. Tras recuperar a un instante PostgreSQL abre una **línea de tiempo nueva**; las copias base antiguas siguen valiendo para
recuperar a instantes anteriores a este, pero haz una base nueva cuanto antes.

## 4. Añadir un nodo (crecer)

Ensayado con `docker-compose.postgres-citus-worker.yml`: reequilibrar y drenar **con tráfico, sin errores ni escrituras perdidas**. En un servidor real:
1. En el nodo nuevo: PostgreSQL con las mismas opciones (`wal_level=logical`, `shared_preload_libraries=citus`), la base `guilda` y las extensiones (`citus`, `unaccent`, `pg_trgm`, `vector`).
2. **Autenticación entre nodos**: Citus se conecta con el MISMO rol de la sesión (`guilda_app`, `guilda_plataforma`, `guilda`) y no admite contraseña en `citus.node_conninfo`. En ambos nodos, un
   `.pgpass` del usuario `postgres` con los tres roles (`*:5432:*:ROL:CONTRASEÑA`, modo 600) o `pg_hba` por red privada/certificados. Sin esto, en cuanto un fragmento pasa al otro nodo la aplicación recibe `ConnectionFailure`.
3. En el coordinador: `select citus_set_coordinator_host('NOMBRE-QUE-VE-EL-WORKER', 5432); select citus_add_node('worker-1', 5432);` y `select citus_rebalance_start(rebalance_strategy := 'by_shard_count'); select citus_rebalance_wait();`
4. Cada nodo necesita su propio archivo de WAL y copia base (`scripts/backup_postgres.sh` por nodo) y la recuperación de todos hasta el MISMO punto de restauración de Citus (`base_AAAAMMDD-HHMMSS`, lo crea cada copia base).
5. Toda tabla distribuida necesita clave primaria (test `test_toda_tabla_distribuida_tiene_clave_primaria…`). Un nodo drenado queda con `shouldhaveshards=false`: ponlo a `true` para reutilizarlo.

## 5. Rotar contraseñas de los roles

`ALTER ROLE guilda_app PASSWORD '…'` (y `guilda_plataforma`, `guilda_monitor`, `guilda`) en el contenedor; actualizar `GUILDA_DATABASE_URL`/`_PLATAFORMA` en `/etc/guilda-work.env`,
`PG_MONITOR_PASSWORD` en Grafana, `PG_APP_PASSWORD` donde se use, y el `.pgpass` de cada nodo si hay más de uno; reiniciar `guilda-work`, `guilda-work-mcp` y `guilda-backoffice`.

## 6. Desde el `pg_dumpall` de Restic (último recurso)

El volcado lógico no incluye la distribución de Citus. Se restaura sobre una base **nueva**: arrancar un contenedor vacío, `scripts/migrar_a_postgres.py`-style: crear la base con las extensiones,
`esquema.crear_si_falta(conn, "citus")` y cargar los **datos** del volcado (`pg_restore --data-only` / `psql` de las sentencias `COPY`) con los triggers desactivados
(`app/bd/migrar_datos.py:sin_disparadores`). Es lento y manual: por eso existen los runbooks 1–3.

## 7. Si el archivo de WAL falla (alerta roja «Archivo de WAL»)

Casi siempre: disco de copias lleno o desmontado, o permisos de `wal/`. `docker logs guilda-work-postgres-app | grep -i archive`; `df -h "$GUILDA_PG_BACKUPS"`; el WAL **no se borra** mientras no se
archive (el disco de datos crece): arreglar la causa y el archivador recupera solo (comprobado en el simulacro). Si el disco de copias se llena, `scripts/backup_postgres.sh limpiar` libera lo anterior a la copia más antigua conservada.

## 8. Ranuras de replicación detenidas (alerta «Ranuras de replicación»)

Una ranura sin lector (p. ej. un reequilibrado interrumpido) retiene WAL y llena el disco. `select slot_name, active, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) from pg_replication_slots;`
y, si es de un reequilibrado abandonado, `select pg_drop_replication_slot('nombre');`.

## 9. Mantenimiento

* Actualizar PostgreSQL/Citus: construir la imagen nueva, **ejecutar el simulacro** con ella (`PG_IMAGEN=…`), y entonces cambiar; los cambios de versión mayor de PostgreSQL requieren `pg_upgrade` o volcado/carga y **invalidan el WAL anterior**: base nueva inmediata.
* Las copias base con la configuración `--data-checksums` detectan corrupción de disco al leer; `pg_basebackup` las verifica al copiar.
* Ensayo trimestral: `scripts/probar.sh --ejecutar scripts/simulacro_restauracion_pg.py`.
