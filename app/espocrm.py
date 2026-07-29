"""Cliente de la API v1 de EspoCRM (Fase CRM: aprovisiona un Equipo por
tenant al crearlo desde el backoffice, ver app/rutas_backoffice.py).

El Equipo es la pieza central del aislamiento entre tenants: EspoCRM
asocia a cada usuario, en cada login, al Equipo cuyo nombre coincide con
el claim `groups` del id_token de Hydra (configuración `oidcTeams` en
Administration → Authentication, ver HOSTING.md) — y los Roles con nivel
de acceso "Team" en Lead/Contact/Account impiden ver registros de otros
Equipos, incluso vía API. Sin el Equipo creado de antemano, ese mapeo no
tiene a qué asociar al usuario.

Auth: API Key de un API User dedicado (Administration → API Users, método
"API Key"), igual que METABASE_API_KEY — se genera una vez a mano y es
opcional a propósito: sin ella, `crear_equipo` no hace nada (no bloquea
la creación del tenant en Guilda Work, ver rutas_backoffice.py).

Mismo criterio que app/kratos.py/app/hydra.py/app/openproject.py: solo
`urllib` de la librería estándar, ningún cliente HTTP nuevo como
dependencia.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

ESPOCRM_URL = os.environ.get("HERRAMIENTA_ESPOCRM_URL", "http://127.0.0.1:8015")
ESPOCRM_API_KEY = os.environ.get("ESPOCRM_API_KEY")
TIMEOUT_SEGUNDOS = 10


class ErrorEspoCRM(Exception):
    """Error legible para mostrar cuando EspoCRM falla."""


def _peticion(url: str, *, metodo: str = "GET", cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    cabeceras = {"Accept": "application/json", "X-Api-Key": ESPOCRM_API_KEY or ""}
    if datos is not None:
        cabeceras["Content-Type"] = "application/json"
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
        raise ErrorEspoCRM(
            f"No se ha podido conectar con EspoCRM ({url}). ¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError as e:
        raise ErrorEspoCRM(f"Tiempo de espera agotado al contactar con EspoCRM ({url}).")


def _buscar_equipo_por_nombre(nombre: str) -> str | None:
    filtro = json.dumps([{"type": "equals", "attribute": "name", "value": nombre}])
    estado, cuerpo = _peticion(
        f"{ESPOCRM_URL}/api/v1/Team?where={urllib.parse.quote(filtro)}"
    )
    if estado != 200:
        return None
    elementos = cuerpo.get("list", [])
    return elementos[0]["id"] if elementos else None


def crear_equipo(nombre_tenant: str) -> str | None:
    """Crea el Equipo de EspoCRM correspondiente a un tenant. Devuelve
    None (sin hacer nada) si ESPOCRM_API_KEY no está configurada — EspoCRM
    es opcional en esta integración, igual que Metabase lo es sin
    METABASE_API_KEY. Idempotente: si ya existe un Equipo con ese nombre,
    devuelve su id existente en vez de fallar."""
    if not ESPOCRM_API_KEY:
        return None
    estado, cuerpo = _peticion(
        f"{ESPOCRM_URL}/api/v1/Team",
        metodo="POST",
        cuerpo={"name": nombre_tenant},
    )
    if estado in (200, 201):
        return cuerpo["id"]
    existente = _buscar_equipo_por_nombre(nombre_tenant)
    if existente is not None:
        return existente
    mensaje = cuerpo.get("message") or cuerpo.get("error") or cuerpo
    raise ErrorEspoCRM(f"No se ha podido crear el Equipo en EspoCRM: {mensaje}")
