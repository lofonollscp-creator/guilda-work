"""Pantallas del Marketing del Comercial (ver app/marketing.py): consentimientos, grupos, plantillas, envíos y la baja de un clic sin iniciar sesión."""
from __future__ import annotations

from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for
from flask_babel import gettext as _

from . import comercial, db, marketing, verticales
from .auth import login_required
from .bd import contexto
from .marketing import ErrorMarketing

marketing_bp = Blueprint("marketing", __name__, url_prefix="/comercial/marketing")
baja_bp = Blueprint("baja_marketing", __name__)


@marketing_bp.before_request
def _solo_con_el_modulo():
    if g.get("tenant_id") is None or not verticales.esta_activo(g.tenant_id, "comercial"):
        abort(404)


def _error() -> str | None:
    return (request.args.get("error") or "")[:300] or None


def _con_error(destino: str, e: Exception, **valores):
    return redirect(url_for(destino, error=_(str(e)) if str(e) else None, **valores))


def _equipo() -> list:
    return db.listar_companeros_tenant(g.usuario_id)


def _plano(**extra) -> dict:
    return {"subnav_activa": "marketing", "error": _error(), **extra}


# --- Inicio ----------------------------------------------------------------------------------------------------------------------

@marketing_bp.route("/")
@login_required
def inicio():
    return render_template("marketing_inicio.html", **_plano(resumen=marketing.resumen_consentimientos(g.tenant_id), envios=marketing.listar_envios(g.tenant_id, 5),
                                                             canal=marketing.canal_configurado(), faltan=marketing.datos_legales_que_faltan(g.tenant_id)))


# --- Consentimientos -------------------------------------------------------------------------------------------------------------

@marketing_bp.route("/consentimientos", methods=["GET", "POST"])
@login_required
def consentimientos():
    if request.method == "POST":
        f = request.form
        try:
            if f.get("accion") == "baja":
                marketing.registrar_baja(g.tenant_id, g.usuario_id, f.get("email"), origen="manual", motivo=f.get("evidencia") or "Baja registrada a mano")
            else:
                marketing.registrar_consentimiento(g.tenant_id, g.usuario_id, f.get("email"), origen=f.get("origen", ""), evidencia=f.get("evidencia", ""), nombre=f.get("nombre", ""))
        except ErrorMarketing as e:
            return _con_error("marketing.consentimientos", e)
        return redirect(url_for("marketing.consentimientos"))
    estado = request.args.get("estado") if request.args.get("estado") in ("consentido", "baja", "rebotado") else None
    return render_template("marketing_consentimientos.html", **_plano(contactos=marketing.listar_contactos(g.tenant_id, estado=estado, q=request.args.get("q")), estado=estado,
                                                                      q=request.args.get("q") or "", origenes=marketing.ORIGENES_MANUALES, nombres_origen=marketing.ORIGENES,
                                                                      resumen=marketing.resumen_consentimientos(g.tenant_id)))


# --- Grupos ---------------------------------------------------------------------------------------------------------------------

def _reglas_del_formulario(f) -> dict:
    return {"fuente": f.get("fuente"), "tipo": f.get("tipo"), "etiquetas": [x for x in (f.get("etiquetas") or "").split(",") if x.strip()], "etiquetas_modo": f.get("etiquetas_modo"),
            "origen": f.get("origen"), "idioma": f.get("idioma"), "etapa": f.get("etapa"), "responsable_id": f.get("responsable_id") or None}


@marketing_bp.route("/grupos", methods=["GET", "POST"])
@login_required
def grupos():
    if request.method == "POST":
        try:
            marketing.crear_grupo(g.tenant_id, g.usuario_id, request.form.get("nombre", ""), _reglas_del_formulario(request.form), request.form.get("descripcion", ""))
        except ErrorMarketing as e:
            return _con_error("marketing.grupos", e)
        return redirect(url_for("marketing.grupos"))
    lista = marketing.listar_grupos(g.tenant_id)
    for gr in lista:
        a = marketing.audiencia(g.tenant_id, g.usuario_id, gr["reglas"])
        gr["destinatarios"], gr["excluidos"] = len(a["destinatarios"]), a["excluidos"]
    return render_template("marketing_grupos.html", **_plano(grupos=lista, equipo=_equipo(), etapas=comercial.listar_etapas(g.tenant_id)))


@marketing_bp.route("/grupos/<int:grupo_id>/papelera", methods=["POST"])
@login_required
def grupo_papelera(grupo_id: int):
    try:
        marketing.papelera_grupo(g.tenant_id, g.usuario_id, grupo_id)
    except ErrorMarketing as e:
        return _con_error("marketing.grupos", e)
    return redirect(url_for("marketing.grupos"))


@marketing_bp.route("/grupos/<int:grupo_id>/audiencia.csv")
@login_required
def grupo_csv(grupo_id: int):
    gr = marketing.obtener_grupo(g.tenant_id, grupo_id)
    if gr is None:
        abort(404)
    datos = marketing.exportar_audiencia_csv(marketing.audiencia(g.tenant_id, g.usuario_id, gr["reglas"])["destinatarios"])
    return Response(datos, mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="audiencia-{grupo_id}.csv"', "Cache-Control": "private, no-store"})


# --- Plantillas -----------------------------------------------------------------------------------------------------------------

def _bloques_del_formulario(f) -> list[dict]:
    bloques = []
    for tipo, texto, url in zip(f.getlist("tipo"), f.getlist("texto"), f.getlist("url")):
        if tipo == "divisor" or texto.strip() or (url.strip() and tipo == "imagen"):
            bloques.append({"tipo": tipo, "texto": texto, "url": url})
    return bloques


@marketing_bp.route("/plantillas")
@login_required
def plantillas():
    return render_template("marketing_plantillas.html", **_plano(plantillas=marketing.listar_plantillas(g.tenant_id)))


@marketing_bp.route("/plantillas/nueva", methods=["GET", "POST"])
@marketing_bp.route("/plantillas/<int:plantilla_id>", methods=["GET", "POST"])
@login_required
def plantilla(plantilla_id: int | None = None):
    existente = marketing.obtener_plantilla(g.tenant_id, plantilla_id) if plantilla_id else None
    if plantilla_id and existente is None:
        abort(404)
    nombre = existente["nombre"] if existente else ""
    asunto = existente["asunto"] if existente else ""
    bloques = existente["bloques"] if existente else [dict(b) for b in marketing.PLANTILLA_INICIAL]
    error, vista, ia = _error(), None, None
    if request.method == "POST":
        f = request.form
        nombre, asunto, bloques = f.get("nombre", ""), f.get("asunto", ""), _bloques_del_formulario(f)
        try:
            if f.get("accion") == "previsualizar":
                vista = marketing.vista_previa(g.tenant_id, bloques)
            elif f.get("accion") == "ia":
                ia = marketing.asistente_ia(g.tenant_id, g.usuario_id, f.get("ia_accion", ""), "\n\n".join(b["texto"] for b in bloques if b["tipo"] in ("titulo", "texto")), f.get("objetivo", ""))
            elif existente:
                marketing.editar_plantilla(g.tenant_id, g.usuario_id, plantilla_id, nombre, asunto, bloques)
                return redirect(url_for("marketing.plantilla", plantilla_id=plantilla_id))
            else:
                return redirect(url_for("marketing.plantilla", plantilla_id=marketing.crear_plantilla(g.tenant_id, g.usuario_id, nombre, asunto, bloques)))
        except ErrorMarketing as e:
            error = str(e)
    return render_template("marketing_plantilla.html", **_plano(p=existente, nombre=nombre, asunto=asunto, bloques=bloques + [{"tipo": "texto", "texto": "", "url": ""}] * 2, vista=vista, ia=ia,
                                                                tipos=marketing.TIPOS_BLOQUE, variables=marketing.VARIABLES, acciones_ia=marketing.ACCIONES_IA, error=error))


@marketing_bp.route("/plantillas/<int:plantilla_id>/papelera", methods=["POST"])
@login_required
def plantilla_papelera(plantilla_id: int):
    try:
        marketing.papelera_plantilla(g.tenant_id, g.usuario_id, plantilla_id)
    except ErrorMarketing as e:
        return _con_error("marketing.plantillas", e)
    return redirect(url_for("marketing.plantillas"))


# --- Envíos ---------------------------------------------------------------------------------------------------------------------

@marketing_bp.route("/envios")
@login_required
def envios():
    return render_template("marketing_envios.html", **_plano(envios=marketing.listar_envios(g.tenant_id)))


@marketing_bp.route("/envios/nuevo", methods=["GET", "POST"])
@login_required
def envio_nuevo():
    if request.method == "POST":
        f = request.form
        p = marketing.obtener_plantilla(g.tenant_id, int(f.get("plantilla_id") or 0))
        try:
            if p is None:
                raise ErrorMarketing("Elige una plantilla.")
            eid = marketing.crear_envio(g.tenant_id, g.usuario_id, f.get("nombre", ""), int(f.get("grupo_id") or 0), f.get("asunto") or p["asunto"], p["bloques"])
        except ErrorMarketing as e:
            return _con_error("marketing.envio_nuevo", e)
        return redirect(url_for("marketing.envio_ver", envio_id=eid))
    return render_template("marketing_envio_nuevo.html", **_plano(grupos=marketing.listar_grupos(g.tenant_id), plantillas=marketing.listar_plantillas(g.tenant_id)))


def _envio_o_404(envio_id: int) -> dict:
    e = marketing.obtener_envio(g.tenant_id, envio_id)
    if e is None:
        abort(404)
    return e


@marketing_bp.route("/envios/<int:envio_id>")
@login_required
def envio_ver(envio_id: int):
    e = _envio_o_404(envio_id)
    revision = marketing.revisar(g.tenant_id, g.usuario_id, envio_id) if e["estado"] == "borrador" else None
    return render_template("marketing_envio_ver.html", **_plano(e=e, revision=revision, destinatarios=marketing.destinatarios_de(g.tenant_id, envio_id) if e["estado"] != "borrador" else [],
                                                                vista=marketing.vista_previa(g.tenant_id, e["bloques"]), aviso=request.args.get("aviso"), es_direccion=bool(g.get("supervisor_tenant") or g.get("es_admin"))))


@marketing_bp.route("/envios/<int:envio_id>/prueba", methods=["POST"])
@login_required
def envio_prueba(envio_id: int):
    _envio_o_404(envio_id)
    try:
        marketing.enviar_prueba(g.tenant_id, g.usuario_id, envio_id, request.form.get("email", ""), url_base=request.url_root)
    except ErrorMarketing as e:
        return _con_error("marketing.envio_ver", e, envio_id=envio_id)
    return redirect(url_for("marketing.envio_ver", envio_id=envio_id, aviso="prueba"))


@marketing_bp.route("/envios/<int:envio_id>/programar", methods=["POST"])
@login_required
def envio_programar(envio_id: int):
    _envio_o_404(envio_id)
    try:
        marketing.programar(g.tenant_id, g.usuario_id, envio_id, request.form.get("confirmacion", ""), url_base=request.url_root)
    except ErrorMarketing as e:
        return _con_error("marketing.envio_ver", e, envio_id=envio_id)
    return redirect(url_for("marketing.envio_ver", envio_id=envio_id, aviso="programado"))


@marketing_bp.route("/envios/<int:envio_id>/cancelar", methods=["POST"])
@login_required
def envio_cancelar(envio_id: int):
    _envio_o_404(envio_id)
    try:
        marketing.cancelar_envio(g.tenant_id, g.usuario_id, envio_id)
    except ErrorMarketing as e:
        return _con_error("marketing.envio_ver", e, envio_id=envio_id)
    return redirect(url_for("marketing.envio_ver", envio_id=envio_id, aviso="cancelado"))


@marketing_bp.route("/envios/<int:envio_id>/audiencia.csv")
@login_required
def envio_csv(envio_id: int):
    e = _envio_o_404(envio_id)
    gr = marketing.obtener_grupo(g.tenant_id, e["grupo_id"]) if e["grupo_id"] else None
    if gr is None:
        abort(404)
    datos = marketing.exportar_audiencia_csv(marketing.audiencia(g.tenant_id, g.usuario_id, gr["reglas"])["destinatarios"])
    return Response(datos, mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="envio-{envio_id}.csv"', "Cache-Control": "private, no-store"})


# --- Baja de un clic (pública) ---------------------------------------------------------------------------------------------------

@baja_bp.route("/baja/<token>", methods=["GET", "POST"])
def baja(token: str):
    """Sin iniciar sesión: el enlace firmado de cada correo. GET pide confirmar; POST (también el de «un clic» de los clientes de correo) da de baja."""
    v = marketing.verificar_token_baja(token)
    if v is None:
        return render_template("marketing_baja.html", estado="invalido"), 404
    tenant_id, email = v
    if request.method == "POST":
        with contexto.en_despacho(tenant_id):
            marketing.registrar_baja(tenant_id, None, email, origen="baja_en_correo", motivo="Baja pedida desde el enlace del correo")
        return render_template("marketing_baja.html", estado="hecha")
    return render_template("marketing_baja.html", estado="confirmar", token=token)
