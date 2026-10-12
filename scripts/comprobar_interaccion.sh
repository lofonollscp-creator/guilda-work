#!/usr/bin/env bash
# Recorrido con clics reales en un navegador (Chromium sin pantalla) sobre una instancia TEMPORAL y aislada de la aplicación: copia del repositorio, base de datos
# de usar y tirar, Kratos simulado, sin tocar datos ni servicios reales. Cada ejecución arranca una instancia nueva y la borra al terminar.
#
#   scripts/comprobar_interaccion.sh [PUERTO]       (por defecto 8099; capturas de los fallos en $SALIDA, por defecto un directorio temporal)
#
# Necesita Playwright y su Chromium (PW_PYTHON y PLAYWRIGHT_BROWSERS_PATH; por defecto /tmp/pw-venv/bin/python y /tmp/pw-browsers). No instala nada.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PUERTO="${1:-8099}"
PW_PYTHON="${PW_PYTHON:-/tmp/pw-venv/bin/python}"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/tmp/pw-browsers}"
[ -x "$PW_PYTHON" ] || { echo "Falta Playwright ($PW_PYTHON). Indica PW_PYTHON con un Python que lo tenga." >&2; exit 2; }
DESTINO="$(mktemp -d /tmp/guilda-interaccion.XXXXXX)"
SALIDA="${SALIDA:-$DESTINO/fallos}"; mkdir -p "$SALIDA"
SERVIDOR=""
limpiar() { [ -n "$SERVIDOR" ] && kill "$SERVIDOR" 2>/dev/null; [ -z "${CONSERVAR:-}" ] && rm -rf "$DESTINO"; }
trap limpiar EXIT INT TERM
cd "$REPO"
git ls-files -z --cached --others --exclude-standard | grep -zv -e '^data/' -e '^mobile/' | rsync -a --files-from=- --from0 ./ "$DESTINO/repo/"
ln -s "$REPO/.venv" "$DESTINO/repo/.venv"
mkdir -p "$DESTINO/home"
cd "$DESTINO/repo"
HOME="$DESTINO/home" .venv/bin/python scripts/servidor_demo.py "$PUERTO" > "$DESTINO/servidor.log" 2>&1 &
SERVIDOR=$!
for _ in $(seq 1 60); do grep -q "Serving on" "$DESTINO/servidor.log" 2>/dev/null && break; sleep 1; done
grep -q "Serving on" "$DESTINO/servidor.log" || { echo "La instancia no arrancó:"; tail -20 "$DESTINO/servidor.log"; exit 2; }
"$PW_PYTHON" scripts/prueba_interaccion.py "$SALIDA" "http://127.0.0.1:$PUERTO"
CODIGO=$?
[ $CODIGO -ne 0 ] && echo "Capturas de los fallos: $SALIDA (se conservan con CONSERVAR=1)"
exit $CODIGO
