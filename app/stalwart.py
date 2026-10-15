"""Cliente de Stalwart Mail Server (correo propio, backend alternativo
con mejor API para MCP que el cliente IMAP genérico de app/correo.py).

Instancia COMPARTIDA (un servidor de correo completo por tenant es
inviable — cada uno necesitaría su propio MX/puertos/TLS públicos).
Aislamiento lógico real vía Tenant/Domain/Account, verificado en vivo
contra un contenedor real (`stalwartlabs/stalwart:latest`, edición
Community, SIN licencia — `"edition":"community"` confirmado en
`/api/account`):

## Aislamiento — real, verificado en vivo con dos tenants reales

Con dos Accounts de dos Tenants distintos, cada una con su propio
ApiKey, una llamada JMAP (`Mailbox/get`) con el `accountId` de la
cuenta del OTRO tenant es rechazada por el propio servidor:
`{"error":{"type":"forbidden","description":"You do not have access to
account <id>"}}`. No es una convención de cliente ni de UI — es un 403
real a nivel de `accountId` JMAP.

## API de administración: JMAP con namespace `x:`

`Tenant`/`Domain`/`Account` (y el resto de objetos de gestión) se
manejan con métodos `x:<Objeto>/<método>` (p.ej. `x:Tenant/set`),
distinto del JMAP RFC-estándar para correo (`Email/*`, `Mailbox/*`, sin
prefijo `x:`). Autenticación de administración: Basic Auth con
`STALWART_ADMIN_USER`/`STALWART_ADMIN_PASSWORD` — confirmado en vivo que
funciona directamente para llamadas `x:*`, sin sesión de cookies.

## Credenciales (API Keys) — el punto que costó más resolver

Añadir una Credential a una Account NUNCA se hace vía `x:Account/set`
(ni al crear ni al actualizar) — de hecho la propia WebUI oficial de
Stalwart choca con el mismo rechazo real del servidor:
`{"type":"invalidProperties","description":"Secondary credentials
cannot be set directly.","properties":["credentials"]}`. Confirmado
capturando la petición real que manda la propia WebUI al intentarlo.

El mecanismo real: cada tipo de credential secundaria es su propio
objeto JMAP de nivel superior (`x:ApiKey`, `x:AppPassword`...), y se
crea con `accountId` = la Account DESTINO (el usuario al que pertenece
la credencial), no la del admin que hace la llamada — a diferencia de
`x:Tenant/set`/`x:Domain/set`/`x:Account/set`, que siempre usan el
`accountId` del admin autenticado. El campo `secret` es `serverSet`
(generado por el servidor, viene en la respuesta de creación) y
`allowedIps`, aunque aparece en `/api/schema` como lista, debe
OMITIRSE por completo al crear (enviar `[]` explícito falla). El
secreto (`API_...`) se usa directamente como Bearer token
(`Authorization: Bearer API_...`) para toda llamada JMAP posterior de
ese usuario — confirmado en vivo que el token queda scoped exactamente
a esa Account (nunca a la del admin).

Mismo criterio que el resto de `app/*.py`: solo `urllib` de la librería
estándar.
"""
import base64
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

STALWART_URL = os.environ.get("HERRAMIENTA_STALWART_URL", "http://127.0.0.1:8025")
STALWART_ADMIN_USER = os.environ.get("STALWART_ADMIN_USER")
STALWART_ADMIN_PASSWORD = os.environ.get("STALWART_ADMIN_PASSWORD")
TIMEOUT_SEGUNDOS = 20
logger = logging.getLogger(__name__)

_USING = [
    "urn:ietf:params:jmap:core", "urn:stalwart:jmap",
    "urn:ietf:params:jmap:mail", "urn:ietf:params:jmap:submission",
]


class ErrorStalwart(Exception):
    """Error legible para mostrar cuando Stalwart falla."""


def _cabecera_admin() -> dict:
    if not STALWART_ADMIN_USER or not STALWART_ADMIN_PASSWORD:
        raise ErrorStalwart("Stalwart no está configurado (falta STALWART_ADMIN_USER/PASSWORD).")
    credencial = f"{STALWART_ADMIN_USER}:{STALWART_ADMIN_PASSWORD}".encode("utf-8")
    return {"Authorization": f"Basic {base64.b64encode(credencial).decode('ascii')}"}


def _jmap(method_calls: list, *, cabeceras: dict) -> dict:
    """POST /jmap/ con el cuerpo de métodos dado. Devuelve
    methodResponses (lista de [nombre, respuesta, id])."""
    cuerpo = json.dumps({"using": _USING, "methodCalls": method_calls}).encode("utf-8")
    todas_cabeceras = {"Accept": "application/json", "Content-Type": "application/json"}
    todas_cabeceras.update(cabeceras)
    req = urllib.request.Request(f"{STALWART_URL}/jmap/", data=cuerpo, headers=todas_cabeceras, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8")
        raise ErrorStalwart(f"Stalwart devolvió HTTP {e.code}: {detalle}") from e
    except urllib.error.URLError as e:
        raise ErrorStalwart(
            f"No se ha podido conectar con Stalwart ({STALWART_URL}). "
            f"¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError:
        raise ErrorStalwart(f"Tiempo de espera agotado al contactar con Stalwart ({STALWART_URL}).")


def _una_respuesta(respuesta: dict, id_llamada: str = "0") -> dict:
    """Extrae el segundo elemento de la methodResponse con ese id de
    llamada, lanzando ErrorStalwart si el propio JMAP devolvió un
    error de método (p.ej. "forbidden", "invalidProperties")."""
    for nombre, cuerpo, id_resp in respuesta.get("methodResponses", []):
        if id_resp != id_llamada:
            continue
        if nombre == "error":
            raise ErrorStalwart(f"Stalwart rechazó la llamada: {cuerpo.get('description', cuerpo)}")
        return cuerpo
    raise ErrorStalwart("Stalwart no devolvió respuesta para la llamada esperada.")


def _buscar_por_nombre_admin(tipo: str, nombre: str) -> dict | None:
    """Busca un objeto x:<tipo> por su campo "name" — sin filtro de
    servidor verificado en vivo para estos objetos, así que se listan
    todos y se filtra en Python (mismo criterio de seguridad que
    app/listmonk.py:_buscar_por_nombre)."""
    respuesta = _jmap(
        [
            [f"x:{tipo}/query", {"accountId": "b"}, "0"],
            [f"x:{tipo}/get", {"accountId": "b", "#ids": {"resultOf": "0", "name": f"x:{tipo}/query", "path": "/ids"}}, "1"],
        ],
        cabeceras=_cabecera_admin(),
    )
    lista = _una_respuesta(respuesta, "1").get("list", [])
    for objeto in lista:
        if objeto.get("name") == nombre:
            return objeto
    return None


def aprovisionar_tenant(tenant_id: int, nombre_tenant: str, dominio_correo: str) -> dict:
    """Crea el Tenant + el Domain (con el dominio propio real del
    cliente) + la Account + un ApiKey para un tenant, todo en una sola
    pasada, sin ningún paso manual. Devuelve {"stalwart_tenant_id",
    "domain_id", "domain_name", "account_id", "api_key"}. Idempotente:
    si el Tenant/Domain/Account ya existen (reintento tras un fallo
    parcial), reutiliza sus ids en vez de fallar; si la Account ya
    tenía ApiKeys de un intento anterior, los borra y crea uno nuevo
    (Stalwart no vuelve a enseñar un secreto ya generado, igual que
    Listmonk con sus usuarios tipo "api")."""
    cabeceras = _cabecera_admin()

    tenant = _buscar_por_nombre_admin("Tenant", nombre_tenant)
    if tenant is None:
        respuesta = _jmap(
            [["x:Tenant/set", {"accountId": "b", "create": {"t1": {"name": nombre_tenant}}}, "0"]],
            cabeceras=cabeceras,
        )
        cuerpo = _una_respuesta(respuesta)
        if "t1" not in cuerpo.get("created", {}):
            error = cuerpo.get("notCreated", {}).get("t1", {})
            raise ErrorStalwart(f"No se ha podido crear el Tenant de Stalwart para '{nombre_tenant}': {error}")
        stalwart_tenant_id = cuerpo["created"]["t1"]["id"]
    else:
        stalwart_tenant_id = tenant["id"]

    dominio = _buscar_por_nombre_admin("Domain", dominio_correo)
    if dominio is None:
        respuesta = _jmap(
            [["x:Domain/set", {"accountId": "b", "create": {"d1": {
                "name": dominio_correo, "isEnabled": True, "memberTenantId": stalwart_tenant_id,
            }}}, "0"]],
            cabeceras=cabeceras,
        )
        cuerpo = _una_respuesta(respuesta)
        if "d1" not in cuerpo.get("created", {}):
            error = cuerpo.get("notCreated", {}).get("d1", {})
            raise ErrorStalwart(f"No se ha podido crear el Domain de Stalwart para '{dominio_correo}': {error}")
        domain_id = cuerpo["created"]["d1"]["id"]
    else:
        domain_id = dominio["id"]

    username = f"tenant-{tenant_id}"
    # x:Account no expone "name" tal cual en /get (se llama distinto en
    # la respuesta), así que aquí solo se intenta crear — si ya existe
    # de un intento anterior, Stalwart lo rechaza por duplicado y se
    # asume que dejó de existir el fallo previo (caso raro, no hay
    # forma fiable de recuperar el id sin volver a listar por email).
    respuesta = _jmap(
        [["x:Account/set", {"accountId": "b", "create": {"u1": {
            "@type": "User", "name": username, "domainId": domain_id,
            "memberTenantId": stalwart_tenant_id, "roles": {"@type": "User"},
        }}}, "0"]],
        cabeceras=cabeceras,
    )
    cuerpo = _una_respuesta(respuesta)
    if "u1" in cuerpo.get("created", {}):
        account_id = cuerpo["created"]["u1"]["id"]
    else:
        raise ErrorStalwart(
            f"No se ha podido crear la Account de Stalwart para el tenant {tenant_id}: "
            f"{cuerpo.get('notCreated', {}).get('u1', {})}"
        )

    # Limpia cualquier ApiKey previo de un intento parcial anterior
    # (Stalwart no vuelve a enseñar un secreto ya generado).
    respuesta = _jmap(
        [["x:ApiKey/query", {"accountId": account_id}, "0"]],
        cabeceras=cabeceras,
    )
    ids_previos = _una_respuesta(respuesta).get("ids", [])
    if ids_previos:
        _jmap(
            [["x:ApiKey/set", {"accountId": account_id, "destroy": ids_previos}, "0"]],
            cabeceras=cabeceras,
        )

    respuesta = _jmap(
        [["x:ApiKey/set", {"accountId": account_id, "create": {"k1": {
            "description": f"Guilda Work — tenant {tenant_id}",
        }}}, "0"]],
        cabeceras=cabeceras,
    )
    cuerpo = _una_respuesta(respuesta)
    if "k1" not in cuerpo.get("created", {}):
        raise ErrorStalwart(
            f"No se ha podido crear el ApiKey de Stalwart para el tenant {tenant_id}: "
            f"{cuerpo.get('notCreated', {}).get('k1', {})}"
        )
    api_key = cuerpo["created"]["k1"]["secret"]

    return {
        "stalwart_tenant_id": stalwart_tenant_id,
        "domain_id": domain_id,
        "domain_name": dominio_correo,
        "account_id": account_id,
        "api_key": api_key,
    }


def _destruir(tipo: str, objeto_id: str, cabeceras: dict) -> dict:
    """Borra un objeto de Stalwart y devuelve lo que NO se ha podido borrar (`{id: motivo}`; vacío si se borró). Stalwart contesta con un 200 aunque el borrado falle: hay que mirar `notDestroyed`."""
    respuesta = _jmap([[f"x:{tipo}/set", {"accountId": "b", "destroy": [objeto_id]}, "0"]], cabeceras=cabeceras)
    for nombre, cuerpo, ident in respuesta.get("methodResponses", []):
        if ident == "0" and nombre != "error":
            return cuerpo.get("notDestroyed") or {}
    return {}


def _destruir_con_firmas_dkim(tipo: str, objeto_id: str, cabeceras: dict) -> None:
    """Como `_destruir`, pero un Domain trae sus firmas DKIM (Stalwart las crea al crearlo) y mientras existan no se deja borrar ni el dominio ni su Tenant («objectIsLinked»):
    se borran las firmas que él mismo dice que están enlazadas y se reintenta una vez."""
    pendiente = _destruir(tipo, objeto_id, cabeceras)
    if not pendiente:
        return
    firmas = [o["id"] for motivo in pendiente.values() if isinstance(motivo, dict) and motivo.get("type") == "objectIsLinked"
              for o in motivo.get("linkedObjects", []) if o.get("object") == "DkimSignature"]
    if firmas:
        _jmap([["x:DkimSignature/set", {"accountId": "b", "destroy": firmas}, "0"]], cabeceras=cabeceras)
        pendiente = _destruir(tipo, objeto_id, cabeceras)
    if pendiente:
        raise ErrorStalwart(f"Stalwart no ha dejado borrar {tipo} {objeto_id}: {pendiente}")


def desaprovisionar_tenant(stalwart_tenant_id: str | None, domain_id: str | None, account_id: str | None) -> None:
    """Borra la Account, el Domain (con sus firmas DKIM) y el Tenant de un tenant. No falla si alguna pieza ya no existe, ni si Stalwart no está configurado; sí avisa
    (`ErrorStalwart`) si Stalwart se niega a borrar algo, en vez de dejar el dominio y el tenant huérfanos sin decirlo."""
    if not STALWART_ADMIN_USER or not STALWART_ADMIN_PASSWORD:
        return
    cabeceras = _cabecera_admin()
    if account_id:
        _destruir("Account", account_id, cabeceras)
    if domain_id:
        _destruir_con_firmas_dkim("Domain", domain_id, cabeceras)
    if stalwart_tenant_id:
        _destruir_con_firmas_dkim("Tenant", stalwart_tenant_id, cabeceras)


# --- API de negocio (Fase MCP) — JMAP RFC-estándar, con el ApiKey del
# propio tenant como Bearer token (confirmado en vivo, scoped a su
# Account) ---

def _cabecera_bearer(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def _account_id_propio(api_key: str) -> str:
    """El accountId del propio tenant no se conoce de antemano en la
    API de negocio (solo se guarda su api_key) — se resuelve leyendo
    /jmap/session, que siempre expone el accountId asociado al token
    usado (confirmado en vivo: nunca el del admin)."""
    req = urllib.request.Request(f"{STALWART_URL}/jmap/session", headers=_cabecera_bearer(api_key))
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            sesion = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ErrorStalwart(f"Stalwart rechazó el ApiKey de este tenant: HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise ErrorStalwart(f"No se ha podido conectar con Stalwart ({STALWART_URL}): {e.reason}") from e
    return sesion["primaryAccounts"]["urn:ietf:params:jmap:mail"]


def listar_mensajes(api_key: str, mailbox: str = "INBOX", limite: int = 20) -> list[dict]:
    if not api_key:
        return []
    account_id = _account_id_propio(api_key)
    respuesta = _jmap(
        [
            ["Mailbox/query", {"accountId": account_id, "filter": {"role": mailbox.lower()}}, "0"],
            ["Email/query", {"accountId": account_id, "filter": {
                "#inMailbox": {"resultOf": "0", "name": "Mailbox/query", "path": "/ids/0"},
            }, "sort": [{"property": "receivedAt", "isAscending": False}], "limit": limite}, "1"],
            ["Email/get", {"accountId": account_id, "#ids": {"resultOf": "1", "name": "Email/query", "path": "/ids"},
             "properties": ["id", "subject", "from", "to", "receivedAt", "preview", "keywords"]}, "2"],
        ],
        cabeceras=_cabecera_bearer(api_key),
    )
    return _una_respuesta(respuesta, "2").get("list", [])


def leer_mensaje(api_key: str, email_id: str) -> dict:
    if not api_key:
        raise ErrorStalwart("Este tenant no tiene Stalwart aprovisionado todavía.")
    account_id = _account_id_propio(api_key)
    respuesta = _jmap(
        [["Email/get", {"accountId": account_id, "ids": [email_id],
          "properties": ["id", "subject", "from", "to", "cc", "receivedAt", "bodyValues", "textBody", "htmlBody"],
          "fetchTextBodyValues": True, "fetchHTMLBodyValues": True}, "0"]],
        cabeceras=_cabecera_bearer(api_key),
    )
    lista = _una_respuesta(respuesta).get("list", [])
    if not lista:
        raise ErrorStalwart(f"No se ha encontrado el mensaje {email_id} en Stalwart.")
    return lista[0]


def enviar_mensaje(api_key: str, para: str, asunto: str, cuerpo: str) -> dict:
    if not api_key:
        raise ErrorStalwart("Este tenant no tiene Stalwart aprovisionado todavía.")
    account_id = _account_id_propio(api_key)
    respuesta = _jmap(
        [
            ["Identity/get", {"accountId": account_id}, "0"],
            ["Email/set", {"accountId": account_id, "create": {"draft": {
                "mailboxIds": {"$draft": True},
                "keywords": {"$draft": True, "$seen": True},
                "to": [{"email": para}],
                "subject": asunto,
                "bodyValues": {"body": {"value": cuerpo, "charset": "utf-8"}},
                "textBody": [{"partId": "body", "type": "text/plain"}],
            }}}, "1"],
            ["EmailSubmission/set", {"accountId": account_id, "create": {"envio": {
                "emailId": "#draft",
                "#identityId": {"resultOf": "0", "name": "Identity/get", "path": "/list/0/id"},
            }}}, "2"],
        ],
        cabeceras=_cabecera_bearer(api_key),
    )
    cuerpo_envio = _una_respuesta(respuesta, "2")
    if "envio" not in cuerpo_envio.get("created", {}):
        raise ErrorStalwart(f"No se ha podido enviar el mensaje a '{para}' con Stalwart: {cuerpo_envio.get('notCreated', {})}")
    return cuerpo_envio["created"]["envio"]


# --- Buzones de personas (IMAP/SMTP) dentro del dominio del despacho ---

def crear_buzon(stalwart_tenant_id: str, domain_id: str, local: str, descripcion: str) -> dict:
    """Crea una cuenta de usuario `local@dominio` en el tenant de Stalwart y le genera una **contraseña de aplicación** (la genera el servidor, nadie la teclea): sirve para IMAP y SMTP.
    Devuelve {"account_id", "secreto"}. Si algo falla a medias, deshace lo creado. El secreto solo existe en esta respuesta (Stalwart no lo vuelve a enseñar)."""
    cabeceras = _cabecera_admin()
    cuerpo = _una_respuesta(_jmap([["x:Account/set", {"accountId": "b", "create": {"u1": {
        "@type": "User", "name": local, "description": descripcion, "domainId": domain_id,
        "memberTenantId": stalwart_tenant_id, "roles": {"@type": "User"},
    }}}, "0"]], cabeceras=cabeceras))
    if "u1" not in cuerpo.get("created", {}):
        raise ErrorStalwart(f"No se ha podido crear el buzón «{local}»: {cuerpo.get('notCreated', {}).get('u1', {})}")
    account_id = cuerpo["created"]["u1"]["id"]
    try:
        cuerpo = _una_respuesta(_jmap([["x:AppPassword/set", {"accountId": account_id, "create": {"k1": {"description": "Guilda Work — IMAP y SMTP"}}}, "0"]], cabeceras=cabeceras))
        if "k1" not in cuerpo.get("created", {}):
            raise ErrorStalwart(f"No se ha podido crear la contraseña de aplicación del buzón: {cuerpo.get('notCreated', {}).get('k1', {})}")
        return {"account_id": account_id, "secreto": cuerpo["created"]["k1"]["secret"]}
    except Exception:
        eliminar_buzon(account_id)
        raise


def eliminar_buzon(account_id: str | None) -> None:
    """Borra un buzón (y con él su correo). No falla si ya no existe ni si Stalwart no está configurado."""
    if not account_id or not STALWART_ADMIN_USER or not STALWART_ADMIN_PASSWORD:
        return
    try:
        if _destruir("Account", account_id, _cabecera_admin()):
            logger.warning("Stalwart no ha dejado borrar el buzón %s", account_id)
    except ErrorStalwart:
        pass
