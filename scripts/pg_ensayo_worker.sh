#!/usr/bin/env bash
# Segundo nodo de Citus para el ensayo de crecimiento (docker-compose.postgres-citus-worker.yml). Requiere la instancia de ensayo arrancada (scripts/pg_ensayo.sh arrancar).
# No toca ninguna base de datos de producción ni los otros contenedores.
#
#   scripts/pg_ensayo_worker.sh arrancar            levanta el worker y espera a que esté sano
#   scripts/pg_ensayo_worker.sh unir BASE           prepara BASE en el worker y lo añade al clúster de BASE (el coordinador pasa a anunciarse por su nombre de contenedor)
#   scripts/pg_ensayo_worker.sh estado BASE         nodos y fragmentos por nodo
#   scripts/pg_ensayo_worker.sh reequilibrar BASE   mueve fragmentos al nuevo nodo en segundo plano (citus_rebalance_start) y espera; con el tráfico de scripts/pg_ensayo_rebalanceo.py
#   scripts/pg_ensayo_worker.sh drenar BASE        saca todos los fragmentos del worker (vuelven al coordinador) en segundo plano y espera
#   scripts/pg_ensayo_worker.sh parar | destruir    para el worker (conserva datos) | lo borra con su volumen
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE=(docker compose -f "$REPO/docker-compose.postgres-citus-worker.yml")
COORD=guilda-pg-ensayo
WORKER=guilda-pg-ensayo-worker
psql_c() { docker exec -i "$COORD" psql -X -U guilda -v ON_ERROR_STOP=1 "$@"; }
psql_w() { docker exec -i "$WORKER" psql -X -U guilda -v ON_ERROR_STOP=1 "$@"; }
caso="${1:-}"; shift || true
base="${1:-}"
valida() { [[ "$base" =~ ^[a-z][a-z0-9_]{0,40}$ ]] || { echo "nombre de base no válido"; exit 2; }; }
case "$caso" in
  arrancar) "${COMPOSE[@]}" up -d --wait ;;
  parar)    "${COMPOSE[@]}" stop ;;
  destruir) echo "Se borrarán el worker y su volumen (nada más)."; "${COMPOSE[@]}" down -v ;;
  unir)
    valida
    psql_w -d postgres -q -c "drop database if exists $base with (force)" -c "create database $base"
    psql_w -d "$base" -q -c "create extension citus" -c "create extension unaccent" -c "create extension pg_trgm"
    # el coordinador se anuncia por su nombre de contenedor (el worker tiene que poder llegar a él); si ya se registró como «localhost» se renombra
    psql_c -d "$base" -At -c "select citus_update_node(nodeid, '$COORD', 5432) from pg_dist_node where groupid = 0 and nodename <> '$COORD'" \
           -c "select citus_set_coordinator_host('$COORD', 5432) where not exists (select 1 from pg_dist_node where groupid = 0)" \
           -c "select citus_add_node('$WORKER', 5432)" \
           -c "select nodeid, nodename, isactive, shouldhaveshards from pg_dist_node order by nodeid" ;;
  estado)
    valida
    psql_c -d "$base" -At -c "select 'nodo '||nodename||' activo='||isactive||' con_fragmentos='||shouldhaveshards from pg_dist_node order by nodeid" \
      -c "select 'fragmentos en '||nodename||': '||count(*) from pg_dist_shard_placement group by nodename order by nodename" ;;
  reequilibrar)
    valida
    ini=$(date +%s.%N)
    psql_c -d "$base" -At -c "select citus_rebalance_start(rebalance_strategy := 'by_shard_count')"
    psql_c -d "$base" -At -c "select citus_rebalance_wait()"
    fin=$(date +%s.%N)
    printf 'reequilibrado en %.1f s\n' "$(echo "$fin - $ini" | bc)"
    "$0" estado "$base" ;;
  drenar)
    valida
    ini=$(date +%s.%N)
    psql_c -d "$base" -At -c "select citus_drain_node('$WORKER', 5432, shard_transfer_mode := 'auto')"
    fin=$(date +%s.%N)
    printf 'drenado en %.1f s\n' "$(echo "$fin - $ini" | bc)"
    "$0" estado "$base" ;;
  *) sed -n 2,14p "$0"; exit 2 ;;
esac
