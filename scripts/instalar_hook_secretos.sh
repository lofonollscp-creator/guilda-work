#!/usr/bin/env bash
# Instala el hook de pre-commit que ejecuta scripts/detectar_secretos.py (AA6). Los hooks de .git no se versionan: hay que instalarlo en cada copia del repositorio.
# Solo BLOQUEA los hallazgos de confianza alta; los de media solo avisan. Para saltarlo en un commit concreto: git commit --no-verify
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$REPO/.git/hooks/pre-commit"
if [ -e "$HOOK" ] && ! grep -q detectar_secretos "$HOOK"; then echo "Ya hay un pre-commit distinto en $HOOK: no lo piso." >&2; exit 1; fi
cat > "$HOOK" <<'HOOK_EOF'
#!/usr/bin/env bash
exec "$(git rev-parse --show-toplevel)/scripts/detectar_secretos.py"
HOOK_EOF
chmod +x "$HOOK"
echo "Hook instalado en $HOOK"
