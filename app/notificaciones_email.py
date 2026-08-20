"""Envío de correo saliente PROPIO de la app (no confundir con
app/correo.py, que es el cliente IMAP/SMTP de un empleado con sus propias
credenciales). Hoy el único uso es mandar el enlace mágico del portal de
cliente (app/rutas_portal_cliente.py) -- canal independiente con sus
propias credenciales dedicadas, mismo criterio que n8n/Outline/
OpenProject/Documenso/Baserow/Listmonk tienen cada uno las suyas contra
el mismo relay IONOS (ver docker-compose.yml).

Requiere las variables de entorno PORTAL_SMTP_HOST/PORTAL_SMTP_PUERTO/
PORTAL_SMTP_USUARIO/PORTAL_SMTP_CONTRASENA/PORTAL_SMTP_REMITENTE. Sin
ellas, configurado() devuelve False y enviar_enlace_portal() lanza
ErrorNotificacionesEmail con un mensaje legible -- el llamante debe
capturarlo (ver app/rutas_portal_cliente.py) y mostrar que el portal no
está configurado todavía, en vez de dejar pasar un 500 en crudo."""
import os
import smtplib
from email.message import EmailMessage

PORTAL_SMTP_HOST = os.environ.get("PORTAL_SMTP_HOST")
PORTAL_SMTP_PUERTO = int(os.environ.get("PORTAL_SMTP_PUERTO", "587"))
PORTAL_SMTP_USUARIO = os.environ.get("PORTAL_SMTP_USUARIO")
PORTAL_SMTP_CONTRASENA = os.environ.get("PORTAL_SMTP_CONTRASENA")
PORTAL_SMTP_REMITENTE = os.environ.get("PORTAL_SMTP_REMITENTE")
TIMEOUT_SEGUNDOS = 10


class ErrorNotificacionesEmail(Exception):
    pass


def configurado() -> bool:
    return bool(PORTAL_SMTP_HOST and PORTAL_SMTP_USUARIO and PORTAL_SMTP_CONTRASENA and PORTAL_SMTP_REMITENTE)


def _enviar(destinatario: str, asunto: str, cuerpo: str) -> None:
    if not configurado():
        raise ErrorNotificacionesEmail(
            "El portal de cliente no está configurado todavía (faltan las variables PORTAL_SMTP_*)."
        )
    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = PORTAL_SMTP_REMITENTE
    mensaje["To"] = destinatario
    mensaje.set_content(cuerpo)
    try:
        with smtplib.SMTP(PORTAL_SMTP_HOST, PORTAL_SMTP_PUERTO, timeout=TIMEOUT_SEGUNDOS) as smtp:
            smtp.starttls()
            smtp.login(PORTAL_SMTP_USUARIO, PORTAL_SMTP_CONTRASENA)
            smtp.send_message(mensaje)
    except (smtplib.SMTPException, OSError) as e:
        raise ErrorNotificacionesEmail(f"No se ha podido enviar el correo: {e}") from e


def enviar_enlace_portal(email_destino: str, url_enlace: str) -> None:
    _enviar(
        email_destino,
        "Tu enlace de acceso a Guilda Work",
        "Hola,\n\n"
        "Este es tu enlace de acceso al portal de cliente. Es de un solo uso y caduca en 15 minutos:\n\n"
        f"{url_enlace}\n\n"
        "Si no has solicitado este enlace, puedes ignorar este correo.\n",
    )


def enviar_solicitud_documento(email_destino: str, descripcion: str, url_portal: str) -> None:
    """Aviso de que el equipo pide un documento concreto para un
    vencimiento (app/rutas_fiscal.py:editar_vencimiento) -- mismo
    criterio que enviar_respuesta_portal: enlaza a /portal/entrar sin
    más, el cliente pide su propio enlace mágico igual que siempre."""
    _enviar(
        email_destino,
        "Tu gestoría te pide un documento",
        "Hola,\n\n"
        f"Tu gestoría necesita que subas el siguiente documento: \"{descripcion}\"\n\n"
        f"Entra en {url_portal} para subirlo desde el portal de cliente.\n",
    )


def enviar_enlace_pago(email_destino: str, concepto: str, url_pago: str) -> None:
    """Aviso de que hay un enlace de pago de Stripe Checkout disponible
    para un vencimiento (app/rutas_fiscal.py:cobrar_stripe_vencimiento).
    A diferencia de enviar_respuesta_portal/enviar_solicitud_documento,
    aquí SÍ se manda la URL directa (la propia página de Stripe, alojada
    por Stripe -- nunca se maneja un dato de tarjeta en Guilda Work) en
    vez de enlazar a /portal/entrar, porque el pago no requiere ninguna
    sesión del portal."""
    _enviar(
        email_destino,
        "Tienes un pago pendiente",
        "Hola,\n\n"
        f"Tu gestoría te ha generado un enlace de pago para: \"{concepto}\"\n\n"
        f"Puedes pagarlo aquí: {url_pago}\n",
    )


def enviar_respuesta_portal(email_destino: str, texto: str, url_portal: str) -> None:
    """Aviso de que el equipo ha respondido un mensaje en el portal --
    NO manda un enlace mágico directo a la conversación (evitaría
    ampliar clientes_fiscales_accesos con un destino de redirección,
    más estado que mantener) -- enlaza a /portal/entrar sin más, el
    cliente pide su propio enlace igual que siempre."""
    _enviar(
        email_destino,
        "Tienes una respuesta nueva en Guilda Work",
        "Hola,\n\n"
        "Tu gestoría te ha respondido en el portal de cliente:\n\n"
        f"\"{texto}\"\n\n"
        f"Entra en {url_portal} para ver la conversación completa.\n",
    )
