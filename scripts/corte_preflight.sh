#!/usr/bin/env bash
# Comprobaciones previas al corte a PostgreSQL (fase 11; docs/runbook-corte-postgres.md). SOLO LEE: no cambia nada ni imprime contraseñas. Se ejecuta como root:
#
#   sudo scripts/corte_preflight.sh
#
# Termina con código 0 si todo está listo (puede haber AVISOS), 1 si hay algún FALLO. Variables: GUILDA_ENV_FILE (/etc/guilda-work.env), GUILDA_PG_ADMIN_ENV (/etc/guilda-pg-admin.env),
# PG_CONTENEDOR (guilda-work-postgres-app), GUILDA_REPO (/home/guilda/guilda-work).
set -uo pipefail
REPO="${GUILDA_REPO:-/home/guilda/guilda-work}"
ENV_APP="${GUILDA_ENV_FILE:-/etc/guilda-work.env}"
ENV_ADMIN="${GUILDA_PG_ADMIN_ENV:-/etc/guilda-pg-admin.env}"
CONT="${PG_CONTENEDOR:-guilda-work-postgres-app}"
fallos=0; avisos=0
ok()    { echo "OK     $*"; }
aviso() { echo "AVISO  $*"; avisos=$((avisos + 1)); }
falla() { echo "FALLO  $*"; fallos=$((fallos + 1)); }
tiene() { grep -qE "^$2=.+" "$1" 2>/dev/null; }

[ "$(id -u)" = 0 ] || { echo "Ejecútalo con sudo."; exit 2; }

# 1. código
cd "$REPO" || { echo "No existe $REPO"; exit 2; }
if git -c safe.directory="$REPO" diff --quiet HEAD -- . 2>/dev/null; then ok "el repositorio no tiene cambios sin commitear ($(git -c safe.directory="$REPO" log --oneline -1))"; else aviso "el repositorio tiene cambios sin commitear"; fi
[ -f scripts/migrar_a_postgres.py ] && [ -f scripts/exportar_a_sqlite.py ] && ok "las herramientas de migración y de vuelta atrás están" || falla "faltan scripts/migrar_a_postgres.py o scripts/exportar_a_sqlite.py (¿código sin actualizar?)"

# 2. la plataforma actual (SQLite)
for u in guilda-work guilda-work-mcp guilda-backoffice; do systemctl is-active --quiet "$u" && ok "$u activo" || aviso "$u no está activo"; done
if [ -f data/registro.db ]; then
  r="$(python3 - <<'PY'
import sqlite3
c = sqlite3.connect("file:data/registro.db?mode=ro", uri=True)
print(c.execute("PRAGMA integrity_check").fetchone()[0], "|", c.execute("SELECT count(*) FROM sqlite_master WHERE name = 'usuarios_tenants'").fetchone()[0])
PY
)"
  [ "${r%% |*}" = "ok" ] && ok "registro.db íntegra ($(du -h data/registro.db | cut -f1))" || falla "registro.db: integrity_check = ${r%% |*}"
  [ "${r##*| }" = "1" ] && ok "registro.db tiene el esquema del código nuevo (usuarios_tenants): el código nuevo ya corrió con SQLite" || falla "registro.db no tiene usuarios_tenants: despliega el código nuevo con SQLite y reinicia ANTES del corte (paso 0 del runbook)"
else falla "no existe data/registro.db"; fi

# 3. entorno
[ -f "$ENV_ADMIN" ] && [ "$(stat -c %a "$ENV_ADMIN")" = "600" ] && tiene "$ENV_ADMIN" PG_APP_PASSWORD && tiene "$ENV_ADMIN" GUILDA_PG_ADMIN_URL && ok "$ENV_ADMIN existe (600) con PG_APP_PASSWORD y GUILDA_PG_ADMIN_URL" || falla "falta $ENV_ADMIN (modo 600) con PG_APP_PASSWORD y GUILDA_PG_ADMIN_URL (el superusuario: NO va en $ENV_APP)"
tiene "$ENV_APP" PG_APP_PASSWORD && falla "$ENV_APP contiene PG_APP_PASSWORD: sácala de ahí, los servicios de la aplicación no deben ver la contraseña del superusuario" || ok "$ENV_APP no contiene la contraseña del superusuario"
tiene "$ENV_APP" GUILDA_PG_BACKUPS && ok "GUILDA_PG_BACKUPS definida" || falla "falta GUILDA_PG_BACKUPS en $ENV_APP"
if tiene "$ENV_APP" GUILDA_DB_ENGINE; then aviso "GUILDA_DB_ENGINE ya está en $ENV_APP (¿corte ya hecho?): $(grep -E '^GUILDA_DB_ENGINE=' "$ENV_APP")"; else ok "GUILDA_DB_ENGINE aún no está en $ENV_APP (la aplicación sigue en SQLite)"; fi

# 4. el contenedor de PostgreSQL
sano=0
if docker inspect -f '{{.State.Health.Status}}' "$CONT" 2>/dev/null | grep -q healthy; then ok "$CONT sano"; sano=1; else falla "$CONT no está sano o no existe (docker compose -f docker-compose.postgres-app.yml up -d --wait)"; fi
psqlc() { docker exec -i "$CONT" psql -X -U guilda -d guilda -At -v ON_ERROR_STOP=1 "$@" 2>/dev/null; }
if [ "$sano" = 1 ]; then
if [ "$(psqlc -c "show archive_mode")" = "on" ]; then ok "archive_mode = on"; else falla "el archivo de WAL no está activado"; fi
[ "$(psqlc -c "show wal_level")" = "logical" ] && ok "wal_level = logical" || falla "wal_level no es logical"
[ "$(psqlc -c "select count(*) from pg_extension where extname in ('citus','unaccent','pg_trgm')")" = "3" ] && ok "extensiones citus, unaccent y pg_trgm" || aviso "faltan extensiones (la herramienta de migración las crea)"
n="$(psqlc -c "select count(*) from tenants" 2>/dev/null || true)"
case "$n" in "") ok "la base 'guilda' está vacía (sin esquema todavía)" ;; 0|1) ok "la base 'guilda' tiene el esquema y está vacía ($n despacho)" ;; *) falla "la base 'guilda' YA tiene $n despachos: el corte no mezcla datos (¿corte hecho? usa otra base o recréala)" ;; esac
for rol in guilda_app guilda_plataforma guilda_backoffice; do
  r="$(psqlc -c "select (rolpassword is not null) from pg_authid where rolname = '$rol'")"
  [ -z "$r" ] && aviso "el rol $rol aún no existe (lo crea el esquema; pon su contraseña después de migrar y antes de arrancar)" || { [ "$r" = "t" ] && ok "el rol $rol tiene contraseña" || aviso "el rol $rol existe SIN contraseña"; }
done
fi

# 5. copias
dest="$(grep -E '^GUILDA_PG_BACKUPS=' "$ENV_APP" 2>/dev/null | cut -d= -f2-)"
if [ -n "$dest" ] && [ -d "$dest/base" ] && [ -d "$dest/wal" ]; then
  [ "$(findmnt -n -o TARGET -T "$dest" 2>/dev/null)" != "/" ] && ok "las copias están en otro disco ($dest, $(df -h --output=avail "$dest" | tail -1 | tr -d ' ') libres)" || falla "$dest está en el disco principal"
  ultima="$(ls -1t "$dest"/base/base-*.tar.gz 2>/dev/null | head -1)"
  if [ -n "$ultima" ] && [ $(( $(date +%s) - $(stat -c %Y "$ultima") )) -lt 129600 ]; then ok "copia base reciente ($(basename "$ultima"))"; else aviso "no hay copia base de las últimas 36 h (scripts/backup_postgres.sh todo)"; fi
else falla "no existen $dest/base y $dest/wal"; fi
estado=/home/guilda/guilda-work/data/backups/restic_estado.json
if [ -f "$estado" ] && python3 - "$estado" <<'PY'
import json, sys, datetime
e = json.load(open(sys.argv[1]))
ok = e.get("ultimo_ok") and (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(e["ultimo_ok"])).total_seconds() < 36 * 3600 and not e.get("errores")
sys.exit(0 if ok else 1)
PY
then ok "Restic: última copia de las últimas 36 h y sin errores"; else aviso "Restic: sin copia completa y limpia en las últimas 36 h"; fi

# 6. espacio y servicios que habrá que parar
libre_gb=$(df -BG --output=avail "$REPO/data" | tail -1 | tr -dc 0-9)
[ "$libre_gb" -ge 5 ] && ok "${libre_gb} GB libres junto a data/" || falla "solo ${libre_gb} GB libres junto a data/"
echo; echo "Se pararán (todos leen $ENV_APP):"
for u in guilda-work guilda-work-mcp guilda-backoffice automatizaciones.timer tareas-recurrentes.timer vencimientos-fiscales.timer vigilar-facturascripts.timer; do
  printf '   %-34s %s\n' "$u" "$(systemctl is-active "$u" 2>/dev/null)"; done
echo; echo "Resultado: $fallos fallo(s), $avisos aviso(s)."
exit $((fallos > 0))
