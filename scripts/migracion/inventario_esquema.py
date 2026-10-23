#!/usr/bin/env python3
"""Inventario del esquema SQLite para la migración a PostgreSQL + Citus (fase 0).

Solo LEE. Abre la base de datos en modo solo lectura y vuelca, por tabla: columnas,
claves foráneas, índices únicos, triggers y, si se pide, el número de filas. No
modifica nada ni importa la aplicación.

    python scripts/migracion/inventario_esquema.py RUTA.db [--filas] > inventario.json

La RUTA debe ser una base creada por init_db() en una copia aislada (esquema limpio)
o, con --filas, una copia de producción: nunca el fichero vivo de la aplicación.
"""
import json
import sqlite3
import sys


def _abrir(ruta):
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def inventario(ruta, filas=False):
    con = _abrir(ruta)
    objetos = con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master").fetchall()
    virtuales = {o["name"] for o in objetos if o["type"] == "table" and (o["sql"] or "").upper().startswith("CREATE VIRTUAL")}
    sombras = tuple(f"{v}_" for v in virtuales)
    tablas = {}
    for o in objetos:
        if o["type"] != "table" or o["name"].startswith("sqlite_") or o["name"].startswith(sombras):
            continue
        n = o["name"]
        cols = [dict(nombre=c["name"], tipo=c["type"], no_nulo=bool(c["notnull"]), defecto=c["dflt_value"], pk=c["pk"])
                for c in con.execute(f'PRAGMA table_info("{n}")')]
        fks = [dict(columna=f["from"], tabla=f["table"], destino=f["to"], on_delete=f["on_delete"])
               for f in con.execute(f'PRAGMA foreign_key_list("{n}")')]
        unicos = []
        for ix in con.execute(f'PRAGMA index_list("{n}")'):
            if ix["unique"]:
                unicos.append(dict(origen=ix["origin"], columnas=[r["name"] for r in con.execute(f'PRAGMA index_info("{ix["name"]}")')],
                                   parcial=bool(ix["partial"])))
        trig = [t["name"] for t in objetos if t["type"] == "trigger" and t["tbl_name"] == n]
        t = dict(virtual=n in virtuales, columnas=cols, fks=fks, unicos=unicos, triggers=trig,
                 sin_rowid="WITHOUT ROWID" in (o["sql"] or "").upper(),
                 autoincrement="AUTOINCREMENT" in (o["sql"] or "").upper(),
                 checks=(o["sql"] or "").upper().count("CHECK"))
        if filas:
            t["filas"] = con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]
        tablas[n] = t
    vistas = {o["name"]: o["sql"] for o in objetos if o["type"] == "view"}
    triggers = {o["name"]: dict(tabla=o["tbl_name"], sql=o["sql"]) for o in objetos if o["type"] == "trigger"}
    indices = sum(1 for o in objetos if o["type"] == "index" and o["sql"])
    return dict(tablas=tablas, vistas=vistas, triggers=triggers, indices_explicitos=indices)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    json.dump(inventario(sys.argv[1], filas="--filas" in sys.argv), sys.stdout, ensure_ascii=False, indent=1)
