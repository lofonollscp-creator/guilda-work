"""Cliente de correo IMAP/POP3 (lectura) y SMTP (envío).

Usa exclusivamente la librería estándar (`imaplib`, `poplib`, `smtplib`,
`email`) para no añadir dependencias de red. La única dependencia nueva es
`keyring`, para guardar la contraseña de cada cuenta en el almacén de
credenciales del sistema (Windows Credential Manager en este equipo) en vez
de en `registro.db` o en un archivo de texto. Se reutiliza la misma
contraseña para SMTP que para IMAP/POP3 (es lo habitual en la inmensa
mayoría de proveedores).

MVP: solo la carpeta INBOX, sin adjuntos.
"""
from __future__ import annotations

import email
import imaplib
import poplib
import smtplib
import socket
from email.header import decode_header
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

import keyring

from . import db

SERVICIO_KEYRING = "guilda-work-correo"
TIMEOUT_SEGUNDOS = 15


class ErrorCorreo(Exception):
    """Error legible para mostrar en la interfaz cuando falla la conexión de correo."""


def _clave_keyring(cuenta_id: int) -> str:
    return f"cuenta-{cuenta_id}"


def guardar_cuenta(
    nombre: str, protocolo: str, host: str, puerto: int, usuario: str, contrasena: str,
    usa_tls: bool = True, smtp_host: str | None = None,
    smtp_puerto: int | None = None, smtp_tls: bool = True,
) -> int:
    """Valida la conexión y, si funciona, crea la cuenta y guarda su
    contraseña en keyring. Devuelve el id. Lanza ErrorCorreo sin crear nada
    si la conexión falla, para no dejar cuentas "rotas" guardadas."""
    if not nombre.strip() or not host.strip() or not usuario.strip():
        raise ErrorCorreo("Faltan datos: nombre, servidor y usuario son obligatorios.")

    if protocolo == "pop3":
        conn = _conectar_pop3(host, puerto, usa_tls, usuario, contrasena)
        conn.quit()
    else:
        conn = _conectar_imap(host, puerto, usa_tls, usuario, contrasena)
        conn.logout()

    cuenta_id = db.crear_cuenta_correo(
        nombre=nombre, protocolo=protocolo, host=host, puerto=puerto, usuario=usuario,
        usa_tls=usa_tls, smtp_host=smtp_host, smtp_puerto=smtp_puerto, smtp_tls=smtp_tls,
    )
    keyring.set_password(SERVICIO_KEYRING, _clave_keyring(cuenta_id), contrasena)
    return cuenta_id


def eliminar_cuenta(cuenta_id: int) -> None:
    try:
        keyring.delete_password(SERVICIO_KEYRING, _clave_keyring(cuenta_id))
    except keyring.errors.PasswordDeleteError:
        pass  # ya no había contraseña guardada (o nunca llegó a guardarse)
    db.eliminar_cuenta_correo(cuenta_id)


def _contrasena(cuenta_id: int) -> str:
    contrasena = keyring.get_password(SERVICIO_KEYRING, _clave_keyring(cuenta_id))
    if not contrasena:
        raise ErrorCorreo(
            "No se encuentra la contraseña de esta cuenta en el almacén de "
            "credenciales del sistema. Elimina la cuenta y vuelve a añadirla."
        )
    return contrasena


def _conectar_imap(host: str, puerto: int, usa_tls: bool, usuario: str, contrasena: str) -> imaplib.IMAP4:
    try:
        if usa_tls:
            conn = imaplib.IMAP4_SSL(host, puerto, timeout=TIMEOUT_SEGUNDOS)
        else:
            conn = imaplib.IMAP4(host, puerto, timeout=TIMEOUT_SEGUNDOS)
        conn.login(usuario, contrasena)
        return conn
    except (imaplib.IMAP4.error, OSError, socket.timeout) as e:
        raise ErrorCorreo(f"No se ha podido conectar a {host}:{puerto} (IMAP): {e}") from e


def _conectar_pop3(host: str, puerto: int, usa_tls: bool, usuario: str, contrasena: str) -> poplib.POP3:
    try:
        if usa_tls:
            conn = poplib.POP3_SSL(host, puerto, timeout=TIMEOUT_SEGUNDOS)
        else:
            conn = poplib.POP3(host, puerto, timeout=TIMEOUT_SEGUNDOS)
        conn.user(usuario)
        conn.pass_(contrasena)
        return conn
    except (poplib.error_proto, OSError, socket.timeout) as e:
        raise ErrorCorreo(f"No se ha podido conectar a {host}:{puerto} (POP3): {e}") from e


def _conectar_imap_cuenta(cuenta) -> imaplib.IMAP4:
    return _conectar_imap(cuenta["host"], cuenta["puerto"], cuenta["usa_tls"], cuenta["usuario"], _contrasena(cuenta["id"]))


def _conectar_pop3_cuenta(cuenta) -> poplib.POP3:
    return _conectar_pop3(cuenta["host"], cuenta["puerto"], cuenta["usa_tls"], cuenta["usuario"], _contrasena(cuenta["id"]))


def probar_conexion(cuenta_id: int) -> None:
    """Abre y cierra la conexión de una cuenta ya guardada, para comprobar
    que sigue funcionando. Lanza ErrorCorreo con un mensaje legible si falla."""
    cuenta = db.obtener_cuenta_correo(cuenta_id)
    if cuenta is None:
        raise ErrorCorreo("Esa cuenta no existe.")
    if cuenta["protocolo"] == "pop3":
        conn = _conectar_pop3_cuenta(cuenta)
        conn.quit()
    else:
        conn = _conectar_imap_cuenta(cuenta)
        conn.logout()


def _decodificar(valor: str | None) -> str:
    if not valor:
        return ""
    partes = decode_header(valor)
    resultado = []
    for texto, codificacion in partes:
        if isinstance(texto, bytes):
            resultado.append(texto.decode(codificacion or "utf-8", errors="replace"))
        else:
            resultado.append(texto)
    return "".join(resultado)


def _cuerpos(mensaje: email.message.Message) -> tuple[str | None, str | None]:
    """Devuelve (texto_plano, html) extraídos del mensaje (ignora adjuntos)."""
    texto = html = None
    if mensaje.is_multipart():
        for parte in mensaje.walk():
            disposicion = str(parte.get("Content-Disposition") or "")
            if "attachment" in disposicion:
                continue
            tipo = parte.get_content_type()
            try:
                contenido = parte.get_payload(decode=True)
            except Exception:
                continue
            if contenido is None:
                continue
            charset = parte.get_content_charset() or "utf-8"
            texto_decodificado = contenido.decode(charset, errors="replace")
            if tipo == "text/plain" and texto is None:
                texto = texto_decodificado
            elif tipo == "text/html" and html is None:
                html = texto_decodificado
    else:
        contenido = mensaje.get_payload(decode=True)
        if contenido is not None:
            charset = mensaje.get_content_charset() or "utf-8"
            texto_decodificado = contenido.decode(charset, errors="replace")
            if mensaje.get_content_type() == "text/html":
                html = texto_decodificado
            else:
                texto = texto_decodificado
    return texto, html


def _fecha_iso(mensaje: email.message.Message) -> str | None:
    valor = mensaje.get("Date")
    if not valor:
        return None
    try:
        dt = parsedate_to_datetime(valor)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt.isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


def _sincronizar_imap(cuenta) -> int:
    conn = _conectar_imap_cuenta(cuenta)
    try:
        estado, _ = conn.select("INBOX")
        if estado != "OK":
            raise ErrorCorreo("No se ha podido abrir la bandeja de entrada (INBOX).")

        estado, datos = conn.uid("search", None, "ALL")
        if estado != "OK":
            raise ErrorCorreo("No se han podido listar los mensajes del servidor.")
        uids_servidor = [u.decode() for u in datos[0].split()] if datos and datos[0] else []

        ya_descargados = db.uids_existentes_correo(cuenta["id"], "INBOX")
        nuevos = [u for u in uids_servidor if u not in ya_descargados]

        for uid in nuevos:
            estado, datos_msg = conn.uid("fetch", uid, "(RFC822)")
            if estado != "OK" or not datos_msg or datos_msg[0] is None:
                continue
            crudo = datos_msg[0][1]
            mensaje = email.message_from_bytes(crudo)
            texto, html = _cuerpos(mensaje)
            db.guardar_mensaje_correo(
                cuenta_id=cuenta["id"],
                uid=uid,
                asunto=_decodificar(mensaje.get("Subject")),
                remitente=_decodificar(mensaje.get("From")),
                destinatarios=_decodificar(mensaje.get("To")),
                fecha=_fecha_iso(mensaje),
                cuerpo_texto=texto,
                cuerpo_html=html,
                carpeta="INBOX",
                message_id=mensaje.get("Message-ID"),
            )
        return len(nuevos)
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _sincronizar_pop3(cuenta) -> int:
    conn = _conectar_pop3_cuenta(cuenta)
    try:
        cantidad = len(conn.list()[1])
        ya_descargados = db.uids_existentes_correo(cuenta["id"], "INBOX")
        nuevos_count = 0
        for indice in range(1, cantidad + 1):
            uid = str(indice)
            if uid in ya_descargados:
                continue
            crudo = b"\n".join(conn.retr(indice)[1])
            mensaje = email.message_from_bytes(crudo)
            texto, html = _cuerpos(mensaje)
            db.guardar_mensaje_correo(
                cuenta_id=cuenta["id"],
                uid=uid,
                asunto=_decodificar(mensaje.get("Subject")),
                remitente=_decodificar(mensaje.get("From")),
                destinatarios=_decodificar(mensaje.get("To")),
                fecha=_fecha_iso(mensaje),
                cuerpo_texto=texto,
                cuerpo_html=html,
                carpeta="INBOX",
                message_id=mensaje.get("Message-ID"),
            )
            nuevos_count += 1
        return nuevos_count
    finally:
        try:
            conn.quit()
        except Exception:
            pass


def sincronizar_bandeja(cuenta_id: int) -> dict:
    """Descarga los mensajes nuevos de INBOX. Devuelve {"nuevos": N}."""
    cuenta = db.obtener_cuenta_correo(cuenta_id)
    if cuenta is None:
        raise ErrorCorreo("Esa cuenta no existe.")
    if cuenta["protocolo"] == "pop3":
        nuevos = _sincronizar_pop3(cuenta)
    else:
        nuevos = _sincronizar_imap(cuenta)
    db.marcar_sincronizada_cuenta_correo(cuenta_id)
    return {"nuevos": nuevos}


def listar_mensajes(cuenta_id: int, solo_no_leidos: bool = False, texto: str | None = None, limite: int = 50):
    return db.listar_mensajes_correo(cuenta_id, solo_no_leidos=solo_no_leidos, texto=texto, limite=limite)


def obtener_mensaje(mensaje_id: int):
    return db.obtener_mensaje_correo(mensaje_id)


def marcar_leido(mensaje_id: int, leido: bool = True) -> None:
    db.marcar_leido_mensaje_correo(mensaje_id, leido)


# --- Envío (SMTP) --------------------------------------------------------------

def _conectar_smtp(host: str, puerto: int, usa_tls: bool, usuario: str, contrasena: str) -> smtplib.SMTP:
    try:
        if puerto == 465:
            conn = smtplib.SMTP_SSL(host, puerto, timeout=TIMEOUT_SEGUNDOS)
        else:
            conn = smtplib.SMTP(host, puerto, timeout=TIMEOUT_SEGUNDOS)
            if usa_tls:
                conn.starttls()
        conn.login(usuario, contrasena)
        return conn
    except (smtplib.SMTPException, OSError, socket.timeout) as e:
        raise ErrorCorreo(f"No se ha podido conectar a {host}:{puerto} (SMTP): {e}") from e


def construir_y_enviar(
    cuenta_id: int, destinatarios: str, asunto: str, cuerpo: str,
    en_respuesta_a: str | None = None,
) -> None:
    """Envía un correo desde `cuenta_id`. `destinatarios` es una cadena con
    uno o varios correos separados por comas. `en_respuesta_a` es el
    Message-ID del mensaje original, si se trata de una respuesta (se manda
    en In-Reply-To/References para que el hilo se vea correctamente en
    Outlook/Gmail/etc.)."""
    cuenta = db.obtener_cuenta_correo(cuenta_id)
    if cuenta is None:
        raise ErrorCorreo("Esa cuenta no existe.")
    if not cuenta["smtp_host"] or not cuenta["smtp_puerto"]:
        raise ErrorCorreo("Esta cuenta no tiene datos de SMTP configurados. Edítala para poder enviar correo.")
    if not destinatarios or not destinatarios.strip():
        raise ErrorCorreo("Indica al menos un destinatario.")
    if not asunto.strip():
        raise ErrorCorreo("El correo necesita un asunto.")

    mensaje = EmailMessage()
    mensaje["From"] = cuenta["usuario"]
    mensaje["To"] = destinatarios.strip()
    mensaje["Subject"] = asunto.strip()
    if en_respuesta_a:
        mensaje["In-Reply-To"] = en_respuesta_a
        mensaje["References"] = en_respuesta_a
    mensaje.set_content(cuerpo)

    contrasena = _contrasena(cuenta_id)
    conn = _conectar_smtp(
        cuenta["smtp_host"], cuenta["smtp_puerto"], bool(cuenta["smtp_tls"]),
        cuenta["usuario"], contrasena,
    )
    try:
        conn.send_message(mensaje)
    except smtplib.SMTPException as e:
        raise ErrorCorreo(f"No se ha podido enviar el correo: {e}") from e
    finally:
        try:
            conn.quit()
        except Exception:
            pass
