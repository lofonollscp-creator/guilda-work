#!/usr/bin/env bash
# Maneja la instancia de ENSAYO de PostgreSQL + Citus (docker-compose.postgres-citus.yml).
# No toca ninguna base de datos de producción ni los otros contenedores.
#
#   scripts/pg_ensayo.sh construir        construye la imagen (Citus + pgvector)
#   scripts/pg_ensayo.sh arrancar         levanta el contenedor y espera a que esté sano
#   scripts/pg_ensayo.sh estado           versión, extensiones y salud del clúster
#   scripts/pg_ensayo.sh url              imprime la URL de conexión de ensayo (para GUILDA_DATABASE_URL / GUILDA_TEST_PG_URL)
#   scripts/pg_ensayo.sh psql [args]      abre psql (o ejecuta lo que pases) en la base 'postgres'
#   scripts/pg_ensayo.sh crear NOMBRE     crea una base vacía con las extensiones y mide el tiempo
#   scripts/pg_ensayo.sh borrar NOMBRE    borra una base de ensayo
#   scripts/pg_ensayo.sh experimentos     ejecuta los experimentos de deploy/postgres-citus/experimentos
#                                         y guarda el informe en data/pg-ensayo/
#   scripts/pg_ensayo.sh parar            para el contenedor (conserva los datos)
#   scripts/pg_ensayo.sh destruir         borra contenedor Y volumen del ensayo
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE=(docker compose -f "$REPO/docker-compose.postgres-citus.yml")
CONTENEDOR=guilda-pg-ensayo
psql_en() { docker exec -i "$CONTENEDOR" psql -X -U guilda -v ON_ERROR_STOP=0 "$@"; }

caso="${1:-}"; shift || true
case "$caso" in
  construir) "${COMPOSE[@]}" build ;;
  arrancar)  "${COMPOSE[@]}" up -d --wait ;;
  parar)     "${COMPOSE[@]}" stop ;;
  destruir)
    echo "Se borrarán el contenedor y el volumen del ENSAYO (nada más)."
    "${COMPOSE[@]}" down -v ;;
  estado)
    psql_en -d postgres -At -c "select 'postgres '||current_setting('server_version')" \
      -c "select 'citus '||citus_version()" \
      -c "select 'extensiones: '||string_agg(extname||' '||extversion, ', ' order by extname) from pg_extension" \
      -c "select 'nodos activos: '||count(*) from citus_get_active_worker_nodes()" \
      -c "select 'shard_count: '||current_setting('citus.shard_count')"
    docker stats --no-stream --format 'memoria: {{.MemUsage}} (límite del contenedor)' "$CONTENEDOR" ;;
  url)       echo "postgresql://guilda:${PG_ENSAYO_PASSWORD:-ensayo}@127.0.0.1:55432/postgres" ;;
  psql)      docker exec -it "$CONTENEDOR" psql -X -U guilda -d postgres "$@" ;;
  crear)
    nombre="${1:?falta NOMBRE}"
    [[ "$nombre" =~ ^[a-z][a-z0-9_]{0,40}$ ]] || { echo "nombre no válido"; exit 2; }
    ini=$(date +%s.%N)
    psql_en -d postgres -q -c "create database $nombre"
    psql_en -d "$nombre" -q -c "create extension citus" -c "create extension vector" \
      -c "create extension unaccent" -c "create extension pg_trgm"
    fin=$(date +%s.%N)
    printf 'base %s creada en %.2f s\n' "$nombre" "$(echo "$fin - $ini" | bc)" ;;
  borrar)
    nombre="${1:?falta NOMBRE}"
    [[ "$nombre" =~ ^[a-z][a-z0-9_]{0,40}$ ]] || { echo "nombre no válido"; exit 2; }
    ini=$(date +%s.%N)
    psql_en -d postgres -q -c "drop database if exists $nombre with (force)"
    fin=$(date +%s.%N)
    printf 'base %s borrada en %.2f s\n' "$nombre" "$(echo "$fin - $ini" | bc)" ;;
  experimentos)
    mkdir -p "$REPO/data/pg-ensayo"
    informe="$REPO/data/pg-ensayo/informe-$(date +%Y%m%d-%H%M%S).txt"
    psql_en -d postgres -q -c "drop database if exists guilda_exp with (force)" -c "create database guilda_exp"
    for f in "$REPO"/deploy/postgres-citus/experimentos/*.sql; do
      echo "######## $(basename "$f")"
      psql_en -d guilda_exp -a -f - < "$f" 2>&1
    done | tee "$informe"
    {
      echo "######## clonado con plantilla (1: directo)"
      ini=$(date +%s.%N)
      psql_en -d postgres -c "create database exp_clon template guilda_exp" 2>&1 || true
      fin=$(date +%s.%N)
      printf 'create database ... template: %.2f s\n' "$(echo "$fin - $ini" | bc)"
      psql_en -d postgres -q -c "drop database if exists exp_clon with (force)" 2>&1 || true
      echo "######## clonado con plantilla (2: sin conexiones, ALLOW_CONNECTIONS false)"
      ini=$(date +%s.%N)
      psql_en -d postgres -q -c "alter database guilda_exp allow_connections false" \
        -c "select pg_terminate_backend(pid) from pg_stat_activity where datname='guilda_exp' and pid<>pg_backend_pid()" >/dev/null 2>&1
      psql_en -d postgres -c "create database exp_clon template guilda_exp" 2>&1 || true
      fin=$(date +%s.%N)
      printf 'create database ... template (variante 2): %.2f s\n' "$(echo "$fin - $ini" | bc)"
      psql_en -d postgres -q -c "alter database guilda_exp allow_connections true" 2>&1 || true
      echo "-- el clon, ¿conserva las tablas distribuidas y responde?"
      psql_en -d exp_clon -At -c "select count(*) || ' tablas citus en el clon' from citus_tables" \
        -c "select count(*) || ' filas de tareas en el clon' from tareas" 2>&1 || true
      ini=$(date +%s.%N)
      psql_en -d postgres -q -c "drop database if exists exp_clon with (force)" 2>&1 || true
      fin=$(date +%s.%N)
      printf 'borrado del clon: %.2f s\n' "$(echo "$fin - $ini" | bc)"
    } | tee -a "$informe"
    echo; echo "Informe guardado en: $informe" ;;
  *) sed -n 2,14p "$0"; exit 2 ;;
esac
