"""API de documentos del despacho (clientes y expedientes del núcleo), área `documentos`. Solo lectura: listar y descargar. Respeta el despacho y la visibilidad de los
expedientes confidenciales igual que la web. Si el despacho tiene el cifrado activado, la descarga solo funciona con el despacho desbloqueado o con un token que
tenga concesión (ver app/cifrado_despacho.py); si no, responde 423 `despacho_bloqueado` (nunca un contenido vacío)."""
from __future__ import annotations

from flask import g, request

from . import almacen_documentos, cifrado_despacho
from .auth import token_required
from .rutas_api import _err, _exigir_tenant_api, _ok, api_bp
from .rutas_api_fiscal import _descarga


@api_bp.route("/documentos", methods=["GET"])
@token_required
def listar_documentos():
    """Metadatos (sin contenido) de los documentos de un cliente (`cliente_id`) o de un expediente (`expediente_id`). `contenido_disponible` dice si se puede descargar ahora."""
    error = _exigir_tenant_api()
    if error:
        return error
    cliente_id, expediente_id = request.args.get("cliente_id", type=int), request.args.get("expediente_id", type=int)
    if cliente_id is None and expediente_id is None:
        return _err("Indica cliente_id o expediente_id.", 400, "peticion_invalida")
    e = cifrado_despacho.estado(g.tenant_id)
    disponible = not e["activo"] or e["desbloqueado"] or cifrado_despacho.tiene_concesion(g.tenant_id)
    docs = almacen_documentos.listar(g.tenant_id, g.usuario_id, cliente_id=cliente_id, expediente_id=expediente_id, limite=200)
    return _ok([{k: d.get(k) for k in ("id", "cliente_id", "expediente_id", "nombre_archivo", "tipo_mime", "tamano_bytes", "categoria", "origen", "creado_en", "cifrado")}
                | {"contenido_disponible": disponible or not d.get("cifrado")} for d in docs])


@api_bp.route("/documentos/<int:documento_id>/contenido", methods=["GET"])
@token_required
def descargar_documento(documento_id: int):
    """Descarga el contenido. 423 `despacho_bloqueado` si está cifrado y no hay clave disponible para este token."""
    error = _exigir_tenant_api()
    if error:
        return error
    d = almacen_documentos.leer(g.tenant_id, g.usuario_id, documento_id)         # DespachoBloqueado -> 423 (manejador global)
    if d is None:
        return _err("Documento no encontrado.", 404, "no_encontrado")
    return _descarga(d["contenido"], d["tipo_mime"], d["nombre_archivo"])
