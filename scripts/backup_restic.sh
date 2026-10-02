#!/usr/bin/env bash
# Backup diario de los volúmenes Docker con datos reales de clientes (ver
# HOSTING.md, sección "Backups con Restic") — complementa, no sustituye,
# a Litestream (que ya replica data/registro.db en continuo, ver
# deploy/litestream.yml) y a db.py:hacer_backup_si_hace_falta() (copia
# local diaria del mismo registro.db).
#
# Verificado en vivo antes de escribir este script (backup + restore
# real contra un bucket S3-compatible, byte a byte idéntico) — ver el
# apartado de verificación de HOSTING.md.
#
# Requiere: RESTIC_REPOSITORY y RESTIC_PASSWORD en /etc/restic.env — nunca
# en este archivo. RESTIC_REPOSITORY puede ser una ruta local absoluta
# (p. ej. /mnt/HC_Volume_106540289/restic, el segundo disco del VPS: no
# hace falta ninguna cuenta externa) o un bucket S3-compatible, en cuyo caso
# hacen falta también AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY.
#
# Política de retención: UNA sola copia (la última) por volumen, para que los
# backups no se acumulen. Ojo con --group-by: todos los volúmenes se respaldan
# como "/data" en el mismo host, así que con el agrupado por defecto
# (host,paths) restic los trataría como un único grupo y --keep-last 1 dejaría
# un solo snapshot en TOTAL, borrando el de los demás volúmenes. Con
# --group-by host,tags (cada volumen lleva su --tag) queda uno por volumen.
#
# Uso: 0 3 * * * /home/guilda/guilda-work/scripts/backup_restic.sh
# (con RandomizedDelaySec si se llama desde un timer systemd, ver
# deploy/restic-backup.timer)

set -euo pipefail

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

# Solo lo irreemplazable — no lo regenerable sin pérdida real (ver
# HOSTING.md para el porqué de cada exclusión: meilisearch-data se
# reindexa solo, caddy-*-data son certificados que se reemiten, las
# configs de Jitsi no llevan datos de cliente, redis-* son cachés).
VOLUMENES=(
  postgres-espocrm-data
  postgres-nextcloud-data
  postgres-documenso-data
  postgres-paperless-data
  postgres-baserow-data
  postgres-chatwoot-data
  postgres-openproject-data
  postgres-facturascripts-data
  postgres-listmonk-data
  postgres-calcom-data
  postgres-umami-data
  nextcloud-data
  paperless-media
  baserow-data
  stalwart-data
  listmonk-uploads
)

PREFIJO="${DOCKER_COMPOSE_PROJECT_PREFIX:-guilda-work}"

# Repositorio local: el contenedor de restic tiene que ver esa ruta.
MONTAJE_REPO=()
case "$RESTIC_REPOSITORY" in
  /*) mkdir -p "$RESTIC_REPOSITORY"; MONTAJE_REPO=(-v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY") ;;
esac

for volumen in "${VOLUMENES[@]}"; do
  volumen_real="${PREFIJO}_${volumen}"
  if ! docker volume inspect "$volumen_real" >/dev/null 2>&1; then
    echo "Aviso: el volumen $volumen_real no existe (¿esa herramienta no está desplegada aquí?), se omite." >&2
    continue
  fi
  echo "== Respaldando $volumen_real =="
  docker run --rm \
    -v "$volumen_real:/data:ro" \
    -v restic-cache:/cache \
    "${MONTAJE_REPO[@]}" \
    -e RESTIC_REPOSITORY -e RESTIC_PASSWORD \
    -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
    restic/restic backup /data --tag "$volumen" --host guilda-work
done

echo "== Purgando snapshots antiguos (política: una única copia por volumen) =="
docker run --rm \
  -v restic-cache:/cache \
  "${MONTAJE_REPO[@]}" \
  -e RESTIC_REPOSITORY -e RESTIC_PASSWORD \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
  restic/restic forget --prune \
  --group-by host,tags --keep-last 1 --host guilda-work
