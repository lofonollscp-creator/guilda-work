"""Seguridad del despacho: cifrado de documentos con la clave del propio despacho (app/cifrado_despacho.py) y registro de quién ha abierto qué.
Solo los responsables del despacho (o un administrador) gestionan el cifrado; cualquier persona del despacho puede ver si está protegido."""
from __future__ import annotations

from flask import Blueprint, Response, abort, g, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _

from . import cifrado_despacho as cd
from . import correo_cifrado
from . import rgpd
from .auth import limiter, login_required

seguridad_bp = Blueprint("seguridad", __name__, url_prefix="/seguridad")


def _exigir_responsable() -> int:
    if g.get("tenant_id") is None:
        abort(404)
    if not (g.get("supervisor_tenant") or g.get("es_admin")):
        abort(403)
    return g.tenant_id


@seguridad_bp.route("/cifrado")
@login_required
def cifrado():
    t = _exigir_responsable()
    return render_template("seguridad_cifrado.html", e=cd.estado(t), accesos=cd.accesos_recientes(t, 50) if cd.esta_activo(t) else [], concesiones=cd.listar_concesiones(t), correo=correo_cifrado.estado(t), niveles=cd.NIVELES,
                           frase_minima=cd.FRASE_MINIMA, error=(request.args.get("error") or "")[:300] or None, aviso=request.args.get("aviso"), clave=None)


def _volver(error: str | None = None, aviso: str | None = None):
    return redirect(url_for("seguridad.cifrado", **({"error": error} if error else {}), **({"aviso": aviso} if aviso else {})))


def _accion(f, aviso: str):
    try:
        f()
    except (ValueError, cd.ClaveIncorrecta, cd.DemasiadosIntentos) as e:
        return _volver(error=str(e))
    return _volver(aviso=aviso)


@seguridad_bp.route("/cifrado/activar", methods=["POST"])
@login_required
@limiter.limit("10/hour")
def activar():
    t = _exigir_responsable()
    if request.form.get("frase") != request.form.get("frase2"):
        return _volver(error=_("Las dos frases no coinciden."))
    if not request.form.get("entendido"):
        return _volver(error=_("Confirma que entiendes que, sin la frase y la clave de recuperación, los documentos no se pueden recuperar."))
    try:
        clave = cd.activar(t, g.usuario_id, request.form.get("frase") or "", request.form.get("nivel") or "medio")
    except ValueError as e:
        return _volver(error=str(e))
    # La clave de recuperación solo se enseña en esta respuesta: no se guarda en claro en ningún sitio ni viaja en una dirección.
    resp = render_template("seguridad_cifrado.html", e=cd.estado(t), accesos=[], concesiones=[], correo=correo_cifrado.estado(t), niveles=cd.NIVELES, frase_minima=cd.FRASE_MINIMA, error=None, aviso=None, clave=clave)
    return resp, 200, {"Cache-Control": "no-store"}


@seguridad_bp.route("/cifrado/desbloquear", methods=["POST"])
@login_required
@limiter.limit("20/hour")
def desbloquear():
    t = _exigir_responsable()
    return _accion(lambda: cd.desbloquear(t, g.usuario_id, request.form.get("frase") or ""), _("Documentos desbloqueados."))


@seguridad_bp.route("/cifrado/bloquear", methods=["POST"])
@login_required
def bloquear():
    t = _exigir_responsable()
    cd.bloquear(t)
    return _volver(aviso=_("Documentos bloqueados."))


@seguridad_bp.route("/cifrado/concesiones/<int:concesion_id>/revocar", methods=["POST"])
@login_required
def revocar_concesion(concesion_id: int):
    t = _exigir_responsable()
    if not cd.revocar_concesion(t, concesion_id):
        abort(404)
    return _volver(aviso=_("Acceso revocado."))


@seguridad_bp.route("/cifrado/correo/activar", methods=["POST"])
@login_required
@limiter.limit("10/hour")
def activar_correo():
    """Activa el correo cifrado (opcional): sella el correo que ya hay y todo el que llegue. No necesita desbloqueo."""
    t = _exigir_responsable()
    try:
        r = correo_cifrado.activar(t, g.usuario_id, request.form.get("nivel") or None)
    except ValueError as e:
        return _volver(error=str(e))
    return _volver(aviso=_("Correo cifrado activado: %(n)s mensajes protegidos.", n=r["sellados"]))


@seguridad_bp.route("/cifrado/correo/nivel", methods=["POST"])
@login_required
@limiter.limit("20/hour")
def nivel_correo():
    """Cambia el nivel de reserva (Laxo, Medio, Estricto). Subirlo no necesita desbloqueo; bajarlo sí."""
    t = _exigir_responsable()
    try:
        n = correo_cifrado.cambiar_nivel(t, g.usuario_id, request.form.get("nivel") or "")
    except (ValueError, cd.DespachoBloqueado) as e:
        return _volver(error=str(e))
    return _volver(aviso=_("Nivel cambiado: %(n)s mensajes actualizados.", n=n))


@seguridad_bp.route("/cifrado/correo/desactivar", methods=["POST"])
@login_required
@limiter.limit("5/hour")
def desactivar_correo():
    """Desactiva el correo cifrado y deja todo en claro. Exige el despacho desbloqueado."""
    t = _exigir_responsable()
    try:
        n = correo_cifrado.desactivar(t, g.usuario_id)
    except (ValueError, cd.DespachoBloqueado) as e:
        return _volver(error=str(e))
    return _volver(aviso=_("Correo cifrado desactivado: %(n)s mensajes descifrados.", n=n))


@seguridad_bp.route("/cifrado/rotar", methods=["POST"])
@login_required
@limiter.limit("5/hour")
def rotar():
    """Cambia la clave del despacho (re-cifra todo). La clave de recuperación nueva solo se enseña en esta respuesta."""
    t = _exigir_responsable()
    if not request.form.get("entendido"):
        return _volver(error=_("Confirma que has entendido que se re-cifran todos los documentos y se revocan los accesos de las integraciones."))
    try:
        clave = cd.rotar_clave(t, g.usuario_id, request.form.get("frase") or "")
    except (ValueError, cd.ClaveIncorrecta, cd.DemasiadosIntentos, cd.ContenidoAlterado) as e:
        return _volver(error=str(e))
    return render_template("seguridad_cifrado.html", e=cd.estado(t), accesos=[], concesiones=[], correo=correo_cifrado.estado(t), niveles=cd.NIVELES, frase_minima=cd.FRASE_MINIMA, error=None, aviso=None, clave=clave), 200, {"Cache-Control": "no-store"}


@seguridad_bp.route("/cifrado/frase", methods=["POST"])
@login_required
@limiter.limit("10/hour")
def cambiar_frase():
    t = _exigir_responsable()
    if request.form.get("frase_nueva") != request.form.get("frase_nueva2"):
        return _volver(error=_("Las dos frases nuevas no coinciden."))
    return _accion(lambda: cd.cambiar_frase(t, g.usuario_id, request.form.get("frase_actual") or "", request.form.get("frase_nueva") or ""), _("Frase cambiada."))


@seguridad_bp.route("/cifrado/recuperar", methods=["POST"])
@login_required
@limiter.limit("10/hour")
def recuperar():
    t = _exigir_responsable()
    if request.form.get("frase_nueva") != request.form.get("frase_nueva2"):
        return _volver(error=_("Las dos frases nuevas no coinciden."))
    return _accion(lambda: cd.recuperar(t, g.usuario_id, request.form.get("clave") or "", request.form.get("frase_nueva") or ""), _("Frase restablecida y documentos desbloqueados."))


@seguridad_bp.route("/privacidad")
@login_required
def privacidad():
    t = _exigir_responsable()
    return render_template("seguridad_privacidad.html", registro=rgpd.registro(t), dias=rgpd.DIAS_PERMITIDOS, error=(request.args.get("error") or "")[:300] or None, aviso=request.args.get("aviso"))


@seguridad_bp.route("/privacidad/vaciar-papelera", methods=["POST"])
@login_required
@limiter.limit("10/hour")
def vaciar_papelera():
    t = _exigir_responsable()
    try:
        r = rgpd.vaciar_papelera(t, g.usuario_id, request.form.get("dias", type=int) if request.form.get("dias") not in (None, "") else -1)
    except ValueError as e:
        return redirect(url_for("seguridad.privacidad", error=str(e)))
    return redirect(url_for("seguridad.privacidad", aviso=_("Papelera vaciada: %(d)s documentos, %(p)s plazos y %(h)s partes de horas.", d=r["documentos"], p=r["plazos"], h=r["partes_tiempo"])))


@seguridad_bp.route("/clientes/<int:cliente_id>/exportar.json")
@login_required
def exportar_cliente(cliente_id: int):
    """Todo lo que el despacho guarda de un cliente (derecho de acceso y portabilidad), en JSON. Solo responsables."""
    t = _exigir_responsable()
    datos = rgpd.exportar_cliente(t, g.usuario_id, True, cliente_id)
    if datos is None:
        abort(404)
    import json
    return Response(json.dumps(datos, ensure_ascii=False, indent=2, default=str), mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="cliente-{cliente_id}.json"', "Cache-Control": "no-store"})


@seguridad_bp.teardown_app_request
def _olvidar_concesion(_exc=None):
    """Los hilos del servidor se reutilizan: la concesión de una petición no puede pasar a la siguiente."""
    cd.restablecer_concesion()


@seguridad_bp.app_errorhandler(cd.DespachoBloqueado)
def _despacho_bloqueado(error):
    """Lo cifrado no se lee con el despacho bloqueado: se dice claro (423), nunca se devuelve vacío."""
    mensaje = str(error)
    if request.path.startswith("/api/"):
        return jsonify(ok=False, error=mensaje, codigo="despacho_bloqueado"), 423
    return render_template("seguridad_bloqueado.html", mensaje=mensaje), 423
