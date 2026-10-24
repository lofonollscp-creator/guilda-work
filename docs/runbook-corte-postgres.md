# Runbook: corte a PostgreSQL + Citus y vuelta atrás

Lo ejecuta una persona con `sudo` en el servidor (no hay nada automático ni programado). Todo está **ensayado de principio a fin** con una copia de los datos reales y con datos sintéticos
(`scripts/ensayo_corte_postgres.py`, informes en `data/pg-ensayo/ensayo-corte-*.json`). Contexto y decisiones: `docs/adr-postgresql-citus.md`; operación diaria: `docs/runbooks-postgresql.md`.

## Tiempos medidos en el ensayo general (2 pasadas seguidas, copia de los datos reales: 69 MB, 1 despacho)
| Paso | Real | Sintético (90 personas, 30 despachos, 100.000 filas) |
|---|---|---|
| Copia final de los SQLite | 0,1 s | 10 s |
| Migración + controles automáticos (incluye `backoffice.db`) | 56 s | 68 s |
| Pruebas de humo sobre PostgreSQL | 7 s | 72 s |
| **Ventana con la plataforma parada** (copia + migración + humo; sin contar reinicios ni tus comprobaciones) | **≈ 63 s** | **≈ 150 s** |
| **Vuelta atrás** (`exportar_a_sqlite.py`, con todo lo escrito tras el corte) | **≈ 10 s** | ≈ 21 s |

Reserva **30 minutos** de ventana: lo que más tarda es lo humano (editar el entorno, reiniciar, mirar pantallas). Lo escrito en PostgreSQL tras el corte vuelve a SQLite sin pérdida
(el ensayo escribe notas, tareas y una nota de administración y comprueba que están tras la vuelta).

---

## Una ayuda para todo el runbook
Las herramientas necesitan el MISMO entorno que los servicios (la clave del llavero de correo y demás, que solo lee root) y la URL del superusuario. Abre una sesión de root (`sudo -i`) y define:
```bash
guilda_py() { ( set -a; source /etc/guilda-work.env; source /etc/guilda-pg-admin.env; set +a; cd /home/guilda/guilda-work && runuser -u guilda --preserve-environment -- .venv/bin/python "$@" ); }
```
(corre como el usuario `guilda`, con el entorno de producción y `GUILDA_PG_ADMIN_URL`; no escribe nada fuera de lo que cada herramienta dice).

## Paso 0 — Antes (días antes, sin parar nada)

1. **Desplegar el código nuevo con el motor SQLite** y reiniciar: `git pull`, `sudo systemctl restart guilda-work guilda-work-mcp guilda-backoffice`, `scripts/verificar_despliegue.sh`.
   El arranque ejecuta `init_db()`, que deja `registro.db` con el esquema nuevo (`usuarios_tenants`…). Déjalo funcionando al menos un día. *Vuelta atrás de este paso: `git checkout` del commit anterior y reiniciar.*
2. **La carpeta de copias, en OTRO disco**, y las variables:
   ```bash
   sudo mkdir -p /mnt/HC_Volume_106540289/guilda-pg-backups/{base,wal} && sudo chmod 777 /mnt/HC_Volume_106540289/guilda-pg-backups/wal
   echo 'GUILDA_PG_BACKUPS=/mnt/HC_Volume_106540289/guilda-pg-backups' | sudo tee -a /etc/guilda-work.env
   # la contraseña del SUPERUSUARIO en un fichero aparte (los servicios de la aplicación NO la ven):
   P="$(openssl rand -base64 33 | tr -d '/+=\n')"
   printf 'PG_APP_PASSWORD=%s\nGUILDA_PG_ADMIN_URL=postgresql://guilda:%s@127.0.0.1:5433/guilda\n' "$P" "$P" | sudo install -m 600 /dev/stdin /etc/guilda-pg-admin.env; unset P
   ```
   Guarda esa contraseña (`sudo cat /etc/guilda-pg-admin.env`) también **fuera del servidor** (gestor de contraseñas).
3. **La imagen y el contenedor** (hace falta ~3 GB de memoria libres; ver «Dimensionar» en `HOSTING.md`):
   ```bash
   cd /home/guilda/guilda-work
   docker compose -f docker-compose.postgres-citus.yml build        # solo construye la imagen guilda-work-citus:ensayo
   sudo docker compose -f docker-compose.postgres-app.yml --env-file /etc/guilda-work.env --env-file /etc/guilda-pg-admin.env up -d --wait
   ```
4. **Copia base y timer** (`HOSTING.md` §9.4): `sudo scripts/backup_postgres.sh todo` y activar `deploy/postgres-backup.timer`.
5. **Verificar que se sabe restaurar**: `scripts/probar.sh --ejecutar scripts/simulacro_restauracion_pg.py` (usa contenedores desechables, no toca el real).
6. **Comprobaciones previas**: `sudo scripts/corte_preflight.sh` — debe acabar con **0 fallos**. Es de solo lectura y no imprime contraseñas.
7. Elegir la hora y **avisar a los despachos** (el sitio estará en mantenimiento unos minutos). Opcional, la víspera: repetir el ensayo general
   (`scripts/probar.sh --ejecutar scripts/ensayo_corte_postgres.py --pasadas 2`) con los datos de ese día.

## Paso 1 — Cerrar y parar

```bash
# 1. Backoffice → Mantenimiento → «Cerrar toda la plataforma» con un mensaje (los administradores siguen entrando). Espera 1 minuto.
# 2. Parar todo lo que escribe en la base de datos (leen /etc/guilda-work.env):
sudo systemctl stop guilda-work guilda-work-mcp guilda-backoffice automatizaciones.timer tareas-recurrentes.timer vencimientos-fiscales.timer vigilar-facturascripts.timer
sudo systemctl stop automatizaciones.service tareas-recurrentes.service vencimientos-fiscales.service vigilar-facturascripts.service 2>/dev/null
sudo fuser -v /home/guilda/guilda-work/data/registro.db /home/guilda/guilda-work/data/backoffice.db     # no debe salir ningún proceso
```

## Paso 2 — Copia de seguridad final (la vuelta más segura: estos ficheros no se tocan nunca)

```bash
sudo -u guilda mkdir -p /home/guilda/guilda-work/data/pre-corte
guilda_py - <<'PY'
import sqlite3
for n in ("registro.db", "backoffice.db"):
    o = sqlite3.connect(f"file:/home/guilda/guilda-work/data/{n}?mode=ro", uri=True); d = sqlite3.connect(f"/home/guilda/guilda-work/data/pre-corte/{n}"); o.backup(d); d.close(); o.close()
PY
ls -la /home/guilda/guilda-work/data/pre-corte/
```
(`data/registro.db` y `data/backoffice.db` tampoco se modifican durante la migración: solo se leen.)

## Paso 3 — Migrar (≈ 1–3 min)

```bash
guilda_py scripts/migrar_a_postgres.py --origen data/registro.db --backoffice data/backoffice.db --esquema citus --informe data/pre-corte/informe-migracion.json
```
Resultado esperado: **«RESULTADO: todo cuadra»** y salida 0. Cualquier otra cosa (discrepancias, error): **no sigas**; no se ha cambiado nada → ve a «Vuelta atrás A». El informe lleva recuentos, sumas
de control por columna, huérfanos, secuencias, RLS y búsqueda.

Ahora las contraseñas de los roles (se crean sin ella) — elige tres contraseñas largas y guárdalas:
```bash
docker exec -i guilda-work-postgres-app psql -U guilda -d guilda <<'SQL'
ALTER ROLE guilda_app PASSWORD '…'; ALTER ROLE guilda_plataforma PASSWORD '…'; ALTER ROLE guilda_backoffice PASSWORD '…'; ALTER ROLE guilda_monitor PASSWORD '…';
SQL
```

## Paso 4 — Cambiar el entorno (una sola vez: lo leen todos los servicios)

Añade a `/etc/guilda-work.env` (las contraseñas son las del paso anterior; el puerto 5433 es el del contenedor):
```
GUILDA_DB_ENGINE=postgres
GUILDA_PG_ESQUEMA=citus
GUILDA_PG_POOL_MAX=12
GUILDA_DATABASE_URL=postgresql://guilda_app:CLAVE_APP@127.0.0.1:5433/guilda
GUILDA_DATABASE_URL_PLATAFORMA=postgresql://guilda_plataforma:CLAVE_PLATAFORMA@127.0.0.1:5433/guilda
GUILDA_DATABASE_URL_BACKOFFICE=postgresql://guilda_backoffice:CLAVE_BACKOFFICE@127.0.0.1:5433/guilda
```
(sin comillas; las contraseñas sin caracteres `@ : / ?` o codificadas como URL). `sudo chmod 600 /etc/guilda-work.env` sigue valiendo.

## Paso 5 — Pruebas de humo con el entorno de producción, ANTES de abrir

```bash
guilda_py scripts/humo_postgres.py
```
Debe acabar con **«TODO BIEN»**: motor, pantallas de cada persona sin errores 5xx, escritura de prueba (deshecha) en cada despacho, búsqueda, backoffice, nodos de Citus, archivo de WAL y aislamiento por
despacho con el rol de la aplicación. Si algo falla, **no abras**: «Vuelta atrás A».

## Paso 6 — Arrancar y abrir

```bash
sudo systemctl start guilda-work guilda-work-mcp guilda-backoffice
sudo systemctl start automatizaciones.timer tareas-recurrentes.timer vencimientos-fiscales.timer vigilar-facturascripts.timer
scripts/verificar_despliegue.sh
# Backoffice → Mantenimiento → quitar el cierre. Entra con un usuario real: tarea nueva, correo, fichaje, un cliente, el asistente jurídico.
sudo scripts/backup_postgres.sh todo        # primera copia base de la vida nueva; el panel Salud debe mostrar «Base de datos» en verde
```
Vigila `journalctl -u guilda-work -p err -f` y el panel *Salud* los primeros minutos. Avisa a los despachos de que ya está.

---

## Vuelta atrás

**A. Antes de que nadie haya escrito en PostgreSQL** (la migración falló, el humo falló, o te arrepientes en los primeros minutos). *No se ha perdido nada*: SQLite no se ha tocado.
```bash
# quitar las 6 líneas añadidas al entorno (GUILDA_DB_ENGINE…GUILDA_DATABASE_URL_BACKOFFICE) y arrancar como antes
sudo systemctl start guilda-work guilda-work-mcp guilda-backoffice automatizaciones.timer tareas-recurrentes.timer vencimientos-fiscales.timer vigilar-facturascripts.timer
```

**B. Ya se ha escrito en PostgreSQL (hasta ~48 h)**: se reconstruyen los SQLite desde PostgreSQL con TODO lo escrito (≈ 10–25 s):
```bash
sudo systemctl stop guilda-work guilda-work-mcp guilda-backoffice automatizaciones.timer tareas-recurrentes.timer vencimientos-fiscales.timer vigilar-facturascripts.timer
sudo mkdir -p /home/guilda/guilda-work/data/vuelta && sudo chown guilda: /home/guilda/guilda-work/data/vuelta
guilda_py scripts/exportar_a_sqlite.py --salida data/vuelta/registro.db --backoffice-salida data/vuelta/backoffice.db --informe data/vuelta/informe.json
#   → «RESULTADO: todo cuadra» (si no, NO sigas y avísame: los datos están intactos en PostgreSQL)
cd /home/guilda/guilda-work/data
sudo -u guilda mv registro.db registro.db.pre-vuelta && sudo -u guilda mv backoffice.db backoffice.db.pre-vuelta && sudo rm -f registro.db-wal registro.db-shm backoffice.db-wal backoffice.db-shm
sudo -u guilda mv vuelta/registro.db registro.db && sudo -u guilda mv vuelta/backoffice.db backoffice.db
# quitar las 6 líneas del entorno y arrancar
sudo systemctl start guilda-work guilda-work-mcp guilda-backoffice automatizaciones.timer tareas-recurrentes.timer vencimientos-fiscales.timer vigilar-facturascripts.timer
```
Lo que se pierde en B: nada escrito en PostgreSQL; sí lo que **no estaba en las bases** (por ejemplo, ficheros subidos a Nextcloud siguen donde estaban; el correo sincronizado se vuelve a descargar solo).
Pasadas ~48 h con escrituras en PostgreSQL, la vuelta atrás deja de ser una opción cómoda (el esquema sigue evolucionando): se corrige hacia delante.

## Después (fase 12)
Observación reforzada durante dos semanas; los SQLite originales (`data/pre-corte/`, y `registro.db`/`backoffice.db` congelados) se conservan al menos 30 días; Litestream y la copia de `registro.db` (§9.1) quedan
sin función y se retiran; `backup_restic.sh` ya hace el `pg_dumpall` del contenedor y guarda la carpeta de copias. Después, la ruta SQLite se retira del código (decisión D2).
