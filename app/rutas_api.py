"""API REST con autenticación por token (Fase 2 de la app móvil): capa fina
de JSON sobre el mismo backend que ya usan las rutas web
(`app/main.py`, `app/rutas_tareas.py`, `app/rutas_correo.py`,
`app/rutas_ia.py`) — ningún endpoint reimplementa lógica de negocio, todos
delegan en las mismas funciones de `db.py`/`correo.py`/`export.py`/
`outlook_ics.py`/`ia_asistente.py`.

Autenticación: cabecera `Authorization: Bearer <token>` (ver
`token_required` en app/auth.py), independiente de la cookie de sesión que
usa la app de escritorio — nunca se mezclan en la misma ruta.

Formato de respuesta uniforme: `{"ok": true, "data": ...}` en éxito,
`{"ok": false, "error": "..."}` en fallo. Cualquier HTTPException (404 de
`abort()`, 405, etc.) se convierte también a ese mismo formato mediante el
errorhandler de más abajo, para que un cliente Flutter nunca reciba HTML.
"""
import base64
from datetime import datetime

from flask import Blueprint, Response, abort, g, jsonify, request
from werkzeug.exceptions import HTTPException

from . import correo, db, export, ia_asistente, kratos
from .auth import limiter, token_required
from .rutas_correo import _ids_propios_del_usuario, _mensaje_de_usuario_o_404

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


@api_bp.errorhandler(HTTPException)
def _error_json(e: HTTPException):
    return jsonify({"ok": False, "error": e.description}), e.code


def _dict(fila) -> dict | None:
    return dict(fila) if fila is not None else None


def _dicts(filas) -> list[dict]:
    return [dict(f) for f in filas]


def _ok(data=None, status: int = 200):
    cuerpo = {"ok": True}
    if data is not None:
        cuerpo["data"] = data
    return jsonify(cuerpo), status


def _err(mensaje: str, status: int = 400):
    return jsonify({"ok": False, "error": mensaje}), status


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _token_de_cabecera() -> str | None:
    cabecera = request.headers.get("Authorization", "")
    return cabecera[7:] if cabecera.startswith("Bearer ") else None


# --- Auth ----------------------------------------------------------------

@api_bp.route("/auth/registro", methods=["POST"])
@limiter.limit("10/minute")
def registro():
    """Fase 7a: la contraseña la custodia Kratos, no esta tabla — el móvil
    sigue recibiendo el mismo token opaco propio de siempre (sin cambios en
    mobile/), solo cambia qué la valida por debajo."""
    datos = _body()
    email = (datos.get("email") or "").strip()
    contrasena = datos.get("contrasena") or ""
    if not email or "@" not in email:
        return _err("Indica un email válido.")
    if len(contrasena) < 8:
        return _err("La contraseña debe tener al menos 8 caracteres.")
    if db.obtener_usuario_por_email(email) is not None:
        return _err("Ya existe una cuenta con ese email.", 409)
    try:
        identity_id = kratos.crear_identidad(email, contrasena)
    except kratos.ErrorKratos as e:
        return _err(str(e))
    usuario_id = db.crear_usuario_vinculado_a_kratos(email, identity_id)
    token = db.crear_token_api(usuario_id, datos.get("nombre_dispositivo"))
    return _ok({"token": token, "usuario": {"id": usuario_id, "email": email}}, 201)


@api_bp.route("/auth/login", methods=["POST"])
@limiter.limit("10/minute")
def login():
    datos = _body()
    email = (datos.get("email") or "").strip()
    contrasena = datos.get("contrasena") or ""
    identity_id = kratos.verificar_credenciales_admin(email, contrasena)
    if identity_id is None:
        return _err("Email o contraseña incorrectos.", 401)
    usuario = db.usuario_por_kratos_id(identity_id)
    if usuario is None:
        # Identidad ya existente en Kratos (p.ej. migrada por
        # scripts/migrar_usuarios_a_kratos.py) que todavía no tiene fila
        # local vinculada — se crea aquí, la primera vez que entra.
        usuario_id = db.crear_usuario_vinculado_a_kratos(email, identity_id)
        usuario = db.obtener_usuario(usuario_id)
    token = db.crear_token_api(usuario["id"], datos.get("nombre_dispositivo"))
    return _ok({"token": token, "usuario": {"id": usuario["id"], "email": usuario["email"]}})


@api_bp.route("/auth/logout", methods=["POST"])
@token_required
def logout():
    token = _token_de_cabecera()
    if token:
        db.revocar_token_api(token)
    return _ok()


@api_bp.route("/auth/me", methods=["GET"])
@token_required
def me():
    usuario = db.obtener_usuario(g.usuario_id)
    return _ok({"id": usuario["id"], "email": usuario["email"]})


# --- Menús / categorías ----------------------------------------------------

@api_bp.route("/categorias", methods=["GET"])
@token_required
def listar_categorias():
    return _ok(_dicts(db.listar_categorias(g.usuario_id)))


@api_bp.route("/categorias", methods=["POST"])
@token_required
def crear_categoria():
    datos = _body()
    nombre = (datos.get("nombre") or "").strip()
    if not nombre:
        return _err("El nombre no puede estar vacío.")
    categoria_id = db.crear_categoria(g.usuario_id, nombre, datos.get("color"))
    return _ok(_dict(db.obtener_categoria(g.usuario_id, categoria_id)), 201)


@api_bp.route("/categorias/<int:categoria_id>", methods=["DELETE"])
@token_required
def eliminar_categoria(categoria_id: int):
    if db.obtener_categoria(g.usuario_id, categoria_id) is None:
        abort(404, "Menú no encontrado.")
    db.eliminar_categoria(g.usuario_id, categoria_id)
    return _ok()


@api_bp.route("/categorias/<int:categoria_id>/favorito", methods=["POST"])
@token_required
def alternar_favorito_categoria(categoria_id: int):
    if db.obtener_categoria(g.usuario_id, categoria_id) is None:
        abort(404, "Menú no encontrado.")
    db.alternar_favorito_categoria(g.usuario_id, categoria_id)
    return _ok(_dict(db.obtener_categoria(g.usuario_id, categoria_id)))


@api_bp.route("/categorias/reordenar", methods=["POST"])
@token_required
def reordenar_categorias():
    datos = _body()
    orden_ids = [int(i) for i in (datos.get("orden") or []) if str(i).isdigit()]
    db.reordenar_categorias(g.usuario_id, orden_ids)
    return _ok()


# --- Notas -----------------------------------------------------------------

@api_bp.route("/notas", methods=["POST"])
@token_required
def crear_nota():
    datos = _body()
    texto = (datos.get("texto") or "").strip()
    if not texto:
        return _err("El texto no puede estar vacío.")
    nota_id = db.crear_nota(g.usuario_id, texto, categoria_id=datos.get("categoria_id"))
    return _ok(_dict(db.obtener_nota(g.usuario_id, nota_id)), 201)


@api_bp.route("/notas/<int:nota_id>", methods=["PUT"])
@token_required
def editar_nota(nota_id: int):
    if db.obtener_nota(g.usuario_id, nota_id) is None:
        abort(404, "Nota no encontrada.")
    texto = (_body().get("texto") or "").strip()
    if not texto:
        return _err("El texto no puede estar vacío.")
    db.editar_nota(g.usuario_id, nota_id, texto)
    return _ok(_dict(db.obtener_nota(g.usuario_id, nota_id)))


@api_bp.route("/notas/<int:nota_id>", methods=["DELETE"])
@token_required
def eliminar_nota(nota_id: int):
    if db.obtener_nota(g.usuario_id, nota_id) is None:
        abort(404, "Nota no encontrada.")
    db.eliminar_nota(g.usuario_id, nota_id)
    return _ok()


# --- Tareas con duración -----------------------------------------------------

@api_bp.route("/tareas", methods=["POST"])
@token_required
def crear_tarea():
    datos = _body()
    nombre = (datos.get("nombre") or "").strip()
    categoria_id = datos.get("categoria_id")
    if not nombre or not categoria_id:
        return _err("nombre y categoria_id son obligatorios.")
    if db.obtener_categoria(g.usuario_id, int(categoria_id)) is None:
        abort(404, "Menú no encontrado.")
    tarea_id = db.crear_tarea(g.usuario_id, nombre, int(categoria_id), datos.get("tipo", "duracion"))
    return _ok(_dict(db.obtener_tarea(g.usuario_id, tarea_id)), 201)


@api_bp.route("/tareas/<int:tarea_id>", methods=["PUT"])
@token_required
def editar_tarea(tarea_id: int):
    if db.obtener_tarea(g.usuario_id, tarea_id) is None:
        abort(404, "Tarea no encontrada.")
    nombre = (_body().get("nombre") or "").strip()
    if nombre:
        db.editar_tarea(g.usuario_id, tarea_id, nombre)
    return _ok(_dict(db.obtener_tarea(g.usuario_id, tarea_id)))


@api_bp.route("/tareas/<int:tarea_id>", methods=["DELETE"])
@token_required
def eliminar_tarea(tarea_id: int):
    if db.obtener_tarea(g.usuario_id, tarea_id) is None:
        abort(404, "Tarea no encontrada.")
    db.eliminar_tarea(g.usuario_id, tarea_id)
    return _ok()


@api_bp.route("/tareas/<int:tarea_id>/pausar", methods=["POST"])
@token_required
def pausar_tarea(tarea_id: int):
    db.pausar_tarea(g.usuario_id, tarea_id)
    return _ok(_dict(db.obtener_tarea(g.usuario_id, tarea_id)))


@api_bp.route("/tareas/<int:tarea_id>/reanudar", methods=["POST"])
@token_required
def reanudar_tarea(tarea_id: int):
    db.reanudar_tarea(g.usuario_id, tarea_id)
    return _ok(_dict(db.obtener_tarea(g.usuario_id, tarea_id)))


@api_bp.route("/tareas/<int:tarea_id>/finalizar", methods=["POST"])
@token_required
def finalizar_tarea(tarea_id: int):
    db.finalizar_tarea(g.usuario_id, tarea_id)
    return _ok(_dict(db.obtener_tarea(g.usuario_id, tarea_id)))


# --- Dashboard / histórico / export ------------------------------------------

@api_bp.route("/dashboard", methods=["GET"])
@token_required
def dashboard():
    menus = db.listar_categorias(g.usuario_id)
    activas = db.tareas_activas(g.usuario_id)
    hoy = datetime.now().strftime("%Y-%m-%d")
    log_hoy = db.historial(g.usuario_id, desde=hoy, hasta=hoy)
    return _ok({
        "menus": _dicts(menus),
        "tareas_activas": _dicts(activas),
        "notas_hoy": len([f for f in log_hoy if f["origen"] == "nota"]),
        "correos_no_leidos": db.contar_no_leidos_total_correo(g.usuario_id),
    })


@api_bp.route("/historial", methods=["GET"])
@token_required
def historial():
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    categoria_id = request.args.get("categoria_id", type=int)
    q = request.args.get("q") or None
    filas = db.historial(g.usuario_id, desde=desde, hasta=hasta, categoria_id=categoria_id, texto=q)
    return _ok(_dicts(filas))


@api_bp.route("/export", methods=["GET"])
@token_required
def exportar():
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    categoria_id = request.args.get("categoria_id", type=int)
    formato = request.args.get("formato", "json")
    if formato == "csv":
        return Response(export.a_csv(g.usuario_id, desde, hasta, categoria_id), mimetype="text/csv")
    if formato == "md":
        return Response(export.a_markdown(g.usuario_id, desde, hasta, categoria_id), mimetype="text/markdown")
    return Response(export.a_json(g.usuario_id, desde, hasta, categoria_id), mimetype="application/json")


# --- Papelera ----------------------------------------------------------------

@api_bp.route("/papelera", methods=["GET"])
@token_required
def papelera():
    return _ok(_dicts(db.papelera(g.usuario_id)))


_ACCIONES_PAPELERA = {
    "nota": (db.restaurar_nota, db.eliminar_nota_definitivamente),
    "tarea": (db.restaurar_tarea, db.eliminar_tarea_definitivamente),
    "menu": (db.restaurar_categoria, db.eliminar_categoria_definitivamente),
}


@api_bp.route("/papelera/<tipo>/<int:item_id>/restaurar", methods=["POST"])
@token_required
def restaurar_de_papelera(tipo: str, item_id: int):
    if tipo not in _ACCIONES_PAPELERA:
        abort(404, "Tipo de elemento desconocido.")
    _ACCIONES_PAPELERA[tipo][0](g.usuario_id, item_id)
    return _ok()


@api_bp.route("/papelera/<tipo>/<int:item_id>/eliminar-definitivamente", methods=["POST"])
@token_required
def eliminar_definitivamente_de_papelera(tipo: str, item_id: int):
    if tipo not in _ACCIONES_PAPELERA:
        abort(404, "Tipo de elemento desconocido.")
    _ACCIONES_PAPELERA[tipo][1](g.usuario_id, item_id)
    return _ok()


# --- Tareas Outlook (estilo To-Do de Outlook) ---------------------------------

@api_bp.route("/tareas-outlook", methods=["GET"])
@token_required
def listar_tareas_outlook():
    return _ok(_dicts(db.listar_tareas_outlook(
        g.usuario_id,
        estado=request.args.get("estado") or None,
        prioridad=request.args.get("prioridad") or None,
        categoria_outlook=request.args.get("categoria") or None,
        texto=request.args.get("q") or None,
    )))


@api_bp.route("/tareas-outlook", methods=["POST"])
@token_required
def crear_tarea_outlook():
    datos = _body()
    asunto = (datos.get("asunto") or "").strip()
    if not asunto:
        return _err("El asunto no puede estar vacío.")
    tarea_id = db.crear_tarea_outlook(
        g.usuario_id, asunto=asunto, cuerpo=datos.get("cuerpo"),
        prioridad=datos.get("prioridad", "normal"),
        fecha_inicio=datos.get("fecha_inicio"), fecha_vencimiento=datos.get("fecha_vencimiento"),
        categoria_outlook=datos.get("categoria_outlook"),
    )
    return _ok(_dict(db.obtener_tarea_outlook(g.usuario_id, tarea_id)), 201)


@api_bp.route("/tareas-outlook/<int:tarea_id>", methods=["PUT"])
@token_required
def editar_tarea_outlook(tarea_id: int):
    if db.obtener_tarea_outlook(g.usuario_id, tarea_id) is None:
        abort(404, "Tarea no encontrada.")
    datos = _body()
    campos = {
        campo: datos[campo]
        for campo in (
            "asunto", "cuerpo", "estado", "prioridad", "porcentaje_completado",
            "fecha_inicio", "fecha_vencimiento", "categoria_outlook",
        )
        if campo in datos
    }
    if campos:
        db.editar_tarea_outlook(g.usuario_id, tarea_id, **campos)
    return _ok(_dict(db.obtener_tarea_outlook(g.usuario_id, tarea_id)))


@api_bp.route("/tareas-outlook/<int:tarea_id>", methods=["DELETE"])
@token_required
def eliminar_tarea_outlook(tarea_id: int):
    if db.obtener_tarea_outlook(g.usuario_id, tarea_id) is None:
        abort(404, "Tarea no encontrada.")
    db.eliminar_tarea_outlook(g.usuario_id, tarea_id)
    return _ok()


@api_bp.route("/tareas-outlook/<int:tarea_id>/completar", methods=["POST"])
@token_required
def completar_tarea_outlook(tarea_id: int):
    if db.obtener_tarea_outlook(g.usuario_id, tarea_id) is None:
        abort(404, "Tarea no encontrada.")
    db.completar_tarea_outlook(g.usuario_id, tarea_id)
    return _ok(_dict(db.obtener_tarea_outlook(g.usuario_id, tarea_id)))


# --- Correo --------------------------------------------------------------

@api_bp.route("/correo/cuentas", methods=["GET"])
@token_required
def listar_cuentas_correo():
    return _ok(_dicts(db.listar_cuentas_correo(g.usuario_id)))


@api_bp.route("/correo/cuentas", methods=["POST"])
@token_required
def crear_cuenta_correo():
    datos = _body()
    try:
        cuenta_id = correo.guardar_cuenta(
            g.usuario_id,
            nombre=datos.get("nombre", ""), protocolo=datos.get("protocolo", "imap"),
            host=datos.get("host", ""), puerto=int(datos.get("puerto") or 993),
            usuario=datos.get("usuario", ""), contrasena=datos.get("contrasena", ""),
            usa_tls=bool(datos.get("usa_tls", True)), smtp_host=datos.get("smtp_host"),
            smtp_puerto=datos.get("smtp_puerto"), smtp_tls=bool(datos.get("smtp_tls", True)),
        )
    except correo.ErrorCorreo as e:
        return _err(str(e))
    return _ok(_dict(db.obtener_cuenta_correo(g.usuario_id, cuenta_id)), 201)


@api_bp.route("/correo/cuentas/<int:cuenta_id>", methods=["DELETE"])
@token_required
def eliminar_cuenta_correo(cuenta_id: int):
    if db.obtener_cuenta_correo(g.usuario_id, cuenta_id) is None:
        abort(404, "Cuenta no encontrada.")
    correo.eliminar_cuenta(g.usuario_id, cuenta_id)
    return _ok()


@api_bp.route("/correo/cuentas/<int:cuenta_id>/sincronizar", methods=["POST"])
@token_required
def sincronizar_cuenta_correo(cuenta_id: int):
    if db.obtener_cuenta_correo(g.usuario_id, cuenta_id) is None:
        abort(404, "Cuenta no encontrada.")
    try:
        resumen = correo.sincronizar_bandeja(g.usuario_id, cuenta_id)
    except correo.ErrorCorreo as e:
        return _err(str(e))
    return _ok(resumen)


@api_bp.route("/correo/carpetas", methods=["GET"])
@token_required
def listar_carpetas_correo():
    cuenta_id = request.args.get("cuenta_id", type=int)
    if cuenta_id is None or db.obtener_cuenta_correo(g.usuario_id, cuenta_id) is None:
        abort(404, "Cuenta no encontrada.")
    return _ok(correo.listar_carpetas(g.usuario_id, cuenta_id))


@api_bp.route("/correo/mensajes", methods=["GET"])
@token_required
def listar_mensajes_correo():
    cuenta_id = request.args.get("cuenta_id", type=int)
    if cuenta_id is None or db.obtener_cuenta_correo(g.usuario_id, cuenta_id) is None:
        abort(404, "Cuenta no encontrada.")
    preferencias = db.obtener_preferencias_correo(g.usuario_id)
    mensajes = correo.listar_mensajes(
        cuenta_id,
        carpeta=request.args.get("carpeta", "INBOX"),
        solo_no_leidos=request.args.get("no_leidos") == "1",
        texto=request.args.get("q") or None,
        limite=preferencias["limite_mensajes"],
        incluir_pospuestos=request.args.get("pospuestos") == "1",
    )
    return _ok(_dicts(mensajes))


@api_bp.route("/correo/mensajes/<int:mensaje_id>", methods=["GET"])
@token_required
def obtener_mensaje_correo(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    datos = _dict(mensaje)
    datos["adjuntos"] = _dicts(db.listar_adjuntos_correo(mensaje_id))
    direccion = correo.direccion_email(mensaje["remitente"])
    datos["remitente_confiable"] = db.es_remitente_confiable(g.usuario_id, direccion)
    return _ok(datos)


@api_bp.route("/correo/mensajes/<int:mensaje_id>/adjuntos/<int:adjunto_id>", methods=["GET"])
@token_required
def descargar_adjunto_correo(mensaje_id: int, adjunto_id: int):
    if not db.adjunto_correo_pertenece_a_usuario(g.usuario_id, adjunto_id):
        abort(404, "Adjunto no encontrado.")
    adjunto = db.obtener_adjunto_correo(adjunto_id)
    if adjunto is None or adjunto["mensaje_id"] != mensaje_id:
        abort(404, "Adjunto no encontrado.")
    return Response(
        adjunto["contenido"],
        mimetype=adjunto["tipo_mime"],
        headers={"Content-Disposition": f'attachment; filename="{adjunto["nombre_archivo"]}"'},
    )


@api_bp.route("/correo/mensajes/<int:mensaje_id>", methods=["DELETE"])
@token_required
def eliminar_mensaje_correo(mensaje_id: int):
    _mensaje_de_usuario_o_404(mensaje_id)
    correo.eliminar_mensaje(mensaje_id)
    return _ok()


@api_bp.route("/correo/mensajes/<int:mensaje_id>/leido", methods=["POST"])
@token_required
def marcar_leido_correo(mensaje_id: int):
    _mensaje_de_usuario_o_404(mensaje_id)
    correo.marcar_leido(mensaje_id, bool(_body().get("leido", True)))
    return _ok()


@api_bp.route("/correo/mensajes/<int:mensaje_id>/destacar", methods=["POST"])
@token_required
def destacar_mensaje_correo(mensaje_id: int):
    _mensaje_de_usuario_o_404(mensaje_id)
    datos = _body()
    correo.destacar_mensaje(mensaje_id, bool(datos.get("destacado", True)), datos.get("fecha_aviso"))
    return _ok()


@api_bp.route("/correo/mensajes/<int:mensaje_id>/posponer", methods=["POST"])
@token_required
def posponer_mensaje_correo(mensaje_id: int):
    _mensaje_de_usuario_o_404(mensaje_id)
    correo.posponer_mensaje(mensaje_id, _body().get("hasta"))
    return _ok()


@api_bp.route("/correo/mensajes/<int:mensaje_id>/categoria", methods=["POST"])
@token_required
def asignar_categoria_correo(mensaje_id: int):
    _mensaje_de_usuario_o_404(mensaje_id)
    correo.asignar_categoria(mensaje_id, _body().get("categoria_id"))
    return _ok()


@api_bp.route("/correo/mensajes/<int:mensaje_id>/mover", methods=["POST"])
@token_required
def mover_mensaje_correo(mensaje_id: int):
    _mensaje_de_usuario_o_404(mensaje_id)
    try:
        correo.mover_mensaje(g.usuario_id, mensaje_id, _body().get("carpeta_destino", ""))
    except correo.ErrorCorreo as e:
        return _err(str(e))
    return _ok()


@api_bp.route("/correo/mensajes/lote/<accion>", methods=["POST"])
@token_required
def accion_en_lote_correo(accion: str):
    """Mismo patrón que las rutas de selección múltiple de rutas_correo.py:
    `accion` es una de leido/destacar/mover/eliminar, aplicada a la lista de
    `ids` del body que de verdad pertenezcan al usuario actual."""
    datos = _body()
    ids = _ids_propios_del_usuario([int(i) for i in datos.get("ids", []) if str(i).isdigit()])
    errores = []
    for mensaje_id in ids:
        if accion == "leido":
            correo.marcar_leido(mensaje_id, bool(datos.get("leido", True)))
        elif accion == "destacar":
            correo.destacar_mensaje(mensaje_id, bool(datos.get("destacado", True)))
        elif accion == "eliminar":
            correo.eliminar_mensaje(mensaje_id)
        elif accion == "mover":
            try:
                correo.mover_mensaje(g.usuario_id, mensaje_id, datos.get("carpeta", ""))
            except correo.ErrorCorreo as e:
                errores.append(str(e))
        else:
            abort(404, "Acción desconocida.")
    return _ok({"procesados": len(ids) - len(errores), "errores": errores})


@api_bp.route("/correo/enviar", methods=["POST"])
@token_required
def enviar_correo():
    datos = _body()
    adjuntos = [
        {
            "nombre": a.get("nombre", "adjunto"),
            "tipo": a.get("tipo") or "application/octet-stream",
            "bytes": base64.b64decode(a["contenido_base64"]),
        }
        for a in datos.get("adjuntos", []) if a.get("contenido_base64")
    ]
    try:
        correo.construir_y_enviar(
            g.usuario_id,
            datos.get("cuenta_id"), datos.get("destinatarios", ""), datos.get("asunto", ""),
            datos.get("cuerpo_html", ""), cc=datos.get("cc", ""), bcc=datos.get("bcc", ""),
            en_respuesta_a=datos.get("en_respuesta_a"), adjuntos=adjuntos or None,
        )
    except correo.ErrorCorreo as e:
        return _err(str(e))
    return _ok()


@api_bp.route("/correo/categorias", methods=["GET"])
@token_required
def listar_categorias_correo():
    return _ok(_dicts(db.listar_categorias_correo(g.usuario_id)))


@api_bp.route("/correo/categorias", methods=["POST"])
@token_required
def crear_categoria_correo():
    datos = _body()
    try:
        categoria_id = correo.crear_categoria(g.usuario_id, datos.get("nombre", ""), datos.get("color", "#7c8ba1"))
    except correo.ErrorCorreo as e:
        return _err(str(e))
    return _ok({"id": categoria_id}, 201)


@api_bp.route("/correo/categorias/<int:categoria_id>", methods=["DELETE"])
@token_required
def eliminar_categoria_correo(categoria_id: int):
    correo.eliminar_categoria(g.usuario_id, categoria_id)
    return _ok()


@api_bp.route("/correo/remitentes-confiables", methods=["GET"])
@token_required
def listar_remitentes_confiables():
    return _ok(_dicts(db.listar_remitentes_confiables(g.usuario_id)))


@api_bp.route("/correo/remitentes-confiables", methods=["POST"])
@token_required
def crear_remitente_confiable():
    datos = _body()
    try:
        remitente_id = correo.confiar_en_remitente(g.usuario_id, datos.get("direccion", ""))
    except correo.ErrorCorreo as e:
        return _err(str(e))
    return _ok({"id": remitente_id}, 201)


@api_bp.route("/correo/remitentes-confiables/<int:remitente_id>", methods=["DELETE"])
@token_required
def eliminar_remitente_confiable(remitente_id: int):
    correo.eliminar_remitente_confiable(g.usuario_id, remitente_id)
    return _ok()


@api_bp.route("/correo/reglas-categoria", methods=["GET"])
@token_required
def listar_reglas_categoria():
    return _ok(_dicts(db.listar_reglas_categoria_correo(g.usuario_id)))


@api_bp.route("/correo/reglas-categoria", methods=["POST"])
@token_required
def crear_regla_categoria():
    datos = _body()
    try:
        regla_id = correo.crear_regla_categoria(
            g.usuario_id, datos.get("remitente_patron", ""), datos.get("categoria_id"),
        )
    except correo.ErrorCorreo as e:
        return _err(str(e))
    return _ok({"id": regla_id}, 201)


@api_bp.route("/correo/reglas-categoria/<int:regla_id>", methods=["DELETE"])
@token_required
def eliminar_regla_categoria(regla_id: int):
    correo.eliminar_regla_categoria(g.usuario_id, regla_id)
    return _ok()


@api_bp.route("/correo/destinatarios-recientes", methods=["GET"])
@token_required
def buscar_destinatarios_recientes():
    q = request.args.get("q", "")
    return _ok(_dicts(db.buscar_destinatarios_recientes(g.usuario_id, q)))


@api_bp.route("/correo/ajustes", methods=["GET"])
@token_required
def obtener_ajustes_correo():
    return _ok(_dict(db.obtener_preferencias_correo(g.usuario_id)))


@api_bp.route("/correo/ajustes", methods=["POST"])
@token_required
def guardar_ajustes_correo():
    datos = _body()
    limite = max(10, min(int(datos.get("limite_mensajes") or 50), 500))
    db.guardar_preferencias_correo(
        g.usuario_id,
        densidad=datos.get("densidad", "normal"),
        marcar_leido_automatico=bool(datos.get("marcar_leido_automatico", True)),
        limite_mensajes=limite,
    )
    return _ok(_dict(db.obtener_preferencias_correo(g.usuario_id)))


@api_bp.route("/correo/firma", methods=["POST"])
@token_required
def guardar_firma_correo():
    datos = _body()
    cuenta_id = datos.get("cuenta_id")
    if db.obtener_cuenta_correo(g.usuario_id, cuenta_id) is None:
        abort(404, "Cuenta no encontrada.")
    correo.guardar_firma(
        g.usuario_id, cuenta_id, datos.get("firma_html", ""),
        en_nuevos=bool(datos.get("firma_en_nuevos", True)),
        en_respuestas=bool(datos.get("firma_en_respuestas", True)),
    )
    return _ok()


# --- Asistente IA ----------------------------------------------------------

@api_bp.route("/ia/mensajes", methods=["GET"])
@token_required
def listar_mensajes_ia():
    return _ok(_dicts(db.listar_mensajes_ia(g.usuario_id)))


@api_bp.route("/ia/mensaje", methods=["POST"])
@token_required
def enviar_mensaje_ia():
    try:
        resultado = ia_asistente.procesar_turno(g.usuario_id, _body().get("texto", ""))
    except ia_asistente.ErrorIA as e:
        return _err(str(e))
    return _ok(resultado)


@api_bp.route("/ia/confirmar", methods=["POST"])
@token_required
def confirmar_ia():
    try:
        resultado = ia_asistente.confirmar_pendiente(g.usuario_id, bool(_body().get("aceptar")))
    except ia_asistente.ErrorIA as e:
        return _err(str(e))
    return _ok(resultado)


@api_bp.route("/ia/vaciar", methods=["POST"])
@token_required
def vaciar_ia():
    db.vaciar_mensajes_ia(g.usuario_id)
    return _ok()


@api_bp.route("/ia/ajustes", methods=["GET"])
@token_required
def obtener_ajustes_ia():
    preferencias = _dict(db.obtener_preferencias_ia(g.usuario_id))
    preferencias["api_key_configurada"] = bool(ia_asistente.obtener_api_key(g.usuario_id))
    return _ok(preferencias)


@api_bp.route("/ia/ajustes", methods=["POST"])
@token_required
def guardar_ajustes_ia():
    datos = _body()
    db.guardar_preferencias_ia(
        g.usuario_id, modelo=datos.get("modelo", ""), modo_autonomo=bool(datos.get("modo_autonomo", False)),
    )
    nueva_clave = (datos.get("api_key") or "").strip()
    if nueva_clave:
        ia_asistente.guardar_api_key(g.usuario_id, nueva_clave)
    if datos.get("borrar_api_key"):
        ia_asistente.borrar_api_key(g.usuario_id)
    return _ok()
