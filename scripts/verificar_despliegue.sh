#!/usr/bin/env bash
# Comprueba que Guilda Work ha quedado sano tras un despliegue/reinicio:
# servicio activo, responde por HTTP y sin errores recientes en el journal.
# Uso: scripts/verificar_despliegue.sh [URL]   (por defecto http://127.0.0.1:8000/)
set -uo pipefail

URL="${1:-http://127.0.0.1:${GUILDA_PORT:-8000}/}"
SERVICIO="${GUILDA_SERVICIO:-guilda-work.service}"
fallos=0

if systemctl is-active --quiet "$SERVICIO"; then
  echo "OK    $SERVICIO activo"
else
  echo "FALLO $SERVICIO no está activo"; fallos=$((fallos + 1))
fi

codigo=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$URL" || true)
case "$codigo" in
  2??|3??) echo "OK    $URL responde ($codigo)" ;;
  *) echo "FALLO $URL no responde bien (HTTP ${codigo:-sin respuesta})"; fallos=$((fallos + 1)) ;;
esac

errores=$(journalctl -u "$SERVICIO" --since "-2 min" -p err --no-pager -q 2>/dev/null | wc -l)
if [ "$errores" -eq 0 ]; then
  echo "OK    sin errores en el journal de los últimos 2 min"
else
  echo "FALLO $errores línea(s) de error en el journal (journalctl -u $SERVICIO -p err --since -2min)"; fallos=$((fallos + 1))
fi

exit $((fallos > 0))
