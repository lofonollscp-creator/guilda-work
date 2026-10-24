"""Exportación INVERSA PostgreSQL -> SQLite (fase 11): la vía de vuelta atrás del corte. Durante las horas/días siguientes al paso a PostgreSQL se siguen escribiendo datos; si hubiera que volver
a SQLite, esos datos no pueden perderse. Este módulo construye un `registro.db` (y un `backoffice.db`) nuevos y completos desde la base de datos viva.

  * Los ficheros destino se crean con el esquema de la aplicación (`db.init_db()` / `backoffice.auth`), así que traen sus índices, triggers y tablas FTS5; los datos se cargan encima.
  * Se copian las columnas que SQLite tiene (el `tenant_id` que PostgreSQL añadió a casi todas las tablas se descarta donde SQLite no lo tenía; el despacho 0 «Plataforma» vuelve a ser NULL
    donde la columna admite nulos) y se saltan las generadas (`busqueda`). Los triggers de SQLite alimentan los índices FTS5 al insertar; los que escriben en otras tablas
    (registro de cambios, clientes de tarea) se compensan: esas tablas se vacían y se cargan al final tal como están en PostgreSQL.
  * Al terminar, cada tabla se lee de vuelta de SQLite y se compara (filas y suma de control por columna) con lo que se leyó de PostgreSQL; además `integrity_check` y `foreign_key_check`.
  * Solo LEE PostgreSQL. Necesita un rol que vea todo (el superusuario): `guilda_plataforma` no ve el esquema `backoffice`.

Hay que ejecutarlo con GUILDA_DB_ENGINE=sqlite (scripts/exportar_a_sqlite.py lo fuerza): `init_db()` crea el esquema de SQLite.
"""
from __future__ import annotations

import sqlite3
import time
from decimal import Decimal
from pathlib import Path

from .migrar_datos import TABLAS_BACKOFFICE
from .verificar_migracion import SEMILLAS_PG, huella

LOTE = 5000
SIN_EXPORTAR = {"bd_esquema_version"}                      # propias de PostgreSQL
RECARGAR_AL_FINAL = ("api_cambios", "tarea_clientes")       # las rellenan triggers de SQLite al insertar en otras tablas


class ErrorDeExportacion(Exception):
    pass


def _valor(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() and "." not in str(v) else float(v)
    if isinstance(v, memoryview):
        return bytes(v)
    return v


def _tablas_sqlite(lite) -> dict[str, list[tuple]]:
    """{tabla: [(nombre, tipo, notnull)]} de las tablas reales (no virtuales ni internas) de la base de SQLite."""
    tablas = {}
    for nombre, sql in lite.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall():
        if sql and sql.upper().startswith("CREATE VIRTUAL"):
            continue
        tablas[nombre] = [(r[1], r[2], r[3]) for r in lite.execute(f'PRAGMA table_info("{nombre}")')]
    return tablas


def _filas_pg(pg, sql: str):
    import psycopg
    with pg.transaction():
        with pg.cursor(name="exportar_sqlite", row_factory=psycopg.rows.tuple_row) as cur:
            cur.itersize = LOTE
            cur.execute(sql)
            while True:
                lote = cur.fetchmany(LOTE)
                if not lote:
                    return
                yield from lote


def _copiar(pg, lite, tabla_pg: str, tabla_sqlite: str, columnas: list[tuple], esquema: str | None = None) -> dict:
    """Copia una tabla. Devuelve {filas, columnas, huella_origen, ...}. `columnas` = las de SQLite (nombre, tipo, notnull)."""
    en_pg = {r[0]: r[1] for r in pg.execute(
        "SELECT column_name, is_generated FROM information_schema.columns WHERE table_schema = %s AND table_name = %s", (esquema or "public", tabla_pg)).fetchall()}
    cols = [c for c in columnas if c[0] in en_pg and en_pg[c[0]] != "ALWAYS"]
    if not cols:
        return {"filas": 0, "columnas": []}
    nombres = [c[0] for c in cols]
    # el despacho 0 «Plataforma» vuelve a ser NULL donde SQLite admite nulos (en PostgreSQL es el valor por defecto de «sin despacho»)
    a_nulo = {i for i, c in enumerate(cols) if c[0] == "tenant_id" and not c[2]}
    lista = ", ".join(f'"{c}"' for c in nombres)
    origen = f'"{esquema}"."{tabla_pg}"' if esquema else f'"{tabla_pg}"'
    marcas = ", ".join("?" * len(cols))
    n = 0
    lote_sqlite = []

    def volcar():
        nonlocal lote_sqlite
        if lote_sqlite:
            lite.executemany(f'INSERT INTO "{tabla_sqlite}" ({lista}) VALUES ({marcas})', lote_sqlite)
            lote_sqlite = []
    donde = f" WHERE {SEMILLAS_PG[tabla_pg]}" if not esquema and tabla_pg in SEMILLAS_PG else ""       # (el despacho 0 «Plataforma» lo crea el esquema de PostgreSQL)
    for fila in _filas_pg(pg, f"SELECT {lista} FROM {origen}{donde}"):
        fila = tuple(None if (i in a_nulo and v == 0) else _valor(v) for i, v in enumerate(fila))
        n += 1
        lote_sqlite.append(fila)
        if len(lote_sqlite) >= LOTE:
            volcar()
    volcar()
    return {"filas": n, "columnas": nombres}


def _leer_de_vuelta(lite, tabla: str, cols: list[str]):
    cur = lite.execute(f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{tabla}"')
    while True:
        lote = cur.fetchmany(LOTE)
        if not lote:
            return
        yield from lote


def _verificar(pg, lite, tabla_pg: str, tabla_sqlite: str, cols: list[str], esquema: str | None, a_nulo: set[str]) -> str | None:
    """Compara PostgreSQL (con el 0->NULL aplicado) y SQLite, columna a columna."""
    if not cols:
        return None
    lista = ", ".join(f'"{c}"' for c in cols)
    origen = f'"{esquema}"."{tabla_pg}"' if esquema else f'"{tabla_pg}"'
    indices_nulo = {i for i, c in enumerate(cols) if c in a_nulo}

    donde = f" WHERE {SEMILLAS_PG[tabla_pg]}" if not esquema and tabla_pg in SEMILLAS_PG else ""

    def desde_pg():
        for fila in _filas_pg(pg, f"SELECT {lista} FROM {origen}{donde}"):
            yield tuple(None if (i in indices_nulo and v == 0) else _valor(v) for i, v in enumerate(fila))
    n_p, h_p = huella(desde_pg(), len(cols))
    n_s, h_s = huella(_leer_de_vuelta(lite, tabla_sqlite, cols), len(cols))
    if n_p != n_s:
        return f"{tabla_sqlite}: {n_p} filas en PostgreSQL y {n_s} en SQLite"
    distintas = [c for c, a, b in zip(cols, h_p, h_s) if a != b]
    return f"{tabla_sqlite}: la suma de control difiere en {', '.join(distintas)}" if distintas else None


def exportar(pg, destino: str | Path, *, backoffice: str | Path | None = None, informar=None) -> dict:
    """Crea `destino` (registro.db) y, si se pide, `backoffice` (backoffice.db) desde la base de datos de `pg` (psycopg, autocommit, superusuario). Los ficheros NO pueden existir."""
    from app import db
    destino = Path(destino)
    if destino.exists():
        raise ErrorDeExportacion(f"{destino} ya existe: no se sobrescribe nada")
    if backoffice and Path(backoffice).exists():
        raise ErrorDeExportacion(f"{backoffice} ya existe: no se sobrescribe nada")
    anterior = db.DB_PATH
    db.DB_PATH = destino
    db.BACKUPS_DIR = destino.parent / "backups-exportacion"
    t0 = time.monotonic()
    informe: dict = {"tablas": {}, "discrepancias": [], "sin_exportar": [], "plataforma_conservadas": {}}
    try:
        db.init_db()                                          # esquema, índices, triggers y FTS5 de SQLite
        lite = sqlite3.connect(destino)
        lite.execute("PRAGMA foreign_keys = OFF")
        tablas = _tablas_sqlite(lite)
        en_pg = {r[0] for r in pg.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'").fetchall()}
        informe["sin_exportar"] = sorted(t for t in en_pg if t not in tablas and t not in SIN_EXPORTAR)
        a_nulo_de = {t: {c[0] for c in cols if c[0] == "tenant_id" and not c[2]} for t, cols in tablas.items()}
        # SQLite arranca con filas que crea init_db (semillas): se vacían las tablas con datos en PostgreSQL para que mande lo de PostgreSQL
        for t in tablas:
            if t in en_pg and t not in RECARGAR_AL_FINAL:
                lite.execute(f'DELETE FROM "{t}"') if _sin_trigger_de_borrado(lite, t) else None
        orden = [t for t in tablas if t in en_pg and t not in RECARGAR_AL_FINAL] + [t for t in RECARGAR_AL_FINAL if t in tablas and t in en_pg]
        usadas: dict[str, list[str]] = {}
        for t in orden:
            if t in RECARGAR_AL_FINAL:
                lite.execute(f'DELETE FROM "{t}"')
            r = _copiar(pg, lite, t, t, tablas[t])
            informe["tablas"][t] = r["filas"]
            usadas[t] = r["columnas"]
            if informar and r["filas"]:
                informar(t, r["filas"])
        lite.commit()
        lite.execute("PRAGMA foreign_keys = ON")
        # lo que quedó en «Plataforma» (despacho 0) en columnas que no admiten nulos no se puede traducir a NULL: se anota
        for t, cols in tablas.items():
            if t in en_pg and any(c[0] == "tenant_id" and c[2] for c in cols):
                n = lite.execute(f'SELECT count(*) FROM "{t}" WHERE tenant_id = 0').fetchone()[0]
                if n:
                    informe["plataforma_conservadas"][t] = n
        # comprobación de cada tabla (las compensadas por triggers se comparan igual: se recargaron al final)
        for t in orden:
            malo = _verificar(pg, lite, t, t, usadas[t], None, a_nulo_de[t])
            if malo:
                informe["discrepancias"].append(malo)
        integridad = lite.execute("PRAGMA integrity_check").fetchone()[0]
        informe["integrity_check"] = integridad
        informe["foreign_key_check"] = len(lite.execute("PRAGMA foreign_key_check").fetchall())
        if integridad != "ok":
            informe["discrepancias"].append(f"integrity_check: {integridad}")
        lite.close()
        if backoffice:
            informe["backoffice"] = _exportar_backoffice(pg, Path(backoffice))
            informe["discrepancias"] += informe["backoffice"]["discrepancias"]
    finally:
        db.DB_PATH = anterior
    informe["segundos"] = round(time.monotonic() - t0, 1)
    informe["ok"] = not informe["discrepancias"]
    return informe


def _sin_trigger_de_borrado(lite, tabla: str) -> bool:
    """Las tablas con un trigger que impide borrar (la auditoría de solo anexado) no se vacían: init_db no les mete filas."""
    return lite.execute("SELECT count(*) FROM sqlite_master WHERE type = 'trigger' AND tbl_name = ? AND sql LIKE '%BEFORE DELETE%'", (tabla,)).fetchone()[0] == 0


def _exportar_backoffice(pg, destino: Path) -> dict:
    """backoffice.db desde el esquema `backoffice`: se crea con backoffice.auth (esquema de SQLite) y se cargan las 10 tablas."""
    from backoffice import auth
    anterior = auth.DB_PATH
    auth.DB_PATH = destino
    informe = {"tablas": {}, "discrepancias": []}
    try:
        from app import bd
        motor, bd.MOTOR = bd.MOTOR, "sqlite"
        try:
            auth.conectar().close()                            # crea el fichero con su esquema
        finally:
            bd.MOTOR = motor
        lite = sqlite3.connect(destino)
        tablas = _tablas_sqlite(lite)
        for t in TABLAS_BACKOFFICE:
            if t not in tablas:
                continue
            r = _copiar(pg, lite, t, t, tablas[t], esquema="backoffice")
            informe["tablas"][t] = r["filas"]
            malo = _verificar(pg, lite, t, t, r["columnas"], "backoffice", set())
            if malo:
                informe["discrepancias"].append("backoffice." + malo)
        lite.commit()
        integridad = lite.execute("PRAGMA integrity_check").fetchone()[0]
        if integridad != "ok":
            informe["discrepancias"].append(f"backoffice.db integrity_check: {integridad}")
        lite.close()
    finally:
        auth.DB_PATH = anterior
    return informe
