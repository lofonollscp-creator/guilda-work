"""Catálogo global de reglas fiscales (fase D del control fiscal): qué modelos hay en cada país y cuándo vencen. Es **de la plataforma**, no de cada despacho: lo escribe y lo aprueba
el propietario desde el backoffice (backoffice/rutas_reglas.py), con versiones y auditoría, igual que las reglas laborales (app/reglas_laborales.py).

Hasta ahora las fechas vivían en el código (app/vencimientos_fiscales.py:MODELOS_POR_PAIS). Al arrancar se **siembran como versión 1 ya aprobada** (aprobada por «valores de partida»)
los modelos que no tengan ninguna fila, así que el comportamiento no cambia hasta que el propietario edite algo. A partir de ahí manda la tabla: cada cambio crea una versión nueva **sin
aprobar** y la vigente sigue siendo la última aprobada. Una versión aprobada con «modelo en uso» desactivado retira el modelo del catálogo (los vencimientos ya generados no se tocan).

Lo que cambia una regla solo afecta a los vencimientos que se generen **a partir de entonces**: los ya generados conservan su fecha."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date

from . import auditoria, db, vencimientos_fiscales

logger = logging.getLogger(__name__)

TIPOS = ("trimestral", "anual")
ESQUEMA = """
CREATE TABLE IF NOT EXISTS reglas_fiscales (
    id INTEGER PRIMARY KEY,
    pais TEXT NOT NULL,
    modelo TEXT NOT NULL,
    version INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    tipo TEXT NOT NULL,
    fechas TEXT NOT NULL,
    activa INTEGER NOT NULL DEFAULT 1,
    nota TEXT,
    origen TEXT NOT NULL DEFAULT 'propietario',
    aprobada INTEGER NOT NULL DEFAULT 0,
    aprobada_por TEXT,
    aprobada_en TEXT,
    creada_por TEXT,
    creada_en TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_reglas_fiscales_version ON reglas_fiscales(pais, modelo, version);
"""
SEMBRADO_POR = "valores de partida (código)"


def crear_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(ESQUEMA)
    _sembrar(conn)


def _fechas_de_codigo(tipo: str, info: dict) -> dict:
    if tipo == "trimestral":
        return {str(t): [m, d] for t, (m, d) in info["trimestres"].items()}
    return {"mes": info["mes_dia"][0], "dia": info["mes_dia"][1], "anio_siguiente": 1 if info["anio_siguiente"] else 0}


def _sembrar(conn: sqlite3.Connection) -> None:
    """Versión 1 aprobada de cada modelo del código que aún no tenga ninguna fila (idempotente; nunca pisa lo que haya cambiado el propietario)."""
    ahora = db.now_iso()
    for pais, datos in vencimientos_fiscales.MODELOS_POR_PAIS.items():
        for tipo, grupo in (("trimestral", datos["trimestrales"]), ("anual", datos["anuales"])):
            for modelo, info in grupo.items():
                if conn.execute("SELECT 1 FROM reglas_fiscales WHERE pais = ? AND modelo = ? LIMIT 1", (pais, modelo)).fetchone() is None:
                    conn.execute("INSERT INTO reglas_fiscales (pais, modelo, version, nombre, tipo, fechas, activa, origen, aprobada, aprobada_por, aprobada_en, creada_por, creada_en) "
                                 "VALUES (?, ?, 1, ?, ?, ?, 1, 'codigo', 1, ?, ?, ?, ?)",
                                 (pais, modelo, info["nombre"], tipo, json.dumps(_fechas_de_codigo(tipo, info)), SEMBRADO_POR, ahora, SEMBRADO_POR, ahora))


# --- Validación -----------------------------------------------------------------------------------------------------------------------------------

def _mes_dia(mes, dia, etiqueta: str) -> list[int]:
    try:
        m, d = int(str(mes).strip()), int(str(dia).strip())
        date(2001, m, d)                     # un 29 de febrero no vale como fecha fija
    except (ValueError, TypeError):
        raise ValueError(f"{etiqueta}: indica un mes (1-12) y un día que existan en ese mes.") from None
    return [m, d]


def validar(tipo: str, datos: dict) -> tuple[str, dict]:
    """`(nombre, fechas)` limpios, o `ValueError` legible. `datos` trae `nombre` y, según el tipo, `m1`/`d1`…`m4`/`d4` (trimestral) o `mes`/`dia`/`anio_siguiente` (anual)."""
    if tipo not in TIPOS:
        raise ValueError("Tipo de modelo desconocido.")
    nombre = " ".join(str(datos.get("nombre", "")).split())[:120]
    if not nombre:
        raise ValueError("Indica el nombre del modelo.")
    if tipo == "trimestral":
        return nombre, {str(t): _mes_dia(datos.get(f"m{t}"), datos.get(f"d{t}"), f"Trimestre {t}") for t in range(1, 5)}
    mes, dia = _mes_dia(datos.get("mes"), datos.get("dia"), "Fecha límite")
    return nombre, {"mes": mes, "dia": dia, "anio_siguiente": 1 if str(datos.get("anio_siguiente", "")) in ("1", "on", "true", "True") else 0}


def _modelo_valido(modelo: str) -> str:
    modelo = (modelo or "").strip().upper()
    if not modelo or len(modelo) > 12 or not all(c.isalnum() or c in "-_" for c in modelo):
        raise ValueError("El código del modelo solo puede llevar letras, números, guion y guion bajo (máximo 12).")
    return modelo


# --- Lectura ---------------------------------------------------------------------------------------------------------------------------------------

def _fila(f) -> dict:
    d = dict(f)
    d["fechas"] = json.loads(d["fechas"])
    return d


def _vigentes_de(conn, pais: str) -> list[dict]:
    filas = conn.execute("SELECT * FROM reglas_fiscales WHERE pais = ? AND aprobada = 1 ORDER BY modelo, version DESC", (pais,)).fetchall()
    vistos, res = set(), []
    for f in filas:
        if f["modelo"] not in vistos:
            vistos.add(f["modelo"]); res.append(_fila(f))
    return res


def catalogo(pais: str) -> dict | None:
    """El calendario del país en el formato de `MODELOS_POR_PAIS[pais]` a partir de las últimas versiones **aprobadas** y en uso; None si no hay ninguna regla de ese país (entonces el
    llamante usa el código)."""
    conn = db.get_connection()
    try:
        vigentes = _vigentes_de(conn, pais)
    finally:
        conn.close()
    if not vigentes:
        return None
    trimestrales, anuales = {}, {}
    for r in vigentes:
        if not r["activa"]:
            continue
        if r["tipo"] == "trimestral":
            trimestrales[r["modelo"]] = {"nombre": r["nombre"], "trimestres": {int(t): tuple(v) for t, v in r["fechas"].items()}}
        else:
            f = r["fechas"]
            anuales[r["modelo"]] = {"nombre": r["nombre"], "mes_dia": (f["mes"], f["dia"]), "anio_siguiente": bool(f["anio_siguiente"])}
    return {"trimestrales": trimestrales, "anuales": anuales}


def _proveedor(pais: str) -> dict | None:
    try:
        return catalogo(pais)
    except Exception:  # noqa: BLE001 -- sin base de datos o con la tabla rota, el calendario sigue funcionando con los valores del código
        logger.exception("No se pudo leer el catálogo de reglas fiscales; se usan los valores del código")
        return None


vencimientos_fiscales.registrar_proveedor(_proveedor)


def estado_de_todos() -> list[dict]:
    """Para el backoffice: por país y modelo, la regla vigente, el borrador pendiente y las versiones anteriores."""
    conn = db.get_connection()
    try:
        filas = [_fila(f) for f in conn.execute("SELECT * FROM reglas_fiscales ORDER BY pais, modelo, version DESC")]
    finally:
        conn.close()
    claves = list(dict.fromkeys((f["pais"], f["modelo"]) for f in filas))
    res = []
    for pais, modelo in claves:
        propias = [f for f in filas if f["pais"] == pais and f["modelo"] == modelo]
        vig = next((f for f in propias if f["aprobada"]), None)
        borrador = next((f for f in propias if not f["aprobada"] and (vig is None or f["version"] > vig["version"])), None)
        res.append({"pais": pais, "modelo": modelo, "tipo": (vig or borrador)["tipo"], "vigente": vig, "borrador": borrador,
                    "historial": [f for f in propias if f is not vig and f is not borrador]})
    return res


# --- Escritura -------------------------------------------------------------------------------------------------------------------------------------

def guardar_borrador(pais: str, modelo: str, tipo: str, admin: str, activa: bool = True, nota: str | None = None, **datos) -> int:
    """Guarda como borrador sin aprobar (nuevo modelo o nueva versión de uno existente) y devuelve su versión. Si la última versión es un borrador sin aprobar se reescribe. Un modelo
    existente conserva su tipo. La vigente no cambia hasta `aprobar`."""
    pais = (pais or "").strip().upper()
    if not pais or len(pais) > 3 or not pais.isalpha():
        raise ValueError("Indica el país con su código de 2 letras (por ejemplo ES).")
    modelo = _modelo_valido(modelo)
    conn = db.get_connection()
    try:
        ultima = conn.execute("SELECT * FROM reglas_fiscales WHERE pais = ? AND modelo = ? ORDER BY version DESC LIMIT 1", (pais, modelo)).fetchone()
        if ultima is not None:
            tipo = ultima["tipo"]
        nombre, fechas = validar(tipo, datos)
        nota = (nota or "").strip()[:500] or None
        valores = (nombre, tipo, json.dumps(fechas), int(bool(activa)), nota, admin, db.now_iso())
        if ultima is not None and not ultima["aprobada"]:
            version = ultima["version"]
            conn.execute("UPDATE reglas_fiscales SET nombre = ?, tipo = ?, fechas = ?, activa = ?, nota = ?, creada_por = ?, creada_en = ? WHERE id = ?", (*valores, ultima["id"]))
        else:
            version = (ultima["version"] + 1) if ultima is not None else 1
            conn.execute("INSERT INTO reglas_fiscales (pais, modelo, version, nombre, tipo, fechas, activa, nota, creada_por, creada_en, aprobada) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                         (pais, modelo, version, *valores))
        auditoria.registrar(None, None, "regla_fiscal.borrador", "regla_fiscal", f"{pais}:{modelo}:{version}", {"por": admin, "tipo": tipo, "fechas": fechas, "activa": bool(activa)}, conn=conn)
        conn.commit()
        return version
    finally:
        conn.close()


def aprobar(pais: str, modelo: str, version: int, admin: str) -> None:
    """Pasa una versión a ser la vigente. Solo versiones más nuevas que la vigente."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM reglas_fiscales WHERE pais = ? AND modelo = ? AND version = ?", (pais, modelo, version)).fetchone()
        if f is None:
            raise ValueError("Esa versión no existe.")
        if f["aprobada"]:
            return
        vig = conn.execute("SELECT version FROM reglas_fiscales WHERE pais = ? AND modelo = ? AND aprobada = 1 ORDER BY version DESC LIMIT 1", (pais, modelo)).fetchone()
        if vig is not None and vig["version"] > version:
            raise ValueError("Ya hay una versión más reciente aprobada.")
        conn.execute("UPDATE reglas_fiscales SET aprobada = 1, aprobada_por = ?, aprobada_en = ? WHERE id = ?", (admin, db.now_iso(), f["id"]))
        auditoria.registrar(None, None, "regla_fiscal.aprobada", "regla_fiscal", f"{pais}:{modelo}:{version}", {"por": admin, "tipo": f["tipo"], "fechas": json.loads(f["fechas"]), "activa": bool(f["activa"])}, conn=conn)
        conn.commit()
    finally:
        conn.close()
