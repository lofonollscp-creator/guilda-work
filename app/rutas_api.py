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
import logging
import base64
import hashlib
import json
from datetime import datetime, timedelta

from flask import Blueprint, Response, abort, g, jsonify, make_response, request, stream_with_context, url_for
from werkzeug.exceptions import HTTPException

from .bd.errores import ErrorIntegridad
from . import alta_cliente, api_contexto, correo, db, estado_herramientas, eventos, fiscal_identidad, peticion, espocrm, export, herramientas, ia_asistente, ia_atajos, kratos, openapi, quickadd
from .auth import limiter, token_required
from .rutas_correo import _ids_propios_del_usuario, _mensaje_de_usuario_o_404

logger = logging.getLogger("guilda")

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")

# Versión del contrato (mayor.menor): el menor sube con cada ampliación compatible; el mayor solo si algo se rompe.
API_VERSION = "1.8"


_CODIGOS_HTTP = {
    400: "peticion_invalida", 401: "no_autenticado", 403: "prohibido", 404: "no_encontrado", 405: "metodo_no_permitido",
    409: "conflicto", 412: "version_obsoleta", 413: "demasiado_grande", 415: "tipo_no_soportado", 422: "entidad_no_procesable", 426: "actualiza_app", 429: "limite_excedido",
}


def _codigo_de(status: int) -> str:
    return _CODIGOS_HTTP.get(status) or ("error_interno" if status >= 500 else "peticion_invalida")


@api_bp.errorhandler(HTTPException)
def _error_json(e: HTTPException):
    respuesta = jsonify({"ok": False, "error": e.description, "codigo": _codigo_de(e.code or 500), "request_id": peticion.id_actual()})
    if e.code == 429 and getattr(e, "retry_after", None):
        respuesta.headers["Retry-After"] = str(int(e.retry_after))
    return respuesta, e.code


@api_bp.errorhandler(fiscal_identidad.ClienteDuplicado)
def _cliente_duplicado(e):
    """Dos clientes de la misma asesoría con la misma identificación fiscal válida: conflicto de negocio, con el cliente existente en el texto."""
    return _err(str(e), 409, "cliente_duplicado")


def _integridad(e):
    """Un valor que la base de datos rechaza (estado o prioridad inexistentes, duplicados...) es un error del cliente,
    no un fallo del servidor."""
    if "UNIQUE" in str(e).upper():
        return _err("Ya existe un registro con esos datos.", 409, "conflicto")
    return _err("Alguno de los valores enviados no es válido (revisa campos como estado o prioridad).", 400, "valor_invalido")


for _clase in ErrorIntegridad:
    api_bp.errorhandler(_clase)(_integridad)


_CORS_METODOS = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
_CORS_ENVIAR = "Authorization, Content-Type, Idempotency-Key, X-Request-Id, If-None-Match"
_CORS_LEER = "X-Request-Id, X-API-Version, X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset, X-Total-Count, ETag, Retry-After, Idempotent-Replay"


def _poner_cors(respuesta, origen: str):
    respuesta.headers["Access-Control-Allow-Origin"] = origen      # nunca `*`: es el origen exacto que el token admite
    respuesta.headers["Vary"] = "Origin"
    respuesta.headers["Access-Control-Expose-Headers"] = _CORS_LEER
    return respuesta


@api_bp.before_request
def _preflight_cors():
    """Responde al preflight de un navegador (`OPTIONS` con `Origin`). No lleva token, así que solo se concede si ALGÚN token
    vivo admite ese origen; la decisión de verdad la toma cada petición con el token que usa (ver `_cabeceras_api`)."""
    if request.method != "OPTIONS" or not request.headers.get("Access-Control-Request-Method"):
        return None
    respuesta = make_response("", 204)
    origen = request.headers.get("Origin", "")
    if origen and db.origen_cors_conocido(origen):
        _poner_cors(respuesta, origen)
        respuesta.headers["Access-Control-Allow-Methods"] = _CORS_METODOS
        respuesta.headers["Access-Control-Allow-Headers"] = _CORS_ENVIAR
        respuesta.headers["Access-Control-Max-Age"] = "600"
    return respuesta


@api_bp.before_request
def _version_minima_de_app():
    """La app móvil manda `X-App-Version`: si es menor que la mínima admitida (`GUILDA_APP_VERSION_MINIMA`) responde `426 actualiza_app`,
    con el enlace de la tienda. Quien no manda la cabecera (web, integraciones, MCP) no se ve afectado."""
    version = request.headers.get("X-App-Version")
    if not version or request.method == "OPTIONS" or request.path.endswith(("/health", "/openapi.json")) or not api_contexto.app_obsoleta(version):
        return None
    cfg = api_contexto.config_app()
    respuesta = jsonify({"ok": False, "error": "Esta versión de la app ya no se admite: actualízala para seguir trabajando.", "codigo": "actualiza_app",
                         "request_id": peticion.id_actual(), "version_minima": cfg["version_minima"], "url_tienda": cfg["url_tienda"]})
    return respuesta, 426


@api_bp.after_request
def _cabeceras_api(respuesta):
    """Versión de la API, cuota restante, y ETag/304 en lecturas JSON (ahorra descargas repetidas a la app móvil y a
    integraciones externas que sondean)."""
    respuesta.headers["X-API-Version"] = API_VERSION
    origen = request.headers.get("Origin")
    if origen and origen in (g.get("origenes_cors_token") or []):
        _poner_cors(respuesta, origen)
    if g.get("token_id"):
        try:
            db.registrar_uso_token(g.token_id, respuesta.status_code)
        except Exception:  # noqa: BLE001 -- el contador nunca debe romper una respuesta
            pass
    limite = g.get("api_limite")
    if limite:
        respuesta.headers["X-RateLimit-Limit"], respuesta.headers["X-RateLimit-Remaining"], respuesta.headers["X-RateLimit-Reset"] = (str(x) for x in limite)
        respuesta.headers["X-RateLimit-Scope"] = g.get("api_cupo", "total")
    if request.method == "GET" and respuesta.status_code == 200 and respuesta.mimetype == "application/json" and not respuesta.is_streamed:
        etag = '"' + hashlib.sha1(respuesta.get_data()).hexdigest()[:20] + '"'
        respuesta.headers["ETag"] = etag
        respuesta.headers["Cache-Control"] = "private, no-cache"
        if etag in [x.strip() for x in request.headers.get("If-None-Match", "").split(",")]:
            respuesta.set_data(b"")
            respuesta.status_code = 304
    return respuesta


def _dict(fila) -> dict | None:
    return dict(fila) if fila is not None else None


def _dicts(filas) -> list[dict]:
    return [dict(f) for f in filas]


def _proyectar(dato, campos: set[str]):
    if isinstance(dato, dict):
        return {k: v for k, v in dato.items() if k in campos}
    if isinstance(dato, list):
        return [_proyectar(x, campos) if isinstance(x, dict) else x for x in dato]
    return dato


def _ok(data=None, status: int = 200):
    cuerpo = {"ok": True}
    if data is not None:
        # `campos=id,asunto` devuelve solo esos campos (menos bytes en móvil); aplica a objetos y a listas de objetos.
        campos = {c.strip() for c in (request.args.get("campos") or "").split(",") if c.strip()}
        cuerpo["data"] = _proyectar(data, campos) if campos else data
    return jsonify(cuerpo), status


def _ok_paginado(filas):
    """Respuesta de listado con paginación OPCIONAL: sin `limit`/`offset` devuelve
    todo, igual que siempre (la app móvil no cambia); con ellos devuelve esa
    página. En ambos casos la cabecera `X-Total-Count` lleva el total sin paginar."""
    filas = list(filas)
    total = len(filas)
    offset = max(0, request.args.get("offset", default=0, type=int) or 0)
    limit = request.args.get("limit", type=int)
    if limit is not None:
        filas = filas[offset:offset + max(1, min(limit, 1000))]
    elif offset:
        filas = filas[offset:]
    respuesta, status = _ok(_dicts(filas))
    respuesta.headers["X-Total-Count"] = str(total)
    return respuesta, status


def _err(mensaje: str, status: int = 400, codigo: str | None = None, campo: str | None = None):
    """Error uniforme: `{"ok": false, "error": "texto para personas", "codigo": "clave_estable", "campo": "opcional"}`.
    `codigo` es lo que debe leer un programa (el texto puede cambiar o traducirse)."""
    cuerpo = {"ok": False, "error": mensaje, "codigo": codigo or _codigo_de(status), "request_id": peticion.id_actual()}
    if campo:
        cuerpo["campo"] = campo
    return jsonify(cuerpo), status


def _err_version(mensaje: str, version_actual: int):
    """412 `version_obsoleta` con la versión que tiene ahora el recurso (`version_actual`): la app ofrece «ver cambios / sobrescribir» sin otra
    petición. Mismo cuerpo que el 409 de las tareas (`rutas_api_tareas_trabajo`), que usa otro número de estado para el mismo concepto."""
    respuesta, status = _err(mensaje, 412, "version_obsoleta")
    cuerpo = respuesta.get_json()
    cuerpo["version_actual"] = version_actual
    return jsonify(cuerpo), status


def _referencia(datos: dict):
    """(hay_referencia, valor). La puede mandar el cliente en el cuerpo (`referencia_externa`) o venir forzada por las rutas
    `.../por-referencia/{ref}`. ValueError si no es válida."""
    forzada = g.get("referencia_forzada")
    if forzada is not None:
        return True, db.validar_referencia_externa(forzada)
    if "referencia_externa" in datos:
        return True, db.validar_referencia_externa(datos["referencia_externa"])
    return False, None


def _error_referencia(tabla: str, dueno_id: int, datos: dict, excepto_id: int | None = None):
    """None si la referencia (si la hay) es válida y está libre; si no, el `_err` que hay que devolver."""
    try:
        hay, ref = _referencia(datos)
    except ValueError as e:
        return _err(str(e), 400, "referencia_invalida", "referencia_externa")
    if hay and ref:
        otro = db.id_por_referencia_externa(tabla, dueno_id, ref)
        if otro is not None and otro != excepto_id:
            return _err(f"Ya existe un registro con referencia_externa «{ref}» (id {otro}).", 409, "referencia_duplicada", "referencia_externa")
    return None


def _guardar_referencia(tabla: str, dueno_id: int, fila_id: int, datos: dict) -> None:
    hay, ref = _referencia(datos)
    if hay:
        db.fijar_referencia_externa(tabla, dueno_id, fila_id, ref)


def _campos_cliente_fiscal(datos: dict):
    """Campos de contacto y configuración que la web también permite editar: `email`, `pais` (código ISO, p. ej. ES), `idioma`
    (es|ca|en|fr) y `recordatorios_portal`. Devuelve (campos, error); `error` es un `_err` ya construido."""
    campos = {}
    if "email" in datos:
        email = (datos["email"] or "").strip() or None
        if email and ("@" not in email or len(email) > 200 or " " in email):
            return None, _err("email no es válido.", 400, "email_invalido", "email")
        campos["email"] = email
    if "pais" in datos:
        pais = str(datos["pais"] or "ES").strip().upper()
        if len(pais) != 2 or not pais.isalpha():
            return None, _err("pais debe ser un código de 2 letras (p. ej. ES).", 400, "pais_invalido", "pais")
        campos["pais"] = pais
    if "idioma" in datos:
        if datos["idioma"] not in ("es", "ca", "en", "fr"):
            return None, _err("idioma debe ser es, ca, en o fr.", 400, "idioma_invalido", "idioma")
        campos["idioma"] = datos["idioma"]
    if "recordatorios_portal" in datos:
        campos["recordatorios_portal"] = 1 if datos["recordatorios_portal"] else 0
    return campos, None




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
    codigo_2fa = str(datos.get("codigo_2fa") or "").strip()
    try:
        identity_id = kratos.verificar_credenciales_admin(email, contrasena, codigo_2fa or None)
    except kratos.Requiere2FA:
        return _err("Esta cuenta tiene la verificación en dos pasos: vuelve a llamar con `codigo_2fa` (el de tu app de autenticación o uno de recuperación).", 401, "requiere_2fa", "codigo_2fa")
    if identity_id is None:
        if codigo_2fa:
            return _err("Email, contraseña o código incorrectos.", 401, "credenciales_o_codigo_incorrectos")
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


@api_bp.route("/tokens", methods=["GET"])
@token_required
def listar_tokens():
    """Tokens de acceso del usuario (nunca el token ni su hash)."""
    return _ok([{**dict(t), "areas": json.loads(t["areas"]) if t["areas"] else [],
                 "origenes_cors": json.loads(t["origenes_cors"]) if t["origenes_cors"] else [],
                 "ips_permitidas": json.loads(t["ips_permitidas"]) if t["ips_permitidas"] else []} for t in db.listar_tokens_api(g.usuario_id)])


@api_bp.route("/tokens", methods=["POST"])
@token_required
def crear_token():
    """Crea otro token (p. ej. para una integración). Cuerpo: `nombre`; `permisos` (`completo` | `solo_lectura`);
    `areas` (lista: notas, tareas, correo, fiscal, fichaje, tiquets, ia, avisos; vacío = todas); y la caducidad con
    `caduca_dias` (1-3650) o `caduca_en` (fecha ISO). Restricciones de red opcionales: `origenes_cors` (orígenes web
    exactos que pueden usar el token desde un navegador, p. ej. `https://panel.ejemplo.com`) e `ips_permitidas` (IP o
    redes CIDR desde las que puede usarse; un token con IPs no sirve por MCP). El token en claro solo se devuelve aquí,
    una vez. Un token de solo lectura o limitado a áreas no puede llamar a esto."""
    datos = _body()
    permisos = datos.get("permisos") or "completo"
    if permisos not in db.PERMISOS_TOKEN_API:
        return _err("permisos debe ser 'completo' o 'solo_lectura'.", 400, "permisos_invalidos", "permisos")
    nombre = (datos.get("nombre") or "").strip()[:80] or None
    caduca_en = datos.get("caduca_en")
    if datos.get("caduca_dias") not in (None, ""):
        dias = datos.get("caduca_dias")
        if not isinstance(dias, int) or isinstance(dias, bool) or not 1 <= dias <= 3650:
            return _err("caduca_dias debe ser un entero entre 1 y 3650.", 400, "caducidad_invalida", "caduca_dias")
        caduca_en = (datetime.now() + timedelta(days=dias)).isoformat(timespec="seconds")
    try:
        token = db.crear_token_api(g.usuario_id, nombre, permisos, areas=datos.get("areas"), caduca_en=caduca_en,
                                   origenes_cors=datos.get("origenes_cors"), ips_permitidas=datos.get("ips_permitidas"))
    except ValueError as e:
        mensaje = str(e)
        if "CORS" in mensaje:
            return _err(mensaje, 400, "origenes_invalidos", "origenes_cors")
        if "IP" in mensaje:
            return _err(mensaje, 400, "ips_invalidas", "ips_permitidas")
        campo = "areas" if "Áreas" in mensaje else "caduca_en"
        return _err(mensaje, 400, "areas_invalidas" if campo == "areas" else "caducidad_invalida", campo)
    token_id = db.id_de_token(token)
    fila = next(t for t in db.listar_tokens_api(g.usuario_id) if t["id"] == token_id)
    return _ok({"token": token, "id": token_id, "permisos": permisos, "nombre": nombre,
                "areas": json.loads(fila["areas"]) if fila["areas"] else [], "caduca_en": fila["caduca_en"],
                "origenes_cors": json.loads(fila["origenes_cors"]) if fila["origenes_cors"] else [],
                "ips_permitidas": json.loads(fila["ips_permitidas"]) if fila["ips_permitidas"] else []}, 201)


@api_bp.route("/tokens/<int:token_id>/uso", methods=["GET"])
@token_required
def uso_de_token(token_id: int):
    """Llamadas y errores por día de uno de tus tokens (`dias`, 1-90, por defecto 30)."""
    if not any(t["id"] == token_id for t in db.listar_tokens_api(g.usuario_id)):
        abort(404, "Token no encontrado.")
    dias = max(1, min(request.args.get("dias", default=30, type=int) or 30, 90))
    return _ok(db.uso_de_token(token_id, dias))


@api_bp.route("/tokens/<int:token_id>", methods=["DELETE"])
@token_required
def revocar_token(token_id: int):
    if not db.revocar_token_api_por_id(g.usuario_id, token_id):
        abort(404, "Token no encontrado.")
    return _ok()


@api_bp.route("/auth/me", methods=["GET"])
@token_required
def me():
    """Datos de la persona autenticada: perfil, despacho y preferencias."""
    usuario = db.obtener_usuario(g.usuario_id)
    # tenant_id (Fase F5, calendario fiscal en móvil): ya lo calcula
    # token_required en g.tenant_id -- expuesto aquí para que el cliente
    # Flutter sepa si mostrar o no la entrada "Calendario fiscal" del
    # dashboard, mismo criterio que ya usa la web con g.tenant_id.
    # fichaje_geolocalizacion (Fase G3): para que el móvil sepa si tiene
    # que pedir permiso de ubicación al fichar -- sin esto pediría el
    # permiso siempre, aunque el tenant no la use.
    tenant = db.obtener_tenant(g.tenant_id) if g.tenant_id else None
    return _ok({
        "id": usuario["id"], "email": usuario["email"], "es_admin": usuario["rol"] == "admin",
        "tenant_id": g.tenant_id,
        "fichaje_geolocalizacion": bool(tenant and tenant["fichaje_geolocalizacion"]),
        # API 1.5 (app móvil): despachos, módulos activos, permisos, cifrado, apariencia y versión mínima de la app.
        **api_contexto.contexto(usuario["id"], g.tenant_id, es_admin=bool(g.es_admin), gestor_fichajes=bool(g.gestor_fichajes),
                                supervisor=bool(g.supervisor_tenant)),
    })


# --- Proyectos / categorías ----------------------------------------------------

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
        abort(404, "Proyecto no encontrado.")
    db.eliminar_categoria(g.usuario_id, categoria_id)
    return _ok()


@api_bp.route("/categorias/<int:categoria_id>/favorito", methods=["POST"])
@token_required
def alternar_favorito_categoria(categoria_id: int):
    if db.obtener_categoria(g.usuario_id, categoria_id) is None:
        abort(404, "Proyecto no encontrado.")
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
    """`creada_en`/`cliente_uuid` opcionales: igual que en /fichaje/marcar,
    para la cola offline de la app móvil."""
    datos = _body()
    texto = (datos.get("texto") or "").strip()
    if not texto:
        return _err("El texto no puede estar vacío.")
    error = _error_referencia("notas", g.usuario_id, datos)
    if error:
        return error
    try:
        nota_id = db.crear_nota(
            g.usuario_id, texto, categoria_id=datos.get("categoria_id"),
            creada_en=datos.get("creada_en"), cliente_uuid=datos.get("cliente_uuid"),
        )
    except ValueError as e:
        return _err(str(e))
    _guardar_referencia("notas", g.usuario_id, nota_id, datos)
    return _ok(_dict(db.obtener_nota(g.usuario_id, nota_id)), 201)


@api_bp.route("/notas/<int:nota_id>", methods=["PUT"])
@token_required
def editar_nota(nota_id: int):
    if db.obtener_nota(g.usuario_id, nota_id) is None:
        abort(404, "Nota no encontrada.")
    datos = _body()
    texto = (datos.get("texto") or "").strip()
    if not texto:
        return _err("El texto no puede estar vacío.")
    error = _error_referencia("notas", g.usuario_id, datos, excepto_id=nota_id)
    if error:
        return error
    db.editar_nota(g.usuario_id, nota_id, texto)
    _guardar_referencia("notas", g.usuario_id, nota_id, datos)
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
        abort(404, "Proyecto no encontrado.")
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
    onboarding_visible = db.onboarding_visible(g.usuario_id)
    return _ok({
        "menus": _dicts(menus),
        "tareas_activas": _dicts(activas),
        "notas_hoy": len([f for f in log_hoy if f["origen"] == "nota"]),
        "correos_no_leidos": db.contar_no_leidos_total_correo(g.usuario_id),
        # Mismo checklist calculado en caliente que en la web (app/main.py:
        # inicio()) -- ver GuildaWorkApp/dashboard_screen.dart.
        "onboarding_visible": onboarding_visible,
        "onboarding_tiene_menu": bool(menus) if onboarding_visible else None,
        "onboarding_tiene_correo": bool(db.listar_cuentas_correo(g.usuario_id)) if onboarding_visible else None,
        "onboarding_ha_usado_ia": bool(db.listar_mensajes_ia(g.usuario_id)) if onboarding_visible else None,
    })


@api_bp.route("/onboarding/ocultar", methods=["POST"])
@token_required
def ocultar_onboarding():
    db.ocultar_onboarding(g.usuario_id)
    return _ok()


@api_bp.route("/historial", methods=["GET"])
@token_required
def historial():
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    categoria_id = request.args.get("categoria_id", type=int)
    q = request.args.get("q") or None
    filas = db.historial(g.usuario_id, desde=desde, hasta=hasta, categoria_id=categoria_id, texto=q)
    return _ok_paginado(filas)


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

def _filas_de_tarea(filas, con_rol: bool = False) -> list[dict]:
    """Las filas de tareas como las pinta la web en lista, «Mi día» y tablero: `vencida` (derivada), `n_comentarios`, `checklist_hechas`/`checklist_total` y `bloqueos`;
    con `con_rol`, también `rol` (dueno, asignada o compartida). Lista, `/mi-dia` y `/tareas-outlook/tablero` comparten esto para que la app vea lo mismo que la web."""
    from . import tareas_trabajo as _tt
    filas = list(filas)
    ids = [f["id"] for f in filas]
    comentarios, checklists, bloqueos = db.contar_comentarios_tareas(ids), db.resumen_checklist(ids), db.bloqueos_de_tareas(ids)
    resultado = []
    for f in filas:
        fila = dict(f)
        fila["vencida"] = _tt.esta_vencida(fila.get("fecha_vencimiento"), fila.get("estado"))      # derivada, como en el detalle (API 1.5: la lista también la trae)
        hechas, total = checklists.get(f["id"], (0, 0))
        fila.update(n_comentarios=comentarios.get(f["id"], 0), checklist_hechas=int(hechas or 0), checklist_total=int(total or 0), bloqueos=bloqueos.get(f["id"], 0))
        if con_rol:
            fila["rol"] = "dueno" if f["usuario_id"] == g.usuario_id else ("asignada" if f["asignada_a"] == g.usuario_id else "compartida")
        resultado.append(fila)
    return resultado


@api_bp.route("/tareas-outlook", methods=["GET"])
@token_required
def listar_tareas_outlook():
    """Filtros: `estado`, `prioridad`, `categoria`, `q`, `desde`/`hasta` (fecha de vencimiento, YYYY-MM-DD).
    `ambito` (opcional): `propias` (por defecto, como siempre), `asignadas`
    (las que me han asignado), `compartidas` (compartidas conmigo) o `todas`.
    Cada fila lleva `rol`: dueno, asignada o compartida.
    `completadas` (opcional, como en la web): `0` oculta las completadas (salvo que se pida un `estado`), `1` las incluye; sin él, se devuelve todo como siempre.
    Cada fila trae además `n_comentarios`, `checklist_hechas`, `checklist_total` y `bloqueos` (tareas previas sin completar), para pintar la lista sin más llamadas."""
    ref = request.args.get("referencia_externa")
    if ref:
        encontrado = db.id_por_referencia_externa("tareas_outlook", g.usuario_id, ref)
        return _ok_paginado([db.obtener_tarea_outlook(g.usuario_id, encontrado)] if encontrado else [])
    ambito = request.args.get("ambito") or "propias"
    if ambito not in ("propias", "asignadas", "compartidas", "todas"):
        return _err("ambito debe ser propias, asignadas, compartidas o todas.")
    filas = db.listar_tareas_outlook(
        g.usuario_id,
        estado=request.args.get("estado") or None,
        prioridad=request.args.get("prioridad") or None,
        categoria_outlook=request.args.get("categoria") or None,
        texto=request.args.get("q") or None,
        desde=request.args.get("desde") or None, hasta=request.args.get("hasta") or None,
        incluir_asignadas=ambito == "todas",
        solo_asignadas=ambito == "asignadas",
        solo_compartidas=ambito == "compartidas",
        excluir_completadas=request.args.get("completadas") == "0" and not request.args.get("estado"),
    )
    return _ok_paginado(_filas_de_tarea(filas, con_rol=ambito != "propias"))


@api_bp.route("/tareas-outlook", methods=["POST"])
@token_required
def crear_tarea_outlook():
    datos = _body()
    asunto = (datos.get("asunto") or "").strip()
    if not asunto:
        return _err("El asunto no puede estar vacío.")
    error = _error_referencia("tareas_outlook", g.usuario_id, datos)
    if error:
        return error
    from datetime import date
    from . import quickadd, tareas_trabajo
    from .rutas_tareas import _notificar_asignacion
    companeros = db.listar_companeros_tenant(g.usuario_id)
    proyectos = db.listar_proyectos_usables(g.usuario_id)
    # `texto_libre`: como el cuadro de alta de la web, «viernes 10h pedir extractos @luis !alta #IVA»; lo que se manda explícito manda sobre lo entendido.
    entendido = None
    if datos.get("texto_libre"):
        entendido = quickadd.interpretar(asunto, date.today(), [(c["id"], c["nombre"], c["email"] if "email" in c.keys() else "") for c in companeros], [(m["id"], m["nombre"]) for m in proyectos])
        asunto = entendido.asunto or asunto
    categoria_id = datos.get("categoria_id") or (entendido.etiqueta_id if entendido else None)
    asignada_a = datos.get("asignada_a") or (entendido.persona_id if entendido else None)
    cliente_id = datos.get("cliente_fiscal_id")
    if categoria_id is not None and categoria_id not in {m["id"] for m in proyectos}:
        return _err("Ese proyecto no existe o no puedes poner tareas en él.", 400, "proyecto_invalido", "categoria_id")
    if asignada_a is not None and asignada_a not in {c["id"] for c in companeros}:
        return _err("Solo puedes asignar a personas de tu despacho.", 400, "asignada_invalida", "asignada_a")
    if cliente_id is not None:
        try:
            tareas_trabajo.validar_clientes(g.usuario_id, [cliente_id], cliente_id)
        except tareas_trabajo.TransicionInvalida as e:
            return _err(str(e), 400, e.codigo, e.campo)
    prioridad = datos.get("prioridad") or (entendido.prioridad if entendido and entendido.prioridad else "normal")
    tarea_id = db.crear_tarea_outlook(
        g.usuario_id, asunto=asunto, cuerpo=datos.get("cuerpo"),
        prioridad=prioridad,
        fecha_inicio=datos.get("fecha_inicio"), fecha_vencimiento=datos.get("fecha_vencimiento") or (entendido.vencimiento if entendido else None),
        categoria_outlook=datos.get("categoria_outlook"), estimacion_min=datos.get("estimacion_min") or (entendido.estimacion_min if entendido else None),
        categoria_id=categoria_id, asignada_a=asignada_a, cliente_fiscal_id=cliente_id,
    )
    _guardar_referencia("tareas_outlook", g.usuario_id, tarea_id, datos)
    _notificar_asignacion(g.usuario_id, tarea_id, asignada_a)
    r = _dict(db.obtener_tarea_outlook(g.usuario_id, tarea_id))
    if entendido is not None:
        r["sin_resolver"] = list(entendido.sin_resolver)       # @menciones o #etiquetas que no se pudieron resolver y se dejaron en el texto
    return _ok(r, 201)


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
            "fecha_inicio", "fecha_vencimiento", "categoria_outlook", "estimacion_min",
        )
        if campo in datos
    }
    if "estimacion" in datos:       # texto libre como en la web («1h30», «45 min», «2» = horas): lo interpreta el servidor
        texto = str(datos.get("estimacion") or "").strip()
        minutos = quickadd.duracion_a_minutos(texto)
        if texto and minutos is None:
            return _err("No entiendo esa estimación: prueba «1h30», «45 min» o «2» (horas).", 400, "estimacion_invalida", "estimacion")
        campos["estimacion_min"] = minutos
    error = _error_referencia("tareas_outlook", g.usuario_id, datos, excepto_id=tarea_id)
    if error:
        return error
    if campos:
        try:
            db.editar_tarea_outlook(g.usuario_id, tarea_id, **campos)
        except ValueError as e:                  # «en revisión» solo se pone y se quita por el flujo de revisión
            return _err(str(e), 409, "estado_en_revision", "estado")
    _guardar_referencia("tareas_outlook", g.usuario_id, tarea_id, datos)
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
    previa = db.obtener_tarea_outlook(g.usuario_id, tarea_id)
    if previa is None:
        abort(404, "Tarea no encontrada.")
    if db.tarea_bloqueada(tarea_id):
        return _err("Esta tarea espera a otras que todavía no están completadas.", 409, "tarea_bloqueada")
    from . import tareas_trabajo
    impedimento = tareas_trabajo.impedimento_de_cierre(tarea_id)
    if impedimento:
        return _err(impedimento[1], 409, impedimento[0])
    db.completar_tarea_outlook(g.usuario_id, tarea_id)
    from .rutas_tareas import _avisar_desbloqueos
    _avisar_desbloqueos(g.usuario_id, tarea_id, previa["estado"] == "completada")
    return _ok(_dict(db.obtener_tarea_outlook(g.usuario_id, tarea_id)))


# --- Tiquets (soporte interno: errores/sugerencias) -----------------------
#
# Tablero COMPARTIDO entre todos los usuarios (igual que app/rutas_tiquets.py,
# mismos permisos exactos: cualquiera lee, solo el dueño -- o un admin --
# puede editar/borrar, y solo un admin puede mover de estado). token_required
# no fija g.es_admin (solo lo hace la sesión web), así que aquí se comprueba
# con db.es_admin(g.usuario_id) explícitamente donde hace falta.

def _puede_borrar_tiquet(tiquet) -> bool:
    return tiquet["usuario_id"] == g.usuario_id or db.es_admin(g.usuario_id)


def _puede_editar_tiquet(tiquet) -> bool:
    return tiquet["usuario_id"] == g.usuario_id and tiquet["estado"] == "sin_revisar"


@api_bp.route("/tiquets", methods=["GET"])
@token_required
def listar_tiquets():
    return _ok_paginado(db.listar_tiquets(
        estado=request.args.get("estado") or None,
        tipo=request.args.get("tipo") or None,
    ))


@api_bp.route("/tiquets", methods=["POST"])
@token_required
def crear_tiquet():
    datos = _body()
    tipo = datos.get("tipo", "")
    titulo = (datos.get("titulo") or "").strip()
    if not titulo or tipo not in ("error", "sugerencia"):
        return _err("Faltan datos: título y tipo (error/sugerencia) son obligatorios.")
    tiquet_id = db.crear_tiquet(g.usuario_id, tipo=tipo, titulo=titulo, descripcion=datos.get("descripcion") or None)
    return _ok(_dict(db.obtener_tiquet(tiquet_id)), 201)


@api_bp.route("/tiquets/<int:tiquet_id>", methods=["PUT"])
@token_required
def editar_tiquet(tiquet_id: int):
    tiquet = db.obtener_tiquet(tiquet_id)
    if tiquet is None:
        abort(404, "Tiquet no encontrado.")
    if not _puede_editar_tiquet(tiquet):
        return _err("Este tiquet no es tuyo, o ya no está 'sin revisar'.", 403)
    datos = _body()
    titulo = (datos.get("titulo") or tiquet["titulo"]).strip()
    tipo = datos.get("tipo") or tiquet["tipo"]
    if not titulo or tipo not in ("error", "sugerencia"):
        return _err("Faltan datos: título y tipo (error/sugerencia) son obligatorios.")
    db.editar_tiquet(
        g.usuario_id, tiquet_id, titulo=titulo,
        descripcion=datos.get("descripcion", tiquet["descripcion"]), tipo=tipo,
    )
    return _ok(_dict(db.obtener_tiquet(tiquet_id)))


@api_bp.route("/tiquets/<int:tiquet_id>", methods=["DELETE"])
@token_required
def eliminar_tiquet(tiquet_id: int):
    tiquet = db.obtener_tiquet(tiquet_id)
    if tiquet is None:
        abort(404, "Tiquet no encontrado.")
    if not _puede_borrar_tiquet(tiquet):
        return _err("Este tiquet no es tuyo.", 403)
    db.eliminar_tiquet(tiquet_id)
    return _ok()


@api_bp.route("/tiquets/<int:tiquet_id>/estado", methods=["POST"])
@token_required
def cambiar_estado_tiquet(tiquet_id: int):
    if not db.es_admin(g.usuario_id):
        return _err("Solo un administrador puede mover tiquets de estado.", 403)
    if db.obtener_tiquet(tiquet_id) is None:
        abort(404, "Tiquet no encontrado.")
    estado = _body().get("estado", "")
    if estado not in ("sin_revisar", "en_revision", "finalizado"):
        return _err("Estado no válido.")
    db.cambiar_estado_tiquet(tiquet_id, estado)
    return _ok(_dict(db.obtener_tiquet(tiquet_id)))


# --- Calendario fiscal (Fase F5: paridad móvil) ----------------------------
#
# Mismo dato que app/rutas_fiscal.py (filtrado por g.tenant_id, no
# g.usuario_id -- son datos de la gestoría, ver comentario de cabecera de
# clientes_fiscales en db.py), pero como API REST para la app móvil. A
# diferencia de la web, "generar vencimientos" aquí no tiene paso
# intermedio de edición de fechas propuestas -- inserta directamente, para
# no tener que replicar en Flutter esa pantalla de confirmación fila a
# fila (quien quiera ajustar una fecha después, edita el vencimiento ya
# creado, igual que puede hacer desde la web).

def _version_if_match() -> int | None:
    """La versión que quien llama dice haber leído (cabecera `If-Match`, con o sin comillas); `None` si no la manda (compatible con quien no la usa)."""
    crudo = (request.headers.get("If-Match") or "").strip()
    if crudo.startswith("W/"):
        crudo = crudo[2:]
    crudo = crudo.strip('"')
    return int(crudo) if crudo.isdigit() else None


def _exigir_tenant_api():
    if g.tenant_id is None:
        return _err("Esta cuenta no tiene un tenant asignado -- pide a un admin que te asigne uno.", 403)
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.path.startswith("/api/v1/fiscal"):
        from . import acceso
        if acceso.es_solo_auditor(g.tenant_id, g.usuario_id):
            return _err("Con el rol de auditor solo puedes leer.", 403, "solo_lectura")
    return None


@api_bp.route("/fiscal/clientes", methods=["GET"])
@token_required
def listar_clientes_fiscales():
    error = _exigir_tenant_api()
    if error:
        return error
    ref = request.args.get("referencia_externa")
    if ref:
        encontrado = db.id_por_referencia_externa("clientes_fiscales", g.tenant_id, ref)
        return _ok_paginado([db.obtener_cliente_fiscal(g.tenant_id, encontrado)] if encontrado else [])
    return _ok_paginado(db.listar_clientes_fiscales(g.tenant_id, q=request.args.get("q") or None))


@api_bp.route("/fiscal/clientes", methods=["POST"])
@token_required
def crear_cliente_fiscal():
    error = _exigir_tenant_api()
    if error:
        return error
    datos = _body()
    nombre = (datos.get("nombre") or "").strip()
    if not nombre:
        return _err("El nombre es obligatorio.")
    error = _error_referencia("clientes_fiscales", g.tenant_id, datos)
    if error:
        return error
    extra, error = _campos_cliente_fiscal(datos)
    if error:
        return error
    cliente_id = db.crear_cliente_fiscal(
        g.tenant_id, nombre, nif=datos.get("nif"), notas=datos.get("notas"),
        modelos_fiscales=datos.get("modelos_fiscales") or None, email=extra.pop("email", None), pais=extra.get("pais") or "ES",
    )
    if extra:
        db.editar_cliente_fiscal(g.tenant_id, cliente_id, **extra)
    alta_cliente.vincular_espocrm(g.tenant_id, cliente_id, nombre)
    _guardar_referencia("clientes_fiscales", g.tenant_id, cliente_id, datos)
    return _ok(_dict(db.obtener_cliente_fiscal(g.tenant_id, cliente_id)), 201)


@api_bp.route("/fiscal/clientes/<int:cliente_id>", methods=["GET"])
@token_required
def obtener_cliente_fiscal(cliente_id: int):
    error = _exigir_tenant_api()
    if error:
        return error
    cliente = db.obtener_cliente_fiscal(g.tenant_id, cliente_id)
    if cliente is None:
        abort(404, "Cliente fiscal no encontrado.")
    datos = dict(cliente)
    datos["modelos_fiscales"] = db.modelos_fiscales_de_cliente(cliente)
    db.registrar_acceso_cliente(g.tenant_id, cliente_id, g.usuario_id, "ficha_vista", "vía API")
    return _ok(datos)


@api_bp.route("/fiscal/clientes/<int:cliente_id>", methods=["PUT"])
@token_required
def editar_cliente_fiscal(cliente_id: int):
    error = _exigir_tenant_api()
    if error:
        return error
    actual = db.obtener_cliente_fiscal(g.tenant_id, cliente_id)
    if actual is None:
        abort(404, "Cliente fiscal no encontrado.")
    esperada = _version_if_match()
    if esperada is not None and esperada != actual["version"]:
        return _err_version("Otra persona ha cambiado este cliente: recárgalo y revisa los cambios.", actual["version"])
    datos = _body()
    campos = {}
    if "nombre" in datos:
        campos["nombre"] = (datos["nombre"] or "").strip()
    if "nif" in datos:
        campos["nif"] = datos["nif"]
    if "notas" in datos:
        campos["notas"] = datos["notas"]
    if "modelos_fiscales" in datos:
        campos["modelos_fiscales"] = db.serializar_modelos_fiscales(datos["modelos_fiscales"])
    if "generacion_automatica" in datos:
        campos["generacion_automatica"] = 1 if datos["generacion_automatica"] else 0
    extra, error = _campos_cliente_fiscal(datos)
    if error:
        return error
    campos.update(extra)
    error = _error_referencia("clientes_fiscales", g.tenant_id, datos, excepto_id=cliente_id)
    if error:
        return error
    db.editar_cliente_fiscal(g.tenant_id, cliente_id, **campos)
    db.registrar_acceso_cliente(g.tenant_id, cliente_id, g.usuario_id, "cliente_editado", "vía API")
    _guardar_referencia("clientes_fiscales", g.tenant_id, cliente_id, datos)
    return _ok(_dict(db.obtener_cliente_fiscal(g.tenant_id, cliente_id)))


@api_bp.route("/fiscal/clientes/<int:cliente_id>", methods=["DELETE"])
@token_required
def eliminar_cliente_fiscal(cliente_id: int):
    error = _exigir_tenant_api()
    if error:
        return error
    if db.obtener_cliente_fiscal(g.tenant_id, cliente_id) is None:
        abort(404, "Cliente fiscal no encontrado.")
    db.eliminar_cliente_fiscal(g.tenant_id, cliente_id)
    db.registrar_acceso_cliente(g.tenant_id, cliente_id, g.usuario_id, "cliente_eliminado", "vía API")
    return _ok()


@api_bp.route("/fiscal/clientes/<int:cliente_id>/generar-vencimientos", methods=["POST"])
@token_required
def generar_vencimientos_fiscales(cliente_id: int):
    """Cuerpo: `modelos` (por defecto los del cliente), `anio` (por defecto el actual). Usa el país de tributación del cliente y
    no duplica: lo que ya existe se devuelve en `omitidos`. Respuesta: `{"creados": n, "ids": [...], "omitidos": n}`."""
    error = _exigir_tenant_api()
    if error:
        return error
    cliente = db.obtener_cliente_fiscal(g.tenant_id, cliente_id)
    if cliente is None:
        abort(404, "Cliente fiscal no encontrado.")
    datos = _body()
    modelos = datos.get("modelos") or db.modelos_fiscales_de_cliente(cliente)
    anio = datos.get("anio") or datetime.now().year
    if not modelos:
        return _err("Indica al menos un modelo.")
    if not isinstance(anio, int) or not 2000 <= anio <= 2100:
        return _err("anio debe ser un año válido.", 400, "peticion_invalida", "anio")
    from . import nucleo
    creados, omitidos = [], 0
    for p in nucleo.propuestas_vencimientos_ajustadas(g.tenant_id, modelos, anio, cliente["pais"]):
        if db.vencimiento_fiscal_existente(g.tenant_id, cliente_id, p["modelo"], p["periodo"]) is not None:
            omitidos += 1
            continue
        creados.append(db.crear_vencimiento_fiscal(g.tenant_id, cliente_id, p["modelo"], p["periodo"], p["fecha_limite"]))
    return _ok({"creados": len(creados), "ids": creados, "omitidos": omitidos}, 201)


@api_bp.route("/fiscal/vencimientos", methods=["GET"])
@token_required
def listar_vencimientos_fiscales():
    """Filtros: `estado`, `cliente_id`, `desde`/`hasta` (fecha límite, YYYY-MM-DD), `pais`. Paginación en SQL con `limit`/`offset`
    (sin `limit`, todos) y total en `X-Total-Count`."""
    error = _exigir_tenant_api()
    if error:
        return error
    filtros = dict(
        estado=request.args.get("estado") or None, cliente_fiscal_id=request.args.get("cliente_id", type=int),
        desde=request.args.get("desde") or None, hasta=request.args.get("hasta") or None, pais=request.args.get("pais") or None,
    )
    limit = request.args.get("limit", type=int)
    offset = max(0, request.args.get("offset", default=0, type=int) or 0)
    filas = db.listar_vencimientos_fiscales(g.tenant_id, limite=None if limit is None else max(1, min(limit, 1000)), offset=offset, **filtros)
    respuesta, status = _ok(_dicts(filas))
    respuesta.headers["X-Total-Count"] = str(db.contar_vencimientos_fiscales(g.tenant_id, **filtros))
    return respuesta, status


@api_bp.route("/fiscal/vencimientos/<int:vencimiento_id>", methods=["PUT"])
@token_required
def editar_vencimiento_fiscal(vencimiento_id: int):
    error = _exigir_tenant_api()
    if error:
        return error
    vencimiento = db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id)
    if vencimiento is None:
        abort(404, "Vencimiento no encontrado.")
    datos = _body()
    esperada = _version_if_match()
    if esperada is not None and esperada != vencimiento["version"]:
        return _err_version("Otra persona ha cambiado este vencimiento: recárgalo y revisa los cambios.", vencimiento["version"])
    campos = {k: datos[k] for k in db.CAMPOS_VENCIMIENTO_FISCAL if k in datos}
    if "estado" in campos:
        from . import obligaciones
        try:
            obligaciones.exigir_para_cambiar_estado(g.tenant_id, g.usuario_id, vencimiento, campos["estado"])
        except ValueError as e:
            return _err(str(e), 409, "flujo_fiscal")
    db.editar_vencimiento_fiscal(g.tenant_id, vencimiento_id, **campos)
    nuevo = (campos.get("documento_solicitado") or "").strip()
    if nuevo and nuevo != vencimiento["documento_solicitado"]:
        # Como en la web: la petición NUEVA de un documento avisa al cliente por correo (best-effort).
        cliente = db.obtener_cliente_fiscal(g.tenant_id, vencimiento["cliente_fiscal_id"])
        if cliente is not None and cliente["email"]:
            from . import notificaciones_email as _ne
            try:
                _ne.enviar_solicitud_documento(cliente["email"], nuevo, url_for("portal_cliente.entrar", _external=True), tenant_id=g.tenant_id)
            except _ne.ErrorNotificacionesEmail:
                pass
    return _ok(_dict(db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id)))


@api_bp.route("/fiscal/vencimientos/<int:vencimiento_id>/presentado", methods=["POST"])
@token_required
def marcar_presentado_vencimiento_fiscal(vencimiento_id: int):
    """Marca el vencimiento como presentado, igual que en la web: genera la constancia en PDF (visible para el cliente en su portal),
    guarda el justificante oficial si se adjunta (multipart, campo `justificante`: imagen o PDF, hasta 8 MB) y emite el evento
    `vencimiento.presentado`."""
    error = _exigir_tenant_api()
    if error:
        return error
    vencimiento = db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id)
    if vencimiento is None:
        abort(404, "Vencimiento no encontrado.")
    from .rutas_fiscal import _generar_constancia, _guardar_justificante
    from . import obligaciones
    try:
        obligaciones.exigir_para_marcar_presentado(g.tenant_id, g.usuario_id, vencimiento, con_justificante=bool(request.files.get("justificante") and request.files["justificante"].filename))
    except ValueError as e:
        return _err(str(e), 409, "flujo_fiscal")
    db.marcar_presentado_vencimiento_fiscal(g.tenant_id, vencimiento_id, g.usuario_id)
    justificante = request.files.get("justificante")
    if justificante is not None and justificante.filename and not _guardar_justificante(vencimiento_id, justificante):
        return _err("Justificante no válido: solo imágenes o PDF, hasta 8 MB (el vencimiento ya queda presentado).", 400, "justificante_invalido", "justificante")
    try:
        _generar_constancia(vencimiento)
    except Exception:  # noqa: BLE001 -- un fallo al generar la constancia nunca deshace el «presentado»
        pass
    try:
        eventos.emitir("vencimiento.presentado", g.tenant_id, {"vencimiento_id": vencimiento_id, "modelo": vencimiento["modelo"], "periodo": vencimiento["periodo"]})
    except Exception:  # noqa: BLE001
        pass
    return _ok(_dict(db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id)))


@api_bp.route("/fiscal/vencimientos/<int:vencimiento_id>", methods=["DELETE"])
@token_required
def eliminar_vencimiento_fiscal(vencimiento_id: int):
    error = _exigir_tenant_api()
    if error:
        return error
    if db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id) is None:
        abort(404, "Vencimiento no encontrado.")
    db.eliminar_vencimiento_fiscal(g.tenant_id, vencimiento_id)
    return _ok()


# --- Fichaje (registro horario) -------------------------------------------
#
# Solo la parte de trabajador (fichar/historial/mis-datos) -- la
# administración (resumen de un tenant, export CSV/PDF) se queda en
# web/escritorio, no tiene sentido revisarla desde el móvil.

@api_bp.route("/fichaje/estado", methods=["GET"])
@token_required
def estado_fichaje():
    return _ok({
        "estado": db.estado_actual_fichaje(g.usuario_id),
        "datos_completos": db.fichaje_datos_completos(g.usuario_id),
    })


@api_bp.route("/fichaje/marcar", methods=["POST"])
@token_required
def marcar_fichaje():
    """`marca_tiempo`/`cliente_uuid` opcionales: los manda la app móvil
    cuando el fichaje se pulsó sin cobertura y se sincroniza más tarde (ver
    SyncService) -- conservan la hora real de la pulsación y evitan
    duplicar la fila si la sincronización se reintenta."""
    datos = _body()
    tipo = datos.get("tipo", "")
    if tipo not in ("entrada", "pausa_inicio", "pausa_fin", "salida"):
        return _err("Tipo de fichaje no válido.")
    if not db.fichaje_datos_completos(g.usuario_id):
        return _err("Antes de fichar hace falta rellenar nombre completo y DNI/NIE en Mis datos.")
    tenant = db.tenant_de_usuario(g.usuario_id)
    # Geolocalización (Fase G3): igual que la web, el servidor solo la
    # guarda si el tenant la tiene activada -- no se fía de que el móvil
    # solo la mande cuando corresponda.
    latitud = longitud = None
    if tenant and tenant["fichaje_geolocalizacion"]:
        latitud = datos.get("latitud")
        longitud = datos.get("longitud")
    try:
        db.fichar(
            g.usuario_id, tenant["id"] if tenant else None, tipo, origen="movil",
            marca_tiempo=datos.get("marca_tiempo"), cliente_uuid=datos.get("cliente_uuid"),
            latitud=latitud, longitud=longitud,
        )
    except ValueError as e:
        return _err(str(e))
    return _ok({"estado": db.estado_actual_fichaje(g.usuario_id)})


@api_bp.route("/fichaje/resumen-semana", methods=["GET"])
@token_required
def resumen_semana_fichaje():
    """Horas de la semana en curso frente a la jornada contratada, y su reparto
    por días (lunes a domingo), para el panel de fichaje de la app."""
    from . import fichaje_export

    resumen = fichaje_export.resumen_semana(g.tenant_id, g.usuario_id)
    dias = fichaje_export.semana_por_dias(g.tenant_id, g.usuario_id)
    return _ok({
        "segundos": resumen["segundos"], "contratados": resumen["contratados"], "diferencia": resumen["diferencia"],
        "porcentaje": resumen["porcentaje"], "en_curso": resumen["en_curso"],
        "dias": [{"fecha": d["fecha"].isoformat(), "segundos": d["segundos"], "hoy": d["hoy"]} for d in dias],
    })


@api_bp.route("/fichaje/historial", methods=["GET"])
@token_required
def historial_fichaje():
    return _ok(_dicts(db.listar_fichajes(
        g.usuario_id, desde=request.args.get("desde") or None, hasta=request.args.get("hasta") or None,
    )))


@api_bp.route("/fichaje/mis-datos", methods=["GET"])
@token_required
def obtener_mis_datos_fichaje():
    return _ok(_dict(db.obtener_fichaje_datos(g.usuario_id)))


@api_bp.route("/fichaje/mis-datos", methods=["POST"])
@token_required
def guardar_mis_datos_fichaje():
    datos = _body()
    nombre_completo = (datos.get("nombre_completo") or "").strip()
    dni_nie = (datos.get("dni_nie") or "").strip()
    if not nombre_completo or not dni_nie:
        return _err("Nombre completo y DNI/NIE son obligatorios.")
    jornada = datos.get("jornada_semanal_horas")
    db.guardar_fichaje_datos(
        g.usuario_id, nombre_completo, dni_nie,
        numero_afiliacion_ss=datos.get("numero_afiliacion_ss") or None,
        categoria_profesional=datos.get("categoria_profesional") or None,
        tipo_contrato=datos.get("tipo_contrato") or None,
        fecha_alta=datos.get("fecha_alta") or None,
        jornada_semanal_horas=float(jornada) if jornada not in (None, "") else None,
        convenio_colectivo=datos.get("convenio_colectivo") or None,
    )
    return _ok(_dict(db.obtener_fichaje_datos(g.usuario_id)))


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
    consulta = correo.consulta_de_busqueda(g.usuario_id, getattr(g, "tenant_id", None), request.args.get("q"))
    mensajes = correo.listar_mensajes(
        cuenta_id,
        carpeta=request.args.get("carpeta", "INBOX"),
        solo_no_leidos=request.args.get("no_leidos") == "1" or consulta.solo_no_leidos,
        texto=consulta.texto or None,
        **consulta.filtros,
        limite=preferencias["limite_mensajes"],
        incluir_pospuestos=request.args.get("pospuestos") == "1",
    )
    return _ok_paginado(mensajes)


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
    respuesta = Response(adjunto["contenido"], mimetype=adjunto["tipo_mime"])
    respuesta.headers.set("Content-Disposition", "attachment", filename=adjunto["nombre_archivo"])
    return respuesta


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
    correo.asignar_categoria(g.usuario_id, mensaje_id, _body().get("categoria_id"))
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


MAX_ADJUNTOS_ENVIO = 20


@api_bp.route("/correo/enviar", methods=["POST"])
@token_required
def enviar_correo():
    """Envía un correo (o lo programa). Dos formas de mandarlo:

    - **JSON**: `adjuntos`: `[{"nombre", "tipo", "contenido_base64"}]`.
    - **multipart/form-data**: campos de texto y ficheros en `adjuntos` (varios). Recomendado para archivos grandes.

    Campos: `cuenta_id`, `destinatarios`, `asunto`, `cuerpo_html`, `cc`, `bcc`, `en_respuesta_a` (Message-ID), `seguimiento_dias`
    («avísame si no responde», 1-30) y `programar_para` (`YYYY-MM-DDTHH:MM`, hora del servidor: queda en cola y se envía entonces,
    respuesta 202 con `envio_id`). Máx. 20 adjuntos y 25 MB en total. Respuesta: `{"enviado": true, "message_id": "..."}`."""
    if request.mimetype == "multipart/form-data":
        datos = request.form.to_dict()
        adjuntos = [{"nombre": f.filename, "tipo": f.mimetype or "application/octet-stream", "bytes": f.read()} for f in request.files.getlist("adjuntos") if f and f.filename]
    else:
        datos = _body()
        adjuntos = []
        for a in datos.get("adjuntos") or []:
            if not isinstance(a, dict) or not a.get("contenido_base64"):
                continue
            try:
                contenido = base64.b64decode(a["contenido_base64"], validate=True)
            except (ValueError, TypeError):
                return _err(f"El adjunto «{a.get('nombre', 'adjunto')}» no es base64 válido.", 400, "adjunto_invalido", "adjuntos")
            adjuntos.append({"nombre": a.get("nombre") or "adjunto", "tipo": a.get("tipo") or "application/octet-stream", "bytes": contenido})
    if len(adjuntos) > MAX_ADJUNTOS_ENVIO:
        return _err(f"Máximo {MAX_ADJUNTOS_ENVIO} adjuntos por correo.", 400, "demasiados_adjuntos", "adjuntos")
    try:
        cuenta_id = int(datos.get("cuenta_id")) if str(datos.get("cuenta_id") or "").lstrip("-").isdigit() else None
        seguimiento = db.seguimiento_dias_valido(datos.get("seguimiento_dias")) if datos.get("seguimiento_dias") not in (None, "") else None
        argumentos = dict(
            cc=datos.get("cc", "") or "", bcc=datos.get("bcc", "") or "", en_respuesta_a=datos.get("en_respuesta_a") or None,
            adjuntos=adjuntos or None, seguimiento_dias=seguimiento,
        )
        programar = (datos.get("programar_para") or "").strip()
        if programar:
            try:
                momento = datetime.fromisoformat(programar)
            except ValueError:
                return _err("programar_para debe ser YYYY-MM-DDTHH:MM.", 400, "peticion_invalida", "programar_para")
            if momento <= datetime.now() + timedelta(minutes=1) or momento > datetime.now() + timedelta(days=366):
                return _err("programar_para tiene que ser futuro (y dentro de un año).", 400, "peticion_invalida", "programar_para")
            enviar_en = momento.isoformat(timespec="seconds")
            envio_id = correo.encolar_envio(
                g.usuario_id, cuenta_id, datos.get("destinatarios", ""), datos.get("asunto", ""), datos.get("cuerpo_html", ""),
                enviar_en=enviar_en, programado=True, **argumentos,
            )
            return _ok({"programado": True, "envio_id": envio_id, "enviar_en": enviar_en}, 202)
        message_id = correo.construir_y_enviar(
            g.usuario_id, cuenta_id, datos.get("destinatarios", ""), datos.get("asunto", ""), datos.get("cuerpo_html", ""), **argumentos,
        )
    except correo.ErrorCorreo as e:
        return _err(str(e))
    return _ok({"enviado": True, "message_id": message_id})


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


def _sse(evento: dict) -> str:
    return f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"


# Variantes en streaming (asistente de voz, Fase V1 del plan
# "eventual-herding-kitten") -- mismo formato SSE que su equivalente web en
# app/rutas_ia.py, ver ia_asistente.procesar_turno_stream para los tipos de
# evento. Las rutas de arriba (/ia/mensaje, /ia/confirmar) no se tocan.


@api_bp.route("/ia/mensaje/stream", methods=["POST"])
@token_required
def enviar_mensaje_ia_stream():
    texto = _body().get("texto", "")
    usuario_id = g.usuario_id

    def generar():
        try:
            for evento in ia_asistente.procesar_turno_stream(usuario_id, texto):
                yield _sse(evento)
        except Exception as e:  # noqa: BLE001 -- el stream ya está abierto, no se puede devolver un error HTTP normal
            yield _sse({"tipo": "error", "mensaje": str(e)})

    return Response(stream_with_context(generar()), mimetype="text/event-stream")


@api_bp.route("/ia/confirmar/stream", methods=["POST"])
@token_required
def confirmar_ia_stream():
    aceptar = bool(_body().get("aceptar"))
    usuario_id = g.usuario_id

    def generar():
        try:
            for evento in ia_asistente.confirmar_pendiente_stream(usuario_id, aceptar):
                yield _sse(evento)
        except Exception as e:  # noqa: BLE001
            yield _sse({"tipo": "error", "mensaje": str(e)})

    return Response(stream_with_context(generar()), mimetype="text/event-stream")


@api_bp.route("/ia/vaciar", methods=["POST"])
@token_required
def vaciar_ia():
    """Abre una conversación nueva (la anterior se conserva en /ia/conversaciones)."""
    db.vaciar_mensajes_ia(g.usuario_id)
    return _ok()


@api_bp.route("/ia/conversaciones", methods=["GET"])
@token_required
def listar_conversaciones_ia():
    return _ok({
        "activa": db.conversacion_ia_activa_id(g.usuario_id, crear=False),
        "conversaciones": _dicts(db.listar_conversaciones_ia(g.usuario_id)),
    })


@api_bp.route("/ia/conversaciones", methods=["POST"])
@token_required
def crear_conversacion_ia():
    return _ok({"id": db.crear_conversacion_ia(g.usuario_id)}, 201)


@api_bp.route("/ia/conversaciones/<int:conversacion_id>/activar", methods=["POST"])
@token_required
def activar_conversacion_ia(conversacion_id: int):
    if not db.activar_conversacion_ia(g.usuario_id, conversacion_id):
        abort(404, "Conversación no encontrada.")
    return _ok()


@api_bp.route("/ia/conversaciones/<int:conversacion_id>/renombrar", methods=["POST"])
@token_required
def renombrar_conversacion_ia(conversacion_id: int):
    try:
        encontrada = db.renombrar_conversacion_ia(g.usuario_id, conversacion_id, _body().get("titulo", ""))
    except ValueError as e:
        return _err(str(e))
    if not encontrada:
        abort(404, "Conversación no encontrada.")
    return _ok()


@api_bp.route("/ia/conversaciones/<int:conversacion_id>", methods=["DELETE"])
@token_required
def eliminar_conversacion_ia(conversacion_id: int):
    if not db.eliminar_conversacion_ia(g.usuario_id, conversacion_id):
        abort(404, "Conversación no encontrada.")
    return _ok()


@api_bp.route("/ia/modelos", methods=["GET"])
@token_required
def listar_modelos_ia():
    return _ok(ia_asistente.listar_modelos_gratuitos())


@api_bp.route("/ia/atajos", methods=["GET"])
@token_required
def listar_atajos_ia():
    """Atajos de prompts: los 6 de serie (sin id) y los propios del usuario."""
    return _ok(ia_atajos.atajos_para(g.usuario_id))


@api_bp.route("/ia/atajos", methods=["POST"])
@token_required
def crear_atajo_ia():
    datos = _body()
    try:
        atajo_id = db.crear_atajo_ia(g.usuario_id, datos.get("titulo", ""), datos.get("prompt", ""))
    except ValueError as e:
        return _err(str(e))
    return _ok({"id": atajo_id}, 201)


@api_bp.route("/ia/atajos/<int:atajo_id>", methods=["DELETE"])
@token_required
def eliminar_atajo_ia(atajo_id: int):
    if not db.eliminar_atajo_ia(g.usuario_id, atajo_id):
        abort(404, "Atajo no encontrado.")
    return _ok()


@api_bp.route("/ia/ajustes", methods=["GET"])
@token_required
def obtener_ajustes_ia():
    preferencias = _dict(db.obtener_preferencias_ia(g.usuario_id))
    preferencias["api_key_configurada"] = bool(ia_asistente.obtener_api_keys(g.usuario_id))
    return _ok(preferencias)


@api_bp.route("/ia/ajustes", methods=["POST"])
@token_required
def guardar_ajustes_ia():
    datos = _body()
    db.guardar_preferencias_ia(
        g.usuario_id, modelo=datos.get("modelo", ""), modo_autonomo=bool(datos.get("modo_autonomo", False)),
        solo_lectura=bool(datos["solo_lectura"]) if "solo_lectura" in datos else None,
    )
    nueva_clave = (datos.get("api_key") or "").strip()
    if nueva_clave:
        # La app móvil solo tiene un campo de clave (a diferencia del textarea
        # "una por línea" de ia_ajustes.html en la web) -- fija la lista de
        # fallback a esta única clave, sustituyendo cualquier lista anterior.
        ia_asistente.guardar_api_keys(g.usuario_id, [nueva_clave])
    if datos.get("borrar_api_key"):
        ia_asistente.borrar_api_key(g.usuario_id)
    return _ok()


# --- Herramientas (Fase 9, app móvil) ---------------------------------------

@api_bp.route("/herramientas", methods=["GET"])
@token_required
def listar_herramientas():
    """Mismo catálogo que /herramientas en la web (app/herramientas.py),
    excepto "chat": Element se consume desde el móvil como cliente Matrix
    nativo (ver /chat/config), no como WebView de Element-web. Mismo
    filtro de visibilidad por tenant que la web (ver
    app/main.py:herramientas_vista()). También incluye FacturaScripts como
    entrada sintética, igual que hace herramientas.html, porque no vive en
    herramientas.HERRAMIENTAS al no ser una instancia compartida (cada
    tenant tiene su propio contenedor y URL, ver HOSTING.md 8.21) — la
    versión móvil se había quedado sin este apartado."""
    tenant = db.tenant_de_usuario(g.usuario_id)
    ocultas = db.herramientas_ocultas_de_tenant(tenant["id"]) if tenant else set()
    vivas = estado_herramientas.estados()
    # La app móvil enseña en gris lo no disponible (campo `disponible`): se marca así también lo que está desplegado pero no responde ahora, para que no sea un enlace muerto.
    lista = [{**h, "disponible": bool(h.get("disponible", True)) and bool(vivas.get(h["id"]))} for h in herramientas.HERRAMIENTAS if h["id"] != "chat" and h["id"] not in ocultas]
    facturascripts_url = tenant["facturascripts_url"] if tenant else None
    lista.append({
        "id": "facturascripts",
        "nombre": "Facturación",
        "descripcion": "Facturas, presupuestos y contabilidad de tu cliente (FacturaScripts).",
        "icono": "🧮",
        "icono_logo": "facturacion.png",
        "color": "#2f6fce",
        "categoria": "Documentos y datos",
        "url": facturascripts_url or "",
        "sso": False,
        "disponible": facturascripts_url is not None,
    })
    return _ok(lista)


@api_bp.route("/chat/config", methods=["GET"])
@token_required
def obtener_chat_config():
    """Configuración para el cliente Matrix nativo de la app móvil — la URL
    del homeserver de Synapse, no la de Element-web."""
    return _ok({"homeserver_url": herramientas.MATRIX_HOMESERVER_URL})


# --- Dispositivos push (Fase 10, notificaciones) ---------------------------

@api_bp.route("/dispositivos-push", methods=["POST"])
@token_required
def registrar_dispositivo_push():
    """La app móvil llama esto tras login y cada vez que Firebase le
    entrega un token FCM nuevo (puede rotar) -- ver
    mobile/lib/services/push_service.dart."""
    datos = _body()
    fcm_token = (datos.get("fcm_token") or "").strip()
    plataforma = datos.get("plataforma") or ""
    if not fcm_token or plataforma not in ("android", "ios"):
        return _err("Faltan datos: fcm_token y plataforma (android/ios) son obligatorios.")
    db.registrar_dispositivo_push(g.usuario_id, fcm_token, plataforma)
    return _ok()


@api_bp.route("/dispositivos-push", methods=["DELETE"])
@token_required
def eliminar_dispositivo_push():
    """Se llama en logout para dejar de mandar push a un dispositivo del
    que se ha cerrado sesión."""
    fcm_token = (_body().get("fcm_token") or "").strip()
    if not fcm_token:
        return _err("Falta fcm_token.")
    db.eliminar_dispositivo_push(g.usuario_id, fcm_token)
    return _ok()


# --- Perfil de usuario (Fase G1: espacio de ajustes de usuario) -----------
# Espejo de /ajustes/perfil (app/main.py) para la app móvil. Cambiar
# contraseña/email se deja SOLO en la web (el flujo `settings` de Kratos
# es HTML, no una API JSON limpia para Flutter) -- el móvil enlaza a la
# web para eso, mismo criterio que ya usa con las claves de OpenRouter.

def _perfil_json(perfil) -> dict:
    """El BLOB del avatar no es serializable a JSON -- se manda solo si
    hay uno (tiene_avatar), la imagen en sí se pide aparte a
    GET /api/v1/avatar/<id>, igual que la web usa una URL <img> separada
    en vez de meter el binario en el propio documento HTML."""
    datos = dict(perfil)
    datos["tiene_avatar"] = datos.pop("avatar_contenido") is not None
    datos.pop("avatar_tipo_mime", None)
    datos["apariencia"] = api_contexto.apariencia_de(g.usuario_id)      # API 1.5: tema, densidad e idioma de la cuenta
    return datos


@api_bp.route("/perfil", methods=["GET"])
@token_required
def obtener_perfil():
    return _ok(_perfil_json(db.obtener_perfil_usuario(g.usuario_id)))


@api_bp.route("/perfil", methods=["PUT"])
@token_required
def editar_perfil():
    datos = _body()
    # API 1.5: apariencia en la cuenta (se aplica en la web y en cualquier dispositivo). Un valor no válido es un 400, no se ignora.
    for campo, validos in (("tema", db.TEMAS_VALIDOS), ("densidad", db.DENSIDADES_VALIDAS), ("idioma", api_contexto.IDIOMAS)):
        if campo in datos and datos.get(campo) not in validos:
            return _err(f"Valor no válido para «{campo}»: usa {', '.join(validos)}.", 400, "valor_invalido", campo)
    db.guardar_apariencia_usuario(g.usuario_id, tema=datos.get("tema"), densidad=datos.get("densidad"))
    if datos.get("idioma"):
        db.cambiar_idioma_usuario(g.usuario_id, datos.get("idioma"))
    db.guardar_perfil_usuario(
        g.usuario_id,
        nombre_mostrado=datos.get("nombre_mostrado"),
        notificar_push_vencimientos=datos.get("notificar_push_vencimientos"),
        notificar_push_tiquets=datos.get("notificar_push_tiquets"),
        notificar_resumen_semanal=datos.get("notificar_resumen_semanal"),
    )
    return _ok(_perfil_json(db.obtener_perfil_usuario(g.usuario_id)))


_AVATAR_TIPOS_PERMITIDOS_API = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
_AVATAR_TAMANO_MAXIMO_BYTES_API = 5 * 1024 * 1024


@api_bp.route("/perfil/avatar", methods=["POST"])
@token_required
def subir_avatar_api():
    """Multipart -- mismo procesado (recorte cuadrado + 256×256 + JPEG)
    que app/main.py:subir_avatar(), duplicado a propósito en vez de
    compartir la vista: una es multipart/HTML-redirect, la otra
    multipart/JSON, con validaciones de error distintas (redirect con
    query param vs {"ok": false})."""
    fichero = request.files.get("avatar")
    if not fichero or not fichero.filename:
        return _err("Falta el archivo 'avatar'.")
    if fichero.mimetype not in _AVATAR_TIPOS_PERMITIDOS_API:
        return _err("Formato de imagen no soportado (usa JPEG, PNG o WEBP).")
    datos = fichero.read(_AVATAR_TAMANO_MAXIMO_BYTES_API + 1)
    if len(datos) > _AVATAR_TAMANO_MAXIMO_BYTES_API:
        return _err("La imagen pesa demasiado (máximo 5 MB).")
    try:
        from io import BytesIO

        from PIL import Image

        imagen = Image.open(BytesIO(datos))
        imagen = imagen.convert("RGB") if imagen.mode not in ("RGB", "RGBA") else imagen
        lado = min(imagen.size)
        izquierda = (imagen.width - lado) // 2
        arriba = (imagen.height - lado) // 2
        imagen = imagen.crop((izquierda, arriba, izquierda + lado, arriba + lado)).resize((256, 256))
        buffer = BytesIO()
        imagen.save(buffer, format="JPEG", quality=88)
        db.guardar_avatar_usuario(g.usuario_id, buffer.getvalue(), "image/jpeg")
    except Exception:
        return _err("No se ha podido procesar la imagen -- prueba con otra.")
    return _ok(_perfil_json(db.obtener_perfil_usuario(g.usuario_id)), 201)


@api_bp.route("/perfil/avatar", methods=["DELETE"])
@token_required
def eliminar_avatar_api():
    db.eliminar_avatar_usuario(g.usuario_id)
    return _ok()


@api_bp.route("/avatar/<int:usuario_id>", methods=["GET"])
@token_required
def avatar_api(usuario_id: int):
    """Sin envoltorio {"ok":...}: la respuesta ES la imagen, mismo
    criterio que /correo/mensajes/<id>/adjuntos/<id> (rutas_correo.py).

    Mismo chequeo de tenant que app/main.py:avatar_usuario() -- ver ahí
    el porqué (usuario_id es un parámetro de ruta libre)."""
    if usuario_id != g.usuario_id:
        tenant_objetivo = db.tenant_de_usuario(usuario_id)
        if tenant_objetivo is None or tenant_objetivo["id"] != g.tenant_id:
            abort(404, "Este usuario no tiene avatar.")
    perfil = db.obtener_perfil_usuario(usuario_id)
    if not perfil["avatar_contenido"]:
        abort(404, "Este usuario no tiene avatar.")
    return Response(perfil["avatar_contenido"], mimetype=perfil["avatar_tipo_mime"])


# --- Estado del servicio --------------------------------------------------

@api_bp.route("/health", methods=["GET"])
def estado_servicio():
    """Comprobación de vida para monitores externos (Uptime Kuma, balanceadores). Sin token y sin datos de nadie: 200 si el servicio
    atiende y la base de datos responde; 503 si no. Pensado para sondearse cada minuto."""
    try:
        conn = db.get_connection()
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 -- cualquier fallo de la base de datos es "no disponible"
        logger.exception("health: la base de datos no responde")
        return _err("La base de datos no responde.", 503, "servicio_no_disponible")
    return _ok({"estado": "ok", "version_api": API_VERSION, "base_de_datos": "ok"})


# --- Documentación --------------------------------------------------------

@api_bp.route("/openapi.json", methods=["GET"])
def openapi_json():
    """Documento OpenAPI 3.0 de toda esta API, generado por introspección
    en vivo de este mismo blueprint (ver app/openapi.py) — sin token: es
    documentación pública, la necesita quien todavía no tiene uno. Se
    devuelve tal cual (sin el sobre {"ok":...}) porque el propio formato
    OpenAPI es el contrato esperado por herramientas externas (Postman,
    Insomnia, generadores de cliente), no el de esta API."""
    return jsonify(openapi.generar_spec())
