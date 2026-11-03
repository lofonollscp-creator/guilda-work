"""«Mis datos y privacidad»: la persona usuaria ejerce por sí misma sus derechos RGPD (app/rgpd_persona.py)."""
from flask import Blueprint, Response, g, redirect, render_template, request, url_for

from . import db, rgpd_persona
from .auth import limiter, login_required

mis_datos_bp = Blueprint("mis_datos", __name__, url_prefix="/cuenta/privacidad")


@mis_datos_bp.route("/")
@login_required
def pantalla():
    return render_template("mis_datos.html", aviso=request.args.get("aviso"), solicitud_abierta=rgpd_persona.solicitud_abierta(g.usuario_id), conversaciones=len(db.listar_conversaciones_ia(g.usuario_id)))


@mis_datos_bp.route("/descargar.json")
@login_required
@limiter.limit("10/hour")
def descargar():
    datos = rgpd_persona.exportar_mis_datos(g.usuario_id)
    return Response(rgpd_persona.como_json(datos), mimetype="application/json",
                    headers={"Content-Disposition": 'attachment; filename="mis-datos-guilda-work.json"', "Cache-Control": "no-store"})


@mis_datos_bp.route("/borrar-historial-ia", methods=["POST"])
@login_required
@limiter.limit("20/hour")
def borrar_historial_ia():
    rgpd_persona.borrar_historial_ia(g.usuario_id)
    return redirect(url_for("mis_datos.pantalla", aviso="historial_ia"))


@mis_datos_bp.route("/olvidar-dispositivos", methods=["POST"])
@login_required
@limiter.limit("20/hour")
def olvidar_dispositivos():
    rgpd_persona.olvidar_dispositivos(g.usuario_id)
    return redirect(url_for("mis_datos.pantalla", aviso="dispositivos"))


@mis_datos_bp.route("/solicitar-baja", methods=["POST"])
@login_required
@limiter.limit("5/hour")
def solicitar_baja():
    rgpd_persona.solicitar_baja(g.usuario_id)
    return redirect(url_for("mis_datos.pantalla", aviso="baja"))
