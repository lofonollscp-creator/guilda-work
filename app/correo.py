"""Cliente de correo IMAP/POP3 (lectura) y SMTP (envío).

Usa exclusivamente la librería estándar (`imaplib`, `poplib`, `smtplib`,
`email`) para no añadir dependencias de red. La única dependencia nueva es
`keyring`, para guardar la contraseña de cada cuenta en un almacén de
credenciales en vez de en `registro.db` o en un archivo de texto plano. Se
reutiliza la misma contraseña para SMTP que para IMAP/POP3 (es lo habitual
en la inmensa mayoría de proveedores).

En Windows/macOS en local, `keyring` usa el backend nativo del sistema
(Credential Manager/Keychain) sin más configuración. En el VPS real
(Ubuntu headless, sin sesión de escritorio ni D-Bus Secret Service) no hay
NINGÚN backend de sistema disponible — `keyring` cae automáticamente al
backend `fail.Keyring`, que lanza `NoKeyringError` en cualquier
`get_password`/`set_password` (visto en producción: Internal Server Error
al crear una cuenta de correo en /correo/cuentas). Por eso se fuerza un
backend de archivo cifrado (`keyrings.cryptfile`, independiente del
escritorio) más abajo, con la contraseña de cifrado derivada de
`GUILDA_SECRET_KEY` — el mismo secreto que ya protege las sesiones de
Flask, para no añadir un secreto más que gestionar en
`/etc/guilda-work.env`. En local esto simplemente sustituye al backend
nativo por uno de archivo, sin cambiar el comportamiento visible.

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
import html.parser
import imaplib
import logging
import os
import poplib
import re
import smtplib
import socket
import threading
import time
from datetime import datetime, timedelta
from email.header import decode_header
from email.message import EmailMessage
from email.utils import make_msgid, getaddresses, parsedate_to_datetime

import keyring
from keyrings.cryptfile.cryptfile import CryptFileKeyring

from . import busqueda, correo_oauth, db, eventos, notificaciones
from .texto_html import html_a_texto_indexable

SERVICIO_KEYRING = "guilda-work-correo"
TIMEOUT_SEGUNDOS = 15

# Mismo logger ya configurado por app/main.py (logging.basicConfig) --
# reutilizarlo aquí basta con pedirlo por nombre, sin volver a
# configurar nada.
logger = logging.getLogger("guilda")


def _configurar_backend_keyring() -> None:
    """Ver docstring del módulo. `keyring_key` fijado a mano en vez de
    dejarlo pedir por `getpass` (su comportamiento por defecto) — no hay
    terminal interactivo en un proceso servido por systemd."""
    backend = CryptFileKeyring()
    backend.file_path = db.RAIZ_PROYECTO / "data" / "correo-keyring.cfg"
    # Mismo motivo que el fallback de app/captcha.py: solo se usa en la app
    # de escritorio local (serve.py exige GUILDA_SECRET_KEY antes de que
    # este módulo se importe en un servidor real). Tiene que ser un valor
    # ESTABLE entre reinicios -- si no, las contraseñas de correo ya
    # guardadas quedarían indescifrables en el siguiente arranque.
    backend.keyring_key = os.environ.get("GUILDA_SECRET_KEY") or "clave-de-desarrollo-no-usar-en-produccion"
    keyring.set_keyring(backend)


_configurar_backend_keyring()


class ErrorCorreo(Exception):
    """Error legible para mostrar en la interfaz cuando falla la conexión de correo."""


def _clave_keyring(cuenta_id: int) -> str:
    return f"cuenta-{cuenta_id}"


def guardar_cuenta(
    usuario_id: int,
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
        usuario_id, nombre=nombre, protocolo=protocolo, host=host, puerto=puerto, usuario=usuario,
        usa_tls=usa_tls, smtp_host=smtp_host, smtp_puerto=smtp_puerto, smtp_tls=smtp_tls,
    )
    try:
        keyring.set_password(SERVICIO_KEYRING, _clave_keyring(cuenta_id), contrasena)
    except Exception as e:
        # Bug encontrado en la auditoría de 2026-10-01: si el keyring falla
        # aquí (disco lleno, backend no disponible...), la cuenta ya creada
        # en BD quedaba "viva" pero sin contraseña recuperable -- se
        # deshace la creación en vez de dejar ese estado a medias.
        db.eliminar_cuenta_correo(usuario_id, cuenta_id)
        raise ErrorCorreo(f"No se ha podido guardar la contraseña de forma segura: {e}") from e
    return cuenta_id


def conectar_cuenta_oauth(usuario_id: int, proveedor: str, autorizacion: dict, nombre: str | None = None) -> int:
    """Crea la cuenta (IMAP + SMTP con XOAUTH2) a partir del resultado de `correo_oauth.canjear_codigo`, o,
    si ya existe una cuenta del mismo proveedor y dirección, le renueva la autorización. Comprueba antes
    que el servidor acepta el token. Devuelve el id de la cuenta."""
    ajustes = correo_oauth.PROVEEDORES[proveedor]
    host, puerto = ajustes["imap"]
    smtp_host, smtp_puerto = ajustes["smtp"]
    email = autorizacion["email"]
    conn = _conectar_imap(host, puerto, True, email, correo_oauth.TokenOAuth(autorizacion["access_token"]))
    conn.logout()
    existente = next((c for c in db.listar_cuentas_correo(usuario_id) if c["usuario"].lower() == email and c["auth_tipo"] == proveedor), None)
    if existente is not None:
        cuenta_id = existente["id"]
    else:
        cuenta_id = db.crear_cuenta_correo(
            usuario_id, nombre=(nombre or "").strip() or email, protocolo="imap", host=host, puerto=puerto, usuario=email,
            usa_tls=True, smtp_host=smtp_host, smtp_puerto=smtp_puerto, smtp_tls=True, auth_tipo=proveedor,
        )
    try:
        correo_oauth.guardar_refresh_token(cuenta_id, autorizacion["refresh_token"])
    except Exception as e:  # noqa: BLE001 -- mismo criterio que guardar_cuenta: sin secreto no se deja la cuenta a medias
        if existente is None:
            db.eliminar_cuenta_correo(usuario_id, cuenta_id)
        raise ErrorCorreo(f"No se ha podido guardar la autorización de forma segura: {e}") from e
    correo_oauth.olvidar(cuenta_id)
    return cuenta_id


def editar_cuenta(
    usuario_id: int, cuenta_id: int,
    nombre: str, protocolo: str, host: str, puerto: int, usuario: str,
    usa_tls: bool = True, smtp_host: str | None = None,
    smtp_puerto: int | None = None, smtp_tls: bool = True,
    contrasena: str | None = None,
) -> None:
    """Igual que guardar_cuenta pero para una cuenta ya existente --
    valida la conexión con los datos nuevos ANTES de guardar nada, para
    no dejar la cuenta en un estado roto. Si `contrasena` viene vacía
    (el usuario no tecleó una nueva), se reutiliza la ya guardada en
    keyring tanto para la validación como para dejarla tal cual -- así
    un error tipográfico de host/puerto se puede corregir sin tener que
    volver a escribir la contraseña cada vez (antes, la única forma de
    arreglarlo era borrar la cuenta entera y recrearla, lo que borraba
    también los mensajes en caché)."""
    if not nombre.strip() or not host.strip() or not usuario.strip():
        raise ErrorCorreo("Faltan datos: nombre, servidor y usuario son obligatorios.")
    if db.obtener_cuenta_correo(usuario_id, cuenta_id) is None:
        raise ErrorCorreo("Esa cuenta no existe.")

    cuenta_actual = db.obtener_cuenta_correo(usuario_id, cuenta_id)
    if es_oauth(cuenta_actual):
        contrasena = None          # entra con OAuth2: no hay contraseña que cambiar
        contrasena_efectiva = _credencial(cuenta_actual, "imap")
    else:
        contrasena_efectiva = contrasena if contrasena else _contrasena(cuenta_id)

    if protocolo == "pop3":
        conn = _conectar_pop3(host, puerto, usa_tls, usuario, contrasena_efectiva)
        conn.quit()
    else:
        conn = _conectar_imap(host, puerto, usa_tls, usuario, contrasena_efectiva)
        conn.logout()

    db.editar_cuenta_correo(
        usuario_id, cuenta_id, nombre=nombre, protocolo=protocolo, host=host, puerto=puerto,
        usuario=usuario, usa_tls=usa_tls, smtp_host=smtp_host, smtp_puerto=smtp_puerto, smtp_tls=smtp_tls,
    )
    if contrasena:
        keyring.set_password(SERVICIO_KEYRING, _clave_keyring(cuenta_id), contrasena)


def eliminar_cuenta(usuario_id: int, cuenta_id: int) -> None:
    correo_oauth.olvidar(cuenta_id)
    try:
        keyring.delete_password(SERVICIO_KEYRING, _clave_keyring(cuenta_id))
    except keyring.errors.PasswordDeleteError:
        pass  # ya no había contraseña guardada (o nunca llegó a guardarse)
    db.eliminar_cuenta_correo(usuario_id, cuenta_id)


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
        if isinstance(contrasena, correo_oauth.TokenOAuth):
            cadena = correo_oauth.cadena_xoauth2(usuario, contrasena).encode()
            conn.authenticate("XOAUTH2", lambda _respuesta: cadena)
        else:
            conn.login(usuario, contrasena)
        return conn
    except (imaplib.IMAP4.error, OSError, socket.timeout) as e:
        # El detalle crudo del driver (que a veces incluye texto interno
        # del propio servidor IMAP) se queda en el log del servidor, no
        # en el mensaje que ve el usuario -- ver el mismo criterio ya
        # aplicado esta sesión a los errores de Stripe en el backoffice.
        logger.warning("Fallo de conexión IMAP a %s:%s -- %s", host, puerto, e)
        raise ErrorCorreo(
            f"No se ha podido conectar con el servidor de correo ({host}:{puerto}) -- revisa el servidor, el puerto y la contraseña."
        ) from e


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


def es_oauth(cuenta) -> bool:
    try:
        return cuenta["auth_tipo"] in correo_oauth.PROVEEDORES
    except (KeyError, IndexError):
        return False


def _credencial(cuenta, recurso: str = "imap"):
    """La contraseña de la cuenta o, si entra con OAuth2, un token de acceso vigente."""
    if es_oauth(cuenta):
        try:
            return correo_oauth.token_de_acceso(cuenta["id"], cuenta["auth_tipo"], recurso)
        except correo_oauth.ErrorOAuth as e:
            raise ErrorCorreo(str(e)) from e
    return _contrasena(cuenta["id"])


def _conectar_imap_cuenta(cuenta) -> imaplib.IMAP4:
    return _conectar_imap(cuenta["host"], cuenta["puerto"], cuenta["usa_tls"], cuenta["usuario"], _credencial(cuenta, "imap"))


def _conectar_pop3_cuenta(cuenta) -> poplib.POP3:
    return _conectar_pop3(cuenta["host"], cuenta["puerto"], cuenta["usa_tls"], cuenta["usuario"], _contrasena(cuenta["id"]))


def probar_conexion(usuario_id: int, cuenta_id: int) -> None:
    """Abre y cierra la conexión de una cuenta ya guardada, para comprobar
    que sigue funcionando. Lanza ErrorCorreo con un mensaje legible si falla."""
    cuenta = db.obtener_cuenta_correo(usuario_id, cuenta_id)
    if cuenta is None:
        raise ErrorCorreo("Esa cuenta no existe.")
    if cuenta["protocolo"] == "pop3":
        conn = _conectar_pop3_cuenta(cuenta)
        conn.quit()
    else:
        conn = _conectar_imap_cuenta(cuenta)
        conn.logout()


def _decodificar_bytes(contenido: bytes, codificacion: str | None) -> str:
    """Wrapper de `bytes.decode` que nunca lanza — algunos servidores
    declaran codecs que no son un nombre Python real (visto en producción:
    "unknown-8bit", una extensión no estándar de RFC 2047 que usan algunos
    MTAs para 8 bits sin codificación declarada; `LookupError: unknown
    encoding`). latin-1 nunca lanza `UnicodeDecodeError` (mapea 1 byte = 1
    carácter), así que sirve de última red sin perder el mensaje entero."""
    try:
        return contenido.decode(codificacion or "utf-8", errors="replace")
    except LookupError:
        return contenido.decode("latin-1", errors="replace")


def _decodificar(valor: str | None) -> str:
    if not valor:
        return ""
    partes = decode_header(valor)
    resultado = []
    for texto, codificacion in partes:
        if isinstance(texto, bytes):
            resultado.append(_decodificar_bytes(texto, codificacion))
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


def _cuerpos(mensaje: email.message.Message) -> tuple[str | None, str | None, list[dict]]:
    """Devuelve (texto_plano, html, adjuntos) extraídos del mensaje. Las
    imágenes incrustadas por Content-ID se embeben en el propio HTML como
    data URI. `adjuntos` es una lista de {"nombre", "tipo", "bytes"} con los
    adjuntos reales (Content-Disposition: attachment) del mensaje."""
    texto = html = None
    imagenes_inline: dict[str, tuple[bytes, str]] = {}
    adjuntos: list[dict] = []
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
                try:
                    contenido = parte.get_payload(decode=True)
                except Exception:
                    contenido = None
                if contenido is not None:
                    adjuntos.append({
                        "nombre": _decodificar(parte.get_filename()) or "adjunto",
                        "tipo": tipo,
                        "bytes": contenido,
                    })
                continue
            try:
                contenido = parte.get_payload(decode=True)
            except Exception:
                continue
            if contenido is None:
                continue
            charset = parte.get_content_charset() or "utf-8"
            texto_decodificado = _decodificar_bytes(contenido, charset)
            if tipo == "text/plain" and texto is None:
                texto = texto_decodificado
            elif tipo == "text/html" and html is None:
                html = texto_decodificado
    else:
        contenido = mensaje.get_payload(decode=True)
        if contenido is not None:
            charset = mensaje.get_content_charset() or "utf-8"
            texto_decodificado = _decodificar_bytes(contenido, charset)
            if mensaje.get_content_type() == "text/html":
                html = texto_decodificado
            else:
                texto = texto_decodificado

    if html and imagenes_inline:
        html = _incrustar_imagenes_inline(html, imagenes_inline)
    return texto, html, adjuntos


def texto_a_html(texto: str) -> str:
    """Convierte texto plano a HTML equivalente (escapado + saltos de línea
    como <br>), para citar mensajes que no tienen versión HTML."""
    return html_lib.escape(texto).replace("\n", "<br>")


_ETIQUETAS_SANEADO_PERMITIDAS = {
    "a", "b", "strong", "i", "em", "u", "s", "p", "br", "blockquote",
    "ul", "ol", "li", "span", "div", "table", "thead", "tbody", "tr", "td", "th",
    "h1", "h2", "h3", "h4", "h5", "h6", "img", "hr", "pre", "code", "font",
}
_ETIQUETAS_SANEADO_SIN_CONTENIDO = {"script", "style", "iframe", "object", "embed", "link", "meta", "base", "form", "svg"}
_ATRIBUTOS_SANEADO_PERMITIDOS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "width", "height"},
    "font": {"color", "size", "face"},
    "table": {"border", "cellpadding", "cellspacing"},
}


class _SaneadorHTML(html_lib.parser.HTMLParser):
    """Filtra HTML de origen no confiable (correos entrantes) a un subconjunto
    seguro de etiquetas/atributos, para citar en respuestas sin ejecutar
    scripts ni gestores de eventos del remitente original."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self._profundidad_omitida = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._procesar_apertura(tag, attrs, autocierre=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._procesar_apertura(tag, attrs, autocierre=True)

    def _procesar_apertura(self, tag: str, attrs: list[tuple[str, str | None]], autocierre: bool) -> None:
        tag = tag.lower()
        if tag in _ETIQUETAS_SANEADO_SIN_CONTENIDO:
            if not autocierre:
                self._profundidad_omitida += 1
            return
        if self._profundidad_omitida:
            return
        if tag not in _ETIQUETAS_SANEADO_PERMITIDAS:
            return
        permitidos = _ATRIBUTOS_SANEADO_PERMITIDOS.get(tag, set())
        trozos = [tag]
        for nombre, valor in attrs:
            nombre = (nombre or "").lower()
            valor = valor or ""
            if nombre not in permitidos:
                continue
            if nombre in ("href", "src"):
                valor_norm = valor.strip().lower()
                permitido = valor_norm.startswith(("http://", "https://", "mailto:"))
                if nombre == "src" and tag == "img":
                    permitido = permitido or valor_norm.startswith(("cid:", "data:image/"))
                if not permitido:
                    continue
            trozos.append(f'{nombre}="{html_lib.escape(valor, quote=True)}"')
        etiqueta = "<" + " ".join(trozos) + (" />" if autocierre else ">")
        self.partes.append(etiqueta)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _ETIQUETAS_SANEADO_SIN_CONTENIDO:
            if self._profundidad_omitida:
                self._profundidad_omitida -= 1
            return
        if self._profundidad_omitida:
            return
        if tag in _ETIQUETAS_SANEADO_PERMITIDAS:
            self.partes.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._profundidad_omitida:
            self.partes.append(html_lib.escape(data))

    def resultado(self) -> str:
        return "".join(self.partes)


def sanear_html_externo(contenido_html: str) -> str:
    """Limpia HTML de un correo recibido (remitente no confiable) antes de
    incrustarlo en el editor de respuesta/reenvío, que renderiza con `|safe`
    dentro de un `contenteditable` — sin esto, un remitente podría inyectar
    `<script>`/`onerror=`/etc. y ejecutar en la sesión de quien responda."""
    saneador = _SaneadorHTML()
    try:
        saneador.feed(contenido_html or "")
        saneador.close()
    except Exception:
        return html_lib.escape(contenido_html or "")
    return saneador.resultado()


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


# --- Sincronización IMAP en ambos sentidos -----------------------------------------------
#
# Hacia aquí: mensajes nuevos (con su estado leído/destacado del servidor), cambios de
# estado hechos desde otros clientes y mensajes borrados en el servidor. Hacia allá: los
# cambios hechos en Guilda se encolan (correo_operaciones) y se aplican al servidor en
# segundo plano. Nada de esto toca los mensajes POP3 (POP3 no tiene estado en el servidor).

VENTANA_RECIENTES = 500            # mensajes más recientes cuyo estado y borrado se comprueban en cada pasada
DESCARGAS_POR_CICLO = 2000         # mensajes que se descargan como máximo por carpeta y pasada
SEGUNDOS_POR_CARPETA = 60          # y tiempo máximo: un buzón enorme se baja en varias pasadas sin bloquear la cuenta
LOTE_DESCARGA = 10                 # mensajes por orden FETCH
PASADA_COMPLETA_CADA = timedelta(minutes=60)
_omitidos: dict[tuple[int, str], set[str]] = {}   # UIDs que no se han podido descargar (no se insiste en cada pasada)

_RE_UID_FETCH = re.compile(rb"\bUID\s+(\d+)", re.IGNORECASE)
_RE_FLAGS_FETCH = re.compile(rb"\bFLAGS\s*\(([^)]*)\)", re.IGNORECASE)


def _flags_de(texto: bytes) -> set[str] | None:
    m = _RE_FLAGS_FETCH.search(texto)
    if not m:
        return None
    return {f.decode("ascii", "replace").lower() for f in m.group(1).split()}


def _parsear_fetch(datos) -> list[dict]:
    """Interpreta la respuesta de `UID FETCH` de imaplib: [{"uid", "flags", "crudo"}].
    Tolera las dos formas habituales: tuplas (cabecera, literal) seguidas de una cola
    tipo b')' o b' FLAGS (\\Seen))', y líneas sueltas b'1 (UID 5 FLAGS (\\Seen))'."""
    resultado: list[dict] = []
    actual: dict | None = None
    for item in datos or []:
        if isinstance(item, tuple):
            cabecera = item[0] if isinstance(item[0], (bytes, bytearray)) else b""
            m = _RE_UID_FETCH.search(bytes(cabecera))
            if not m:
                actual = None
                continue
            actual = {"uid": int(m.group(1)), "flags": _flags_de(bytes(cabecera)), "crudo": item[1] if len(item) > 1 else None}
            resultado.append(actual)
        elif isinstance(item, (bytes, bytearray)):
            texto = bytes(item)
            if actual is not None and not re.match(rb"\s*\d+\s+\(", texto):
                # cola tras el literal (algunos servidores ponen aquí los FLAGS)
                f = _flags_de(texto)
                if f is not None and actual["flags"] is None:
                    actual["flags"] = f
                continue
            m = _RE_UID_FETCH.search(texto)
            if m:
                actual = {"uid": int(m.group(1)), "flags": _flags_de(texto), "crudo": None}
                resultado.append(actual)
    for r in resultado:
        if r["flags"] is None:
            r["flags"] = set()
    return resultado


def _uidvalidity(conn) -> str | None:
    try:
        _, datos = conn.response("UIDVALIDITY")
        if datos and datos[0]:
            return datos[0].decode() if isinstance(datos[0], bytes) else str(datos[0])
    except Exception:  # noqa: BLE001 -- servidores/dobles sin la respuesta: se sincroniza igual
        pass
    return None


def _uids_busqueda(conn, *criterio) -> list[int]:
    estado, datos = conn.uid("search", None, *criterio)
    if estado != "OK":
        raise ErrorCorreo("El servidor de correo no ha podido listar los mensajes de la carpeta.")
    return sorted(int(u) for u in (datos[0].split() if datos and datos[0] else []))


def _pasada_completa_vencida(ultima: str | None, ahora: datetime) -> bool:
    if not ultima:
        return True
    try:
        return ahora - datetime.fromisoformat(ultima) >= PASADA_COMPLETA_CADA
    except ValueError:
        return True


_RE_MODSEQ_SELECT = re.compile(rb"HIGHESTMODSEQ\s+(\d+)", re.IGNORECASE)


def _capacidades(conn) -> set[str]:
    """Capacidades del servidor DESPUÉS de autenticarse. `imaplib` conserva las de antes del login, y muchos
    servidores (Dovecot) anuncian CONDSTORE, IDLE, etc. solo tras él, así que se vuelven a pedir."""
    try:
        estado, datos = conn.capability()
        if estado == "OK" and datos and datos[0]:
            texto = datos[0].decode("utf-8", "replace") if isinstance(datos[0], (bytes, bytearray)) else str(datos[0])
            return set(texto.upper().split())
    except Exception:  # noqa: BLE001 -- dobles o servidores raros: las que ya tenía imaplib
        pass
    return {str(c).upper() for c in getattr(conn, "capabilities", ())}


def _activar_condstore(conn) -> bool:
    """CONDSTORE (RFC 7162): el servidor numera cada cambio (MODSEQ), lo que permite preguntar solo por lo
    que ha cambiado desde la última pasada. Se activa una vez por conexión; sin soporte, False."""
    previo = getattr(conn, "_condstore_activo", None)
    if previo is not None:
        return previo
    activo = False
    try:
        capacidades = _capacidades(conn)
        if "CONDSTORE" in capacidades and "ENABLE" in capacidades:
            estado, _ = conn.enable("CONDSTORE")
            activo = estado == "OK"
    except Exception:  # noqa: BLE001 -- servidor raro: se sincroniza como siempre
        activo = False
    try:
        conn._condstore_activo = activo
    except AttributeError:
        pass
    return activo


def _highestmodseq(conn) -> int | None:
    """HIGHESTMODSEQ que el servidor dio al seleccionar la carpeta (None si no lo da: NOMODSEQ, sin soporte...)."""
    try:
        _, datos = conn.response("OK")
        for d in datos or []:
            m = _RE_MODSEQ_SELECT.search(d if isinstance(d, (bytes, bytearray)) else str(d).encode())
            if m:
                return int(m.group(1))
    except Exception:  # noqa: BLE001
        pass
    return None


def _estados_servidor(conn, rango: str, cambios_desde: int | None = None) -> dict[int, set[str]]:
    """{uid: banderas}. Con `cambios_desde` (CONDSTORE) solo los mensajes modificados después de ese MODSEQ."""
    if cambios_desde is not None:
        estado, datos = conn.uid("fetch", rango, "(FLAGS)", f"(CHANGEDSINCE {int(cambios_desde)})")
    else:
        estado, datos = conn.uid("fetch", rango, "(FLAGS)")
    if estado != "OK":
        return {}
    return {r["uid"]: r["flags"] for r in _parsear_fetch(datos)}


def _texto_para_indexar(texto: str | None, html: str | None) -> str | None:
    """Los correos solo-HTML no traen texto plano; se saca del HTML para poder buscarlos por su cuerpo."""
    if texto or not html:
        return texto
    return html_a_texto_indexable(html) or None


def _guardar_mensaje_imap(cuenta, carpeta: str, uid: str, crudo: bytes, flags: set[str]) -> tuple[int | None, bool]:
    mensaje = email.message_from_bytes(crudo)
    texto, html, adjuntos = _cuerpos(mensaje)
    texto = _texto_para_indexar(texto, html)
    leido = "\\seen" in flags
    mensaje_id = db.guardar_mensaje_correo(
        cuenta_id=cuenta["id"], uid=uid,
        asunto=_decodificar(mensaje.get("Subject")), remitente=_decodificar(mensaje.get("From")),
        destinatarios=_decodificar(mensaje.get("To")), cc=_decodificar(mensaje.get("Cc")) or None,
        fecha=_fecha_iso(mensaje), cuerpo_texto=texto, cuerpo_html=html, carpeta=carpeta,
        message_id=mensaje.get("Message-ID"), in_reply_to=_decodificar(mensaje.get("In-Reply-To")),
        referencias=_decodificar(mensaje.get("References")),
        leido=leido, destacado="\\flagged" in flags,
    )
    if adjuntos and mensaje_id is not None:
        db.guardar_adjuntos_correo(mensaje_id, adjuntos)
    if mensaje_id is not None:
        _aplicar_categoria_automatica(
            cuenta["usuario_id"], mensaje_id, _decodificar(mensaje.get("From")), _decodificar(mensaje.get("Subject")),
        )
    return mensaje_id, leido


def _sincronizar_carpeta_imap(conn: imaplib.IMAP4, cuenta, carpeta: str) -> dict:
    """Sincroniza una carpeta y devuelve {"descargados", "no_leidos", "estados", "borrados"}.

    Cada pasada mira los nuevos (UID mayor que el último visto) y, de los `VENTANA_RECIENTES`
    más recientes, su estado y si siguen existiendo. Una pasada COMPLETA (la primera, tras un
    cambio de UIDVALIDITY, mientras quede historial por bajar y cada hora) revisa toda la
    carpeta. La descarga está acotada (`DESCARGAS_POR_CICLO`, lo más reciente primero): un
    buzón de decenas de miles de correos se baja en varias pasadas sin bloquear la sincronización."""
    resumen = {"descargados": 0, "no_leidos": 0, "estados": 0, "borrados": 0}
    condstore = _activar_condstore(conn)
    estado, datos_select = conn.select(f'"{carpeta}"')
    if estado != "OK":
        return resumen
    modseq_servidor = _highestmodseq(conn) if condstore else None
    cid = cuenta["id"]
    try:
        existentes = int(datos_select[0]) if datos_select and datos_select[0] else None
    except (ValueError, TypeError):
        existentes = None
    validez = _uidvalidity(conn)
    fila = db.estado_carpeta_correo(cid, carpeta)
    if fila is not None and fila["uidvalidity"] and validez and fila["uidvalidity"] != validez:
        logger.warning("UIDVALIDITY de «%s» cambiado en la cuenta %s: se vuelve a descargar la carpeta", carpeta, cid)
        db.vaciar_carpeta_correo(cid, carpeta)
        _omitidos.pop((cid, carpeta), None)
        fila = db.estado_carpeta_correo(cid, carpeta)
    ultimo = int(fila["ultimo_uid_sincronizado"]) if fila is not None and fila["ultimo_uid_sincronizado"] else None
    ahora = datetime.now()
    completa = ultimo is None or bool(fila and fila["descarga_pendiente"]) or _pasada_completa_vencida(fila["ultima_pasada_completa"] if fila else None, ahora)

    pendientes = db.operaciones_por_mensaje_correo(cid, carpeta)
    conocidos = db.uids_existentes_correo(cid, carpeta)
    omitidos = _omitidos.setdefault((cid, carpeta), set())

    if completa:
        servidor = _uids_busqueda(conn, "ALL")
        candidatos = servidor
        borrables = sorted(int(u) for u in conocidos if int(u) not in set(servidor))
        # Salvaguarda: si la búsqueda no cuadra con lo que el servidor dice tener, no se borra nada.
        if existentes is not None and existentes != len(servidor):
            logger.warning("Carpeta «%s» (cuenta %s): SEARCH ALL devuelve %s y EXISTS %s; no se borra nada", carpeta, cid, len(servidor), existentes)
            borrables = []
        minimo_estado = None
        vistos_servidor = servidor
    else:
        recientes = sorted((int(u) for u in conocidos), reverse=True)[:VENTANA_RECIENTES]
        minimo_estado = recientes[-1] if recientes else None
        en_ventana = _uids_busqueda(conn, "UID", f"{minimo_estado}:*") if minimo_estado is not None else []
        presentes = set(en_ventana)
        borrables = [u for u in sorted(recientes) if u not in presentes]
        candidatos = [u for u in _uids_busqueda(conn, "UID", f"{ultimo + 1}:*") if u > ultimo]
        vistos_servidor = sorted(presentes | set(candidatos))

    if borrables:
        resumen["borrados"] = db.eliminar_mensajes_correo_por_uid(cid, carpeta, [str(u) for u in borrables])
        conocidos -= {str(u) for u in borrables}

    faltan = sorted(
        (u for u in candidatos if str(u) not in conocidos and str(u) not in omitidos and "eliminar" not in pendientes.get(str(u), ())),
        reverse=True,
    )
    a_descargar = faltan[:DESCARGAS_POR_CICLO]
    limite_tiempo = time.monotonic() + SEGUNDOS_POR_CARPETA
    intentados = 0
    for inicio in range(0, len(a_descargar), LOTE_DESCARGA):
        if time.monotonic() > limite_tiempo:
            break
        lote = a_descargar[inicio:inicio + LOTE_DESCARGA]
        intentados += len(lote)
        estado, datos = conn.uid("fetch", ",".join(str(u) for u in lote), "(BODY.PEEK[] FLAGS)")
        recibidos = {r["uid"]: r for r in _parsear_fetch(datos)} if estado == "OK" else {}
        for uid in lote:
            r = recibidos.get(uid)
            if r is None or not r["crudo"]:
                omitidos.add(str(uid))
                continue
            _, leido = _guardar_mensaje_imap(cuenta, carpeta, str(uid), r["crudo"], r["flags"])
            resumen["descargados"] += 1
            if not leido:
                resumen["no_leidos"] += 1

    # Estado (leído/destacado) tal como está en el servidor, salvo lo que aquí está pendiente de enviar.
    # Con CONDSTORE y un MODSEQ guardado de la pasada anterior no hace falta releer las banderas de la
    # ventana: si no ha cambiado nada se omite, y si ha cambiado se piden solo los mensajes modificados
    # (también los antiguos, que antes solo se veían en la pasada completa de cada hora).
    modseq_guardado = int(fila["modseq"]) if fila is not None and fila["modseq"] else None
    cambios_desde = None
    if modseq_servidor is not None and modseq_guardado is not None and not completa and modseq_servidor >= modseq_guardado:
        if modseq_servidor == modseq_guardado:
            rango = None
        else:
            rango, cambios_desde = "1:*", modseq_guardado
    else:
        rango = "1:*" if completa else (f"{minimo_estado}:*" if minimo_estado is not None else None)
    if rango:
        pendientes = db.operaciones_por_mensaje_correo(cid, carpeta)   # incluye lo que acaban de encolar las reglas al descargar
        servidor_flags = _estados_servidor(conn, rango, cambios_desde)
        locales = db.estados_mensajes_correo(cid, carpeta, None if (completa or cambios_desde is not None) else minimo_estado)
        cambios = []
        for uid, (leido, destacado) in locales.items():
            flags = servidor_flags.get(int(uid))
            if flags is None:
                continue
            pend = pendientes.get(uid, set())
            nuevo_leido = leido if pend & {"leido", "no_leido"} else int("\\seen" in flags)
            nuevo_destacado = destacado if pend & {"destacar", "quitar_destacar"} else int("\\flagged" in flags)
            if (nuevo_leido, nuevo_destacado) != (leido, destacado):
                cambios.append((uid, nuevo_leido, nuevo_destacado))
        db.aplicar_estados_servidor_correo(cid, carpeta, cambios)
        resumen["estados"] = len(cambios)

    actualizar = {"uidvalidity": validez, "modseq": str(modseq_servidor) if modseq_servidor is not None else None}
    maximo = max([*vistos_servidor, ultimo or 0], default=0)
    if maximo:
        actualizar["ultimo_uid_sincronizado"] = str(maximo)
    if completa:
        actualizar["ultima_pasada_completa"] = ahora.isoformat(timespec="seconds")
    actualizar["descarga_pendiente"] = int(len(faltan) > intentados)
    db.guardar_estado_carpeta_correo(cid, carpeta, **actualizar)
    return resumen


def _sincronizar_imap(cuenta) -> dict:
    conn = _conectar_imap_cuenta(cuenta)
    try:
        # Primero lo que se hizo aquí (leído, borrado…) y después lo que ha cambiado allí: así un
        # cambio local reciente nunca lo pisa el estado antiguo del servidor.
        _aplicar_operaciones(conn, cuenta)
        estado, lineas = conn.list()
        if estado != "OK":
            raise ErrorCorreo("No se han podido listar las carpetas del servidor.")
        nombres_carpetas = _parsear_carpetas_imap(lineas) or ["INBOX"]
        db.guardar_carpetas_correo(
            cuenta["id"], [(n, _nombre_visible_carpeta(n)) for n in nombres_carpetas]
        )
        total = {"descargados": 0, "no_leidos": 0, "estados": 0, "borrados": 0}
        for nombre in nombres_carpetas:
            for clave, valor in _sincronizar_carpeta_imap(conn, cuenta, nombre).items():
                total[clave] += valor
        return total
    finally:
        try:
            conn.logout()
        except Exception:
            pass


# --- Cola de cambios hacia el servidor --------------------------------------------------

_locks_operaciones: dict[int, threading.Lock] = {}


def _carpeta_papelera(conn) -> str | None:
    """Carpeta de eliminados del servidor: la marcada \\Trash (RFC 6154) o, si no, por nombre habitual."""
    try:
        estado, lineas = conn.list()
    except Exception:  # noqa: BLE001
        return None
    if estado != "OK":
        return None
    candidata = None
    for linea in lineas or []:
        texto = linea.decode("utf-8", "replace") if isinstance(linea, bytes) else str(linea)
        m = _PATRON_LISTA_IMAP.match(texto.strip())
        if not m:
            continue
        nombre = m.group(3)
        if nombre.startswith('"') and nombre.endswith('"'):
            nombre = nombre[1:-1]
        if "\\trash" in texto.lower():
            return nombre
        if nombre.rsplit("/", 1)[-1].rsplit(".", 1)[-1].lower() in ("trash", "papelera", "deleted items", "deleted messages", "elementos eliminados", "bin"):
            candidata = candidata or nombre
    return candidata


def _aplicar_operaciones(conn, cuenta) -> dict:
    """Aplica en el servidor los cambios pendientes de la cuenta, agrupando por carpeta. Una
    operación que falla se reintenta en la siguiente pasada (y a las 5 se da por perdida)."""
    hechas = fallidas = 0
    pendientes = db.operaciones_pendientes_correo(cuenta["id"])
    if not pendientes:
        return {"hechas": 0, "fallidas": 0}
    papelera = None
    papelera_buscada = False
    por_carpeta: dict[str, list] = {}
    for op in pendientes:
        por_carpeta.setdefault(op["carpeta"], []).append(op)
    for carpeta, ops in por_carpeta.items():
        estado, _ = conn.select(f'"{carpeta}"')
        if estado != "OK":
            for op in ops:
                db.fallar_operacion_correo(op["id"], f"No se pudo abrir la carpeta «{carpeta}».")
                fallidas += 1
            continue
        validez = _uidvalidity(conn)
        # Última orden de estado por mensaje: marcar y desmarcar seguidos se reducen a la final.
        ultima_de_estado: dict[tuple[str, str], int] = {}
        for op in ops:
            grupo = "leido" if op["operacion"] in ("leido", "no_leido") else ("destacado" if op["operacion"] in ("destacar", "quitar_destacar") else None)
            if grupo:
                ultima_de_estado[(op["uid"], grupo)] = op["id"]
        for op in ops:
            try:
                if op["uidvalidity"] and validez and op["uidvalidity"] != validez:
                    db.cerrar_operacion_correo(op["id"])  # los UID de esa carpeta ya no son los mismos: no se puede aplicar
                    continue
                accion = op["operacion"]
                grupo = "leido" if accion in ("leido", "no_leido") else ("destacado" if accion in ("destacar", "quitar_destacar") else None)
                if grupo and ultima_de_estado.get((op["uid"], grupo)) != op["id"]:
                    db.cerrar_operacion_correo(op["id"])  # superada por otra posterior
                    continue
                if accion in ("leido", "no_leido", "destacar", "quitar_destacar"):
                    signo = "+" if accion in ("leido", "destacar") else "-"
                    bandera = "\\Seen" if accion in ("leido", "no_leido") else "\\Flagged"
                    estado, _ = conn.uid("store", op["uid"], f"{signo}FLAGS.SILENT", f"({bandera})")
                    if estado != "OK":
                        raise ErrorCorreo("El servidor no ha aceptado el cambio de estado.")
                elif accion == "eliminar":
                    if not papelera_buscada:
                        papelera, papelera_buscada = _carpeta_papelera(conn), True
                        conn.select(f'"{carpeta}"')  # LIST no cambia la carpeta, pero así se garantiza
                    if papelera and papelera != carpeta:
                        estado, _ = conn.uid("copy", op["uid"], f'"{papelera}"')
                        if estado != "OK":
                            raise ErrorCorreo("No se ha podido mover el mensaje a la papelera.")
                    estado, _ = conn.uid("store", op["uid"], "+FLAGS.SILENT", "(\\Deleted)")
                    if estado != "OK":
                        raise ErrorCorreo("El servidor no ha aceptado el borrado.")
                    if "UIDPLUS" in tuple(getattr(conn, "capabilities", ()) or ()):
                        conn.uid("expunge", op["uid"])  # solo ESTE mensaje (EXPUNGE a secas barre todos los marcados)
                    else:
                        conn.expunge()
                db.cerrar_operacion_correo(op["id"])
                hechas += 1
            except (ErrorCorreo, imaplib.IMAP4.error, OSError) as e:
                db.fallar_operacion_correo(op["id"], str(e))
                fallidas += 1
                if isinstance(e, (imaplib.IMAP4.abort, OSError)):
                    return {"hechas": hechas, "fallidas": fallidas + 1}  # la conexión ya no vale; se sigue en la próxima pasada
    return {"hechas": hechas, "fallidas": fallidas}


def procesar_operaciones_cuenta(cuenta_id: int, espera: float = 0.0) -> dict:
    """Aplica las operaciones pendientes de una cuenta con su propia conexión (sin esperar a la
    siguiente sincronización). `espera`: segundos antes de empezar, para agrupar una ráfaga de
    cambios (p. ej. marcar 20 mensajes como leídos) en una sola conexión. Nunca lanza: lo que
    falle se reintenta."""
    if espera:
        time.sleep(espera)
    lock = _locks_operaciones.setdefault(cuenta_id, threading.Lock())
    if not lock.acquire(blocking=False):
        return {"hechas": 0, "fallidas": 0}
    total = {"hechas": 0, "fallidas": 0}
    try:
        cuenta = db.obtener_cuenta_correo_por_id(cuenta_id)
        if cuenta is None or cuenta["protocolo"] == "pop3" or not db.operaciones_pendientes_correo(cuenta_id):
            return total
        try:
            conn = _conectar_imap_cuenta(cuenta)
        except ErrorCorreo:
            return total
        try:
            for _ in range(3):  # lo que se encole mientras tanto se recoge en la misma conexión
                r = _aplicar_operaciones(conn, cuenta)
                total["hechas"] += r["hechas"]
                total["fallidas"] += r["fallidas"]
                if r["fallidas"] or not db.operaciones_pendientes_correo(cuenta_id):
                    break
            return total
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        logger.exception("No se pudieron aplicar las operaciones pendientes de la cuenta %s", cuenta_id)
        return {"hechas": 0, "fallidas": 0}
    finally:
        lock.release()


def _encolar_y_lanzar(mensaje, operacion: str) -> None:
    """Encola un cambio sobre un mensaje IMAP y lo aplica en segundo plano (si no, la próxima
    sincronización lo hará). Las cuentas POP3 no tienen estado en el servidor."""
    cuenta = db.obtener_cuenta_correo_por_id(mensaje["cuenta_id"])
    if cuenta is None or cuenta["protocolo"] == "pop3":
        return
    db.encolar_operacion_correo(mensaje["cuenta_id"], mensaje["carpeta"], mensaje["uid"], operacion)
    if not _SIN_SEGUNDO_PLANO:
        threading.Thread(target=procesar_operaciones_cuenta, args=(mensaje["cuenta_id"], 1.5), daemon=True).start()


_SIN_SEGUNDO_PLANO = False   # los tests lo activan para aplicar las operaciones de forma determinista


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
            texto, html, adjuntos = _cuerpos(mensaje)
            texto = _texto_para_indexar(texto, html)
            mensaje_id = db.guardar_mensaje_correo(
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
                in_reply_to=_decodificar(mensaje.get("In-Reply-To")),
                referencias=_decodificar(mensaje.get("References")),
            )
            if adjuntos and mensaje_id is not None:
                db.guardar_adjuntos_correo(mensaje_id, adjuntos)
            if mensaje_id is not None:
                _aplicar_categoria_automatica(
                cuenta["usuario_id"], mensaje_id, _decodificar(mensaje.get("From")), _decodificar(mensaje.get("Subject")),
            )
            nuevos_count += 1
        return nuevos_count
    finally:
        try:
            conn.quit()
        except Exception:
            pass


_locks_sincronizacion: dict[int, threading.Lock] = {}
_locks_sincronizacion_guard = threading.Lock()


def _lock_de_cuenta(cuenta_id: int) -> threading.Lock:
    with _locks_sincronizacion_guard:
        return _locks_sincronizacion.setdefault(cuenta_id, threading.Lock())


def sincronizar_bandeja(usuario_id: int, cuenta_id: int) -> dict:
    """Descarga los mensajes nuevos. En IMAP, de todas las carpetas del
    servidor (descubiertas automáticamente); en POP3, de la única bandeja
    posible. Devuelve {"nuevos": N}.

    `correo_mensajes` ya tiene `UNIQUE(cuenta_id, carpeta, uid)` con
    `INSERT OR IGNORE` (ver db.guardar_mensaje_correo), así que dos
    sincronizaciones simultáneas de la misma cuenta NUNCA duplican un
    mensaje en BD -- pero sí pueden contar el mismo mensaje nuevo dos
    veces cada una por su cuenta y disparar dos notificaciones push
    duplicadas (doble clic en "Sincronizar", o el botón + el auto-sync
    casi a la vez). El lock evita eso sin bloquear la petición: si ya
    hay una sincronización de esta cuenta en curso, se devuelve
    "nada nuevo" en vez de esperar -- la que ya está en marcha cubre el
    mismo rango de todas formas."""
    cuenta = db.obtener_cuenta_correo(usuario_id, cuenta_id)
    if cuenta is None:
        raise ErrorCorreo("Esa cuenta no existe.")
    lock = _lock_de_cuenta(cuenta_id)
    if not lock.acquire(blocking=False):
        return {"nuevos": 0}
    try:
        if cuenta["protocolo"] == "pop3":
            nuevos = sin_leer = _sincronizar_pop3(cuenta)
            detalle = {}
        else:
            detalle = _sincronizar_imap(cuenta)
            nuevos, sin_leer = detalle["descargados"], detalle["no_leidos"]
        db.marcar_sincronizada_cuenta_correo(cuenta_id)
        _fallos_consecutivos.pop(cuenta_id, None)
        _ciclos_omitidos.pop(cuenta_id, None)
        if nuevos:
            _reindexar_mensajes_recientes(usuario_id, cuenta_id)
        if sin_leer:
            # Solo avisa de lo que de verdad es nuevo para el usuario: el historial que ya
            # estaba leído en el servidor (primera sincronización) no genera notificaciones.
            _emitir_evento_correo_nuevo(usuario_id, cuenta_id, sin_leer)
        return {"nuevos": nuevos}
    finally:
        lock.release()


# --- Sincronización automática de todas las cuentas (servidor) ---------------

FALLOS_PARA_FRENAR = 3
CICLOS_ENTRE_REINTENTOS_TRAS_FRENO = 6
_fallos_consecutivos: dict[int, int] = {}
_ciclos_omitidos: dict[int, int] = {}


def sincronizar_todas_las_cuentas() -> dict:
    """Sincroniza las cuentas de correo de TODOS los usuarios, una a una.

    La llama el hilo periódico del servidor (app/main.py). Cada cuenta va en
    su propio try/except: un fallo (contraseña caducada, servidor caído) se
    guarda como error de esa cuenta -- se ve en Cuentas y en la bandeja -- y
    no impide sincronizar las demás.

    Tras FALLOS_PARA_FRENAR errores seguidos, una cuenta solo se reintenta
    cada CICLOS_ENTRE_REINTENTOS_TRAS_FRENO pasadas: no tiene sentido
    insistir cada pocos minutos con una contraseña que ya sabemos mala (y
    algunos proveedores bloquean la cuenta por intentos repetidos).
    Devuelve un resumen {"cuentas", "nuevos", "errores", "omitidas"}."""
    resumen = {"cuentas": 0, "nuevos": 0, "errores": 0, "omitidas": 0}
    for fila in db.listar_todas_las_cuentas_correo():
        cuenta_id, usuario_id = fila["id"], fila["usuario_id"]
        resumen["cuentas"] += 1
        if _fallos_consecutivos.get(cuenta_id, 0) >= FALLOS_PARA_FRENAR:
            omitidos = _ciclos_omitidos.get(cuenta_id, 0) + 1
            if omitidos < CICLOS_ENTRE_REINTENTOS_TRAS_FRENO:
                _ciclos_omitidos[cuenta_id] = omitidos
                resumen["omitidas"] += 1
                continue
            _ciclos_omitidos[cuenta_id] = 0
        try:
            resultado = sincronizar_bandeja(usuario_id, cuenta_id)
            resumen["nuevos"] += resultado.get("nuevos", 0)
        except ErrorCorreo as e:
            _registrar_fallo_sincronizacion(cuenta_id, str(e))
            resumen["errores"] += 1
        except Exception as e:  # noqa: BLE001 -- nada debe tumbar el hilo ni las demás cuentas
            logger.exception("Error inesperado sincronizando la cuenta de correo %s", cuenta_id)
            _registrar_fallo_sincronizacion(cuenta_id, f"Error inesperado ({type(e).__name__}).")
            resumen["errores"] += 1
    return resumen


def _registrar_fallo_sincronizacion(cuenta_id: int, mensaje: str) -> None:
    _fallos_consecutivos[cuenta_id] = _fallos_consecutivos.get(cuenta_id, 0) + 1
    try:
        db.marcar_error_sincronizacion_cuenta_correo(cuenta_id, mensaje)
    except Exception:  # noqa: BLE001
        logger.exception("No se ha podido guardar el error de sincronización de la cuenta %s", cuenta_id)


def _emitir_evento_correo_nuevo(usuario_id: int, cuenta_id: int, nuevos: int) -> None:
    """Un evento por SINCRONIZACIÓN con novedades (no uno por mensaje) —
    _reindexar_mensajes_recientes reindexa un lote de recientes, no solo
    los nuevos de esta pasada, así que la señal de negocio real aquí es
    "esta cuenta tiene correo nuevo", no un evento por cada mensaje del
    lote de reindexado."""
    try:
        tenant = db.tenant_de_usuario(usuario_id)
        eventos.emitir("correo.mensaje_nuevo", tenant["id"] if tenant else None, {"cuenta_id": cuenta_id, "nuevos": nuevos})
    except Exception:
        pass
    if db.notificacion_tipo_activa(usuario_id, "correo_nuevo"):
        cuerpo = "Tienes 1 mensaje nuevo." if nuevos == 1 else f"Tienes {nuevos} mensajes nuevos."
        notificaciones.crear_y_enviar(
            usuario_id, "correo_nuevo", "Correo nuevo", cuerpo, url=f"/correo/?cuenta_id={cuenta_id}",
            datos={"tipo": "correo_nuevo", "cuenta_id": cuenta_id},
        )


def _reindexar_mensajes_recientes(usuario_id: int, cuenta_id: int, limite: int = 200) -> None:
    """Indexa (o reindexa, es un upsert) los mensajes más recientes de
    esta cuenta en el buscador unificado (ver app/busqueda.py) — solo
    tras una sincronización con mensajes nuevos, no en cada sincronización
    vacía. Falla en silencio si el buscador no está configurado/caído:
    es una mejora de UX, no debe romper la sincronización de correo en sí."""
    try:
        for mensaje in db.listar_mensajes_correo(cuenta_id, limite=limite):
            busqueda.indexar_mensaje(dict(mensaje), usuario_id=usuario_id)
    except busqueda.ErrorBusqueda:
        pass


CARPETA_POP3_UNICA = ("INBOX", "Bandeja de entrada")


def listar_carpetas(usuario_id: int, cuenta_id: int) -> list[dict]:
    """Carpetas de una cuenta. Las cuentas POP3 siempre devuelven una única
    carpeta sintética "Bandeja de entrada" (POP3 no tiene carpetas reales)."""
    cuenta = db.obtener_cuenta_correo(usuario_id, cuenta_id)
    if cuenta is not None and cuenta["protocolo"] == "pop3":
        return [{"nombre": CARPETA_POP3_UNICA[0], "nombre_visible": CARPETA_POP3_UNICA[1]}]
    carpetas = [dict(c) for c in db.listar_carpetas_correo(cuenta_id)]
    return carpetas or [{"nombre": "INBOX", "nombre_visible": "Bandeja de entrada"}]


def listar_mensajes(
    cuenta_id: int, carpeta: str = "INBOX", solo_no_leidos: bool = False,
    texto: str | None = None, limite: int = 50, incluir_pospuestos: bool = False,
    **filtros,
):
    """`filtros`: con_adjuntos, categoria_id, desde, hasta, solo_destacados, cliente_fiscal_id."""
    return db.listar_mensajes_correo(
        cuenta_id, carpeta=carpeta, solo_no_leidos=solo_no_leidos, texto=texto,
        limite=limite, incluir_pospuestos=incluir_pospuestos, **filtros,
    )


def consulta_de_busqueda(usuario_id: int, tenant_id: int | None, q: str | None):
    """Texto de la caja de búsqueda -> `busqueda_correo.Consulta` (operadores resueltos con las categorías
    del usuario y los clientes de su despacho)."""
    from . import busqueda_correo
    if not q or ":" not in q:
        return busqueda_correo.Consulta(texto=(q or "").strip())
    categorias = [(c["id"], c["nombre"]) for c in db.listar_categorias_correo(usuario_id)]
    clientes = [(c["id"], c["nombre"]) for c in db.listar_clientes_fiscales(tenant_id)] if tenant_id is not None else []
    return busqueda_correo.interpretar(q, categorias, clientes)


def obtener_mensaje(mensaje_id: int):
    return db.obtener_mensaje_correo(mensaje_id)


def marcar_leido(mensaje_id: int, leido: bool = True) -> None:
    mensaje = db.obtener_mensaje_correo(mensaje_id)
    if mensaje is None or bool(mensaje["leido"]) == bool(leido):
        db.marcar_leido_mensaje_correo(mensaje_id, leido)
        return
    db.marcar_leido_mensaje_correo(mensaje_id, leido)
    _encolar_y_lanzar(mensaje, "leido" if leido else "no_leido")


def eliminar_mensaje(mensaje_id: int) -> None:
    """Lo quita de aquí y, en las cuentas IMAP, del servidor (a la papelera si la tiene)."""
    mensaje = db.obtener_mensaje_correo(mensaje_id)
    db.eliminar_mensaje_correo(mensaje_id)
    if mensaje is not None:
        _encolar_y_lanzar(mensaje, "eliminar")


def destacar_mensaje(mensaje_id: int, destacado: bool, fecha_aviso: str | None = None) -> None:
    mensaje = db.obtener_mensaje_correo(mensaje_id)
    db.destacar_mensaje_correo(mensaje_id, destacado, fecha_aviso)
    if mensaje is not None and bool(mensaje["destacado"]) != bool(destacado):
        _encolar_y_lanzar(mensaje, "destacar" if destacado else "quitar_destacar")


def posponer_mensaje(mensaje_id: int, hasta: str | None) -> None:
    db.posponer_mensaje_correo(mensaje_id, hasta)


def direccion_email(texto: str | None) -> str | None:
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
    propia = direccion_email(direccion_propia)
    vistas: set[str] = set()
    resultado: list[str] = []
    for campo in (mensaje["remitente"], mensaje["destinatarios"], mensaje["cc"]):
        if not campo:
            continue
        for destinatario in campo.split(","):
            destinatario = destinatario.strip()
            if not destinatario:
                continue
            clave = direccion_email(destinatario)
            if not clave or clave == propia or clave in vistas:
                continue
            vistas.add(clave)
            resultado.append(destinatario)
    return ", ".join(resultado)


def _aplicar_categoria_automatica(
    usuario_id: int, mensaje_id: int, remitente_crudo: str | None, asunto: str | None = None,
) -> None:
    """Aplica al mensaje recién insertado la regla simple de categoría por
    remitente (email exacto o "@dominio.com") y después las reglas avanzadas
    (remitente y/o asunto -> categoría, leído, destacar, cliente fiscal).
    Un fallo en una regla nunca debe romper la sincronización."""
    direccion = direccion_email(remitente_crudo)
    categoria_id = db.categoria_id_por_remitente_correo(usuario_id, direccion)
    if categoria_id is not None:
        db.asignar_categoria_correo(usuario_id, mensaje_id, categoria_id)
    try:
        for regla in db.reglas_correo_aplicables(usuario_id, direccion, asunto):
            if regla["categoria_id"] is not None:
                db.asignar_categoria_correo(usuario_id, mensaje_id, regla["categoria_id"])
            if regla["marcar_leido"]:
                marcar_leido(mensaje_id, True)
            if regla["destacar"]:
                destacar_mensaje(mensaje_id, True)
            if regla["cliente_fiscal_id"] is not None:
                tenant = db.tenant_de_usuario(usuario_id)
                if tenant is not None:
                    db.asignar_cliente_fiscal_correo(tenant["id"], mensaje_id, regla["cliente_fiscal_id"])
                if regla["archivar_adjuntos"]:
                    archivar_correo_en_expediente(usuario_id, mensaje_id, regla["cliente_fiscal_id"], automatico=True)
    except Exception:  # noqa: BLE001
        logger.exception("Regla de correo fallida (mensaje %s)", mensaje_id)
    try:
        _vincular_cliente_por_remitente(usuario_id, mensaje_id, direccion)
    except Exception:  # noqa: BLE001
        logger.exception("Vínculo automático con cliente fiscal fallido (mensaje %s)", mensaje_id)


def _vincular_cliente_por_remitente(usuario_id: int, mensaje_id: int, direccion: str | None) -> bool:
    """Si el remitente es el email de un cliente fiscal del despacho (y solo de
    uno), enlaza el mensaje con él. No pisa un vínculo ya puesto por una regla
    o a mano. Devuelve True si ha vinculado."""
    if not direccion:
        return False
    tenant = db.tenant_de_usuario(usuario_id)
    if tenant is None:
        return False
    cliente_id = db.cliente_fiscal_id_por_email(tenant["id"], direccion)
    if cliente_id is None:
        return False
    mensaje = db.obtener_mensaje_correo(mensaje_id)
    if mensaje is None or mensaje["cliente_fiscal_id"] is not None:
        return False
    db.asignar_cliente_fiscal_correo(tenant["id"], mensaje_id, cliente_id)
    return True


def vincular_correos_a_clientes(usuario_id: int) -> int:
    """Pasa por los mensajes sin cliente del usuario y enlaza los que vienen del
    email de un cliente fiscal. Devuelve cuántos ha vinculado."""
    tenant = db.tenant_de_usuario(usuario_id)
    if tenant is None:
        return 0
    n = 0
    for fila in db.mensajes_correo_sin_cliente(usuario_id):
        cliente_id = db.cliente_fiscal_id_por_email(tenant["id"], direccion_email(fila["remitente"]))
        if cliente_id is not None:
            db.asignar_cliente_fiscal_correo(tenant["id"], fila["id"], cliente_id)
            n += 1
    return n


# --- Plantillas con variables --------------------------------------------------

VARIABLES_PLANTILLA = (
    ("cliente", "Nombre del cliente fiscal"), ("nif", "NIF del cliente"), ("modelo", "Modelo del próximo vencimiento"),
    ("periodo", "Periodo del próximo vencimiento"), ("fecha_limite", "Fecha límite del próximo vencimiento"),
    ("documento", "Documentación que se ha pedido para ese vencimiento"), ("dias", "Días que faltan para el vencimiento"),
    ("enlace_portal", "Enlace al portal del cliente"),
    ("mi_nombre", "Tu nombre"), ("despacho", "Nombre de tu despacho"), ("fecha", "Fecha de hoy"),
)
_PATRON_VARIABLE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def contexto_plantilla(usuario_id: int, cliente_fiscal_id: int | None = None, modelo: str | None = None) -> dict[str, str]:
    """Valores de las variables para este usuario y, si se indica, ese cliente
    fiscal (solo si es de su despacho) con su próximo vencimiento pendiente. Con `modelo` (una plantilla
    pensada para el 303, por ejemplo) se usa el próximo vencimiento pendiente DE ESE MODELO."""
    tenant = db.tenant_de_usuario(usuario_id)
    usuario = db.obtener_usuario(usuario_id)
    valores = {
        "mi_nombre": (db.nombre_mostrado_usuario(usuario_id) or (usuario["email"] if usuario else "")),
        "despacho": tenant["nombre"] if tenant else "",
        "fecha": datetime.now().strftime("%d/%m/%Y"),
    }
    if tenant is not None and cliente_fiscal_id:
        cliente = db.obtener_cliente_fiscal(tenant["id"], cliente_fiscal_id)
        if cliente is not None:
            valores["cliente"] = cliente["nombre"] or ""
            valores["nif"] = cliente["nif"] or ""
            proximos = db.listar_vencimientos_fiscales(tenant["id"], estado="pendiente", cliente_fiscal_id=cliente_fiscal_id)
            if modelo:
                proximos = [p for p in proximos if (p["modelo"] or "").strip().lower() == modelo.strip().lower()]
            if proximos:
                v = min(proximos, key=lambda f: f["fecha_limite"])
                valores["modelo"], valores["periodo"] = v["modelo"] or "", v["periodo"] or ""
                valores["documento"] = (v["documento_solicitado"] or "").strip()
                try:
                    restantes = (datetime.strptime(v["fecha_limite"][:10], "%Y-%m-%d").date() - datetime.now().date()).days
                    valores["dias"] = str(restantes) if restantes >= 0 else str(-restantes)
                except ValueError:
                    pass
                base = os.environ.get("GUILDA_URL_PUBLICA", "").strip().rstrip("/")
                if base:
                    valores["enlace_portal"] = f"{base}/portal/entrar"
                try:
                    valores["fecha_limite"] = datetime.strptime(v["fecha_limite"][:10], "%Y-%m-%d").strftime("%d/%m/%Y")
                except ValueError:
                    valores["fecha_limite"] = v["fecha_limite"] or ""
    return valores


def rellenar_plantilla(texto: str | None, valores: dict[str, str], html: bool = False) -> tuple[str, list[str]]:
    """Sustituye `{{variable}}`. Las que no se pueden resolver se dejan tal cual
    (para que se vea qué falta) y se devuelven en la lista. Con `html=True` el
    valor se escapa, porque el cuerpo se inserta como HTML."""
    sin_resolver: list[str] = []

    def cambiar(m):
        nombre = m.group(1)
        if nombre in valores and valores[nombre] != "":
            return html_lib.escape(valores[nombre]) if html else valores[nombre]
        if nombre in dict(VARIABLES_PLANTILLA) and nombre not in sin_resolver:
            sin_resolver.append(nombre)
        return m.group(0)

    return _PATRON_VARIABLE.sub(cambiar, texto or ""), sin_resolver


# --- Adjuntos del correo -> documentos de un vencimiento -------------------------

def guardar_adjunto_en_vencimiento(usuario_id: int, mensaje_id: int, adjunto_id: int, vencimiento_id: int, visible_cliente: bool = False) -> int:
    """Copia el adjunto de un correo del usuario como documento de un vencimiento
    de su despacho. Por defecto es interno (el cliente no lo ve en el portal);
    solo se puede enseñar al cliente si es imagen o PDF. Devuelve el id del
    documento."""
    tenant = db.tenant_de_usuario(usuario_id)
    if tenant is None:
        raise ErrorCorreo("Tu usuario no pertenece a ningún despacho.")
    if not db.adjunto_correo_pertenece_a_usuario(usuario_id, adjunto_id):
        raise ErrorCorreo("Adjunto no encontrado.")
    adjunto = db.obtener_adjunto_correo(adjunto_id)
    if adjunto is None or adjunto["mensaje_id"] != mensaje_id:
        raise ErrorCorreo("Adjunto no encontrado.")
    if db.obtener_vencimiento_fiscal(tenant["id"], vencimiento_id) is None:
        raise ErrorCorreo("Vencimiento no encontrado.")
    contenido = adjunto["contenido"] or b""
    if len(contenido) > db.TAMANO_MAXIMO_DOCUMENTO_VENCIMIENTO:
        raise ErrorCorreo("El adjunto supera el tamaño máximo (8 MB).")
    if visible_cliente and adjunto["tipo_mime"] not in db.MIME_PERMITIDOS_DOCUMENTO_VENCIMIENTO:
        raise ErrorCorreo("Solo se pueden enseñar al cliente imágenes o PDF.")
    return db.subir_documento_vencimiento(
        vencimiento_id, adjunto["nombre_archivo"], adjunto["tipo_mime"], contenido,
        origen="correo_compartido" if visible_cliente else "correo",
    )


_PATRON_IMG_REMOTA = re.compile(r'(<img\b[^>]*\bsrc=["\'])(https?://[^"\']+)(["\'])', re.IGNORECASE)


def html_con_imagenes_bloqueadas(html: str | None) -> tuple[str, bool]:
    """Sustituye el `src` de cualquier `<img src="http(s)://...">` por un
    marcador inerte, para que el navegador (o el HtmlWidget del móvil) no
    llegue a pedirlo por red — evita tracking pixels y fugas de IP de
    remitentes no confiables. Devuelve (html_modificado, hubo_bloqueo).
    No modifica el HTML guardado en la base de datos, solo el que se
    muestra en este momento."""
    if not html:
        return html or "", False
    hubo = False

    def _reemplazo(m: re.Match) -> str:
        nonlocal hubo
        hubo = True
        return f'{m.group(1)}data:,{m.group(3)} data-src-bloqueado="{m.group(2)}"'

    return _PATRON_IMG_REMOTA.sub(_reemplazo, html), hubo


def mover_mensaje(usuario_id: int, mensaje_id: int, carpeta_destino: str) -> None:
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
    cuenta = db.obtener_cuenta_correo(usuario_id, mensaje["cuenta_id"])
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

def crear_categoria(usuario_id: int, nombre: str, color: str) -> int:
    if not nombre.strip():
        raise ErrorCorreo("La categoría necesita un nombre.")
    try:
        return db.crear_categoria_correo(usuario_id, nombre, color)
    except ValueError as e:
        raise ErrorCorreo(str(e)) from e


def listar_categorias(usuario_id: int):
    return db.listar_categorias_correo(usuario_id)


def eliminar_categoria(usuario_id: int, categoria_id: int) -> None:
    db.eliminar_categoria_correo(usuario_id, categoria_id)


def asignar_categoria(usuario_id: int, mensaje_id: int, categoria_id: int | None) -> None:
    db.asignar_categoria_correo(usuario_id, mensaje_id, categoria_id)


def asignar_cliente_fiscal(tenant_id: int, mensaje_id: int, cliente_fiscal_id: int | None) -> None:
    db.asignar_cliente_fiscal_correo(tenant_id, mensaje_id, cliente_fiscal_id)


# --- Del correo al expediente del cliente -------------------------------------------

LOGO_MAXIMO_BYTES = 30 * 1024      # una imagen pequeña de firma o logotipo no es un documento del cliente


def _correo_como_texto(mensaje) -> bytes:
    """El correo en texto plano (cabeceras y cuerpo), para guardarlo en el expediente. No se guarda el HTML
    del remitente tal cual: al abrirlo luego podría cargar contenido remoto."""
    cuerpo = mensaje["cuerpo_texto"] or html_a_texto_plano(mensaje["cuerpo_html"] or "") or ""
    cabeceras = [
        f"De: {mensaje['remitente'] or ''}", f"Para: {mensaje['destinatarios'] or ''}",
        *([f"Cc: {mensaje['cc']}"] if mensaje["cc"] else []),
        f"Fecha: {(mensaje['fecha'] or '')[:19].replace('T', ' ')}", f"Asunto: {mensaje['asunto'] or ''}",
    ]
    return ("\n".join(cabeceras) + "\n\n" + cuerpo).encode("utf-8")


def archivar_correo_en_expediente(
    usuario_id: int, mensaje_id: int, cliente_fiscal_id: int, adjunto_ids: list[int] | None = None,
    guardar_correo: bool = False, categoria: str | None = None, automatico: bool = False,
) -> dict:
    """Guarda en el expediente del cliente los adjuntos elegidos (todos si `adjunto_ids` es None) y,
    si se pide, el propio correo como texto; deja el correo vinculado al cliente. `automatico` (reglas):
    se omiten las imágenes pequeñas (logos, firmas). Devuelve {'archivados', 'duplicados', 'omitidos'}
    o lanza ErrorCorreo si el mensaje o el cliente no son válidos."""
    resumen = {"archivados": 0, "duplicados": 0, "omitidos": 0}
    if not db.mensaje_correo_pertenece_a_usuario(usuario_id, mensaje_id):
        raise ErrorCorreo("Ese correo no existe.")
    tenant = db.tenant_de_usuario(usuario_id)
    if tenant is None or db.obtener_cliente_fiscal(tenant["id"], cliente_fiscal_id) is None:
        raise ErrorCorreo("Ese cliente no existe.")
    mensaje = db.obtener_mensaje_correo(mensaje_id)
    db.asignar_cliente_fiscal_correo(tenant["id"], mensaje_id, cliente_fiscal_id)

    def guardar(nombre, tipo, contenido):
        resultado, _id = db.archivar_documento_cliente(
            usuario_id, cliente_fiscal_id, nombre, tipo, contenido, categoria=categoria, origen="correo",
            mensaje_correo_id=mensaje_id, asunto_origen=mensaje["asunto"],
        )
        if resultado == "ok":
            resumen["archivados"] += 1
        elif resultado == "duplicado":
            resumen["duplicados"] += 1
        else:
            resumen["omitidos"] += 1

    for fila in db.listar_adjuntos_correo(mensaje_id):
        if adjunto_ids is not None and fila["id"] not in adjunto_ids:
            continue
        if automatico and fila["tipo_mime"].startswith("image/") and fila["tamano_bytes"] < LOGO_MAXIMO_BYTES:
            resumen["omitidos"] += 1
            continue
        adjunto = db.obtener_adjunto_correo(fila["id"])
        if adjunto is not None:
            guardar(adjunto["nombre_archivo"], adjunto["tipo_mime"], bytes(adjunto["contenido"]))
    if guardar_correo:
        fecha = (mensaje["fecha"] or "")[:10]
        asunto = re.sub(r"[^\w .-]+", "", mensaje["asunto"] or "sin asunto").strip()[:80] or "sin asunto"
        guardar(f"Correo {fecha} - {asunto}.txt".replace("  ", " "), "text/plain", _correo_como_texto(mensaje))
    if resumen["archivados"] and not automatico:
        db.registrar_acceso_cliente(tenant["id"], cliente_fiscal_id, usuario_id, "correo_archivado", f"{resumen['archivados']} documento(s) de «{(mensaje['asunto'] or '')[:80]}»")
    return resumen


# --- Plantillas de respuesta guardadas -------------------------------------

def crear_plantilla(usuario_id: int, nombre: str, asunto: str | None, cuerpo: str, modelo: str | None = None) -> int:
    if not nombre.strip():
        raise ErrorCorreo("La plantilla necesita un nombre.")
    if not cuerpo.strip():
        raise ErrorCorreo("La plantilla necesita un cuerpo.")
    return db.crear_plantilla_correo(usuario_id, nombre, asunto, cuerpo, modelo)


def listar_plantillas(usuario_id: int):
    return db.listar_plantillas_correo(usuario_id)


def obtener_plantilla(usuario_id: int, plantilla_id: int):
    return db.obtener_plantilla_correo(usuario_id, plantilla_id)


def eliminar_plantilla(usuario_id: int, plantilla_id: int) -> None:
    db.eliminar_plantilla_correo(usuario_id, plantilla_id)


# --- Remitentes de confianza ---------------------------------------------------

def confiar_en_remitente(usuario_id: int, direccion: str) -> int:
    direccion = direccion_email(direccion) or direccion.strip().lower()
    if not direccion:
        raise ErrorCorreo("Indica una dirección de correo.")
    return db.confiar_en_remitente(usuario_id, direccion)


def listar_remitentes_confiables(usuario_id: int):
    return db.listar_remitentes_confiables(usuario_id)


def eliminar_remitente_confiable(usuario_id: int, remitente_id: int) -> None:
    db.eliminar_remitente_confiable(usuario_id, remitente_id)


# --- Reglas de categorización automática por remitente --------------------------

def crear_regla_categoria(usuario_id: int, remitente_patron: str, categoria_id: int) -> int:
    remitente_patron = remitente_patron.strip().lower()
    if not remitente_patron:
        raise ErrorCorreo("Indica un email o un dominio (@ejemplo.com).")
    try:
        return db.crear_regla_categoria_correo(usuario_id, remitente_patron, categoria_id)
    except ValueError as e:
        raise ErrorCorreo(str(e)) from e


def listar_reglas_categoria(usuario_id: int):
    return db.listar_reglas_categoria_correo(usuario_id)


def eliminar_regla_categoria(usuario_id: int, regla_id: int) -> None:
    db.eliminar_regla_categoria_correo(usuario_id, regla_id)


# --- Firma ---------------------------------------------------------------------

def guardar_firma(usuario_id: int, cuenta_id: int, firma_html: str, en_nuevos: bool, en_respuestas: bool) -> None:
    firma_html = sanear_html_externo(firma_html) if firma_html else firma_html
    db.guardar_firma_correo(usuario_id, cuenta_id, firma_html or None, en_nuevos, en_respuestas)


def preparar_cuerpo_inicial(usuario_id: int, cuenta_id: int, es_respuesta: bool, contenido_tras_firma: str = "") -> str:
    """Cuerpo con el que se abre el editor de redactar: un párrafo vacío
    (para que el cursor quede libre encima) seguido de la firma si
    corresponde según los interruptores de la cuenta, y después el contenido
    que ya hubiera (la cita de responder/reenviar, o nada si es nuevo)."""
    cuenta = db.obtener_cuenta_correo(usuario_id, cuenta_id)
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
        if isinstance(contrasena, correo_oauth.TokenOAuth):
            cadena = correo_oauth.cadena_xoauth2(usuario, contrasena)
            conn.ehlo_or_helo_if_needed()
            conn.auth("XOAUTH2", lambda challenge=None: cadena)
        else:
            conn.login(usuario, contrasena)
        return conn
    except (smtplib.SMTPException, OSError, socket.timeout) as e:
        logger.warning("Fallo de conexión SMTP a %s:%s -- %s", host, puerto, e)
        raise ErrorCorreo(
            f"No se ha podido conectar con el servidor de correo saliente ({host}:{puerto}) -- revisa el servidor, el puerto y la contraseña."
        ) from e


def _direcciones(cadena: str | None) -> list[str]:
    return [d.strip() for d in (cadena or "").split(",") if d.strip()]


def validar_envio(usuario_id: int, cuenta_id: int, destinatarios: str, asunto: str, cuerpo_html: str):
    """Las comprobaciones previas a enviar (también se hacen al ENCOLAR un
    envío, para que el error salga en el editor y no más tarde, a solas).
    Devuelve la cuenta."""
    cuenta = db.obtener_cuenta_correo(usuario_id, cuenta_id)
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
    return cuenta


def encolar_envio(
    usuario_id: int, cuenta_id: int, destinatarios: str, asunto: str, cuerpo_html: str,
    cc: str = "", bcc: str = "", en_respuesta_a: str | None = None, adjuntos: list[dict] | None = None,
    *, enviar_en: str, programado: bool = False, seguimiento_dias: int | None = None,
) -> int:
    """Valida y deja el correo en la cola (se envía cuando llegue `enviar_en`,
    ISO local). Devuelve el id del envío."""
    validar_envio(usuario_id, cuenta_id, destinatarios, asunto, cuerpo_html)
    adjuntos = adjuntos or []
    if sum(len(a["bytes"]) for a in adjuntos) > db.MAX_BYTES_ADJUNTOS_ENVIO:
        raise ErrorCorreo("Los adjuntos superan el tamaño máximo de 25 MB.")
    return db.encolar_envio_correo(
        usuario_id, cuenta_id, destinatarios, cc, bcc, asunto, cuerpo_html, en_respuesta_a,
        adjuntos, enviar_en, programado, seguimiento_dias,
    )


def borrador_desde_envio(envio) -> int:
    """Devuelve el envío al editor como borrador (deshacer/cancelar/fallo)."""
    borrador_id = db.guardar_borrador_correo(
        envio["usuario_id"], None, cuenta_id=envio["cuenta_id"], destinatarios=envio["destinatarios"],
        cc=envio["cc"] or "", bcc=envio["bcc"] or "", asunto=envio["asunto"], cuerpo_html=envio["cuerpo_html"],
        en_respuesta_a=envio["en_respuesta_a"],
    )
    db.copiar_adjuntos_envio_a_borrador(envio["id"], borrador_id)  # los adjuntos viajan con el borrador
    return borrador_id


def procesar_envios_pendientes(ahora: datetime | None = None) -> int:
    """Envía los correos de la cola cuya hora ha llegado. Un fallo nunca
    pierde el correo: queda como borrador y se avisa al usuario. Devuelve
    cuántos se enviaron."""
    ahora = ahora or datetime.now()
    db.rescatar_envios_atascados((ahora - timedelta(minutes=10)).isoformat(timespec="seconds"))
    enviados = 0
    for envio in db.envios_correo_vencidos(ahora.isoformat(timespec="seconds")):
        if not db.reclamar_envio_correo(envio["id"]):
            continue  # otro proceso se lo ha quedado, o el usuario lo ha cancelado
        try:
            construir_y_enviar(
                envio["usuario_id"], envio["cuenta_id"], envio["destinatarios"], envio["asunto"],
                envio["cuerpo_html"], cc=envio["cc"] or "", bcc=envio["bcc"] or "",
                en_respuesta_a=envio["en_respuesta_a"], adjuntos=db.adjuntos_envio_correo(envio["id"]),
                seguimiento_dias=envio["seguimiento_dias"],
            )
        except Exception as e:  # noqa: BLE001 -- un envío fallido no debe parar la cola
            logger.exception("Envío de correo %s fallido", envio["id"])
            borrador_id = borrador_desde_envio(envio)
            db.cerrar_envio_correo(envio["id"], "error", str(e)[:500])
            try:
                notificaciones.crear_y_enviar(
                    envio["usuario_id"], "correo_envio_fallido", "No se pudo enviar un correo",
                    f"«{envio['asunto']}»: {e}. Está en tus borradores.",
                    f"/correo/redactar?borrador_id={borrador_id}",
                )
            except Exception:  # noqa: BLE001
                logger.exception("No se pudo notificar el fallo del envío %s", envio["id"])
            continue
        db.cerrar_envio_correo(envio["id"], "enviado")
        enviados += 1
    db.purgar_envios_correo_antiguos((ahora - timedelta(days=7)).isoformat(timespec="seconds"))
    return enviados


def _direcciones_propias(cuenta) -> set[str]:
    propia = direccion_email(cuenta["usuario"])
    return {propia.lower()} if propia else set()


def procesar_seguimientos(ahora: datetime | None = None) -> dict:
    """Revisa los correos de los que se espera respuesta: si ha llegado (en el mismo hilo y de otra persona) se
    cierran; si ha pasado el plazo sin ella, se avisa una sola vez. Devuelve {'respondidos', 'avisados'}."""
    ahora = ahora or datetime.now()
    resultado = {"respondidos": 0, "avisados": 0}
    cuentas: dict[int, object] = {}
    for seg in db.seguimientos_en_espera():
        cuenta = cuentas.get(seg["cuenta_id"]) or cuentas.setdefault(seg["cuenta_id"], db.obtener_cuenta_correo(seg["usuario_id"], seg["cuenta_id"]))
        if cuenta is None:
            db.cancelar_seguimiento_correo(seg["usuario_id"], seg["id"])
            continue
        respuesta = db.respuesta_a_mensaje(seg["cuenta_id"], seg["message_id"], seg["creado_en"], _direcciones_propias(cuenta))
        if respuesta is not None:
            if db.cerrar_seguimiento_correo(seg["id"], "respondido"):
                resultado["respondidos"] += 1
            continue
        if seg["avisar_en"] <= ahora.isoformat(timespec="seconds") and db.cerrar_seguimiento_correo(seg["id"], "sin_respuesta"):
            local = db.mensaje_local_por_message_id(seg["usuario_id"], seg["message_id"])
            url = f"/correo/?cuenta_id={seg['cuenta_id']}&mensaje_id={local['id']}" if local else f"/correo/?cuenta_id={seg['cuenta_id']}"
            try:
                notificaciones.crear_y_enviar(
                    seg["usuario_id"], "correo_sin_respuesta", "Sin respuesta a tu correo",
                    f"«{seg['asunto'] or '(sin asunto)'}» a {seg['destinatarios'] or '—'} no ha tenido respuesta.", url,
                    datos={"tipo": "correo_sin_respuesta"},
                )
            except Exception:  # noqa: BLE001
                logger.exception("No se pudo avisar del seguimiento %s", seg["id"])
            resultado["avisados"] += 1
    return resultado


def construir_y_enviar(
    usuario_id: int,
    cuenta_id: int, destinatarios: str, asunto: str, cuerpo_html: str,
    cc: str = "", bcc: str = "", en_respuesta_a: str | None = None,
    adjuntos: list[dict] | None = None, seguimiento_dias: int | None = None,
) -> str:
    """Envía un correo desde `cuenta_id` y devuelve su Message-ID. Con `seguimiento_dias`, avisa si en esos
    días no llega respuesta (ver `procesar_seguimientos`). `destinatarios`/`cc`/`bcc` son
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
    cuenta = validar_envio(usuario_id, cuenta_id, destinatarios, asunto, cuerpo_html)

    mensaje = EmailMessage()
    mensaje["From"] = cuenta["usuario"]
    # Message-ID propio (los servidores respetan el que ya viene): así se puede reconocer la respuesta.
    dominio = direccion_email(cuenta["usuario"]).rpartition("@")[2] if direccion_email(cuenta["usuario"]) else None
    mensaje_id = make_msgid(domain=dominio or None)
    mensaje["Message-ID"] = mensaje_id
    mensaje["To"] = destinatarios.strip()
    if cc.strip():
        mensaje["Cc"] = cc.strip()
    mensaje["Subject"] = asunto.strip()
    if en_respuesta_a:
        mensaje["In-Reply-To"] = en_respuesta_a
        mensaje["References"] = en_respuesta_a
    mensaje.set_content(html_a_texto_plano(cuerpo_html) or " ")
    mensaje.add_alternative(cuerpo_html, subtype="html")

    for adjunto in (adjuntos or []):
        maintype, _, subtype = adjunto["tipo"].partition("/")
        mensaje.add_attachment(
            adjunto["bytes"], maintype=maintype or "application",
            subtype=subtype or "octet-stream", filename=adjunto["nombre"],
        )

    todos_los_destinatarios = _direcciones(destinatarios) + _direcciones(cc) + _direcciones(bcc)

    contrasena = _credencial(cuenta, "smtp")
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

    for nombre, direccion in getaddresses([destinatarios, cc, bcc]):
        if direccion.strip():
            db.registrar_destinatario_reciente(usuario_id, direccion.strip(), nombre.strip() or None)
    try:
        tenant = db.tenant_de_usuario(usuario_id)
        eventos.emitir(
            "correo.enviado", tenant["id"] if tenant else None,
            {"cuenta_id": cuenta_id, "destinatarios": destinatarios.strip(), "asunto": asunto.strip()},
        )
    except Exception:  # noqa: BLE001 -- un webhook fallido no debe afectar a un correo ya enviado
        logger.exception("No se pudo emitir el evento correo.enviado")
    if seguimiento_dias:
        db.crear_seguimiento_correo(usuario_id, cuenta_id, mensaje_id, asunto.strip(), destinatarios.strip(), seguimiento_dias)
    return mensaje_id
