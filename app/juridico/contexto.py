"""Contexto del cliente para una consulta jurídica (J4): los datos del cliente que ayudan a decidir qué norma le aplica (tipo de cliente y, si hay ficha fiscal con el mismo NIF, su forma jurídica,
territorio y régimen de IVA), junto con su nombre y NIF.

Lo que se envía lo ve la persona antes de consultar (`texto`) y es exactamente lo que recibe el modelo. Va como «hechos aportados por el despacho»: no se cita como fuente jurídica. Como
cualquier texto que sale hacia el proveedor de IA, pasa antes por la seudonimización de `app/anonimizar.py` (nombres, NIF y demás datos personales sustituidos por etiquetas), salvo que el servidor la
tenga desactivada (solo desarrollo): en ese caso la pantalla lo dice."""
from __future__ import annotations

import json
from datetime import date

from .. import acceso, anonimizar, db

FORMAS = {"persona_fisica": "persona física", "sociedad": "sociedad", "comunidad_bienes": "comunidad de bienes", "otra": "otra forma jurídica"}
TERRITORIOS = {"peninsula_baleares": "Península y Baleares", "canarias": "Canarias", "ceuta_melilla": "Ceuta y Melilla"}
REGIMENES = {"general": "general", "simplificado": "simplificado", "general_y_simplificado": "general y simplificado", "recargo": "recargo de equivalencia", "exento": "exento", "otro": "otro"}


def datos_cliente(tenant_id: int, usuario_id: int, cliente_id: int | None, hoy: date | None = None) -> dict | None:
    """Los datos que se pueden enviar de ese cliente, o None si no existe o la persona no lo ve."""
    if not cliente_id or not acceso.puede_ver_cliente_nucleo(tenant_id, usuario_id, cliente_id):
        return None
    conn = db.get_connection()
    try:
        c = conn.execute("SELECT id, tipo, nombre, nif FROM clientes WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (cliente_id, tenant_id)).fetchone()
        if c is None:
            return None
        d: dict = {"tipo": c["tipo"], "nombre": c["nombre"], "nif": c["nif"], "perfil": None}
        if c["nif"]:
            fiscal = conn.execute("SELECT id FROM clientes_fiscales WHERE tenant_id = ? AND nif = ? AND papelera_en IS NULL ORDER BY id LIMIT 1", (tenant_id, c["nif"])).fetchone()
            if fiscal:
                dia = (hoy or date.today()).isoformat()
                p = conn.execute("SELECT * FROM fiscal_perfiles WHERE tenant_id = ? AND cliente_fiscal_id = ? AND vigente_desde <= ? AND COALESCE(vigente_hasta, '9999-12-31') >= ?",
                                 (tenant_id, fiscal["id"], dia, dia)).fetchone()
                if p:
                    actividades = []
                    try:
                        actividades = [str(a.get("descripcion") or a.get("epigrafe") or a.get("cnae") or "").strip() for a in (json.loads(p["actividades"]) if p["actividades"] else []) if isinstance(a, dict)]
                    except ValueError:
                        pass
                    d["perfil"] = {"forma": FORMAS.get(p["forma_juridica"], p["forma_juridica"]), "residencia": p["residencia"], "territorio": TERRITORIOS.get(p["territorio_iva"], p["territorio_iva"]),
                                   "regimen_iva": REGIMENES.get(p["regimen_iva"], p["regimen_iva"]), "periodicidad": p["periodicidad"], "criterio_caja": bool(p["criterio_caja"]),
                                   "foral": bool(p["tributacion_foral"]), "actividades": [a for a in actividades if a][:5]}
        return d
    finally:
        conn.close()


def texto(d: dict | None) -> str:
    """El bloque tal como lo recibe el modelo (y como se enseña antes de enviar)."""
    if not d:
        return ""
    lineas = [f"- Cliente: {d['nombre']}" + (f" (NIF {d['nif']})" if d.get("nif") else ""), f"- Tipo de cliente: {'empresa' if d['tipo'] == 'empresa' else 'persona'}"]
    p = d.get("perfil")
    if p:
        lineas += [f"- Forma jurídica: {p['forma']}", f"- Residencia: {p['residencia']} · territorio de IVA: {p['territorio']}",
                   f"- Régimen de IVA: {p['regimen_iva']} ({p['periodicidad']})" + (" · criterio de caja" if p["criterio_caja"] else ""), ]
        if p["foral"]:
            lineas.append("- Tributación foral: sí")
        if p["actividades"]:
            lineas.append("- Actividades: " + "; ".join(p["actividades"]))
    return "\n".join(lineas)


def protegido() -> bool:
    """¿Los datos personales se sustituyen por etiquetas antes de salir hacia el proveedor de IA?"""
    return anonimizar.activada()
