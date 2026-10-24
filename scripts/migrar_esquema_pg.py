#!/usr/bin/env python3
"""Aplica las migraciones pendientes del esquema de PostgreSQL (fase 12; app/bd/migraciones/LEEME.md). Se ejecuta en cada despliegue que traiga migraciones, ANTES de reiniciar los servicios,
con el superusuario (los servicios no son propietarios de las tablas):

  guilda_py scripts/migrar_esquema_pg.py --estado        # versión de la base, versión que espera el código y lo que falta
  guilda_py scripts/migrar_esquema_pg.py                 # aplica lo que falta, en orden

`--url` (o GUILDA_PG_ADMIN_URL). Código de salida 0 correcto, 2 error (la migración que falló no queda anotada; las anteriores sí). Las migraciones son idempotentes: se puede repetir."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("GUILDA_PG_ADMIN_URL"))
    ap.add_argument("--estado", action="store_true", help="solo mostrar el estado, sin aplicar nada")
    args = ap.parse_args(argv)
    if not args.url:
        ap.error("falta --url (o GUILDA_PG_ADMIN_URL en el entorno)")
    from app.bd import migraciones
    from app.bd import postgres as pg
    pg.fijar_url(args.url)
    conn = pg.conectar()
    try:
        try:
            actual, esperada, pendientes = migraciones.version_actual(conn), migraciones.version_esperada(), migraciones.pendientes(conn)
        except migraciones.ErrorDeMigracion as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        print(f"esquema de la base: {actual} · el código espera: {esperada} · pendientes: {pendientes or 'ninguna'} · modo: {migraciones.modo_de(conn)}")
        if args.estado or not pendientes:
            return 0
        try:
            migraciones.aplicar(conn, informar=lambda v, d: print(f"  aplicada {v}: {d}", flush=True))
        except migraciones.ErrorDeMigracion as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        print(f"esquema de la base: {migraciones.version_actual(conn)}")
        return 0
    finally:
        conn.close()
        pg.cerrar_pool()


if __name__ == "__main__":
    sys.exit(main())
