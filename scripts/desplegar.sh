#!/usr/bin/env bash
# Ayuda para desplegar (AA1): la receta de «despliégalo todo» en un solo comando, parando en el primer fallo. No decide nada por su cuenta: lo lanza una persona.
#
#   scripts/desplegar.sh --simular     enseña lo que haría, sin tocar nada
#   scripts/desplegar.sh               push, migraciones ANTES de reiniciar, reinicio, Kratos si cambió su configuración y verificación
#   scripts/desplegar.sh --ayuda-web   además publica el centro de ayuda (../guilda-help/publicar.sh)
# Debe ejecutarse como root (systemctl). Antes: suite en verde y todo commiteado.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SERVICIOS="${GUILDA_SERVICIOS:-guilda-work guilda-backoffice guilda-work-mcp}"
USUARIO="${GUILDA_USUARIO:-guilda}"
SIMULAR=0; AYUDA=0
for a in "$@"; do
  case "$a" in
    --simular) SIMULAR=1 ;;
    --ayuda-web) AYUDA=1 ;;
    -h|--ayuda|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Opción desconocida: $a (usa --ayuda)" >&2; exit 2 ;;
  esac
done
paso() { printf '\n== %s\n' "$1"; }
ejecutar() { if [ "$SIMULAR" = 1 ]; then printf '   [simulado] %s\n' "$*"; else "$@"; fi; }
git_() { git -c safe.directory="$REPO" -C "$REPO" "$@"; }

[ "$SIMULAR" = 1 ] || [ "$(id -u)" -eq 0 ] || { echo "Ejecútalo como root (hace falta systemctl)." >&2; exit 2; }

paso "Comprobaciones previas"
rama="$(git_ rev-parse --abbrev-ref HEAD)"
[ "$rama" = main ] || { echo "Estás en «$rama», no en main." >&2; exit 2; }
if [ -n "$(git_ status --porcelain --untracked-files=no)" ]; then echo "Hay cambios sin commitear:" >&2; git_ status --short --untracked-files=no >&2; exit 2; fi
git_ fetch -q origin main 2>/dev/null || echo "   (no se pudo consultar origin: se compara con lo último que se conocía)"
desplegado="$(git_ rev-parse origin/main)"
nuevo="$(git_ rev-parse HEAD)"
if [ "$desplegado" = "$nuevo" ]; then echo "Nada nuevo que subir (origin/main = HEAD = $(git_ rev-parse --short HEAD))."; fi
echo "Desplegado hasta ahora: $(git_ rev-parse --short "$desplegado")   →   nuevo: $(git_ rev-parse --short "$nuevo")"
git_ log --oneline "$desplegado..$nuevo" | sed 's/^/   /' | cut -c1-130
cambiado() { git_ diff --name-only "$desplegado" "$nuevo" -- "$@" | grep -q .; }

paso "Subir a GitHub"
ejecutar su "$USUARIO" -c "cd '$REPO' && git -c safe.directory='$REPO' push origin main"

if cambiado app/bd/migraciones app/bd/esquema_pg; then
  paso "Migraciones (ANTES de reiniciar)"
  ejecutar bash -c "set -a; source /etc/guilda-pg-admin.env; set +a; cd '$REPO' && runuser -u '$USUARIO' --preserve-environment -- .venv/bin/python scripts/migrar_esquema_pg.py"
else
  paso "Migraciones: ninguna pendiente"
fi

if cambiado requirements.txt; then
  echo; echo "AVISO: requirements.txt cambió. Instala las dependencias nuevas en .venv ANTES de seguir (y prueba la suite en una copia del entorno)."
fi
if cambiado docker-compose.yml; then
  echo; echo "AVISO: docker-compose.yml cambió. Este script no recrea contenedores: revísalo y usa «docker compose up -d <servicio>» donde haga falta."
fi

paso "Reiniciar servicios"
ejecutar systemctl restart $SERVICIOS

if cambiado deploy/kratos; then
  paso "Kratos: su configuración cambió"
  ejecutar docker restart guilda-work-kratos
fi

if [ "$AYUDA" = 1 ]; then
  paso "Publicar el centro de ayuda"
  ejecutar bash -c "cd '$REPO/../guilda-help' && ./publicar.sh"
fi

paso "Verificar"
if [ "$SIMULAR" = 1 ]; then echo "   [simulado] scripts/verificar_despliegue.sh"; else sleep 8; "$REPO/scripts/verificar_despliegue.sh"; fi
echo; echo "Anota el despliegue en la bitácora (hasta $(git_ rev-parse --short "$nuevo"))."
