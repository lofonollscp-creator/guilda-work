"""Decoradores de autenticación compartidos por app/main.py y los blueprints
(rutas_correo.py, rutas_tareas.py, rutas_ia.py, rutas_api.py). Vive en su
propio módulo para que los blueprints puedan importarlo sin crear un import
circular con app/main.py (que a su vez importa los blueprints).

Dos mecanismos independientes que conviven porque atienden a clientes
distintos: `login_required` (cookie de sesión, navegador de escritorio) y
`token_required` (cabecera Authorization: Bearer, app móvil / Fase 2) —
nunca se usan juntos en la misma ruta.

`limiter` (Fase 3, hosting): instancia de Flask-Limiter sin `app` todavía
enlazada — vive aquí (no en main.py) por el mismo motivo que los
decoradores de arriba: rutas_api.py necesita decorar vistas con
`@limiter.limit(...)` sin crear un import circular con main.py, que es
quien luego llama a `limiter.init_app(app)`."""
import hashlib
import os
import threading
import time
from collections import deque
from functools import wraps

from flask import Response, abort, g, jsonify, make_response, redirect, request, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from . import api_areas, db

# Los contadores viven en memoria del proceso: se reinician con cada reinicio
# y no se comparten entre procesos. Con un solo proceso de waitress (el caso
# actual) basta; si algún día hay varios, GUILDA_LIMITER_URI apunta a Redis
# (p. ej. redis://127.0.0.1:6379) sin tocar código. Ver HOSTING.md.
LIMITER_STORAGE_URI = os.environ.get("GUILDA_LIMITER_URI", "memory://")
limiter = Limiter(key_func=get_remote_address, storage_uri=LIMITER_STORAGE_URI)


# Límite de la API por usuario (cualquier token suyo cuenta junto): ventana deslizante de 60 s en memoria.
API_LIMITE_POR_MINUTO = int(os.environ.get("GUILDA_API_LIMITE_POR_MINUTO", "600"))
_ventanas: dict[int, deque] = {}
_lock_ventanas = threading.Lock()


def reiniciar_limite_api() -> None:
    with _lock_ventanas:
        _ventanas.clear()


def _consumir_cupo(usuario_id: int) -> tuple[bool, int, int]:
    """(permitido, restantes, segundos hasta liberar un hueco)."""
    ahora = time.monotonic()
    with _lock_ventanas:
        ventana = _ventanas.setdefault(usuario_id, deque())
        while ventana and ahora - ventana[0] >= 60:
            ventana.popleft()
        if len(ventana) >= API_LIMITE_POR_MINUTO:
            return False, 0, max(1, int(60 - (ahora - ventana[0])) + 1)
        ventana.append(ahora)
        return True, API_LIMITE_POR_MINUTO - len(ventana), max(1, int(60 - (ahora - ventana[0])))


def _error_api(mensaje: str, status: int, codigo: str, **extra):
    from . import peticion

    cuerpo = {"ok": False, "error": mensaje, "codigo": codigo, "request_id": peticion.id_actual(), **extra}
    return jsonify(cuerpo), status


def login_required(vista):
    @wraps(vista)
    def decorada(*args, **kwargs):
        if not g.usuario_id:
            return redirect(url_for("login", siguiente=request.path))
        return vista(*args, **kwargs)
    return decorada


def admin_required(vista):
    """Para el backoffice (Fase 7c) — se apoya en `g.es_admin`, que ya
    fija `_resolver_usuario_actual()` en main.py a partir de
    `usuarios.rol`. Se combina siempre con `login_required` encima."""
    @wraps(vista)
    def decorada(*args, **kwargs):
        if not g.get("es_admin"):
            abort(403)
        return vista(*args, **kwargs)
    return decorada


def token_required(vista):
    @wraps(vista)
    def decorada(*args, **kwargs):
        cabecera = request.headers.get("Authorization", "")
        token = cabecera[7:] if cabecera.startswith("Bearer ") else None
        autenticado = db.autenticar_token_completo(token, request.remote_addr) if token else None
        if autenticado is None:
            return _error_api("Token inválido o ausente.", 401, "token_invalido")
        if autenticado.get("caducado"):
            return _error_api("Este token ha caducado. Crea otro desde Mis dispositivos.", 401, "token_caducado")
        usuario_id, permisos = autenticado["usuario_id"], autenticado["permisos"]
        g.token_id, g.areas_token = autenticado["token_id"], autenticado["areas"]
        # Un token de solo lectura únicamente puede consultar (GET): cualquier
        # otro método se rechaza aquí, antes de llegar a la vista. La única
        # excepción es cerrar su propia sesión (revocarse a sí mismo).
        if permisos == "solo_lectura" and request.method not in ("GET", "HEAD", "OPTIONS") \
                and request.endpoint != "api.logout":
            return _error_api("Este token es de solo lectura.", 403, "token_solo_lectura")
        # Un token limitado a ciertas áreas solo llega a ellas (y nunca a las rutas transversales ni a gestionar tokens).
        if autenticado["areas"] and not api_areas.permite(autenticado["areas"], request.path):
            return _error_api(
                f"Este token solo tiene acceso a: {', '.join(autenticado['areas'])}.", 403, "token_area_no_permitida", areas=autenticado["areas"],
            )
        g.usuario_id = usuario_id
        g.permisos_token = permisos
        # Mismo cálculo que _resolver_usuario_actual() en main.py -- hasta
        # ahora ninguna ruta por token leía g.es_admin/g.gestor_fichajes/
        # g.supervisor_tenant (quedaban sin fijar, ausentes de g por
        # completo), así que cualquier ruta de la app móvil/API que mirara
        # alguno de esos flags fallaría con un AttributeError en vez de
        # comportarse como el usuario que realmente es.
        tenant = db.tenant_de_usuario(usuario_id)
        g.tenant_id = tenant["id"] if tenant else None
        g.es_admin = db.es_admin(usuario_id)
        g.gestor_fichajes = db.es_gestor_fichajes(usuario_id)
        g.supervisor_tenant = db.es_supervisor_tenant(usuario_id)

        permitido, restantes, reinicio = _consumir_cupo(usuario_id)
        g.api_limite = (API_LIMITE_POR_MINUTO, restantes, reinicio)
        if not permitido:
            respuesta, status = _error_api(f"Has superado el límite de {API_LIMITE_POR_MINUTO} peticiones por minuto.", 429, "limite_excedido")
            respuesta.headers["Retry-After"] = str(reinicio)
            return respuesta, status

        # Idempotencia: con `Idempotency-Key` en un POST, repetir la misma petición devuelve la misma respuesta sin
        # volver a ejecutarla (reintentos de red seguros). Misma clave con otra petición = 422.
        clave = (request.headers.get("Idempotency-Key") or "").strip()[:128] if request.method == "POST" else ""
        if clave and not request.path.endswith("/stream"):
            huella = hashlib.sha256((request.path + "\n").encode() + request.get_data()).hexdigest()
            estado = db.idempotencia_reservar(usuario_id, clave, huella)
            if estado[0] == "conflicto":
                return _error_api("Esa Idempotency-Key ya se usó con una petición distinta.", 422, "idempotencia_conflicto")
            if estado[0] == "en_curso":
                return _error_api("Hay otra petición con esa Idempotency-Key en curso.", 409, "idempotencia_en_curso")
            if estado[0] == "repetida":
                respuesta = Response(estado[2], status=estado[1], mimetype="application/json")
                respuesta.headers["Idempotent-Replay"] = "true"
                return respuesta
            try:
                respuesta = make_response(vista(*args, **kwargs))
            except Exception:
                db.idempotencia_liberar(usuario_id, clave)
                raise
            if respuesta.status_code >= 500 or respuesta.is_streamed:
                db.idempotencia_liberar(usuario_id, clave)
            else:
                db.idempotencia_guardar(usuario_id, clave, respuesta.status_code, respuesta.get_data(as_text=True))
            return respuesta
        return vista(*args, **kwargs)
    return decorada
