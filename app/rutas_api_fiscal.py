"""API fiscal completa: expediente documental del cliente, vencimientos (alta, detalle, propuestas, generación masiva), documentos y mensajes
con el cliente por vencimiento, constancia y justificante, recordatorios del portal, registro de accesos (RGPD), resumen y papelera.
Capa fina sobre las mismas funciones de `db.py` y las mismas reglas que la web (`rutas_fiscal.py`): mismos permisos por despacho, mismo
registro de accesos al expediente y los mismos avisos por correo. Área de token: `fiscal`. Todo aditivo."""
from datetime import date

from flask import Response, abort, g, request

from . import db, nextcloud, notificaciones_email
from .auth import token_required
from .rutas_api import _body, _dict, _dicts, _err, _exigir_tenant_api, _ok, _ok_paginado, api_bp
from .vencimientos_fiscales import MODELOS_POR_PAIS, generar_vencimientos_propuestos, modelos_disponibles as modelos_disponibles_para_pais

# Tipos que un navegador interpretaría como página: se sirven siempre como descarga genérica (igual que la web).
_TIPOS_PELIGROSOS = ("text/html", "application/xhtml+xml", "image/svg+xml", "text/xml", "application/xml", "text/javascript")
ESTADOS_VENCIMIENTO = ("pendiente", "presentado", "fuera_plazo")


def _con_despacho(vista):
    """Todas las rutas fiscales exigen un despacho; las respuestas de error son las de siempre."""
    from functools import wraps

    @wraps(vista)
    def envuelta(*a, **k):
        error = _exigir_tenant_api()
        return error if error else vista(*a, **k)
    return envuelta


def _cliente_o_404(cliente_id: int):
    cliente = db.obtener_cliente_fiscal(g.tenant_id, cliente_id)
    if cliente is None:
        abort(404, "Cliente fiscal no encontrado.")
    return cliente


def _vencimiento_o_404(vencimiento_id: int):
    v = db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id)
    if v is None:
        abort(404, "Vencimiento no encontrado.")
    return v


def _descarga(contenido: bytes, tipo_mime: str, nombre: str) -> Response:
    tipo = (tipo_mime or "application/octet-stream").lower().split(";")[0]
    r = Response(bytes(contenido), mimetype="application/octet-stream" if tipo in _TIPOS_PELIGROSOS else tipo)
    r.headers.set("Content-Disposition", "attachment", filename=nombre)
    r.headers.set("X-Content-Type-Options", "nosniff")
    return r


# --- Cliente: resumen, accesos y expediente documental -------------------------------------------------------------------

@api_bp.route("/fiscal/clientes/<int:cliente_id>/resumen", methods=["GET"])
@token_required
@_con_despacho
def resumen_cliente(cliente_id: int):
    """Vista ligera: modelos, vencimientos pendientes y los próximos."""
    cliente = _cliente_o_404(cliente_id)
    pendientes = db.listar_vencimientos_fiscales(g.tenant_id, cliente_fiscal_id=cliente_id, estado="pendiente")
    return _ok({
        "id": cliente["id"], "nombre": cliente["nombre"], "nif": cliente["nif"], "pais": cliente["pais"], "email": cliente["email"],
        "modelos": db.modelos_fiscales_de_cliente(cliente), "generacion_automatica": bool(cliente["generacion_automatica"]),
        "vencimientos_pendientes": len(pendientes), "proximos": _dicts(pendientes[:5]),
    })


@api_bp.route("/fiscal/clientes/<int:cliente_id>/accesos", methods=["GET"])
@token_required
@_con_despacho
def accesos_cliente(cliente_id: int):
    """Registro de quién ha visto o tocado el expediente (auditoría y RGPD). Solo supervisores del despacho. `limit` hasta 5000."""
    _cliente_o_404(cliente_id)
    if not db.es_supervisor_tenant(g.usuario_id):
        abort(403, "Solo un supervisor del despacho puede ver el registro de accesos.")
    limite = max(1, min(request.args.get("limit", default=200, type=int) or 200, 5000))
    return _ok(db.listar_accesos_cliente(g.tenant_id, cliente_id, limite))


@api_bp.route("/fiscal/clientes/<int:cliente_id>/documentos", methods=["GET"])
@token_required
@_con_despacho
def listar_documentos_cliente(cliente_id: int):
    """Expediente del cliente (metadatos, sin contenido)."""
    _cliente_o_404(cliente_id)
    return _ok_paginado(db.listar_documentos_cliente(g.tenant_id, cliente_id))


@api_bp.route("/fiscal/clientes/<int:cliente_id>/documentos", methods=["POST"])
@token_required
@_con_despacho
def subir_documentos_cliente(cliente_id: int):
    """Multipart: uno o varios `archivo` (hasta 10, 15 MB cada uno) y `categoria` opcional
    (Extractos, Facturas emitidas, Facturas recibidas, Modelos presentados, Contratos, Otros). Devuelve el resultado por archivo
    (`ok`, `duplicado`, `grande`, `vacio`, `limite`)."""
    _cliente_o_404(cliente_id)
    archivos = [a for a in request.files.getlist("archivo")[:10] if a and a.filename]
    if not archivos:
        return _err("Adjunta al menos un archivo en el campo «archivo» (multipart).", 400, "sin_archivos", "archivo")
    resultados = []
    for archivo in archivos:
        resultado, documento_id = db.archivar_documento_cliente(
            g.usuario_id, cliente_id, archivo.filename, archivo.mimetype, archivo.read(db.MAX_DOCUMENTO_CLIENTE_BYTES + 1), categoria=request.form.get("categoria"),
        )
        if resultado == "ok":
            db.registrar_acceso_cliente(g.tenant_id, cliente_id, g.usuario_id, "documento_subido", f"{archivo.filename} (vía API)")
        resultados.append({"archivo": archivo.filename, "resultado": resultado, "id": documento_id})
    return _ok(resultados, 201 if any(r["resultado"] == "ok" for r in resultados) else 200)


@api_bp.route("/fiscal/clientes/<int:cliente_id>/documentos/<int:documento_id>", methods=["GET"])
@token_required
@_con_despacho
def descargar_documento_cliente(cliente_id: int, documento_id: int):
    documento = db.obtener_documento_cliente(g.tenant_id, cliente_id, documento_id)
    if documento is None:
        abort(404, "Documento no encontrado.")
    db.registrar_acceso_cliente(g.tenant_id, cliente_id, g.usuario_id, "documento_descargado", f"{documento['nombre_archivo']} (vía API)")
    return _descarga(documento["contenido"], documento["tipo_mime"], documento["nombre_archivo"])


@api_bp.route("/fiscal/clientes/<int:cliente_id>/documentos/<int:documento_id>", methods=["DELETE"])
@token_required
@_con_despacho
def eliminar_documento_cliente(cliente_id: int, documento_id: int):
    previo = db.obtener_documento_cliente(g.tenant_id, cliente_id, documento_id)
    if not db.eliminar_documento_cliente(g.usuario_id, cliente_id, documento_id):
        abort(404, "Documento no encontrado.")
    db.registrar_acceso_cliente(g.tenant_id, cliente_id, g.usuario_id, "documento_eliminado", f"{previo['nombre_archivo'] if previo else ''} (vía API)")
    return _ok()


# --- Vencimientos: propuestas, alta, detalle y generación masiva ---------------------------------------------------------

@api_bp.route("/fiscal/modelos", methods=["GET"])
@token_required
def modelos_fiscales_disponibles():
    """Modelos fiscales por país (`pais`, por defecto el de tus clientes: ES)."""
    pais = request.args.get("pais") or "ES"
    return _ok({"pais": pais, "paises": sorted(MODELOS_POR_PAIS), "modelos": modelos_disponibles_para_pais(pais)})


@api_bp.route("/fiscal/vencimientos/propuestas", methods=["GET"])
@token_required
@_con_despacho
def propuestas_vencimientos():
    """Vista previa, sin crear nada: `cliente_id` (obligatorio), `modelos` (separados por comas; por defecto los del cliente), `anio`."""
    cliente = _cliente_o_404(request.args.get("cliente_id", type=int) or 0)
    modelos = [m for m in (request.args.get("modelos") or "").split(",") if m] or db.modelos_fiscales_de_cliente(cliente)
    anio = request.args.get("anio", type=int) or date.today().year
    propuestas = generar_vencimientos_propuestos(modelos, anio, pais=cliente["pais"])
    return _ok([{**p, "ya_existe": db.vencimiento_fiscal_existente(g.tenant_id, cliente["id"], p["modelo"], p["periodo"]) is not None} for p in propuestas])


@api_bp.route("/fiscal/vencimientos/generar-masivo", methods=["POST"])
@token_required
@_con_despacho
def generar_vencimientos_masivo():
    """Genera los vencimientos del año (`anio`, por defecto el actual) de TODOS los clientes que tienen modelos definidos, sin duplicar."""
    anio = _body().get("anio") or date.today().year
    if not isinstance(anio, int) or not 2000 <= anio <= 2100:
        return _err("anio debe ser un año válido.", 400, "peticion_invalida", "anio")
    creados = omitidos = 0
    for cliente in db.listar_clientes_fiscales(g.tenant_id):
        modelos = db.modelos_fiscales_de_cliente(cliente)
        for p in (generar_vencimientos_propuestos(modelos, anio, pais=cliente["pais"]) if modelos else []):
            if db.vencimiento_fiscal_existente(g.tenant_id, cliente["id"], p["modelo"], p["periodo"]) is not None:
                omitidos += 1
                continue
            db.crear_vencimiento_fiscal(g.tenant_id, cliente["id"], p["modelo"], p["periodo"], p["fecha_limite"])
            creados += 1
    return _ok({"creados": creados, "omitidos": omitidos, "anio": anio}, 201)


@api_bp.route("/fiscal/vencimientos", methods=["POST"])
@token_required
@_con_despacho
def crear_vencimiento():
    """Alta de un vencimiento a mano: `cliente_id`, `modelo`, `periodo`, `fecha_limite` (YYYY-MM-DD); opcionales `usuario_id` (responsable) y `notas`.
    409 `vencimiento_duplicado` si ese cliente ya tiene ese modelo y periodo."""
    d = _body()
    cliente = _cliente_o_404(int(d["cliente_id"]) if str(d.get("cliente_id") or "").isdigit() else 0)
    modelo, periodo, fecha = (str(d.get(k) or "").strip() for k in ("modelo", "periodo", "fecha_limite"))
    if not modelo or not periodo:
        return _err("modelo y periodo son obligatorios.", 400, "peticion_invalida", "modelo")
    try:
        date.fromisoformat(fecha[:10])
    except ValueError:
        return _err("fecha_limite debe ser YYYY-MM-DD.", 400, "peticion_invalida", "fecha_limite")
    responsable = d.get("usuario_id")
    if responsable is not None and responsable not in db.usuarios_de_tenant(g.tenant_id):
        return _err("El responsable no es de tu despacho.", 400, "peticion_invalida", "usuario_id")
    existente = db.vencimiento_fiscal_existente(g.tenant_id, cliente["id"], modelo, periodo)
    if existente is not None:
        return _err(f"Ese cliente ya tiene el modelo {modelo} del periodo {periodo} (id {existente}).", 409, "vencimiento_duplicado")
    vencimiento_id = db.crear_vencimiento_fiscal(g.tenant_id, cliente["id"], modelo, periodo, fecha[:10], usuario_id=responsable, notas=d.get("notas"))
    return _ok(_dict(db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id)), 201)


@api_bp.route("/fiscal/vencimientos/<int:vencimiento_id>", methods=["GET"])
@token_required
@_con_despacho
def obtener_vencimiento(vencimiento_id: int):
    """Detalle con el estado de lo que tiene dentro: documentos, mensajes sin leer del cliente y si tiene constancia o justificante."""
    v = _dict(_vencimiento_o_404(vencimiento_id))
    docs = db.listar_documentos_vencimiento(vencimiento_id)
    v["documentos"] = len(docs)
    v["tiene_constancia"] = any(d["origen"] == "constancia" for d in docs)
    v["tiene_justificante"] = any(d["origen"] == "justificante" for d in docs)
    v["mensajes"] = len(db.listar_mensajes_vencimiento(vencimiento_id))
    return _ok(v)


# --- Documentos, constancia y justificante del vencimiento -----------------------------------------------------------------

@api_bp.route("/fiscal/vencimientos/<int:vencimiento_id>/documentos", methods=["GET"])
@token_required
@_con_despacho
def listar_documentos_vencimiento(vencimiento_id: int):
    """Lo que ha subido el cliente desde el portal (`origen: cliente`), la constancia (`constancia`) y el justificante oficial (`justificante`)."""
    _vencimiento_o_404(vencimiento_id)
    return _ok_paginado(db.listar_documentos_vencimiento(vencimiento_id))


@api_bp.route("/fiscal/vencimientos/<int:vencimiento_id>/documentos/<int:documento_id>", methods=["GET"])
@token_required
@_con_despacho
def descargar_documento_vencimiento(vencimiento_id: int, documento_id: int):
    v = _vencimiento_o_404(vencimiento_id)
    documento = db.obtener_documento_vencimiento(documento_id)
    if documento is None or documento["vencimiento_id"] != vencimiento_id:
        abort(404, "Documento no encontrado.")
    try:
        contenido = db.contenido_documento_vencimiento(documento)
    except nextcloud.ErrorNextcloud:
        return _err("El almacén de documentos no responde ahora mismo. Inténtalo en unos minutos.", 503, "almacen_no_disponible")
    db.registrar_acceso_cliente(g.tenant_id, v["cliente_fiscal_id"], g.usuario_id, "vencimiento_documento_descargado", f"{documento['nombre_archivo']} (vía API)")
    return _descarga(contenido, documento["tipo_mime"], documento["nombre_archivo"])


@api_bp.route("/fiscal/vencimientos/<int:vencimiento_id>/justificante", methods=["POST"])
@token_required
@_con_despacho
def subir_justificante(vencimiento_id: int):
    """Multipart, campo `justificante`: imagen o PDF de hasta 8 MB. Visible para el cliente en su portal. Si ya estaba presentado, actualiza la constancia."""
    v = _vencimiento_o_404(vencimiento_id)
    from .rutas_fiscal import _generar_constancia, _guardar_justificante
    if not _guardar_justificante(vencimiento_id, request.files.get("justificante")):
        return _err("Archivo no válido: solo imágenes o PDF, hasta 8 MB.", 400, "justificante_invalido", "justificante")
    if v["estado"] == "presentado" and db.listar_documentos_vencimiento(vencimiento_id, origen="constancia"):
        _generar_constancia(v)
    return _ok({"subido": True}, 201)


@api_bp.route("/fiscal/vencimientos/<int:vencimiento_id>/constancia", methods=["POST"])
@token_required
@_con_despacho
def regenerar_constancia(vencimiento_id: int):
    """(Re)genera la constancia de presentación en PDF (no sustituye al justificante oficial)."""
    v = _vencimiento_o_404(vencimiento_id)
    from .rutas_fiscal import _generar_constancia
    _generar_constancia(v)
    return _ok({"generada": True}, 201)


# --- Mensajes con el cliente (portal) ---------------------------------------------------------------------------------------

@api_bp.route("/fiscal/vencimientos/<int:vencimiento_id>/mensajes", methods=["GET"])
@token_required
@_con_despacho
def listar_mensajes_vencimiento(vencimiento_id: int):
    """Conversación con el cliente sobre este vencimiento (`autor`: `cliente` | `empleado`)."""
    _vencimiento_o_404(vencimiento_id)
    return _ok(_dicts(db.listar_mensajes_vencimiento(vencimiento_id)))


@api_bp.route("/fiscal/vencimientos/<int:vencimiento_id>/mensajes", methods=["POST"])
@token_required
@_con_despacho
def responder_mensaje_vencimiento(vencimiento_id: int):
    """Cuerpo: `{"texto": "..."}`. Se guarda como mensaje del equipo y se avisa al cliente por correo, como en la web."""
    v = _vencimiento_o_404(vencimiento_id)
    texto = (_body().get("texto") or "").strip()
    if not texto:
        return _err("El mensaje no puede estar vacío.", 400, "mensaje_vacio", "texto")
    db.crear_mensaje_vencimiento(vencimiento_id, "empleado", texto, usuario_id=g.usuario_id)
    db.marcar_mensajes_leidos(vencimiento_id, "empleado")
    cliente = db.obtener_cliente_fiscal(g.tenant_id, v["cliente_fiscal_id"])
    avisado = False
    if cliente is not None and cliente["email"]:
        from flask import url_for
        try:
            notificaciones_email.enviar_respuesta_portal(cliente["email"], texto, url_for("portal_cliente.entrar", _external=True))
            avisado = True
        except notificaciones_email.ErrorNotificacionesEmail:
            pass
    return _ok({"mensajes": _dicts(db.listar_mensajes_vencimiento(vencimiento_id)), "cliente_avisado_por_correo": avisado}, 201)


# --- Recordatorios al cliente (portal) ---------------------------------------------------------------------------------------

@api_bp.route("/fiscal/recordatorios", methods=["GET"])
@token_required
@_con_despacho
def config_recordatorios():
    """Cuándo y cómo se recuerda a los clientes sus vencimientos: días de aviso antes/después, aviso al equipo y texto propio con
    marcas (`marcas`)."""
    return _ok({**db.obtener_config_recordatorios(g.tenant_id), "marcas": notificaciones_email.MARCAS_PLANTILLA, "smtp_configurado": notificaciones_email.configurado(),
                "max_avisos_antes": db.MAX_AVISOS_ANTES, "max_avisos_despues": db.MAX_AVISOS_DESPUES})


@api_bp.route("/fiscal/recordatorios", methods=["PUT"])
@token_required
@_con_despacho
def guardar_config_recordatorios():
    """Cuerpo: `dias_antes` (lista, 0-60), `dias_despues` (lista, 1-30), `avisar_equipo`, `asunto` y `cuerpo` (los dos juntos o vacíos)."""
    d = _body()
    actual = db.obtener_config_recordatorios(g.tenant_id)
    try:
        config = db.guardar_config_recordatorios(
            g.tenant_id, d.get("dias_antes", actual["dias_antes"]), d.get("dias_despues", actual["dias_despues"]),
            bool(d.get("avisar_equipo", actual["avisar_equipo"])), d.get("asunto", actual["asunto"]), d.get("cuerpo", actual["cuerpo"]),
        )
    except ValueError as e:
        return _err(str(e), 400, "recordatorios_invalidos")
    return _ok(config)


# --- Papelera fiscal -----------------------------------------------------------------------------------------------------

@api_bp.route("/fiscal/papelera", methods=["GET"])
@token_required
@_con_despacho
def papelera_fiscal():
    """Clientes y vencimientos borrados (recuperables)."""
    return _ok_paginado(db.papelera_fiscal(g.tenant_id))


@api_bp.route("/fiscal/papelera/<tipo>/<int:item_id>/restaurar", methods=["POST"])
@token_required
@_con_despacho
def restaurar_papelera_fiscal(tipo: str, item_id: int):
    """`tipo`: `cliente_fiscal` | `vencimiento_fiscal`."""
    if tipo == "cliente_fiscal":
        db.restaurar_cliente_fiscal(g.tenant_id, item_id)
        db.registrar_acceso_cliente(g.tenant_id, item_id, g.usuario_id, "cliente_editado", "restaurado de la papelera (vía API)")
    elif tipo == "vencimiento_fiscal":
        db.restaurar_vencimiento_fiscal(g.tenant_id, item_id)
    else:
        abort(404, "Tipo de elemento desconocido.")
    return _ok()
