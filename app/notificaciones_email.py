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

# Destino de los avisos operativos internos (no de cara al cliente, ver
# enviar_alerta_interna) -- reusa el mismo canal PORTAL_SMTP_* dedicado,
# solo cambia el destinatario.
ALERTAS_ADMIN_EMAIL = os.environ.get("ALERTAS_ADMIN_EMAIL")


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


def _(mensaje: str, **valores) -> str:
    """Texto traducible; sin contexto de aplicación devuelve el español."""
    from flask_babel import gettext
    try:
        return gettext(mensaje, **valores)
    except RuntimeError:
        return mensaje % valores if valores else mensaje


def enviar_recordatorio_vencimiento(
    email_destino: str, cliente_nombre: str, modelo: str, periodo: str, fecha_limite: str, dias: int,
    url_portal: str | None, gestoria: str, documento_solicitado: str | None = None,
) -> None:
    """El llamante fija el idioma del cliente (ver app/portal_recordatorios.py)."""
    cuando = _("mañana") if dias == 1 else _("dentro de %(n)s días", n=dias)
    cuerpo = _("Hola, %(cliente)s:", cliente=cliente_nombre) + "\n\n" + _(
        "Te recordamos que el modelo %(modelo)s (%(periodo)s) vence %(cuando)s, el %(fecha)s.",
        modelo=modelo, periodo=periodo, cuando=cuando, fecha=fecha_limite[:10],
    ) + "\n"
    if documento_solicitado:
        cuerpo += "\n" + _("Para prepararlo necesitamos de tu parte: %(documento)s.", documento=documento_solicitado) + "\n"
    if url_portal:
        cuerpo += "\n" + _("Puedes subir documentación y escribirnos desde tu portal de cliente:") + f"\n{url_portal}\n"
    cuerpo += "\n" + _("Un saludo,") + f"\n{gestoria}\n\n" + _(
        "Recibes este aviso porque tu gestoría tiene activados los recordatorios del portal. "
        "Si prefieres no recibirlos, díselo y los desactivará."
    ) + "\n"
    _enviar(email_destino, _("Recordatorio: el %(modelo)s vence %(cuando)s", modelo=modelo, cuando=cuando), cuerpo)


def enviar_alerta_interna(asunto: str, cuerpo: str) -> None:
    """Aviso operativo interno (para el equipo de Guilda, no para un
    cliente) -- usado hoy solo por scripts/vigilar_facturascripts.py para
    avisar cuando repara (o no consigue reparar) un contenedor caído.
    Requiere ALERTAS_ADMIN_EMAIL; si no está configurada, lanza
    ErrorNotificacionesEmail igual que _enviar cuando falta PORTAL_SMTP_*
    -- el llamante decide si eso es grave (el vigilante lo trata como
    best-effort, ver ese script)."""
    if not ALERTAS_ADMIN_EMAIL:
        raise ErrorNotificacionesEmail("ALERTAS_ADMIN_EMAIL no está configurada.")
    _enviar(ALERTAS_ADMIN_EMAIL, asunto, cuerpo)


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
