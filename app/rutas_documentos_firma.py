"""Pantallas de los documentos que se firman con Documenso desde la ficha del cliente (ver app/documentos_firma.py): elegir el documento, revisar el borrador, enviarlo a firma,
seguir su estado y, la dirección, cambiar los textos de serie por los del despacho."""
from __future__ import annotations

from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for

from . import documentos_firma, nucleo
from .auth import login_required

documentos_firma_bp = Blueprint("documentos_firma", __name__, url_prefix="/documentos-firma")


def _tenant() -> int:
    if g.get("tenant_id") is None:
        abort(404)
    return g.tenant_id


def _cliente(cliente_id: int):
    c = nucleo.obtener_cliente(_tenant(), cliente_id)
    if c is None:
        abort(404)
    return c


def _supervisor() -> bool:
    return bool(g.get("supervisor_tenant") or g.get("es_admin"))


def _a_la_ficha(cliente_id: int, **consulta):
    return redirect(url_for("clientes.ficha", cliente_id=cliente_id, pestana="documentos", **consulta) + "#firmas")


@documentos_firma_bp.route("/clientes/<int:cliente_id>/nuevo/<clave>")
@login_required
def nuevo(cliente_id: int, clave: str):
    c = _cliente(cliente_id)
    if clave not in documentos_firma.PLANTILLAS:
        abort(404)
    return render_template("documento_firma_nuevo.html", c=c, f=documentos_firma.formulario(_tenant(), cliente_id, clave), error=(request.args.get("error") or "")[:300] or None,
                           valores={}, puede_enviar=documentos_firma.puede_enviar(_tenant()), subnav="clientes")


@documentos_firma_bp.route("/clientes/<int:cliente_id>/crear/<clave>", methods=["POST"])
@login_required
def crear(cliente_id: int, clave: str):
    c = _cliente(cliente_id)
    if clave not in documentos_firma.PLANTILLAS:
        abort(404)
    try:
        did = documentos_firma.crear_borrador(_tenant(), g.usuario_id, cliente_id, clave, request.form, lugar=request.form.get("lugar", ""),
                                              firmante_email=request.form.get("firmante_email", ""), firmante_nombre=request.form.get("firmante_nombre", ""))
    except documentos_firma.ErrorDocumento as e:
        return render_template("documento_firma_nuevo.html", c=c, f=documentos_firma.formulario(_tenant(), cliente_id, clave), error=str(e), valores=request.form,
                               puede_enviar=documentos_firma.puede_enviar(_tenant()), subnav="clientes"), 400
    return redirect(url_for("documentos_firma.ver", cliente_id=cliente_id, documento_id=did))


@documentos_firma_bp.route("/clientes/<int:cliente_id>/<int:documento_id>")
@login_required
def ver(cliente_id: int, documento_id: int):
    c = _cliente(cliente_id)
    d = documentos_firma.obtener(_tenant(), cliente_id, documento_id)
    if d is None:
        abort(404)
    return render_template("documento_firma_ver.html", c=c, d=d, error=(request.args.get("error") or "")[:300] or None, aviso=request.args.get("aviso"),
                           puede_enviar=documentos_firma.puede_enviar(_tenant()), max_recordatorios=documentos_firma.MAX_RECORDATORIOS, subnav="clientes")


@documentos_firma_bp.route("/clientes/<int:cliente_id>/<int:documento_id>/pdf")
@login_required
def pdf(cliente_id: int, documento_id: int):
    _cliente(cliente_id)
    try:
        titulo, contenido = documentos_firma.pdf_del_documento(_tenant(), cliente_id, documento_id)
    except documentos_firma.ErrorDocumento:
        abort(404)
    return Response(contenido, mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="documento-{documento_id}.pdf"', "Cache-Control": "private, no-store"})


def _accion(cliente_id: int, documento_id: int, hacer, aviso: str):
    _cliente(cliente_id)
    try:
        hacer(_tenant(), g.usuario_id, cliente_id, documento_id)
    except documentos_firma.ErrorDocumento as e:
        return redirect(url_for("documentos_firma.ver", cliente_id=cliente_id, documento_id=documento_id, error=str(e)[:300]))
    return redirect(url_for("documentos_firma.ver", cliente_id=cliente_id, documento_id=documento_id, aviso=aviso))


@documentos_firma_bp.route("/clientes/<int:cliente_id>/<int:documento_id>/enviar", methods=["POST"])
@login_required
def enviar(cliente_id: int, documento_id: int):
    return _accion(cliente_id, documento_id, documentos_firma.enviar, "enviado")


@documentos_firma_bp.route("/clientes/<int:cliente_id>/<int:documento_id>/cancelar", methods=["POST"])
@login_required
def cancelar(cliente_id: int, documento_id: int):
    return _accion(cliente_id, documento_id, documentos_firma.cancelar, "cancelado")


@documentos_firma_bp.route("/clientes/<int:cliente_id>/<int:documento_id>/actualizar", methods=["POST"])
@login_required
def actualizar(cliente_id: int, documento_id: int):
    return _accion(cliente_id, documento_id, documentos_firma.refrescar, "actualizado")


@documentos_firma_bp.route("/clientes/<int:cliente_id>/<int:documento_id>/recordar", methods=["POST"])
@login_required
def recordar(cliente_id: int, documento_id: int):
    return _accion(cliente_id, documento_id, documentos_firma.recordar, "recordado")


@documentos_firma_bp.route("/plantillas")
@login_required
def plantillas():
    return render_template("documentos_firma_plantillas.html", catalogo=documentos_firma.catalogo(_tenant()), puede_editar=_supervisor(), subnav="clientes",
                           recordatorio_dias=documentos_firma.recordatorio_dias(_tenant()), max_dias=documentos_firma.MAX_DIAS_RECORDATORIO, max_recordatorios=documentos_firma.MAX_RECORDATORIOS,
                           error=(request.args.get("error") or "")[:300] or None, aviso=request.args.get("aviso"))


@documentos_firma_bp.route("/plantillas/recordatorio", methods=["POST"])
@login_required
def recordatorio():
    try:
        documentos_firma.fijar_recordatorio_dias(_tenant(), g.usuario_id, request.form.get("dias"))
    except documentos_firma.ErrorDocumento as e:
        return redirect(url_for("documentos_firma.plantillas", error=str(e)))
    return redirect(url_for("documentos_firma.plantillas", aviso="guardado"))


@documentos_firma_bp.route("/plantillas/<clave>", methods=["GET", "POST"])
@login_required
def plantilla(clave: str):
    if clave not in documentos_firma.PLANTILLAS:
        abort(404)
    t, error, aviso = _tenant(), None, None
    texto, propio = documentos_firma.texto_de(t, clave)
    if request.method == "POST":
        try:
            if request.form.get("accion") == "restaurar":
                documentos_firma.restaurar_texto(t, g.usuario_id, clave)
                aviso = "restaurado"
            else:
                documentos_firma.guardar_texto(t, g.usuario_id, clave, request.form.get("texto", ""))
                aviso = "guardado"
            texto, propio = documentos_firma.texto_de(t, clave)
        except documentos_firma.ErrorDocumento as e:
            error, texto = str(e), request.form.get("texto", texto)
    return render_template("documento_firma_plantilla.html", clave=clave, p=documentos_firma.PLANTILLAS[clave], texto=texto, propio=propio, variables=documentos_firma.variables_de(clave),
                           puede_editar=_supervisor(), error=error, aviso=aviso, subnav="clientes")
