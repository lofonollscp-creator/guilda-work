#!/usr/bin/env bash
# Segunda copia de Restic FUERA del servidor y del proveedor del VPS (AD1): replica el repositorio local de Restic (segundo disco) en el bucket de AWS S3 que ya usa el almacén de
# documentos, en la carpeta «copias-restic/». Usa `restic copy`: solo sube los snapshots que aún no están, cifrados con la misma contraseña (RESTIC_PASSWORD) y sin releer los volúmenes.
# Así, si se pierde el VPS y su disco, las bases de datos, secretos y volúmenes se restauran desde S3 (docs: HOSTING.md «Copia de seguridad en S3»).
#
# Requiere /etc/restic.env (RESTIC_REPOSITORY local, RESTIC_PASSWORD) y las GUILDA_S3_* de /etc/guilda-work.env (las mismas claves del almacén de objetos: deben poder escribir en
# la carpeta copias-restic/ y borrar ahí, para la retención). Retención en S3: 7 diarias, 4 semanales, 6 mensuales y 6 anuales por objetivo. Los domingos comprueba una muestra del 2 %.
# Estado en data/backups/restic_s3_estado.json (lo lee el panel Salud). Uso: scripts/copia_s3_restic.sh   (lo lanza deploy/restic-s3.timer a las 04:15; también a mano, como root)
set -uo pipefail

for f in "${RESTIC_ENV_FILE:-/etc/restic.env}" "${GUILDA_ENV_FILE:-/etc/guilda-work.env}"; do
  if [ -f "$f" ]; then set -a; . "$f"; set +a; fi
done
REPO_APP="${GUILDA_REPO:-/home/guilda/guilda-work}"
ESTADO="${GUILDA_RESTIC_S3_ESTADO:-$REPO_APP/data/backups/restic_s3_estado.json}"
INICIO="$(date -Is)"

terminar() {
  local codigo="$1"; shift
  mkdir -p "$(dirname "$ESTADO")"
  python3 -I - "$ESTADO" "$INICIO" "${COPIADOS:-}" "$@" <<'PY'
import json, sys, datetime
ruta, inicio, copiados, *errores = sys.argv[1:]
errores = [e for e in errores if e]
fin = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
estado = {"inicio": inicio, "fin": fin, "snapshots_copiados": int(copiados) if copiados.isdigit() else None, "errores": errores[:20]}
try:
    previo = json.load(open(ruta))
except Exception:
    previo = {}
estado["ultimo_ok"] = fin if not errores else previo.get("ultimo_ok")
json.dump(estado, open(ruta, "w"), indent=1)
PY
  chown --reference="$REPO_APP/data" "$ESTADO" 2>/dev/null || true
  exit "$codigo"
}

if [ -z "${RESTIC_REPOSITORY:-}" ] || [ -z "${RESTIC_PASSWORD:-}" ]; then echo "RESTIC_REPOSITORY/RESTIC_PASSWORD no configuradas." >&2; terminar 1 "faltan RESTIC_REPOSITORY/RESTIC_PASSWORD"; fi
if [ -z "${GUILDA_S3_BUCKET:-}" ] || [ -z "${GUILDA_S3_ACCESS_KEY:-}" ] || [ -z "${GUILDA_S3_SECRET_KEY:-}" ]; then echo "Faltan GUILDA_S3_BUCKET/ACCESS_KEY/SECRET_KEY." >&2; terminar 1 "faltan las claves de S3"; fi
case "$RESTIC_REPOSITORY" in /*) ;; *) echo "RESTIC_REPOSITORY debe ser una ruta local absoluta." >&2; terminar 1 "repositorio local no válido" ;; esac

IMAGEN="${RESTIC_IMAGEN:-restic/restic@sha256:9940e6c7421ab3a21ee9fdc4e91596d04c792b600d31b102696c75cbf3ac4481}"
ENDPOINT="${GUILDA_S3_ENDPOINT:-s3.amazonaws.com}"
DESTINO="s3:https://$ENDPOINT/$GUILDA_S3_BUCKET/${GUILDA_RESTIC_S3_PREFIJO:-copias-restic}"
export AWS_ACCESS_KEY_ID="$GUILDA_S3_ACCESS_KEY" AWS_SECRET_ACCESS_KEY="$GUILDA_S3_SECRET_KEY" AWS_DEFAULT_REGION="${GUILDA_S3_REGION:-eu-north-1}"
export RESTIC_FROM_REPOSITORY="$RESTIC_REPOSITORY" RESTIC_FROM_PASSWORD="$RESTIC_PASSWORD"

# El destino lleva la contraseña de Restic pero NO su ruta local; el origen se monta con escritura porque restic crea ahí sus ficheros de bloqueo (no modifica los snapshots).
_restic() { docker run --rm -v restic-cache:/cache -v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY" -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_DEFAULT_REGION \
  -e RESTIC_PASSWORD -e RESTIC_FROM_REPOSITORY -e RESTIC_FROM_PASSWORD -e RESTIC_REPOSITORY="$DESTINO" "$IMAGEN" "$@"; }

if ! _restic cat config >/dev/null 2>&1; then
  echo "== Creando el repositorio en S3 (primera vez) =="
  _restic init --from-repo "$RESTIC_REPOSITORY" --copy-chunker-params -q || { echo "FALLO: no se pudo crear el repositorio en S3" >&2; terminar 1 "init del repositorio en S3"; }
fi
echo "== Copiando snapshots nuevos a S3 =="
ANTES="$(_restic snapshots --json 2>/dev/null | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)"
_restic copy -q || { echo "FALLO: restic copy" >&2; terminar 1 "restic copy"; }
DESPUES="$(_restic snapshots --json 2>/dev/null | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)"
COPIADOS=$((DESPUES - ANTES))
echo "== Retención en S3 =="
_restic forget --prune --group-by host,tags --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --keep-yearly 6 -q || { echo "FALLO: forget" >&2; terminar 1 "forget en S3"; }
if [ "$(date +%u)" = "7" ]; then _restic check --read-data-subset=2% -q || { echo "FALLO: check" >&2; terminar 1 "check en S3"; }; fi
echo "Terminado: $COPIADOS snapshots copiados."
terminar 0
