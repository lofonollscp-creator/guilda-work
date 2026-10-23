"""El SQL de la aplicación no vuelve a usar construcciones que solo existen en SQLite (migración a PostgreSQL, fase 3).

`scripts/migracion/auditar_sql.py` lee el código fuente; este test falla si reaparece algo que ya se había hecho portable
(INSERT OR IGNORE/REPLACE, strftime/julianday/date('now'), group_concat, COLLATE NOCASE, `IS ?`, ...) o si se usa
sqlite_master / un PRAGMA solo-SQLite fuera del código que solo corre en SQLite.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "migracion"))
import auditar_sql  # noqa: E402


def test_no_hay_construcciones_sqlite_no_portables():
    malos = auditar_sql.incumplimientos()
    assert not malos, "SQL no portable a PostgreSQL:\n" + "\n".join(f"  [{c}] {r}:{l}  …{f[:120]}" for c, r, l, f in malos)


def test_las_sentencias_dml_se_parsean_como_postgresql():
    """Sintaxis (no semántica): cada SELECT/INSERT/UPDATE/DELETE embebido debe ser SQL válido para el analizador de PostgreSQL."""
    pglast = pytest.importorskip("pglast")
    omitidas = re.compile(r"\bMATCH\b|\bfts5\b|_fts\b|PRAGMA|sqlite_|\bplano\s*\(", re.I)         # FTS5 y funciones propias: fase 4-5
    fallos = []
    total = 0
    for rel, linea, texto in auditar_sql.sentencias_completas():
        if omitidas.search(texto) or "__x__" in texto or "%s" in texto or re.search(r"\b(NEW|OLD)\.", texto) or re.search(r"\b(WHERE|AND|OR|SET)\s*$", texto.strip(), re.I):
            continue                                                    # fragmentos de SQL dinámico (f-strings, `%s`) y cuerpos de triggers: no son sentencias completas
        sql = re.sub(r"(?<![:\w]):[A-Za-z_]\w*", "$1", texto)          # :nombre → $1
        sql = sql.replace("?", "$1")                                    # ? → $1
        sql = re.sub(r"\{[^{}]*\}", "x", sql)                           # restos de plantillas
        total += 1
        try:
            pglast.parse_sql(sql)
        except Exception as e:                                          # noqa: BLE001
            fallos.append(f"  {rel}:{linea}  {str(e)[:100]}  …{' '.join(sql.split())[:100]}")
    assert total > 400
    assert not fallos, f"{len(fallos)} sentencias no son SQL de PostgreSQL válido:\n" + "\n".join(fallos[:60])


def test_el_auditor_detecta_lo_que_debe(tmp_path, monkeypatch):
    """El propio auditor funciona: un fichero con SQL de SQLite genera hallazgos."""
    f = tmp_path / "app" / "x.py"
    f.parent.mkdir()
    f.write_text("c.execute(\"INSERT OR IGNORE INTO t (a) VALUES (?)\")\nc.execute(\"SELECT group_concat(a) FROM t WHERE b IS ?\")\n")
    monkeypatch.setattr(auditar_sql, "RAIZ", tmp_path)
    monkeypatch.setattr(auditar_sql, "CARPETAS", ("app",))
    monkeypatch.setattr(auditar_sql, "FICHEROS_RAIZ", ())
    cats = {c for c, *_ in auditar_sql.incumplimientos()}
    assert {"insert_or", "group_concat", "is_igualdad"} <= cats
