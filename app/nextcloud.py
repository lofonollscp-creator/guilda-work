"""Cliente de la API de Nextcloud (Fase Drive: aprovisiona el espacio de
cada tenant al crearlo desde el backoffice, ver app/rutas_backoffice.py).

Un tenant = un Grupo de Nextcloud + un Group Folder (app oficial "Group
folders", ver HOSTING.md 8.20) asignado a ese Grupo — es la pieza que
permite "compartir recursos dentro del tenant" (pedido explícito del
usuario) sin que aparezca en el Drive de otro tenant. El aislamiento de
verdad entre tenants no depende de esto (el directorio de cada usuario
ya es privado por diseño en Nextcloud) — depende del ajuste de admin
"Restringir a compartir solo con el propio grupo" (ver HOSTING.md), que
no se puede activar por API, solo desde el panel.

Auth: NEXTCLOUD_ADMIN_USER/NEXTCLOUD_ADMIN_PASSWORD (Basic Auth) — las
mismas credenciales del contenedor, ya obligatorias en docker-compose.yml,
sin generar un token aparte. Opcional a propósito para app/nextcloud.py:
si no están puestas en el entorno de esta app (por ejemplo en un entorno
de pruebas), `crear_espacio_tenant` no hace nada, mismo criterio que
METABASE_API_KEY/ESPOCRM_API_KEY.

La API de Provisioning de Nextcloud (OCS) envuelve siempre la respuesta
en `{"ocs": {"meta": {"statuscode": ...}, "data": {...}}}` con HTTP 200
casi siempre — el estado real está en `meta.statuscode`, no en el código
HTTP (a diferencia de EspoCRM/OpenProject). `?format=json` pide JSON en
vez de XML, es un parámetro oficial y estable de la API OCS.

Mismo criterio que el resto de app/*.py de integraciones: solo `urllib`
de la librería estándar.
"""
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

NEXTCLOUD_URL = os.environ.get("HERRAMIENTA_NEXTCLOUD_URL", "http://127.0.0.1:8016")
NEXTCLOUD_ADMIN_USER = os.environ.get("NEXTCLOUD_ADMIN_USER")
NEXTCLOUD_ADMIN_PASSWORD = os.environ.get("NEXTCLOUD_ADMIN_PASSWORD")
TIMEOUT_SEGUNDOS = 10

STATUSCODE_OK = 100
STATUSCODE_GRUPO_YA_EXISTE = 102


class ErrorNextcloud(Exception):
    """Error legible para mostrar cuando Nextcloud falla."""


def _cabecera_auth() -> dict:
    credenciales = base64.b64encode(
        f"{NEXTCLOUD_ADMIN_USER}:{NEXTCLOUD_ADMIN_PASSWORD}".encode()
    ).decode()
    return {"Authorization": f"Basic {credenciales}"}


def _peticion(url: str, *, metodo: str = "GET", cuerpo: dict | None = None):
    datos = urllib.parse.urlencode(cuerpo).encode("utf-8") if cuerpo is not None else None
    cabeceras = {
        "Accept": "application/json",
        "OCS-APIRequest": "true",
        **_cabecera_auth(),
    }
    if datos is not None:
        cabeceras["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=datos, headers=cabeceras, method=metodo)
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
        raise ErrorNextcloud(
            f"No se ha podido conectar con Nextcloud ({url}). ¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError as e:
        raise ErrorNextcloud(f"Tiempo de espera agotado al contactar con Nextcloud ({url}).")


def _crear_grupo(nombre_tenant: str) -> None:
    estado, cuerpo = _peticion(
        f"{NEXTCLOUD_URL}/ocs/v1.php/cloud/groups?format=json",
        metodo="POST",
        cuerpo={"groupid": nombre_tenant},
    )
    statuscode = cuerpo.get("ocs", {}).get("meta", {}).get("statuscode")
    if estado != 200 or statuscode not in (STATUSCODE_OK, STATUSCODE_GRUPO_YA_EXISTE):
        mensaje = cuerpo.get("ocs", {}).get("meta", {}).get("message") or cuerpo
        raise ErrorNextcloud(f"No se ha podido crear el grupo en Nextcloud: {mensaje}")


def _buscar_carpeta_por_mountpoint(nombre_tenant: str) -> int | None:
    estado, cuerpo = _peticion(f"{NEXTCLOUD_URL}/apps/groupfolders/folders?format=json")
    if estado != 200:
        return None
    datos = cuerpo.get("ocs", {}).get("data", {})
    carpetas = datos.values() if isinstance(datos, dict) else datos
    for carpeta in carpetas:
        if carpeta.get("mount_point") == nombre_tenant:
            return carpeta.get("id")
    return None


def _crear_carpeta_de_grupo(nombre_tenant: str) -> None:
    """Crea el Group Folder y le concede acceso al grupo del tenant — la
    app "Group folders" tiene que estar activada (`occ app:enable
    groupfolders`, ver HOSTING.md 8.20), si no esta llamada falla.
    Idempotente: si ya existe una carpeta con ese mountpoint (repetir el
    alta del mismo tenant), se reutiliza en vez de crear una duplicada."""
    folder_id = _buscar_carpeta_por_mountpoint(nombre_tenant)
    if folder_id is None:
        estado, cuerpo = _peticion(
            f"{NEXTCLOUD_URL}/apps/groupfolders/folders?format=json",
            metodo="POST",
            cuerpo={"mountpoint": nombre_tenant},
        )
        datos = cuerpo.get("ocs", {}).get("data", {})
        folder_id = datos.get("id") if isinstance(datos, dict) else None
        if estado != 200 or folder_id is None:
            mensaje = cuerpo.get("ocs", {}).get("meta", {}).get("message") or cuerpo
            raise ErrorNextcloud(f"No se ha podido crear la carpeta compartida en Nextcloud: {mensaje}")

    estado, cuerpo = _peticion(
        f"{NEXTCLOUD_URL}/apps/groupfolders/folders/{folder_id}/groups?format=json",
        metodo="POST",
        cuerpo={"group": nombre_tenant},
    )
    if estado != 200:
        mensaje = cuerpo.get("ocs", {}).get("meta", {}).get("message") or cuerpo
        raise ErrorNextcloud(f"No se ha podido dar acceso al grupo sobre la carpeta: {mensaje}")


def crear_espacio_tenant(nombre_tenant: str) -> None:
    """Crea el Grupo y su Group Folder para un tenant. No hace nada (sin
    fallar) si NEXTCLOUD_ADMIN_USER/NEXTCLOUD_ADMIN_PASSWORD no están
    configurados — Nextcloud es opcional en esta integración, igual que
    EspoCRM/Metabase con su credencial opcional."""
    if not NEXTCLOUD_ADMIN_USER or not NEXTCLOUD_ADMIN_PASSWORD:
        return
    _crear_grupo(nombre_tenant)
    _crear_carpeta_de_grupo(nombre_tenant)
