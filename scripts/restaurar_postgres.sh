#!/usr/bin/env bash
# Restaura la copia física de la base de datos de la aplicación (scripts/backup_postgres.sh) en una INSTANCIA APARTE o en un volumen nuevo, completa o hasta un instante
# (fase 10; ver docs/runbooks-postgresql.md). NUNCA toca el contenedor ni el volumen de producción.
#
#   scripts/restaurar_postgres.sh instancia [opciones]      levanta una instancia temporal para INSPECCIONAR (y exportar un despacho con scripts/copia_despacho.py)
#   scripts/restaurar_postgres.sh volumen NOMBRE [opciones] prepara un volumen Docker con los datos recuperados, para sustituir al de producción (lo cambias tú, ver el runbook)
#   scripts/restaurar_postgres.sh quitar [CONTENEDOR]       borra la instancia temporal y su volumen
#
# Opciones: --hasta "AAAA-MM-DD HH:MM:SS" (hora del servidor)  |  --punto NOMBRE (un punto de restauración, p. ej. el base_AAAAMMDD-HHMMSS de Citus)  |  (sin nada: hasta el final del WAL)
#           --base FICHERO (por defecto la última, o la más reciente ANTERIOR al instante pedido)   --wal CARPETA (por defecto $GUILDA_PG_BACKUPS/wal)
#           --puerto N (55441)   --nombre CONTENEDOR (guilda-pg-restaurado)   --memoria 1g
# Variables: GUILDA_PG_BACKUPS, PG_IMAGEN (guilda-work-citus:ensayo). La instancia restaurada trae las mismas contraseñas de roles que la base original.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${GUILDA_ENV_FILE:-/etc/guilda-work.env}"
[ -f "$ENV_FILE" ] && { set -a; source "$ENV_FILE" 2>/dev/null; set +a; }
IMAGEN="${PG_IMAGEN:-guilda-work-citus:ensayo}"
DESTINO="${GUILDA_PG_BACKUPS:-}"
accion="${1:-}"; shift || true
VOLUMEN_NOMBRE=""
if [ "$accion" = "volumen" ]; then VOLUMEN_NOMBRE="${1:?falta el nombre del volumen}"; shift; fi
HASTA=""; PUNTO=""; BASE_FICHERO=""; WAL=""; PUERTO=55441; NOMBRE=guilda-pg-restaurado; MEMORIA=1g
while [ $# -gt 0 ]; do
  case "$1" in
    --hasta) HASTA="$2"; shift ;; --punto) PUNTO="$2"; shift ;; --base) BASE_FICHERO="$2"; shift ;; --wal) WAL="$2"; shift ;;
    --puerto) PUERTO="$2"; shift ;; --nombre) NOMBRE="$2"; shift ;; --memoria) MEMORIA="$2"; shift ;;
    *) echo "opción desconocida: $1" >&2; exit 2 ;;
  esac; shift
done
WAL="${WAL:-$DESTINO/wal}"

preparar_volumen() {   # $1 = nombre del volumen
  local volumen="$1" base
  if [ -z "$BASE_FICHERO" ]; then
    # la copia base más reciente (si se pide un instante: la más reciente que empezó ANTES de él)
    local limite=""
    [ -n "$HASTA" ] && limite="$(date -d "$HASTA" +%s 2>/dev/null)"
    base="$(ls -1 "$DESTINO"/base/base-*.tar.gz 2>/dev/null | sort | while read -r f; do
      if [ -n "$limite" ]; then
        s="$(basename "$f" | sed 's/base-\([0-9]\{4\}\)\([0-9]\{2\}\)\([0-9]\{2\}\)-\([0-9]\{2\}\)\([0-9]\{2\}\)\([0-9]\{2\}\).*/\1-\2-\3 \4:\5:\6/')"
        [ "$(date -d "$s" +%s)" -le "$limite" ] || continue
      fi
      echo "$f"; done | tail -1)"
  else base="$BASE_FICHERO"; fi
  [ -f "$base" ] || { echo "No hay una copia base adecuada en $DESTINO/base." >&2; return 1; }
  [ -d "$WAL" ] || { echo "No existe la carpeta de WAL $WAL." >&2; return 1; }
  echo "Copia base: $(basename "$base")"
  docker volume create "$volumen" >/dev/null || return 1
  docker run --rm -u root -v "$volumen:/pgdata" -v "$(dirname "$base"):/base:ro" --entrypoint bash "$IMAGEN" -c \
    "tar xzf /base/$(basename "$base") -C /pgdata && chown -R postgres:postgres /pgdata && chmod 700 /pgdata && rm -f /pgdata/postmaster.pid" || return 1
  local objetivo=""
  [ -n "$HASTA" ] && objetivo="recovery_target_time = '$HASTA'"
  [ -n "$PUNTO" ] && objetivo="recovery_target_name = '$PUNTO'"
  docker run --rm -u root -v "$volumen:/pgdata" --entrypoint bash "$IMAGEN" -c "
    {
      echo \"restore_command = 'cp /backup/wal/%f %p'\"
      echo \"recovery_target_timeline = 'latest'\"
      [ -n \"$objetivo\" ] && echo \"$objetivo\" && echo \"recovery_target_inclusive = on\"
      echo \"recovery_target_action = 'promote'\"
    } >> /pgdata/postgresql.auto.conf && touch /pgdata/recovery.signal && chown postgres:postgres /pgdata/postgresql.auto.conf /pgdata/recovery.signal" || return 1
}

case "$accion" in
  instancia)
    [ -n "$DESTINO" ] || { echo "Define GUILDA_PG_BACKUPS." >&2; exit 2; }
    docker rm -f "$NOMBRE" >/dev/null 2>&1; docker volume rm "$NOMBRE-datos" >/dev/null 2>&1
    inicio=$(date +%s)
    preparar_volumen "$NOMBRE-datos" || exit 1
    docker run -d --name "$NOMBRE" --memory "$MEMORIA" --shm-size 256m -p "127.0.0.1:$PUERTO:5432" \
      -v "$NOMBRE-datos:/var/lib/postgresql/data" -v "$WAL:/backup/wal:ro" "$IMAGEN" \
      postgres -c shared_preload_libraries=citus,pg_stat_statements -c wal_level=logical -c archive_mode=off -c max_connections=100 -c hot_standby=on >/dev/null || exit 1
    echo -n "Reproduciendo WAL"
    for _ in $(seq 1 600); do
      if docker exec "$NOMBRE" psql -X -U guilda -d postgres -At -c "select not pg_is_in_recovery()" 2>/dev/null | grep -q t; then
        echo; echo "Instancia lista en $(( $(date +%s) - inicio )) s: postgresql://guilda:<contraseña>@127.0.0.1:$PUERTO/postgres"
        docker exec "$NOMBRE" psql -X -U guilda -d postgres -At -c "select 'recuperada hasta: '||coalesce(pg_last_xact_replay_timestamp()::text, '(sin transacciones reproducidas)')" 2>/dev/null
        exit 0
      fi
      echo -n "."; sleep 1
    done
    echo; echo "La recuperación no terminó en 10 min; mira: docker logs $NOMBRE" >&2; exit 1 ;;
  volumen)
    [ -n "$DESTINO" ] || { echo "Define GUILDA_PG_BACKUPS." >&2; exit 2; }
    docker volume inspect "$VOLUMEN_NOMBRE" >/dev/null 2>&1 && { echo "El volumen $VOLUMEN_NOMBRE ya existe: elige otro nombre (no se sobrescribe nada)." >&2; exit 2; }
    preparar_volumen "$VOLUMEN_NOMBRE" || exit 1
    echo "Volumen $VOLUMEN_NOMBRE listo (con recovery.signal): al arrancar el contenedor con él, PostgreSQL reproduce el WAL de $WAL y se promueve solo." ;;
  quitar)
    docker rm -f "${1:-$NOMBRE}" >/dev/null 2>&1; docker volume rm "${1:-$NOMBRE}-datos" >/dev/null 2>&1; echo "Instancia ${1:-$NOMBRE} retirada." ;;
  *) sed -n 2,15p "$0"; exit 2 ;;
esac
