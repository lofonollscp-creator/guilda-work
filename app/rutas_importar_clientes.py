"""Pantallas para importar clientes desde un Excel o un CSV (ver app/importador_clientes.py). Solo la dirección y la coordinación del despacho: una importación crea muchas fichas de golpe."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for
from flask_babel import gettext as _

from . import alta_cliente, importador_clientes as imp
from .auth import limiter, login_required
from .rutas_nucleo import _supervisor, _tenant

importar_clientes_bp = Blueprint("importar_clientes", __name__, url_prefix="/clientes/importar")


def _permitido() -> int:
    t = _tenant()
    if not _supervisor():
        abort(403)
    return t


def _correspondencia(cabeceras: list[str], origen) -> dict[int, str]:
    """La que eligió la persona (`c0`, `c1`… = campo de cada columna; vacío = no importar) o, si no ha elegido, la reconocida por las cabeceras."""
    if any(k.startswith("c") and k[1:].isdigit() for k in origen):
        res = {}
        for i in range(len(cabeceras)):
            campo = origen.get(f"c{i}", "")
            if campo in imp.CAMPOS and campo not in res.values():
                res[i] = campo
        return res
    return imp.reconocer_columnas(cabeceras)


@importar_clientes_bp.route("/", methods=["GET"])
@login_required
def inicio():
    _permitido()
    return render_template("clientes_importar.html", error=(request.args.get("error") or "")[:300] or None, subnav="clientes", campos=imp.ETIQUETAS_CAMPO, max_filas=imp.MAX_FILAS)


@importar_clientes_bp.route("/", methods=["POST"])
@login_required
@limiter.limit("20/hour")
def subir():
    t = _permitido()
    archivo = request.files.get("archivo")
    if archivo is None or not archivo.filename:
        return redirect(url_for("importar_clientes.inicio", error=_("Elige un archivo.")))
    try:
        ident = imp.preparar(t, g.usuario_id, archivo.filename, archivo.read(imp.MAX_BYTES + 1))
    except imp.ErrorImportacion as e:
        return redirect(url_for("importar_clientes.inicio", error=str(e)))
    return redirect(url_for("importar_clientes.revisar", ident=ident))


@importar_clientes_bp.route("/plantilla.csv")
@login_required
def plantilla():
    _permitido()
    return Response("﻿" + imp.PLANTILLA_CSV, mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="plantilla-clientes.csv"'})


def _datos_revision(t: int, ident: str, origen):
    importacion = imp.cargar(t, g.usuario_id, ident)
    if importacion is None:
        return None, None, None, None
    corr = _correspondencia(importacion["cabeceras"], origen)
    try:
        previa, error = imp.vista_previa(t, importacion, corr), None
    except imp.ErrorImportacion as e:
        previa, error = None, str(e)
    return importacion, corr, previa, error


@importar_clientes_bp.route("/<ident>", methods=["GET"])
@login_required
def revisar(ident: str):
    t = _permitido()
    importacion, corr, previa, error = _datos_revision(t, ident, request.args)
    if importacion is None:
        return redirect(url_for("importar_clientes.inicio", error=_("Esa importación ya no está disponible: sube el archivo otra vez.")))
    return render_template(
        "clientes_importar_vista.html", ident=ident, importacion=importacion, correspondencia=corr, previa=previa, error=error, subnav="clientes", campos=imp.ETIQUETAS_CAMPO,
        gestion_fiscal_disponible=alta_cliente.gestion_fiscal_disponible(t), paises=alta_cliente.PAISES, max_mostradas=100, etiqueta_sugerida=_("importación") + f" {date.today().isoformat()}")


@importar_clientes_bp.route("/<ident>", methods=["POST"])
@login_required
@limiter.limit("20/hour")
def confirmar(ident: str):
    t = _permitido()
    importacion, corr, previa, error = _datos_revision(t, ident, request.form)
    if importacion is None:
        return redirect(url_for("importar_clientes.inicio", error=_("Esa importación ya no está disponible: sube el archivo otra vez.")))
    if previa is None:
        return redirect(url_for("importar_clientes.revisar", ident=ident, **{f"c{i}": c for i, c in corr.items()}))
    imp.descartar(ident)                       # de un solo uso: un segundo envío del mismo formulario no vuelve a crear nada
    resultado = imp.importar(
        t, g.usuario_id, importacion, corr, omitir_duplicados=request.form.get("omitir_duplicados") == "1", gestion_fiscal=request.form.get("gestion_fiscal") == "1",
        pais=request.form.get("pais") or "ES", etiqueta_comun=request.form.get("etiqueta_comun"), perfil_tipo=request.form.get("perfil_tipo") or None,
        generacion_automatica=request.form.get("generacion_automatica") == "1")
    return render_template("clientes_importar_resultado.html", r=resultado, archivo=importacion["nombre"], subnav="clientes")
