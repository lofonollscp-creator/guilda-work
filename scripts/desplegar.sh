#!/usr/bin/env bash
# Despliegue en el VPS: trae los cambios, actualiza dependencias solo si
# cambiaron, reinicia el servicio y comprueba que ha quedado sano.
# Uso (como usuario guilda, con sudo para el reinicio): scripts/desplegar.sh
set -euo pipefail

cd "$(dirname "$0")/.."
SERVICIO="${GUILDA_SERVICIO:-guilda-work.service}"

# Antes de tocar nada: el código nuevo tiene que migrar bien una COPIA de la base real.
git fetch -q
if [ "$(git rev-parse HEAD)" != "$(git rev-parse '@{u}')" ] && [ -f data/registro.db ]; then
  nuevo=$(mktemp -d)
  git archive '@{u}' | tar -x -C "$nuevo"
  echo "== Comprobando las migraciones del código nuevo sobre una copia de la base real =="
  if .venv/bin/python "$nuevo/scripts/comprobar_migraciones.py" --codigo "$nuevo"; then
    rm -rf "$nuevo"
  else
    rm -rf "$nuevo"
    echo "Despliegue CANCELADO: no se ha cambiado nada ni reiniciado el servicio." >&2
    exit 1
  fi
fi

antes=$(git rev-parse HEAD)
git pull --ff-only
despues=$(git rev-parse HEAD)

if [ "$antes" != "$despues" ] && git diff --name-only "$antes" "$despues" | grep -q '^requirements.*\.txt$'; then
  echo "== requirements cambiado: instalando dependencias =="
  .venv/bin/pip install -r requirements.txt
fi

echo "== Reiniciando $SERVICIO =="
sudo systemctl restart "$SERVICIO"
sleep 3
exec scripts/verificar_despliegue.sh
