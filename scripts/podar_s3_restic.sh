#!/usr/bin/env bash
# Poda MANUAL de la copia de Restic en AWS S3 (la copia diaria es de solo añadir: las claves de la app no pueden borrar). Hace falta una credencial TEMPORAL con s3:DeleteObject sobre
# copias-restic/ (por ejemplo, una sesión de `aws login` o una clave que crees para esto y borres después). NUNCA pongas esa credencial en /etc/guilda-work.env.
#
#   AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=… [AWS_SESSION_TOKEN=…] scripts/podar_s3_restic.sh            # simulación (no borra nada)
#   AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=… scripts/podar_s3_restic.sh --aplicar                       # aplica la retención: 7 diarias, 4 semanales, 6 mensuales, 6 anuales
# Requiere /etc/restic.env (RESTIC_PASSWORD) y GUILDA_S3_BUCKET/ENDPOINT de /etc/guilda-work.env. Quita antes los bloqueos caducados.
set -uo pipefail
for f in /etc/restic.env /etc/guilda-work.env; do [ -f "$f" ] && { set -a; . "$f"; set +a; }; done
[ -n "${AWS_ACCESS_KEY_ID:-}" ] && [ -n "${AWS_SECRET_ACCESS_KEY:-}" ] || { echo "Pasa AWS_ACCESS_KEY_ID y AWS_SECRET_ACCESS_KEY de la credencial con permiso de borrado." >&2; exit 2; }
if [ "${AWS_ACCESS_KEY_ID}" = "${GUILDA_S3_ACCESS_KEY:-}" ]; then echo "Esa es la clave de la app, que no puede borrar. Usa una credencial temporal distinta." >&2; exit 2; fi
IMAGEN="${RESTIC_IMAGEN:-restic/restic@sha256:9940e6c7421ab3a21ee9fdc4e91596d04c792b600d31b102696c75cbf3ac4481}"
export RESTIC_REPOSITORY="s3:https://${GUILDA_S3_ENDPOINT:-s3.amazonaws.com}/$GUILDA_S3_BUCKET/${GUILDA_RESTIC_S3_PREFIJO:-copias-restic}" AWS_DEFAULT_REGION="${GUILDA_S3_REGION:-eu-north-1}"
_restic() { docker run --rm -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN -e AWS_DEFAULT_REGION -e RESTIC_PASSWORD -e RESTIC_REPOSITORY "$IMAGEN" "$@"; }
_restic unlock || true
if [ "${1:-}" = "--aplicar" ]; then
  _restic forget --prune --group-by host,tags --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --keep-yearly 6
else
  echo "== SIMULACIÓN (usa --aplicar para borrar de verdad) =="
  _restic forget --dry-run --group-by host,tags --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --keep-yearly 6
fi
