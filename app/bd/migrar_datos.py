"""Copia los datos de una base SQLite a la de PostgreSQL (esquema multitenant ya creado).

Sirve para la carga definitiva de producción (fase 8), para las plantillas de las pruebas (fase 7) y para los ensayos con una copia de producción. Solo LEE la base de SQLite:
trabaja sobre una copia temporal a la que añade el `tenant_id` que falta (app/bd/tenant.py) y que luego carga con COPY.

  * Orden: tablas de referencia, tablas de un despacho (padres antes que hijas) y tablas locales. Con `sin_comprobaciones` (superusuario) se desactivan triggers y claves foráneas
    durante la carga y después se comprueba que no queda ninguna fila huérfana.
  * Lo que no cabe (un texto donde va un entero, un NUL en un texto…) se señala con la tabla, la columna y el valor, no con un error genérico de COPY.
  * Al final se ajustan las secuencias de identidad para que el siguiente id sea el máximo + 1.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import time

from . import tenant

LOTE = 5000
SALTAR = {"bd_esquema_version"}


class ErrorDeCarga(Exception):
    pass


def _hay_citus(raw) -> bool:
    return raw.execute("SELECT 1 FROM pg_extension WHERE extname = 'citus'").fetchone() is not None


def _columnas_pg(conn_pg, tabla: str) -> list[tuple[str, str, bool]]:
    """[(columna, tipo, generada)] de una tabla de PostgreSQL."""
    return [(r[0], r[1], r[2] == "ALWAYS") for r in conn_pg.execute(
        "SELECT column_name, data_type, is_generated FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = %s ORDER BY ordinal_position",
        (tabla,)).fetchall()]


def _orden(clases: dict) -> list[str]:
    referencia = [t for t, c in clases.items() if c.nombre == "referencia"]
    # tenants antes que usuarios antes que lo demás de referencia (usuarios.tenant_id → tenants)
    primeras = [t for t in ("tenants", "planes_guilda", "usuarios", "usuarios_tenants") if t in referencia]
    return primeras + [t for t in referencia if t not in primeras] + tenant.orden_de_relleno(clases) + [t for t, c in clases.items() if c.nombre == "local"]


def orden_de_carga(raw, preferido: list[str]) -> list[str]:
    """`preferido` reordenado para que cada tabla vaya DESPUÉS de las tablas a las que apuntan sus claves foráneas reales (en Citus se comprueban durante la carga). Entre las que
    pueden ir, se respeta el orden de `preferido`. Las claves de una tabla hacia sí misma se ignoran; un ciclo entre tablas deja el resto en el orden preferido."""
    posicion = {t: i for i, t in enumerate(preferido)}
    padres: dict[str, set[str]] = {t: set() for t in preferido}
    for hija, padre in raw.execute("SELECT c.conrelid::regclass::text, c.confrelid::regclass::text FROM pg_constraint c WHERE c.contype = 'f' AND c.conrelid <> c.confrelid").fetchall():
        if hija in padres and padre in posicion:
            padres[hija].add(padre)
    hechas: set[str] = set()
    orden: list[str] = []
    pendientes = list(preferido)
    while pendientes:
        listas = [t for t in pendientes if padres[t] <= hechas]
        if not listas:
            orden += pendientes
            break
        t = min(listas, key=posicion.__getitem__)
        orden.append(t)
        hechas.add(t)
        pendientes.remove(t)
    return orden


def copiar(ruta_sqlite, conn_pg, *, sin_comprobaciones: bool = True, informar=None, informe: dict | None = None) -> dict[str, int]:
    """Carga todos los datos. `conn_pg` es una conexión (psycopg o ConexionPG) de un superusuario cuando `sin_comprobaciones`. Devuelve {tabla: filas}.
    Con `informe` (un diccionario vacío) ejecuta además los controles de app/bd/verificar_migracion.py contra la copia de SQLite y deja en él el resultado."""
    raw = getattr(conn_pg, "_raw", conn_pg)
    clases = tenant.cargar_modelo()
    directorio = tempfile.mkdtemp(prefix="guilda-migracion-")
    try:
        origen = sqlite3.connect(f"file:{ruta_sqlite}?mode=ro", uri=True)
        copia = os.path.join(directorio, "copia.db")
        destino = sqlite3.connect(copia)
        origen.backup(destino)
        origen.close()
        tenant.rellenar(destino, crear_columnas=True, por_defecto=tenant.TENANT_PLATAFORMA)
        destino.row_factory = None
        existentes = set(tenant.tablas_de_datos(destino))
        con_disparadores: list[str] = []
        if sin_comprobaciones:
            raw.execute("SET session_replication_role = replica")
            # En Citus ese ajuste no llega a los fragmentos: los disparadores (registro de cambios, versiones…) se desactivan tabla a tabla y se reactivan al terminar.
            con_disparadores = [r[0] for r in raw.execute(
                "SELECT DISTINCT c.relname FROM pg_trigger g JOIN pg_class c ON c.oid = g.tgrelid WHERE NOT g.tgisinternal AND c.relnamespace = current_schema()::regnamespace "
                "AND c.relkind IN ('r', 'p')").fetchall()]
            if con_disparadores:
                raw.execute("SET citus.enable_unsafe_triggers = true") if _hay_citus(raw) else None
            for t in con_disparadores:
                raw.execute(f'ALTER TABLE "{t}" DISABLE TRIGGER USER')
        cargadas: dict[str, int] = {}
        usadas: dict[str, list[str]] = {}
        tiempos: dict[str, float] = {}
        avisos: dict[str, dict[str, int]] = {}
        preferido = [t for t in _orden(clases) if t in existentes and t not in SALTAR]
        try:
            for t in orden_de_carga(raw, preferido):
                cols_sqlite = [r[1] for r in destino.execute(f'PRAGMA table_info("{t}")')]
                cols_pg = {c: g for c, _t, g in _columnas_pg(raw, t)}
                cols = [c for c in cols_sqlite if c in cols_pg and not cols_pg[c]]            # sin las columnas generadas (búsqueda)
                if not cols:
                    continue
                t0 = time.monotonic()
                n = _copiar_tabla(destino, raw, t, cols, avisos)
                tiempos[t] = round(time.monotonic() - t0, 2)
                usadas[t] = cols
                if n:
                    cargadas[t] = n
                if informar:
                    informar(t, n)
        finally:
            for t in con_disparadores:
                raw.execute(f'ALTER TABLE "{t}" ENABLE TRIGGER USER')
            if sin_comprobaciones:
                raw.execute("SET session_replication_role = DEFAULT")
        # El despacho principal de cada persona figura siempre entre sus despachos (lo que hace init_db en SQLite): una base anterior a la tabla no la trae rellena.
        creadas = raw.execute("INSERT INTO usuarios_tenants (usuario_id, tenant_id, creado_en) SELECT id, tenant_id, to_char(localtimestamp, 'YYYY-MM-DD\"T\"HH24:MI:SS') "
                              "FROM usuarios WHERE tenant_id IS NOT NULL ON CONFLICT DO NOTHING").rowcount
        _ajustar_identidades(raw, list(cargadas))
        if informe is not None:
            from . import verificar_migracion
            informe.update(verificar_migracion.verificar(destino, raw, usadas))
            informe["segundos_de_carga"] = tiempos
            informe["nul_eliminados"] = avisos
            informe["pertenencias_creadas"] = creadas
        destino.close()
        if sin_comprobaciones and informe is None:
            huerfanas = comprobar_claves(raw)
            if huerfanas:
                raise ErrorDeCarga("filas huérfanas tras la carga: " + "; ".join(f"{t}.{fk}: {n}" for t, fk, n in huerfanas[:15]))
        return cargadas
    finally:
        shutil.rmtree(directorio, ignore_errors=True)


def _copiar_tabla(origen, raw, tabla: str, cols: list[str], avisos: dict | None = None) -> int:
    """COPY por lotes. Un texto con bytes NUL (PostgreSQL no los admite en `text`) se carga sin ellos y se anota en `avisos[tabla][columna]` = filas afectadas."""
    lista = ", ".join(f'"{c}"' for c in cols)
    cur = origen.execute(f'SELECT {lista} FROM "{tabla}"')
    total = 0
    while True:
        filas = cur.fetchmany(LOTE)
        if not filas:
            break
        filas = [_sin_nul(f, cols, tabla, avisos) for f in filas]
        try:
            with raw.cursor() as c, c.copy(f'COPY "{tabla}" ({lista}) FROM STDIN') as copy:
                for f in filas:
                    copy.write_row(f)
        except Exception as e:                                                                  # noqa: BLE001
            raw.rollback() if not raw.autocommit else None
            culpable = _buscar_fila_rechazada(raw, tabla, cols, filas)
            raise ErrorDeCarga(f"{tabla}: {culpable or e}") from e
        total += len(filas)
    return total


def _sin_nul(fila, cols, tabla, avisos):
    if not any(isinstance(v, str) and "\x00" in v for v in fila):
        return fila
    nueva = list(fila)
    for i, v in enumerate(nueva):
        if isinstance(v, str) and "\x00" in v:
            nueva[i] = v.replace("\x00", "")
            if avisos is not None:
                por_columna = avisos.setdefault(tabla, {})
                por_columna[cols[i]] = por_columna.get(cols[i], 0) + 1
    return tuple(nueva)


def _buscar_fila_rechazada(raw, tabla: str, cols: list[str], filas) -> str | None:
    """Reintenta fila a fila (en una transacción que se deshace) para decir cuál se rechaza y por qué."""
    lista = ", ".join(f'"{c}"' for c in cols)
    marcas = ", ".join(["%s"] * len(cols))
    for fila in filas:
        try:
            raw.execute("SAVEPOINT prueba") if not raw.autocommit else raw.execute("BEGIN")
            raw.execute(f'INSERT INTO "{tabla}" ({lista}) VALUES ({marcas})', fila)
            raw.execute("ROLLBACK TO SAVEPOINT prueba") if not raw.autocommit else raw.execute("ROLLBACK")
        except Exception as e:                                                                  # noqa: BLE001
            try:
                raw.execute("ROLLBACK")
            except Exception:                                                                   # noqa: BLE001
                pass
            return f"fila {dict((c, (repr(v)[:60])) for c, v in zip(cols, fila))}: {str(e).splitlines()[0]}"
    return None


def _ajustar_identidades(raw, tablas: list[str]) -> None:
    for t in tablas:
        fila = raw.execute("SELECT a.attname FROM pg_attribute a WHERE a.attrelid = to_regclass(%s) AND a.attidentity <> '' AND NOT a.attisdropped", (t,)).fetchone()
        if fila:
            c = fila[0]
            raw.execute(f'SELECT setval(pg_get_serial_sequence(%s, %s), COALESCE((SELECT MAX("{c}") FROM "{t}"), 0) + 1, false)', (f'"{t}"', c))


def comprobar_claves(raw) -> list[tuple[str, str, int]]:
    """[(tabla, clave foránea, filas huérfanas)] de las claves foráneas que NO se cumplen. La carga las desactiva (triggers en modo réplica), así que se comprueban a mano: una
    fila con la clave rellena y sin padre."""
    malas = []
    claves = raw.execute(
        "SELECT c.conrelid::regclass::text, c.conname, "
        "(SELECT array_agg(a.attname ORDER BY k.o) FROM unnest(c.conkey) WITH ORDINALITY k(n, o) JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.n), "
        "c.confrelid::regclass::text, "
        "(SELECT array_agg(a.attname ORDER BY k.o) FROM unnest(c.confkey) WITH ORDINALITY k(n, o) JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.n) "
        "FROM pg_constraint c WHERE c.contype = 'f' AND c.connamespace = current_schema()::regnamespace").fetchall()
    for hija, nombre, cols_h, padre, cols_p in claves:
        con_valor = " AND ".join(f'h."{c}" IS NOT NULL' for c in cols_h)
        igual = " AND ".join(f'p."{cp}" = h."{ch}"' for ch, cp in zip(cols_h, cols_p))
        n = raw.execute(f"SELECT count(*) FROM {hija} h WHERE {con_valor} AND NOT EXISTS (SELECT 1 FROM {padre} p WHERE {igual})").fetchone()[0]
        if n:
            malas.append((hija, nombre, n))
    return malas
