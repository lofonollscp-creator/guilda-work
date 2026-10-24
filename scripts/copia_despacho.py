#!/usr/bin/env python3
"""Exporta e importa UN despacho de la base de datos PostgreSQL (fase 10; ver app/bd/despacho_copia.py y docs/runbooks-postgresql.md).

  scripts/copia_despacho.py exportar --url postgresql://…/guilda --despacho 12 --salida /var/backups/despacho-12.tar.gz
  scripts/copia_despacho.py ver      --entrada /var/backups/despacho-12.tar.gz
  scripts/copia_despacho.py importar --url postgresql://…/guilda --entrada /var/backups/despacho-12.tar.gz [--reemplazar]

`--url` es la de un SUPERUSUARIO (desactiva triggers durante la carga). Para recuperar un despacho tras un error, exporta de la instancia restaurada a un instante anterior
(scripts/restaurar_postgres.sh) e importa en la base viva con --reemplazar: solo se toca ese despacho. Código de salida 0 correcto, 1 la comprobación final difiere, 2 error."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("accion", choices=("exportar", "importar", "ver"))
    ap.add_argument("--url")
    ap.add_argument("--despacho", type=int)
    ap.add_argument("--salida")
    ap.add_argument("--entrada")
    ap.add_argument("--reemplazar", action="store_true", help="al importar: borra antes lo que el despacho tenga en la base de destino")
    ap.add_argument("--otra-version", action="store_true", help="al importar: acepta una copia de otra versión del esquema")
    args = ap.parse_args(argv)
    from app.bd import despacho_copia as dc

    try:
        if args.accion == "ver":
            m = dc.leer_manifiesto(args.entrada)
            print(f"despacho {m['despacho']} «{m['nombre']}» · {m['fecha']} · esquema {m['version_esquema']} · {sum(t['filas'] for t in m['tablas'].values()):,} filas en {len(m['tablas'])} tablas".replace(",", "."))
            for t, i in sorted(m["tablas"].items(), key=lambda x: -x[1]["filas"])[:15]:
                print(f"  {t}: {i['filas']}")
            return 0
        import psycopg
        if not args.url:
            ap.error("falta --url")
        with psycopg.connect(args.url, autocommit=True) as raw:
            if args.accion == "exportar":
                if args.despacho is None or not args.salida:
                    ap.error("exportar necesita --despacho y --salida")
                m = dc.exportar(raw, args.despacho, args.salida, informar=lambda t, n: print(f"  {t}: {n}", flush=True))
                print(f"exportado el despacho {m['despacho']} «{m['nombre']}»: {sum(t['filas'] for t in m['tablas'].values())} filas en {m['segundos']} s -> {args.salida}")
                return 0
            if not args.entrada:
                ap.error("importar necesita --entrada")
            r = dc.importar(raw, args.entrada, reemplazar=args.reemplazar, permitir_otra_version=args.otra_version, informar=lambda t, n: print(f"  {t}: {n}", flush=True))
            print(f"importado el despacho {r['despacho']} en {r['segundos']} s: {sum(r['tablas'].values())} filas" + (f" (borradas antes: {sum(r['borradas'].values())})" if r["borradas"] else ""))
            for d in r["discrepancias"]:
                print(f"  DISCREPANCIA: {d}", file=sys.stderr)
            return 0 if r["ok"] else 1
    except dc.ErrorDeCopia as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
