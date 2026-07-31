"""Cliente de Cal.diy (Fase citas: reserva de citas tipo Cal.com, ver
mcp_tools.py).

## Por qué Cal.diy y no Cal.com

Cal.com dejó de ser open source en julio de 2026 (el repositorio pasó a
privado). La continuación libre real es **Cal.diy**
(`github.com/calcom/cal.diy`, licencia MIT) — mismo motor de reservas,
sin SSO/SAML ni Equipos/Organizaciones en la edición libre (confirmado
en el propio `cal.com/blog/cal-diy-open-source-to-closed-source`, y en
`.env.example` del repo: `ORGANIZATIONS_ENABLED` está marcado
explícitamente como "solo para entornos no-prod", no una función real
de producción en self-hosting).

## Por qué instancia compartida y no una por tenant (a diferencia de FacturaScripts)

Verificado en la documentación oficial de Docker de Cal.diy:
`NEXT_PUBLIC_WEBAPP_URL` es una variable de **compilación** de Next.js,
no de ejecución — "changing these is not required for evaluation, but
may be required for production... you must build and publish your own
image". Una imagen prehecha no puede servir URLs distintas por
contenedor, así que el patrón de FacturaScripts (un contenedor físico
por tenant) es inviable aquí sin reconstruir la imagen por tenant.

En su lugar: **una única instancia compartida** (se construye una sola
vez, apuntando al dominio público real) + **un usuario de servicio de
Cal.diy por tenant** — mismo nivel de aislamiento que ya se aceptó en
Documenso (por Equipo) o Paperless-ngx (por Grupo+usuario), aquí a nivel
de usuario individual porque es lo único disponible gratis. Cal.diy,
a diferencia de FacturaScripts, es una aplicación multiusuario por
diseño desde su núcleo (cada persona tiene sus propios tipos de evento y
reservas) — el aislamiento entre cuentas de una misma instancia es el
control de acceso básico del producto, no la función de pago "Equipos".
**Esto se verificó leyendo el código fuente real** (no solo
documentación) de `apps/web/app/api/auth/setup/route.ts` y
`apps/web/app/api/auth/signup/route.ts` +
`.../handlers/selfHostedHandler.ts` del repo `calcom/cal.diy` — pero
**no se ha podido levantar un contenedor real y probarlo de punta a
punta en este entorno** (el monorepo es demasiado grande para
compilarlo en esta máquina de desarrollo). La prueba real de aislamiento
entre dos tenants queda pendiente para cuando se despliegue de verdad
(ver HOSTING.md 8.25) — mismo criterio de honestidad que el resto de
`app/*.py`: no se afirma "verificado en vivo" si no lo está.

## Aprovisionamiento

- `POST /api/auth/setup` (app web, sin autenticar): crea el primer
  usuario ADMIN de la instancia — solo funciona si la tabla de usuarios
  está completamente vacía (verificado en el código:
  `prisma.user.count() !== 0` → 400 "No setup needed"). Se ejecuta UNA
  VEZ al desplegar (`_bootstrap_admin`), no por tenant — mismo papel que
  el superusuario inicial de Baserow.
- `POST /api/auth/signup` (app web, sin autenticar): da de alta un
  usuario normal. Al no llevar `token` de invitación de equipo, cae en
  `selfHostedSignupHandler` — pensado explícitamente para self-hosters.
  No devuelve un id numérico, solo confirma la creación (por eso
  `tenants.calcom_email` guarda el email, no un id). La verificación de
  email es un feature flag (`checkIfFeatureIsEnabledGlobally
  ("email-verification")`, desactivado por defecto) — no bloquea el
  login si no hay SMTP configurado, verificado leyendo
  `packages/features/auth/lib/verifyEmail.ts`.
- El API Key de cada usuario de servicio se genera **a mano** desde su
  propia cuenta (Configuración → Developer → API Keys) — no se ha
  encontrado (ni en el código ni en la documentación) un endpoint admin
  para crear API Keys de otro usuario en la edición self-hosted; mismo
  paso manual único por tenant que ya se acepta para
  `facturascripts_api_key`/`documenso_api_key`.

## API de negocio (API v2)

Corre en un contenedor aparte (`apps/api/v2/Dockerfile`, no viene
incluida en la imagen de la app web — confirmado en el
`docker-compose.yml` real del repo). Autenticación por cabecera
`Authorization: Bearer <api_key>`. **Cada grupo de endpoints exige su
propia cabecera `cal-api-version`** (confirmado en la documentación
oficial de la API — endpoints distintos, versiones distintas; omitirla
hace que la API sirva una versión antigua por defecto), de ahí que cada
función de este módulo lleve la suya explícita en vez de una constante
global.

Mismo criterio que el resto de `app/*.py`: solo `urllib` de la librería
estándar.
"""
import json
import os
import secrets
import string
import urllib.error
import urllib.parse
import urllib.request

CALCOM_WEB_URL = os.environ.get("CALCOM_WEB_URL", "http://127.0.0.1:8021")
CALCOM_API_URL = os.environ.get("CALCOM_API_URL", "http://127.0.0.1:8022")
CALCOM_ADMIN_EMAIL = os.environ.get("CALCOM_ADMIN_EMAIL")
CALCOM_ADMIN_PASSWORD = os.environ.get("CALCOM_ADMIN_PASSWORD")
TIMEOUT_SEGUNDOS = 20

# Confirmadas contra la documentación oficial de la API v2
# (cal.com/docs/api-reference/v2/...) — cada grupo de endpoints pin su
# propia versión, no hay una única constante global válida para toda la
# API.
_VERSION_BOOKINGS_LISTAR = "2026-05-01"
_VERSION_BOOKINGS_CREAR = "2026-02-25"
_VERSION_BOOKINGS_CANCELAR = "2026-02-25"
_VERSION_EVENT_TYPES = "2024-06-14"


class ErrorCalcom(Exception):
    """Error legible para mostrar cuando Cal.diy falla."""


def _generar_password_valida() -> str:
    """Cal.diy exige mínimo 15 caracteres, con mayúscula, minúscula y
    número (verificado en `isPasswordValid`, `packages/prisma/zod-utils.ts`)
    — se construye a mano en vez de confiar en que `secrets.token_urlsafe`
    tenga las tres clases de caracteres por azar."""
    base = secrets.token_urlsafe(18)
    completa = list(base + "aA1")
    secrets.SystemRandom().shuffle(completa)
    return "".join(completa)


def _peticion_web(endpoint: str, cuerpo: dict):
    """Llamadas a la app web (no autenticadas: /api/auth/setup y
    /api/auth/signup, ambas pensadas para usarse sin sesión)."""
    datos = json.dumps(cuerpo).encode("utf-8")
    req = urllib.request.Request(
        f"{CALCOM_WEB_URL}{endpoint}",
        data=datos,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            cuerpo_resp = resp.read().decode("utf-8")
            return resp.status, (json.loads(cuerpo_resp) if cuerpo_resp else {})
    except urllib.error.HTTPError as e:
        cuerpo_error = e.read().decode("utf-8")
        try:
            return e.code, json.loads(cuerpo_error)
        except json.JSONDecodeError:
            return e.code, {"message": cuerpo_error}
    except urllib.error.URLError as e:
        raise ErrorCalcom(
            f"No se ha podido conectar con Cal.diy ({CALCOM_WEB_URL}). "
            f"¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError:
        raise ErrorCalcom(f"Tiempo de espera agotado al contactar con Cal.diy ({CALCOM_WEB_URL}).")


def _peticion_api(endpoint: str, api_key: str, version: str, *, metodo: str = "GET", cuerpo: dict | None = None):
    """Llamadas a la API v2 (contenedor aparte, `CALCOM_API_URL`)."""
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    cabeceras = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "cal-api-version": version,
    }
    if datos is not None:
        cabeceras["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{CALCOM_API_URL}/v2{endpoint}", data=datos, headers=cabeceras, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            cuerpo_resp = resp.read().decode("utf-8")
            return resp.status, (json.loads(cuerpo_resp) if cuerpo_resp else {})
    except urllib.error.HTTPError as e:
        cuerpo_error = e.read().decode("utf-8")
        try:
            return e.code, json.loads(cuerpo_error)
        except json.JSONDecodeError:
            return e.code, {"message": cuerpo_error}
    except urllib.error.URLError as e:
        raise ErrorCalcom(
            f"No se ha podido conectar con la API de Cal.diy ({CALCOM_API_URL}). "
            f"¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError:
        raise ErrorCalcom(f"Tiempo de espera agotado al contactar con la API de Cal.diy ({CALCOM_API_URL}).")


def _slug(nombre: str) -> str:
    permitidos = string.ascii_lowercase + string.digits
    bruto = "".join(ch if ch in permitidos else "-" for ch in nombre.lower().strip())
    while "--" in bruto:
        bruto = bruto.replace("--", "-")
    return bruto.strip("-") or "tenant"


def bootstrap_admin() -> None:
    """Crea el primer usuario ADMIN de la instancia compartida. Se llama
    UNA VEZ al desplegar (paso de despliegue, ver HOSTING.md 8.25), no
    desde `aprovisionar_tenant` — mismo papel que el superusuario inicial
    de Baserow, que tampoco se crea por código. Idempotente: si la
    instancia ya tiene usuarios, `/api/auth/setup` devuelve 400
    ("No setup needed"), que aquí se trata como éxito, no como error."""
    if not CALCOM_ADMIN_EMAIL or not CALCOM_ADMIN_PASSWORD:
        raise ErrorCalcom("Definí CALCOM_ADMIN_EMAIL y CALCOM_ADMIN_PASSWORD antes de arrancar Cal.diy.")
    estado, cuerpo = _peticion_web(
        "/api/auth/setup",
        {
            "username": "admin",
            "full_name": "Guilda Work",
            "email_address": CALCOM_ADMIN_EMAIL,
            "password": CALCOM_ADMIN_PASSWORD,
        },
    )
    if estado not in (200, 400):
        mensaje = cuerpo.get("message") or cuerpo
        raise ErrorCalcom(f"No se ha podido crear el admin inicial de Cal.diy: {mensaje}")


def aprovisionar_tenant(tenant_id: int, nombre_tenant: str) -> dict:
    """Da de alta un usuario de servicio de Cal.diy para un tenant, vía
    el registro estándar (`selfHostedSignupHandler`). Devuelve
    {"email", "admin_pass"}. Idempotente: si el email ya existe (alta
    repetida tras un fallo parcial), no es un error — se devuelve el
    mismo email con una contraseña nueva (la anterior queda inservible,
    habría que regenerar el API Key a mano de nuevo, aceptable para un
    caso tan raro como reintentar un alta ya hecha)."""
    slug = _slug(nombre_tenant)
    email = f"tenant-{slug}@calcom.local"
    contrasena = _generar_password_valida()
    estado, cuerpo = _peticion_web(
        "/api/auth/signup",
        {"email": email, "username": f"tenant-{slug}", "password": contrasena},
    )
    if estado not in (200, 201) and "already" not in json.dumps(cuerpo).lower():
        mensaje = cuerpo.get("message") or cuerpo
        raise ErrorCalcom(f"No se ha podido crear el usuario de servicio de Cal.diy para '{nombre_tenant}': {mensaje}")
    return {"email": email, "admin_pass": contrasena}


# --- API de negocio (Fase MCP) — usa el API Key del propio tenant ---

def listar_tipos_evento(api_key: str) -> list[dict]:
    """[] si `api_key` está vacía (tenant sin aprovisionar todavía, o sin
    el paso manual de generar el API Key hecho)."""
    if not api_key:
        return []
    estado, cuerpo = _peticion_api("/event-types", api_key, _VERSION_EVENT_TYPES)
    if estado != 200:
        mensaje = cuerpo.get("message") or cuerpo
        raise ErrorCalcom(f"No se han podido listar los tipos de evento de Cal.diy: {mensaje}")
    return cuerpo.get("data", [])


def listar_reservas(api_key: str, desde: str | None = None, hasta: str | None = None) -> list[dict]:
    if not api_key:
        return []
    parametros = {}
    if desde:
        parametros["afterStart"] = desde
    if hasta:
        parametros["beforeEnd"] = hasta
    endpoint = f"/bookings?{urllib.parse.urlencode(parametros)}" if parametros else "/bookings"
    estado, cuerpo = _peticion_api(endpoint, api_key, _VERSION_BOOKINGS_LISTAR)
    if estado != 200:
        mensaje = cuerpo.get("message") or cuerpo
        raise ErrorCalcom(f"No se han podido listar las reservas de Cal.diy: {mensaje}")
    return cuerpo.get("data", [])


def crear_reserva(api_key: str, tipo_evento_id: int, inicio: str, nombre_asistente: str, email_asistente: str, zona_horaria: str = "Europe/Madrid") -> dict:
    if not api_key:
        raise ErrorCalcom("Este tenant no tiene Cal.diy aprovisionado todavía.")
    estado, cuerpo = _peticion_api(
        "/bookings", api_key, _VERSION_BOOKINGS_CREAR, metodo="POST",
        cuerpo={
            "start": inicio,
            "eventTypeId": tipo_evento_id,
            "attendee": {"name": nombre_asistente, "email": email_asistente, "timeZone": zona_horaria},
        },
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("message") or cuerpo
        raise ErrorCalcom(f"No se ha podido crear la reserva en Cal.diy: {mensaje}")
    return cuerpo.get("data", cuerpo)


def cancelar_reserva(api_key: str, reserva_uid: str, motivo: str = "") -> dict:
    if not api_key:
        raise ErrorCalcom("Este tenant no tiene Cal.diy aprovisionado todavía.")
    estado, cuerpo = _peticion_api(
        f"/bookings/{reserva_uid}/cancel", api_key, _VERSION_BOOKINGS_CANCELAR, metodo="POST",
        cuerpo={"cancellationReason": motivo} if motivo else {},
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("message") or cuerpo
        raise ErrorCalcom(f"No se ha podido cancelar la reserva {reserva_uid} en Cal.diy: {mensaje}")
    return cuerpo.get("data", cuerpo)
