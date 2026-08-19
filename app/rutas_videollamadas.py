"""Videollamadas (Jitsi Meet) -- hasta ahora `jitsi.generar_jwt_sala()`
solo era alcanzable desde el Asistente IA (`mcp_tools.py:videollamadas_crear_sala`),
sin ninguna ruta web: un empleado que quisiera iniciar una llamada tenía
que pedírselo al asistente con un prompt. Instancia compartida, sin
aprovisionamiento por tenant (ver app/jitsi.py) -- una sala no tiene
datos persistentes que listar, así que esta vista es solo un formulario
para crear una sala nueva y entrar directamente, no un listado."""
import uuid

from flask import Blueprint, abort, g, redirect, render_template, request

from . import db, jitsi
from .auth import login_required

videollamadas_bp = Blueprint("videollamadas", __name__, url_prefix="/videollamadas")


@videollamadas_bp.route("/")
@login_required
def nueva():
    return render_template("videollamadas_nueva.html", error=None)


@videollamadas_bp.route("/", methods=["POST"])
@login_required
def crear():
    if g.tenant_id is None:
        abort(403)
    tenant = db.obtener_tenant(g.tenant_id)
    usuario = db.obtener_usuario(g.usuario_id)
    nombre_mostrado = (request.form.get("nombre_mostrado") or "").strip() or usuario["email"]
    try:
        sala = jitsi.nombre_sala(tenant["nombre"], uuid.uuid4().hex[:12])
        token = jitsi.generar_jwt_sala(tenant["nombre"], nombre_mostrado, sala, moderador=True)
    except jitsi.ErrorJitsi as e:
        return render_template("videollamadas_nueva.html", error=str(e))
    return redirect(jitsi.url_sala(sala, token))
