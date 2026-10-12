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
import re
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


API_LIMITE_ESCRITURAS_POR_MINUTO = int(os.environ.get("GUILDA_API_LIMITE_ESCRITURAS_POR_MINUTO", "200"))
API_LIMITE_PESADAS_POR_MINUTO = int(os.environ.get("GUILDA_API_LIMITE_PESADAS_POR_MINUTO", "20"))

# Rutas caras (llamadas al modelo de IA, exportaciones, importaciones, sincronizar un buzón, enviar correo): cupo propio y bajo.
_PESADA = re.compile(r"/ia/(?:mensaje|confirmar)(?:/stream)?$|/exportar|/importar|/informe|/sincronizar$|/correo/enviar$")


def tipo_de_peticion(metodo: str, ruta: str) -> str:
    """`pesada` (rutas caras), `escritura` (el resto de POST/PUT/PATCH/DELETE) o `lectura`."""
    if _PESADA.search(ruta):
        return "pesada"
    return "escritura" if metodo in ("POST", "PUT", "PATCH", "DELETE") else "lectura"


def _consumir_cupo_api(usuario_id: int, tipo: str) -> tuple[bool, int, int, int, str]:
    """Cuenta la petición en el total de la persona y en el cupo de su tipo. Si alguno está agotado no gasta ninguno.
    Devuelve (permitido, límite aplicable, restantes, segundos hasta liberar un hueco, tipo del cupo que manda)."""
    ahora = time.monotonic()
    cupos = [("total", usuario_id, API_LIMITE_POR_MINUTO)]
    if tipo == "pesada":
        cupos.append(("pesada", f"api:pesada:{usuario_id}", API_LIMITE_PESADAS_POR_MINUTO))
    elif tipo == "escritura":
        cupos.append(("escritura", f"api:escritura:{usuario_id}", API_LIMITE_ESCRITURAS_POR_MINUTO))
    with _lock_ventanas:
        ventanas = []
        for nombre, clave, limite in cupos:
            ventana = _ventanas.setdefault(clave, deque())
            while ventana and ahora - ventana[0] >= 60:
                ventana.popleft()
            if len(ventana) >= limite:
                return False, limite, 0, max(1, int(60 - (ahora - ventana[0])) + 1), nombre
            ventanas.append((nombre, ventana, limite))
        for _n, ventana, _l in ventanas:
            ventana.append(ahora)
        # El que más cerca está de agotarse es el que se informa en las cabeceras.
        nombre, ventana, limite = min(ventanas, key=lambda v: v[2] - len(v[1]))
        return True, limite, limite - len(ventana), max(1, int(60 - (ahora - ventana[0]))), nombre


def consumir_cupos_nombrados(cupos: list[tuple[str, int]]) -> tuple[bool, int]:
    """Comprueba varias ventanas de 60 s a la vez (p. ej. el total y las escrituras de una persona) y solo si TODAS tienen hueco
    cuenta la llamada en todas: una petición rechazada no gasta cupo. (permitido, segundos hasta poder reintentar)."""
    ahora = time.monotonic()
    with _lock_ventanas:
        ventanas = []
        for clave, limite in cupos:
            ventana = _ventanas.setdefault(clave, deque())
            while ventana and ahora - ventana[0] >= 60:
                ventana.popleft()
            if len(ventana) >= limite:
                return False, max(1, int(60 - (ahora - ventana[0])) + 1)
            ventanas.append(ventana)
        for ventana in ventanas:
            ventana.append(ahora)
        return True, 0


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
        if autenticado.get("ip_no_permitida"):
            return _error_api("Este token no se puede usar desde esta dirección IP.", 403, "ip_no_permitida")
        usuario_id, permisos = autenticado["usuario_id"], autenticado["permisos"]
        g.token_id, g.areas_token = autenticado["token_id"], autenticado["areas"]
        g.origenes_cors_token = autenticado.get("origenes_cors", [])
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
        # El propio token es el secreto con el que se abre su concesión de acceso a lo cifrado (si el despacho se la dio). Se limpia al terminar la petición.
        from . import cifrado_despacho
        cifrado_despacho.fijar_concesion("api", token)
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

        tipo = tipo_de_peticion(request.method, request.path)
        permitido, limite, restantes, reinicio, cupo = _consumir_cupo_api(usuario_id, tipo)
        g.api_limite = (limite, restantes, reinicio)
        g.api_cupo = cupo
        if not permitido:
            cual = {"total": "peticiones", "escritura": "escrituras", "pesada": "operaciones pesadas (IA, exportaciones, sincronizaciones, envíos)"}[cupo]
            respuesta, status = _error_api(f"Has superado el límite de {limite} {cual} por minuto.", 429, "limite_excedido", cupo=cupo)
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
