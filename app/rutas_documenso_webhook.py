"""Webhook entrante de Documenso: avisa de que un documento se ha firmado o rechazado (ver app/documentos_firma.py).

Sin `@login_required`: un webhook no trae sesión. La autenticidad es el secreto compartido que se configura en Documenso (la cabecera `X-Documenso-Secret` lleva ese texto tal cual, no una
firma) y que aquí está en `DOCUMENSO_WEBHOOK_SECRET`; sin él configurado el endpoint no acepta nada. El contenido del aviso NO se da por bueno: solo se usa para saber de qué documento se
trata, y el estado se pregunta a la API de Documenso. Por eso da igual cómo se llamen los eventos (`DOCUMENT_COMPLETED`, `document.completed`…)."""
import hmac
import os

from flask import Blueprint, Response, request

from . import documentos_firma

documenso_webhook_bp = Blueprint("documenso_webhook", __name__, url_prefix="/webhooks")


def _ids_del_aviso(cuerpo) -> list[str]:
    """Los identificadores que puede traer el aviso para el documento, venga como venga."""
    if not isinstance(cuerpo, dict):
        return []
    carga = cuerpo.get("payload") if isinstance(cuerpo.get("payload"), dict) else cuerpo
    return [str(carga[k]) for k in ("id", "envelopeId", "documentId") if carga.get(k) not in (None, "")]


@documenso_webhook_bp.route("/documenso", methods=["POST"])
def recibir():
    secreto = os.environ.get("DOCUMENSO_WEBHOOK_SECRET", "")
    if not secreto:
        return Response(status=503)
    if not hmac.compare_digest(request.headers.get("X-Documenso-Secret", "").encode(), secreto.encode()):
        return Response(status=401)
    for ident in _ids_del_aviso(request.get_json(silent=True)):
        documentos_firma.refrescar_por_documenso(ident)
    return Response("ok", status=200)
