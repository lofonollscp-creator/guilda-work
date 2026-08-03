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
# Requiere: RESTIC_REPOSITORY, RESTIC_PASSWORD y las credenciales del
# backend S3-compatible (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY) en
# /etc/restic.env — nunca en este archivo.
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
    -e RESTIC_REPOSITORY -e RESTIC_PASSWORD \
    -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
    restic/restic backup /data --tag "$volumen" --host guilda-work
done

echo "== Purgando snapshots antiguos (política: 7 diarios, 4 semanales, 6 mensuales) =="
docker run --rm \
  -v restic-cache:/cache \
  -e RESTIC_REPOSITORY -e RESTIC_PASSWORD \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
  restic/restic forget --prune \
  --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --host guilda-work
