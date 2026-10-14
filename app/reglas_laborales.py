"""Reglas laborales de la plataforma: cuándo vencen el TC, el modelo 190 y los plazos que nacen de un alta, una baja o un contrato.

**No hay ninguna fecha legal en el código.** Las reglas viven en la tabla `reglas_laborales` (global de la plataforma, sin despacho) y están **vacías al instalar**: una regla que nadie ha
aprobado no genera nada. Las escribe y las aprueba el propietario desde el backoffice (backoffice/rutas_reglas.py); cada cambio crea una **versión nueva sin aprobar** y la vigente sigue
siendo la última aprobada hasta que se apruebe la siguiente. Todo queda en la auditoría. Es el germen del catálogo global de reglas del control fiscal (fase D): comparte su noción de
«versión aprobada por el propietario» en vez de inventar otra.

Las funciones de cálculo (`periodos_mensuales`, `periodo_anual`) son puras: reciben una regla (un diccionario) y devuelven fechas, sin base de datos ni Flask. El ajuste al siguiente día hábil
con los festivos del despacho lo hace quien las usa (app/perfil_fiscal.py:ajustar_a_calendario)."""
from __future__ import annotations

import calendar
import sqlite3
from datetime import date

from . import auditoria, db

# clave -> (tipo de regla, nombre). El 111 no está: ya existe en app/vencimientos_fiscales.py. Las nóminas tampoco: su día es una preferencia de cada despacho (app/laboral.py).
CLAVES: dict[str, tuple[str, str]] = {
    "tc": ("mensual", "Cotizaciones a la Seguridad Social (TC)"),
    "m190": ("anual", "Modelo 190 (resumen anual de retenciones)"),
    "alta_ss": ("desde_hecho", "Alta de un trabajador en la Seguridad Social"),
    "baja_ss": ("desde_hecho", "Baja de un trabajador en la Seguridad Social"),
    "contrato": ("desde_hecho", "Comunicación del contrato"),
}
UNIDADES = ("habiles", "naturales", "meses")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS reglas_laborales (
    id INTEGER PRIMARY KEY,
    clave TEXT NOT NULL,
    version INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    dia INTEGER,
    mes INTEGER,
    mes_siguiente INTEGER NOT NULL DEFAULT 0,
    anio_siguiente INTEGER NOT NULL DEFAULT 0,
    plazo INTEGER,
    unidad TEXT,
    nota TEXT,
    aprobada INTEGER NOT NULL DEFAULT 0,
    aprobada_por TEXT,
    aprobada_en TEXT,
    creada_por TEXT,
    creada_en TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_reglas_laborales_version ON reglas_laborales(clave, version);
"""
PARAMETROS = ("dia", "mes", "mes_siguiente", "anio_siguiente", "plazo", "unidad")


def crear_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(ESQUEMA)


# --- Cálculo puro --------------------------------------------------------------------------------------------------------------------------------------

def _dia_valido(anio: int, mes: int, dia: int) -> date:
    """El día pedido del mes, o el último si el mes no llega a él (30 en febrero → 28/29)."""
    return date(anio, mes, min(dia, calendar.monthrange(anio, mes)[1]))


def periodos_mensuales(regla: dict, anio: int) -> list[dict]:
    """Los 12 periodos `AAAA-MM` del año `anio` con su fecha límite: el día `dia` del propio mes del periodo, o del siguiente si `mes_siguiente` (diciembre salta a enero)."""
    res = []
    for mes in range(1, 13):
        destino_mes, destino_anio = (mes % 12 + 1, anio + (mes == 12)) if regla.get("mes_siguiente") else (mes, anio)
        res.append({"periodo": f"{anio}-{mes:02d}", "fecha_limite": _dia_valido(destino_anio, destino_mes, int(regla["dia"])).isoformat()})
    return res


def periodo_anual(regla: dict, anio: int) -> dict:
    """El periodo `AAAA-anual` del año `anio`: el día/mes de la regla, en el año siguiente si `anio_siguiente`."""
    return {"periodo": f"{anio}-anual", "fecha_limite": _dia_valido(anio + (1 if regla.get("anio_siguiente") else 0), int(regla["mes"]), int(regla["dia"])).isoformat()}


def validar(clave: str, datos: dict) -> dict:
    """Los parámetros limpios de una regla de esa clave, o `ValueError` con un mensaje legible. Solo se conservan los que su tipo usa."""
    if clave not in CLAVES:
        raise ValueError("Regla desconocida.")
    tipo = CLAVES[clave][0]

    def entero(campo: str, etiqueta: str, minimo: int, maximo: int) -> int:
        try:
            v = int(str(datos.get(campo, "")).strip())
        except ValueError:
            raise ValueError(f"{etiqueta}: indica un número.") from None
        if not minimo <= v <= maximo:
            raise ValueError(f"{etiqueta}: debe estar entre {minimo} y {maximo}.")
        return v

    limpio: dict = {}
    if tipo in ("mensual", "anual"):
        limpio["dia"] = entero("dia", "Día", 1, 31)
    if tipo == "anual":
        limpio["mes"] = entero("mes", "Mes", 1, 12)
        limpio["anio_siguiente"] = 1 if str(datos.get("anio_siguiente", "")) in ("1", "on", "true", "True") else 0
    if tipo == "mensual":
        limpio["mes_siguiente"] = 1 if str(datos.get("mes_siguiente", "")) in ("1", "on", "true", "True") else 0
    if tipo == "desde_hecho":
        limpio["plazo"] = entero("plazo", "Plazo", -3650, 3650)
        unidad = str(datos.get("unidad", "")).strip()
        if unidad not in UNIDADES:
            raise ValueError("Unidad: elige días hábiles, naturales o meses.")
        limpio["unidad"] = unidad
    return limpio


# --- Versiones y aprobación ----------------------------------------------------------------------------------------------------------------------------

def _regla(f) -> dict:
    return dict(f)


def vigente(clave: str) -> dict | None:
    """La última versión **aprobada** de la regla, o None si nadie la ha aprobado (entonces no se genera nada)."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM reglas_laborales WHERE clave = ? AND aprobada = 1 ORDER BY version DESC LIMIT 1", (clave,)).fetchone()
        return _regla(f) if f else None
    finally:
        conn.close()


def vigentes() -> dict[str, dict]:
    return {c: r for c in CLAVES if (r := vigente(c)) is not None}


def estado_de_todas() -> list[dict]:
    """Para la pantalla del backoffice: de cada clave, su regla vigente, el borrador pendiente de aprobar (si lo hay) y las versiones anteriores."""
    conn = db.get_connection()
    try:
        filas = [_regla(f) for f in conn.execute("SELECT * FROM reglas_laborales ORDER BY clave, version DESC")]
    finally:
        conn.close()
    res = []
    for clave, (tipo, nombre) in CLAVES.items():
        propias = [f for f in filas if f["clave"] == clave]
        vig = next((f for f in propias if f["aprobada"]), None)
        borrador = next((f for f in propias if not f["aprobada"] and (vig is None or f["version"] > vig["version"])), None)
        res.append({"clave": clave, "tipo": tipo, "nombre": nombre, "vigente": vig, "borrador": borrador, "historial": [f for f in propias if f is not vig and f is not borrador]})
    return res


def guardar_borrador(clave: str, admin: str, **datos) -> int:
    """Guarda los parámetros como borrador sin aprobar y devuelve su versión. Si la última versión es un borrador sin aprobar se reescribe; si es la aprobada (o no hay ninguna) se crea
    una versión nueva. La vigente no cambia hasta `aprobar`."""
    limpio = validar(clave, datos)
    nota = (datos.get("nota") or "").strip()[:500] or None
    conn = db.get_connection()
    try:
        ultima = conn.execute("SELECT * FROM reglas_laborales WHERE clave = ? ORDER BY version DESC LIMIT 1", (clave,)).fetchone()
        valores = {c: limpio.get(c) for c in PARAMETROS}
        valores["mes_siguiente"] = valores["mes_siguiente"] or 0
        valores["anio_siguiente"] = valores["anio_siguiente"] or 0
        if ultima is not None and not ultima["aprobada"]:
            version = ultima["version"]
            conn.execute(f"UPDATE reglas_laborales SET {', '.join(f'{c} = ?' for c in valores)}, nota = ?, creada_por = ?, creada_en = ? WHERE id = ?",
                         (*valores.values(), nota, admin, db.now_iso(), ultima["id"]))
        else:
            version = (ultima["version"] + 1) if ultima is not None else 1
            conn.execute(f"INSERT INTO reglas_laborales (clave, version, tipo, {', '.join(valores)}, nota, aprobada, creada_por, creada_en) VALUES (?, ?, ?, {', '.join('?' * len(valores))}, ?, 0, ?, ?)",
                         (clave, version, CLAVES[clave][0], *valores.values(), nota, admin, db.now_iso()))
        auditoria.registrar(None, None, "regla_laboral.borrador", "regla_laboral", f"{clave}:{version}", {"por": admin, **limpio}, conn=conn)
        conn.commit()
        return version
    finally:
        conn.close()


def aprobar(clave: str, version: int, admin: str) -> None:
    """Aprueba una versión: pasa a ser la vigente. Solo se aprueban versiones más nuevas que la vigente (las anteriores quedan de historial)."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM reglas_laborales WHERE clave = ? AND version = ?", (clave, version)).fetchone()
        if f is None:
            raise ValueError("Esa versión no existe.")
        if f["aprobada"]:
            return
        vig = conn.execute("SELECT version FROM reglas_laborales WHERE clave = ? AND aprobada = 1 ORDER BY version DESC LIMIT 1", (clave,)).fetchone()
        if vig is not None and vig["version"] > version:
            raise ValueError("Ya hay una versión más reciente aprobada.")
        conn.execute("UPDATE reglas_laborales SET aprobada = 1, aprobada_por = ?, aprobada_en = ? WHERE id = ?", (admin, db.now_iso(), f["id"]))
        auditoria.registrar(None, None, "regla_laboral.aprobada", "regla_laboral", f"{clave}:{version}",
                            {"por": admin, **{c: f[c] for c in PARAMETROS if f[c] is not None}}, conn=conn)
        conn.commit()
    finally:
        conn.close()
