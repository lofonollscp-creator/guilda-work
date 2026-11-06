#!/usr/bin/env bash
# Copia de los documentos que viven en el bucket S3 (ver docs/almacen-de-objetos.md) al repositorio de Restic, FUERA de AWS: si se pierde la
# cuenta de AWS, los documentos siguen en el segundo disco del VPS. Dos pasos: 1) espejo incremental del bucket (scripts/espejo_objetos.py,
# solo añade y comprueba la huella de cada objeto) y 2) `restic backup` del espejo con la etiqueta «objetos» (mismo repositorio y contraseña que
# scripts/backup_restic.sh). Las bases de datos (que guardan el registro de objetos) ya las cubre esa otra copia.
#
# Requiere /etc/restic.env (RESTIC_REPOSITORY, RESTIC_PASSWORD) y las GUILDA_S3_* de /etc/guilda-work.env.
# Retención: 7 diarias, 4 semanales, 6 mensuales y 6 anuales. El espejo nunca borra, así que la última copia siempre tiene todo.
# Uso: scripts/backup_objetos_restic.sh   (lo lanza deploy/restic-objetos.timer a las 03:40; también a mano, como root)
set -uo pipefail

for f in "${RESTIC_ENV_FILE:-/etc/restic.env}" "${GUILDA_ENV_FILE:-/etc/guilda-work.env}"; do
  if [ -f "$f" ]; then set -a; . "$f"; set +a; fi
done
if [ -z "${RESTIC_REPOSITORY:-}" ] || [ -z "${RESTIC_PASSWORD:-}" ]; then echo "RESTIC_REPOSITORY/RESTIC_PASSWORD no configuradas." >&2; exit 1; fi
if [ "${GUILDA_OBJETOS:-}" != "s3" ]; then echo "GUILDA_OBJETOS no es s3: no hay bucket que copiar."; exit 0; fi
case "$RESTIC_REPOSITORY" in /*) ;; *) echo "RESTIC_REPOSITORY debe ser una ruta local absoluta." >&2; exit 1 ;; esac

IMAGEN="${RESTIC_IMAGEN:-restic/restic@sha256:9940e6c7421ab3a21ee9fdc4e91596d04c792b600d31b102696c75cbf3ac4481}"
REPO_APP="${GUILDA_REPO:-/home/guilda/guilda-work}"
export GUILDA_OBJETOS_ESPEJO="${GUILDA_OBJETOS_ESPEJO:-$(dirname "$RESTIC_REPOSITORY")/objetos-espejo}"
export GUILDA_OBJETOS_ESPEJO_ESTADO="${GUILDA_OBJETOS_ESPEJO_ESTADO:-$REPO_APP/data/backups/restic_objetos_estado.json}"

# El espejo y el repositorio deben estar en otro disco, no en el principal (ver backup_restic.sh).
_existente="$GUILDA_OBJETOS_ESPEJO"; while [ ! -e "$_existente" ]; do _existente="$(dirname "$_existente")"; done
if [ "$(findmnt -n -o TARGET -T "$_existente" 2>/dev/null)" = "/" ] && [ "${RESTIC_PERMITIR_MISMO_DISCO:-0}" != "1" ]; then
  echo "El espejo $GUILDA_OBJETOS_ESPEJO está en el disco principal (¿segundo disco sin montar?). No se hace la copia." >&2; exit 1
fi

echo "== Espejo del bucket en $GUILDA_OBJETOS_ESPEJO =="
"$REPO_APP/.venv/bin/python" -I "$REPO_APP/scripts/espejo_objetos.py" || { echo "El espejo terminó con errores; no se copia a Restic." >&2; exit 1; }

_restic() { docker run --rm -v restic-cache:/cache -v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY" -v "$GUILDA_OBJETOS_ESPEJO:/objetos:ro" -e RESTIC_REPOSITORY -e RESTIC_PASSWORD "$IMAGEN" "$@"; }
echo "== Restic: copia del espejo =="
_restic backup /objetos --tag objetos --host guilda-work -q || { echo "FALLO: restic backup" >&2; exit 1; }
_restic forget --prune --group-by host,tags --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --keep-yearly 6 --tag objetos --host guilda-work -q || { echo "FALLO: forget" >&2; exit 1; }
if [ "$(date +%u)" = "7" ]; then _restic check --read-data-subset=3% -q || { echo "FALLO: check" >&2; exit 1; }; fi
chown --reference="$REPO_APP/data" "$GUILDA_OBJETOS_ESPEJO_ESTADO" 2>/dev/null || true
echo "Terminado."
