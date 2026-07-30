"""Cliente de la API REST de Baserow (Fase hojas: hojas de cálculo tipo
base de datos, ver mcp_tools.py).

Confirmado leyendo el spec OpenAPI real (`GET /api/schema.json` contra
una instancia en marcha, no solo la documentación) que el aprovisionamiento
es un híbrido entre Paperless-ngx (100% automático) y Documenso (0%):

- **SÍ hay API real** para crear Workspaces (`POST /api/workspaces/`) y
  tokens de base de datos ligados a un Workspace concreto
  (`POST /api/database/tokens/`) — un token de base de datos solo ve el
  Workspace al que pertenece (aislamiento real, es el propio modelo de
  datos de Baserow: cada base/tabla vive dentro de un Workspace, no una
  capa de permisos añadida encima).
- **NO hay forma de añadir un usuario ya existente a un Workspace por
  API** — confirmado en el spec:
  `/api/workspaces/users/workspace/{workspace_id}/` solo acepta `GET`.
  La única vía es invitar por email
  (`POST /api/workspaces/invitations/workspace/{id}/`, sí automatizable)
  y que la persona acepte ella misma desde su bandeja de entrada — fuera
  del control de este módulo.

SSO: confirmado en la documentación oficial que está solo en el plan
Advanced Enterprise, también en self-hosted — no hay integración con
Hydra aquí, cada persona inicia sesión con su propia cuenta de Baserow.

Auth de administración: `BASEROW_ADMIN_EMAIL`/`BASEROW_ADMIN_PASSWORD`
(el superusuario NO se autocrea al arrancar el contenedor, a diferencia
de Paperless-ngx — es un paso manual único, ver HOSTING.md) via JWT
(`POST /api/user/token-auth/`). Igual que con Paperless-ngx, el JWT se
cachea en memoria del proceso en vez de pedir uno nuevo en cada llamada
de aprovisionamiento (mismo motivo: evitar un throttling real que ya se
encontró una vez en un endpoint de login equivalente).

Mismo criterio que el resto de app/*.py: solo `urllib` de la librería
estándar.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

BASEROW_URL = os.environ.get("HERRAMIENTA_BASEROW_URL", "http://127.0.0.1:8020")
BASEROW_ADMIN_EMAIL = os.environ.get("BASEROW_ADMIN_EMAIL")
BASEROW_ADMIN_PASSWORD = os.environ.get("BASEROW_ADMIN_PASSWORD")
TIMEOUT_SEGUNDOS = 20


class ErrorBaserow(Exception):
    """Error legible para mostrar cuando Baserow falla."""


def _peticion(endpoint: str, *, auth: str | None, metodo: str = "GET", cuerpo: dict | None = None):
    """`auth` ya viene formada (`Token <db_token>` o `JWT <jwt>`) —
    Baserow usa dos esquemas distintos según el endpoint (ver docstring
    del módulo), a diferencia del resto de app/*.py que solo tiene uno."""
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    cabeceras = {"Accept": "application/json"}
    if auth:
        cabeceras["Authorization"] = auth
    if datos is not None:
        cabeceras["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASEROW_URL}{endpoint}", data=datos, headers=cabeceras, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            cuerpo_resp = resp.read().decode("utf-8")
            return resp.status, (json.loads(cuerpo_resp) if cuerpo_resp else {})
    except urllib.error.HTTPError as e:
        cuerpo_error = e.read().decode("utf-8")
        try:
            return e.code, json.loads(cuerpo_error)
        except json.JSONDecodeError:
            return e.code, {"error": cuerpo_error}
    except urllib.error.URLError as e:
        raise ErrorBaserow(
            f"No se ha podido conectar con Baserow ({BASEROW_URL}). ¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError:
        raise ErrorBaserow(f"Tiempo de espera agotado al contactar con Baserow ({BASEROW_URL}).")


_jwt_admin_cache: str | None = None


def _jwt_admin(*, forzar_nuevo: bool = False) -> str | None:
    """None si BASEROW_ADMIN_EMAIL/PASSWORD no están configuradas —
    Baserow es opcional en esta integración, igual que Paperless-ngx sin
    PAPERLESS_ADMIN_USER. Se cachea en memoria del proceso, PERO a
    diferencia del token de Paperless-ngx (que no caduca), el
    `access_token` de Baserow solo vale 10 minutos (confirmado en el
    spec OpenAPI real) — `_peticion_admin()` fuerza un nuevo login si el
    cacheado ya no vale, en vez de intentar refrescarlo con el
    `refresh_token` (más simple, y el login no está sujeto al
    throttling que sí tiene `/api/token/` en Paperless-ngx, verificado
    en vivo)."""
    global _jwt_admin_cache
    if not BASEROW_ADMIN_EMAIL or not BASEROW_ADMIN_PASSWORD:
        return None
    if _jwt_admin_cache is None or forzar_nuevo:
        estado, cuerpo = _peticion(
            "/api/user/token-auth/", auth=None, metodo="POST",
            cuerpo={"email": BASEROW_ADMIN_EMAIL, "password": BASEROW_ADMIN_PASSWORD},
        )
        if estado != 200:
            mensaje = cuerpo.get("detail") or cuerpo
            raise ErrorBaserow(f"No se ha podido iniciar sesión en Baserow como '{BASEROW_ADMIN_EMAIL}': {mensaje}")
        _jwt_admin_cache = cuerpo["access_token"]
    return _jwt_admin_cache


def _peticion_admin(endpoint: str, *, metodo: str = "GET", cuerpo: dict | None = None):
    """Como _peticion(), pero con el JWT de administración — si el
    cacheado ya caducó (401), pide uno nuevo y reintenta una vez."""
    jwt = _jwt_admin()
    if jwt is None:
        return None, None
    estado, resp = _peticion(endpoint, auth=f"JWT {jwt}", metodo=metodo, cuerpo=cuerpo)
    if estado == 401:
        jwt = _jwt_admin(forzar_nuevo=True)
        estado, resp = _peticion(endpoint, auth=f"JWT {jwt}", metodo=metodo, cuerpo=cuerpo)
    return estado, resp


def _buscar_workspace_por_nombre(nombre: str) -> int | None:
    estado, cuerpo = _peticion_admin("/api/workspaces/")
    if estado != 200:
        return None
    for w in cuerpo:
        if w.get("name") == nombre:
            return w["id"]
    return None


def aprovisionar_tenant(nombre_tenant: str) -> dict | None:
    """Crea el Workspace de un tenant y un token de base de datos ligado
    a él — todo en una sola llamada, sin ningún paso manual. Devuelve
    {"workspace_id", "api_key"}, o None si BASEROW_ADMIN_EMAIL/PASSWORD
    no están configuradas. Idempotente: busca primero por nombre antes
    de crear — verificado en vivo que, a diferencia de EspoCRM/
    Nextcloud/Paperless-ngx, Baserow NO rechaza nombres de Workspace
    duplicados (`POST /api/workspaces/` siempre devuelve 200 y crea uno
    nuevo), así que "crear y solo buscar si falla" crearía un Workspace
    distinto en cada reintento en vez de reutilizar el existente."""
    if _jwt_admin() is None:
        return None

    workspace_id = _buscar_workspace_por_nombre(nombre_tenant)
    if workspace_id is None:
        estado, cuerpo = _peticion_admin("/api/workspaces/", metodo="POST", cuerpo={"name": nombre_tenant})
        if estado not in (200, 201):
            mensaje = cuerpo.get("detail") or cuerpo
            raise ErrorBaserow(f"No se ha podido crear el Workspace de Baserow para '{nombre_tenant}': {mensaje}")
        workspace_id = cuerpo["id"]

    estado, cuerpo = _peticion_admin(
        "/api/database/tokens/", metodo="POST", cuerpo={"name": nombre_tenant, "workspace": workspace_id},
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("detail") or cuerpo
        raise ErrorBaserow(f"No se ha podido crear el token de Baserow para '{nombre_tenant}': {mensaje}")
    return {"workspace_id": workspace_id, "api_key": cuerpo["key"]}


def desaprovisionar_tenant(workspace_id: int | None) -> None:
    """Borra el Workspace de un tenant (bases de datos/tablas incluidas)
    de verdad — no falla si ya no existe, ni si Baserow no está
    configurado.

    Verificado en vivo: `DELETE /api/workspaces/{id}/` solo lo manda a
    la papelera (soft delete) — confirmado que un Workspace solo en
    papelera se puede seguir "viendo" con su token. Hace falta una
    segunda llamada, `DELETE /api/trash/workspace/{id}/`, para vaciarla
    y borrarlo de verdad (confirmado con un `GET` posterior al mismo
    Workspace: 404 `ERROR_GROUP_DOES_NOT_EXIST`, ya no existe).

    Nota de comportamiento (no un fallo de seguridad, verificado en
    vivo): incluso tras el borrado real, su token de base de datos sigue
    aceptándose como credencial válida — `listar_tablas()` con ese token
    devuelve `[]` (sin tablas, porque ya no hay ningún Workspace al que
    pertenezcan) en vez de un 401/403 explícito. No hay fuga de datos de
    otro tenant en ningún caso — solo que el error no es tan explícito
    como cabría esperar; documentado también en HOSTING.md."""
    if workspace_id is None:
        return
    _peticion_admin(f"/api/workspaces/{workspace_id}/", metodo="DELETE")
    _peticion_admin(f"/api/trash/workspace/{workspace_id}/", metodo="DELETE")


def invitar_usuario(workspace_id: int | None, email: str) -> None:
    """Invita a una persona al Workspace de un tenant por email — la
    invitación la manda Baserow (si hay SMTP configurado, ver
    HOSTING.md); aceptarla es cosa suya, fuera del control de este
    módulo. No hace nada sin Baserow configurado o sin workspace_id."""
    if workspace_id is None or _jwt_admin() is None:
        return
    estado, cuerpo = _peticion_admin(
        f"/api/workspaces/invitations/workspace/{workspace_id}/", metodo="POST",
        cuerpo={
            "email": email, "permissions": "member",
            # La ruta real del frontend que acepta la invitación
            # (confirmado en el código fuente de web-frontend/modules/
            # core/routes.js) — Baserow le añade "/<token>" al final.
            "base_url": f"{BASEROW_URL}/workspace-invitation",
        },
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("detail") or cuerpo
        raise ErrorBaserow(f"No se ha podido invitar a '{email}' al Workspace de Baserow: {mensaje}")


# --- API de negocio (Fase MCP) — usa el token de base de datos del propio tenant ---

def listar_tablas(api_key: str) -> list[dict]:
    """Lista las tablas visibles con el token de un tenant (todas las
    que estén dentro de su Workspace). [] si `api_key` está vacía
    (tenant sin Baserow aprovisionado todavía)."""
    if not api_key:
        return []
    estado, cuerpo = _peticion("/api/database/tables/all-tables/", auth=f"Token {api_key}")
    if estado != 200:
        mensaje = cuerpo.get("detail") or cuerpo
        raise ErrorBaserow(f"No se han podido listar las tablas de Baserow: {mensaje}")
    return cuerpo


def listar_filas(api_key: str, tabla_id: int, texto: str | None = None, limite: int = 20) -> list[dict]:
    if not api_key:
        return []
    parametros = {"size": limite}
    if texto:
        parametros["search"] = texto
    estado, cuerpo = _peticion(
        f"/api/database/rows/table/{tabla_id}/?{urllib.parse.urlencode(parametros)}", auth=f"Token {api_key}",
    )
    if estado != 200:
        mensaje = cuerpo.get("detail") or cuerpo
        raise ErrorBaserow(f"No se han podido listar las filas de la tabla {tabla_id} de Baserow: {mensaje}")
    return cuerpo.get("results", [])


def crear_fila(api_key: str, tabla_id: int, campos: dict) -> dict:
    """Crea una fila. `campos`: {"Nombre de columna": valor, ...} — los
    nombres de columna de Baserow son las propias claves del cuerpo."""
    if not api_key:
        raise ErrorBaserow("Este tenant no tiene Baserow aprovisionado todavía.")
    estado, cuerpo = _peticion(
        f"/api/database/rows/table/{tabla_id}/", auth=f"Token {api_key}", metodo="POST", cuerpo=campos,
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("detail") or cuerpo
        raise ErrorBaserow(f"No se ha podido crear la fila en la tabla {tabla_id} de Baserow: {mensaje}")
    return cuerpo
