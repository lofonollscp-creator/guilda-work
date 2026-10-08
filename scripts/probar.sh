#!/usr/bin/env bash
# Ejecuta la suite de tests en una COPIA aislada del repo (nunca contra los datos
# reales) y la borra al terminar, pase lo que pase.
#
#   scripts/probar.sh                      suite completa (con Kratos real en Docker)
#   scripts/probar.sh --rapida             sin Kratos ni Docker: solo los tests que no inician sesión real
#   scripts/probar.sh --perfil             mide tiempos/consultas de las pantallas con datos sintéticos (no ejecuta tests)
#   scripts/probar.sh --carga              N usuarios a la vez (lecturas y escrituras) sobre datos sintéticos; ver scripts/prueba_carga.py
#   scripts/probar.sh -n 2                 con 2 procesos en paralelo (cada uno arranca su Kratos)
#   scripts/probar.sh tests/test_x.py -k y cualquier otro argumento de pytest
#
# Variables: GUILDA_TMP (dónde crear la copia, por defecto /tmp), GUILDA_MIN_LIBRE_MB
# (espacio libre mínimo, por defecto 1500).
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${GUILDA_TMP:-/tmp}"
MIN_LIBRE_MB="${GUILDA_MIN_LIBRE_MB:-1500}"
WORKERS=""
RAPIDA=0
PERFIL=0
CARGA=0
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --rapida) RAPIDA=1 ;;
    --perfil) PERFIL=1 ;;
    --carga) CARGA=1 ;;
    -n) WORKERS="$2"; shift ;;
    *) ARGS+=("$1") ;;
  esac
  shift
done

# 1. Copias olvidadas de ejecuciones anteriores (más de 2 h y sin pytest vivo): fuera.
find "$BASE" -maxdepth 1 -type d -name 'guilda-probar.*' -mmin +120 2>/dev/null | while read -r vieja; do
  if ! pgrep -f "$vieja" >/dev/null 2>&1; then rm -rf "$vieja"; fi
done

# 2. Espacio suficiente (el /tmp del VPS es un tmpfs pequeño).
libre_mb=$(df -Pm "$BASE" | awk 'NR==2 {print $4}')
if [ "$libre_mb" -lt "$MIN_LIBRE_MB" ]; then
  echo "Solo quedan ${libre_mb} MB libres en $BASE (hacen falta ${MIN_LIBRE_MB}). Libera espacio o usa GUILDA_TMP." >&2
  exit 2
fi

# 3. Copia: solo ficheros del repo (tracked + nuevos no ignorados), sin data/ ni builds.
DESTINO="$(mktemp -d "$BASE/guilda-probar.XXXXXX")"
trap 'rm -rf "$DESTINO"' EXIT INT TERM
cd "$REPO"
git ls-files -z --cached --others --exclude-standard | grep -zv -e '^data/' -e '^mobile/build/' | rsync -a --files-from=- --from0 ./ "$DESTINO/"
ln -s "$REPO/.venv" "$DESTINO/.venv"
cd "$DESTINO"

if [ "$CARGA" = 1 ]; then
  nice -n 5 .venv/bin/python scripts/prueba_carga.py "${ARGS[@]}"
  exit $?
fi

if [ "$PERFIL" = 1 ]; then
  nice -n 10 .venv/bin/python scripts/perfil_pantallas.py "${ARGS[@]}"
  exit $?
fi

OPCIONES=(-q -p no:cacheprovider "--basetemp=$DESTINO/_bt")
[ -n "$WORKERS" ] && OPCIONES+=(-n "$WORKERS")
[ "$RAPIDA" = 1 ] && export GUILDA_SIN_KRATOS=1

nice -n 10 .venv/bin/python -m pytest "${OPCIONES[@]}" "${ARGS[@]}"
exit $?
