"""API REST del Asistente jurídico (área de token `juridico`): biblioteca, documentos y versiones, adjuntos privados, conversaciones, consultas con citas, informes y diagnóstico de fuentes.

Capa fina sobre `app/juridico/`: mismas reglas que la web. Sin `LEGAL_AI_ENABLED` o sin el vertical activo todo es 404. El `tenant_id` sale siempre del token, nunca del cuerpo. Una consulta
(`POST …/ejecuciones`) se ejecuta de forma síncrona y admite `Idempotency-Key`: la misma clave devuelve la misma ejecución sin repetir el gasto de IA. Errores tipados: `permiso` (403),
`no_encontrado` (404), `limite_uso` (429), `consulta_extensa` (413), `proveedor_no_disponible` (503), `peticion_invalida` (400), `adjunto_invalido` y derivados (400/413/415/422)."""
from __future__ import annotations

from flask import g, request
from flask_babel import gettext

from . import acceso, db, verticales
from .auth import token_required
from .juridico import adjuntos, asistente, busqueda, corpus, informes, modulo
from .juridico.esquema import COLECCIONES
from .rutas_api import _body, _err, _exigir_tenant_api, _ok, _ok_paginado, api_bp

_HTTP = {"permiso": 403, "no_encontrado": 404, "limite_uso": 429, "consulta_extensa": 413, "proveedor_no_disponible": 503, "peticion_invalida": 400, "archivo_grande": 413, "tipo_no_admitido": 415,
         "archivo_vacio": 400, "archivo_corrupto": 422, "macros": 422, "expansion_excesiva": 422, "demasiadas_paginas": 422, "sin_texto_ocr_requerido": 422, "pdf_no_soportado": 422, "pdf_protegido": 422,
         "antivirus": 422, "demasiados_adjuntos": 400, "extraccion_pendiente": 409, "error_interno": 500}


def _preparar():
    error = _exigir_tenant_api()
    if error:
        return error
    if not modulo.habilitado() or not verticales.esta_activo(g.tenant_id, "juridico"):
        return _err(gettext("Tu despacho no tiene el Asistente jurídico."), 404, "no_encontrado")
    return None


def _fallo(e):
    codigo = getattr(e, "codigo", "peticion_invalida")
    return _err(str(e), _HTTP.get(codigo, 400), codigo)


def _protegido(funcion):
    error = _preparar()
    if error:
        return error
    try:
        return funcion()
    except (asistente.ErrorJuridico, adjuntos.ErrorAdjunto, informes.ErrorInforme) as e:
        return _fallo(e)
    except busqueda.ErrorBusqueda as e:
        return _err(str(e), 400, "peticion_invalida")
    except corpus.ErrorCorpus as e:
        return _err(str(e), 400, "peticion_invalida")


def _int(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


# --- Biblioteca ---------------------------------------------------------------------------------------------------------------------------------

@api_bp.route("/juridico/colecciones", methods=["GET"])
@token_required
def colecciones_juridico_api():
    """Colecciones con su cobertura REAL para tu despacho: fuentes usables, documentos, fechas, última carga correcta, pendientes y cuarentena. Una colección sin fuente habilitada aparece con `disponible: false`."""
    def _lista():
        usables = set(corpus.fuentes_para_despacho(g.tenant_id, "indexar"))
        cob = [c for c in corpus.cobertura() if c["fuente_id"] in usables]
        salida = []
        for clave, nombre in COLECCIONES.items():
            fuentes = [{k: c[k] for k in ("fuente_id", "nombre", "documentos", "fragmentos", "desde", "hasta", "ultimo_exito_en", "pendientes", "reintentables", "cuarentena")} for c in cob if c["coleccion"] == clave]
            salida.append({"clave": clave, "nombre": nombre, "disponible": bool(fuentes), "fuentes": fuentes})
        return _ok(salida)
    return _protegido(_lista)


@api_bp.route("/juridico/buscar", methods=["POST"])
@token_required
def buscar_juridico_api():
    """Busca en la biblioteca (identificadores exactos + texto + similitud si hay embeddings). Cuerpo: `{"consulta": "...", "colecciones": ["legislacion"], "materia", "territorio", "emisor", "tipo",
    "desde", "hasta", "fecha_juridica": "AAAA-MM-DD", "limite": 20, "cursor": "..."}`. Devuelve resultados agrupados por documento con `motivo`, localizador, vigencia y fecha de captura, más `huecos`
    (normas sin texto aplicable a esa fecha) y `avisos` (colecciones pedidas y no disponibles). Paginación por `siguiente_cursor`."""
    def _buscar():
        d = _body()
        cols = d.get("colecciones")
        if cols is not None and (not isinstance(cols, list) or any(c not in COLECCIONES for c in cols)):
            return _err(gettext("Colecciones no válidas."), 400, "peticion_invalida", "colecciones")
        r = busqueda.buscar(g.tenant_id, d.get("consulta") or "", colecciones=cols, materia=d.get("materia"), territorio=d.get("territorio"), emisor=d.get("emisor"), tipo=d.get("tipo"),
                            desde=d.get("desde"), hasta=d.get("hasta"), fecha_juridica=d.get("fecha_juridica"), limite=_int(d.get("limite")) or 20, cursor=d.get("cursor"))
        return _ok(r)
    return _protegido(_buscar)


@api_bp.route("/juridico/documentos/<int:documento_id>", methods=["GET"])
@token_required
def documento_juridico_api(documento_id: int):
    """Metadatos de un documento, sus versiones y sus relaciones documentadas. 404 si su fuente no está disponible para tu despacho."""
    def _ver():
        d = busqueda.documento(g.tenant_id, documento_id)
        return _err(gettext("No existe ese documento."), 404, "no_encontrado") if d is None else _ok(d)
    return _protegido(_ver)


@api_bp.route("/juridico/documentos/<int:documento_id>/versiones/<int:version_id>", methods=["GET"])
@token_required
def version_juridico_api(documento_id: int, version_id: int):
    """Texto de una versión con sus localizadores. `fecha_juridica` (AAAA-MM-DD) limita los fragmentos a los vigentes en esa fecha según la fuente."""
    def _ver():
        t = busqueda.texto_de_version(g.tenant_id, documento_id, version_id, request.args.get("fecha_juridica") or None)
        return _err(gettext("No existe esa versión."), 404, "no_encontrado") if t is None else _ok(t)
    return _protegido(_ver)


# --- Adjuntos privados -----------------------------------------------------------------------------------------------------------------------

@api_bp.route("/juridico/adjuntos", methods=["POST"])
@token_required
def subir_adjunto_juridico_api():
    """Sube un adjunto privado (multipart, campo `archivo`; opcionales `cliente_id` y `expediente_id`). TXT, DOCX sin macros y PDF con texto; 20 MB y 100 páginas como máximo. Se extrae el texto de forma
    síncrona y no se guarda el archivo original. Devuelve su estado (`lista` o error tipado)."""
    def _subir():
        a = request.files.get("archivo")
        if a is None or not a.filename:
            return _err(gettext("Falta el archivo (campo `archivo`)."), 400, "peticion_invalida", "archivo")
        r = adjuntos.subir(g.tenant_id, g.usuario_id, a.filename, a.read(adjuntos.MAX_BYTES + 1), cliente_id=_int(request.form.get("cliente_id")), expediente_id=_int(request.form.get("expediente_id")))
        return _ok(r, 201)
    return _protegido(_subir)


@api_bp.route("/juridico/adjuntos/<int:adjunto_id>/estado", methods=["GET"])
@token_required
def estado_adjunto_juridico_api(adjunto_id: int):
    """Estado de la extracción (`pendiente`, `lista`, `fallida`) y su retención. No devuelve el texto."""
    def _ver():
        a = adjuntos.obtener(g.tenant_id, g.usuario_id, adjunto_id)
        return _err(gettext("No existe ese adjunto."), 404, "no_encontrado") if a is None else _ok(a)
    return _protegido(_ver)


@api_bp.route("/juridico/adjuntos/<int:adjunto_id>", methods=["DELETE"])
@token_required
def borrar_adjunto_juridico_api(adjunto_id: int):
    """Borra el adjunto con su texto extraído e índice."""
    def _borrar():
        return _ok() if adjuntos.borrar(g.tenant_id, g.usuario_id, adjunto_id) else _err(gettext("No existe ese adjunto."), 404, "no_encontrado")
    return _protegido(_borrar)


# --- Conversaciones y consultas ------------------------------------------------------------------------------------------------------------------

@api_bp.route("/juridico/conversaciones", methods=["POST"])
@token_required
def crear_conversacion_juridico_api():
    """Crea una conversación privada: `{"cliente_id": 12, "expediente_id": 7, "titulo": "..."}` (todo opcional). El cliente/expediente tiene que ser visible para ti."""
    def _crear():
        d = _body()
        cid = asistente.crear_conversacion(g.tenant_id, g.usuario_id, cliente_id=_int(d.get("cliente_id")), expediente_id=_int(d.get("expediente_id")), titulo=d.get("titulo"))
        return _ok({"id": cid}, 201)
    return _protegido(_crear)


@api_bp.route("/juridico/conversaciones/<int:conversacion_id>/ejecuciones", methods=["POST"])
@token_required
def consultar_juridico_api(conversacion_id: int):
    """Lanza una consulta: `{"pregunta": "...", "colecciones": [...], "materia", "territorio", "fecha_juridica": "AAAA-MM-DD", "modo_temporal": "actual|historico", "objetivo":
    "consulta|busqueda|resumen|borrador", "adjunto_ids": [3]}`. Cabecera `Idempotency-Key` opcional. Devuelve el `LegalAnswer`: `status` (`answered`, `needs_context`, `insufficient_evidence`),
    `facts`, `missingFacts`, `conclusion`, `claims` con `citationIds`, `citations` (extracto, localizador, versión y enlace puestos por el servidor), `limitations`, `suggestedNextSteps` y `coverage`.
    Nunca se responde de memoria: sin fuentes recuperadas es `insufficient_evidence` y no se llama al modelo. Usa tu modelo de IA configurado."""
    def _lanzar():
        d = _body()
        cols = d.get("colecciones")
        if cols is not None and (not isinstance(cols, list) or any(c not in COLECCIONES for c in cols)):
            return _err(gettext("Colecciones no válidas."), 400, "peticion_invalida", "colecciones")
        ids = d.get("adjunto_ids") or []
        if not isinstance(ids, list) or any(not isinstance(i, int) for i in ids):
            return _err(gettext("`adjunto_ids` debe ser una lista de enteros."), 400, "peticion_invalida", "adjunto_ids")
        r = asistente.consultar(g.tenant_id, g.usuario_id, conversacion_id, d.get("pregunta") or "", colecciones=cols, materia=d.get("materia"), territorio=d.get("territorio"),
                                fecha_juridica=d.get("fecha_juridica"), modo_temporal=d.get("modo_temporal") or "actual", objetivo=d.get("objetivo") or "consulta", adjunto_ids=ids,
                                clave_idempotencia=(request.headers.get("Idempotency-Key") or "").strip()[:100] or None)
        return _ok(r, 200)
    return _protegido(_lanzar)


@api_bp.route("/juridico/ejecuciones/<int:ejecucion_id>", methods=["GET"])
@token_required
def ejecucion_juridico_api(ejecucion_id: int):
    """El resultado guardado de una consulta (solo para quien la lanzó)."""
    return _protegido(lambda: _ok(asistente.respuesta_de(g.tenant_id, g.usuario_id, ejecucion_id)))


# --- Informes -----------------------------------------------------------------------------------------------------------------------------------

def _informe_json(i: dict) -> dict:
    return {k: i.get(k) for k in ("id", "ejecucion_id", "cliente_id", "expediente_id", "titulo", "estado", "creado_por", "revisado_por", "revisado_en", "creado_en", "aviso_fuente")}


@api_bp.route("/juridico/ejecuciones/<int:ejecucion_id>/informe", methods=["POST"])
@token_required
def guardar_informe_juridico_api(ejecucion_id: int):
    """Guarda una instantánea de la consulta respondida en el expediente/cliente de su conversación: `{"titulo": "..."}`. Queda como `borrador`. Una consulta que no está `answered` no se guarda."""
    def _guardar():
        inf = informes.guardar(g.tenant_id, g.usuario_id, ejecucion_id, titulo=_body().get("titulo"))
        return _ok(_informe_json(inf) | {"instantanea": inf["instantanea"]}, 201)
    return _protegido(_guardar)


@api_bp.route("/juridico/informes", methods=["GET"])
@token_required
def informes_juridico_api():
    """Informes que puedes ver. Filtros: `expediente_id`, `cliente_id`. Paginación opcional `limit`/`offset`."""
    return _protegido(lambda: _ok_paginado([_informe_json(i) for i in informes.listar(g.tenant_id, g.usuario_id, expediente_id=request.args.get("expediente_id", type=int), cliente_id=request.args.get("cliente_id", type=int))]))


@api_bp.route("/juridico/informes/<int:informe_id>", methods=["GET"])
@token_required
def informe_juridico_api(informe_id: int):
    """Un informe con su instantánea (consulta, respuesta y citas con su versión y fecha de captura)."""
    def _ver():
        i = informes.obtener(g.tenant_id, g.usuario_id, informe_id)
        return _err(gettext("No existe ese informe."), 404, "no_encontrado") if i is None else _ok(_informe_json(i) | {"instantanea": i["instantanea"]})
    return _protegido(_ver)


@api_bp.route("/juridico/informes/<int:informe_id>/revision", methods=["PATCH"])
@token_required
def revisar_informe_juridico_api(informe_id: int):
    """Registra la revisión: `{"decision": "revisado" | "archivado", "nota": "..."}`. `revisado` solo lo marca la dirección o una persona autorizada (queda quién y cuándo); un informe con una fuente
    retirada no se puede revisar hasta volver a lanzar la consulta."""
    def _revisar():
        d = _body()
        return _ok(_informe_json(informes.revisar(g.tenant_id, g.usuario_id, informe_id, d.get("decision") or "revisado", d.get("nota"))))
    return _protegido(_revisar)


# --- Diagnóstico de fuentes (solo administración de la plataforma) -----------------------------------------------------------------------

@api_bp.route("/juridico/admin/fuentes", methods=["GET"])
@token_required
def fuentes_juridico_api():
    """Diagnóstico de cada fuente: estado, habilitación, política vigente, cobertura, últimas ejecuciones y registros con problemas. Solo el administrador de la plataforma."""
    def _ver():
        if not db.es_admin(g.usuario_id):
            return _err(gettext("Solo el administrador de la plataforma puede ver el diagnóstico de fuentes."), 403, "permiso")
        from .juridico import catalogo, ingesta
        cob = {c["fuente_id"]: c for c in corpus.cobertura()}
        return _ok([{**f, "habilitada": bool(f["habilitada"]), "cobertura": cob[f["id"]], "politica": corpus.politica_vigente(f["id"]), "verificacion": catalogo.VERIFICACION.get(f["id"]), "ejecuciones": ingesta.ultimas_ejecuciones(f["id"], 5),
                     "problemas": ingesta.registros_con_problemas(f["id"], 20)} for f in corpus.listar_fuentes()])
    return _protegido(_ver)
