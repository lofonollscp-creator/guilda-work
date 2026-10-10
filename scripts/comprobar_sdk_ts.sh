#!/usr/bin/env bash
# Comprueba el cliente de TypeScript que genera la API: lo descarga de esta instancia, lo compila con tsc en modo estricto y ejecuta
# una prueba de comportamiento (reintentos, Idempotency-Key estable, Retry-After, errores, firma de webhooks) con un fetch falso.
# Usa un contenedor Node desechable (no instala nada en el servidor). Uso:  scripts/comprobar_sdk_ts.sh [http://127.0.0.1:8000]
set -euo pipefail
BASE="${1:-http://127.0.0.1:8000}"
AQUI="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -fsS "$BASE/docs/sdk/guilda-work.ts" -o "$TMP/guilda-work.ts"
cp "$AQUI/sdk_ts_prueba.mjs" "$TMP/prueba.mjs"
docker run --rm -v "$TMP:/w" -w /w node:22-alpine sh -c '
  npm i --no-audit --no-fund --silent typescript@5 >/dev/null 2>&1
  npx tsc --strict --target es2022 --module es2022 --moduleResolution node --lib es2022,dom guilda-work.ts
  mv guilda-work.js guilda-work.mjs
  sed -i "s#./guilda-work.js#./guilda-work.mjs#" prueba.mjs
  node prueba.mjs'
