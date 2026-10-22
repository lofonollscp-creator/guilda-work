#!/usr/bin/env bash
# Pruebas de navegador (Playwright + Chromium) de los flujos críticos: tests/e2e. Corren en una COPIA aislada, como el resto (scripts/probar.sh), y NO forman parte de la suite normal.
#
#   scripts/probar_navegador.sh                   todas las pruebas de tests/e2e
#   scripts/probar_navegador.sh -k portal         solo las que coincidan
#
# Instalación (una sola vez, la hace una persona; ver HOSTING.md, «Pruebas de navegador»):
#   .venv/bin/pip install -r requirements-e2e.txt && .venv/bin/playwright install --with-deps chromium
REPO="$(cd "$(dirname "$0")/.." && pwd)"
if ! "$REPO/.venv/bin/python" -c "import playwright" 2>/dev/null; then
  echo "Playwright no está instalado en el entorno virtual. Instálalo una vez con:" >&2
  echo "  .venv/bin/pip install -r requirements-e2e.txt && .venv/bin/playwright install --with-deps chromium" >&2
  exit 3
fi
export GUILDA_E2E=1
exec "$REPO/scripts/probar.sh" tests/e2e "$@"
