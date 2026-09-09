"""Cliente de la API de Stripe -- dos usos DISTINTOS de la misma cuenta
Stripe de Guilda Work (la plataforma), cada uno con sus propias
funciones más abajo:

- **Connect** (`crear_cuenta_connect`/`crear_sesion_pago`, bloque 5):
  cada tenant conecta su propia cuenta Stripe Express -- el dinero de
  sus cobros a SUS clientes finales le llega directo a su banco, vía
  un "cargo de destino" (`transfer_data.destination`): la cuenta de
  PLATAFORMA hace el cargo, pero transfiere el importe completo a la
  cuenta Connect del tenant, sin retener nada aquí.
- **Facturación de plataforma** (`sincronizar_plan`/`crear_suscripcion`/
  etc, bloque 6): Guilda Work cobra a sus propios tenants por usar la
  app, sobre la cuenta de PLATAFORMA sin Connect -- planes/extras
  configurables desde el backoffice, no hardcoded aquí.

Nunca se maneja un dato de tarjeta dentro de Guilda Work -- todo pasa
por Stripe Checkout (página alojada por Stripe), nunca Stripe Elements
embebido a mano. Coherente con las reglas de seguridad de este
proyecto: nunca manejar credenciales de pago directamente.

Mismo criterio que el resto de `app/*.py`: solo `urllib`, sin el SDK
oficial `stripe` -- la API de Stripe usa autenticación HTTP Basic (la
clave secreta como usuario, sin contraseña) y cuerpos
`application/x-www-form-urlencoded` con notación de corchetes para
listas/objetos anidados (`line_items[0][price_data][unit_amount]`),
ambas cosas resueltas a mano aquí, sin dependencias nuevas.

**Sin cuenta Stripe real todavía** (bloqueante externo -- el usuario
tiene que crearla, ver HOSTING.md): los nombres exactos de parámetros
de abajo siguen la documentación pública de Stripe pero no se han
podido verificar contra la API real -- confirmar en cuanto haya claves
de test (`sk_test_...`), mismo criterio de honestidad que Cal.diy/
Jitsi en este proyecto.
"""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

STRIPE_API_URL = "https://api.stripe.com/v1"
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
TIMEOUT_SEGUNDOS = 20


class ErrorStripe(Exception):
    """Error legible para mostrar cuando Stripe falla."""


def configurado() -> bool:
    return bool(STRIPE_SECRET_KEY)


def _aplanar(datos, prefijo: str = "") -> list[tuple[str, object]]:
    """Aplana un dict/list anidado a pares clave-valor con la notación
    de corchetes que exige la API de Stripe -- no acepta JSON, solo
    x-www-form-urlencoded."""
    pares: list[tuple[str, object]] = []
    if isinstance(datos, dict):
        for clave, valor in datos.items():
            nueva_clave = f"{prefijo}[{clave}]" if prefijo else clave
            pares.extend(_aplanar(valor, nueva_clave))
    elif isinstance(datos, list):
        for i, valor in enumerate(datos):
            pares.extend(_aplanar(valor, f"{prefijo}[{i}]"))
    elif isinstance(datos, bool):
        pares.append((prefijo, "true" if datos else "false"))
    elif datos is not None:
        pares.append((prefijo, datos))
    return pares


def _peticion(endpoint: str, *, metodo: str = "GET", cuerpo: dict | None = None) -> dict:
    if not STRIPE_SECRET_KEY:
        raise ErrorStripe("Stripe no está configurado todavía (falta STRIPE_SECRET_KEY).")
    datos = urllib.parse.urlencode(_aplanar(cuerpo)).encode("utf-8") if cuerpo else None
    credenciales = base64.b64encode(f"{STRIPE_SECRET_KEY}:".encode("utf-8")).decode("ascii")
    cabeceras = {"Authorization": f"Basic {credenciales}"}
    if datos is not None:
        cabeceras["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(f"{STRIPE_API_URL}{endpoint}", data=datos, headers=cabeceras, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        cuerpo_error = e.read().decode("utf-8")
        try:
            mensaje = json.loads(cuerpo_error).get("error", {}).get("message", cuerpo_error)
        except json.JSONDecodeError:
            mensaje = cuerpo_error
        raise ErrorStripe(f"Stripe devolvió un error: {mensaje}") from e
    except urllib.error.URLError as e:
        raise ErrorStripe(f"No se ha podido conectar con Stripe. Detalle: {e.reason}") from e


def verificar_firma_webhook(payload: bytes, cabecera_firma: str, tolerancia_segundos: int = 300) -> dict:
    """Verifica la firma `Stripe-Signature` de un webhook (algoritmo
    documentado de Stripe: HMAC-SHA256 de "{timestamp}.{payload}" con
    el secreto de firma del endpoint) y devuelve el evento ya parseado.
    Lanza ErrorStripe si la firma no es válida o el timestamp está
    fuera de tolerancia (protección contra repetición)."""
    if not STRIPE_WEBHOOK_SECRET:
        raise ErrorStripe("Stripe no está configurado todavía (falta STRIPE_WEBHOOK_SECRET).")
    partes = dict(p.split("=", 1) for p in cabecera_firma.split(",") if "=" in p)
    timestamp = partes.get("t")
    firma_recibida = partes.get("v1")
    if not timestamp or not firma_recibida:
        raise ErrorStripe("Cabecera Stripe-Signature mal formada.")
    if abs(time.time() - int(timestamp)) > tolerancia_segundos:
        raise ErrorStripe("El webhook de Stripe ha caducado (timestamp fuera de tolerancia).")
    mensaje_firmado = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
    firma_esperada = hmac.new(STRIPE_WEBHOOK_SECRET.encode("utf-8"), mensaje_firmado, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(firma_esperada, firma_recibida):
        raise ErrorStripe("Firma de Stripe inválida.")
    return json.loads(payload)


# --- Bloque 5: Stripe Connect (cada tenant cobra a sus propios clientes) ---

def crear_cuenta_connect(email: str, nombre_tenant: str, url_retorno: str, url_refrescar: str) -> tuple[str, str]:
    """Crea una cuenta Stripe Connect Express para un tenant y genera su
    enlace de onboarding -- devuelve (stripe_account_id, url_onboarding).
    Quien llama (app/rutas_backoffice.py) es quien persiste el
    account_id en tenants.stripe_account_id."""
    cuenta = _peticion("/accounts", metodo="POST", cuerpo={
        "type": "express",
        "email": email,
        "business_profile": {"name": nombre_tenant},
        "capabilities": {"card_payments": {"requested": True}, "transfers": {"requested": True}},
    })
    enlace = _peticion("/account_links", metodo="POST", cuerpo={
        "account": cuenta["id"],
        "refresh_url": url_refrescar,
        "return_url": url_retorno,
        "type": "account_onboarding",
    })
    return cuenta["id"], enlace["url"]


def cuenta_connect_lista(stripe_account_id: str) -> bool:
    """True si la cuenta ya completó el onboarding y puede recibir
    pagos de verdad."""
    cuenta = _peticion(f"/accounts/{stripe_account_id}")
    return bool(cuenta.get("charges_enabled"))


def crear_sesion_pago(
    stripe_account_id: str, importe_centimos: int, concepto: str,
    url_exito: str, url_cancelar: str, moneda: str = "eur", metadata: dict | None = None,
) -> str:
    """Checkout Session de "cargo de destino" -- la cuenta de
    PLATAFORMA hace el cobro pero transfiere el importe completo a la
    cuenta Connect del tenant (transfer_data.destination), nunca se
    retiene nada aquí. Devuelve la URL de Checkout a la que redirigir
    al cliente final. `importe_centimos` debe leerse en caliente de
    FacturaScripts justo antes de llamar a esto -- nunca cacheado.
    `metadata` (p.ej. `{"vencimiento_id": ...}`) viaja tal cual al
    evento `checkout.session.completed` del webhook -- es lo único que
    le permite saber a qué vencimiento de Guilda Work corresponde el
    pago (ver app/rutas_stripe_webhook.py)."""
    cuerpo = {
        "mode": "payment",
        "line_items": [{
            "price_data": {
                "currency": moneda,
                "unit_amount": importe_centimos,
                "product_data": {"name": concepto},
            },
            "quantity": 1,
        }],
        "payment_intent_data": {"transfer_data": {"destination": stripe_account_id}},
        "success_url": url_exito,
        "cancel_url": url_cancelar,
    }
    if metadata:
        cuerpo["metadata"] = metadata
    sesion = _peticion("/checkout/sessions", metodo="POST", cuerpo=cuerpo)
    return sesion["url"]


# --- Bloque 6: facturación de plataforma (Guilda Work cobra a sus tenants) -

def sincronizar_plan(nombre: str, precio_centimos: int | None) -> str | None:
    """Crea el Product+Price de un plan en la cuenta de PLATAFORMA --
    devuelve el price_id de Stripe, o None si el plan todavía no tiene
    precio fijado (no tiene sentido crear un Price sin importe; el
    usuario fija el precio desde el backoffice cuando lo decida)."""
    if precio_centimos is None:
        return None
    producto = _peticion("/products", metodo="POST", cuerpo={"name": nombre})
    precio = _peticion("/prices", metodo="POST", cuerpo={
        "product": producto["id"],
        "unit_amount": precio_centimos,
        "currency": "eur",
        "recurring": {"interval": "month"},
    })
    return precio["id"]


def sincronizar_extra(nombre: str, precio_centimos: int | None) -> str | None:
    """Igual que sincronizar_plan, pero sin `recurring` -- un extra se
    factura como cargo puntual en la próxima factura, no como
    suscripción aparte."""
    if precio_centimos is None:
        return None
    producto = _peticion("/products", metodo="POST", cuerpo={"name": nombre})
    precio = _peticion("/prices", metodo="POST", cuerpo={
        "product": producto["id"], "unit_amount": precio_centimos, "currency": "eur",
    })
    return precio["id"]


def crear_cliente_plataforma(email: str, nombre_tenant: str) -> str:
    cliente = _peticion("/customers", metodo="POST", cuerpo={"email": email, "name": nombre_tenant})
    return cliente["id"]


def crear_suscripcion(stripe_customer_id: str, stripe_price_id: str) -> str:
    """Crea la Subscription DIRECTAMENTE por API -- requiere que el
    cliente ya tenga un método de pago por defecto guardado en Stripe
    (si no, Stripe rechaza la petición con "no attached payment source").
    Un tenant recién asignado nunca lo tiene todavía -- para activar una
    suscripción nueva desde cero, usar crear_sesion_suscripcion en su
    lugar (Checkout alojado por Stripe, pide la tarjeta él solo). Esta
    función queda para el caso de reactivar una suscripción de un cliente
    que YA tiene tarjeta guardada de una suscripción anterior."""
    suscripcion = _peticion("/subscriptions", metodo="POST", cuerpo={
        "customer": stripe_customer_id,
        "items": [{"price": stripe_price_id}],
    })
    return suscripcion["id"]


def crear_sesion_suscripcion(stripe_customer_id: str, stripe_price_id: str, url_exito: str, url_cancelar: str) -> str:
    """Checkout Session en modo suscripción -- a diferencia de
    crear_suscripcion, esta genera una página alojada por Stripe que pide
    la tarjeta y crea la suscripción sola, sin asumir que el cliente ya
    tiene un método de pago. El webhook (checkout.session.completed con
    mode="subscription", ver app/rutas_stripe_webhook.py) guarda el
    subscription_id resultante y marca el estado del tenant."""
    sesion = _peticion("/checkout/sessions", metodo="POST", cuerpo={
        "mode": "subscription",
        "customer": stripe_customer_id,
        "line_items": [{"price": stripe_price_id, "quantity": 1}],
        "success_url": url_exito,
        "cancel_url": url_cancelar,
    })
    return sesion["url"]


def anadir_extra_a_suscripcion(stripe_customer_id: str, stripe_subscription_id: str, stripe_price_id: str, cantidad: int = 1) -> None:
    """Añade un extra como cargo puntual a la PRÓXIMA factura de la
    suscripción -- vía /v1/invoiceitems, no /v1/subscription_items.
    Los Subscription Items de Stripe exigen un Price recurrente
    (`recurring`); `sincronizar_extra` crea a propósito un Price SIN
    `recurring` (un extra es un cargo de una vez, no una línea nueva
    permanente de la suscripción) -- intentar añadirlo como
    subscription_item lo rechazaría Stripe con un error de "price sin
    definición recurrente". Un invoiceitem con `subscription` sí
    acepta un Price no recurrente y se factura una sola vez, en el
    siguiente ciclo de esa suscripción."""
    _peticion("/invoiceitems", metodo="POST", cuerpo={
        "customer": stripe_customer_id, "subscription": stripe_subscription_id,
        "price": stripe_price_id, "quantity": cantidad,
    })


def listar_facturas_cliente(stripe_customer_id: str, limite: int = 10) -> list[dict]:
    parametros = urllib.parse.urlencode({"customer": stripe_customer_id, "limit": limite})
    resultado = _peticion(f"/invoices?{parametros}")
    return resultado.get("data", [])
