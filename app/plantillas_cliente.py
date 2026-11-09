"""Plantillas de cliente: el punto de partida de un alta según el tipo de cliente (autónomo, sociedad, particular…).

Una plantilla guarda lo que se repite al dar de alta a un cliente de la gestoría: el perfil fiscal (de él salen los modelos propuestos, ver app/perfil_fiscal.py),
si se generan solos sus vencimientos, las etiquetas y, opcionalmente, una plantilla de tareas que se aplica al darlo de alta (app/db_tareas.py).

Hay tres **de serie** (definidas en código, comunes a todos los despachos y sin tocar la base de datos) y las que cada despacho crea (`plantillas_cliente`). Las de serie son
un punto de partida **sin validar**: el perfil que traen es una sugerencia habitual, no una regla fiscal, y los modelos que de él salen se siguen mostrando como propuesta
editable en la ficha del cliente. Los identificadores son texto: `serie:<tipo>` para las de serie y el id numérico para las del despacho."""
from __future__ import annotations

import json
import sqlite3

from flask_babel import lazy_gettext as _l

from .bd.errores import ErrorIntegridad
from . import db, perfil_fiscal

ESQUEMA = """
CREATE TABLE IF NOT EXISTS plantillas_cliente (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    perfil_tipo TEXT,
    perfil_atributos TEXT NOT NULL DEFAULT '[]',
    generacion_automatica INTEGER NOT NULL DEFAULT 0,
    plantilla_tareas_id INTEGER,
    etiquetas TEXT,
    peticiones TEXT NOT NULL DEFAULT '[]',
    invitar_portal INTEGER NOT NULL DEFAULT 0,
    creado_por INTEGER,
    creado_en TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_plantillas_cliente_nombre ON plantillas_cliente(tenant_id, lower(nombre));
"""

# Lo que se suele pedir a un cliente nuevo según su tipo: al darlo de alta con una plantilla, se le abre una petición de documentos por cada línea (texto en español, el del equipo).
PETICIONES_DE_SERIE = {
    "autonomo": ["DNI o NIE (por las dos caras)", "Certificado digital o autorización para presentar en tu nombre", "Declaración de la Renta del último año", "Alta en el censo (modelo 036 o 037) y en el RETA"],
    "sociedad": ["Escritura de constitución y estatutos", "NIF de la sociedad (tarjeta del CIF)", "DNI del administrador o de los socios", "Certificado digital de la sociedad o autorización", "Cuentas anuales y Impuesto de Sociedades del último año"],
    "particular": ["DNI o NIE (por las dos caras)", "Declaración de la Renta del último año", "Certificado digital o Cl@ve"],
}
MAX_PETICIONES = 15


def peticiones_limpias(valor) -> list[str]:
    """Una lista de títulos de petición: texto (una por línea) o lista; sin vacíos ni repetidas, de hasta 120 caracteres."""
    lineas = valor.splitlines() if isinstance(valor, str) else list(valor or [])
    return list(dict.fromkeys(" ".join(str(l).split())[:120] for l in lineas if str(l).strip()))[:MAX_PETICIONES]


DE_SERIE = (
    {"id": "serie:autonomo", "nombre": _l("Autónomo"), "perfil_tipo": "autonomo", "perfil_atributos": ["iva", "estimacion_directa"]},
    {"id": "serie:sociedad", "nombre": _l("Sociedad"), "perfil_tipo": "sociedad", "perfil_atributos": ["iva"]},
    {"id": "serie:particular", "nombre": _l("Particular"), "perfil_tipo": "particular", "perfil_atributos": []},
)


def crear_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(ESQUEMA)
    db._asegurar_columna(conn, "plantillas_cliente", "peticiones", "TEXT NOT NULL DEFAULT '[]'")
    db._asegurar_columna(conn, "plantillas_cliente", "invitar_portal", "INTEGER NOT NULL DEFAULT 0")


def _serie(p: dict) -> dict:
    return {**p, "de_serie": True, "generacion_automatica": False, "plantilla_tareas_id": None, "etiquetas": [], "peticiones": list(PETICIONES_DE_SERIE.get(p["perfil_tipo"], [])), "invitar_portal": False}


def _fila(f) -> dict:
    return {
        "id": str(f["id"]), "nombre": f["nombre"], "perfil_tipo": f["perfil_tipo"] or None, "perfil_atributos": json.loads(f["perfil_atributos"] or "[]"),
        "generacion_automatica": bool(f["generacion_automatica"]), "plantilla_tareas_id": f["plantilla_tareas_id"],
        "etiquetas": [e for e in (f["etiquetas"] or "").split(",") if e], "de_serie": False,
        "peticiones": json.loads(f["peticiones"] or "[]") if "peticiones" in f.keys() else [], "invitar_portal": bool(f["invitar_portal"]) if "invitar_portal" in f.keys() else False,
    }


def listar(tenant_id: int) -> list[dict]:
    """Primero las de serie y después las del despacho, por nombre."""
    conn = db.get_connection()
    try:
        propias = [_fila(f) for f in conn.execute("SELECT * FROM plantillas_cliente WHERE tenant_id = ? ORDER BY lower(nombre)", (tenant_id,))]
    finally:
        conn.close()
    return [_serie(p) for p in DE_SERIE] + propias


def obtener(tenant_id: int, plantilla_id: str | int | None) -> dict | None:
    """La plantilla (de serie o del despacho) o None si no existe o es de otro despacho."""
    if plantilla_id in (None, ""):
        return None
    plantilla_id = str(plantilla_id)
    if plantilla_id.startswith("serie:"):
        return next((_serie(p) for p in DE_SERIE if p["id"] == plantilla_id), None)
    if not plantilla_id.isdigit():
        return None
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM plantillas_cliente WHERE id = ? AND tenant_id = ?", (int(plantilla_id), tenant_id)).fetchone()
    finally:
        conn.close()
    return _fila(f) if f else None


def _etiquetas_limpias(etiquetas) -> list[str]:
    if isinstance(etiquetas, str):
        etiquetas = etiquetas.split(",")
    vistas: list[str] = []
    for e in etiquetas or []:
        e = (e or "").strip().lower()[:40]
        if e and "," not in e and e not in vistas:
            vistas.append(e)
    return vistas[:20]


def crear(tenant_id: int, usuario_id: int, nombre: str, *, perfil_tipo: str | None = None, perfil_atributos=(), generacion_automatica: bool = False,
          plantilla_tareas_id: int | None = None, etiquetas=(), peticiones=(), invitar_portal: bool = False) -> str:
    """Crea una plantilla del despacho y devuelve su id (texto). `ValueError` con un mensaje legible si algo no vale."""
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("Indica el nombre de la plantilla.")
    if len(nombre) > 80:
        raise ValueError("El nombre es demasiado largo (máx. 80 caracteres).")
    if perfil_tipo and perfil_tipo not in perfil_fiscal.TIPOS:
        raise ValueError("Tipo de cliente no válido.")
    atributos = perfil_fiscal.perfil_limpio(perfil_tipo, perfil_atributos)["atributos"] if (perfil_tipo or list(perfil_atributos)) else []
    if plantilla_tareas_id is not None:
        tp = db.obtener_plantilla_tareas(usuario_id, plantilla_tareas_id)
        if tp is None:
            raise ValueError("La plantilla de tareas no existe.")
        if not tp["compartida"]:
            raise ValueError("La plantilla de tareas debe estar compartida con el despacho para que la apliquen todas las personas.")
    conn = db.get_connection()
    try:
        try:
            cur = conn.execute(
                "INSERT INTO plantillas_cliente (tenant_id, nombre, perfil_tipo, perfil_atributos, generacion_automatica, plantilla_tareas_id, etiquetas, peticiones, invitar_portal, creado_por, creado_en) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (tenant_id, nombre, perfil_tipo or None, json.dumps(atributos), 1 if generacion_automatica else 0, plantilla_tareas_id,
                 ",".join(_etiquetas_limpias(etiquetas)) or None, json.dumps(peticiones_limpias(peticiones), ensure_ascii=False), 1 if invitar_portal else 0, usuario_id, db.now_iso()))
        except ErrorIntegridad:
            raise ValueError("Ya hay una plantilla con ese nombre.") from None
        conn.commit()
        return str(cur.lastrowid)
    finally:
        conn.close()


def eliminar(tenant_id: int, plantilla_id: str | int) -> bool:
    """Borra una plantilla del despacho (las de serie no se borran). No afecta a los clientes ya creados con ella."""
    if not str(plantilla_id).isdigit():
        return False
    conn = db.get_connection()
    try:
        cur = conn.execute("DELETE FROM plantillas_cliente WHERE id = ? AND tenant_id = ?", (int(plantilla_id), tenant_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
