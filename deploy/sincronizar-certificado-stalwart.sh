#!/usr/bin/env bash
# Copia el certificado HTTPS de mail.guildawork.com (el que Caddy obtiene y renueva con Let's Encrypt) a una carpeta que el
# contenedor de Stalwart puede leer, para que IMAP/SMTP (993, 465, 587, 25) presenten el mismo certificado válido que el 443.
# Stalwart corre como uid 2000 y los ficheros de Caddy son de su usuario (modo 600), así que no se pueden montar tal cual.
# Si el certificado cambia (renovación cada ~60 días) reinicia Stalwart (~10 s) para que lo cargue. Idempotente.
#   Uso: sincronizar-certificado-stalwart.sh [dominio]   (por defecto mail.guildawork.com)
set -euo pipefail
DOMINIO="${1:-mail.guildawork.com}"
ORIGEN="$(ls -d /var/lib/caddy/.local/share/caddy/certificates/*/"$DOMINIO" 2>/dev/null | head -1 || true)"
DESTINO="/etc/guilda-work/stalwart-certs"
UID_STALWART=2000

if [ -z "$ORIGEN" ] || [ ! -s "$ORIGEN/$DOMINIO.crt" ] || [ ! -s "$ORIGEN/$DOMINIO.key" ]; then
  logger -t stalwart-cert "No hay certificado de Caddy para $DOMINIO; no se toca nada."
  echo "No hay certificado de Caddy para $DOMINIO" >&2
  exit 1
fi

install -d -m 750 "$DESTINO"
chown "root:$UID_STALWART" "$DESTINO"
cambiado=0
for ext in crt key; do
  if ! cmp -s "$ORIGEN/$DOMINIO.$ext" "$DESTINO/$DOMINIO.$ext" 2>/dev/null; then
    install -m 640 "$ORIGEN/$DOMINIO.$ext" "$DESTINO/$DOMINIO.$ext.nuevo"
    chown "root:$UID_STALWART" "$DESTINO/$DOMINIO.$ext.nuevo"
    mv -f "$DESTINO/$DOMINIO.$ext.nuevo" "$DESTINO/$DOMINIO.$ext"
    cambiado=1
  fi
done

if [ "$cambiado" = 1 ]; then
  logger -t stalwart-cert "Certificado de $DOMINIO actualizado."
  if docker ps --format '{{.Names}}' | grep -qx guilda-work-stalwart; then
    docker restart guilda-work-stalwart >/dev/null
    logger -t stalwart-cert "Stalwart reiniciado para cargar el certificado nuevo."
  fi
  echo "certificado actualizado"
else
  echo "sin cambios"
fi
