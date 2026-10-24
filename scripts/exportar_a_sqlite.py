#!/usr/bin/env python3
"""VUELTA ATRÁS del corte a PostgreSQL (fase 11): construye `registro.db` y `backoffice.db` NUEVOS desde la base de datos PostgreSQL viva, con todo lo escrito desde el corte.

  scripts/exportar_a_sqlite.py --url postgresql://guilda:…@127.0.0.1:5433/guilda --salida /mnt/…/vuelta/registro.db --backoffice-salida /mnt/…/vuelta/backoffice.db

* Solo LEE PostgreSQL (hace falta el superusuario `guilda`: `guilda_plataforma` no ve el esquema `backoffice`). No sobrescribe: los ficheros de salida no pueden existir.
* Comprueba cada tabla (filas y suma de control por columna), `integrity_check` y `foreign_key_check`. Código de salida 0 correcto, 1 hay discrepancias, 2 error.
* Se ejecuta con la aplicación PARADA (para que nadie escriba durante la exportación). Después: copiar los dos ficheros a `data/`, quitar GUILDA_DB_ENGINE de /etc/guilda-work.env y arrancar
  (docs/runbooks-postgresql.md, «Vuelta atrás»). Ensayado en scripts/ensayo_corte_postgres.py.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ["GUILDA_DB_ENGINE"] = "sqlite"                    # init_db() tiene que crear el esquema de SQLite aunque el entorno diga postgres
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("GUILDA_PG_ADMIN_URL"), help="URL del superusuario de PostgreSQL, con la base de la aplicación (por defecto, GUILDA_PG_ADMIN_URL)")
    ap.add_argument("--salida", required=True, help="registro.db nuevo")
    ap.add_argument("--backoffice-salida", help="backoffice.db nuevo (si se omite, no se exporta el backoffice)")
    ap.add_argument("--informe", help="guardar el informe JSON aquí")
    args = ap.parse_args(argv)
    if not args.url:
        ap.error("falta --url (o GUILDA_PG_ADMIN_URL en el entorno)")
    import psycopg
    from app.bd import exportar_sqlite
    try:
        with psycopg.connect(args.url, autocommit=True) as pg:
            informe = exportar_sqlite.exportar(pg, args.salida, backoffice=args.backoffice_salida, informar=lambda t, n: print(f"  {t}: {n}", flush=True))
    except exportar_sqlite.ErrorDeExportacion as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    filas = sum(informe["tablas"].values())
    print(f"{len(informe['tablas'])} tablas, {filas:,} filas en {informe['segundos']} s · integrity_check: {informe['integrity_check']} · foreign_key_check: {informe['foreign_key_check']} filas con clave rota".replace(",", "."))
    if informe.get("plataforma_conservadas"):
        print("  filas del despacho «Plataforma» que no admiten NULL y se conservan con tenant_id = 0:", informe["plataforma_conservadas"])
    if informe.get("sin_exportar"):
        print("  tablas de PostgreSQL que SQLite no tiene (no se exportan):", ", ".join(informe["sin_exportar"]))
    for d in informe["discrepancias"]:
        print(f"  DISCREPANCIA: {d}", file=sys.stderr)
    if args.informe:
        Path(args.informe).write_text(json.dumps(informe, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        os.chmod(args.informe, 0o600)
    print("RESULTADO:", "todo cuadra" if informe["ok"] else f"{len(informe['discrepancias'])} discrepancias")
    return 0 if informe["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
