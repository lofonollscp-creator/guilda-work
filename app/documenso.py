"""Cliente de la API pública de Documenso (Fase firmas: enviar documentos
a firmar desde un asistente, ver mcp_tools.py).

**Sin funciones de aprovisionamiento** — a diferencia de
`app/espocrm.py`/`app/nextcloud.py`/`app/facturascripts.py`, este módulo
NO tiene ningún `crear_equipo()`/`invitar_miembro()`. Verificado en vivo,
levantando una instancia real con Docker y descargando el spec OpenAPI
real directamente del propio contenedor (`GET /api/v2-beta/openapi.json`,
no la documentación de marketing): 89 endpoints reales, ninguno de
Equipos/Organización/miembros — todos son `/document/*`, `/envelope/*`,
`/template/*`, `/folder/*`, `/embedding/*`. Gestión de Equipos y altas de
miembros se hace exclusivamente desde la interfaz web de Documenso, sin
vía de automatización real (ver HOSTING.md para los pasos manuales).

También confirmado en la documentación oficial de Documenso: el "SSO
Portal" (login vía Ory Hydra, como EspoCRM/Nextcloud) es una función de
pago (Enterprise) — aquí no hay SSO, cada persona inicia sesión con sus
propias credenciales de Documenso.

Aislamiento entre tenants: cada tenant tiene su propio Equipo en
Documenso (creado a mano) y su propio token de API, generado **desde
dentro de la configuración de ese Equipo** (no desde la cuenta
personal) — ese origen es lo que da al token el contexto de Equipo para
todas las llamadas. `tenants.documenso_api_key` (`app/db.py`) guarda ese
token; quien llama a este módulo (`mcp_tools.py`) lo resuelve y lo pasa
explícito, mismo desacoplo de `app/db.py` que el resto de `app/*.py`.

Mismo criterio que el resto de app/*.py: solo `urllib`, salvo el
`email.mime`/`uuid` de la librería estándar para construir el cuerpo
multipart (Documenso exige `multipart/form-data` para crear documentos,
con el PDF como parte binaria — no hay forma de mandarlo como JSON).
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

DOCUMENSO_URL = os.environ.get("HERRAMIENTA_DOCUMENSO_URL", "http://127.0.0.1:8018")
TIMEOUT_SEGUNDOS = 20


class ErrorDocumenso(Exception):
    """Error legible para mostrar cuando Documenso falla."""


def _peticion_json(endpoint: str, api_key: str, *, metodo: str = "GET", cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    cabeceras = {"Accept": "application/json", "Authorization": api_key}
    if datos is not None:
        cabeceras["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{DOCUMENSO_URL}/api/v2-beta{endpoint}", data=datos, headers=cabeceras, method=metodo)
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
        raise ErrorDocumenso(
            f"No se ha podido conectar con Documenso ({DOCUMENSO_URL}). ¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError as e:
        raise ErrorDocumenso(f"Tiempo de espera agotado al contactar con Documenso ({DOCUMENSO_URL}).")


def listar_documentos(api_key: str, texto: str | None = None, limite: int = 20) -> list[dict]:
    """Busca/lista documentos (envelopes de tipo DOCUMENT). [] si
    `api_key` está vacía (tenant sin token de Documenso guardado
    todavía)."""
    if not api_key:
        return []
    parametros = {"perPage": limite, "type": "DOCUMENT"}
    if texto:
        parametros["query"] = texto
    estado, cuerpo = _peticion_json(f"/envelope?{urllib.parse.urlencode(parametros)}", api_key)
    if estado != 200:
        mensaje = cuerpo.get("message") or cuerpo.get("error") or cuerpo
        raise ErrorDocumenso(f"No se han podido listar los documentos de Documenso: {mensaje}")
    return cuerpo.get("data", cuerpo if isinstance(cuerpo, list) else [])


def _cuerpo_multipart(campos: dict, nombre_archivo: str, contenido_pdf: bytes) -> tuple[bytes, str]:
    """Construye un cuerpo multipart/form-data con dos partes: `payload`
    (JSON) y `files` (el PDF) — Documenso exige exactamente estos
    nombres de parte (confirmado en el spec OpenAPI real)."""
    limite = uuid.uuid4().hex
    partes = []
    for nombre, valor in campos.items():
        partes.append(
            f"--{limite}\r\nContent-Disposition: form-data; name=\"{nombre}\"\r\n\r\n{valor}\r\n".encode("utf-8")
        )
    partes.append(
        f"--{limite}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{nombre_archivo}\"\r\n"
        f"Content-Type: application/pdf\r\n\r\n".encode("utf-8")
        + contenido_pdf
        + b"\r\n"
    )
    partes.append(f"--{limite}--\r\n".encode("utf-8"))
    return b"".join(partes), f"multipart/form-data; boundary={limite}"


def crear_documento(api_key: str, titulo: str, contenido_pdf: bytes, firmantes: list[dict]) -> dict:
    """Crea un documento (envelope) y lo deja en borrador, listo para
    `enviar_a_firma`. `firmantes`: lista de {"email": str, "nombre": str}
    — cada uno recibe un único campo de firma en la primera página,
    posicionado por defecto (esquina inferior derecha); para colocar
    campos a medida, usa la propia interfaz web de Documenso."""
    if not api_key:
        raise ErrorDocumenso("Este tenant no tiene un token de Documenso configurado todavía.")
    recipients = [
        {
            "email": f["email"],
            "name": f.get("nombre", ""),
            "role": "SIGNER",
            "fields": [{
                "type": "SIGNATURE",
                "page": 1,
                "positionX": 70, "positionY": 85, "width": 20, "height": 5,
            }],
        }
        for f in firmantes
    ]
    payload = json.dumps({"title": titulo, "type": "DOCUMENT", "recipients": recipients})
    cuerpo, content_type = _cuerpo_multipart({"payload": payload}, "documento.pdf", contenido_pdf)

    req = urllib.request.Request(
        f"{DOCUMENSO_URL}/api/v2-beta/envelope/create",
        data=cuerpo,
        headers={"Accept": "application/json", "Authorization": api_key, "Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            resultado = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        mensaje = e.read().decode("utf-8")
        raise ErrorDocumenso(f"No se ha podido crear el documento '{titulo}' en Documenso: {mensaje}") from e
    except urllib.error.URLError as e:
        raise ErrorDocumenso(f"No se ha podido conectar con Documenso ({DOCUMENSO_URL}): {e.reason}") from e
    return resultado


def enviar_a_firma(api_key: str, documento_id: str) -> dict:
    """Distribuye un documento en borrador — manda el email de firma a
    cada destinatario."""
    if not api_key:
        raise ErrorDocumenso("Este tenant no tiene un token de Documenso configurado todavía.")
    estado, cuerpo = _peticion_json(
        "/envelope/distribute", api_key, metodo="POST", cuerpo={"envelopeId": documento_id}
    )
    if estado != 200:
        mensaje = cuerpo.get("message") or cuerpo.get("error") or cuerpo
        raise ErrorDocumenso(f"No se ha podido enviar a firma el documento {documento_id} de Documenso: {mensaje}")
    return cuerpo


def descargar_firmado(api_key: str, documento_id: str) -> bytes:
    """Descarga el PDF de un documento (firmado del todo o no — el propio
    PDF refleja el estado actual). Verificado en vivo: el documento en sí
    no se descarga por su propio id, sino por el id de su
    "envelope item" (`envelopeItems[].id` al consultar
    `GET /envelope/{id}`) — un documento normal (no combinado a partir de
    varios archivos) tiene un único item, así que se resuelve aquí sin
    que quien llama tenga que conocer ese detalle."""
    if not api_key:
        raise ErrorDocumenso("Este tenant no tiene un token de Documenso configurado todavía.")
    estado, envelope = _peticion_json(f"/envelope/{documento_id}", api_key)
    if estado != 200:
        mensaje = envelope.get("message") or envelope.get("error") or envelope
        raise ErrorDocumenso(f"No se ha podido consultar el documento {documento_id} de Documenso: {mensaje}")
    items = envelope.get("envelopeItems", [])
    if not items:
        raise ErrorDocumenso(f"El documento {documento_id} de Documenso no tiene ningún archivo asociado.")
    item_id = items[0]["id"]

    req = urllib.request.Request(
        f"{DOCUMENSO_URL}/api/v2-beta/envelope/item/{item_id}/download",
        headers={"Authorization": api_key},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise ErrorDocumenso(f"No se ha podido descargar el documento {documento_id} de Documenso (HTTP {e.code}).") from e
    except urllib.error.URLError as e:
        raise ErrorDocumenso(f"No se ha podido conectar con Documenso ({DOCUMENSO_URL}): {e.reason}") from e
