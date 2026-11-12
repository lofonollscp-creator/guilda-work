#!/usr/bin/env bash
# Busca CVE conocidos en las dependencias INSTALADAS en .venv (los requisitos no están fijados a una versión exacta, así que se audita lo real).
# Crea un entorno desechable con pip-audit; no toca .venv. Necesita red. Sale con 1 si hay vulnerabilidades.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d "${GUILDA_TMP:-/tmp}/auditoria-deps.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
python3 -m venv "$TMP/v"
"$TMP/v/bin/pip" install -q pip-audit
"$TMP/v/bin/pip-audit" --path "$REPO/.venv/lib/python"*/site-packages --progress-spinner off
