"""Traducción de las sentencias SQL de SQLite a PostgreSQL en tiempo de ejecución.

Solo lo MECÁNICO y seguro: marcadores de parámetros, `%` literal, `BEGIN IMMEDIATE`,
`INSERT OR IGNORE` y los `PRAGMA` inofensivos. Lo demás (fechas con strftime, rowid,
FTS5, `INSERT OR REPLACE`...) se reescribe en el propio SQL de la aplicación en la fase 3
y aquí falla con un mensaje claro en vez de ejecutar algo distinto.
"""
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

_PALABRA = re.compile(r"[A-Za-z_]+")
_INSERT = re.compile(r'^INSERT\s+(?:OR\s+(\w+)\s+)?INTO\s+"?([A-Za-z_][A-Za-z0-9_]*)"?', re.I)
_PRAGMA = re.compile(r"^PRAGMA\s+([a-z_]+)\s*(?:\(\s*([^)]*?)\s*\)|=\s*([^;]+))?\s*;?\s*$", re.I)

PRAGMAS_SIN_EFECTO = {
    "foreign_keys", "busy_timeout", "journal_mode", "wal_checkpoint", "secure_delete",
    "synchronous", "optimize", "cache_size", "temp_store", "mmap_size", "wal_autocheckpoint",
}


class NoPortable(NotImplementedError):
    """Construcción de SQLite sin traducción automática: hay que reescribir la sentencia."""


@dataclass(frozen=True)
class Preparada:
    sql_con_parametros: str        # con %s y %% (para ejecutar con parámetros)
    sql_sin_parametros: str        # con % literales sin duplicar
    nombrados: bool                # usa :nombre → %(nombre)s
    verbo: str                     # SELECT, INSERT, UPDATE, DELETE, BEGIN...
    es_escritura: bool             # INSERT/UPDATE/DELETE: abre transacción y va con SAVEPOINT
    tabla_insert: Optional[str]    # tabla de un INSERT (para lastrowid)
    tiene_returning: bool
    pragma: Optional[tuple]        # (nombre, argumento) si es un PRAGMA
    begin_inmediato: bool          # BEGIN IMMEDIATE/EXCLUSIVE: serializa escritores como SQLite


def _recorrer(sql: str, nombrados: bool):
    """Genera (trozo, es_codigo): separa literales, identificadores y comentarios del código."""
    i, n = 0, len(sql)
    ini = 0
    while i < n:
        c = sql[i]
        if c == "'" or c == '"':
            if ini < i:
                yield sql[ini:i], True
            j = i + 1
            while j < n:
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:
                        j += 2
                        continue
                    break
                j += 1
            yield sql[i:j + 1], False
            i = ini = j + 1
        elif c == "-" and sql.startswith("--", i):
            if ini < i:
                yield sql[ini:i], True
            j = sql.find("\n", i)
            j = n if j < 0 else j
            yield sql[i:j], False
            i = ini = j
        elif c == "/" and sql.startswith("/*", i):
            if ini < i:
                yield sql[ini:i], True
            j = sql.find("*/", i + 2)
            j = n if j < 0 else j + 2
            yield sql[i:j], False
            i = ini = j
        else:
            i += 1
    if ini < n:
        yield sql[ini:], True


def _sin_comentarios(sql: str) -> str:
    return "".join(t if codigo else (" " if t.startswith(("--", "/*")) else t) for t, codigo in _recorrer(sql, False)).strip()


@lru_cache(maxsize=4096)
def preparar(sql: str) -> Preparada:
    limpio = _sin_comentarios(sql)
    verbo = (_PALABRA.match(limpio).group(0).upper() if _PALABRA.match(limpio) else "")
    nombrados = bool(re.search(r"(?<![:\w]):[A-Za-z_]\w*", "".join(t for t, c in _recorrer(sql, False) if c)))
    con, sin = [], []
    for trozo, codigo in _recorrer(sql, nombrados):
        if codigo:
            t = trozo
            if nombrados:
                t = re.sub(r"(?<![:\w]):([A-Za-z_]\w*)", r"%(\1)s", t)
            else:
                t = t.replace("?", "\0")           # marcador temporal: no se confunde con los % que añadimos
            sin.append(t.replace("\0", "?") if not nombrados else t)
            con.append(t.replace("%", "%%").replace("%%(", "%(").replace("%%s", "%s") if nombrados else t.replace("%", "%%").replace("\0", "%s"))
        else:
            sin.append(trozo)
            con.append(trozo.replace("%", "%%"))
    sql_con, sql_sin = "".join(con), "".join(sin)
    if nombrados:
        sql_con = re.sub(r"%%\(([A-Za-z_]\w*)\)s", r"%(\1)s", sql_con)

    pragma = None
    m = _PRAGMA.match(limpio) if verbo == "PRAGMA" else None
    if m:
        pragma = (m.group(1).lower(), (m.group(2) if m.group(2) is not None else m.group(3)))
    elif verbo == "PRAGMA":
        raise NoPortable(f"PRAGMA no reconocido: {limpio[:80]}")

    begin_inmediato = False
    if verbo == "BEGIN":
        resto = limpio[5:].strip().rstrip(";").strip().upper()
        if resto in ("IMMEDIATE", "EXCLUSIVE"):
            begin_inmediato = True
            sql_con = sql_sin = "BEGIN"
        elif resto in ("", "DEFERRED", "TRANSACTION"):
            sql_con = sql_sin = "BEGIN"
        else:
            raise NoPortable(f"BEGIN no reconocido: {limpio[:80]}")

    tabla, ignorar = None, False
    if verbo in ("INSERT", "REPLACE"):
        if verbo == "REPLACE":
            raise NoPortable("REPLACE INTO: reescribir con INSERT ... ON CONFLICT (...) DO UPDATE")
        mi = _INSERT.match(limpio)
        if mi:
            alternativa, tabla = (mi.group(1) or "").upper(), mi.group(2)
            if alternativa == "REPLACE":
                raise NoPortable("INSERT OR REPLACE: reescribir con INSERT ... ON CONFLICT (...) DO UPDATE")
            if alternativa and alternativa != "IGNORE":
                raise NoPortable(f"INSERT OR {alternativa} sin traducción automática")
            ignorar = alternativa == "IGNORE"
    tiene_returning = bool(re.search(r"\bRETURNING\b", limpio, re.I))
    if ignorar:
        # INSERT OR IGNORE INTO t ...  →  INSERT INTO t ... ON CONFLICT DO NOTHING (antes de RETURNING si lo hay)
        def _a_pg(s):
            s = re.sub(r"^(\s*(?:/\*.*?\*/\s*)*INSERT)\s+OR\s+IGNORE\s+INTO", r"\1 INTO", s, count=1, flags=re.I | re.S)
            if re.search(r"\bON\s+CONFLICT\b", s, re.I):
                return s
            cola = "ON CONFLICT DO NOTHING"
            return re.sub(r"\s+RETURNING\b", f" {cola} RETURNING", s, count=1, flags=re.I) if tiene_returning else s.rstrip().rstrip(";") + f" {cola}"
        sql_con, sql_sin = _a_pg(sql_con), _a_pg(sql_sin)
    escritura = verbo in ("INSERT", "UPDATE", "DELETE")
    return Preparada(sql_con, sql_sin, nombrados, verbo, escritura, tabla, tiene_returning, pragma, begin_inmediato)


def dividir_sentencias(script: str) -> list[str]:
    """Separa un script de PostgreSQL en sentencias por los «;» que están fuera de literales, comentarios y cuerpos entre $$…$$ (o $etiqueta$…$etiqueta$)."""
    sentencias, actual, i, n = [], [], 0, len(script)
    while i < n:
        c = script[i]
        if c == "'":
            j = i + 1
            while j < n:
                if script[j] == "'":
                    if j + 1 < n and script[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            actual.append(script[i:j + 1])
            i = j + 1
        elif script.startswith("--", i):
            j = script.find("\n", i)
            j = n if j < 0 else j
            i = j
        elif script.startswith("/*", i):
            j = script.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif c == "$":
            m = re.match(r"\$([A-Za-z_]\w*)?\$", script[i:])
            if m:
                cierre = m.group(0)
                j = script.find(cierre, i + len(cierre))
                j = n if j < 0 else j + len(cierre)
                actual.append(script[i:j])
                i = j
            else:
                actual.append(c)
                i += 1
        elif c == ";":
            texto = "".join(actual).strip()
            if texto:
                sentencias.append(texto)
            actual = []
            i += 1
        else:
            actual.append(c)
            i += 1
    texto = "".join(actual).strip()
    if texto:
        sentencias.append(texto)
    return sentencias
