#!/usr/bin/env bash
# Copia de seguridad diaria con Restic (ver HOSTING.md, «Copia de seguridad con Restic»). Cubre lo que NO tiene otra copia:
#   - cada base de datos Postgres en marcha (pg_dumpall: copia consistente, no los ficheros crudos);
#   - los volúmenes de Docker con datos reales (correo de Stalwart, Nextcloud, Vaultwarden, Synapse, n8n, VPN...); los volúmenes de
#     Postgres de servicios PARADOS se copian crudos (no hay contenedor al que pedir un volcado);
#   - las bases SQLite de la plataforma (registro.db y backoffice.db, con la API de copia de SQLite: consistentes en caliente),
#     los secretos y la configuración (.env, /etc/guilda-work.env, Caddyfile, claves del backoffice y del llavero de correo);
#   - los datos de FacturaScripts de cada despacho (bind mounts).
# NO cubre lo regenerable: cachés (redis, meilisearch), logs (loki), certificados de Caddy, configuración de Jitsi.
#
# Requiere /etc/restic.env (solo root, modo 600) con RESTIC_REPOSITORY (ruta local ABSOLUTA, p. ej. el segundo disco del VPS) y
# RESTIC_PASSWORD. SIN esa contraseña la copia no se puede abrir: guárdala FUERA de este servidor (gestor de contraseñas).
#
# Restic corre en un contenedor (imagen fijada por digest, la misma que se probó). Cada objetivo es independiente: si uno falla se
# anota, se sigue con los demás y el script termina con error al final. Estado en data/backups/restic_estado.json (lo lee el
# panel Salud del backoffice y avisa por correo si la copia se retrasa o falla).
#
# Retención por objetivo: 7 diarias, 4 semanales y 6 mensuales. Los domingos, comprobación de integridad de una muestra.
#
# Uso: scripts/backup_restic.sh   (lo lanza deploy/restic-backup.timer a las 03:00; también a mano, como root)
set -uo pipefail

ENV_FILE="${RESTIC_ENV_FILE:-/etc/restic.env}"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
if [ -z "${RESTIC_REPOSITORY:-}" ] || [ -z "${RESTIC_PASSWORD:-}" ]; then
  echo "RESTIC_REPOSITORY/RESTIC_PASSWORD no configuradas (¿falta $ENV_FILE?)." >&2
  exit 1
fi
case "$RESTIC_REPOSITORY" in
  /*) ;;
  *) echo "RESTIC_REPOSITORY debe ser una ruta local absoluta (para un bucket S3 usa restic a mano)." >&2; exit 1 ;;
esac

IMAGEN="${RESTIC_IMAGEN:-restic/restic@sha256:9940e6c7421ab3a21ee9fdc4e91596d04c792b600d31b102696c75cbf3ac4481}"
PREFIJO="${DOCKER_COMPOSE_PROJECT_PREFIX:-guilda-work}"
REPO_APP="${GUILDA_REPO:-/home/guilda/guilda-work}"
ESTADO="${GUILDA_RESTIC_ESTADO:-$REPO_APP/data/backups/restic_estado.json}"
HOST_TAG="guilda-work"
# Volúmenes que NO se copian (regenerables): cachés, logs, índices, certificados, configuración de Jitsi.
EXCLUIR='^(redis-|loki-data|meilisearch-data|jitsi-|caddy-|paperless-broker-data)'

# Que el destino sea de verdad OTRO disco: si el segundo disco no está montado (arranque, fallo), escribir en la ruta dejaría la copia
# en el mismo disco que los datos sin avisar. Con RESTIC_PERMITIR_MISMO_DISCO=1 se salta (solo para pruebas).
_existente="$RESTIC_REPOSITORY"
while [ ! -e "$_existente" ]; do _existente="$(dirname "$_existente")"; done
if [ "$(findmnt -n -o TARGET -T "$_existente" 2>/dev/null)" = "/" ] && [ "${RESTIC_PERMITIR_MISMO_DISCO:-0}" != "1" ]; then
  echo "El destino $RESTIC_REPOSITORY está en el disco principal (¿segundo disco sin montar?). No se hace la copia." >&2
  exit 1
fi

mkdir -p "$RESTIC_REPOSITORY"
INICIO="$(date -Is)"
ERRORES=()
OBJETIVOS=0
STAGING="$(mktemp -d /var/tmp/restic-staging.XXXXXX)"
trap 'rm -rf "$STAGING"' EXIT INT TERM

# restic en contenedor: cada función añade lo que necesita montar. El repositorio se monta en su misma ruta.
_restic() { docker run --rm -v restic-cache:/cache -v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY" -e RESTIC_REPOSITORY -e RESTIC_PASSWORD "$@"; }
restic_simple()  { _restic "$IMAGEN" "$@"; }
restic_stdin()   { _restic -i "$IMAGEN" "$@"; }
restic_volumen() { local v="$1"; shift; _restic -v "$v:/data:ro" "$IMAGEN" "$@"; }
restic_host()    { _restic -v "/:/host:ro" -v "$STAGING:/staging:ro" "$IMAGEN" "$@"; }

fallo() { echo "FALLO: $1" >&2; ERRORES+=("$1"); }

if ! restic_simple cat config >/dev/null 2>&1; then
  echo "== Inicializando el repositorio en $RESTIC_REPOSITORY =="
  restic_simple init || { echo "No se pudo inicializar el repositorio." >&2; exit 1; }
fi

# 1. Bases de datos Postgres en marcha: volcado completo, sin parar nada.
mapfile -t CONTENEDORES_PG < <(docker ps --format '{{.Names}}' | grep -E "^${PREFIJO}-postgres-" | sort)
DUMPEADOS=()
for contenedor in "${CONTENEDORES_PG[@]}"; do
  nombre="${contenedor#${PREFIJO}-postgres-}"
  echo "== Volcado de $contenedor =="
  OBJETIVOS=$((OBJETIVOS + 1))
  if docker exec "$contenedor" sh -c 'pg_dumpall -U "${POSTGRES_USER:-postgres}"' | restic_stdin backup --stdin --stdin-filename "${contenedor}.sql" --tag "pg-${nombre}" --host "$HOST_TAG" -q; then
    DUMPEADOS+=("postgres-${nombre}-data")
  else
    fallo "postgres:${nombre}"
  fi
done

# 2. Volúmenes de Docker con datos (los de Postgres ya volcados y los regenerables se saltan).
mapfile -t VOLUMENES < <(docker volume ls --format '{{.Name}}' | grep -E "^${PREFIJO}_" | sed "s/^${PREFIJO}_//" | sort)
for volumen in "${VOLUMENES[@]}"; do
  if [[ "$volumen" =~ $EXCLUIR ]]; then continue; fi
  if printf '%s\n' "${DUMPEADOS[@]:-}" | grep -qx "$volumen"; then continue; fi
  echo "== Volumen $volumen =="
  OBJETIVOS=$((OBJETIVOS + 1))
  restic_volumen "${PREFIJO}_${volumen}" backup /data --tag "vol-${volumen}" --host "$HOST_TAG" -q || fallo "volumen:${volumen}"
done

# 3. SQLite de la plataforma (copia consistente con la API de SQLite) + secretos y configuración + datos de FacturaScripts.
echo "== Bases SQLite, secretos y configuración =="
OBJETIVOS=$((OBJETIVOS + 1))
python3 -I - "$REPO_APP/data" "$STAGING" <<'PY' || fallo "sqlite"
import sqlite3, sys
origen, destino = sys.argv[1], sys.argv[2]
for nombre in ("registro.db", "backoffice.db"):
    try:
        fuente = sqlite3.connect(f"file:{origen}/{nombre}?mode=ro", uri=True)
    except sqlite3.Error:
        continue
    copia = sqlite3.connect(f"{destino}/{nombre}")
    fuente.backup(copia)
    copia.execute("pragma journal_mode=delete")      # sin ficheros -wal/-shm sueltos en la copia
    copia.close(); fuente.close()
PY
RUTAS_HOST=()
for ruta in \
  "$REPO_APP/.env" /etc/guilda-work.env /etc/caddy/Caddyfile \
  "$REPO_APP/data/backoffice_secret.key" "$REPO_APP/data/correo-keyring.cfg" \
  /mnt/HC_Volume_106540289/facturascripts-tenants "${GUILDA_PG_BACKUPS:-}"; do   # (esta última: copias base + WAL de la base de datos, ver scripts/backup_postgres.sh)
  [ -n "$ruta" ] && [ -e "$ruta" ] && RUTAS_HOST+=("/host$ruta")
done
restic_host backup /staging "${RUTAS_HOST[@]}" --tag host --host "$HOST_TAG" -q || fallo "host"

# 4. Retención y, los domingos, comprobación de una muestra de los datos.
echo "== Purgando snapshots antiguos =="
restic_simple forget --prune --group-by host,tags --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --host "$HOST_TAG" -q || fallo "forget"
if [ "$(date +%u)" = "7" ]; then
  echo "== Comprobando integridad (muestra) =="
  restic_simple check --read-data-subset=3% -q || fallo "check"
fi

# 5. Estado para el panel Salud.
FIN="$(date -Is)"
mkdir -p "$(dirname "$ESTADO")"
python3 -I - "$ESTADO" "$INICIO" "$FIN" "$OBJETIVOS" "$RESTIC_REPOSITORY" "${ERRORES[@]:-}" <<'PY'
import json, sys
ruta, inicio, fin, objetivos, repo, *errores = sys.argv[1:]
errores = [e for e in errores if e]
estado = {"inicio": inicio, "fin": fin, "objetivos": int(objetivos), "repositorio": repo, "errores": errores}
if not errores:
    estado["ultimo_ok"] = fin
else:
    try:
        estado["ultimo_ok"] = json.load(open(ruta)).get("ultimo_ok")      # no pisar la última copia buena con un intento fallido
    except Exception:
        estado["ultimo_ok"] = None
json.dump(estado, open(ruta, "w"), indent=1)
PY
chown --reference="$REPO_APP/data" "$ESTADO" 2>/dev/null || true

if [ "${#ERRORES[@]}" -gt 0 ]; then
  echo "Terminado CON ERRORES (${#ERRORES[@]}): ${ERRORES[*]}" >&2
  exit 1
fi
echo "Terminado: $OBJETIVOS objetivos respaldados."
