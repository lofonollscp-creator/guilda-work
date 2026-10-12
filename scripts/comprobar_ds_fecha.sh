#!/usr/bin/env bash
# Prueba el selector de fecha (app/static/ds_fecha.js) con jsdom en un contenedor Node desechable (no instala nada en el servidor;
# descarga jsdom). Uso:  scripts/comprobar_ds_fecha.sh
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/scripts" "$TMP/app/static"
cp "$AQUI/ds_fecha_prueba.mjs" "$TMP/scripts/" && cp "$AQUI/../app/static/ds_fecha.js" "$TMP/app/static/"
docker run --rm -v "$TMP:/w" -w /w node:22-alpine sh -c 'npm i --no-audit --no-fund --silent jsdom@25 >/dev/null 2>&1 && node scripts/ds_fecha_prueba.mjs'
