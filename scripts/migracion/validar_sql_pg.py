#!/usr/bin/env python3
"""Valida CONTRA UN POSTGRESQL REAL (con el esquema ya creado) todas las sentencias SQL completas de la aplicación, sin ejecutarlas:
cada una se envía con PREPARE, así que PostgreSQL comprueba tablas, columnas, funciones, tipos de los operadores, GROUP BY, ambigüedades...

    python scripts/migracion/validar_sql_pg.py postgresql://usuario:clave@host:puerto/base_con_el_esquema [-v]

No modifica datos (PREPARE solo analiza). Se omiten los fragmentos de SQL dinámico y lo que depende de FTS5 (fase 5).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auditar_sql  # noqa: E402

# Tablas de backoffice.db (la base SQLite propia del backoffice): no existen en el esquema de PostgreSQL de la aplicación.
TABLAS_DEL_BACKOFFICE = r"(admins|intentos_login|auditoria|cobros|notas_tenant|snapshots_tenants|salud_historial|seguimiento_tenant|auditorias_dependencias|resumenes_enviados)"
OMITIR = re.compile(r"\bMATCH\b|\bpg_dist_\w+|\bcitus_\w+|\bfts5\b|_fts\b|PRAGMA|sqlite_|\bbm25\b|_nueva\b|\b(FROM|INTO|UPDATE|JOIN)\s+" + TABLAS_DEL_BACKOFFICE + r"\b", re.I)


def preparar_texto(texto):
    """? y :nombre → $1, $2... Devuelve (sql, n_parámetros)."""
    n = 0
    nombres = {}

    def marcador(m):
        nonlocal n
        n += 1
        return f"${n}"

    sql = re.sub(r"(?<![:\w]):([A-Za-z_]\w*)", lambda m: nombres.setdefault(m.group(1), f"${len(nombres) + 1}"), texto)
    if nombres:
        return sql, len(nombres)
    sql = re.sub(r"\?", marcador, texto)
    return sql, n


def validar(url, verboso=False):
    import psycopg
    fallos, total = [], 0
    with psycopg.connect(url, autocommit=True) as c:
        for rel, linea, texto in auditar_sql.sentencias_completas():
            if OMITIR.search(texto) or "__x__" in texto or "%s" in texto or re.search(r"\b(NEW|OLD)\.", texto) or re.search(r"(\b(WHERE|AND|OR|SET)|,)\s*$", texto.strip(), re.I):
                continue
            sql, _ = preparar_texto(re.sub(r"\{[^{}]*\}", "x", texto))
            total += 1
            try:
                c.execute("PREPARE v AS " + sql)
                c.execute("DEALLOCATE v")
            except psycopg.Error as e:
                fallos.append((rel, linea, str(e).split("\n")[0][:140], " ".join(sql.split())[:160]))
                try:
                    c.execute("DEALLOCATE v")
                except psycopg.Error:
                    pass
    return total, fallos


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    total, fallos = validar(sys.argv[1])
    print(f"{total} sentencias preparadas, {len(fallos)} fallos")
    for rel, linea, error, sql in sorted(fallos):
        print(f"{rel}:{linea}  {error}\n      {sql}")
    sys.exit(1 if fallos else 0)
