"""Contexto de un correo con el resto de Guilda Work: de qué cliente es, qué vencimientos y tareas tiene abiertos, qué documentos se han archivado de este mensaje y, si no está
vinculado, qué clientes podrían ser. Es la mitad «correo → resto» de la conexión recíproca (la otra mitad son los botones «Escribir» de la ficha del cliente y de sus vencimientos).

Solo se enseña lo que la persona puede ver (oficinas, app/acceso.py); sin despacho no hay contexto."""
from __future__ import annotations

from . import acceso, db

ESTADOS_ABIERTOS = ("pendiente", "fuera_plazo")
LIMITE = 5


def _documentos_del_mensaje(tenant_id: int, mensaje_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT id, nombre_archivo, cliente_id FROM documentos WHERE tenant_id = ? AND mensaje_correo_id = ? AND papelera_en IS NULL ORDER BY id LIMIT ?",
                             (tenant_id, mensaje_id, LIMITE)).fetchall()
    finally:
        conn.close()
    return [dict(f) for f in filas]


def _clientes_candidatos(tenant_id: int, usuario_id: int, direccion: str) -> list[dict]:
    """Clientes del núcleo (visibles) cuyo email, o el de alguno de sus contactos, es `direccion`."""
    if not direccion:
        return []
    extra, pe = acceso.restriccion_nucleo(tenant_id, "c.id")
    conn = db.get_connection()
    try:
        filas = conn.execute(
            f"""SELECT DISTINCT c.id, c.nombre FROM clientes c LEFT JOIN cliente_contactos k ON k.cliente_id = c.id
                WHERE c.tenant_id = ? AND c.papelera_en IS NULL AND (LOWER(TRIM(c.email)) = ? OR LOWER(TRIM(k.email)) = ?){extra} ORDER BY c.nombre LIMIT ?""",
            (tenant_id, direccion, direccion, *pe, LIMITE)).fetchall()
    finally:
        conn.close()
    return [dict(f) for f in filas]


def contexto_de_mensaje(usuario_id: int, tenant_id: int | None, mensaje, direccion_remitente: str | None, hoy: str | None = None) -> dict | None:
    """El panel de contexto del mensaje, o None si la persona no tiene despacho."""
    if tenant_id is None:
        return None
    ctx: dict = {"cliente": None, "vencimientos": [], "tareas": [], "documentos": _documentos_del_mensaje(tenant_id, mensaje["id"]), "candidatos": []}
    cliente_id = mensaje["cliente_fiscal_id"]
    if cliente_id and acceso.puede_ver_cliente(tenant_id, usuario_id, cliente_id):
        fiscal = db.obtener_cliente_fiscal(tenant_id, cliente_id)
        if fiscal is not None:
            ctx["cliente"] = {"id": fiscal["id"], "nucleo_id": fiscal["cliente_id"], "nombre": fiscal["nombre"], "email": fiscal["email"]}
            ctx["vencimientos"] = [dict(v) for v in db.listar_vencimientos_fiscales(tenant_id, cliente_fiscal_id=cliente_id) if v["estado"] in ESTADOS_ABIERTOS][:LIMITE]
            tareas = [t for t in db.listar_tareas_outlook(usuario_id, incluir_asignadas=True, cliente_fiscal_id=cliente_id) if t["estado"] != "completada"]
            ctx["tareas"] = [dict(t) for t in sorted(tareas, key=lambda t: (t["fecha_vencimiento"] or "9999", t["id"]))][:LIMITE]
    elif direccion_remitente:
        ctx["candidatos"] = _clientes_candidatos(tenant_id, usuario_id, direccion_remitente.lower())
    return ctx
