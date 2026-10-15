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
import re
import smtplib
from email.message import EmailMessage

from . import correo_diseno

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


def _marca(tenant_id: int | None) -> dict | None:
    """La marca del despacho (nombre, color y logo público) para vestir el correo con ella; None si no la ha personalizado. Nunca rompe el envío."""
    if tenant_id is None:
        return None
    try:
        from . import marca
        return marca.para_correo(tenant_id)
    except Exception:  # noqa: BLE001
        return None


def _construir(tenant_id: int | None, *args, **kwargs):
    return correo_diseno.construir(*args, marca=_marca(tenant_id), **kwargs)


def _asunto(asunto: str, tenant_id: int | None) -> str:
    """El asunto con el nombre del despacho en lugar de «Guilda Work», si tiene marca propia."""
    m = _marca(tenant_id)
    return asunto.replace("Guilda Work", m["nombre"]) if m and m.get("nombre") else asunto


def configurado() -> bool:
    return bool(PORTAL_SMTP_HOST and PORTAL_SMTP_USUARIO and PORTAL_SMTP_CONTRASENA and PORTAL_SMTP_REMITENTE)


def _enviar(destinatario: str, asunto: str, cuerpo: str, html: str | None = None) -> None:
    if not configurado():
        raise ErrorNotificacionesEmail(
            "El portal de cliente no está configurado todavía (faltan las variables PORTAL_SMTP_*)."
        )
    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = PORTAL_SMTP_REMITENTE
    mensaje["To"] = destinatario
    mensaje.set_content(cuerpo)
    if html:
        mensaje.add_alternative(html, subtype="html")      # multipart/alternative: texto plano + versión con el diseño de Guilda Work
    try:
        with smtplib.SMTP(PORTAL_SMTP_HOST, PORTAL_SMTP_PUERTO, timeout=TIMEOUT_SEGUNDOS) as smtp:
            smtp.starttls()
            smtp.login(PORTAL_SMTP_USUARIO, PORTAL_SMTP_CONTRASENA)
            smtp.send_message(mensaje)
    except (smtplib.SMTPException, OSError) as e:
        raise ErrorNotificacionesEmail(f"No se ha podido enviar el correo: {e}") from e


def enviar_enlace_portal(email_destino: str, url_enlace: str, tenant_id: int | None = None) -> None:
    plano, html = _construir(tenant_id, 
        _("Tu acceso al portal de cliente"),
        [_("Pulsa el botón para entrar a tu portal de cliente. El enlace es de un solo uso y caduca en 15 minutos.")],
        boton=(_("Entrar al portal"), url_enlace),
        aviso=_("Si no has solicitado este enlace, puedes ignorar este correo: nadie podrá entrar sin él."),
        preencabezado=_("Tu enlace de acceso (caduca en 15 minutos)"),
    )
    _enviar(email_destino, _asunto(_("Tu enlace de acceso a Guilda Work"), tenant_id), plano, html)


def enviar_solicitud_documento(email_destino: str, descripcion: str, url_portal: str, tenant_id: int | None = None) -> None:
    """Aviso de que el equipo pide un documento concreto para un
    vencimiento (app/rutas_fiscal.py:editar_vencimiento) -- mismo
    criterio que enviar_respuesta_portal: enlaza a /portal/entrar sin
    más, el cliente pide su propio enlace mágico igual que siempre."""
    plano, html = _construir(tenant_id, 
        _("Tu gestoría te pide un documento"),
        [_("Para seguir con tu expediente necesitamos que subas este documento:")],
        cita=descripcion,
        boton=(_("Subir el documento"), url_portal),
        aviso=_("Entra al portal de cliente con tu email: te mandaremos un enlace de acceso."),
        preencabezado=descripcion,
    )
    _enviar(email_destino, _asunto(_("Tu gestoría te pide un documento"), tenant_id), plano, html)


def enviar_enlace_pago(email_destino: str, concepto: str, url_pago: str, tenant_id: int | None = None) -> None:
    """Aviso de que hay un enlace de pago de Stripe Checkout disponible
    para un vencimiento (app/rutas_fiscal.py:cobrar_stripe_vencimiento).
    A diferencia de enviar_respuesta_portal/enviar_solicitud_documento,
    aquí SÍ se manda la URL directa (la propia página de Stripe, alojada
    por Stripe -- nunca se maneja un dato de tarjeta en Guilda Work) en
    vez de enlazar a /portal/entrar, porque el pago no requiere ninguna
    sesión del portal."""
    plano, html = _construir(tenant_id, 
        _("Tienes un pago pendiente"),
        [_("Tu gestoría te ha generado un enlace de pago para:")],
        cita=concepto,
        boton=(_("Pagar ahora"), url_pago),
        aviso=_("El pago se hace en la página segura de Stripe: Guilda Work nunca ve los datos de tu tarjeta."),
        preencabezado=concepto,
    )
    _enviar(email_destino, _asunto(_("Tienes un pago pendiente"), tenant_id), plano, html)


def _(mensaje: str, **valores) -> str:
    """Texto traducible; sin contexto de aplicación devuelve el español."""
    from flask_babel import gettext
    try:
        return gettext(mensaje, **valores)
    except (RuntimeError, KeyError):       # sin aplicación, o en una app sin Babel (el backoffice): el español de siempre
        return mensaje % valores if valores else mensaje


def texto_cuando(dias: int) -> str:
    """«hoy», «mañana», «dentro de 3 días», «ayer», «hace 2 días»."""
    if dias == 0:
        return _("hoy")
    if dias == 1:
        return _("mañana")
    if dias > 1:
        return _("dentro de %(n)s días", n=dias)
    if dias == -1:
        return _("ayer")
    return _("hace %(n)s días", n=-dias)


def enviar_recordatorio_vencimiento(
    email_destino: str, cliente_nombre: str, modelo: str, periodo: str, fecha_limite: str, dias: int,
    url_portal: str | None, gestoria: str, documento_solicitado: str | None = None,
    plantilla: tuple[str, str] | None = None, tenant_id: int | None = None,
) -> None:
    """`dias` > 0: faltan; 0: vence hoy; < 0: venció hace -dias. El llamante fija el idioma del cliente (ver
    app/portal_recordatorios.py). `plantilla` = (asunto, cuerpo) con el texto propio del despacho, con
    {marcas} (ver `valores_plantilla`); sin ella, el texto de siempre."""
    cuando = texto_cuando(dias)
    if plantilla:
        valores = valores_plantilla(cliente_nombre, modelo, periodo, fecha_limite, dias, cuando, url_portal, gestoria, documento_solicitado)
        asunto, cuerpo = rellenar_plantilla(plantilla[0], valores), rellenar_plantilla(plantilla[1], valores)
        # Texto propio del despacho: se respeta tal cual (párrafos separados por línea en blanco) dentro del diseño de Guilda Work
        parrafos = [p.strip() for p in re.split(r"\n\s*\n", cuerpo.strip()) if p.strip()]
        plano, html = _construir(tenant_id, asunto, parrafos, boton=(_("Abrir mi portal de cliente"), url_portal) if url_portal else None, pie=gestoria, preencabezado=asunto, plano=cuerpo)
        _enviar(email_destino, _asunto(asunto, tenant_id), plano, html)
        return
    if dias >= 0:
        linea = _(
            "Te recordamos que el modelo %(modelo)s (%(periodo)s) vence %(cuando)s, el %(fecha)s.",
            modelo=modelo, periodo=periodo, cuando=cuando, fecha=fecha_limite[:10],
        )
        asunto = _("Recordatorio: el %(modelo)s vence %(cuando)s", modelo=modelo, cuando=cuando)
    else:
        linea = _(
            "Te recordamos que el modelo %(modelo)s (%(periodo)s) venció %(cuando)s, el %(fecha)s, y seguimos pendientes de tu parte.",
            modelo=modelo, periodo=periodo, cuando=cuando, fecha=fecha_limite[:10],
        )
        asunto = _("Recordatorio: el %(modelo)s venció %(cuando)s", modelo=modelo, cuando=cuando)
    parrafos = [_("Hola, %(cliente)s:", cliente=cliente_nombre), linea]
    if documento_solicitado:
        parrafos.append(_("Para prepararlo necesitamos de tu parte: %(documento)s.", documento=documento_solicitado))
    if url_portal:
        parrafos.append(_("Puedes subir documentación y escribirnos desde tu portal de cliente."))
    parrafos.append(_("Un saludo,") + f"\n{gestoria}")
    plano, html = _construir(tenant_id, 
        asunto, parrafos, boton=(_("Abrir mi portal de cliente"), url_portal) if url_portal else None,
        aviso=_("Recibes este aviso porque tu gestoría tiene activados los recordatorios del portal. Si prefieres no recibirlos, díselo y los desactivará."),
        pie=gestoria, preencabezado=linea,
    )
    _enviar(email_destino, _asunto(asunto, tenant_id), plano, html)


MARCAS_PLANTILLA = ("cliente", "modelo", "periodo", "fecha_limite", "dias", "cuando", "documento", "enlace", "despacho")


def valores_plantilla(cliente_nombre, modelo, periodo, fecha_limite, dias, cuando, url_portal, gestoria, documento) -> dict:
    return {
        "cliente": cliente_nombre, "modelo": modelo, "periodo": periodo, "fecha_limite": (fecha_limite or "")[:10], "dias": str(abs(int(dias))),
        "cuando": cuando, "documento": documento or "", "enlace": url_portal or "", "despacho": gestoria,
    }


def rellenar_plantilla(texto: str, valores: dict) -> str:
    """Cambia cada {marca} conocida por su valor; lo demás (llaves sueltas, marcas desconocidas) se deja como está.
    Sin `str.format`, para que nadie pueda colar atributos u otras expresiones."""
    return re.sub(r"\{(\w+)\}", lambda m: str(valores[m.group(1)]) if m.group(1) in valores else m.group(0), texto or "")


def textos_aviso_certificado(cliente_nombre: str, tipo: str, caduca: str, dias: int, gestoria: str, instrucciones: str = "", *, tiene_enlace: bool = False) -> tuple[str, list[str]]:
    """(asunto, párrafos) del aviso de caducidad del certificado del cliente, en el idioma activo. `dias` > 0: faltan; 0: caduca hoy; < 0: caducó hace -dias."""
    cuando = texto_cuando(dias)
    if dias >= 0:
        asunto = _("Tu certificado digital caduca %(cuando)s", cuando=cuando)
        linea = _("Tu certificado digital (%(tipo)s) caduca %(cuando)s, el %(fecha)s.", tipo=tipo, cuando=cuando, fecha=caduca)
        consecuencia = _("Si caduca, no podremos presentar impuestos ni acceder a tus notificaciones en tu nombre hasta que lo renueves.")
    else:
        asunto = _("Tu certificado digital caducó %(cuando)s", cuando=cuando)
        linea = _("Tu certificado digital (%(tipo)s) caducó %(cuando)s, el %(fecha)s.", tipo=tipo, cuando=cuando, fecha=caduca)
        consecuencia = _("Mientras no lo renueves, no podemos presentar impuestos ni acceder a tus notificaciones en tu nombre.")
    parrafos = [_("Hola, %(cliente)s:", cliente=cliente_nombre), linea, consecuencia]
    if instrucciones:
        parrafos.append(instrucciones)
    parrafos.append(_("Si necesitas ayuda para renovarlo, respóndenos o pídela desde tu portal de cliente.") if tiene_enlace else _("Si necesitas ayuda para renovarlo, respóndenos a este correo."))
    parrafos.append(_("Un saludo,") + f"\n{gestoria}")
    return asunto, parrafos


def enviar_aviso_certificado(email_destino: str, cliente_nombre: str, tipo: str, caduca: str, dias: int, url_portal: str | None, gestoria: str, instrucciones: str = "",
                             plantilla: tuple[str, str] | None = None, tenant_id: int | None = None) -> None:
    """Aviso al cliente de que su certificado digital caduca (o caducó). Sin datos técnicos del certificado: solo el tipo y la fecha. El llamante fija el idioma del cliente.
    `plantilla` = (asunto, cuerpo) con el texto propio del despacho y {marcas} (ver `certificados.MARCAS_PLANTILLA`)."""
    cuando = texto_cuando(dias)
    if plantilla:
        valores = {"cliente": cliente_nombre, "tipo": tipo, "caduca": caduca, "dias": str(abs(int(dias))), "cuando": cuando, "despacho": gestoria, "instrucciones": instrucciones or "", "enlace": url_portal or ""}
        asunto, cuerpo = rellenar_plantilla(plantilla[0], valores), rellenar_plantilla(plantilla[1], valores)
        parrafos = [p.strip() for p in re.split(r"\n\s*\n", cuerpo.strip()) if p.strip()]
        plano, html = _construir(tenant_id, asunto, parrafos, boton=(_("Abrir mi portal de cliente"), url_portal) if url_portal else None, pie=gestoria, preencabezado=asunto, plano=cuerpo)
        _enviar(email_destino, _asunto(asunto, tenant_id), plano, html)
        return
    asunto, parrafos = textos_aviso_certificado(cliente_nombre, tipo, caduca, dias, gestoria, instrucciones, tiene_enlace=bool(url_portal))
    plano, html = _construir(tenant_id, 
        asunto, parrafos, boton=(_("Abrir mi portal de cliente"), url_portal) if url_portal else None,
        aviso=_("Recibes este aviso porque tu gestoría tiene activados los avisos de caducidad de tu certificado digital. Si prefieres no recibirlos, díselo y los desactivará."),
        pie=gestoria, preencabezado=parrafos[1])
    _enviar(email_destino, _asunto(asunto, tenant_id), plano, html)


def _enmascarar(email: str | None) -> str | None:
    """`ana@guilda.cat` -> `a**@guilda.cat`: para mostrar a quién llegan los avisos sin exponer la dirección entera."""
    if not email or "@" not in email:
        return None
    local, dominio = email.split("@", 1)
    return f"{local[:1]}{'*' * max(len(local) - 1, 1)}@{dominio}"


def estado_configuracion() -> dict:
    """Qué hay configurado para los avisos por correo (nunca contraseñas ni la dirección completa)."""
    variables = {
        "PORTAL_SMTP_HOST": PORTAL_SMTP_HOST, "PORTAL_SMTP_USUARIO": PORTAL_SMTP_USUARIO,
        "PORTAL_SMTP_CONTRASENA": PORTAL_SMTP_CONTRASENA, "PORTAL_SMTP_REMITENTE": PORTAL_SMTP_REMITENTE,
        "ALERTAS_ADMIN_EMAIL": ALERTAS_ADMIN_EMAIL,
    }
    faltan = [nombre for nombre, valor in variables.items() if not valor]
    return {
        "listo": not faltan,
        "faltan": faltan,
        "servidor": f"{PORTAL_SMTP_HOST}:{PORTAL_SMTP_PUERTO}" if PORTAL_SMTP_HOST else None,
        "destino": _enmascarar(ALERTAS_ADMIN_EMAIL),
    }


def comprobar_conexion() -> str:
    """Se conecta al servidor de correo y se autentica, SIN enviar nada. Devuelve un texto para el usuario; si falla, lanza
    ErrorNotificacionesEmail con la causa (sin credenciales)."""
    if not configurado():
        raise ErrorNotificacionesEmail("Faltan variables PORTAL_SMTP_*: no hay nada que comprobar.")
    try:
        with smtplib.SMTP(PORTAL_SMTP_HOST, PORTAL_SMTP_PUERTO, timeout=TIMEOUT_SEGUNDOS) as smtp:
            smtp.starttls()
            smtp.login(PORTAL_SMTP_USUARIO, PORTAL_SMTP_CONTRASENA)
            smtp.noop()
    except smtplib.SMTPAuthenticationError as e:
        raise ErrorNotificacionesEmail(f"El servidor rechazó el usuario o la contraseña (código {e.smtp_code}).") from e
    except (smtplib.SMTPException, OSError) as e:
        raise ErrorNotificacionesEmail(f"No se pudo conectar con {PORTAL_SMTP_HOST}:{PORTAL_SMTP_PUERTO}: {type(e).__name__}") from e
    return f"Conexión y autenticación correctas con {PORTAL_SMTP_HOST}:{PORTAL_SMTP_PUERTO} (no se ha enviado ningún correo)."


def enviar_aviso_de_prueba() -> str:
    """Manda un aviso real al destino de las alertas para comprobar que llega. Devuelve el destino enmascarado."""
    enviar_alerta_interna(
        "[Guilda Work] aviso de prueba",
        "Este es un aviso de prueba de Guilda Work.\n\nSi lo estás leyendo, las alertas (copias de seguridad, errores del servidor, "
        "salud del sistema) te llegarán a esta dirección.\n",
    )
    return _enmascarar(ALERTAS_ADMIN_EMAIL) or "el destino configurado"


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
    titulo = re.sub(r"^\[Guilda Work\]\s*", "", asunto)
    plano, html = correo_diseno.construir(titulo, preformateado=cuerpo, pie=_("Aviso interno de Guilda Work"), preencabezado=titulo, plano=cuerpo)
    _enviar(ALERTAS_ADMIN_EMAIL, asunto, plano, html)


def enviar_respuesta_portal(email_destino: str, texto: str, url_portal: str, tenant_id: int | None = None) -> None:
    """Aviso de que el equipo ha respondido un mensaje en el portal --
    NO manda un enlace mágico directo a la conversación (evitaría
    ampliar clientes_fiscales_accesos con un destino de redirección,
    más estado que mantener) -- enlaza a /portal/entrar sin más, el
    cliente pide su propio enlace igual que siempre."""
    plano, html = _construir(tenant_id, 
        _("Tienes una respuesta nueva"),
        [_("Tu gestoría te ha respondido en el portal de cliente:")],
        cita=texto,
        boton=(_("Ver la conversación"), url_portal),
        aviso=_("Entra al portal con tu email: te mandaremos un enlace de acceso."),
        preencabezado=texto[:120],
    )
    _enviar(email_destino, _asunto(_("Tienes una respuesta nueva en Guilda Work"), tenant_id), plano, html)
