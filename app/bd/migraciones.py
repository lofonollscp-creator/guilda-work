"""Migraciones numeradas del esquema de PostgreSQL (fase 12). El esquema base es la versión 1 (app/bd/esquema.py); cada cambio posterior es un fichero de app/bd/migraciones/ (ver su LEEME.md).

  * `pendientes(conn)` — qué ficheros faltan por aplicar; `aplicar(conn)` — los aplica en orden bajo un bloqueo (dos procesos a la vez no se pisan) y anota cada versión en `bd_esquema_version`.
  * `version_esperada()` — la del código (la mayor de los ficheros, o 1); `comprobar(conn)` — el arranque de los servicios falla con un mensaje claro si la base va por detrás.
Hace falta el propietario de las tablas (el superusuario): los servicios NO aplican migraciones, las aplica scripts/migrar_esquema_pg.py en el despliegue.
"""
from __future__ import annotations

import re
from pathlib import Path

from .esquema import VERSION_BASE

DIRECTORIO_MIGRACIONES = Path(__file__).resolve().parent / "migraciones"
_FICHERO = re.compile(r"^(\d{3,})_([a-z0-9_]+)(?:\.(mt|citus))?\.sql$")
_CLAVE_BLOQUEO = "guilda.migraciones"


class ErrorDeMigracion(Exception):
    pass


def ficheros() -> dict[int, dict]:
    """{versión: {'base': Path, 'mt': Path|None, 'citus': Path|None, 'nombre': str}} de los ficheros de migración."""
    versiones: dict[int, dict] = {}
    for f in sorted(DIRECTORIO_MIGRACIONES.glob("*.sql")):
        m = _FICHERO.match(f.name)
        if not m:
            raise ErrorDeMigracion(f"nombre de migración no válido: {f.name} (NNN_descripcion[.mt|.citus].sql)")
        v = int(m.group(1))
        if v <= VERSION_BASE:
            raise ErrorDeMigracion(f"{f.name}: las migraciones empiezan en {VERSION_BASE + 1} (la {VERSION_BASE} es el esquema base)")
        d = versiones.setdefault(v, {"base": None, "mt": None, "citus": None, "nombre": m.group(2)})
        if d["nombre"] != m.group(2):
            raise ErrorDeMigracion(f"la versión {v} tiene dos nombres distintos ({d['nombre']} y {m.group(2)})")
        d[m.group(3) or "base"] = f
    huecos = [v for v in range(VERSION_BASE + 1, max(versiones, default=VERSION_BASE) + 1) if v not in versiones]
    if huecos:
        raise ErrorDeMigracion(f"faltan las versiones {huecos}: las migraciones no pueden tener huecos")
    return versiones


def version_esperada() -> int:
    return max(ficheros(), default=VERSION_BASE)


def version_actual(conn) -> int | None:
    from . import existe_tabla
    if not existe_tabla(conn, "bd_esquema_version"):
        return None
    return conn.execute("SELECT max(version) FROM bd_esquema_version").fetchone()[0]


def modo_de(conn) -> str:
    """'citus' si la base tiene la extensión y tablas distribuidas, 'multitenant' si tiene `usuarios_tenants`, 'simple' si no."""
    if conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'citus'").fetchone() and conn.execute("SELECT 1 FROM pg_dist_partition LIMIT 1").fetchone():
        return "citus"
    return "multitenant" if conn.execute("SELECT to_regclass('usuarios_tenants') IS NOT NULL").fetchone()[0] else "simple"


def pendientes(conn) -> list[int]:
    actual = version_actual(conn)
    if actual is None:
        raise ErrorDeMigracion("la base de datos no tiene esquema (ejecuta antes la creación del esquema base)")
    return [v for v in sorted(ficheros()) if v > actual]


def aplicar(conn, *, informar=None) -> list[int]:
    """Aplica en orden lo que falta. `conn` es una ConexionPG de un rol propietario (superusuario). Devuelve las versiones aplicadas. Si una falla, las anteriores quedan anotadas y la excepción nombra el fichero."""
    fs = ficheros()
    raw = getattr(conn, "_raw", conn)
    raw.execute("SELECT pg_advisory_lock(hashtext(%s))", (_CLAVE_BLOQUEO,))
    aplicadas: list[int] = []
    try:
        for v in pendientes(conn):                                        # (se lee DENTRO del bloqueo: otro proceso pudo aplicar mientras se esperaba)
            modo = modo_de(conn)
            d = fs[v]
            partes = [d["base"]] + ([d["mt"]] if modo in ("multitenant", "citus") else []) + ([d["citus"]] if modo == "citus" else [])
            textos = [p.read_text(encoding="utf-8") for p in partes if p is not None]
            if not textos:
                raise ErrorDeMigracion(f"la versión {v} no tiene fichero aplicable al modo {modo}")
            descripcion = (textos[0].splitlines()[0].lstrip("- ").strip() if textos[0].startswith("--") else d["nombre"].replace("_", " "))[:200]
            try:
                conn.ejecutar_script("\n".join(textos), por_sentencias=(modo == "citus"))
            except Exception as e:                                                                   # noqa: BLE001
                raise ErrorDeMigracion(f"migración {v} ({', '.join(p.name for p in partes if p)}) falló: {type(e).__name__}: {str(e).splitlines()[0][:200]}") from e
            raw.execute("INSERT INTO bd_esquema_version (version, aplicada_en, descripcion) VALUES (%s, to_char(localtimestamp, 'YYYY-MM-DD\"T\"HH24:MI:SS'), %s)", (v, descripcion))
            aplicadas.append(v)
            if informar:
                informar(v, descripcion)
    finally:
        raw.execute("SELECT pg_advisory_unlock(hashtext(%s))", (_CLAVE_BLOQUEO,))
    return aplicadas


def comprobar(conn) -> None:
    """Para el arranque: la base tiene que estar al menos en la versión que espera el código."""
    actual, esperada = version_actual(conn), version_esperada()
    if actual is not None and actual < esperada:
        raise ErrorDeMigracion(f"el esquema de la base de datos es el {actual} y este código necesita el {esperada}: ejecuta scripts/migrar_esquema_pg.py (con el superusuario) antes de arrancar")
