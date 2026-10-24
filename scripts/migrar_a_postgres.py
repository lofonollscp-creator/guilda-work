#!/usr/bin/env python3
"""Migra los datos de `registro.db` (SQLite) a PostgreSQL y ejecuta los controles (fase 8 del plan, docs/plan-migracion-postgresql-citus.md).

  scripts/migrar_a_postgres.py --origen data/registro.db --url postgresql://guilda:***@127.0.0.1:55432/gw_ensayo1 --recrear-base --informe data/pg-ensayo/ensayo1.json

* SOLO LEE las bases de SQLite (las abre en modo de solo lectura y trabaja sobre una copia temporal). `backoffice.db` (la base propia del backoffice: administradores, auditoría,
  cobros…) se carga en el esquema `backoffice` de la misma base de datos; se toma de `--backoffice` o, si no se indica, de la carpeta de `--origen`.
* Re-ejecutable: con `--recrear-base` borra y vuelve a crear la base de destino (solo si se llama `gw_*`/`ensayo*`, o con `--forzar`); sin él se niega si la base ya tiene despachos.
* Necesita un superusuario de PostgreSQL (desactiva triggers y claves foráneas durante la carga y las comprueba a mano después).
* Código de salida: 0 todo cuadra, 1 hay discrepancias en los controles, 2 error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


def _preparar_base(url: str, esquema: str) -> None:
    """Extensiones y, en Citus, el coordinador como nodo con fragmentos. Idempotente: sirve igual para una base recién creada que para la `guilda` que crea el contenedor de producción."""
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    nombre = conninfo_to_dict(url)["dbname"]
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(f'ALTER DATABASE "{nombre}" SET timezone TO \'Europe/Madrid\'')
        for extension in (["citus"] if esquema == "citus" else []) + ["unaccent", "pg_trgm", "pg_stat_statements"]:
            c.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")
        if esquema == "citus" and not c.execute("SELECT 1 FROM pg_dist_node WHERE groupid = 0").fetchone():
            c.execute("SELECT citus_set_coordinator_host('localhost', 5432)")
            c.execute("SELECT citus_set_node_property('localhost', 5432, 'shouldhaveshards', true)")


def _crear_base(url: str, esquema: str) -> None:
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    nombre = conninfo_to_dict(url)["dbname"]
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", nombre) or nombre == "postgres":
        raise SystemExit(f"nombre de base no válido para recrear: {nombre!r}")
    with psycopg.connect(make_conninfo(url, dbname="postgres"), autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{nombre}"')
    _preparar_base(url, esquema)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--origen", required=True, help="registro.db (SQLite)")
    ap.add_argument("--url", default=os.environ.get("GUILDA_PG_ADMIN_URL"), help="URL de PostgreSQL de un superusuario, con la base de destino (por defecto, GUILDA_PG_ADMIN_URL)")
    ap.add_argument("--esquema", choices=("multitenant", "citus"), default="citus")
    ap.add_argument("--recrear-base", action="store_true", help="borra y crea la base de destino antes de cargar")
    ap.add_argument("--forzar", action="store_true", help="permite recrear una base cuyo nombre no empieza por gw_ ni ensayo")
    ap.add_argument("--backoffice", help="backoffice.db (por defecto, la de la misma carpeta que --origen, si existe)")
    ap.add_argument("--informe", help="dónde guardar el informe JSON (por defecto data/pg-ensayo/migracion-<fecha>.json)")
    args = ap.parse_args(argv)

    if not args.url:
        ap.error("falta --url (o GUILDA_PG_ADMIN_URL en el entorno)")
    origen = Path(args.origen)
    if not origen.is_file():
        print(f"no existe {origen}", file=sys.stderr)
        return 2
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    from app.bd import esquema as esq
    from app.bd import migrar_datos, verificar_migracion

    nombre = conninfo_to_dict(args.url).get("dbname", "")
    inicio = time.monotonic()
    try:
        if args.recrear_base:
            if not (nombre.startswith("gw_") or nombre.startswith("ensayo")) and not args.forzar:
                print(f"se niega a recrear {nombre!r}: usa un nombre gw_*/ensayo* o --forzar", file=sys.stderr)
                return 2
            _crear_base(args.url, args.esquema)
        else:
            _preparar_base(args.url, args.esquema)                                                  # (la base de producción ya existe: la crea el contenedor)
        with psycopg.connect(args.url, autocommit=True) as conn:
            t0 = time.monotonic()
            from app.bd import postgres as pg
            pg.fijar_url(args.url)
            c = pg.conectar()
            try:
                creado = esq.crear_si_falta(c, args.esquema)
            finally:
                c.close()
            pg.cerrar_pool()
            if not creado:
                hay = conn.execute("SELECT count(*) FROM tenants").fetchone()[0]
                if hay > 1:
                    print("la base de destino ya tiene despachos: usa --recrear-base (la carga no mezcla datos)", file=sys.stderr)
                    return 2
            segundos_esquema = round(time.monotonic() - t0, 1)
            informe: dict = {}
            t0 = time.monotonic()
            cargadas = migrar_datos.copiar(origen, conn, informe=informe, informar=lambda t, n: print(f"  {t}: {n}", flush=True) if n else None)
            ruta_bo = Path(args.backoffice) if args.backoffice else origen.with_name("backoffice.db")
            if ruta_bo.is_file():
                bo: dict = {}
                filas_bo = migrar_datos.copiar_backoffice(ruta_bo, conn, informe=bo)
                informe["backoffice"] = bo
                informe["discrepancias"] += bo["discrepancias"]
                informe["ok"] = informe["ok"] and bo["ok"]
                cargadas = {**cargadas, **{f"backoffice.{t}": n for t, n in filas_bo.items()}}
                print(f"  backoffice.db: {sum(filas_bo.values())} filas en {len(filas_bo)} tablas")
            else:
                informe["backoffice"] = None
            informe["segundos_totales"] = round(time.monotonic() - t0, 1)
            informe["segundos_esquema"] = segundos_esquema
    except migrar_datos.ErrorDeCarga as e:
        print(f"ERROR de carga: {e}", file=sys.stderr)
        return 2
    informe.update({
        "origen": str(origen), "origen_bytes": origen.stat().st_size, "esquema": args.esquema, "base": nombre, "fecha": datetime.now().isoformat(timespec="seconds"),
        "filas": sum(cargadas.values()),
    })
    destino = Path(args.informe) if args.informe else RAIZ / "data" / "pg-ensayo" / f"migracion-{datetime.now():%Y%m%d-%H%M%S}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(informe, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.chmod(destino, 0o600)                                                                           # el informe lleva recuentos por despacho
    print(verificar_migracion.resumen(informe))
    print(f"informe: {destino}  (total {time.monotonic() - inicio:.0f} s)")
    return 0 if informe["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
