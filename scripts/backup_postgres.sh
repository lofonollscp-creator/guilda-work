#!/usr/bin/env bash
# Copias FÍSICAS de la base de datos de la aplicación (PostgreSQL + Citus), para recuperarla entera o a un instante concreto (fase 10; ver HOSTING.md §9.4 y
# docs/runbooks-postgresql.md). Se apoya en el archivo continuo de WAL que ya hace el propio contenedor (archive_command → $GUILDA_PG_BACKUPS/wal, RPO ≤ 5 min):
#
#   scripts/backup_postgres.sh base      copia base completa (pg_basebackup) + punto de restauración de Citus; la deja en $GUILDA_PG_BACKUPS/base/
#   scripts/backup_postgres.sh limpiar   retención: se conservan las últimas $PG_BASES_CONSERVADAS (7) copias base y el WAL desde la más antigua
#   scripts/backup_postgres.sh estado    resumen (y data/backups/pg_estado.json, que lee el panel Salud)
#   scripts/backup_postgres.sh todo      base + limpiar + estado (lo que lanza deploy/postgres-backup.timer cada noche)
#
# Variables: GUILDA_PG_BACKUPS (obligatoria, carpeta en OTRO disco), PG_CONTENEDOR (guilda-work-postgres-app), PG_USUARIO (guilda), PG_BASE (guilda),
# PG_BASES_CONSERVADAS (7), GUILDA_BACKUPS_DIR (carpeta del estado; por defecto data/backups), PG_PERMITIR_MISMO_DISCO=1 (solo para pruebas).
# Las copias llevan los datos de TODOS los despachos sin cifrar: Restic (scripts/backup_restic.sh) las cifra al llevarlas fuera de esa carpeta.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${GUILDA_ENV_FILE:-/etc/guilda-work.env}"
[ -f "$ENV_FILE" ] && { set -a; source "$ENV_FILE" 2>/dev/null; set +a; }
CONTENEDOR="${PG_CONTENEDOR:-guilda-work-postgres-app}"
USUARIO="${PG_USUARIO:-guilda}"
BASE="${PG_BASE:-guilda}"
CONSERVAR="${PG_BASES_CONSERVADAS:-7}"
DESTINO="${GUILDA_PG_BACKUPS:-}"
ESTADO_DIR="${GUILDA_BACKUPS_DIR:-$REPO/data/backups}"
ESTADO="$ESTADO_DIR/pg_estado.json"

[ -n "$DESTINO" ] || { echo "Define GUILDA_PG_BACKUPS (carpeta en otro disco)." >&2; exit 2; }
if [ "${PG_PERMITIR_MISMO_DISCO:-0}" != "1" ]; then
  _e="$DESTINO"; while [ ! -e "$_e" ]; do _e="$(dirname "$_e")"; done
  [ "$(findmnt -n -o TARGET -T "$_e" 2>/dev/null)" = "/" ] && { echo "$DESTINO está en el disco principal (¿segundo disco sin montar?). No se hace nada." >&2; exit 2; }
fi
mkdir -p "$DESTINO/base" "$DESTINO/wal" "$ESTADO_DIR"
psql_c() { docker exec -i "$CONTENEDOR" psql -X -U "$USUARIO" -d "$BASE" -At -v ON_ERROR_STOP=1 "$@"; }

escribir_estado() {   # $1 = ok|error  $2 = detalle
  GUILDA_ESTADO="$ESTADO" GUILDA_DESTINO="$DESTINO" GUILDA_RES="$1" GUILDA_DET="${2:-}" python3 - <<'PY'
import json, os, glob, time
from datetime import datetime
ruta, destino = os.environ["GUILDA_ESTADO"], os.environ["GUILDA_DESTINO"]
try:
    estado = json.load(open(ruta))
except Exception:
    estado = {}
bases = sorted(glob.glob(os.path.join(destino, "base", "base-*.tar.gz")))
estado.update({"bases": len(bases), "tamano_bases": sum(os.path.getsize(b) for b in bases),
               "tamano_wal": sum(os.path.getsize(f) for f in glob.glob(os.path.join(destino, "wal", "*")) if os.path.isfile(f)), "actualizado": datetime.now().isoformat(timespec="seconds")})
if os.environ["GUILDA_RES"] == "ok" and bases:
    estado.update({"ultima_base": os.path.basename(bases[-1]), "ultimo_ok": datetime.fromtimestamp(os.path.getmtime(bases[-1])).isoformat(timespec="seconds"), "error": None})
elif os.environ["GUILDA_RES"] == "error":
    estado.update({"error": os.environ["GUILDA_DET"], "ultimo_error": datetime.now().isoformat(timespec="seconds")})
json.dump(estado, open(ruta + ".tmp", "w"), indent=1)
os.replace(ruta + ".tmp", ruta)
PY
}

base() {
  docker inspect -f '{{.State.Running}}' "$CONTENEDOR" 2>/dev/null | grep -q true || { echo "El contenedor $CONTENEDOR no está en marcha." >&2; escribir_estado error "contenedor parado"; return 1; }
  local sello nombre punto tmp inicio
  sello="$(date +%Y%m%d-%H%M%S)"; nombre="base-$sello.tar.gz"; punto="base_$sello"; tmp="$DESTINO/base/.$nombre.tmp"; inicio=$(date +%s)
  # Punto de restauración de Citus: con varios nodos, cada uno se recupera hasta ESTE nombre y quedan coherentes entre sí (en un nodo no hace daño).
  psql_c -c "select citus_create_restore_point('$punto')" >/dev/null 2>&1 || true
  if ! docker exec "$CONTENEDOR" pg_basebackup -U "$USUARIO" -D - -Ft -X none -c fast -l "$nombre" 2>"$DESTINO/base/.$nombre.log" | gzip -1 > "$tmp"; then
    escribir_estado error "pg_basebackup falló: $(tail -1 "$DESTINO/base/.$nombre.log")"; rm -f "$tmp"; echo "pg_basebackup falló." >&2; return 1
  fi
  # comprobaciones baratas: el gzip y el tar se leen enteros y traen lo imprescindible; la prueba de verdad es el simulacro de restauración
  if ! gzip -t "$tmp" || ! tar tzf "$tmp" backup_label PG_VERSION >/dev/null 2>&1; then
    escribir_estado error "la copia $nombre no se puede leer o está incompleta"; rm -f "$tmp"; echo "La copia no es válida." >&2; return 1
  fi
  local wal_inicial
  wal_inicial="$(tar xzOf "$tmp" backup_label | sed -n 's/^START WAL LOCATION: .*(file \([0-9A-F]*\)).*/\1/p')"
  mv "$tmp" "$DESTINO/base/$nombre"
  printf '{"nombre": "%s", "wal_inicial": "%s", "punto_restauracion": "%s", "segundos": %s, "bytes": %s}\n' "$nombre" "$wal_inicial" "$punto" "$(( $(date +%s) - inicio ))" "$(stat -c %s "$DESTINO/base/$nombre")" > "$DESTINO/base/$nombre.json"
  rm -f "$DESTINO/base/.$nombre.log"
  # el WAL que cierra la copia tiene que estar archivado antes de darla por buena
  psql_c -c "select pg_switch_wal()" >/dev/null 2>&1
  echo "Copia base $nombre ($(du -h "$DESTINO/base/$nombre" | cut -f1), WAL inicial $wal_inicial, $(( $(date +%s) - inicio )) s)"
  escribir_estado ok
}

limpiar() {
  local bases viejas conservadas minimo
  mapfile -t bases < <(ls -1 "$DESTINO"/base/base-*.tar.gz 2>/dev/null | sort)
  if [ "${#bases[@]}" -gt "$CONSERVAR" ]; then
    for b in "${bases[@]:0:${#bases[@]}-CONSERVAR}"; do rm -f "$b" "$b.json"; echo "Retirada $(basename "$b")"; done
  fi
  mapfile -t conservadas < <(ls -1 "$DESTINO"/base/base-*.tar.gz 2>/dev/null | sort)
  [ "${#conservadas[@]}" -gt 0 ] || return 0
  minimo="$(sed -n 's/.*"wal_inicial": "\([0-9A-F]*\)".*/\1/p' "${conservadas[0]}.json" 2>/dev/null)"
  if [ -n "$minimo" ]; then
    # el WAL anterior al de la copia más antigua que se conserva ya no sirve para nada
    docker exec "$CONTENEDOR" pg_archivecleanup -d /backup/wal "$minimo" 2>&1 | grep -c removing | sed 's/^/WAL retirados: /'
  fi
}

estado() {
  escribir_estado "${1:-ok}" >/dev/null 2>&1
  python3 - "$ESTADO" <<'PY'
import json, sys
e = json.load(open(sys.argv[1]))
print(f"copias base: {e.get('bases')} ({e.get('tamano_bases', 0)/1e6:.0f} MB) · última: {e.get('ultima_base')} ({e.get('ultimo_ok')}) · WAL archivado: {e.get('tamano_wal', 0)/1e6:.0f} MB · error: {e.get('error')}")
PY
  psql_c -c "select 'archivador: último WAL '||coalesce(last_archived_wal,'-')||' a las '||coalesce(last_archived_time::text,'-')||' · fallos: '||failed_count||coalesce(' (último '||last_failed_time||')','') from pg_stat_archiver" 2>/dev/null
}

case "${1:-}" in
  base) base ;;
  limpiar) limpiar ;;
  estado) estado ;;
  todo) base && limpiar; r=$?; estado >/dev/null; exit $r ;;
  *) sed -n 2,12p "$0"; exit 2 ;;
esac
