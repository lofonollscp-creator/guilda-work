"""Firma de documentos desde el portal: el despacho envía un PDF a firmar desde un vencimiento (Documenso) y el cliente lo ve en «Para hacer» con el botón que lo lleva directo a la página de firma, sin buscar el correo.

La firma ocurre en Documenso (aquí no se firma nada ni se guarda ninguna clave). Para saber si ya firmó se pregunta a Documenso: el webhook lo anota (`vencimientos_fiscales.documenso_firmado_en`) y, si no llegó, se comprueba
al abrir la página de firma, que así se corrige sola."""
from __future__ import annotations

from . import db, documenso

ABIERTOS = ("DRAFT", "PENDING")


def pendientes(vencimientos) -> list:
    """Los vencimientos con un documento enviado a firma y sin constancia de que se haya firmado."""
    return [v for v in vencimientos if v["documenso_documento_id"] and not v["documenso_firmado_en"]]


def _clave(tenant_id: int) -> str | None:
    t = db.obtener_tenant(tenant_id)
    return t["documenso_api_key"] if t else None


def marcar_firmado(tenant_id: int, vencimiento_id: int) -> None:
    db.editar_vencimiento_fiscal(tenant_id, vencimiento_id, documenso_firmado_en=db.now_iso())


def consultar(cliente: dict, vencimiento) -> dict:
    """`{estado, enlace}`: `firmado`, `por_firmar` (con el enlace a su página de firma), `rechazado` o `no_disponible` (Documenso no responde o no hay clave)."""
    clave = _clave(cliente["tenant_id"])
    if not clave or not vencimiento["documenso_documento_id"]:
        return {"estado": "no_disponible", "enlace": None}
    try:
        documento = documenso.obtener_documento(clave, vencimiento["documenso_documento_id"])
    except documenso.ErrorDocumenso:
        return {"estado": "no_disponible", "enlace": None}
    estado = str(documento.get("status") or "").upper()
    if estado == "COMPLETED":
        marcar_firmado(cliente["tenant_id"], vencimiento["id"])
        return {"estado": "firmado", "enlace": None}
    if estado == "REJECTED":
        return {"estado": "rechazado", "enlace": None}
    if estado in ABIERTOS:
        enlace = documenso.enlace_de_firma(documento, cliente["email"] or "")
        if enlace is None and any(r.get("signingStatus") == "SIGNED" and str(r.get("email") or "").lower() == (cliente["email"] or "").lower() for r in documento.get("recipients", [])):
            return {"estado": "firmado", "enlace": None}                    # tú ya firmaste: queda esperar a los demás
        return {"estado": "por_firmar", "enlace": enlace}
    return {"estado": "no_disponible", "enlace": None}


def marcar_por_documenso(documenso_id: str) -> int:
    """Lo llama el webhook: para los vencimientos con ese documento, pregunta a Documenso y anota los que ya están firmados del todo. Devuelve cuántos."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT id, tenant_id FROM vencimientos_fiscales WHERE documenso_documento_id = ? AND documenso_firmado_en IS NULL", (str(documenso_id),)).fetchall()
    finally:
        conn.close()
    n = 0
    for f in filas:
        clave = _clave(f["tenant_id"])
        try:
            if clave and str(documenso.estado_documento(clave, str(documenso_id))).upper() == "COMPLETED":
                marcar_firmado(f["tenant_id"], f["id"])
                n += 1
        except documenso.ErrorDocumenso:
            continue
    return n
