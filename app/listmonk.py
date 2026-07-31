"""Cliente de Listmonk (Fase newsletter: envíos masivos/newsletters, ver
mcp_tools.py).

A diferencia de Cal.diy/Documenso/FacturaScripts, aquí el
aprovisionamiento por tenant es 100% automático, sin ningún paso
manual — verificado en vivo, contra un contenedor real (Postgres +
`listmonk/listmonk:latest`, imagen oficial, sin el problema de build de
Cal.diy):

## Aislamiento por lista — real, verificado en vivo

Cada usuario tiene un `list_role_id` con permisos (`list:get`/
`list:manage`) restringidos a listas concretas. El endpoint de listar/
buscar suscriptores filtra por esos ids DENTRO de la propia consulta a
base de datos (`filterListQueryByPerm` en el código fuente real de
Listmonk, `cmd/subscribers.go`) — no es una convención de UI. Probado
en vivo con dos tenants reales: el token de un tenant, al pedir la
lista del otro, recibe una lista vacía (no un error, pero tampoco ve
nada); al intentar CREAR un suscriptor en la lista ajena, recibe
`403 Permission denied: lists` explícito.

**Hallazgo real, no anticipado en el diseño inicial**: los permisos
`subscribers:*`/`campaigns:*` NO se pueden asignar dentro de un Rol de
lista (`POST /api/roles/lists` los rechaza con
`"Invalid fields: list permission: subscribers:get"`, confirmado en
vivo y en el código fuente, `validateListRole` en `cmd/roles.go` solo
acepta `list:get`/`list:manage` ahí) — esos permisos de ACCIÓN van en
el Rol de USUARIO (compartido entre todos los tenants, ver
`_ROL_USUARIO_TENANT`), y lo que de verdad restringe qué listas/
suscriptores/campañas puede tocar cada tenant es su Rol de LISTA. Este
diseño de dos roles (uno de acción compartido + uno de alcance por
tenant) se confirmó probándolo de verdad, no solo leyendo el modelo de
datos.

## Aprovisionamiento — sin ningún paso manual

`POST /api/users` con `"type": "api"` genera un token de 48 caracteres
en el momento y lo devuelve en la propia respuesta de creación (no se
oculta para usuarios tipo `api`, a diferencia de los tipo `user`) —
confirmado en vivo. Con eso: crear la Lista del tenant → crear su Rol
de lista (solo `list:get`/`list:manage` sobre esa lista) → crear un
usuario tipo `api` con ese `list_role_id` y el Rol de usuario base
compartido → guardar el token que llega en la respuesta. Cero pasos
manuales.

Auth de administración: sesión por cookie (`POST /admin/login` con
`username`/`password` de formulario, no JSON) — confirmado en vivo que
la Basic Auth con usuario+contraseña humana YA NO funciona en las
versiones actuales de Listmonk (`"invalid API credentials"`, el propio
código fuente lo confirma como comportamiento heredado que se
mantiene solo para cookies de sesión antiguas, no para Basic Auth
nueva) — así que este módulo inicia sesión con
`LISTMONK_ADMIN_USER`/`LISTMONK_ADMIN_PASSWORD` y reutiliza la cookie
de sesión para las llamadas de administración (crear Lista/Rol/
usuario). El bootstrap del propio superadmin es 100% declarativo
(`LISTMONK_ADMIN_USER`/`PASSWORD` en `docker-compose.yml`, confirmado
en el `docker-compose.yml` oficial del proyecto) — no hace falta ni una
función `bootstrap_admin()` propia, a diferencia de Cal.diy.

## API de negocio

Con el token del propio tenant (`Authorization: token
<username>:<token>`, confirmado en vivo — NO es `Bearer` ni Basic).
`PUT /api/campaigns/{id}/status` con `{"status": "running"}` envía una
campaña — confirmado en vivo (no estaba en la documentación consultada
de antemano).

Mismo criterio que el resto de `app/*.py`: solo `urllib` de la
librería estándar.
"""
import http.cookiejar
import json
import os
import urllib.error
import urllib.parse
import urllib.request

LISTMONK_URL = os.environ.get("HERRAMIENTA_LISTMONK_URL", "http://127.0.0.1:8023")
LISTMONK_ADMIN_USER = os.environ.get("LISTMONK_ADMIN_USER")
LISTMONK_ADMIN_PASSWORD = os.environ.get("LISTMONK_ADMIN_PASSWORD")
TIMEOUT_SEGUNDOS = 20

# Rol de USUARIO compartido por todos los tenants — lleva los permisos
# de ACCIÓN (no de alcance: eso lo da el Rol de lista de cada tenant).
# Verificado en vivo que un Rol de lista no puede llevar estos permisos
# él mismo, ver docstring del módulo.
_ROL_USUARIO_TENANT = "Tenant"
_PERMISOS_ROL_USUARIO_TENANT = [
    "subscribers:get", "subscribers:manage",
    "campaigns:get", "campaigns:manage", "campaigns:send",
]
_PERMISOS_ROL_LISTA_TENANT = ["list:get", "list:manage"]


class ErrorListmonk(Exception):
    """Error legible para mostrar cuando Listmonk falla."""


def _peticion(endpoint: str, *, metodo: str = "GET", cuerpo: dict | None = None,
              cabeceras: dict | None = None, opener: urllib.request.OpenerDirector | None = None):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    todas_cabeceras = {"Accept": "application/json"}
    if cabeceras:
        todas_cabeceras.update(cabeceras)
    if datos is not None:
        todas_cabeceras["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{LISTMONK_URL}{endpoint}", data=datos, headers=todas_cabeceras, method=metodo)
    abrir = (opener.open if opener else urllib.request.urlopen)
    try:
        with abrir(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            cuerpo_resp = resp.read().decode("utf-8")
            return resp.status, (json.loads(cuerpo_resp) if cuerpo_resp else {})
    except urllib.error.HTTPError as e:
        cuerpo_error = e.read().decode("utf-8")
        try:
            return e.code, json.loads(cuerpo_error)
        except json.JSONDecodeError:
            return e.code, {"message": cuerpo_error}
    except urllib.error.URLError as e:
        raise ErrorListmonk(
            f"No se ha podido conectar con Listmonk ({LISTMONK_URL}). "
            f"¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError:
        raise ErrorListmonk(f"Tiempo de espera agotado al contactar con Listmonk ({LISTMONK_URL}).")


def _sesion_admin() -> urllib.request.OpenerDirector | None:
    """Inicia sesión con LISTMONK_ADMIN_USER/PASSWORD y devuelve un
    opener con la cookie de sesión ya puesta — None si esas variables no
    están configuradas (Listmonk es opcional, mismo criterio que
    PAPERLESS_ADMIN_USER). Basic Auth con usuario/contraseña humana no
    funciona (verificado en vivo), hace falta la sesión de verdad."""
    if not LISTMONK_ADMIN_USER or not LISTMONK_ADMIN_PASSWORD:
        return None
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    datos = urllib.parse.urlencode({"username": LISTMONK_ADMIN_USER, "password": LISTMONK_ADMIN_PASSWORD}).encode("utf-8")
    req = urllib.request.Request(f"{LISTMONK_URL}/admin/login", data=datos, method="POST")
    try:
        opener.open(req, timeout=TIMEOUT_SEGUNDOS)
    except urllib.error.HTTPError as e:
        raise ErrorListmonk(f"No se ha podido iniciar sesión en Listmonk como admin: HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise ErrorListmonk(f"No se ha podido conectar con Listmonk ({LISTMONK_URL}): {e.reason}") from e
    if not any(c.name == "session" for c in jar):
        raise ErrorListmonk("Login de administrador de Listmonk rechazado — revisa LISTMONK_ADMIN_USER/PASSWORD.")
    return opener


def _buscar_por_nombre(endpoint: str, nombre: str, opener: urllib.request.OpenerDirector) -> dict | None:
    """Busca por "name" (Listas, Roles) o, si no hay ese campo,
    "username"/"email" (Usuarios — su registro no tiene "name")."""
    estado, cuerpo = _peticion(endpoint, opener=opener)
    if estado != 200:
        return None
    resultados = cuerpo.get("data", {})
    lista = resultados.get("results", resultados) if isinstance(resultados, dict) else resultados
    for r in lista or []:
        if nombre in (r.get("name"), r.get("username"), r.get("email")):
            return r
    return None


def _rol_usuario_tenant_id(opener: urllib.request.OpenerDirector) -> int:
    """Crea (o reutiliza) el Rol de usuario compartido con los permisos
    de acción — idempotente por nombre."""
    existente = _buscar_por_nombre("/api/roles/users", _ROL_USUARIO_TENANT, opener)
    if existente is not None:
        return existente["id"]
    estado, cuerpo = _peticion(
        "/api/roles/users", metodo="POST", opener=opener,
        cuerpo={"name": _ROL_USUARIO_TENANT, "permissions": _PERMISOS_ROL_USUARIO_TENANT},
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("message") or cuerpo
        raise ErrorListmonk(f"No se ha podido crear el Rol de usuario base de Listmonk: {mensaje}")
    return cuerpo["data"]["id"]


def aprovisionar_tenant(nombre_tenant: str) -> dict | None:
    """Crea la Lista + el Rol de lista + un usuario de servicio tipo
    'api' para un tenant, todo en una sola pasada, sin ningún paso
    manual. Devuelve {"list_id", "list_role_id", "api_key"}, o None si
    LISTMONK_ADMIN_USER/PASSWORD no están configuradas. Idempotente: si
    la Lista o el Rol ya existen (reintento tras un fallo parcial),
    reutiliza sus ids en vez de fallar."""
    opener = _sesion_admin()
    if opener is None:
        return None

    lista = _buscar_por_nombre("/api/lists", nombre_tenant, opener)
    if lista is None:
        estado, cuerpo = _peticion(
            "/api/lists", metodo="POST", opener=opener,
            cuerpo={"name": nombre_tenant, "type": "private", "optin": "single"},
        )
        if estado not in (200, 201):
            mensaje = cuerpo.get("message") or cuerpo
            raise ErrorListmonk(f"No se ha podido crear la Lista de Listmonk para '{nombre_tenant}': {mensaje}")
        lista = cuerpo["data"]
    list_id = lista["id"]

    rol_lista = _buscar_por_nombre("/api/roles/lists", nombre_tenant, opener)
    if rol_lista is None:
        estado, cuerpo = _peticion(
            "/api/roles/lists", metodo="POST", opener=opener,
            cuerpo={"name": nombre_tenant, "lists": [{"id": list_id, "permissions": _PERMISOS_ROL_LISTA_TENANT}]},
        )
        if estado not in (200, 201):
            mensaje = cuerpo.get("message") or cuerpo
            raise ErrorListmonk(f"No se ha podido crear el Rol de lista de Listmonk para '{nombre_tenant}': {mensaje}")
        rol_lista = cuerpo["data"]
    list_role_id = rol_lista["id"]

    rol_usuario_id = _rol_usuario_tenant_id(opener)

    username = f"tenant-{nombre_tenant.lower().replace(' ', '-')}-api"
    estado, cuerpo = _peticion(
        "/api/users", metodo="POST", opener=opener,
        cuerpo={
            "type": "api", "username": username, "status": "enabled",
            "user_role_id": rol_usuario_id, "list_role_id": list_role_id,
        },
    )
    if estado in (200, 201):
        api_key = f"{username}:{cuerpo['data']['password']}"
    else:
        # Ya existía de un intento anterior: no se puede recuperar su
        # token (Listmonk no lo vuelve a enseñar) — hace falta borrarlo
        # y recrearlo para tener un token utilizable.
        existente = _buscar_por_nombre("/api/users", username, opener)
        if existente is None:
            mensaje = cuerpo.get("message") or cuerpo
            raise ErrorListmonk(f"No se ha podido crear el usuario de servicio de Listmonk para '{nombre_tenant}': {mensaje}")
        _peticion(f"/api/users/{existente['id']}", metodo="DELETE", opener=opener)
        estado, cuerpo = _peticion(
            "/api/users", metodo="POST", opener=opener,
            cuerpo={
                "type": "api", "username": username, "status": "enabled",
                "user_role_id": rol_usuario_id, "list_role_id": list_role_id,
            },
        )
        if estado not in (200, 201):
            mensaje = cuerpo.get("message") or cuerpo
            raise ErrorListmonk(f"No se ha podido recrear el usuario de servicio de Listmonk para '{nombre_tenant}': {mensaje}")
        api_key = f"{username}:{cuerpo['data']['password']}"

    return {"list_id": list_id, "list_role_id": list_role_id, "api_key": api_key}


def crear_usuario_tenant(email: str, list_role_id: int, opener: urllib.request.OpenerDirector | None = None) -> None:
    """Da de alta (o actualiza el rol de) un usuario humano de Listmonk
    para que pueda entrar por SSO con el alcance correcto — se llama
    desde crear_usuario() de Guilda Work, no desde aprovisionar_tenant().
    No hace nada si Listmonk no está configurado."""
    propio = opener is None
    if propio:
        opener = _sesion_admin()
        if opener is None:
            return
    rol_usuario_id = _rol_usuario_tenant_id(opener)
    existente = _buscar_por_nombre("/api/users", email, opener)
    if existente is not None:
        estado, cuerpo = _peticion(
            f"/api/users/{existente['id']}", metodo="PUT", opener=opener,
            cuerpo={
                "type": "user", "username": existente["username"], "email": email, "status": "enabled",
                "password_login": False, "user_role_id": rol_usuario_id, "list_role_id": list_role_id,
            },
        )
    else:
        estado, cuerpo = _peticion(
            "/api/users", metodo="POST", opener=opener,
            cuerpo={
                "type": "user", "username": email, "email": email, "status": "enabled",
                "password_login": False, "user_role_id": rol_usuario_id, "list_role_id": list_role_id,
            },
        )
    if estado not in (200, 201):
        mensaje = cuerpo.get("message") or cuerpo
        raise ErrorListmonk(f"No se ha podido dar de alta a '{email}' en Listmonk: {mensaje}")


def desaprovisionar_tenant(list_id: int | None, list_role_id: int | None) -> None:
    """Borra la Lista y el Rol de lista de un tenant — los usuarios
    (api/humanos) ligados a ese Rol quedan sin permisos de alcance
    automáticamente, no hace falta borrarlos aparte. No falla si alguna
    pieza ya no existe, ni si Listmonk no está configurado."""
    opener = _sesion_admin()
    if opener is None:
        return
    if list_role_id is not None:
        _peticion(f"/api/roles/{list_role_id}", metodo="DELETE", opener=opener)
    if list_id is not None:
        _peticion(f"/api/lists/{list_id}", metodo="DELETE", opener=opener)


# --- API de negocio (Fase MCP) — usa el token del propio tenant ---

def _cabecera_token(api_key: str) -> dict:
    return {"Authorization": f"token {api_key}"}


def listar_suscriptores(api_key: str, list_id: int, texto: str | None = None, limite: int = 20) -> list[dict]:
    if not api_key:
        return []
    parametros = {"list_id": list_id, "per_page": limite}
    if texto:
        parametros["query"] = f"subscribers.email LIKE '%{texto}%' OR subscribers.name LIKE '%{texto}%'"
    estado, cuerpo = _peticion(f"/api/subscribers?{urllib.parse.urlencode(parametros)}", cabeceras=_cabecera_token(api_key))
    if estado != 200:
        mensaje = cuerpo.get("message") or cuerpo
        raise ErrorListmonk(f"No se han podido listar los suscriptores de Listmonk: {mensaje}")
    return cuerpo.get("data", {}).get("results", [])


def crear_suscriptor(api_key: str, list_id: int, email: str, nombre: str, atribs: dict | None = None) -> dict:
    if not api_key:
        raise ErrorListmonk("Este tenant no tiene Listmonk aprovisionado todavía.")
    estado, cuerpo = _peticion(
        "/api/subscribers", metodo="POST", cabeceras=_cabecera_token(api_key),
        cuerpo={"email": email, "name": nombre, "lists": [list_id], "status": "enabled", "attribs": atribs or {}},
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("message") or cuerpo
        raise ErrorListmonk(f"No se ha podido dar de alta a '{email}' en Listmonk: {mensaje}")
    return cuerpo.get("data", cuerpo)


def listar_campanas(api_key: str) -> list[dict]:
    if not api_key:
        return []
    estado, cuerpo = _peticion("/api/campaigns", cabeceras=_cabecera_token(api_key))
    if estado != 200:
        mensaje = cuerpo.get("message") or cuerpo
        raise ErrorListmonk(f"No se han podido listar las campañas de Listmonk: {mensaje}")
    return cuerpo.get("data", {}).get("results", [])


def crear_campana(api_key: str, list_id: int, nombre: str, asunto: str, cuerpo_html: str) -> dict:
    if not api_key:
        raise ErrorListmonk("Este tenant no tiene Listmonk aprovisionado todavía.")
    estado, cuerpo = _peticion(
        "/api/campaigns", metodo="POST", cabeceras=_cabecera_token(api_key),
        cuerpo={
            "name": nombre, "subject": asunto, "lists": [list_id],
            "content_type": "richtext", "body": cuerpo_html, "type": "regular",
        },
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("message") or cuerpo
        raise ErrorListmonk(f"No se ha podido crear la campaña '{nombre}' en Listmonk: {mensaje}")
    return cuerpo.get("data", cuerpo)


def enviar_campana(api_key: str, campana_id: int) -> dict:
    if not api_key:
        raise ErrorListmonk("Este tenant no tiene Listmonk aprovisionado todavía.")
    estado, cuerpo = _peticion(
        f"/api/campaigns/{campana_id}/status", metodo="PUT", cabeceras=_cabecera_token(api_key),
        cuerpo={"status": "running"},
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("message") or cuerpo
        raise ErrorListmonk(f"No se ha podido enviar la campaña {campana_id} en Listmonk: {mensaje}")
    return cuerpo.get("data", cuerpo)
