"""Reglas laborales de la plataforma (app/reglas_laborales.py): el propietario escribe y aprueba aquí cuándo vencen el TC, el modelo 190 y los plazos que nacen de un alta, una baja o un
contrato. Hasta que una regla no se aprueba, ningún despacho genera nada de ella."""
from __future__ import annotations

from flask import flash, g, redirect, render_template, request, url_for

from app import reglas_laborales

from . import auth
from .rutas import bp


@bp.route("/reglas-laborales")
@auth.login_required
def reglas_laborales_vista():
    return render_template("reglas_laborales.html", reglas=reglas_laborales.estado_de_todas(), unidades=reglas_laborales.UNIDADES, error=request.args.get("error"))


@bp.route("/reglas-laborales/<clave>", methods=["POST"])
@auth.login_required
def reglas_laborales_guardar(clave: str):
    try:
        reglas_laborales.guardar_borrador(clave, g.admin["usuario"], **request.form.to_dict())
    except ValueError as e:
        return redirect(url_for("rutas.reglas_laborales_vista", error=str(e)))
    flash("Borrador guardado: todavía no está aprobado, así que no se aplica.")
    return redirect(url_for("rutas.reglas_laborales_vista") + f"#{clave}")


@bp.route("/reglas-laborales/<clave>/<int:version>/aprobar", methods=["POST"])
@auth.login_required
def reglas_laborales_aprobar(clave: str, version: int):
    try:
        reglas_laborales.aprobar(clave, version, g.admin["usuario"])
    except ValueError as e:
        return redirect(url_for("rutas.reglas_laborales_vista", error=str(e)))
    flash("Regla aprobada: desde ahora los despachos la aplican.")
    return redirect(url_for("rutas.reglas_laborales_vista") + f"#{clave}")


# --- Reglas fiscales (catálogo global de modelos y fechas) ----------------------------------------------------------------------------------------

from app import reglas_fiscales  # noqa: E402


@bp.route("/reglas-fiscales")
@auth.login_required
def reglas_fiscales_vista():
    return render_template("reglas_fiscales.html", reglas=reglas_fiscales.estado_de_todos(), error=request.args.get("error"))


@bp.route("/reglas-fiscales/guardar", methods=["POST"])
@auth.login_required
def reglas_fiscales_guardar():
    datos = request.form.to_dict()
    pais, modelo, tipo = datos.pop("pais", ""), datos.pop("modelo", ""), datos.pop("tipo", "")
    activa = datos.pop("activa", "") == "1"
    nota = datos.pop("nota", "")
    try:
        reglas_fiscales.guardar_borrador(pais, modelo, tipo, g.admin["usuario"], activa=activa, nota=nota, **{k: v for k, v in datos.items() if k != "_csrf"})
    except ValueError as e:
        return redirect(url_for("rutas.reglas_fiscales_vista", error=str(e)))
    flash("Borrador guardado: todavía no está aprobado, así que no se aplica.")
    return redirect(url_for("rutas.reglas_fiscales_vista") + f"#{pais.upper()}-{modelo.upper()}")


@bp.route("/reglas-fiscales/<pais>/<modelo>/<int:version>/aprobar", methods=["POST"])
@auth.login_required
def reglas_fiscales_aprobar(pais: str, modelo: str, version: int):
    try:
        reglas_fiscales.aprobar(pais, modelo, version, g.admin["usuario"])
    except ValueError as e:
        return redirect(url_for("rutas.reglas_fiscales_vista", error=str(e)))
    flash("Regla aprobada: los vencimientos que se generen a partir de ahora la usan. Los ya generados conservan su fecha.")
    return redirect(url_for("rutas.reglas_fiscales_vista") + f"#{pais}-{modelo}")
