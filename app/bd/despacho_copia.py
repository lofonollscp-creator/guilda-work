"""Copia y restauración de UN despacho (fase 10): sacar de una base de datos todo lo que es de un despacho y volver a ponerlo en otra (o en la misma) sin tocar a los demás.

Sirve para el caso más frecuente de recuperación —«se borró/estropeó lo de un despacho»— sin restaurar toda la plataforma: se recupera la copia física a un instante en una instancia
aparte (scripts/restaurar_postgres.sh), se exporta de ella el despacho y se importa en la base viva. También para pasar un despacho de una instalación a otra.

Qué lleva el fichero (.tar.gz, modo 0600): una entrada por tabla con COPY binario de las filas de ese `tenant_id` (todas las tablas de despacho del modelo, app/bd/tenant_modelo.json) y un
manifiesto con columnas, recuentos y una suma de control por columna (la misma de app/bd/verificar_migracion.py). Además lo mínimo de las tablas de referencia para que el despacho
tenga sentido: su fila de `tenants`, sus personas (`usuarios`, `usuario_perfil`) y su pertenencia (`usuarios_tenants`). NO lleva: la configuración global, el corpus jurídico compartido
(tablas locales) ni las filas de otros despachos de esas personas.

Importar: se niega si el despacho ya tiene datos (salvo `reemplazar`, que borra antes SOLO lo de ese despacho); las filas de referencia ya existentes se respetan; la auditoría (solo de
anexado) no se borra al reemplazar y se completa con lo que falte. Al terminar compara recuentos y sumas de control con el manifiesto. Hace falta un superusuario (desactiva triggers).
"""
from __future__ import annotations

import io
import json
import os
import tarfile
import tempfile
import time
from datetime import datetime

from . import tenant
from .migrar_datos import _ajustar_identidades, _columnas_pg, orden_de_carga, sin_disparadores
from .verificar_migracion import huella

VERSION_FORMATO = 1
CLASES_DE_DESPACHO = ("propio", "usuario", "hija")
TOLERANTES = ("auditoria_eventos",)            # solo de anexado: al importar se añade lo que falte, nunca se borra ni se sobrescribe
CHUNK = 1 << 20
# (tabla, filtro por despacho) de lo de referencia que acompaña al despacho, en el orden en que se carga
REFERENCIA = (
    ("tenants", "id = {t}"),
    ("usuarios", "id IN (SELECT usuario_id FROM usuarios_tenants WHERE tenant_id = {t})"),
    ("usuarios_tenants", "tenant_id = {t}"),
    ("usuario_perfil", "usuario_id IN (SELECT usuario_id FROM usuarios_tenants WHERE tenant_id = {t})"),
)


class ErrorDeCopia(Exception):
    pass


def _tablas_del_despacho(raw) -> list[str]:
    """Tablas con `tenant_id` en la base, en el orden en que se pueden cargar (padres antes que hijas)."""
    clases = tenant.cargar_modelo()
    con_columna = {r[0] for r in raw.execute(
        "SELECT table_name FROM information_schema.columns WHERE table_schema = current_schema() AND column_name = 'tenant_id'").fetchall()}
    preferido = [t for t in tenant.orden_de_relleno(clases) if clases[t].nombre in CLASES_DE_DESPACHO and t in con_columna]
    return orden_de_carga(raw, preferido)


def _columnas(raw, tabla: str) -> list[str]:
    return [c for c, _tipo, generada in _columnas_pg(raw, tabla) if not generada]            # (las generadas —búsqueda— las recalcula PostgreSQL)


def _version_esquema(raw) -> int | None:
    try:
        return raw.execute("SELECT max(version) FROM bd_esquema_version").fetchone()[0]
    except Exception:                                                                                # noqa: BLE001
        return None


def _consulta(tabla: str, columnas: list[str], filtro: str) -> str:
    return f'SELECT {", ".join(chr(34) + c + chr(34) for c in columnas)} FROM "{tabla}" WHERE {filtro}'


def _filas(raw, sql: str):
    import psycopg
    with raw.transaction():
        with raw.cursor(name="copia_despacho", row_factory=psycopg.rows.tuple_row) as cur:
            cur.itersize = 5000
            cur.execute(sql)
            yield from cur


def exportar(raw, tenant_id: int, destino: str, *, informar=None) -> dict:
    """Escribe en `destino` (.tar.gz) todo lo del despacho. `raw` es una conexión psycopg en autocommit. Devuelve el manifiesto."""
    tenant_id = int(tenant_id)
    fila = raw.execute("SELECT nombre FROM tenants WHERE id = %s", (tenant_id,)).fetchone()
    if fila is None:
        raise ErrorDeCopia(f"el despacho {tenant_id} no existe en esta base de datos")
    manifiesto: dict = {"formato": VERSION_FORMATO, "despacho": tenant_id, "nombre": fila[0], "fecha": datetime.now().isoformat(timespec="seconds"),
                        "version_esquema": _version_esquema(raw), "tablas": {}, "referencia": {}}
    t0 = time.monotonic()
    fd, ruta_tmp = tempfile.mkstemp(prefix=".despacho-", suffix=".tar.gz", dir=os.path.dirname(os.path.abspath(destino)) or ".")
    os.close(fd)
    try:
        with tarfile.open(ruta_tmp, "w:gz") as tar, tempfile.TemporaryDirectory(prefix="guilda-copia-") as tmp:
            for grupo, lista in (("referencia", [(t, f.format(t=tenant_id)) for t, f in REFERENCIA]),
                                 ("tablas", [(t, f"tenant_id = {tenant_id}") for t in _tablas_del_despacho(raw)])):
                for tabla, filtro in lista:
                    cols = _columnas(raw, tabla)
                    if not cols:
                        continue
                    consulta = _consulta(tabla, cols, filtro)
                    n_filas, hashes = huella(_filas(raw, consulta), len(cols))
                    if n_filas == 0:
                        continue
                    fichero = os.path.join(tmp, f"{grupo}-{tabla}.bin")
                    with open(fichero, "wb") as fh, raw.cursor() as cur, cur.copy(f"COPY ({consulta}) TO STDOUT (FORMAT BINARY)") as copia:
                        for bloque in copia:
                            fh.write(bloque)
                    tar.add(fichero, arcname=f"{grupo}/{tabla}.bin")
                    manifiesto[grupo][tabla] = {"filas": n_filas, "columnas": cols, "huella": hashes}
                    if informar:
                        informar(tabla, n_filas)
            manifiesto["segundos"] = round(time.monotonic() - t0, 1)
            datos = json.dumps(manifiesto, ensure_ascii=False, indent=1).encode()
            info = tarfile.TarInfo("manifiesto.json")
            info.size = len(datos)
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(datos))
        os.chmod(ruta_tmp, 0o600)
        os.replace(ruta_tmp, destino)
    except BaseException:
        if os.path.exists(ruta_tmp):
            os.unlink(ruta_tmp)
        raise
    return manifiesto


def leer_manifiesto(ruta: str) -> dict:
    with tarfile.open(ruta, "r:gz") as tar:
        return json.load(tar.extractfile("manifiesto.json"))


def importar(raw, ruta: str, *, reemplazar: bool = False, permitir_otra_version: bool = False, informar=None) -> dict:
    """Carga el fichero en la base de `raw` (superusuario, autocommit). Devuelve {tablas, borradas, segundos, ok, discrepancias}."""
    manifiesto = leer_manifiesto(ruta)
    if manifiesto.get("formato") != VERSION_FORMATO:
        raise ErrorDeCopia(f"formato de copia no reconocido: {manifiesto.get('formato')!r}")
    t_id = int(manifiesto["despacho"])
    version = _version_esquema(raw)
    if manifiesto.get("version_esquema") != version and not permitir_otra_version:
        raise ErrorDeCopia(f"la copia es del esquema {manifiesto.get('version_esquema')} y la base es del {version}: si el esquema no cambió en lo que importa, usa permitir_otra_version")
    tablas = [t for t in _tablas_del_despacho(raw)]
    con_datos = {}
    for t in tablas:
        n = raw.execute(f'SELECT count(*) FROM "{t}" WHERE tenant_id = %s', (t_id,)).fetchone()[0]
        if n and t not in TOLERANTES:
            con_datos[t] = n
    if con_datos and not reemplazar:
        raise ErrorDeCopia(f"el despacho {t_id} ya tiene datos en esta base ({', '.join(f'{t}: {n}' for t, n in list(con_datos.items())[:6])}…): usa reemplazar para borrarlos antes")
    t0 = time.monotonic()
    borradas: dict[str, int] = {}
    cargadas: dict[str, int] = {}
    with sin_disparadores(raw), tarfile.open(ruta, "r:gz") as tar:
        with raw.transaction():
            if raw.execute("SELECT current_setting('citus.multi_shard_modify_mode', true)").fetchone()[0] is not None:
                raw.execute("SET LOCAL citus.multi_shard_modify_mode TO 'sequential'")
            if reemplazar:
                for t in tenant._orden_de_borrado(raw, tablas):
                    if t in TOLERANTES:
                        continue
                    n = raw.execute(f'DELETE FROM "{t}" WHERE tenant_id = %s', (t_id,)).rowcount
                    if n:
                        borradas[t] = n
            for grupo in ("referencia", "tablas"):
                for tabla in ([t for t, _f in REFERENCIA] if grupo == "referencia" else tablas):
                    info = manifiesto[grupo].get(tabla)
                    if not info:
                        continue
                    cols = info["columnas"]
                    existentes = set(_columnas(raw, tabla))
                    faltan = [c for c in cols if c not in existentes]
                    if faltan:
                        raise ErrorDeCopia(f"{tabla}: la base de destino no tiene las columnas {', '.join(faltan)}")
                    cuantas = _cargar_tabla(raw, tar.extractfile(f"{grupo}/{tabla}.bin"), tabla, cols, tolerante=(grupo == "referencia" or tabla in TOLERANTES))
                    cargadas[tabla] = cuantas
                    if informar:
                        informar(tabla, cuantas)
        _ajustar_identidades(raw, [t for t in cargadas if t not in dict(REFERENCIA)])
    discrepancias = _comprobar(raw, manifiesto, t_id)
    return {"despacho": t_id, "tablas": cargadas, "borradas": borradas, "segundos": round(time.monotonic() - t0, 1), "ok": not discrepancias, "discrepancias": discrepancias}


def _cargar_tabla(raw, flujo, tabla: str, cols: list[str], *, tolerante: bool) -> int:
    lista = ", ".join(f'"{c}"' for c in cols)
    if not tolerante:
        with raw.cursor() as cur:
            with cur.copy(f'COPY "{tabla}" ({lista}) FROM STDIN (FORMAT BINARY)') as copia:
                while True:
                    bloque = flujo.read(CHUNK)
                    if not bloque:
                        break
                    copia.write(bloque)
            return cur.rowcount                                                                  # (el recuento solo existe cuando el COPY ya terminó)
    # lo que ya existe se respeta: se carga en una tabla temporal y se pasa con ON CONFLICT DO NOTHING
    raw.execute(f'CREATE TEMP TABLE "_imp_{tabla}" ON COMMIT DROP AS SELECT {lista} FROM "{tabla}" WITH NO DATA')
    with raw.cursor() as cur, cur.copy(f'COPY "_imp_{tabla}" ({lista}) FROM STDIN (FORMAT BINARY)') as copia:
        while True:
            bloque = flujo.read(CHUNK)
            if not bloque:
                break
            copia.write(bloque)
    return raw.execute(f'INSERT INTO "{tabla}" ({lista}) SELECT {lista} FROM "_imp_{tabla}" ON CONFLICT DO NOTHING').rowcount


def _comprobar(raw, manifiesto: dict, t_id: int) -> list[str]:
    """Recuentos y sumas de control de lo importado frente al manifiesto (la auditoría y la referencia pueden tener MÁS filas: solo se exige que estén las del manifiesto)."""
    malas = []
    for grupo, filtros in (("tablas", {t: f"tenant_id = {t_id}" for t in manifiesto["tablas"]}), ("referencia", {t: f.format(t=t_id) for t, f in REFERENCIA})):
        for tabla, info in manifiesto[grupo].items():
            cols = info["columnas"]
            n, hashes = huella(_filas(raw, _consulta(tabla, cols, filtros[tabla])), len(cols))
            if grupo == "referencia" or tabla in TOLERANTES:
                if n < info["filas"]:
                    malas.append(f"{tabla}: faltan filas ({n} de {info['filas']})")
            elif n != info["filas"]:
                malas.append(f"{tabla}: {n} filas y la copia tenía {info['filas']}")
            elif hashes != info["huella"]:
                distintas = [c for c, a, b in zip(cols, hashes, info["huella"]) if a != b]
                malas.append(f"{tabla}: la suma de control difiere en {', '.join(distintas)}")
    return malas
