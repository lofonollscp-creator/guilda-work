"""Gestión laboral de los clientes (primera rebanada): los trabajadores de cada cliente de la gestoría.

Solo guarda lo mínimo para llevar su gestión: identificación (nombre, NIF/NIE, número de afiliación), puesto, tipo de contrato, jornada y fechas de alta y baja. **No guarda
salarios ni calcula nóminas** y **no genera obligaciones ni fechas laborales** (TC, 111/190, altas y bajas): esas reglas las valida el propietario antes de entrar en el catálogo
fiscal (ver app/vencimientos_fiscales.py), así que aquí solo hay datos, no calendario.

Son datos personales de terceros (las personas que trabajan para el cliente): el acceso a la pestaña Laboral y cada alta, cambio o borrado quedan anotados en el registro de accesos
del cliente (`cliente_accesos`), que lo ven los supervisores; el borrado manda a la papelera y la papelera se vacía con el resto (app/rgpd.py:vaciar_papelera); y el cliente entra
en su exportación RGPD. Los permisos son los del cliente fiscal (oficinas, ver app/acceso.py)."""
from __future__ import annotations

import sqlite3
from datetime import date

from flask_babel import lazy_gettext as _l

from . import db, fiscal_identidad

TIPOS_CONTRATO = (
    ("indefinido", _l("Indefinido")), ("temporal", _l("Temporal")), ("practicas", _l("Prácticas")), ("formacion", _l("Formación")), ("otro", _l("Otro")),
)
_CLAVES_CONTRATO = {k for k, _ in TIPOS_CONTRATO}
CAMPOS = ("nombre", "nif", "naf", "puesto", "tipo_contrato", "jornada_horas_semana", "fecha_alta", "fecha_baja", "notas")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS trabajadores_cliente (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    nif TEXT,
    nif_normalizado TEXT,
    naf TEXT,
    puesto TEXT,
    tipo_contrato TEXT,
    jornada_horas_semana REAL,
    fecha_alta TEXT,
    fecha_baja TEXT,
    notas TEXT,
    creado_por INTEGER,
    creado_en TEXT NOT NULL,
    actualizado_en TEXT,
    papelera_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_trabajadores_cliente ON trabajadores_cliente(cliente_fiscal_id, papelera_en);
CREATE UNIQUE INDEX IF NOT EXISTS ux_trabajadores_cliente_nif ON trabajadores_cliente(cliente_fiscal_id, nif_normalizado)
    WHERE nif_normalizado IS NOT NULL AND papelera_en IS NULL;
"""


def crear_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(ESQUEMA)


def _texto(valor, maximo: int) -> str | None:
    valor = " ".join((valor or "").split())
    return valor[:maximo] or None


def _fecha(valor, campo: str) -> str | None:
    valor = (valor or "").strip()
    if not valor:
        return None
    try:
        return date.fromisoformat(valor[:10]).isoformat()
    except ValueError:
        raise ValueError(f"{campo}: fecha no válida.") from None


def _limpiar(datos: dict) -> dict:
    """Valida y normaliza los campos recibidos (solo los presentes). `ValueError` con un mensaje legible si algo no vale."""
    res: dict = {}
    if "nombre" in datos:
        nombre = _texto(datos["nombre"], 200)
        if not nombre:
            raise ValueError("Indica el nombre del trabajador.")
        res["nombre"] = nombre
    if "nif" in datos:
        res["nif"] = _texto(datos["nif"], 30)
        res["nif_normalizado"] = fiscal_identidad.normalizar(res["nif"]) or None
    if "naf" in datos:
        naf = "".join(c for c in (datos["naf"] or "") if c not in " /-.")
        if naf and (not naf.isdigit() or not 8 <= len(naf) <= 15):
            raise ValueError("El número de afiliación solo lleva dígitos (normalmente 12).")
        res["naf"] = naf or None
    if "puesto" in datos:
        res["puesto"] = _texto(datos["puesto"], 120)
    if "tipo_contrato" in datos:
        tipo = (datos["tipo_contrato"] or "").strip()
        if tipo and tipo not in _CLAVES_CONTRATO:
            raise ValueError("Tipo de contrato no válido.")
        res["tipo_contrato"] = tipo or None
    if "jornada_horas_semana" in datos:
        bruto = str(datos["jornada_horas_semana"] if datos["jornada_horas_semana"] is not None else "").strip().replace(",", ".")
        try:
            horas = float(bruto) if bruto else None
        except ValueError:
            raise ValueError("La jornada son horas a la semana (por ejemplo 40).") from None
        if horas is not None and not 0 < horas <= 60:
            raise ValueError("La jornada debe estar entre 0 y 60 horas a la semana.")
        res["jornada_horas_semana"] = horas
    for campo, etiqueta in (("fecha_alta", "Fecha de alta"), ("fecha_baja", "Fecha de baja")):
        if campo in datos:
            res[campo] = _fecha(datos[campo], etiqueta)
    if "notas" in datos:
        res["notas"] = (datos["notas"] or "").strip()[:2000] or None
    return res


def _comprobar_fechas(alta: str | None, baja: str | None) -> None:
    if alta and baja and baja < alta:
        raise ValueError("La baja no puede ser anterior al alta.")


def _cliente_vivo(conn, tenant_id: int, cliente_fiscal_id: int) -> None:
    if conn.execute("SELECT 1 FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (cliente_fiscal_id, tenant_id)).fetchone() is None:
        raise ValueError("Cliente no encontrado.")


def crear(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, nombre: str, **datos) -> int:
    """Da de alta un trabajador del cliente. Un mismo NIF no puede estar dos veces entre los trabajadores vivos de un cliente."""
    campos = _limpiar({"nombre": nombre, **{k: v for k, v in datos.items() if k in CAMPOS}})
    _comprobar_fechas(campos.get("fecha_alta"), campos.get("fecha_baja"))
    campos = {c: campos.get(c) for c in (*CAMPOS, "nif_normalizado")}
    conn = db.get_connection()
    try:
        _cliente_vivo(conn, tenant_id, cliente_fiscal_id)
        try:
            cur = conn.execute(
                f"INSERT INTO trabajadores_cliente (tenant_id, cliente_fiscal_id, {', '.join(campos)}, creado_por, creado_en) VALUES (?, ?, {', '.join('?' * len(campos))}, ?, ?)",
                (tenant_id, cliente_fiscal_id, *campos.values(), usuario_id, db.now_iso()))
        except sqlite3.IntegrityError:
            raise ValueError("Ya hay un trabajador con ese NIF en este cliente.") from None
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def obtener(tenant_id: int, trabajador_id: int):
    conn = db.get_connection()
    try:
        return conn.execute("SELECT * FROM trabajadores_cliente WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (trabajador_id, tenant_id)).fetchone()
    finally:
        conn.close()


def editar(tenant_id: int, trabajador_id: int, **datos) -> None:
    actual = obtener(tenant_id, trabajador_id)
    if actual is None:
        raise ValueError("Trabajador no encontrado.")
    campos = _limpiar({k: v for k, v in datos.items() if k in CAMPOS})
    _comprobar_fechas(campos.get("fecha_alta", actual["fecha_alta"]), campos.get("fecha_baja", actual["fecha_baja"]))
    if not campos:
        return
    conn = db.get_connection()
    try:
        try:
            conn.execute(f"UPDATE trabajadores_cliente SET {', '.join(f'{c} = ?' for c in campos)}, actualizado_en = ? WHERE id = ? AND tenant_id = ?",
                         (*campos.values(), db.now_iso(), trabajador_id, tenant_id))
        except sqlite3.IntegrityError:
            raise ValueError("Ya hay un trabajador con ese NIF en este cliente.") from None
        conn.commit()
    finally:
        conn.close()


def eliminar(tenant_id: int, trabajador_id: int) -> bool:
    """Lo manda a la papelera (se vacía con el resto, ver app/rgpd.py)."""
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE trabajadores_cliente SET papelera_en = ? WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (db._marca_papelera(), trabajador_id, tenant_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def listar(tenant_id: int, cliente_fiscal_id: int, hoy: str | None = None) -> list[dict]:
    """Los trabajadores vivos del cliente: primero los que están de alta hoy (sin baja o con baja futura), después los que ya causaron baja; cada uno con `de_baja`."""
    hoy = hoy or date.today().isoformat()
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT * FROM trabajadores_cliente WHERE tenant_id = ? AND cliente_fiscal_id = ? AND papelera_en IS NULL", (tenant_id, cliente_fiscal_id)).fetchall()
    finally:
        conn.close()
    res = [{**dict(f), "de_baja": bool(f["fecha_baja"] and f["fecha_baja"] < hoy)} for f in filas]
    res.sort(key=lambda t: (t["de_baja"], t["nombre"].lower(), t["id"]))
    return res
