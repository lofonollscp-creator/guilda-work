#!/usr/bin/env bash
# Prueba de RESTAURACIÓN de la copia de Restic (la que importa: una copia que no se puede restaurar no es una copia). Una vez al mes
# (restic-verificacion.timer) hace de verdad lo que haría un desastre, pero en una carpeta temporal y sin tocar producción:
#   1. restic check con lectura del 10 % de los datos;
#   2. restaura registro.db y comprueba su integridad y que tiene usuarios;
#   3. restaura el volcado de Kratos y lo carga en un Postgres desechable SIN red (comprueba que hay identidades);
#   4. restaura un volumen (Vaultwarden) y comprueba que no está vacío.
# Deja el resultado en data/backups/restic_estado_restauracion.json (lo lee el panel Salud). Termina con error si algo falla.
#
# Uso: scripts/verificar_restauracion_restic.sh   (como root; usa /etc/restic.env igual que backup_restic.sh)
set -uo pipefail

ENV_FILE="${RESTIC_ENV_FILE:-/etc/restic.env}"
if [ -f "$ENV_FILE" ]; then set -a; source "$ENV_FILE"; set +a; fi
if [ -z "${RESTIC_REPOSITORY:-}" ] || [ -z "${RESTIC_PASSWORD:-}" ]; then
  echo "RESTIC_REPOSITORY/RESTIC_PASSWORD no configuradas (¿falta $ENV_FILE?)." >&2; exit 1
fi

IMAGEN="${RESTIC_IMAGEN:-restic/restic@sha256:9940e6c7421ab3a21ee9fdc4e91596d04c792b600d31b102696c75cbf3ac4481}"
IMAGEN_PG="${RESTIC_IMAGEN_PG:-postgres:16-alpine@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777}"
REPO_APP="${GUILDA_REPO:-/home/guilda/guilda-work}"
ESTADO="${GUILDA_RESTIC_ESTADO_RESTAURACION:-$REPO_APP/data/backups/restic_estado_restauracion.json}"
TRABAJO="$(mktemp -d /var/tmp/restic-verificacion.XXXXXX)"
CONTENEDOR_PG="restic-verificacion-pg-$$"
RESULTADOS=()
FALLOS=0

limpiar() { docker rm -f "$CONTENEDOR_PG" >/dev/null 2>&1; rm -rf "$TRABAJO"; }
trap limpiar EXIT INT TERM

R() { docker run --rm -v restic-cache:/cache -v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY" -v "$TRABAJO:/out" -e RESTIC_REPOSITORY -e RESTIC_PASSWORD "$IMAGEN" "$@"; }
registrar() { RESULTADOS+=("$1=$2"); [ "$2" = "ok" ] || FALLOS=$((FALLOS + 1)); echo "  $1: $2"; }

echo "== 1. Integridad del repositorio (10 % de los datos) =="
if R check --read-data-subset=10% -q >/dev/null 2>&1; then registrar integridad ok; else registrar integridad "error: restic check falló"; fi

echo "== 2. registro.db =="
if R restore latest --tag host --include /staging/registro.db --target /out/host -q >/dev/null 2>&1 && [ -f "$TRABAJO/host/staging/registro.db" ]; then
  resultado="$(python3 -I - "$TRABAJO/host/staging/registro.db" <<'PY'
import sqlite3, sys
c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True)
integridad = c.execute("pragma integrity_check").fetchone()[0]
usuarios = c.execute("select count(*) from usuarios").fetchone()[0]
print("ok" if integridad == "ok" and usuarios > 0 else f"error: integridad={integridad} usuarios={usuarios}")
PY
  )"
  registrar registro_db "${resultado:-error: sin resultado}"
else
  registrar registro_db "error: no se pudo restaurar"
fi

echo "== 3. Volcado de Kratos en un Postgres desechable =="
if R restore latest --tag pg-kratos --target /out/kratos -q >/dev/null 2>&1; then
  volcado="$(find "$TRABAJO/kratos" -name '*.sql' | head -1)"
  if [ -n "$volcado" ] && docker run -d --rm --name "$CONTENEDOR_PG" --network none -e POSTGRES_PASSWORD=verificacion -v "$volcado:/volcado.sql:ro" "$IMAGEN_PG" >/dev/null 2>&1; then
    for _ in $(seq 1 30); do docker exec "$CONTENEDOR_PG" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
    if docker exec "$CONTENEDOR_PG" psql -U postgres -v ON_ERROR_STOP=0 -q -f /volcado.sql >/dev/null 2>&1; then
      n="$(docker exec "$CONTENEDOR_PG" psql -U postgres -d kratos -At -c 'select count(*) from identities' 2>/dev/null || echo 0)"
      if [ "${n:-0}" -gt 0 ] 2>/dev/null; then registrar kratos "ok"; else registrar kratos "error: la base restaurada no tiene identidades"; fi
    else
      registrar kratos "error: psql no pudo cargar el volcado"
    fi
    docker rm -f "$CONTENEDOR_PG" >/dev/null 2>&1
  else
    registrar kratos "error: no hay volcado o no arrancó el Postgres de prueba"
  fi
else
  registrar kratos "error: no se pudo restaurar el volcado"
fi

echo "== 4. Volumen de Vaultwarden =="
if R restore latest --tag vol-vaultwarden-data --target /out/vault -q >/dev/null 2>&1; then
  n="$(find "$TRABAJO/vault" -type f | wc -l)"
  if [ "$n" -gt 0 ]; then registrar vaultwarden ok; else registrar vaultwarden "error: el volumen restaurado está vacío"; fi
else
  registrar vaultwarden "error: no se pudo restaurar el volumen"
fi

FECHA="$(date -Is)"
mkdir -p "$(dirname "$ESTADO")"
python3 -I - "$ESTADO" "$FECHA" "$FALLOS" "${RESULTADOS[@]}" <<'PY'
import json, sys
ruta, fecha, fallos, *resultados = sys.argv[1:]
comprobaciones = dict(r.split("=", 1) for r in resultados)
estado = {"fecha": fecha, "ok": int(fallos) == 0, "comprobaciones": comprobaciones}
try:
    anterior = json.load(open(ruta))
except Exception:
    anterior = {}
estado["ultimo_ok"] = fecha if estado["ok"] else anterior.get("ultimo_ok")
json.dump(estado, open(ruta, "w"), indent=1, ensure_ascii=False)
PY
chown --reference="$REPO_APP/data" "$ESTADO" 2>/dev/null || true

if [ "$FALLOS" -gt 0 ]; then echo "Prueba de restauración CON $FALLOS fallo(s)." >&2; exit 1; fi
echo "Prueba de restauración correcta."
