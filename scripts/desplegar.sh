#!/usr/bin/env bash
# Despliegue en el VPS: trae los cambios, actualiza dependencias solo si
# cambiaron, reinicia el servicio y comprueba que ha quedado sano.
# Uso (como usuario guilda, con sudo para el reinicio): scripts/desplegar.sh
set -euo pipefail

cd "$(dirname "$0")/.."
SERVICIO="${GUILDA_SERVICIO:-guilda-work.service}"

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
