#!/usr/bin/env python3
"""Planifica CONTRA UN CITUS REAL (esquema de la variante `citus`) todas las sentencias SQL completas de la aplicación, sin ejecutarlas: PREPARE + EXPLAIN EXECUTE con
parámetros NULL. Citus rechaza al planificar lo que no sabe repartir (joins entre tablas distribuidas que no son por tenant_id, subconsultas correlacionadas...).

    python scripts/migracion/validar_sql_citus.py postgresql://usuario:clave@host:puerto/base_citus [-v]

Con --reescribir se aplica la reescritura de app/bd/citus.py y con --con-despacho además el filtro de despacho de una conexión de la aplicación. Con --con-valores los parámetros valen 1 en vez de NULL (el planificador no puede descartar todos los shards por un NULL). Muestra cuántas sentencias se planifican bien, cuáles son de un solo shard («router») y cuáles se reparten, y agrupa los errores. No modifica datos.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auditar_sql  # noqa: E402
import validar_sql_pg  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.bd import citus  # noqa: E402


verboso_lista = {"por_defecto": []}


# Migraciones de bases SQLite antiguas y el UPDATE tenant_id del borrado (en PostgreSQL se borra con tenant.borrar_filas_de_tenant): no se ejecutan sobre Citus.
SOLO_SQLITE = re.compile(r"SET tenant_id = NULL|INSERT INTO tarea_revision_votos \(revision_id, revisor_id, estado, nota, votado_en\)\s+SELECT|INSERT INTO tarea_clientes \([^)]*\)\s+SELECT\s+cf\.tenant_id", re.I)


def validar(url, verboso=False, valor="NULL", reescribir=False, con_despacho=False):
    import psycopg
    ok, router, repartidas, fallos = 0, 0, 0, []
    inserciones = {"explicito": 0, "por_defecto": 0}               # INSERT: con tenant_id en las columnas, o dejando que lo ponga el valor por defecto de la conexión
    with psycopg.connect(url, autocommit=True) as c:
        for rel, linea, texto in auditar_sql.sentencias_completas():
            if SOLO_SQLITE.search(texto) or validar_sql_pg.OMITIR.search(texto) or "__x__" in texto or "%s" in texto or re.search(r"\b(NEW|OLD)\.", texto) or re.search(r"(\b(WHERE|AND|OR|SET)|,)\s*$", texto.strip(), re.I):
                continue
            texto = re.sub(r"\{[^{}]*\}", "x", texto)
            if con_despacho:                                                    # como una conexión de la aplicación con despacho 1
                ins = citus.reescribir_insert(texto)
                texto = (ins[0] if ins else citus.reescribir_sqlite_con_despacho(texto) or citus.reescribir_sqlite(texto) or texto).replace(citus.SENTINELA, "1")
            elif reescribir:
                texto = citus.reescribir_sqlite(texto) or texto
            sql, n = validar_sql_pg.preparar_texto(texto)
            try:
                c.execute("PREPARE v AS " + sql)
            except psycopg.Error:
                continue                                                     # ya lo recoge validar_sql_pg
            try:
                plan = "\n".join(r[0] for r in c.execute("EXPLAIN (COSTS OFF) EXECUTE v(" + ", ".join([valor] * n) + ")").fetchall()) if n else \
                       "\n".join(r[0] for r in c.execute("EXPLAIN (COSTS OFF) EXECUTE v").fetchall())
                ok += 1
                m = re.search(r"Task Count: (\d+)", plan)
                if m and m.group(1) == "1":
                    router += 1
                elif m:
                    repartidas += 1
            except psycopg.Error as e:
                if "INSERT with NULL in the partition column" in str(e):          # esperado: el EXPLAIN pasa NULL a todo, incluido el tenant_id del INSERT
                    ok += 1
                    inserciones["explicito" if re.search(r"\(\s*[^)]*\btenant_id\b", sql.split("VALUES")[0] if "VALUES" in sql else sql, re.I) else "por_defecto"] += 1
                    if "por_defecto" in verboso_lista and not re.search(r"\btenant_id\b", sql.split("VALUES")[0]):
                        verboso_lista["por_defecto"].append((rel, linea, " ".join(sql.split())[:160]))
                    continue
                fallos.append((rel, linea, str(e).split("\n")[0][:150], " ".join(sql.split())[:200]))
            finally:
                try:
                    c.execute("DEALLOCATE v")
                except psycopg.Error:
                    pass
    return ok, router, repartidas, fallos, inserciones


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    ok, router, repartidas, fallos, inserciones = validar(sys.argv[1], valor="1" if "--con-valores" in sys.argv else "NULL", reescribir="--reescribir" in sys.argv, con_despacho="--con-despacho" in sys.argv)
    print(f"{ok} sentencias planificadas ({router} de un solo shard, {repartidas} repartidas, {sum(inserciones.values())} INSERT: {inserciones['explicito']} con tenant_id en las columnas y "
          f"{inserciones['por_defecto']} que lo toman del despacho de la conexión) y {len(fallos)} que Citus rechaza")
    import collections
    for msg, n in collections.Counter(re.sub(r'"[^"]*"', '"…"', f[2]) for f in fallos).most_common():
        print(f"  {n:4d}  {msg}")
    if "--por-defecto" in sys.argv:
        for rel, linea, sql in verboso_lista["por_defecto"]:
            print(f"{rel}:{linea}  {sql}")
    if "-v" in sys.argv:
        for rel, linea, e, sql in sorted(fallos):
            print(f"{rel}:{linea}  {e}\n      {sql}")
    sys.exit(1 if fallos else 0)
