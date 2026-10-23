#!/usr/bin/env python3
"""Audita el SQL embebido en el código de la aplicación: ¿qué construcciones de SQLite no son portables a PostgreSQL?

Solo lee el código fuente (no ejecuta nada ni abre bases de datos):

    python scripts/migracion/auditar_sql.py            resumen por categoría
    python scripts/migracion/auditar_sql.py -v         con cada aparición (fichero:línea)
    python scripts/migracion/auditar_sql.py --json     salida para otras herramientas

Se usa también desde tests/test_sql_portable.py para que no vuelvan a colarse construcciones no portables.
"""
import ast
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CARPETAS = ("app", "mcp_tools")
FICHEROS_RAIZ = ("cli.py", "serve.py", "serve_backoffice.py", "run.py", "mcp_server.py", "mcp_server_remoto.py")

# categoría -> (expresión, fase en la que se resuelve, descripción)
REGLAS = {
    "insert_or": (r"\bINSERT\s+OR\s+(IGNORE|REPLACE|ABORT|FAIL|ROLLBACK)\b|\bREPLACE\s+INTO\b", 3, "INSERT OR ... / REPLACE INTO"),
    "strftime": (r"\bstrftime\s*\(", 3, "strftime()"),
    "fecha_sqlite": (r"\b(datetime|date|time|julianday|unixepoch)\s*\(\s*'(now|[0-9])|\bdatetime\s*\(|\bjulianday\s*\(|\bdate\s*\(\s*[a-z_.]+\s*,\s*'", 3, "date()/datetime()/julianday()"),
    "rowid": (r"\b(rowid|oid)\b", 3, "rowid"),
    "group_concat": (r"\bgroup_concat\s*\(", 3, "group_concat()"),
    "ifnull_iif": (r"\b(ifnull|iif|glob|printf|instr|unicode|zeroblob|randomblob|hex)\s*\(", 3, "ifnull/iif/glob/printf/instr/hex"),
    "typeof": (r"\btypeof\s*\(", 3, "typeof()"),
    "last_insert": (r"\b(last_insert_rowid|changes|total_changes)\s*\(", 3, "last_insert_rowid()/changes()"),
    "collate_nocase": (r"\bCOLLATE\s+(NOCASE|BINARY|RTRIM)\b", 3, "COLLATE NOCASE/BINARY"),
    "like": (r"\bLIKE\b", 3, "LIKE (en SQLite no distingue mayúsculas; en PostgreSQL sí)"),
    "pragma": (r"\bPRAGMA\b", 3, "PRAGMA"),
    "begin_inmediato": (r"\bBEGIN\s+(IMMEDIATE|EXCLUSIVE|DEFERRED)\b", 2, "BEGIN IMMEDIATE (lo traduce la capa)"),
    "fts5": (r"\bfts5\b|\bMATCH\b|\bbm25\s*\(|\bsnippet\s*\(|\bhighlight\s*\(", 5, "FTS5"),
    "char_func": (r"\bchar\s*\(", 3, "char() de SQLite (en PostgreSQL es chr(): pasar el carácter como parámetro)"),
    "limit_menos_uno": (r"\bLIMIT\s+-1\b", 3, "LIMIT -1"),
    "sqlite_master": (r"\bsqlite_(master|schema|sequence|stat\d?)\b", 3, "sqlite_master/sqlite_sequence"),
    "autoincrement": (r"\bAUTOINCREMENT\b|\bWITHOUT\s+ROWID\b|\bINTEGER\s+PRIMARY\s+KEY\b", 4, "DDL de SQLite"),
    "vacuum_attach": (r"\b(VACUUM|ATTACH\s+DATABASE|DETACH\s+DATABASE|REINDEX)\b", 10, "VACUUM/ATTACH"),
    "comillas_dobles_literal": (r"(=|\bIN\s*\(|,)\s*\"[A-Za-z0-9_ .:-]*\"", 3, "cadena literal con comillas dobles (PostgreSQL la lee como identificador)"),
    "is_igualdad": (r"\bIS\s+(?:NOT\s+)?(?!NOT\b|NULL\b|TRUE\b|FALSE\b|DISTINCT\b|UNKNOWN\b|NORMALIZED\b)(?:\?|'|\d|[a-z_]+\.[a-z_]+|:[a-z])", 3, "IS / IS NOT como igualdad (PostgreSQL: IS [NOT] DISTINCT FROM)"),
    "igual_doble": (r"[^=!<>]==[^=]", 3, "operador =="),
    "limit_en_escritura": (r"\b(UPDATE|DELETE\s+FROM)\b[^;()]*\b(ORDER\s+BY|LIMIT)\b", 3, "UPDATE/DELETE con ORDER BY o LIMIT"),
    "plano": (r"\bplano\s*\(", 4, "plano() (función registrada con create_function)"),
}
_SQL = re.compile(r"^\s*(?:--[^\n]*\n\s*)*(SELECT|INSERT|UPDATE|DELETE|WITH|CREATE|DROP|ALTER|PRAGMA|REPLACE|VACUUM|ANALYZE|BEGIN|SAVEPOINT|RELEASE)\b", re.I)
_ALGUNA_PALABRA = re.compile(r"\b(FROM|INTO|WHERE|VALUES|SET|JOIN|TABLE|INDEX|TRIGGER)\b", re.I)


def ficheros():
    for c in CARPETAS:
        yield from sorted((RAIZ / c).rglob("*.py"))
    for f in FICHEROS_RAIZ:
        if (RAIZ / f).exists():
            yield RAIZ / f


def _texto(nodo):
    """Texto de una cadena o f-string; las expresiones de un f-string se sustituyen por un identificador neutro."""
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return nodo.value
    if isinstance(nodo, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "__x__" for v in nodo.values)
    return None


def cadenas(ruta: Path):
    """(línea, texto, es_sentencia_completa) de cada cadena del fichero que parezca SQL."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    dentro_de_fstring = set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.JoinedStr):
            for v in ast.walk(n):
                if v is not n:
                    dentro_de_fstring.add(id(v))
    for n in ast.walk(arbol):
        if id(n) in dentro_de_fstring:
            continue
        t = _texto(n)
        if t is None or len(t) < 12:
            continue
        if _SQL.match(t) or (_ALGUNA_PALABRA.search(t) and re.search(r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE)\b", t, re.I)):
            yield n.lineno, t, bool(_SQL.match(t))


# Construcciones que YA no deben aparecer (fases 2-3 completadas). Se comprueban en tests/test_sql_portable.py.
PROHIBIDAS = ("char_func", "insert_or", "strftime", "fecha_sqlite", "group_concat", "collate_nocase", "ifnull_iif", "typeof", "last_insert",
              "limit_menos_uno", "comillas_dobles_literal", "is_igualdad", "igual_doble", "limit_en_escritura")
# Pendientes para fases posteriores o propias de código solo-SQLite (guardado por bd.MOTOR): categoría -> ficheros donde se admiten.
PERMITIDAS_EN = {
    "pragma_sqlite": ("app/db.py", "app/tareas_trabajo.py"),        # integrity_check, foreign_key_check, writable_schema, schema_version
    "sqlite_master": ("app/db.py", "app/tareas_trabajo.py", "app/bd/__init__.py"),
}
_PRAGMA_SOLO_SQLITE = re.compile(r"\bPRAGMA\s+(integrity_check|foreign_key_check|writable_schema|schema_version|quick_check|user_version|index_list|index_info|foreign_key_list)\b", re.I)
_DDL = re.compile(r"^\s*(?:--[^\n]*\n\s*)*(CREATE|ALTER|DROP)\b", re.I)


def incumplimientos():
    """Apariciones de construcciones no portables que ya no se admiten: [(categoría, fichero, línea, fragmento)]."""
    malos = []
    for f in ficheros():
        rel = str(f.relative_to(RAIZ))
        if rel.startswith(("app/bd/",)) or rel in ("app/sdk_generador.py", "app/nextcloud.py"):        # generadores de código y XML, no SQL
            continue
        for linea, texto, completa in cadenas(f):
            ddl = bool(re.search(r"\bCREATE\s+(TEMP\w*\s+)?(TABLE|TRIGGER|INDEX|VIRTUAL|VIEW)\b", texto, re.I)) or bool(_DDL.match(texto))
            for cat in PROHIBIDAS:
                if ddl and cat in ("insert_or", "fecha_sqlite", "ifnull_iif", "comillas_dobles_literal", "is_igualdad"):
                    continue                                      # triggers y valores por defecto de DDL de SQLite: fase 4
                if cat == "comillas_dobles_literal" and not completa:
                    continue
                for m in re.finditer(REGLAS[cat][0], texto, re.I):
                    if cat == "is_igualdad" and re.search(r"\b(OLD|NEW)\.", m.group(0) + texto[m.end():m.end() + 20], re.I):
                        continue                                  # condición de un trigger de SQLite: fase 4
                    malos.append((cat, rel, linea, " ".join(texto[max(0, m.start() - 30):m.end() + 40].split())))
            for m in _PRAGMA_SOLO_SQLITE.finditer(texto):
                if rel not in PERMITIDAS_EN["pragma_sqlite"]:
                    malos.append(("pragma_sqlite", rel, linea, m.group(0)))
            if re.search(REGLAS["sqlite_master"][0], texto, re.I) and rel not in PERMITIDAS_EN["sqlite_master"]:
                malos.append(("sqlite_master", rel, linea, "sqlite_master fuera de código solo-SQLite (usar bd.existe_tabla)"))
    return malos


def sentencias_completas():
    """[(fichero, línea, texto)] de las sentencias DML que empiezan por SELECT/INSERT/UPDATE/DELETE/WITH."""
    for f in ficheros():
        rel = str(f.relative_to(RAIZ))
        if rel.startswith("app/bd/") or rel in ("app/sdk_generador.py", "app/nextcloud.py"):
            continue
        for linea, texto, completa in cadenas(f):
            if completa and re.match(r"\s*(?:--[^\n]*\n\s*)*(SELECT|INSERT|UPDATE|DELETE|WITH)\b", texto, re.I):
                yield rel, linea, texto


def auditar():
    """{categoría: [(fichero relativo, línea, fragmento)]}"""
    hallazgos = {k: [] for k in REGLAS}
    for f in ficheros():
        rel = str(f.relative_to(RAIZ))
        for linea, texto, _ in cadenas(f):
            for cat, (patron, _fase, _desc) in REGLAS.items():
                for m in re.finditer(patron, texto, re.I):
                    ini = max(0, m.start() - 30)
                    hallazgos[cat].append((rel, linea, " ".join(texto[ini:m.end() + 40].split())))
    return hallazgos


if __name__ == "__main__":
    h = auditar()
    if "--json" in sys.argv:
        json.dump(h, sys.stdout, ensure_ascii=False, indent=1)
        sys.exit(0)
    verboso = "-v" in sys.argv
    print(f"{'categoría':26s} {'n':>5s}  fase  descripción")
    for cat, lista in sorted(h.items(), key=lambda kv: -len(kv[1])):
        _p, fase, desc = REGLAS[cat]
        print(f"{cat:26s} {len(lista):5d}  {fase:>4d}  {desc}")
        if verboso:
            for rel, linea, frag in lista:
                print(f"      {rel}:{linea}  …{frag}")
