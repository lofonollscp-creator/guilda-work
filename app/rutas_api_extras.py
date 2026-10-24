"""API: adjuntos de notas, envíos programados y plantillas de correo, y administración del fichaje (registro horario).
Misma capa fina sobre `db.py`/`correo.py`/`fichaje_export.py` que la web, con sus mismos permisos. Todo aditivo."""
from datetime import datetime

from flask import Response, abort, g, request

from . import correo, db, fichaje_export
from .auth import token_required
from .rutas_api import _body, _dict, _dicts, _err, _ok, _ok_paginado, api_bp
from . import rutas_api_hoy  # noqa: F401 -- registra GET /hoy en api_bp


# --- Adjuntos de notas --------------------------------------------------------------------------------------------------

def _nota_o_404(nota_id: int):
    nota = db.obtener_nota(g.usuario_id, nota_id)
    if nota is None:
        abort(404, "Nota no encontrada.")
    return nota


@api_bp.route("/notas/<int:nota_id>/adjuntos", methods=["GET"])
@token_required
def listar_adjuntos_nota(nota_id: int):
    """Adjuntos de la nota (metadatos, sin el contenido)."""
    _nota_o_404(nota_id)
    return _ok(_dicts(db.listar_adjuntos_nota(nota_id)))


@api_bp.route("/notas/<int:nota_id>/adjuntos", methods=["POST"])
@token_required
def subir_adjuntos_nota(nota_id: int):
    """Multipart, uno o varios `adjunto`. Imágenes (png, jpeg, gif, webp), PDF, texto y CSV; 5 MB cada uno y 5 por nota.
    Devuelve el resultado por archivo (los válidos quedan adjuntos aunque otro falle)."""
    _nota_o_404(nota_id)
    archivos = [f for f in request.files.getlist("adjunto") if f and f.filename]
    if not archivos:
        return _err("Adjunta al menos un archivo en el campo «adjunto» (multipart).", 400, "sin_archivos", "adjunto")
    resultados = []
    for f in archivos:
        try:
            adjunto_id = db.agregar_adjunto_nota(g.usuario_id, nota_id, f.filename, f.mimetype, f.read(db.NOTAS_ADJUNTOS_TAMANO_MAXIMO + 1))
            resultados.append({"archivo": f.filename, "ok": True, "id": adjunto_id})
        except ValueError as e:
            resultados.append({"archivo": f.filename, "ok": False, "error": str(e)})
    return _ok(resultados, 201 if any(r["ok"] for r in resultados) else 400)


@api_bp.route("/notas/adjuntos/<int:adjunto_id>", methods=["GET"])
@token_required
def descargar_adjunto_nota(adjunto_id: int):
    """Descarga el archivo (`?ver=1` lo muestra en línea si es una imagen)."""
    adjunto = db.obtener_adjunto_nota(g.usuario_id, adjunto_id)
    if adjunto is None:
        abort(404, "Adjunto no encontrado.")
    en_linea = request.args.get("ver") == "1" and adjunto["tipo_mime"].startswith("image/")
    r = Response(adjunto["contenido"], mimetype=adjunto["tipo_mime"])
    r.headers["Content-Disposition"] = f'{"inline" if en_linea else "attachment"}; filename="{adjunto["nombre"].replace(chr(34), "")}"'
    r.headers["X-Content-Type-Options"] = "nosniff"
    return r


@api_bp.route("/notas/adjuntos/<int:adjunto_id>", methods=["DELETE"])
@token_required
def eliminar_adjunto_nota(adjunto_id: int):
    if not db.eliminar_adjunto_nota(g.usuario_id, adjunto_id):
        abort(404, "Adjunto no encontrado.")
    return _ok()


# --- Envíos programados -------------------------------------------------------------------------------------------------

def _envio_publico(f) -> dict:
    return {k: f[k] for k in ("id", "cuenta_id", "destinatarios", "cc", "asunto", "estado", "enviar_en", "programado", "procesado_en", "error") if k in f.keys()}


@api_bp.route("/correo/envios/<int:envio_id>", methods=["GET"])
@token_required
def estado_envio(envio_id: int):
    """Estado de un envío (`pendiente`, `enviado`, `cancelado`, `error`...)."""
    envio = db.obtener_envio_correo(g.usuario_id, envio_id)
    if envio is None:
        abort(404, "Envío no encontrado.")
    return _ok(_envio_publico(envio))


@api_bp.route("/correo/envios/<int:envio_id>/cancelar", methods=["POST"])
@token_required
def cancelar_envio(envio_id: int):
    """Cancela un envío programado que aún no ha salido (409 si ya se envió). Con `{"como_borrador": true}` el correo se conserva
    como borrador en la web (devuelve `borrador_id`); si no, se descarta con sus adjuntos."""
    envio = db.obtener_envio_correo(g.usuario_id, envio_id)
    if envio is None:
        abort(404, "Envío no encontrado.")
    if not db.cancelar_envio_correo(g.usuario_id, envio_id):
        return _err("Ya no se puede cancelar: el correo ya se ha enviado o se está enviando.", 409, "envio_no_cancelable")
    borrador_id = correo.borrador_desde_envio(envio) if _body().get("como_borrador") else None
    db.cerrar_envio_correo(envio_id, "cancelado", borrar_adjuntos=True)
    return _ok({"cancelado": True, "borrador_id": borrador_id})


# --- Plantillas de correo -------------------------------------------------------------------------------------------------

@api_bp.route("/correo/plantillas/variables", methods=["GET"])
@token_required
def variables_plantilla():
    """Variables `{{...}}` que se pueden usar en una plantilla."""
    return _ok([{"nombre": n, "descripcion": d} for n, d in correo.VARIABLES_PLANTILLA])


def _plantilla_o_404(plantilla_id: int):
    p = correo.obtener_plantilla(g.usuario_id, plantilla_id)
    if p is None:
        abort(404, "Plantilla no encontrada.")
    return p


@api_bp.route("/correo/plantillas/<int:plantilla_id>", methods=["GET"])
@token_required
def obtener_plantilla(plantilla_id: int):
    """La plantilla. Con `?cliente_fiscal_id=` (de tu despacho) devuelve además `renderizada`: asunto y cuerpo con las variables
    rellenadas y `sin_resolver` (las que no se pudieron resolver)."""
    p = _plantilla_o_404(plantilla_id)
    datos = _dict(p)
    cliente_id = request.args.get("cliente_fiscal_id", type=int)
    if cliente_id is not None:
        valores = correo.contexto_plantilla(g.usuario_id, cliente_id, p["modelo"])
        asunto, falta_a = correo.rellenar_plantilla(p["asunto"], valores)
        cuerpo, falta_c = correo.rellenar_plantilla(p["cuerpo"], valores, html=True)
        datos["renderizada"] = {"asunto": asunto, "cuerpo": cuerpo, "sin_resolver": sorted(set(falta_a + falta_c))}
    return _ok(datos)


def _datos_plantilla(parcial: dict | None = None):
    d = {**(parcial or {}), **_body()}
    return str(d.get("nombre") or ""), d.get("asunto"), str(d.get("cuerpo") or ""), d.get("modelo")


@api_bp.route("/correo/plantillas", methods=["POST"])
@token_required
def crear_plantilla():
    """Cuerpo: `nombre`, `asunto` (opcional), `cuerpo` (HTML, admite `{{variables}}`), `modelo` (opcional, p. ej. 303: usa el próximo vencimiento de ese modelo)."""
    try:
        plantilla_id = correo.crear_plantilla(g.usuario_id, *_datos_plantilla())
    except correo.ErrorCorreo as e:
        return _err(str(e), 400, "plantilla_invalida")
    return _ok(_dict(correo.obtener_plantilla(g.usuario_id, plantilla_id)), 201)


@api_bp.route("/correo/plantillas/<int:plantilla_id>", methods=["PUT"])
@token_required
def editar_plantilla(plantilla_id: int):
    """Cambia cualquier subconjunto de `nombre`, `asunto`, `cuerpo` y `modelo`."""
    actual = _plantilla_o_404(plantilla_id)
    try:
        correo.editar_plantilla(g.usuario_id, plantilla_id, *_datos_plantilla(dict(actual)))
    except correo.ErrorCorreo as e:
        return _err(str(e), 400, "plantilla_invalida")
    return _ok(_dict(correo.obtener_plantilla(g.usuario_id, plantilla_id)))


@api_bp.route("/correo/plantillas/<int:plantilla_id>", methods=["DELETE"])
@token_required
def eliminar_plantilla(plantilla_id: int):
    _plantilla_o_404(plantilla_id)
    correo.eliminar_plantilla(g.usuario_id, plantilla_id)
    return _ok()


# --- Fichaje: administración -------------------------------------------------------------------------------------------------

TIPOS_FICHAJE = ("entrada", "pausa_inicio", "pausa_fin", "salida")


def _puede_administrar(tenant_id: int | None) -> bool:
    return bool(g.es_admin or (g.gestor_fichajes and g.tenant_id is not None and g.tenant_id == tenant_id))


def _tenant_admin() -> int:
    """Despacho que se administra: el propio para un gestor de fichajes; un administrador global elige con `tenant_id`."""
    tenant_id = request.args.get("tenant_id", type=int) if g.es_admin else g.tenant_id
    if tenant_id is None:
        if g.es_admin:
            abort(400, "Indica tenant_id: qué despacho quieres administrar.")
        abort(403, "No eres gestor de fichajes de ningún despacho.")
    if not _puede_administrar(tenant_id):
        abort(403, "No tienes permiso para administrar el fichaje de ese despacho.")
    if db.obtener_tenant(tenant_id) is None:
        abort(404, "Despacho no encontrado.")
    return tenant_id


def _trabajador_administrable(usuario_id: int):
    t = db.obtener_usuario(usuario_id)
    if t is None or not _puede_administrar(t["tenant_id"]):
        abort(404, "Trabajador no encontrado.")   # no se distingue «no existe» de «no es tuyo»
    return t


@api_bp.route("/fichaje/admin/resumen", methods=["GET"])
@token_required
def fichaje_admin_resumen():
    """Horas trabajadas por trabajador del despacho en el periodo (`desde`, `hasta`: YYYY-MM-DD) y lo acumulado esta semana.
    Gestores de fichajes (su despacho) y administradores (con `tenant_id`)."""
    tenant_id = _tenant_admin()
    desde, hasta = request.args.get("desde") or None, request.args.get("hasta") or None
    semana = fichaje_export.segundos_por_usuario_semana(tenant_id)
    return _ok({"tenant_id": tenant_id, "desde": desde, "hasta": hasta,
                "trabajadores": [{**f, "semana_segundos": semana.get(f.get("usuario_id"), 0)} for f in db.resumen_fichajes_tenant(tenant_id, desde, hasta)]})


@api_bp.route("/fichaje/admin/usuarios/<int:usuario_id>", methods=["GET"])
@token_required
def fichaje_admin_detalle(usuario_id: int):
    """Datos laborales y fichajes de un trabajador (incluidas las correcciones, que son filas nuevas con `corrige_a`)."""
    t = _trabajador_administrable(usuario_id)
    desde, hasta = request.args.get("desde") or None, request.args.get("hasta") or None
    return _ok({"usuario_id": usuario_id, "email": t["email"], "datos": _dict(db.obtener_fichaje_datos(usuario_id)), "fichajes": _dicts(db.listar_fichajes(usuario_id, desde, hasta))})


@api_bp.route("/fichaje/admin/usuarios/<int:usuario_id>/corregir", methods=["POST"])
@token_required
def fichaje_admin_corregir(usuario_id: int):
    """Corrección auditable de un olvido (p. ej. una salida sin fichar). Cuerpo: `tipo` (entrada|pausa_inicio|pausa_fin|salida),
    `marca_tiempo` (la fecha y hora REAL, `YYYY-MM-DDTHH:MM`), `corrige_a` (id del fichaje que se corrige, opcional) y `nota`.
    Nunca sobrescribe: inserta un fichaje nuevo (origen `correccion_admin`, con quién lo hizo) enlazado al original."""
    t = _trabajador_administrable(usuario_id)
    d = _body()
    if d.get("tipo") not in TIPOS_FICHAJE:
        return _err(f"tipo debe ser uno de: {', '.join(TIPOS_FICHAJE)}.", 400, "tipo_invalido", "tipo")
    try:
        marca = datetime.fromisoformat(str(d.get("marca_tiempo") or "")).isoformat(timespec="seconds")
    except ValueError:
        return _err("marca_tiempo debe ser la fecha y hora real, YYYY-MM-DDTHH:MM.", 400, "marca_invalida", "marca_tiempo")
    corrige_a = d.get("corrige_a") if isinstance(d.get("corrige_a"), int) and not isinstance(d.get("corrige_a"), bool) else None
    try:
        fichaje_id = db.fichar(
            usuario_id, t["tenant_id"], d["tipo"], origen="correccion_admin", creado_por=g.usuario_id,
            corrige_a=corrige_a, nota=(d.get("nota") or "").strip() or None, marca_tiempo=marca,
        )
    except ValueError as e:
        return _err(str(e), 400, "fichaje_invalido")
    return _ok({"corregido": True, "fichaje_id": fichaje_id}, 201)


def _exportar(formato: str):
    tenant_id = _tenant_admin()
    desde, hasta, usuario = request.args.get("desde") or None, request.args.get("hasta") or None, request.args.get("usuario_id", type=int)
    if usuario is not None:
        _trabajador_administrable(usuario)
    contenido = {"csv": fichaje_export.a_csv, "pdf": fichaje_export.a_pdf, "json": fichaje_export.a_json}[formato](tenant_id, desde, hasta, usuario)
    tipo = {"csv": "text/csv", "pdf": "application/pdf", "json": "application/json"}[formato]
    r = Response(contenido, mimetype=tipo)
    r.headers["Content-Disposition"] = f"attachment; filename=fichajes.{formato}"
    r.headers["X-Content-Type-Options"] = "nosniff"
    return r


@api_bp.route("/fichaje/admin/exportar.csv", methods=["GET"])
@token_required
def fichaje_admin_csv():
    """Registro horario diario en CSV (`desde`, `hasta`, `usuario_id`; un administrador global añade `tenant_id`)."""
    return _exportar("csv")


@api_bp.route("/fichaje/admin/exportar.pdf", methods=["GET"])
@token_required
def fichaje_admin_pdf():
    return _exportar("pdf")


@api_bp.route("/fichaje/admin/exportar.json", methods=["GET"])
@token_required
def fichaje_admin_json():
    """Detalle crudo por evento con el hash de cada fila (interoperable, para Inspección de Trabajo)."""
    return _exportar("json")


@api_bp.route("/fichaje/admin/verificar-integridad", methods=["GET"])
@token_required
def fichaje_admin_integridad():
    """Comprueba la cadena de hashes del registro horario y dice si está íntegra o en qué fila se rompió."""
    if not (g.es_admin or g.gestor_fichajes):
        abort(403, "Solo gestores de fichajes y administradores.")
    return _ok(db.verificar_integridad_fichajes())
