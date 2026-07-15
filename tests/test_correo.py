"""Tests del cliente de correo (app/correo.py): cuentas, sincronización
IMAP/POP3, envío por SMTP y lectura de la caché local. imaplib/poplib/smtplib
están mockeados (nunca se conecta a un servidor real).
"""
import imaplib
import poplib
import smtplib
from email.message import EmailMessage

import pytest

from app import correo, db


def _mensaje_bytes(asunto: str, remitente: str, cuerpo: str, message_id: str | None = None) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = remitente
    msg["To"] = "yo@ejemplo.com"
    msg["Date"] = "Mon, 13 Jul 2026 09:00:00 +0000"
    if message_id:
        msg["Message-ID"] = message_id
    msg.set_content(cuerpo)
    return bytes(msg)


def _mensaje_con_adjunto_bytes(asunto: str, remitente: str, cuerpo: str, nombre_archivo: str, contenido_adjunto: bytes) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = remitente
    msg["To"] = "yo@ejemplo.com"
    msg["Date"] = "Mon, 13 Jul 2026 09:00:00 +0000"
    msg.set_content(cuerpo)
    msg.add_attachment(contenido_adjunto, maintype="text", subtype="plain", filename=nombre_archivo)
    return bytes(msg)


class FakeIMAP:
    def __init__(self, mensajes: dict[str, bytes], contrasena_valida: str = "correcta", carpetas=("INBOX",)):
        self._mensajes = mensajes
        self._contrasena_valida = contrasena_valida
        self._carpetas = carpetas

    def login(self, usuario, contrasena):
        if contrasena != self._contrasena_valida:
            raise imaplib.IMAP4.error("credenciales inválidas")
        return "OK", [b"Logged in"]

    def list(self):
        return "OK", [f'(\\HasNoChildren) "/" "{c}"'.encode() for c in self._carpetas]

    def select(self, carpeta):
        return "OK", [b"1"]

    def uid(self, comando, *args):
        if comando == "search":
            uids = " ".join(self._mensajes.keys()).encode()
            return "OK", [uids]
        if comando == "fetch":
            uid = args[0]
            if uid not in self._mensajes:
                return "OK", [None]
            return "OK", [(b"1 (RFC822 {n})", self._mensajes[uid])]
        if comando == "copy":
            self.copiados = getattr(self, "copiados", [])
            self.copiados.append(args)
            return "OK", [b"COPY completed"]
        if comando == "store":
            self.marcados = getattr(self, "marcados", [])
            self.marcados.append(args)
            return "OK", [b"STORE completed"]
        raise AssertionError(f"comando IMAP inesperado: {comando}")

    def expunge(self):
        self.expurgado = True
        return "OK", [b"EXPUNGE completed"]

    def logout(self):
        return "BYE", [b"Logout"]


class FakePOP3:
    def __init__(self, mensajes: list[bytes], contrasena_valida: str = "correcta"):
        self._mensajes = mensajes
        self._contrasena_valida = contrasena_valida
        self._usuario = None

    def user(self, usuario):
        self._usuario = usuario

    def pass_(self, contrasena):
        if contrasena != self._contrasena_valida:
            raise poplib.error_proto("credenciales inválidas")

    def list(self):
        return b"+OK", [str(i).encode() for i in range(1, len(self._mensajes) + 1)]

    def retr(self, indice):
        crudo = self._mensajes[indice - 1]
        lineas = crudo.split(b"\n")
        return b"+OK", lineas

    def quit(self):
        pass


def _cuenta_imap(monkeypatch, mensajes: dict[str, bytes], contrasena_valida: str = "correcta", carpetas=("INBOX",)) -> None:
    monkeypatch.setattr(
        imaplib, "IMAP4_SSL",
        lambda host, port, timeout=None: FakeIMAP(mensajes, contrasena_valida, carpetas),
    )


def _cuenta_imap_instancia_compartida(monkeypatch, mensajes: dict[str, bytes], carpetas=("INBOX",)) -> "FakeIMAP":
    """Como _cuenta_imap, pero siempre devuelve la MISMA instancia de FakeIMAP
    en cada conexión — para poder inspeccionar su estado (copiados/marcados)
    después de una operación que abre más de una conexión IMAP en el test."""
    instancia = FakeIMAP(mensajes, "correcta", carpetas)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda host, port, timeout=None: instancia)
    return instancia


def _cuenta_pop3(monkeypatch, mensajes: list[bytes], contrasena_valida: str = "correcta") -> None:
    monkeypatch.setattr(poplib, "POP3_SSL", lambda host, port, timeout=None: FakePOP3(mensajes, contrasena_valida))


class FakeSMTP:
    ultimo_mensaje = None

    def __init__(self, mensajes_enviados: list, contrasena_valida: str = "correcta", destinatarios_capturados: list | None = None):
        self._mensajes_enviados = mensajes_enviados
        self._contrasena_valida = contrasena_valida
        self._destinatarios_capturados = destinatarios_capturados

    def starttls(self):
        pass

    def login(self, usuario, contrasena):
        if contrasena != self._contrasena_valida:
            raise smtplib.SMTPAuthenticationError(535, b"credenciales invalidas")

    def send_message(self, mensaje, to_addrs=None):
        self._mensajes_enviados.append(mensaje)
        if self._destinatarios_capturados is not None:
            self._destinatarios_capturados.append(to_addrs)

    def quit(self):
        pass


def _cuenta_smtp(monkeypatch, mensajes_enviados: list, contrasena_valida: str = "correcta", destinatarios_capturados: list | None = None) -> None:
    fabrica = lambda host, port, timeout=None: FakeSMTP(mensajes_enviados, contrasena_valida, destinatarios_capturados)
    monkeypatch.setattr(smtplib, "SMTP", fabrica)
    monkeypatch.setattr(smtplib, "SMTP_SSL", fabrica)


def _crear_cuenta_con_smtp(monkeypatch) -> int:
    _cuenta_imap(monkeypatch, {})
    return correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
        smtp_host="smtp.ejemplo.com", smtp_puerto=587, smtp_tls=True,
    )


# --- Cuentas -------------------------------------------------------------------

def test_guardar_cuenta_imap_valida_conexion_y_guarda_contrasena_en_keyring(monkeypatch):
    _cuenta_imap(monkeypatch, {})
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    cuentas = db.listar_cuentas_correo()
    assert len(cuentas) == 1
    assert cuentas[0]["id"] == cuenta_id
    assert cuentas[0]["nombre"] == "Trabajo"

    import keyring
    assert keyring.get_password(correo.SERVICIO_KEYRING, correo._clave_keyring(cuenta_id)) == "correcta"


def test_guardar_cuenta_con_credenciales_invalidas_no_crea_nada(monkeypatch):
    _cuenta_imap(monkeypatch, {}, contrasena_valida="correcta")
    with pytest.raises(correo.ErrorCorreo):
        correo.guardar_cuenta(
            nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
            usuario="yo@ejemplo.com", contrasena="incorrecta",
        )
    assert db.listar_cuentas_correo() == []


def test_guardar_cuenta_sin_datos_obligatorios_lanza_error():
    with pytest.raises(correo.ErrorCorreo):
        correo.guardar_cuenta(nombre="", protocolo="imap", host="x", puerto=993, usuario="y", contrasena="z")


def test_eliminar_cuenta_borra_cuenta_mensajes_y_credencial(monkeypatch):
    _cuenta_imap(monkeypatch, {"1": _mensaje_bytes("Hola", "a@b.com", "cuerpo")})
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.sincronizar_bandeja(cuenta_id)
    assert len(correo.listar_mensajes(cuenta_id)) == 1

    correo.eliminar_cuenta(cuenta_id)

    assert db.listar_cuentas_correo() == []
    assert correo.listar_mensajes(cuenta_id) == []
    import keyring
    assert keyring.get_password(correo.SERVICIO_KEYRING, correo._clave_keyring(cuenta_id)) is None


def test_probar_conexion_cuenta_inexistente_lanza_error():
    with pytest.raises(correo.ErrorCorreo):
        correo.probar_conexion(999)


# --- Sincronización IMAP --------------------------------------------------------

def test_sincronizar_bandeja_imap_descarga_mensajes_nuevos(monkeypatch):
    mensajes = {
        "1": _mensaje_bytes("Primer correo", "a@b.com", "Hola, este es el cuerpo."),
        "2": _mensaje_bytes("Segundo correo", "c@d.com", "Otro cuerpo distinto."),
    }
    _cuenta_imap(monkeypatch, mensajes)
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )

    resumen = correo.sincronizar_bandeja(cuenta_id)
    assert resumen == {"nuevos": 2}

    guardados = correo.listar_mensajes(cuenta_id)
    assert len(guardados) == 2
    asuntos = {m["asunto"] for m in guardados}
    assert asuntos == {"Primer correo", "Segundo correo"}


def test_sincronizar_bandeja_no_redescarga_mensajes_ya_guardados(monkeypatch):
    mensajes = {"1": _mensaje_bytes("Único", "a@b.com", "cuerpo")}
    _cuenta_imap(monkeypatch, mensajes)
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    assert correo.sincronizar_bandeja(cuenta_id) == {"nuevos": 1}
    assert correo.sincronizar_bandeja(cuenta_id) == {"nuevos": 0}
    assert len(correo.listar_mensajes(cuenta_id)) == 1


def test_sincronizar_bandeja_marca_ultima_sincronizacion(monkeypatch):
    _cuenta_imap(monkeypatch, {})
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.sincronizar_bandeja(cuenta_id)
    cuenta = db.obtener_cuenta_correo(cuenta_id)
    assert cuenta["ultima_sincronizacion"] is not None


# --- Sincronización POP3 --------------------------------------------------------

def test_sincronizar_bandeja_pop3_descarga_mensajes(monkeypatch):
    mensajes = [_mensaje_bytes("Correo POP3", "a@b.com", "cuerpo pop3")]
    _cuenta_pop3(monkeypatch, mensajes)
    cuenta_id = correo.guardar_cuenta(
        nombre="Personal", protocolo="pop3", host="pop.ejemplo.com", puerto=995,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    resumen = correo.sincronizar_bandeja(cuenta_id)
    assert resumen == {"nuevos": 1}
    guardados = correo.listar_mensajes(cuenta_id)
    assert guardados[0]["asunto"] == "Correo POP3"


# --- Lectura de la caché local ---------------------------------------------------

def test_listar_mensajes_filtra_por_no_leidos_y_texto(monkeypatch):
    mensajes = {
        "1": _mensaje_bytes("Factura de luz", "luz@empresa.com", "cuerpo"),
        "2": _mensaje_bytes("Reunión mañana", "jefe@empresa.com", "cuerpo"),
    }
    _cuenta_imap(monkeypatch, mensajes)
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.sincronizar_bandeja(cuenta_id)

    assert len(correo.listar_mensajes(cuenta_id, texto="Factura")) == 1
    assert len(correo.listar_mensajes(cuenta_id, solo_no_leidos=True)) == 2

    mensaje = correo.listar_mensajes(cuenta_id, texto="Factura")[0]
    correo.marcar_leido(mensaje["id"], True)
    assert len(correo.listar_mensajes(cuenta_id, solo_no_leidos=True)) == 1
    assert correo.obtener_mensaje(mensaje["id"])["leido"] == 1


def test_eliminar_mensaje_lo_quita_de_la_cache_local(monkeypatch):
    mensajes = {"1": _mensaje_bytes("Hola", "a@b.com", "cuerpo")}
    _cuenta_imap(monkeypatch, mensajes)
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.sincronizar_bandeja(cuenta_id)
    mensaje_id = correo.listar_mensajes(cuenta_id)[0]["id"]

    correo.eliminar_mensaje(mensaje_id)

    assert correo.obtener_mensaje(mensaje_id) is None
    assert correo.listar_mensajes(cuenta_id) == []


def test_contar_no_leidos_correo(monkeypatch):
    mensajes = {
        "1": _mensaje_bytes("Uno", "a@b.com", "cuerpo"),
        "2": _mensaje_bytes("Dos", "c@d.com", "cuerpo"),
    }
    _cuenta_imap(monkeypatch, mensajes)
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.sincronizar_bandeja(cuenta_id)
    assert db.contar_no_leidos_correo(cuenta_id) == 2

    mensaje = correo.listar_mensajes(cuenta_id, texto="Uno")[0]
    correo.marcar_leido(mensaje["id"], True)
    assert db.contar_no_leidos_correo(cuenta_id) == 1


def test_sincronizar_guarda_message_id_para_poder_responder(monkeypatch):
    mensajes = {"1": _mensaje_bytes("Hola", "a@b.com", "cuerpo", message_id="<abc123@ejemplo.com>")}
    _cuenta_imap(monkeypatch, mensajes)
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.sincronizar_bandeja(cuenta_id)
    guardado = correo.listar_mensajes(cuenta_id)[0]
    assert guardado["message_id"] == "<abc123@ejemplo.com>"


# --- Envío (SMTP) ----------------------------------------------------------------

def test_construir_y_enviar_manda_html_y_texto_plano_alternativo(monkeypatch):
    enviados = []
    _cuenta_smtp(monkeypatch, enviados)
    cuenta_id = _crear_cuenta_con_smtp(monkeypatch)

    correo.construir_y_enviar(
        cuenta_id, "destino@ejemplo.com", "Asunto de prueba",
        "<p>Cuerpo <b>en negrita</b> del mensaje.</p>",
    )

    assert len(enviados) == 1
    enviado = enviados[0]
    assert enviado["To"] == "destino@ejemplo.com"
    assert enviado["Subject"] == "Asunto de prueba"
    assert enviado["From"] == "yo@ejemplo.com"
    assert enviado.is_multipart()
    html_parte = enviado.get_body(preferencelist=("html",))
    assert "<b>en negrita</b>" in html_parte.get_content()
    texto_parte = enviado.get_body(preferencelist=("plain",))
    assert texto_parte.get_content().strip() == "Cuerpo en negrita del mensaje."


def test_construir_y_enviar_respuesta_incluye_in_reply_to(monkeypatch):
    enviados = []
    _cuenta_smtp(monkeypatch, enviados)
    cuenta_id = _crear_cuenta_con_smtp(monkeypatch)

    correo.construir_y_enviar(
        cuenta_id, "destino@ejemplo.com", "Re: Hola", "<p>Respuesta.</p>",
        en_respuesta_a="<abc123@ejemplo.com>",
    )

    enviado = enviados[0]
    assert enviado["In-Reply-To"] == "<abc123@ejemplo.com>"
    assert enviado["References"] == "<abc123@ejemplo.com>"


def test_construir_y_enviar_sin_smtp_configurado_lanza_error(monkeypatch):
    _cuenta_imap(monkeypatch, {})
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    with pytest.raises(correo.ErrorCorreo):
        correo.construir_y_enviar(cuenta_id, "destino@ejemplo.com", "Asunto", "<p>Cuerpo</p>")


def test_construir_y_enviar_sin_destinatarios_lanza_error(monkeypatch):
    enviados = []
    _cuenta_smtp(monkeypatch, enviados)
    cuenta_id = _crear_cuenta_con_smtp(monkeypatch)
    with pytest.raises(correo.ErrorCorreo):
        correo.construir_y_enviar(cuenta_id, "", "Asunto", "<p>Cuerpo</p>")
    assert enviados == []


def test_construir_y_enviar_cuerpo_vacio_lanza_error(monkeypatch):
    enviados = []
    _cuenta_smtp(monkeypatch, enviados)
    cuenta_id = _crear_cuenta_con_smtp(monkeypatch)
    with pytest.raises(correo.ErrorCorreo):
        correo.construir_y_enviar(cuenta_id, "destino@ejemplo.com", "Asunto", "<p><br></p>")
    assert enviados == []


def test_construir_y_enviar_credenciales_invalidas_lanza_error(monkeypatch):
    enviados = []
    _cuenta_smtp(monkeypatch, enviados, contrasena_valida="otra-cosa")
    cuenta_id = _crear_cuenta_con_smtp(monkeypatch)
    with pytest.raises(correo.ErrorCorreo):
        correo.construir_y_enviar(cuenta_id, "destino@ejemplo.com", "Asunto", "<p>Cuerpo</p>")
    assert enviados == []


def test_construir_y_enviar_cuenta_inexistente_lanza_error():
    with pytest.raises(correo.ErrorCorreo):
        correo.construir_y_enviar(999, "destino@ejemplo.com", "Asunto", "<p>Cuerpo</p>")


# --- HTML enriquecido: helpers y contenido embebido ------------------------------

def test_texto_a_html_escapa_y_convierte_saltos_de_linea():
    assert correo.texto_a_html("Hola <b>mundo</b>\nSegunda línea") == "Hola &lt;b&gt;mundo&lt;/b&gt;<br>Segunda línea"


def test_html_a_texto_plano_extrae_texto_legible():
    html = "<p>Hola <b>mundo</b></p><p>Segundo párrafo</p><br>Tercera línea"
    assert correo.html_a_texto_plano(html) == "Hola mundo\n\nSegundo párrafo\n\nTercera línea"


def test_sincronizar_incrusta_imagenes_inline_como_data_uri(monkeypatch):
    from email.message import EmailMessage as _EM

    msg = _EM()
    msg["Subject"] = "Con imagen"
    msg["From"] = "a@b.com"
    msg["To"] = "yo@ejemplo.com"
    msg["Date"] = "Mon, 13 Jul 2026 09:00:00 +0000"
    msg.set_content("Versión en texto plano.")
    msg.add_alternative('<p>Mira esto:</p><img src="cid:logo1">', subtype="html")
    html_part = msg.get_body(preferencelist=("html",))
    html_part.add_related(b"contenido-fake-png", maintype="image", subtype="png", cid="<logo1>")

    _cuenta_imap(monkeypatch, {"1": bytes(msg)})
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.sincronizar_bandeja(cuenta_id)

    guardado = correo.listar_mensajes(cuenta_id)[0]
    assert "cid:logo1" not in guardado["cuerpo_html"]
    assert "data:image/png;base64," in guardado["cuerpo_html"]


# --- Carpetas IMAP (todas se sincronizan automáticamente) -----------------------

def test_parsear_carpetas_imap_reconoce_nombres_con_espacios():
    lineas = [
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\HasNoChildren) "/" "[Gmail]/Sent Mail"',
        b'(\\Noselect \\HasChildren) "/" "[Gmail]"',
    ]
    assert correo._parsear_carpetas_imap(lineas) == ["INBOX", "[Gmail]/Sent Mail", "[Gmail]"]


def test_nombre_visible_carpeta_traduce_nombres_conocidos():
    assert correo._nombre_visible_carpeta("INBOX") == "Bandeja de entrada"
    assert correo._nombre_visible_carpeta("[Gmail]/Sent Mail") == "Enviados"
    assert correo._nombre_visible_carpeta("Trabajo/Proyectos") == "Proyectos"


def test_sincronizar_imap_descubre_y_sincroniza_varias_carpetas(monkeypatch):
    mensajes = {"1": _mensaje_bytes("Hola", "a@b.com", "cuerpo")}
    _cuenta_imap(monkeypatch, mensajes, carpetas=("INBOX", "Enviados"))
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    resumen = correo.sincronizar_bandeja(cuenta_id)
    assert resumen == {"nuevos": 2}  # el mismo UID "1" se sincroniza en cada una de las 2 carpetas

    carpetas = db.listar_carpetas_correo(cuenta_id)
    assert {c["nombre"] for c in carpetas} == {"INBOX", "Enviados"}

    assert len(correo.listar_mensajes(cuenta_id, carpeta="INBOX")) == 1
    assert len(correo.listar_mensajes(cuenta_id, carpeta="Enviados")) == 1


def test_listar_carpetas_pop3_devuelve_una_unica_bandeja_sintetica(monkeypatch):
    _cuenta_pop3(monkeypatch, [])
    cuenta_id = correo.guardar_cuenta(
        nombre="Personal", protocolo="pop3", host="pop.ejemplo.com", puerto=995,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    carpetas = correo.listar_carpetas(cuenta_id)
    assert carpetas == [{"nombre": "INBOX", "nombre_visible": "Bandeja de entrada"}]
    # POP3 no puede tener carpetas reales: no debe crearse ninguna fila en la tabla.
    assert db.listar_carpetas_correo(cuenta_id) == []


# --- Cc ------------------------------------------------------------------------

def test_sincronizar_guarda_cc(monkeypatch):
    msg = _mensaje_bytes("Hola", "a@b.com", "cuerpo")
    # _mensaje_bytes no añade Cc; se construye uno aparte para este test.
    from email.message import EmailMessage as _EM
    m = _EM()
    m["Subject"] = "Con copia"
    m["From"] = "a@b.com"
    m["To"] = "yo@ejemplo.com"
    m["Cc"] = "otro@ejemplo.com, tercero@ejemplo.com"
    m["Date"] = "Mon, 13 Jul 2026 09:00:00 +0000"
    m.set_content("cuerpo")

    _cuenta_imap(monkeypatch, {"1": bytes(m)})
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.sincronizar_bandeja(cuenta_id)
    guardado = correo.listar_mensajes(cuenta_id)[0]
    assert guardado["cc"] == "otro@ejemplo.com, tercero@ejemplo.com"


def test_construir_y_enviar_con_cc_y_cco(monkeypatch):
    enviados = []
    capturados = []
    _cuenta_smtp(monkeypatch, enviados, destinatarios_capturados=capturados)
    cuenta_id = _crear_cuenta_con_smtp(monkeypatch)

    correo.construir_y_enviar(
        cuenta_id, "destino@ejemplo.com", "Asunto", "<p>Cuerpo</p>",
        cc="copia@ejemplo.com", bcc="oculto@ejemplo.com",
    )

    enviado = enviados[0]
    assert enviado["Cc"] == "copia@ejemplo.com"
    assert enviado["Bcc"] is None  # Cco NUNCA es una cabecera del mensaje enviado
    assert set(capturados[0]) == {"destino@ejemplo.com", "copia@ejemplo.com", "oculto@ejemplo.com"}


def test_construir_y_enviar_sin_cc_ni_cco_no_incluye_cabecera_cc(monkeypatch):
    enviados = []
    _cuenta_smtp(monkeypatch, enviados)
    cuenta_id = _crear_cuenta_con_smtp(monkeypatch)

    correo.construir_y_enviar(cuenta_id, "destino@ejemplo.com", "Asunto", "<p>Cuerpo</p>")

    assert enviados[0]["Cc"] is None


# --- Categorías (propias de Guilda Work) -----------------------------------------

def test_crear_listar_eliminar_categoria():
    cat_id = correo.crear_categoria("Importante", "#e0555a")
    categorias = correo.listar_categorias()
    assert len(categorias) == 1
    assert categorias[0]["nombre"] == "Importante"
    assert categorias[0]["color"] == "#e0555a"

    correo.eliminar_categoria(cat_id)
    assert correo.listar_categorias() == []


def test_crear_categoria_sin_nombre_lanza_error():
    with pytest.raises(correo.ErrorCorreo):
        correo.crear_categoria("", "#000000")


def test_asignar_categoria_a_mensaje_y_eliminarla_la_deja_sin_categoria(monkeypatch):
    _cuenta_imap(monkeypatch, {"1": _mensaje_bytes("Hola", "a@b.com", "cuerpo")})
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.sincronizar_bandeja(cuenta_id)
    mensaje_id = correo.listar_mensajes(cuenta_id)[0]["id"]
    cat_id = correo.crear_categoria("Urgente", "#e0555a")

    correo.asignar_categoria(mensaje_id, cat_id)
    assert correo.obtener_mensaje(mensaje_id)["categoria_id"] == cat_id

    correo.eliminar_categoria(cat_id)
    assert correo.obtener_mensaje(mensaje_id)["categoria_id"] is None


# --- Firma -----------------------------------------------------------------------

def test_preparar_cuerpo_inicial_sin_firma_configurada(monkeypatch):
    _cuenta_imap(monkeypatch, {})
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    assert correo.preparar_cuerpo_inicial(cuenta_id, es_respuesta=False) == "<p><br></p>"


def test_preparar_cuerpo_inicial_respeta_los_interruptores(monkeypatch):
    _cuenta_imap(monkeypatch, {})
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.guardar_firma(cuenta_id, "<p>-- Mi firma</p>", en_nuevos=True, en_respuestas=False)

    nuevo = correo.preparar_cuerpo_inicial(cuenta_id, es_respuesta=False)
    assert "Mi firma" in nuevo

    respuesta = correo.preparar_cuerpo_inicial(cuenta_id, es_respuesta=True, contenido_tras_firma="<p>cita</p>")
    assert "Mi firma" not in respuesta
    assert "cita" in respuesta


def test_preparar_cuerpo_inicial_ninguno_de_los_dos(monkeypatch):
    _cuenta_imap(monkeypatch, {})
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.guardar_firma(cuenta_id, "<p>-- Mi firma</p>", en_nuevos=False, en_respuestas=False)

    assert "Mi firma" not in correo.preparar_cuerpo_inicial(cuenta_id, es_respuesta=False)
    assert "Mi firma" not in correo.preparar_cuerpo_inicial(cuenta_id, es_respuesta=True)


# --- Destacar (con fecha de aviso opcional) --------------------------------------

def test_destacar_mensaje_y_quitar_destacado(monkeypatch):
    _cuenta_imap(monkeypatch, {"1": _mensaje_bytes("Hola", "a@b.com", "cuerpo")})
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.sincronizar_bandeja(cuenta_id)
    mensaje_id = correo.listar_mensajes(cuenta_id)[0]["id"]

    correo.destacar_mensaje(mensaje_id, True, fecha_aviso="2026-08-01")
    mensaje = correo.obtener_mensaje(mensaje_id)
    assert mensaje["destacado"] == 1
    assert mensaje["fecha_aviso"] == "2026-08-01"

    correo.destacar_mensaje(mensaje_id, False)
    mensaje = correo.obtener_mensaje(mensaje_id)
    assert mensaje["destacado"] == 0
    assert mensaje["fecha_aviso"] is None  # se limpia al quitar el destacado


# --- Posponer (Snooze) ------------------------------------------------------------

def test_mensaje_pospuesto_en_el_futuro_se_oculta_de_la_lista(monkeypatch):
    _cuenta_imap(monkeypatch, {"1": _mensaje_bytes("Hola", "a@b.com", "cuerpo")})
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.sincronizar_bandeja(cuenta_id)
    mensaje_id = correo.listar_mensajes(cuenta_id)[0]["id"]

    correo.posponer_mensaje(mensaje_id, "2099-01-01T00:00:00")
    assert correo.listar_mensajes(cuenta_id) == []
    assert len(correo.listar_mensajes(cuenta_id, incluir_pospuestos=True)) == 1


def test_mensaje_pospuesto_en_el_pasado_vuelve_a_verse(monkeypatch):
    _cuenta_imap(monkeypatch, {"1": _mensaje_bytes("Hola", "a@b.com", "cuerpo")})
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.sincronizar_bandeja(cuenta_id)
    mensaje_id = correo.listar_mensajes(cuenta_id)[0]["id"]

    correo.posponer_mensaje(mensaje_id, "2020-01-01T00:00:00")
    assert len(correo.listar_mensajes(cuenta_id)) == 1


def test_quitar_pospuesto():
    tid = db.crear_cuenta_correo("Prueba", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    db.guardar_mensaje_correo(
        cuenta_id=tid, uid="1", asunto="Hola", remitente="a@b.com", destinatarios="yo@ejemplo.com",
        fecha=None, cuerpo_texto="cuerpo", cuerpo_html=None,
    )
    mensaje_id = db.listar_mensajes_correo(tid)[0]["id"]
    db.posponer_mensaje_correo(mensaje_id, "2099-01-01T00:00:00")
    assert db.listar_mensajes_correo(tid) == []

    db.posponer_mensaje_correo(mensaje_id, None)
    assert len(db.listar_mensajes_correo(tid)) == 1


# --- Responder a todos -------------------------------------------------------------

def test_destinatarios_responder_a_todos_dedupe_y_excluye_la_propia_cuenta():
    mensaje = {
        "remitente": "Ana <ana@empresa.com>",
        "destinatarios": "yo@trabajo.com, Luis <luis@empresa.com>",
        "cc": "ana@empresa.com, Marta <marta@empresa.com>",
    }
    resultado = correo.destinatarios_responder_a_todos(mensaje, "yo@trabajo.com")
    assert resultado == "Ana <ana@empresa.com>, Luis <luis@empresa.com>, Marta <marta@empresa.com>"


def test_destinatarios_responder_a_todos_sin_cc():
    mensaje = {"remitente": "ana@empresa.com", "destinatarios": "yo@trabajo.com", "cc": None}
    assert correo.destinatarios_responder_a_todos(mensaje, "yo@trabajo.com") == "ana@empresa.com"


# --- Mover a otra carpeta (solo IMAP) ----------------------------------------------

def test_mover_mensaje_copia_marca_borrado_expurga_y_borra_la_fila_local(monkeypatch):
    instancia = _cuenta_imap_instancia_compartida(monkeypatch, {"1": _mensaje_bytes("Hola", "a@b.com", "cuerpo")})
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.sincronizar_bandeja(cuenta_id)
    mensaje_id = correo.listar_mensajes(cuenta_id)[0]["id"]

    correo.mover_mensaje(mensaje_id, "Archivo")

    assert instancia.copiados == [("1", '"Archivo"')]
    assert instancia.marcados == [("1", "+FLAGS", "(\\Deleted)")]
    assert instancia.expurgado is True
    assert correo.obtener_mensaje(mensaje_id) is None  # se borra de la caché local


def test_mover_mensaje_en_cuenta_pop3_lanza_error(monkeypatch):
    _cuenta_pop3(monkeypatch, [_mensaje_bytes("Hola", "a@b.com", "cuerpo")])
    cuenta_id = correo.guardar_cuenta(
        nombre="Personal", protocolo="pop3", host="pop.ejemplo.com", puerto=995,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.sincronizar_bandeja(cuenta_id)
    mensaje_id = correo.listar_mensajes(cuenta_id)[0]["id"]

    with pytest.raises(correo.ErrorCorreo):
        correo.mover_mensaje(mensaje_id, "Archivo")


def test_mover_mensaje_inexistente_lanza_error():
    with pytest.raises(correo.ErrorCorreo):
        correo.mover_mensaje(999, "Archivo")


# --- Adjuntos (Fase 5) -----------------------------------------------------

def test_sincronizar_guarda_adjuntos_reales(monkeypatch):
    crudo = _mensaje_con_adjunto_bytes(
        "Con adjunto", "a@b.com", "cuerpo", "informe.txt", b"contenido del adjunto",
    )
    _cuenta_imap(monkeypatch, {"1": crudo})
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.sincronizar_bandeja(cuenta_id)

    mensaje = correo.listar_mensajes(cuenta_id)[0]
    adjuntos = db.listar_adjuntos_correo(mensaje["id"])
    assert len(adjuntos) == 1
    assert adjuntos[0]["nombre_archivo"] == "informe.txt"
    assert adjuntos[0]["tamano_bytes"] == len(b"contenido del adjunto")

    completo = db.obtener_adjunto_correo(adjuntos[0]["id"])
    assert completo["contenido"] == b"contenido del adjunto"


def test_sincronizar_mensaje_sin_adjuntos_no_crea_filas(monkeypatch):
    _cuenta_imap(monkeypatch, {"1": _mensaje_bytes("Sin adjuntos", "a@b.com", "cuerpo")})
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.sincronizar_bandeja(cuenta_id)
    mensaje = correo.listar_mensajes(cuenta_id)[0]
    assert db.listar_adjuntos_correo(mensaje["id"]) == []


def test_eliminar_mensaje_borra_tambien_sus_adjuntos(monkeypatch):
    crudo = _mensaje_con_adjunto_bytes("Con adjunto", "a@b.com", "cuerpo", "x.txt", b"datos")
    _cuenta_imap(monkeypatch, {"1": crudo})
    cuenta_id = correo.guardar_cuenta(
        nombre="Trabajo", protocolo="imap", host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )
    correo.sincronizar_bandeja(cuenta_id)
    mensaje = correo.listar_mensajes(cuenta_id)[0]
    adjunto_id = db.listar_adjuntos_correo(mensaje["id"])[0]["id"]

    correo.eliminar_mensaje(mensaje["id"])

    assert db.obtener_adjunto_correo(adjunto_id) is None


def test_construir_y_enviar_con_adjunto(monkeypatch):
    enviados = []
    _cuenta_smtp(monkeypatch, enviados)
    cuenta_id = _crear_cuenta_con_smtp(monkeypatch)

    correo.construir_y_enviar(
        cuenta_id, "destino@ejemplo.com", "Con adjunto", "<p>Cuerpo</p>",
        adjuntos=[{"nombre": "datos.csv", "tipo": "text/csv", "bytes": b"a,b,c\n1,2,3"}],
    )

    enviado = enviados[0]
    assert enviado.is_multipart()
    adjuntos_enviados = [p for p in enviado.walk() if p.get_content_disposition() == "attachment"]
    assert len(adjuntos_enviados) == 1
    assert adjuntos_enviados[0].get_filename() == "datos.csv"
    assert adjuntos_enviados[0].get_payload(decode=True) == b"a,b,c\n1,2,3"


def test_construir_y_enviar_sin_adjuntos_no_rompe(monkeypatch):
    enviados = []
    _cuenta_smtp(monkeypatch, enviados)
    cuenta_id = _crear_cuenta_con_smtp(monkeypatch)

    correo.construir_y_enviar(cuenta_id, "destino@ejemplo.com", "Sin adjunto", "<p>Cuerpo</p>")

    assert len(enviados) == 1
