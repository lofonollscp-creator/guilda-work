#!/usr/bin/env bash
# Prueba de humo tras un despliegue (AA2): servicios activos, las tres webs responden, cabeceras de seguridad, sin errores recientes en el registro.
# Solo hace GET (nada que provoque 403: CrowdSec banea la IP del servidor si ve varios seguidos). Sale con 1 si algo falla.
#
#   scripts/verificar_despliegue.sh [URL] [--minutos N]   (URL: la comprobación local, por defecto http://127.0.0.1:8000/login; errores de los últimos 2 min por defecto)
# Variables: GUILDA_HOST_APP, GUILDA_HOST_PORTAL, GUILDA_HOST_BACKOFFICE (por defecto *.guildawork.com), GUILDA_SERVICIOS o, como antes, GUILDA_SERVICIO (uno solo).
# Con GUILDA_SOLO_LOCAL=1 solo comprueba servicios, la URL local y el registro (instalaciones sin los dominios públicos).
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="${GUILDA_HOST_APP:-app.guildawork.com}"
PORTAL="${GUILDA_HOST_PORTAL:-clientes.guildawork.com}"
BACKOFFICE="${GUILDA_HOST_BACKOFFICE:-backoffice.guildawork.com}"
SERVICIOS="${GUILDA_SERVICIOS:-${GUILDA_SERVICIO:-guilda-work guilda-backoffice guilda-work-mcp}}"
MINUTOS=2
URL_LOCAL="http://127.0.0.1:${GUILDA_PORT:-8000}/login"
if [ -n "${1:-}" ] && [ "${1#--}" = "$1" ]; then URL_LOCAL="$1"; shift; fi
[ "${1:-}" = "--minutos" ] && MINUTOS="${2:-2}"
fallos=0
ok()   { printf '  ✓ %s\n' "$1"; }
mal()  { printf '  ✗ %s\n' "$1"; fallos=$((fallos + 1)); }

echo "Versión: $(git -C "$REPO" log -1 --format='%h %s' 2>/dev/null | cut -c1-100)"

echo "Servicios"
for s in $SERVICIOS; do
  if systemctl is-active --quiet "$s"; then ok "$s activo"; else mal "$s NO está activo"; fi
done
if command -v docker >/dev/null 2>&1; then
  estado="$(docker inspect -f '{{.State.Status}}' guilda-work-kratos 2>/dev/null || echo ausente)"
  if [ "$estado" = running ]; then ok "kratos en marcha"; else mal "kratos: $estado"; fi
fi

echo "Respuestas"
codigo() { curl -s -o /dev/null -m 10 -w '%{http_code}' "$1"; }
comprobar() {   # nombre url códigos-aceptados
  local c; c="$(codigo "$2")"
  case " $3 " in *" $c "*) ok "$1 → $c" ;; *) mal "$1 → $c (esperaba $3)" ;; esac
}
comprobar "app (local)" "$URL_LOCAL" "200 302"
if [ "${GUILDA_SOLO_LOCAL:-0}" != 1 ]; then
  comprobar "app" "https://$APP/login" "200 302"
  comprobar "portal" "https://$PORTAL/portal/" "200 302"
  comprobar "backoffice" "https://$BACKOFFICE/" "200 302 401"
  comprobar "API" "https://$APP/api/v1/health" "200"

  echo "Cabeceras de seguridad (https://$APP/login)"
  cab="$(curl -sI -m 10 "https://$APP/login")"
  echo "$cab" | grep -qi '^strict-transport-security:' && ok "HSTS" || mal "falta HSTS"
  echo "$cab" | grep -qi '^x-content-type-options: *nosniff' && ok "nosniff" || mal "falta X-Content-Type-Options"
  echo "$cab" | grep -qi '^content-security-policy' && ok "CSP" || mal "falta CSP"
  echo "$cab" | grep -qi '^permissions-policy:' && ok "Permissions-Policy" || mal "falta Permissions-Policy"
  if echo "$cab" | grep -qiE '^(server|x-powered-by|via):'; then mal "se publica el software o la versión: $(echo "$cab" | grep -iE '^(server|x-powered-by|via):' | tr -d '\r' | head -1)"; else ok "sin Server / X-Powered-By / Via"; fi
fi

echo "Registro de errores (últimos ${MINUTOS} min)"
args=(); for s in $SERVICIOS; do args+=(-u "$s"); done
errores="$(journalctl "${args[@]}" --since "-${MINUTOS}min" -p err --no-pager -q 2>/dev/null | grep -c . || true)"
if [ "${errores:-0}" -eq 0 ]; then ok "sin errores"; else mal "${errores} línea(s) de error: journalctl ${args[*]} --since -${MINUTOS}min -p err"; fi

echo
if [ "$fallos" -eq 0 ]; then echo "Despliegue verificado."; exit 0; fi
echo "$fallos comprobación(es) fallida(s). Para volver atrás: git -C $REPO log --oneline -5 → git revert <commit> → push → reiniciar los servicios."
exit 1
