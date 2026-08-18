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


def enviar_enlace_portal(email_destino: str, url_enlace: str) -> None:
    if not configurado():
        raise ErrorNotificacionesEmail(
            "El portal de cliente no está configurado todavía (faltan las variables PORTAL_SMTP_*)."
        )
    mensaje = EmailMessage()
    mensaje["Subject"] = "Tu enlace de acceso a Guilda Work"
    mensaje["From"] = PORTAL_SMTP_REMITENTE
    mensaje["To"] = email_destino
    mensaje.set_content(
        "Hola,\n\n"
        "Este es tu enlace de acceso al portal de cliente. Es de un solo uso y caduca en 15 minutos:\n\n"
        f"{url_enlace}\n\n"
        "Si no has solicitado este enlace, puedes ignorar este correo.\n"
    )
    try:
        with smtplib.SMTP(PORTAL_SMTP_HOST, PORTAL_SMTP_PUERTO, timeout=TIMEOUT_SEGUNDOS) as smtp:
            smtp.starttls()
            smtp.login(PORTAL_SMTP_USUARIO, PORTAL_SMTP_CONTRASENA)
            smtp.send_message(mensaje)
    except (smtplib.SMTPException, OSError) as e:
        raise ErrorNotificacionesEmail(f"No se ha podido enviar el correo: {e}") from e
