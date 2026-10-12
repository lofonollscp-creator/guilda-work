"""Envío de un documento de un expediente a firmar con Documenso (Gabinete de abogados e Inmobiliaria). Es una acción externa: quien la llama ya ha pedido confirmación
en pantalla. Usa el token de Documenso del despacho (el mismo que las firmas del asistente)."""
from __future__ import annotations

from . import almacen_documentos, db, documenso, nucleo


def enviar(tenant_id: int, usuario_id: int, documento_id: int, email: str, nombre: str, comprobar_expediente) -> str:
    """Devuelve el id del documento en Documenso. `comprobar_expediente(expediente_id)` lanza ValueError si el expediente no es del módulo o la persona no puede verlo."""
    d = almacen_documentos.leer(tenant_id, usuario_id, documento_id)
    if d is None or d["expediente_id"] is None:
        raise ValueError("Documento no encontrado.")
    comprobar_expediente(d["expediente_id"])
    email = (email or "").strip()
    if "@" not in email or len(email) > 200:
        raise ValueError("Indica el email de quien firma.")
    tenant = db.obtener_tenant(tenant_id)
    clave = (tenant["documenso_api_key"] if tenant else None) or ""
    try:
        doc = documenso.crear_documento(clave, d["nombre_archivo"], d["contenido"], [{"email": email, "nombre": (nombre or "").strip()[:100]}])
        ident = str(doc.get("id") or doc.get("envelopeId") or "")
        documenso.enviar_a_firma(clave, ident)
    except documenso.ErrorDocumenso as e:
        raise ValueError(str(e)) from e
    conn = db.get_connection()
    try:
        nucleo._evento(conn, d["expediente_id"], "firma", f"Enviado a firma: {d['nombre_archivo']} → {email}.", usuario_id)
        conn.commit()
    finally:
        conn.close()
    return ident
