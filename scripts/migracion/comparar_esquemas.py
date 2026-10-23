#!/usr/bin/env python3
"""Compara el esquema de una base SQLite con el de una base PostgreSQL (fase 4): tablas, columnas, nulos, claves primarias, UNIQUE y claves foráneas.

    python scripts/migracion/comparar_esquemas.py BASE.db postgresql://usuario:clave@host:puerto/base

Imprime las diferencias y termina con código 1 si las hay. Solo lee.
"""
import sqlite3
import sys

CLASE = {"INTEGER": "bigint", "TEXT": "text", "REAL": "double precision", "BLOB": "bytea"}


def esquema_sqlite(ruta):
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    maestro = con.execute("SELECT type, name, sql FROM sqlite_master").fetchall()
    virtuales = {n for t, n, s in maestro if t == "table" and (s or "").upper().startswith("CREATE VIRTUAL")}
    sombras = tuple(v + "_" for v in virtuales)
    out = {}
    for t, n, s in maestro:
        if t != "table" or n.startswith("sqlite_") or n in virtuales or n.startswith(sombras):
            continue
        cols = con.execute(f'PRAGMA table_info("{n}")').fetchall()
        pk = tuple(c[1] for c in sorted((c for c in cols if c[5]), key=lambda c: c[5]))
        unicos = set()
        for fila in con.execute(f'PRAGMA index_list("{n}")').fetchall():
            if fila[3] == "u":
                unicos.add(tuple(r[2] for r in sorted(con.execute(f'PRAGMA index_info("{fila[1]}")').fetchall())))
        fks = set()
        grupos = {}
        for f in con.execute(f'PRAGMA foreign_key_list("{n}")').fetchall():
            grupos.setdefault(f[0], []).append(f)
        for filas in grupos.values():
            filas.sort(key=lambda f: f[1])
            fks.add((tuple(f[3] for f in filas), filas[0][2], (filas[0][6] or "NO ACTION").upper()))
        out[n] = {"cols": {c[1]: (CLASE[(c[2] or "").upper()], bool(c[3]) or c[1] in pk) for c in cols}, "pk": pk, "unicos": unicos, "fks": fks}
    return out


def esquema_postgres(url):
    import psycopg
    out = {}
    with psycopg.connect(url) as c:
        for (t,) in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"):
            out[t] = {"cols": {}, "pk": (), "unicos": set(), "fks": set()}
        for t, n, tipo, nulo in c.execute("SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = current_schema() ORDER BY ordinal_position"):
            if t in out:
                out[t]["cols"][n] = ({"bigint": "bigint", "text": "text", "double precision": "double precision", "bytea": "bytea"}.get(tipo, tipo), nulo == "NO")
        for t, tipo, cols in c.execute(
            "SELECT c.conrelid::regclass::text, c.contype, array(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(n, o) JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.n ORDER BY k.o) "
            "FROM pg_constraint c WHERE c.connamespace = current_schema()::regnamespace AND c.contype IN ('p', 'u')"):
            if t in out:
                (out[t].__setitem__("pk", tuple(cols)) if tipo == "p" else out[t]["unicos"].add(tuple(cols)))
        for t, cols, padre, accion in c.execute(
            "SELECT c.conrelid::regclass::text, array(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(n, o) JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.n ORDER BY k.o), "
            "c.confrelid::regclass::text, c.confdeltype FROM pg_constraint c WHERE c.connamespace = current_schema()::regnamespace AND c.contype = 'f'"):
            if t in out:
                out[t]["fks"].add((tuple(cols), padre, {"a": "NO ACTION", "r": "RESTRICT", "c": "CASCADE", "n": "SET NULL", "d": "SET DEFAULT"}[accion]))
    return out


def comparar(a, b):
    b = {t: v for t, v in b.items() if t != "bd_esquema_version"}          # propia de PostgreSQL (versión del esquema)
    dif = []
    for t in sorted(set(a) | set(b)):
        if t not in b:
            dif.append(f"{t}: falta en PostgreSQL")
        elif t not in a:
            dif.append(f"{t}: sobra en PostgreSQL")
        else:
            for k in ("cols", "pk", "unicos", "fks"):
                if a[t][k] != b[t][k]:
                    x, y = a[t][k], b[t][k]
                    detalle = {c: (x.get(c), y.get(c)) for c in set(x) | set(y) if x.get(c) != y.get(c)} if k == "cols" else (x ^ y if isinstance(x, set) else (x, y))
                    dif.append(f"{t}.{k}: {detalle}")
    return dif


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    dif = comparar(esquema_sqlite(sys.argv[1]), esquema_postgres(sys.argv[2]))
    print("\n".join(dif) if dif else "esquemas equivalentes")
    sys.exit(1 if dif else 0)
