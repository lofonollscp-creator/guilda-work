"""Cliente de correo IMAP/POP3 (lectura) y SMTP (envío).

Usa exclusivamente la librería estándar (`imaplib`, `poplib`, `smtplib`,
`email`) para no añadir dependencias de red. La única dependencia nueva es
`keyring`, para guardar la contraseña de cada cuenta en el almacén de
credenciales del sistema (Windows Credential Manager en este equipo) en vez
de en `registro.db` o en un archivo de texto. Se reutiliza la misma
contraseña para SMTP que para IMAP/POP3 (es lo habitual en la inmensa
mayoría de proveedores).

Los correos se muestran y se redactan en HTML enriquecido (al estilo New
Outlook): al sincronizar, las imágenes incrustadas (`cid:`) se embeben como
data URI dentro del propio HTML guardado, para que no queden rotas al
mostrarlo; al enviar, se genera un mensaje multipart/alternative (texto plano
+ HTML) a partir de lo que el usuario escribe en el editor.

Carpetas: en IMAP se descubren y sincronizan TODAS las carpetas del
servidor automáticamente (sin pantalla de selección). POP3 no tiene ningún
concepto de carpetas a nivel de protocolo — solo hay una "INBOX" implícita,
siempre, sin excepción posible.

Sin adjuntos descargables aparte de las imágenes incrustadas en el propio
cuerpo del mensaje.
"""
from __future__ import annotations

import base64
import email
import html as html_lib
import imaplib
import poplib
import re
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


def _incrustar_imagenes_inline(html: str, imagenes: dict[str, tuple[bytes, str]]) -> str:
    """Sustituye src="cid:xxx" por data URIs, para que las imágenes
    incrustadas (logos, gráficos...) no aparezcan rotas al mostrar el HTML."""
    def reemplazar(m: re.Match) -> str:
        cid = m.group(2)
        if cid in imagenes:
            contenido, tipo = imagenes[cid]
            b64 = base64.b64encode(contenido).decode("ascii")
            return f'src={m.group(1)}data:{tipo};base64,{b64}{m.group(1)}'
        return m.group(0)

    return re.sub(r'src=(["\'])cid:([^"\']+)\1', reemplazar, html, flags=re.IGNORECASE)


def _cuerpos(mensaje: email.message.Message) -> tuple[str | None, str | None]:
    """Devuelve (texto_plano, html) extraídos del mensaje. Las imágenes
    incrustadas por Content-ID se embeben en el propio HTML como data URI."""
    texto = html = None
    imagenes_inline: dict[str, tuple[bytes, str]] = {}
    if mensaje.is_multipart():
        for parte in mensaje.walk():
            tipo = parte.get_content_type()
            content_id = parte.get("Content-ID")
            if content_id and tipo.startswith("image/"):
                try:
                    contenido = parte.get_payload(decode=True)
                except Exception:
                    continue
                if contenido is not None:
                    imagenes_inline[content_id.strip("<>")] = (contenido, tipo)
                continue

            disposicion = str(parte.get("Content-Disposition") or "")
            if "attachment" in disposicion:
                continue
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

    if html and imagenes_inline:
        html = _incrustar_imagenes_inline(html, imagenes_inline)
    return texto, html


def texto_a_html(texto: str) -> str:
    """Convierte texto plano a HTML equivalente (escapado + saltos de línea
    como <br>), para citar mensajes que no tienen versión HTML."""
    return html_lib.escape(texto).replace("\n", "<br>")


def html_a_texto_plano(contenido_html: str) -> str:
    """Conversión simple de HTML a texto plano, para el fallback text/plain
    que acompaña a todo correo HTML enviado (algunos clientes lo prefieren)."""
    texto = re.sub(r"<br\s*/?>", "\n", contenido_html, flags=re.IGNORECASE)
    texto = re.sub(r"</(p|div|h[1-6])>", "\n\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"</li>", "\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"<[^>]+>", "", texto)
    texto = html_lib.unescape(texto).strip()
    return re.sub(r"\n{3,}", "\n\n", texto)


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


_PATRON_LISTA_IMAP = re.compile(r'^\(([^)]*)\)\s+("[^"]*"|NIL)\s+(".*"|\S+)$')

ETIQUETAS_CARPETA = {
    "inbox": "Bandeja de entrada",
    "sent": "Enviados", "sent items": "Enviados", "sent mail": "Enviados",
    "drafts": "Borradores",
    "trash": "Papelera", "deleted items": "Papelera", "deleted messages": "Papelera",
    "junk": "Spam", "junk e-mail": "Spam", "spam": "Spam",
    "archive": "Archivo", "all mail": "Todos",
}


def _parsear_carpetas_imap(lineas: list) -> list[str]:
    """Parsea la respuesta de `LIST` de IMAP y devuelve los nombres de
    carpeta tal cual los usa el servidor. No decodifica UTF-7 modificado
    (limitación aceptada: un nombre de carpeta no-ASCII puede mostrarse
    codificado en vez de legible)."""
    nombres = []
    for linea in lineas or []:
        if isinstance(linea, bytes):
            linea = linea.decode("utf-8", errors="replace")
        m = _PATRON_LISTA_IMAP.match(linea.strip())
        if not m:
            continue
        crudo = m.group(3)
        if crudo.startswith('"') and crudo.endswith('"'):
            crudo = crudo[1:-1]
        nombres.append(crudo)
    return nombres


def _nombre_visible_carpeta(nombre: str) -> str:
    ultimo = re.split(r"[\\/]", nombre)[-1].strip()
    return ETIQUETAS_CARPETA.get(ultimo.lower(), ultimo)


def _sincronizar_carpeta_imap(conn: imaplib.IMAP4, cuenta, carpeta: str) -> int:
    estado, _ = conn.select(f'"{carpeta}"')
    if estado != "OK":
        return 0

    estado, datos = conn.uid("search", None, "ALL")
    if estado != "OK":
        raise ErrorCorreo(f"No se han podido listar los mensajes de la carpeta «{carpeta}».")
    uids_servidor = [u.decode() for u in datos[0].split()] if datos and datos[0] else []

    ya_descargados = db.uids_existentes_correo(cuenta["id"], carpeta)
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
            cc=_decodificar(mensaje.get("Cc")) or None,
            fecha=_fecha_iso(mensaje),
            cuerpo_texto=texto,
            cuerpo_html=html,
            carpeta=carpeta,
            message_id=mensaje.get("Message-ID"),
        )
    return len(nuevos)


def _sincronizar_imap(cuenta) -> int:
    conn = _conectar_imap_cuenta(cuenta)
    try:
        estado, lineas = conn.list()
        if estado != "OK":
            raise ErrorCorreo("No se han podido listar las carpetas del servidor.")
        nombres_carpetas = _parsear_carpetas_imap(lineas) or ["INBOX"]
        db.guardar_carpetas_correo(
            cuenta["id"], [(n, _nombre_visible_carpeta(n)) for n in nombres_carpetas]
        )

        total_nuevos = 0
        for nombre in nombres_carpetas:
            total_nuevos += _sincronizar_carpeta_imap(conn, cuenta, nombre)
        return total_nuevos
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
                cc=_decodificar(mensaje.get("Cc")) or None,
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
    """Descarga los mensajes nuevos. En IMAP, de todas las carpetas del
    servidor (descubiertas automáticamente); en POP3, de la única bandeja
    posible. Devuelve {"nuevos": N}."""
    cuenta = db.obtener_cuenta_correo(cuenta_id)
    if cuenta is None:
        raise ErrorCorreo("Esa cuenta no existe.")
    if cuenta["protocolo"] == "pop3":
        nuevos = _sincronizar_pop3(cuenta)
    else:
        nuevos = _sincronizar_imap(cuenta)
    db.marcar_sincronizada_cuenta_correo(cuenta_id)
    return {"nuevos": nuevos}


CARPETA_POP3_UNICA = ("INBOX", "Bandeja de entrada")


def listar_carpetas(cuenta_id: int) -> list[dict]:
    """Carpetas de una cuenta. Las cuentas POP3 siempre devuelven una única
    carpeta sintética "Bandeja de entrada" (POP3 no tiene carpetas reales)."""
    cuenta = db.obtener_cuenta_correo(cuenta_id)
    if cuenta is not None and cuenta["protocolo"] == "pop3":
        return [{"nombre": CARPETA_POP3_UNICA[0], "nombre_visible": CARPETA_POP3_UNICA[1]}]
    carpetas = [dict(c) for c in db.listar_carpetas_correo(cuenta_id)]
    return carpetas or [{"nombre": "INBOX", "nombre_visible": "Bandeja de entrada"}]


def listar_mensajes(
    cuenta_id: int, carpeta: str = "INBOX", solo_no_leidos: bool = False,
    texto: str | None = None, limite: int = 50, incluir_pospuestos: bool = False,
):
    return db.listar_mensajes_correo(
        cuenta_id, carpeta=carpeta, solo_no_leidos=solo_no_leidos, texto=texto,
        limite=limite, incluir_pospuestos=incluir_pospuestos,
    )


def obtener_mensaje(mensaje_id: int):
    return db.obtener_mensaje_correo(mensaje_id)


def marcar_leido(mensaje_id: int, leido: bool = True) -> None:
    db.marcar_leido_mensaje_correo(mensaje_id, leido)


def eliminar_mensaje(mensaje_id: int) -> None:
    db.eliminar_mensaje_correo(mensaje_id)


def destacar_mensaje(mensaje_id: int, destacado: bool, fecha_aviso: str | None = None) -> None:
    db.destacar_mensaje_correo(mensaje_id, destacado, fecha_aviso)


def posponer_mensaje(mensaje_id: int, hasta: str | None) -> None:
    db.posponer_mensaje_correo(mensaje_id, hasta)


def _direccion_email(texto: str | None) -> str | None:
    """Extrae solo la dirección de "Nombre <correo@x.com>" (o la devuelve
    tal cual si ya es una dirección pelada), en minúsculas para comparar."""
    if not texto:
        return None
    texto = texto.strip()
    if "<" in texto and ">" in texto:
        texto = texto.split("<", 1)[1].split(">", 1)[0]
    return texto.strip().lower() or None


def destinatarios_responder_a_todos(mensaje, direccion_propia: str | None) -> str:
    """Une remitente + "Para" + "Cc" del mensaje original en una sola lista
    para "Responder a todos", sin duplicados y sin incluir la propia cuenta."""
    propia = _direccion_email(direccion_propia)
    vistas: set[str] = set()
    resultado: list[str] = []
    for campo in (mensaje["remitente"], mensaje["destinatarios"], mensaje["cc"]):
        if not campo:
            continue
        for destinatario in campo.split(","):
            destinatario = destinatario.strip()
            if not destinatario:
                continue
            clave = _direccion_email(destinatario)
            if not clave or clave == propia or clave in vistas:
                continue
            vistas.add(clave)
            resultado.append(destinatario)
    return ", ".join(resultado)


def mover_mensaje(mensaje_id: int, carpeta_destino: str) -> None:
    """Mueve un mensaje a otra carpeta — solo IMAP (POP3 no tiene carpetas).

    A diferencia de eliminar_mensaje (que es solo caché local), esto actúa
    de verdad en el servidor: copia el mensaje a la carpeta destino, marca
    el original como \\Deleted y expurga (compatible con cualquier servidor
    IMAP, sin depender de la extensión MOVE). Si solo cambiáramos la
    carpeta en nuestra caché, la próxima sincronización volvería a
    descargar el mensaje "perdido" en su carpeta original, duplicándolo —
    por eso se borra la fila local y se deja que la próxima sincronización
    la traiga de vuelta, ya con su nuevo UID, en la carpeta destino."""
    mensaje = db.obtener_mensaje_correo(mensaje_id)
    if mensaje is None:
        raise ErrorCorreo("Ese mensaje no existe.")
    cuenta = db.obtener_cuenta_correo(mensaje["cuenta_id"])
    if cuenta is None:
        raise ErrorCorreo("Esa cuenta no existe.")
    if cuenta["protocolo"] == "pop3":
        raise ErrorCorreo("Las cuentas POP3 no tienen carpetas: no se puede mover el mensaje.")

    conn = _conectar_imap_cuenta(cuenta)
    try:
        estado, _ = conn.select(f'"{mensaje["carpeta"]}"')
        if estado != "OK":
            raise ErrorCorreo(f"No se ha podido abrir la carpeta «{mensaje['carpeta']}».")
        estado, _ = conn.uid("copy", mensaje["uid"], f'"{carpeta_destino}"')
        if estado != "OK":
            raise ErrorCorreo(f"No se ha podido copiar el mensaje a «{carpeta_destino}».")
        conn.uid("store", mensaje["uid"], "+FLAGS", "(\\Deleted)")
        conn.expunge()
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    db.eliminar_mensaje_correo(mensaje_id)


# --- Categorías (propias de Guilda Work, no se sincronizan) -------------------

def crear_categoria(nombre: str, color: str) -> int:
    if not nombre.strip():
        raise ErrorCorreo("La categoría necesita un nombre.")
    return db.crear_categoria_correo(nombre, color)


def listar_categorias():
    return db.listar_categorias_correo()


def eliminar_categoria(categoria_id: int) -> None:
    db.eliminar_categoria_correo(categoria_id)


def asignar_categoria(mensaje_id: int, categoria_id: int | None) -> None:
    db.asignar_categoria_correo(mensaje_id, categoria_id)


# --- Firma ---------------------------------------------------------------------

def guardar_firma(cuenta_id: int, firma_html: str, en_nuevos: bool, en_respuestas: bool) -> None:
    db.guardar_firma_correo(cuenta_id, firma_html or None, en_nuevos, en_respuestas)


def preparar_cuerpo_inicial(cuenta_id: int, es_respuesta: bool, contenido_tras_firma: str = "") -> str:
    """Cuerpo con el que se abre el editor de redactar: un párrafo vacío
    (para que el cursor quede libre encima) seguido de la firma si
    corresponde según los interruptores de la cuenta, y después el contenido
    que ya hubiera (la cita de responder/reenviar, o nada si es nuevo)."""
    cuenta = db.obtener_cuenta_correo(cuenta_id)
    aplica_firma = False
    firma_html = None
    if cuenta is not None:
        firma_html = cuenta["firma_html"]
        aplica_firma = bool(firma_html) and bool(
            cuenta["firma_en_respuestas"] if es_respuesta else cuenta["firma_en_nuevos"]
        )
    partes = ["<p><br></p>"]
    if aplica_firma:
        partes.append(firma_html)
    if contenido_tras_firma:
        partes.append(contenido_tras_firma)
    return "".join(partes)


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


def _direcciones(cadena: str | None) -> list[str]:
    return [d.strip() for d in (cadena or "").split(",") if d.strip()]


def construir_y_enviar(
    cuenta_id: int, destinatarios: str, asunto: str, cuerpo_html: str,
    cc: str = "", bcc: str = "", en_respuesta_a: str | None = None,
) -> None:
    """Envía un correo desde `cuenta_id`. `destinatarios`/`cc`/`bcc` son
    cadenas con uno o varios correos separados por comas. `cuerpo_html` es
    el HTML escrito en el editor enriquecido — se manda como
    multipart/alternative (texto plano generado automáticamente + HTML),
    igual que hacen Outlook, Gmail, etc. `en_respuesta_a` es el Message-ID
    del mensaje original, si se trata de una respuesta (se manda en
    In-Reply-To/References para que el hilo se vea correctamente en el
    cliente de destino).

    `bcc` (Cco) NUNCA se añade como cabecera del mensaje — por definición,
    nadie salvo el remitente debe poder ver quién iba en copia oculta. Sus
    direcciones solo se añaden a la lista de destinatarios del sobre SMTP
    (`to_addrs`), construida aquí explícitamente en vez de dejar que
    `smtplib` derive los destinatarios de las cabeceras."""
    cuenta = db.obtener_cuenta_correo(cuenta_id)
    if cuenta is None:
        raise ErrorCorreo("Esa cuenta no existe.")
    if not cuenta["smtp_host"] or not cuenta["smtp_puerto"]:
        raise ErrorCorreo("Esta cuenta no tiene datos de SMTP configurados. Edítala para poder enviar correo.")
    if not destinatarios or not destinatarios.strip():
        raise ErrorCorreo("Indica al menos un destinatario.")
    if not asunto.strip():
        raise ErrorCorreo("El correo necesita un asunto.")
    if not cuerpo_html or not html_a_texto_plano(cuerpo_html).strip():
        raise ErrorCorreo("El correo no puede estar vacío.")

    mensaje = EmailMessage()
    mensaje["From"] = cuenta["usuario"]
    mensaje["To"] = destinatarios.strip()
    if cc.strip():
        mensaje["Cc"] = cc.strip()
    mensaje["Subject"] = asunto.strip()
    if en_respuesta_a:
        mensaje["In-Reply-To"] = en_respuesta_a
        mensaje["References"] = en_respuesta_a
    mensaje.set_content(html_a_texto_plano(cuerpo_html) or " ")
    mensaje.add_alternative(cuerpo_html, subtype="html")

    todos_los_destinatarios = _direcciones(destinatarios) + _direcciones(cc) + _direcciones(bcc)

    contrasena = _contrasena(cuenta_id)
    conn = _conectar_smtp(
        cuenta["smtp_host"], cuenta["smtp_puerto"], bool(cuenta["smtp_tls"]),
        cuenta["usuario"], contrasena,
    )
    try:
        conn.send_message(mensaje, to_addrs=todos_los_destinatarios)
    except smtplib.SMTPException as e:
        raise ErrorCorreo(f"No se ha podido enviar el correo: {e}") from e
    finally:
        try:
            conn.quit()
        except Exception:
            pass
