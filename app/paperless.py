"""Cliente de la API REST de Paperless-ngx (Fase documentos: gestión
documental/OCR, ver mcp_tools.py).

A diferencia de Documenso/FacturaScripts, aquí el aprovisionamiento por
tenant SÍ es 100% automático, sin ningún paso manual — confirmado leyendo
el código fuente real de Paperless-ngx (`src/paperless/views.py`,
`src/paperless/serialisers.py`, `src/documents/views.py`, no solo su
documentación):

- `UserViewSet`/`GroupViewSet` (registrados como `/api/users/` y
  `/api/groups/`, `ModelViewSet` completo) permiten crear Usuarios y
  Grupos por API. El `GroupSerializer` acepta permisos como codenames
  Django planos (`"add_document"`, `"view_document"`,
  `"change_document"`).
- `POST /api/token/` (username+password → token) permite generar el
  token de un usuario recién creado en la misma llamada, sin pasar por
  su sesión web.
- `DocumentViewSet` monta `DocumentPermissionsFilter` como filtro del
  queryset — el aislamiento entre tenants es real, aplicado en la propia
  consulta a base de datos, no una convención de UI (mismo nivel de
  confianza que los Roles "Team" de EspoCRM).

Diseño de aislamiento: un Grupo + un usuario de servicio por tenant
(miembro solo de ese Grupo, sin ser superusuario). Los documentos que
suba el MCP de un tenant se marcan con `owner` = ese usuario y
`set_permissions` restringido a ese Grupo — así ningún otro tenant puede
verlos ni editarlos, aunque la instancia sea compartida.

Auth de administración: `PAPERLESS_ADMIN_USER`/`PAPERLESS_ADMIN_PASSWORD`
(crean un superusuario al arrancar el contenedor, ver HOSTING.md) — este
módulo pide un token nuevo con esas credenciales en cada llamada de
aprovisionamiento en vez de guardar uno de larga duración, evita
gestionar caducidad. Opcional a propósito: sin esas variables,
`aprovisionar_tenant` no hace nada, mismo criterio que
`ESPOCRM_API_KEY`/`NEXTCLOUD_ADMIN_USER`.

Mismo criterio que el resto de app/*.py: solo `urllib` de la librería
estándar, salvo `uuid` para el cuerpo multipart de la subida de
documentos (mismo motivo que en app/documenso.py: Paperless-ngx exige
`multipart/form-data` para /api/documents/post_document/).
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

PAPERLESS_URL = os.environ.get("HERRAMIENTA_PAPERLESS_URL", "http://127.0.0.1:8019")
PAPERLESS_ADMIN_USER = os.environ.get("PAPERLESS_ADMIN_USER")
PAPERLESS_ADMIN_PASSWORD = os.environ.get("PAPERLESS_ADMIN_PASSWORD")
TIMEOUT_SEGUNDOS = 20
# view_paperlesstask: sin ella, el token del propio tenant no puede
# consultar /api/tasks/ para saber si su documento ya se procesó
# (verificado en vivo: sin este permiso, PaperlessObjectPermissions
# devuelve 403 "You do not have permission to perform this action" en
# ese endpoint, aunque el documento se suba bien).
PERMISOS_GRUPO_TENANT = ["add_document", "view_document", "change_document", "view_paperlesstask"]


class ErrorPaperless(Exception):
    """Error legible para mostrar cuando Paperless-ngx falla."""


def _peticion(endpoint: str, api_key: str, *, metodo: str = "GET", cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    cabeceras = {"Accept": "application/json", "Authorization": f"Token {api_key}"}
    if datos is not None:
        cabeceras["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{PAPERLESS_URL}{endpoint}", data=datos, headers=cabeceras, method=metodo)
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
        raise ErrorPaperless(
            f"No se ha podido conectar con Paperless-ngx ({PAPERLESS_URL}). "
            f"¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError:
        raise ErrorPaperless(f"Tiempo de espera agotado al contactar con Paperless-ngx ({PAPERLESS_URL}).")


def _token(username: str, password: str) -> str:
    datos = json.dumps({"username": username, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        f"{PAPERLESS_URL}/api/token/",
        data=datos,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            return json.loads(resp.read().decode("utf-8"))["token"]
    except urllib.error.HTTPError as e:
        raise ErrorPaperless(f"No se ha podido obtener un token de Paperless-ngx para '{username}': {e.read().decode('utf-8')}") from e
    except urllib.error.URLError as e:
        raise ErrorPaperless(f"No se ha podido conectar con Paperless-ngx ({PAPERLESS_URL}): {e.reason}") from e


_token_admin_cache: str | None = None


def _token_admin() -> str | None:
    """None si PAPERLESS_ADMIN_USER/PASSWORD no están configuradas —
    Paperless-ngx es opcional en esta integración, igual que EspoCRM sin
    ESPOCRM_API_KEY.

    El token se cachea en memoria del proceso tras la primera llamada, en
    vez de pedir uno nuevo en cada aprovisionamiento como se hacía al
    principio — verificado en vivo que `/api/token/` tiene un límite de
    peticiones real (HTTP 429 "Request was throttled") que salta al dar
    de alta varios tenants seguidos. El token de un usuario en
    Paperless-ngx no caduca por sí solo (hay que revocarlo a mano), así
    que cachearlo para toda la vida del proceso es seguro."""
    global _token_admin_cache
    if not PAPERLESS_ADMIN_USER or not PAPERLESS_ADMIN_PASSWORD:
        return None
    if _token_admin_cache is None:
        _token_admin_cache = _token(PAPERLESS_ADMIN_USER, PAPERLESS_ADMIN_PASSWORD)
    return _token_admin_cache


def _buscar_por_nombre(endpoint: str, campo: str, valor: str, token_admin: str) -> int | None:
    estado, cuerpo = _peticion(f"{endpoint}?{urllib.parse.urlencode({campo: valor})}", token_admin)
    if estado != 200:
        return None
    resultados = cuerpo.get("results", cuerpo if isinstance(cuerpo, list) else [])
    for r in resultados:
        if r.get(campo) == valor:
            return r["id"]
    return None


def aprovisionar_tenant(nombre_tenant: str) -> dict | None:
    """Crea el Grupo + el usuario de servicio de un tenant en
    Paperless-ngx, y genera su token de API — todo en una sola llamada,
    sin ningún paso manual. Devuelve {"group_id", "user_id", "api_key"},
    o None si PAPERLESS_ADMIN_USER/PASSWORD no están configuradas.
    Idempotente: si el Grupo o el usuario ya existen (reintento tras un
    fallo parcial), reutiliza sus ids en vez de fallar."""
    token_admin = _token_admin()
    if token_admin is None:
        return None

    estado, cuerpo = _peticion(
        "/api/groups/", token_admin, metodo="POST",
        cuerpo={"name": nombre_tenant, "permissions": PERMISOS_GRUPO_TENANT},
    )
    if estado in (200, 201):
        group_id = cuerpo["id"]
    else:
        group_id = _buscar_por_nombre("/api/groups/", "name", nombre_tenant, token_admin)
        if group_id is None:
            mensaje = cuerpo.get("detail") or cuerpo
            raise ErrorPaperless(f"No se ha podido crear el Grupo de Paperless-ngx para '{nombre_tenant}': {mensaje}")

    username = f"tenant-{nombre_tenant.lower().replace(' ', '-')}"
    contrasena = uuid.uuid4().hex  # de un solo uso, solo para sacar el token; no se guarda
    estado, cuerpo = _peticion(
        "/api/users/", token_admin, metodo="POST",
        cuerpo={
            "username": username, "password": contrasena,
            "groups": [group_id], "is_staff": False, "is_superuser": False,
        },
    )
    if estado in (200, 201):
        user_id = cuerpo["id"]
    else:
        user_id = _buscar_por_nombre("/api/users/", "username", username, token_admin)
        if user_id is None:
            mensaje = cuerpo.get("detail") or cuerpo
            raise ErrorPaperless(f"No se ha podido crear el usuario de servicio de Paperless-ngx para '{nombre_tenant}': {mensaje}")
        # El usuario ya existía de un intento anterior: su contraseña de
        # entonces no es la que acabamos de generar — hace falta
        # restablecerla para poder sacar un token nuevo.
        _peticion(f"/api/users/{user_id}/", token_admin, metodo="PATCH", cuerpo={"password": contrasena})

    api_key = _token(username, contrasena)
    return {"group_id": group_id, "user_id": user_id, "api_key": api_key}


def desaprovisionar_tenant(user_id: int | None, group_id: int | None) -> None:
    """Borra el usuario de servicio y el Grupo de un tenant. No falla si
    alguna pieza ya no existe (idempotente ante reintentos), ni si
    Paperless-ngx no está configurado."""
    token_admin = _token_admin()
    if token_admin is None:
        return
    if user_id is not None:
        _peticion(f"/api/users/{user_id}/", token_admin, metodo="DELETE")
    if group_id is not None:
        _peticion(f"/api/groups/{group_id}/", token_admin, metodo="DELETE")


# --- API de negocio (Fase MCP) — usa el token del propio tenant, nunca el de admin ---

def listar_documentos(api_key: str, texto: str | None = None, limite: int = 20) -> list[dict]:
    """Busca/lista documentos. Ya viene filtrado por
    DocumentPermissionsFilter (solo lo que el usuario de servicio del
    tenant puede ver) — no hace falta filtrar nada a mano aquí. []
    si `api_key` está vacía (tenant sin aprovisionar todavía)."""
    if not api_key:
        return []
    parametros = {"page_size": limite}
    if texto:
        parametros["query"] = texto
    estado, cuerpo = _peticion(f"/api/documents/?{urllib.parse.urlencode(parametros)}", api_key)
    if estado != 200:
        mensaje = cuerpo.get("detail") or cuerpo
        raise ErrorPaperless(f"No se han podido listar los documentos de Paperless-ngx: {mensaje}")
    return cuerpo.get("results", [])


def _esperar_tarea(task_id: str, api_key: str, *, intentos: int = 20, espera_segundos: float = 1.5) -> int:
    for _ in range(intentos):
        estado, cuerpo = _peticion(f"/api/tasks/?task_id={task_id}", api_key)
        if estado == 200 and cuerpo:
            resultados = cuerpo if isinstance(cuerpo, list) else cuerpo.get("results", [])
            tarea = resultados[0] if resultados else None
            if tarea is not None:
                # Verificado en vivo: los valores de `status` son en
                # minúscula ("success"/"failure", no "SUCCESS"/"FAILURE"
                # como en la documentación resumida), y el documento
                # creado viaja en `related_document_ids` (lista), no en
                # un campo `related_document` singular.
                if tarea.get("status") == "success":
                    ids = tarea.get("related_document_ids") or []
                    if ids:
                        return ids[0]
                if tarea.get("status") == "failure":
                    raise ErrorPaperless(f"Paperless-ngx no pudo procesar el documento subido: {tarea.get('result_data')}")
        time.sleep(espera_segundos)
    raise ErrorPaperless(f"Paperless-ngx no terminó de procesar el documento (tarea {task_id}) a tiempo.")


def subir_documento(api_key: str, owner_id: int, group_id: int, titulo: str, contenido_pdf: bytes, nombre_archivo: str) -> dict:
    """Sube un documento, espera a que Paperless-ngx termine de
    procesarlo (OCR incluido) y le aplica los permisos que cierran el
    aislamiento de verdad: propietario = usuario de servicio del tenant,
    visible/editable solo por su Grupo."""
    if not api_key:
        raise ErrorPaperless("Este tenant no tiene Paperless-ngx aprovisionado todavía.")
    limite = uuid.uuid4().hex
    cuerpo = (
        f"--{limite}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\n{titulo}\r\n"
        f"--{limite}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{nombre_archivo}\"\r\n"
        f"Content-Type: application/pdf\r\n\r\n"
    ).encode("utf-8") + contenido_pdf + f"\r\n--{limite}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        f"{PAPERLESS_URL}/api/documents/post_document/",
        data=cuerpo,
        headers={
            "Accept": "application/json", "Authorization": f"Token {api_key}",
            "Content-Type": f"multipart/form-data; boundary={limite}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            task_id = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ErrorPaperless(f"No se ha podido subir el documento '{titulo}' a Paperless-ngx: {e.read().decode('utf-8')}") from e
    except urllib.error.URLError as e:
        raise ErrorPaperless(f"No se ha podido conectar con Paperless-ngx ({PAPERLESS_URL}): {e.reason}") from e

    documento_id = _esperar_tarea(task_id, api_key)
    estado, documento = _peticion(
        f"/api/documents/{documento_id}/", api_key, metodo="PATCH",
        cuerpo={
            "owner": owner_id,
            "set_permissions": {
                "view": {"users": [], "groups": [group_id]},
                "change": {"users": [], "groups": [group_id]},
            },
        },
    )
    if estado != 200:
        mensaje = documento.get("detail") or documento
        raise ErrorPaperless(f"El documento {documento_id} se subió pero no se le pudieron aplicar los permisos: {mensaje}")
    return documento


def descargar_documento(api_key: str, documento_id: str) -> bytes:
    if not api_key:
        raise ErrorPaperless("Este tenant no tiene Paperless-ngx aprovisionado todavía.")
    req = urllib.request.Request(
        f"{PAPERLESS_URL}/api/documents/{documento_id}/download/",
        headers={"Authorization": f"Token {api_key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise ErrorPaperless(f"No se ha podido descargar el documento {documento_id} de Paperless-ngx (HTTP {e.code}).") from e
    except urllib.error.URLError as e:
        raise ErrorPaperless(f"No se ha podido conectar con Paperless-ngx ({PAPERLESS_URL}): {e.reason}") from e
