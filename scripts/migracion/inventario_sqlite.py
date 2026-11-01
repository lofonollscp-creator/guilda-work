#!/usr/bin/env python3
"""Inventario de lo que queda de SQLite en el código, para planificar su retirada (docs/retirada-sqlite.md).

    python scripts/migracion/inventario_sqlite.py          resumen y tabla por fichero
    python scripts/migracion/inventario_sqlite.py --json   para otras herramientas

Solo lee el código fuente. Cuenta, por fichero: importaciones y usos de `sqlite3`, `PRAGMA`/`sqlite_master`, ramas por motor (`MOTOR`, `es_postgres`), tablas FTS5/`MATCH` y, en `tests/`, los tests marcados `solo_sqlite`."""
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CARPETAS = ("app", "backoffice", "mcp_tools", "scripts")
FICHEROS_RAIZ = ("cli.py", "serve.py", "serve_backoffice.py", "run.py", "mcp_server.py", "mcp_server_remoto.py")
PATRONES = {
    "sqlite3": re.compile(r"\bsqlite3\b"),
    "pragma": re.compile(r"\bPRAGMA\b|\bsqlite_master\b|\bsqlite_sequence\b"),
    "motor": re.compile(r"\bMOTOR\b|\bes_postgres\b|\bmotor_actual\b"),
    "fts5": re.compile(r"\bfts5\b|\bUSING\s+fts|\bMATCH\b", re.I),
}
OPERATIVO = ("deploy/litestream.service", "deploy/litestream.yml", "scripts/exportar_a_sqlite.py", "scripts/ensayo_corte_postgres.py", "app/bd/exportar_sqlite.py")


def inventario() -> dict:
    por_fichero = {}
    ficheros = [f for c in CARPETAS for f in (RAIZ / c).rglob("*.py")] + [RAIZ / f for f in FICHEROS_RAIZ if (RAIZ / f).exists()]
    for f in ficheros:
        if "migracion" in f.parts and f.name.startswith("inventario_"):
            continue
        texto = f.read_text(encoding="utf-8", errors="replace")
        cuentas = {k: len(p.findall(texto)) for k, p in PATRONES.items()}
        if any(cuentas.values()):
            por_fichero[str(f.relative_to(RAIZ))] = cuentas
    solo_sqlite = {}
    for f in (RAIZ / "tests").rglob("test_*.py"):
        texto = f.read_text(encoding="utf-8", errors="replace")
        n = len(re.findall(r"@pytest\.mark\.solo_sqlite|pytest\.mark\.solo_sqlite", texto))
        if n:
            solo_sqlite[str(f.relative_to(RAIZ))] = n
    return {"ficheros": por_fichero, "solo_sqlite": solo_sqlite, "operativo": {f: (RAIZ / f).exists() for f in OPERATIVO},
            "totales": {k: sum(v[k] for v in por_fichero.values()) for k in PATRONES}}


def main() -> int:
    inv = inventario()
    if "--json" in sys.argv:
        print(json.dumps(inv, indent=1, ensure_ascii=False))
        return 0
    print("Totales:", ", ".join(f"{k}={v}" for k, v in inv["totales"].items()), f"· ficheros con SQLite: {len(inv['ficheros'])} · ficheros de test solo_sqlite: {len(inv['solo_sqlite'])}")
    print(f"\n{'fichero':44s} {'sqlite3':>7s} {'pragma':>6s} {'motor':>5s} {'fts5':>5s}")
    for f, c in sorted(inv["ficheros"].items(), key=lambda kv: -(kv[1]["sqlite3"] + kv[1]["pragma"] + kv[1]["motor"])):
        print(f"{f:44s} {c['sqlite3']:7d} {c['pragma']:6d} {c['motor']:5d} {c['fts5']:5d}")
    print("\nOperativo que se retira con SQLite:", ", ".join(f"{f}{'' if ok else ' (ya no existe)'}" for f, ok in inv["operativo"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
