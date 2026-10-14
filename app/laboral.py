"""Gestión laboral de los clientes (primera rebanada): los trabajadores de cada cliente de la gestoría.

Solo guarda lo mínimo para llevar su gestión: identificación (nombre, NIF/NIE, número de afiliación), puesto, tipo de contrato, jornada y fechas de alta y baja. **No guarda
salarios ni calcula nóminas** y **no genera obligaciones ni fechas laborales** (TC, 111/190, altas y bajas): esas reglas las valida el propietario antes de entrar en el catálogo
fiscal (ver app/vencimientos_fiscales.py), así que aquí solo hay datos, no calendario.

**Solo el nombre es obligatorio**: el resto de datos son opcionales y ninguno impide guardar por su formato o su rango (un nº de afiliación con letras, una jornada de 70 horas, una baja
anterior al alta o un NIF repetido se guardan y la pantalla lo señala con un aviso suave). Únicamente fallan los textos que no se pueden interpretar (una fecha o un número ilegibles),
porque guardarlos corrompería el dato.

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
CAMPOS = ("nombre", "nif", "naf", "puesto", "categoria", "convenio", "tipo_contrato", "jornada_horas_semana", "fecha_alta", "fecha_baja", "notas")

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
    categoria TEXT,
    convenio TEXT,
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
DROP INDEX IF EXISTS ux_trabajadores_cliente_nif;
"""


def crear_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(ESQUEMA)
    for columna in ("categoria", "convenio"):          # bases creadas antes de existir estas columnas
        db._asegurar_columna(conn, "trabajadores_cliente", columna, "TEXT")


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
        res["naf"] = _texto(datos["naf"], 30)
    if "puesto" in datos:
        res["puesto"] = _texto(datos["puesto"], 120)
    if "categoria" in datos:
        res["categoria"] = _texto(datos["categoria"], 120)
    if "convenio" in datos:
        res["convenio"] = _texto(datos["convenio"], 200)
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
        if horas is not None and not 0 <= horas < float("inf"):
            raise ValueError("La jornada son horas a la semana (por ejemplo 40).")
        res["jornada_horas_semana"] = horas
    for campo, etiqueta in (("fecha_alta", "Fecha de alta"), ("fecha_baja", "Fecha de baja")):
        if campo in datos:
            res[campo] = _fecha(datos[campo], etiqueta)
    if "notas" in datos:
        res["notas"] = (datos["notas"] or "").strip()[:2000] or None
    return res


def _cliente_vivo(conn, tenant_id: int, cliente_fiscal_id: int) -> None:
    if conn.execute("SELECT 1 FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (cliente_fiscal_id, tenant_id)).fetchone() is None:
        raise ValueError("Cliente no encontrado.")


def crear(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, nombre: str, **datos) -> int:
    """Da de alta un trabajador del cliente. Un mismo NIF no puede estar dos veces entre los trabajadores vivos de un cliente."""
    campos = _limpiar({"nombre": nombre, **{k: v for k, v in datos.items() if k in CAMPOS}})
    campos = {c: campos.get(c) for c in (*CAMPOS, "nif_normalizado")}
    conn = db.get_connection()
    try:
        _cliente_vivo(conn, tenant_id, cliente_fiscal_id)
        cur = conn.execute(
            f"INSERT INTO trabajadores_cliente (tenant_id, cliente_fiscal_id, {', '.join(campos)}, creado_por, creado_en) VALUES (?, ?, {', '.join('?' * len(campos))}, ?, ?)",
            (tenant_id, cliente_fiscal_id, *campos.values(), usuario_id, db.now_iso()))
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
    if not campos:
        return
    conn = db.get_connection()
    try:
        conn.execute(f"UPDATE trabajadores_cliente SET {', '.join(f'{c} = ?' for c in campos)}, actualizado_en = ? WHERE id = ? AND tenant_id = ?",
                     (*campos.values(), db.now_iso(), trabajador_id, tenant_id))
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
    """Los trabajadores vivos del cliente: primero los que están de alta hoy (sin baja o con baja futura), después los que ya causaron baja. Cada uno lleva `de_baja` y los avisos suaves
    `nif_repetido` y `baja_antes_del_alta` (no impiden guardar nada)."""
    hoy = hoy or date.today().isoformat()
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT * FROM trabajadores_cliente WHERE tenant_id = ? AND cliente_fiscal_id = ? AND papelera_en IS NULL", (tenant_id, cliente_fiscal_id)).fetchall()
    finally:
        conn.close()
    repetidos: dict[str, int] = {}
    for f in filas:
        if f["nif_normalizado"]:
            repetidos[f["nif_normalizado"]] = repetidos.get(f["nif_normalizado"], 0) + 1
    res = [{**dict(f), "de_baja": bool(f["fecha_baja"] and f["fecha_baja"] < hoy),
            "nif_repetido": bool(f["nif_normalizado"] and repetidos[f["nif_normalizado"]] > 1),
            "baja_antes_del_alta": bool(f["fecha_alta"] and f["fecha_baja"] and f["fecha_baja"] < f["fecha_alta"])} for f in filas]
    res.sort(key=lambda t: (t["de_baja"], t["nombre"].lower(), t["id"]))
    return res
