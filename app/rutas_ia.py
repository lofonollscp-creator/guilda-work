"""Rutas del Asistente IA (chat con OpenRouter + herramientas del MCP), en
su propio Blueprint, mismo patrón que app/rutas_correo.py."""
import json

from flask import (
    Blueprint, Response, abort, g, jsonify, redirect, render_template, request, stream_with_context, url_for,
)

from flask_babel import gettext as _

from . import db, ia_asistente as asistente, ia_atajos, ia_claves, ia_consumo, ia_despacho, ia_proveedores, ia_soporte, ia_uso, ocr_local
from .ia_errores import ErrorIA
from .auth import login_required

ia_bp = Blueprint("ia", __name__, url_prefix="/ia")


def _sse(evento: dict) -> str:
    return f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"


@ia_bp.route("/")
@login_required
def asistente_vista():
    return render_template(
        "ia_asistente.html",
        conversaciones=db.listar_conversaciones_ia(g.usuario_id),
        conversacion_activa_id=db.conversacion_ia_activa_id(g.usuario_id, crear=False),
        mensajes=db.listar_mensajes_ia(g.usuario_id),
        pendiente=asistente.pendiente_actual(g.usuario_id),
        preferencias=db.obtener_preferencias_ia(g.usuario_id),
        ia_atajos=ia_atajos.atajos_para(g.usuario_id),
        panel_flotante=False,
    )


@ia_bp.route("/panel")
@login_required
def panel_flotante():
    """Contenido del panel flotante del asistente. Se pide al abrirlo (no va en cada
    página): el historial de la conversación puede ser largo."""
    return render_template(
        "_ia_panel_flotante.html", mensajes=db.listar_mensajes_ia(g.usuario_id),
        pendiente=asistente.pendiente_actual(g.usuario_id), atajos=ia_atajos.atajos_para(g.usuario_id),
    )


def _recordar_pantalla() -> None:
    """La pantalla desde la que se escribe (cabecera Referer del navegador), para que el soporte sepa de qué «aquí» habla."""
    from flask import current_app

    endpoint, argumentos = ia_soporte.pantalla_de_url(request.referrer, current_app._get_current_object())
    ia_soporte.recordar_pantalla(g.usuario_id, endpoint, argumentos)


@ia_bp.route("/mensaje", methods=["POST"])
@login_required
def enviar_mensaje():
    datos = request.get_json(silent=True) or {}
    _recordar_pantalla()
    try:
        resultado = asistente.procesar_turno(g.usuario_id, datos.get("texto", ""))
        return jsonify({"ok": True, **resultado})
    except asistente.ErrorIA as e:
        return jsonify({"ok": False, "error": _(str(e))})


_ADJUNTO_TAMANO_MAXIMO_BYTES = 1 * 1024 * 1024  # 1 MB -- son ficheros de texto/CSV pequeños, no documentos grandes
_ADJUNTO_BINARIO_MAXIMO_BYTES = 8 * 1024 * 1024  # 8 MB -- una foto o un PDF de una factura (como en Facturas para contabilizar)


def _mime_de_factura(datos: bytes) -> str | None:
    """«application/pdf», «image/jpeg» o «image/png» según lo que el archivo es de verdad (sus primeros bytes), o None si no es ninguno de los tres."""
    if datos[:5] == b"%PDF-":
        return "application/pdf"
    if datos[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if datos[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return None


@ia_bp.route("/adjuntos", methods=["POST"])
@login_required
def subir_adjunto():
    """Sube un fichero de texto/CSV al chat -- el asistente lo lee bajo
    demanda con la tool leer_adjunto_chat (app/ia_herramientas.py) cuando
    el usuario se refiera al id devuelto aquí. Sin soporte de PDF/binarios
    en esta fase (no hay ninguna librería de extracción de PDF en el
    proyecto, añadirla es una decisión aparte, no forzada por esto)."""
    fichero = request.files.get("adjunto")
    if not fichero or not fichero.filename:
        return jsonify({"ok": False, "error": "Falta el archivo."})
    datos = fichero.read(_ADJUNTO_BINARIO_MAXIMO_BYTES + 1)
    mime = _mime_de_factura(datos)
    if mime:                                                                  # una foto o un PDF (por lo que son de verdad, no por su extensión): sirve para crear una factura con `contabilidad_factura_desde_adjunto`
        if len(datos) > _ADJUNTO_BINARIO_MAXIMO_BYTES:
            return jsonify({"ok": False, "error": "El archivo pesa demasiado (máximo 8 MB)."})
        fichero_mime = mime
    else:
        if len(datos) > _ADJUNTO_TAMANO_MAXIMO_BYTES:
            return jsonify({"ok": False, "error": "El archivo pesa demasiado (máximo 1 MB)."})
        try:
            datos.decode("utf-8")
        except UnicodeDecodeError:
            return jsonify({"ok": False, "error": "Solo se admiten archivos de texto o CSV (UTF-8), fotos (JPG, PNG) o PDF."})
        fichero_mime = fichero.mimetype
    adjunto_id = db.crear_adjunto_ia(g.usuario_id, fichero.filename, fichero_mime, datos)
    return jsonify({"ok": True, "id": adjunto_id, "nombre_archivo": fichero.filename})


_TIPOS_PREVISUALIZABLES = ("application/pdf",)


@ia_bp.route("/adjuntos/<int:adjunto_id>")
@login_required
def descargar_adjunto(adjunto_id: int):
    """Sirve un adjunto del chat -- tanto los que sube el propio usuario
    como los que le manda una tool (Drive, documento firmado...), mismo
    criterio de privacidad que subir_adjunto/leer_adjunto_chat (solo el
    dueño puede verlo). Inline para imagen/PDF (se ve directo en el
    navegador), descarga forzada para el resto -- mismo patrón que
    correo.descargar_adjunto (app/rutas_correo.py)."""
    adjunto = db.obtener_adjunto_ia(g.usuario_id, adjunto_id)
    if adjunto is None:
        abort(404)
    tipo_mime = adjunto["tipo_mime"] or "application/octet-stream"
    previsualizable = tipo_mime.startswith("image/") or tipo_mime in _TIPOS_PREVISUALIZABLES
    disposicion = "inline" if previsualizable else "attachment"
    respuesta = Response(adjunto["contenido"], mimetype=tipo_mime)
    respuesta.headers.set("Content-Disposition", disposicion, filename=adjunto["nombre_archivo"])
    return respuesta


@ia_bp.route("/confirmar", methods=["POST"])
@login_required
def confirmar():
    datos = request.get_json(silent=True) or {}
    try:
        resultado = asistente.confirmar_pendiente(g.usuario_id, bool(datos.get("aceptar")))
        return jsonify({"ok": True, **resultado})
    except asistente.ErrorIA as e:
        return jsonify({"ok": False, "error": _(str(e))})


# --- Variantes en streaming (asistente de voz, Fase V1 del plan
# "eventual-herding-kitten") ------------------------------------------------
# Formato Server-Sent Events: cada línea "data: {...}\n\n" es uno de los
# eventos que ya documenta ia_asistente.procesar_turno_stream (delta de
# texto / mensaje persistido / confirmación pendiente / error / fin). Las
# rutas /mensaje y /confirmar de arriba NO se tocan -- se quedan para quien
# no necesite ir leyendo la respuesta en voz alta según llega.


@ia_bp.route("/mensaje/stream", methods=["POST"])
@login_required
def enviar_mensaje_stream():
    datos = request.get_json(silent=True) or {}
    _recordar_pantalla()
    texto = datos.get("texto", "")
    usuario_id = g.usuario_id

    def generar():
        try:
            for evento in asistente.procesar_turno_stream(usuario_id, texto):
                yield _sse(evento)
        except Exception as e:  # noqa: BLE001 -- el stream ya está abierto, no se puede devolver un 500
            yield _sse({"tipo": "error", "mensaje": asistente.mensaje_de_error(e)})

    return Response(stream_with_context(generar()), mimetype="text/event-stream")


@ia_bp.route("/confirmar/stream", methods=["POST"])
@login_required
def confirmar_stream():
    datos = request.get_json(silent=True) or {}
    aceptar = bool(datos.get("aceptar"))
    usuario_id = g.usuario_id

    def generar():
        try:
            for evento in asistente.confirmar_pendiente_stream(usuario_id, aceptar):
                yield _sse(evento)
        except Exception as e:  # noqa: BLE001
            yield _sse({"tipo": "error", "mensaje": asistente.mensaje_de_error(e)})

    return Response(stream_with_context(generar()), mimetype="text/event-stream")


@ia_bp.route("/vaciar", methods=["POST"])
@login_required
def vaciar():
    """"Nueva conversación": la anterior se conserva en la lista."""
    db.vaciar_mensajes_ia(g.usuario_id)
    return "", 204


@ia_bp.route("/conversaciones")
@login_required
def conversaciones():
    return jsonify({
        "ok": True,
        "activa": db.conversacion_ia_activa_id(g.usuario_id, crear=False),
        "conversaciones": [dict(c) for c in db.listar_conversaciones_ia(g.usuario_id)],
    })


@ia_bp.route("/conversaciones/<int:conversacion_id>/activar", methods=["POST"])
@login_required
def activar_conversacion(conversacion_id: int):
    if not db.activar_conversacion_ia(g.usuario_id, conversacion_id):
        abort(404)
    return "", 204


@ia_bp.route("/conversaciones/<int:conversacion_id>/renombrar", methods=["POST"])
@login_required
def renombrar_conversacion(conversacion_id: int):
    titulo = (request.get_json(silent=True) or {}).get("titulo", "")
    try:
        encontrada = db.renombrar_conversacion_ia(g.usuario_id, conversacion_id, titulo)
    except ValueError as e:
        return jsonify({"ok": False, "error": _(str(e))}), 400
    if not encontrada:
        abort(404)
    return "", 204


@ia_bp.route("/conversaciones/<int:conversacion_id>/eliminar", methods=["POST"])
@login_required
def eliminar_conversacion(conversacion_id: int):
    if not db.eliminar_conversacion_ia(g.usuario_id, conversacion_id):
        abort(404)
    return "", 204


@ia_bp.route("/modelos")
@login_required
def modelos():
    """Modelos gratuitos de OpenRouter (ver ia_asistente.listar_modelos_gratuitos),
    usado tanto por el <select> de /ia/ajustes como por el datalist de
    proveedor=openrouter en /historial (informes)."""
    proveedor = request.args.get("proveedor", "openrouter")
    if proveedor == "openrouter":
        return jsonify(asistente.listar_modelos_gratuitos())
    try:
        prov = ia_proveedores.obtener(proveedor)
    except ValueError:
        abort(404)
    claves = ia_claves.de_usuario(proveedor, g.usuario_id) or (ia_claves.de_despacho(proveedor, g.tenant_id) if g.tenant_id else [])
    if prov.pide_clave and not claves:
        return jsonify({"modelos": [], "sugeridos": list(prov.modelos_sugeridos), "error": _("Añade antes una clave de este proveedor para poder listar sus modelos.")})
    try:
        return jsonify({"modelos": ia_proveedores.listar_modelos(proveedor, claves[0] if claves else "", _url_del_despacho(proveedor)), "sugeridos": list(prov.modelos_sugeridos)})
    except ErrorIA as e:
        return jsonify({"modelos": [], "sugeridos": list(prov.modelos_sugeridos), "error": _(str(e))[:200]})


def _url_del_despacho(proveedor: str) -> str | None:
    if not g.tenant_id:
        return None
    return next((p["url_base"] for p in ia_despacho.listar(g.tenant_id) if p["id"] == proveedor and p["url_base"]), None)


@ia_bp.route("/ajustes")
@login_required
def ajustes():
    preferencias = db.obtener_preferencias_ia(g.usuario_id)
    proveedor = preferencias["proveedor_ia"] if "proveedor_ia" in preferencias.keys() else "openrouter"
    direccion = bool(g.tenant_id) and ia_despacho.es_direccion(g.usuario_id)
    return render_template(
        "ia_ajustes.html",
        preferencias=preferencias,
        proveedor_elegido=proveedor,
        proveedores=[ia_proveedores.obtener(p) for p in ia_proveedores.ORDEN if ia_despacho.permitido(g.tenant_id, p) or p == proveedor],
        claves_propias={p: len(ia_claves.de_usuario(p, g.usuario_id)) for p in ia_proveedores.ORDEN},
        modelos_sugeridos=asistente.listar_modelos_gratuitos(),
        num_claves_configuradas=len(asistente.obtener_api_keys(g.usuario_id)),
        atajos_propios=db.listar_atajos_ia(g.usuario_id),
        consumo=ia_consumo.estado(g.tenant_id) if g.tenant_id else None,
        despacho=ia_despacho.listar(g.tenant_id) if g.tenant_id else [],
        normas=ia_despacho.config(g.tenant_id) if g.tenant_id else None, ocr_disponible=ocr_local.disponible(),
        uso=ia_uso.resumen(g.tenant_id) if g.tenant_id else None,
        es_direccion=direccion,
        error=request.args.get("error"),
        aviso=request.args.get("aviso"),
    )


def _exigir_direccion() -> None:
    if not g.tenant_id or not ia_despacho.es_direccion(g.usuario_id):
        abort(403)


def _lineas(texto: str) -> list[str]:
    return [c.strip() for c in (texto or "").splitlines() if c.strip()]


@ia_bp.route("/ajustes/despacho/<proveedor>", methods=["POST"])
@login_required
def guardar_proveedor_despacho(proveedor: str):
    """La dirección activa un proveedor para todo el despacho: modelo del asistente y de las facturas, dirección propia (Ollama) y claves compartidas."""
    _exigir_direccion()
    try:
        ia_proveedores.obtener(proveedor)
    except ValueError:
        abort(404)
    try:
        ia_despacho.guardar(g.tenant_id, proveedor, activo=request.form.get("activo") == "on", modelo_asistente=request.form.get("modelo_asistente", ""),
                            modelo_facturas=request.form.get("modelo_facturas", ""), url_base=request.form.get("url_base", ""), claves_nuevas=_lineas(request.form.get("claves", "")),
                            borrar_claves=request.form.get("borrar_claves") == "on", por=g.usuario_id)
    except ValueError as e:
        return redirect(url_for("ia.ajustes", error=_(str(e))) + f"#proveedor-{proveedor}")
    from . import auditoria
    auditoria.registrar(g.tenant_id, g.usuario_id, "ia.proveedor_despacho", "ia_proveedor", None, {"proveedor": proveedor, "activo": request.form.get("activo") == "on"})
    return redirect(url_for("ia.ajustes", aviso=_("Guardado.")) + f"#proveedor-{proveedor}")


@ia_bp.route("/ajustes/despacho/<proveedor>/mover/<sentido>", methods=["POST"])
@login_required
def mover_proveedor_despacho(proveedor: str, sentido: str):
    _exigir_direccion()
    if sentido not in ("arriba", "abajo"):
        abort(404)
    ia_despacho.mover(g.tenant_id, proveedor, arriba=(sentido == "arriba"))
    return redirect(url_for("ia.ajustes") + f"#proveedor-{proveedor}")


@ia_bp.route("/ajustes/despacho/voz", methods=["POST"])
@login_required
def guardar_voz_despacho():
    _exigir_direccion()
    ia_despacho.guardar_voz(g.tenant_id, request.form.get("voz", ""), por=g.usuario_id)
    from . import auditoria
    auditoria.registrar(g.tenant_id, g.usuario_id, "ia.voz_despacho", "ia_config", None, {})
    return redirect(url_for("ia.ajustes", guardado="voz") + "#voz")


@ia_bp.route("/ajustes/despacho/normas", methods=["POST"])
@login_required
def guardar_normas_despacho():
    _exigir_direccion()
    try:
        ia_despacho.guardar_config(g.tenant_id, solo_ue=request.form.get("solo_ue") == "on", claves_personales=request.form.get("claves_personales") == "on",
                                   facturas_modo=request.form.get("facturas_modo", "compartida"), umbral_confianza=request.form.get("umbral_confianza", 90),
                                   lectura_texto=request.form.get("lectura_texto") == "on", separar_pdf=request.form.get("separar_pdf") == "on", ocr_local=request.form.get("ocr_local", "respaldo"), segunda_lectura=request.form.get("segunda_lectura") == "on", por=g.usuario_id)
    except ValueError as e:
        return redirect(url_for("ia.ajustes", error=_(str(e))) + "#normas")
    from . import auditoria
    auditoria.registrar(g.tenant_id, g.usuario_id, "ia.normas_despacho", "ia_config", None, {})
    return redirect(url_for("ia.ajustes", aviso=_("Guardado.")) + "#normas")


@ia_bp.route("/ajustes/probar", methods=["POST"])
@login_required
def probar_clave():
    """Comprueba una clave y un modelo con una consulta mínima (no cuenta en el límite de IA). Usa la clave escrita en el formulario o, si está vacía, la guardada (`ambito` = usuario o despacho)."""
    proveedor, modelo = request.form.get("proveedor", ""), request.form.get("modelo", "").strip()
    ambito = request.form.get("ambito", "usuario")
    try:
        prov = ia_proveedores.obtener(proveedor)
        url = ia_proveedores.url_valida(request.form.get("url_base", "")) if request.form.get("url_base", "").strip() else _url_del_despacho(proveedor)
    except ValueError as e:
        return jsonify({"ok": False, "error": _(str(e))})
    if ambito == "despacho":
        _exigir_direccion()
    if not ia_despacho.permitido(g.tenant_id, proveedor):
        return jsonify({"ok": False, "error": _("El despacho no admite este proveedor (solo UE o tu propia red).")})
    escritas = _lineas(request.form.get("clave", ""))
    guardadas = ia_claves.de_despacho(proveedor, g.tenant_id) if ambito == "despacho" and g.tenant_id else (asistente.obtener_api_keys(g.usuario_id) if proveedor == "openrouter" else ia_claves.de_usuario(proveedor, g.usuario_id))
    clave = (escritas or guardadas or [""])[0]
    if prov.pide_clave and not clave:
        return jsonify({"ok": False, "error": _("No hay ninguna clave que probar.")})
    if not modelo:
        return jsonify({"ok": False, "error": _("Indica un modelo para probar.")})
    motivo = ia_proveedores.probar(proveedor, modelo, clave, url)
    return jsonify({"ok": not motivo, "error": _(motivo) if motivo else "", "mensaje": _("Funciona: la clave y el modelo responden.") if not motivo else ""})


@ia_bp.route("/ajustes/atajos", methods=["POST"])
@login_required
def crear_atajo():
    try:
        db.crear_atajo_ia(g.usuario_id, request.form.get("titulo", ""), request.form.get("prompt", ""))
    except ValueError as e:
        return redirect(url_for("ia.ajustes", error=_(str(e))))
    return redirect(url_for("ia.ajustes"))


@ia_bp.route("/ajustes/atajos/<int:atajo_id>/eliminar", methods=["POST"])
@login_required
def eliminar_atajo(atajo_id: int):
    db.eliminar_atajo_ia(g.usuario_id, atajo_id)
    return redirect(url_for("ia.ajustes"))


@ia_bp.route("/ajustes", methods=["POST"])
@login_required
def guardar_ajustes():
    modelo = request.form.get("modelo", "").strip()
    if not modelo:
        modelo = request.form.get("modelo_personalizado", "").strip()
    proveedor = request.form.get("proveedor", "openrouter")
    try:
        ia_proveedores.obtener(proveedor)
    except ValueError:
        return redirect(url_for("ia.ajustes", error=_("Proveedor de IA no válido.")))
    if not ia_despacho.permitido(g.tenant_id, proveedor):
        return redirect(url_for("ia.ajustes", error=_("El despacho solo admite proveedores de la UE o de tu propia red: este manda los datos fuera.")))
    if g.tenant_id and not ia_despacho.config(g.tenant_id)["claves_personales"] and (_lineas(request.form.get("api_keys", "")) or proveedor != "openrouter"):
        return redirect(url_for("ia.ajustes", error=_("La dirección del despacho no permite claves personales: se usan las del despacho.")))
    db.guardar_preferencias_ia(
        g.usuario_id,
        modelo=modelo,
        modo_autonomo=request.form.get("modo_autonomo") == "on",
        solo_lectura=request.form.get("solo_lectura") == "on",
    )
    db.guardar_proveedor_ia(g.usuario_id, proveedor)

    nuevas_claves = request.form.get("api_keys", "").splitlines()
    if any(c.strip() for c in nuevas_claves):
        if proveedor == "openrouter":
            asistente.guardar_api_keys(g.usuario_id, nuevas_claves)
        else:
            ia_claves.guardar_de_usuario(proveedor, g.usuario_id, nuevas_claves)
    if request.form.get("borrar_api_keys") == "on":
        if proveedor == "openrouter":
            asistente.borrar_api_key(g.usuario_id)
        else:
            ia_claves.borrar_de_usuario(proveedor, g.usuario_id)

    return redirect(url_for("ia.ajustes", aviso=_("Guardado.")))
