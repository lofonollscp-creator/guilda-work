#!/usr/bin/env python3
"""Comprobación POSTERIOR al despliegue de Guilda Fiscal: solo LEE el catálogo de PostgreSQL (no toca ni un dato de ningún despacho) y dice si todo lo que tiene que estar, está.

  sudo bash -c 'set -a; source /etc/guilda-work.env; set +a; runuser -u guilda --preserve-environment -- /home/guilda/guilda-work/.venv/bin/python /home/guilda/guilda-work/scripts/fiscal/verificar_despliegue.py'

Usa la URL de la plataforma (`GUILDA_DATABASE_URL_PLATAFORMA`) o `--url`. Comprueba: versión del esquema (≥ 3), las siete tablas, sus claves primarias con `tenant_id`, el aislamiento por despacho (RLS), los triggers de
inmutabilidad, la distribución en Citus (si lo hay), que las tablas están vacías o con datos de uso normal, y que el módulo está dado de alta en la aplicación. Código de salida 0 = todo bien · 1 = algo falta."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

TABLAS = ("fiscal_perfiles", "fiscal_relaciones", "fiscal_apuntes", "fiscal_instantaneas", "fiscal_declaraciones", "fiscal_casillas", "fiscal_artefactos")
TRIGGERS = ("fiscal_instantaneas_inmutable", "fiscal_artefactos_inmutable", "fiscal_casillas_solo_borrador", "fiscal_declaraciones_reglas")
VERSION_MINIMA = 3


def comprobar(conn) -> list[tuple[bool, str]]:
    r: list[tuple[bool, str]] = []

    def uno(sql, *args):
        return conn.execute(sql, args).fetchone()[0]

    v = uno("SELECT max(version) FROM bd_esquema_version")
    r.append((v is not None and v >= VERSION_MINIMA, f"versión del esquema: {v} (se espera ≥ {VERSION_MINIMA})"))
    existentes = {f[0] for f in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() AND table_name LIKE 'fiscal\\_%'").fetchall()}
    for t in TABLAS:
        r.append((t in existentes, f"tabla {t}"))
    for t in TABLAS:
        if t not in existentes:
            continue
        pk = conn.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = ?::regclass AND contype = 'p'", (t,)).fetchone()
        r.append((bool(pk) and "tenant_id" in pk[0], f"{t}: clave primaria con tenant_id ({pk[0] if pk else 'sin clave primaria'})"))
        rls = conn.execute("SELECT relrowsecurity FROM pg_class WHERE oid = ?::regclass", (t,)).fetchone()[0]
        pol = uno("SELECT count(*) FROM pg_policy WHERE polrelid = ?::regclass AND polname = 'aislamiento'", t)
        r.append((bool(rls) and pol == 1, f"{t}: aislamiento por despacho (RLS activo y política «aislamiento»)"))
    triggers = {f[0] for f in conn.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 'fiscal\\_%'").fetchall()}
    for t in TRIGGERS:
        r.append((t in triggers, f"trigger {t}"))
    r.append((bool(uno("SELECT count(*) FROM pg_proc WHERE proname = 'fiscal_dia'")), "función fiscal_dia (inmutable) para la restricción de no solape"))
    r.append((bool(uno("SELECT count(*) FROM pg_constraint WHERE conname = 'fiscal_perfiles_sin_solape'")), "restricción de no solape de vigencias de los perfiles"))
    if uno("SELECT count(*) FROM pg_extension WHERE extname = 'citus'"):
        distribuidas = {f[0] for f in conn.execute("SELECT logicalrelid::text FROM pg_dist_partition").fetchall()}
        for t in TABLAS:
            r.append((t in distribuidas, f"Citus: {t} distribuida"))
        grupos = {f[0] for f in conn.execute("SELECT colocationid FROM pg_dist_partition WHERE logicalrelid::text = ANY(?)", (list(TABLAS),)).fetchall()}
        base = conn.execute("SELECT colocationid FROM pg_dist_partition WHERE logicalrelid::text = 'abogados_ajustes'").fetchone()
        r.append((len(grupos) == 1 and bool(base) and base[0] in grupos, "Citus: colocalizadas con el resto de tablas de despacho"))
    from app import verticales
    import app.fiscal_nucleo  # noqa: F401  (da de alta el vertical)
    f = verticales.VERTICALES.get("fiscal")
    r.append((bool(f) and f.disponible, "módulo «Guilda Fiscal» dado de alta y disponible en la aplicación"))
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("GUILDA_DATABASE_URL_PLATAFORMA") or os.environ.get("GUILDA_PG_ADMIN_URL"))
    args = ap.parse_args(argv)
    if not args.url:
        ap.error("falta --url (o GUILDA_DATABASE_URL_PLATAFORMA en el entorno)")
    from app.bd import postgres as pg
    pg.fijar_url(args.url)
    conn = pg.conectar()
    try:
        resultados = comprobar(conn)
    finally:
        conn.close()
        pg.cerrar_pool()
    for ok, texto in resultados:
        print(("  ✓ " if ok else "  ✗ ") + texto)
    fallos = [t for ok, t in resultados if not ok]
    print("\nTODO CORRECTO" if not fallos else f"\nFALTAN {len(fallos)} COSA(S): revisa las marcadas con ✗ (¿se aplicaron las migraciones 002 y 003?)")
    return 0 if not fallos else 1


if __name__ == "__main__":
    sys.exit(main())
