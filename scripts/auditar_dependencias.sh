#!/usr/bin/env bash
# Busca CVE conocidos en las dependencias INSTALADAS en .venv (los requisitos no están fijados a una versión exacta, así que se audita lo real).
# Crea un entorno desechable con pip-audit; no toca .venv. Necesita red. Deja el resultado en data/backups/cve_estado.json (lo lee el panel Salud)
# y sale con 1 si hay vulnerabilidades. Lo lanza semanalmente deploy/auditoria-dependencias.timer.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ESTADO="${GUILDA_ESTADO_CVE:-${GUILDA_BACKUPS_DIR:-$REPO/data/backups}/cve_estado.json}"
TMP="$(mktemp -d "${GUILDA_TMP:-/tmp}/auditoria-deps.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
python3 -m venv "$TMP/v"
"$TMP/v/bin/pip" install -q pip-audit
# pip-audit sale con 1 si encuentra algo: el JSON se escribe igual.
"$TMP/v/bin/pip-audit" --path "$REPO/.venv/lib/python"*/site-packages --progress-spinner off --format json -o "$TMP/auditoria.json" >/dev/null 2>"$TMP/error.txt" || true
[ -s "$TMP/auditoria.json" ] || { echo "pip-audit no produjo resultado:" >&2; cat "$TMP/error.txt" >&2; exit 2; }
python3 - "$TMP/auditoria.json" "$ESTADO" <<'PY'
import json, sys
from datetime import datetime
bruto = json.load(open(sys.argv[1]))
vulnerables = []
for d in bruto.get("dependencies", []):
    vulns = d.get("vulns") or []
    if vulns:
        vulnerables.append({"paquete": d["name"], "version": d["version"], "ids": sorted({v["id"] for v in vulns}),
                            "corregida": sorted({f for v in vulns for f in v.get("fix_versions", [])}, reverse=True)[:1]})
estado = {"fecha": datetime.now().isoformat(timespec="seconds"), "vulnerables": vulnerables, "total": len(vulnerables)}
json.dump(estado, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
for v in vulnerables:
    print(f"{v['paquete']} {v['version']}: {len(v['ids'])} aviso(s), corregido en {', '.join(v['corregida']) or '?'}")
print("Sin vulnerabilidades conocidas." if not vulnerables else f"{len(vulnerables)} paquete(s) con vulnerabilidades.")
sys.exit(1 if vulnerables else 0)
PY
