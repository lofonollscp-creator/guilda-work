#!/usr/bin/env bash
# ¿Se puede pasar la política de scripts (CSP) de «informar» a «forzar»? Cuenta los avisos `CSP:` del registro de guilda-work en los últimos N
# días (por defecto 5) y comprueba que el registro cubre ese periodo. No cambia nada: si sale «LISTO», para forzar:
#     echo 'GUILDA_CSP=forzar' >> /etc/guilda-work.env && systemctl restart guilda-work
# y para volver atrás, cambia el valor a `reportar` (o quita la línea) y reinicia.
#
#   scripts/comprobar_csp_para_forzar.sh [DIAS]
set -uo pipefail
DIAS="${1:-5}"
modo="$(grep -E '^GUILDA_CSP=' /etc/guilda-work.env 2>/dev/null | tail -1 | cut -d= -f2)"
echo "Modo actual: ${modo:-reportar (por defecto)}"
primera="$(journalctl -u guilda-work --no-pager -o short-unix 2>/dev/null | head -1 | cut -d. -f1)"
ahora="$(date +%s)"
cubre=$(( primera > 0 ? (ahora - primera) / 86400 : 0 ))
avisos="$(journalctl -u guilda-work --no-pager --since "-${DIAS} days" 2>/dev/null | grep -c 'CSP:' || true)"
echo "El registro cubre ${cubre} días; avisos CSP en los últimos ${DIAS} días: ${avisos}"
if [ "$avisos" -gt 0 ]; then
  echo "NO LISTO: hay avisos. Los últimos:"
  journalctl -u guilda-work --no-pager --since "-${DIAS} days" 2>/dev/null | grep 'CSP:' | tail -5 | sed -E "s/.*(violated-directive='[^']*').*(blocked-uri='[^']*').*(document-uri='[^']*').*/  \1 \2 \3/"
  exit 1
fi
if [ "$cubre" -lt "$DIAS" ]; then echo "NO LISTO: el registro no cubre ${DIAS} días todavía."; exit 1; fi
echo "LISTO: ${DIAS} días sin avisos CSP."
