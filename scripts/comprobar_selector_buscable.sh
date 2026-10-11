#!/usr/bin/env bash
# Prueba el comportamiento de app/static/selector_buscable.js (selector con buscador) con jsdom, en un
# contenedor Node desechable (no instala nada en el servidor). Uso:  scripts/comprobar_selector_buscable.sh
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/scripts" "$TMP/app/static"
cp "$AQUI/selector_buscable_prueba.mjs" "$TMP/scripts/" && cp "$AQUI/../app/static/selector_buscable.js" "$TMP/app/static/"
docker run --rm -v "$TMP:/w" -w /w node:22-alpine sh -c 'npm i --no-audit --no-fund --silent jsdom@25 >/dev/null 2>&1 && node scripts/selector_buscable_prueba.mjs'
