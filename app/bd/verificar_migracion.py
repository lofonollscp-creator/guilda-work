"""Controles de una migración SQLite -> PostgreSQL (fase 8). Solo LEEN: comparan la copia de SQLite (con el `tenant_id` ya rellenado) con lo que hay en PostgreSQL.

  * recuento por tabla y por despacho;
  * suma de control por columna (independiente del orden de las filas): una discrepancia dice tabla y columna, no solo «algo no cuadra»;
  * tamaño total de los BLOB (bytea) por tabla;
  * filas huérfanas (claves foráneas que no se cumplen) y secuencias de identidad por detrás del máximo;
  * búsqueda de texto equivalente: unas palabras reales de cada índice dan las mismas filas en FTS5 y en tsvector.

El resultado es un diccionario que se guarda como informe; `informe["discrepancias"]` vacío significa que todo cuadra.
"""
from __future__ import annotations

import hashlib
import re
import time
from collections import Counter
from decimal import Decimal

LOTE = 5000
MASCARA = (1 << 64) - 1

# (tabla FTS5 de SQLite, tabla base, columna de texto con la que se eligen las palabras de prueba)
INDICES_BUSQUEDA = [
    ("correo_fts", "correo_mensajes", "asunto"),
    ("jur_fragmentos_fts", "jur_fragmentos", "texto"),
    ("jur_fragmentos_privados_fts", "jur_fragmentos_privados", "texto"),
]
PALABRAS_POR_INDICE = 25
# filas que pone el propio esquema de PostgreSQL y no vienen de SQLite (app/bd/esquema_pg/07_semillas.sql: el despacho 0 «Plataforma»)
SEMILLAS_PG = {"tenants": "id <> 0"}


def _canon(v) -> bytes:
    if v is None:
        return b"\0"
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, int):
        return b"i" + str(v).encode()
    if isinstance(v, Decimal):
        v = int(v) if v == v.to_integral_value() and "." not in str(v) else float(v)
        return _canon(v)
    if isinstance(v, float):
        return b"f" + repr(v).encode()
    if isinstance(v, str):
        return b"s" + v.replace("\x00", "").encode("utf-8", "surrogatepass")          # la carga quita los NUL (PostgreSQL no los admite)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return b"b" + bytes(v)
    return b"?" + repr(v).encode()


def huella(filas, ncols: int) -> tuple[int, list[int]]:
    """(número de filas, suma de control de cada columna). La suma de los hashes de 64 bits no depende del orden."""
    acumulado = [0] * ncols
    n = 0
    for fila in filas:
        n += 1
        for i, v in enumerate(fila):
            acumulado[i] = (acumulado[i] + int.from_bytes(hashlib.blake2b(_canon(v), digest_size=8).digest(), "big")) & MASCARA
    return n, acumulado


def _filas_pg(raw, sql: str):
    import psycopg
    with raw.transaction():
        with raw.cursor(name="verificar", row_factory=psycopg.rows.tuple_row) as cur:
            cur.itersize = LOTE
            cur.execute(sql)
            yield from cur


def _filas_sqlite(origen, sql: str):
    cur = origen.execute(sql)
    while True:
        lote = cur.fetchmany(LOTE)
        if not lote:
            return
        yield from lote


def _tablas_con_tenant(raw) -> set[str]:
    return {r[0] for r in raw.execute(
        "SELECT table_name FROM information_schema.columns WHERE table_schema = current_schema() AND column_name = 'tenant_id'").fetchall()}


def verificar(origen, raw, columnas: dict[str, list[str]], *, informar=None) -> dict:
    """`origen`: la copia de SQLite con el despacho rellenado; `raw`: conexión psycopg; `columnas`: {tabla: columnas cargadas}. Devuelve el informe."""
    inicio = time.monotonic()
    informe: dict = {"tablas": {}, "discrepancias": [], "por_despacho": {}, "blobs": {}, "busqueda": {}, "huerfanas": [], "secuencias": []}
    malas = informe["discrepancias"]
    con_tenant = _tablas_con_tenant(raw)
    tipos_bytea = {(t, c) for t, c in raw.execute(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = current_schema() AND data_type = 'bytea'").fetchall()}
    totales_despacho: Counter = Counter()
    por_tabla_y_despacho: dict[str, dict] = {}

    for tabla, cols in columnas.items():
        lista = ", ".join(f'"{c}"' for c in cols)
        n_o, h_o = huella(_filas_sqlite(origen, f'SELECT {lista} FROM "{tabla}"'), len(cols))
        donde = f" WHERE {SEMILLAS_PG[tabla]}" if tabla in SEMILLAS_PG else ""
        n_d, h_d = huella(_filas_pg(raw, f'SELECT {lista} FROM "{tabla}"{donde}'), len(cols))
        info = {"origen": n_o, "destino": n_d}
        if n_o != n_d:
            malas.append(f"{tabla}: {n_o} filas en SQLite y {n_d} en PostgreSQL")
        else:
            distintas = [c for c, a, b in zip(cols, h_o, h_d) if a != b]
            if distintas:
                info["columnas_distintas"] = distintas
                malas.append(f"{tabla}: la suma de control difiere en {', '.join(distintas)}")
        informe["tablas"][tabla] = info

        if "tenant_id" in cols and tabla in con_tenant:
            a = dict(origen.execute(f'SELECT tenant_id, COUNT(*) FROM "{tabla}" GROUP BY tenant_id').fetchall())
            b = dict(raw.execute(f'SELECT tenant_id, COUNT(*) FROM "{tabla}"{donde} GROUP BY tenant_id').fetchall())
            if a != b:
                malas.append(f"{tabla}: el recuento por despacho difiere ({ {k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)} })")
            totales_despacho.update({k: v for k, v in b.items() if k is not None})
            por_tabla_y_despacho[tabla] = b

        blobs = [c for c in cols if (tabla, c) in tipos_bytea]
        if blobs:
            expresion = " + ".join(f'COALESCE(length("{c}"), 0)' for c in blobs)
            exp_pg = " + ".join(f'COALESCE(octet_length("{c}"), 0)' for c in blobs)
            o = origen.execute(f'SELECT COALESCE(SUM({expresion}), 0) FROM "{tabla}"').fetchone()[0]
            d = raw.execute(f'SELECT COALESCE(SUM({exp_pg}), 0) FROM "{tabla}"').fetchone()[0]
            informe["blobs"][tabla] = {"origen": int(o), "destino": int(d)}
            if int(o) != int(d):
                malas.append(f"{tabla}: los BLOB ocupan {o} bytes en SQLite y {d} en PostgreSQL")
        if informar:
            informar(tabla, info)

    informe["por_despacho"] = {int(k): int(v) for k, v in sorted(totales_despacho.items())}

    from .migrar_datos import comprobar_claves
    for t, fk, n in comprobar_claves(raw):
        informe["huerfanas"].append(f"{t}.{fk}: {n}")
        malas.append(f"filas huérfanas en {t} ({fk}): {n}")

    for tabla in columnas:
        fila = raw.execute("SELECT a.attname FROM pg_attribute a WHERE a.attrelid = to_regclass(%s) AND a.attidentity <> '' AND NOT a.attisdropped", (f'"{tabla}"',)).fetchone()
        if not fila:
            continue
        c = fila[0]
        maximo = raw.execute(f'SELECT COALESCE(MAX("{c}"), 0) FROM "{tabla}"').fetchone()[0]
        seq = raw.execute("SELECT pg_get_serial_sequence(%s, %s)", (f'"{tabla}"', c)).fetchone()[0]
        ultimo, llamada = raw.execute(f"SELECT last_value, is_called FROM {seq}").fetchone()
        siguiente = ultimo + 1 if llamada else ultimo
        informe["secuencias"].append((tabla, int(maximo), int(siguiente)))
        if siguiente <= maximo:
            malas.append(f"{tabla}: la secuencia de {c} daría {siguiente} y ya existe {maximo}")

    sin_pertenencia = raw.execute("SELECT count(*) FROM usuarios u WHERE u.tenant_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM usuarios_tenants m WHERE m.usuario_id = u.id AND m.tenant_id = u.tenant_id)").fetchone()[0]
    if sin_pertenencia:
        malas.append(f"{sin_pertenencia} personas con despacho principal sin su fila en usuarios_tenants")
    _comprobar_roles(raw, informe, por_tabla_y_despacho)
    _comprobar_busqueda(origen, raw, informe)
    informe["segundos"] = round(time.monotonic() - inicio, 1)
    informe["ok"] = not malas
    return informe


def _comprobar_roles(raw, informe: dict, esperado: dict[str, dict]) -> None:
    """Con el rol de la aplicación (`guilda_app`, sin BYPASSRLS) y un despacho fijado, cada tabla de ese despacho devuelve exactamente sus filas: ni más (fuga) ni menos (política mal escrita)."""
    from . import tenant
    if raw.execute("SELECT 1 FROM pg_roles WHERE rolname = 'guilda_app'").fetchone() is None:
        return
    clases = tenant.cargar_modelo()
    tablas = [t for t in esperado if t in clases and clases[t].nombre in ("propio", "hija")
              and raw.execute("SELECT relrowsecurity FROM pg_class WHERE oid = to_regclass(%s)", (f'"{t}"',)).fetchone()[0]]
    despachos = sorted({k for t in tablas for k in esperado[t] if k and k > 0})[:5]
    comprobadas = 0
    for d in despachos:
        with raw.transaction():
            raw.execute("SET LOCAL ROLE guilda_app")
            raw.execute("SELECT set_config('app.tenant_id', %s, true)", (str(d),))
            for t in tablas:
                visibles = raw.execute(f'SELECT COUNT(*) FROM "{t}" WHERE tenant_id = %s', (d,)).fetchone()[0]
                todas = raw.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                comprobadas += 1
                if visibles != esperado[t].get(d, 0):
                    informe["discrepancias"].append(f"{t}: con el rol de la aplicación el despacho {d} ve {visibles} filas y debería ver {esperado[t].get(d, 0)}")
                elif todas != visibles:
                    informe["discrepancias"].append(f"{t}: con el rol de la aplicación el despacho {d} ve {todas - visibles} filas de otros despachos")
    informe["roles"] = {"despachos": despachos, "comprobaciones": comprobadas}


def _palabras(origen, tabla: str, columna: str) -> list[str]:
    cuenta: Counter = Counter()
    for (texto,) in _filas_sqlite(origen, f'SELECT "{columna}" FROM "{tabla}" WHERE "{columna}" IS NOT NULL LIMIT 20000'):
        for p in set(re.findall(r"[^\W\d_]{5,20}", texto.lower())):
            cuenta[p] += 1
    ordenadas = sorted(cuenta, key=lambda p: (-cuenta[p], p))
    if len(ordenadas) <= PALABRAS_POR_INDICE:
        return ordenadas
    paso = len(ordenadas) / PALABRAS_POR_INDICE                               # repartidas entre las frecuentes y las raras
    return [ordenadas[int(i * paso)] for i in range(PALABRAS_POR_INDICE)]


def _comprobar_busqueda(origen, raw, informe: dict) -> None:
    for fts, base, columna in INDICES_BUSQUEDA:
        existe_origen = origen.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (fts,)).fetchone()
        existe_destino = raw.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = %s AND column_name = 'busqueda'", (base,)).fetchone()
        if not (existe_origen and existe_destino):
            continue
        palabras = _palabras(origen, base, columna)
        distintas = []
        for p in palabras:
            try:
                a = {r[0] for r in origen.execute(f'SELECT rowid FROM "{fts}" WHERE "{fts}" MATCH ?', (f'"{p}"',))}
            except Exception as e:                                                                  # noqa: BLE001  (un índice FTS5 dañado en el origen también es un hallazgo)
                informe["discrepancias"].append(f"{fts}: el índice de SQLite falla con «{p}»: {e}")
                break
            b = {r[0] for r in raw.execute(f"SELECT id FROM \"{base}\" WHERE busqueda @@ plainto_tsquery('es_simple', %s)", (p,))}
            if a != b:
                distintas.append((p, len(a), len(b)))
        informe["busqueda"][base] = {"palabras": len(palabras), "distintas": distintas}
        if distintas:
            informe["discrepancias"].append(f"{base}: la búsqueda difiere en {len(distintas)} de {len(palabras)} palabras (p. ej. {distintas[:3]})")


def resumen(informe: dict) -> str:
    """Texto legible del informe (sin datos de los despachos, solo recuentos)."""
    filas = sum(t["destino"] for t in informe["tablas"].values())
    lineas = [f"{len(informe['tablas'])} tablas, {filas:,} filas, controles en {informe.get('segundos', '?')} s".replace(",", ".")]
    lineas.append("RESULTADO: " + ("todo cuadra" if informe["ok"] else f"{len(informe['discrepancias'])} discrepancias"))
    lineas += [f"  - {d}" for d in informe["discrepancias"][:40]]
    return "\n".join(lineas)
