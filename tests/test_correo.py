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


class FakeIMAP:
    def __init__(self, mensajes: dict[str, bytes], contrasena_valida: str = "correcta"):
        self._mensajes = mensajes
        self._contrasena_valida = contrasena_valida

    def login(self, usuario, contrasena):
        if contrasena != self._contrasena_valida:
            raise imaplib.IMAP4.error("credenciales inválidas")
        return "OK", [b"Logged in"]

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
        raise AssertionError(f"comando IMAP inesperado: {comando}")

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


def _cuenta_imap(monkeypatch, mensajes: dict[str, bytes], contrasena_valida: str = "correcta") -> None:
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda host, port, timeout=None: FakeIMAP(mensajes, contrasena_valida))


def _cuenta_pop3(monkeypatch, mensajes: list[bytes], contrasena_valida: str = "correcta") -> None:
    monkeypatch.setattr(poplib, "POP3_SSL", lambda host, port, timeout=None: FakePOP3(mensajes, contrasena_valida))


class FakeSMTP:
    ultimo_mensaje = None

    def __init__(self, mensajes_enviados: list, contrasena_valida: str = "correcta"):
        self._mensajes_enviados = mensajes_enviados
        self._contrasena_valida = contrasena_valida

    def starttls(self):
        pass

    def login(self, usuario, contrasena):
        if contrasena != self._contrasena_valida:
            raise smtplib.SMTPAuthenticationError(535, b"credenciales invalidas")

    def send_message(self, mensaje):
        self._mensajes_enviados.append(mensaje)

    def quit(self):
        pass


def _cuenta_smtp(monkeypatch, mensajes_enviados: list, contrasena_valida: str = "correcta") -> None:
    monkeypatch.setattr(smtplib, "SMTP", lambda host, port, timeout=None: FakeSMTP(mensajes_enviados, contrasena_valida))
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda host, port, timeout=None: FakeSMTP(mensajes_enviados, contrasena_valida))


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

def test_construir_y_enviar_manda_el_mensaje_con_los_campos_correctos(monkeypatch):
    enviados = []
    _cuenta_smtp(monkeypatch, enviados)
    cuenta_id = _crear_cuenta_con_smtp(monkeypatch)

    correo.construir_y_enviar(cuenta_id, "destino@ejemplo.com", "Asunto de prueba", "Cuerpo del mensaje.")

    assert len(enviados) == 1
    enviado = enviados[0]
    assert enviado["To"] == "destino@ejemplo.com"
    assert enviado["Subject"] == "Asunto de prueba"
    assert enviado["From"] == "yo@ejemplo.com"
    assert enviado.get_content().strip() == "Cuerpo del mensaje."


def test_construir_y_enviar_respuesta_incluye_in_reply_to(monkeypatch):
    enviados = []
    _cuenta_smtp(monkeypatch, enviados)
    cuenta_id = _crear_cuenta_con_smtp(monkeypatch)

    correo.construir_y_enviar(
        cuenta_id, "destino@ejemplo.com", "Re: Hola", "Respuesta.",
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
        correo.construir_y_enviar(cuenta_id, "destino@ejemplo.com", "Asunto", "Cuerpo")


def test_construir_y_enviar_sin_destinatarios_lanza_error(monkeypatch):
    enviados = []
    _cuenta_smtp(monkeypatch, enviados)
    cuenta_id = _crear_cuenta_con_smtp(monkeypatch)
    with pytest.raises(correo.ErrorCorreo):
        correo.construir_y_enviar(cuenta_id, "", "Asunto", "Cuerpo")
    assert enviados == []


def test_construir_y_enviar_credenciales_invalidas_lanza_error(monkeypatch):
    enviados = []
    _cuenta_smtp(monkeypatch, enviados, contrasena_valida="otra-cosa")
    cuenta_id = _crear_cuenta_con_smtp(monkeypatch)
    with pytest.raises(correo.ErrorCorreo):
        correo.construir_y_enviar(cuenta_id, "destino@ejemplo.com", "Asunto", "Cuerpo")
    assert enviados == []


def test_construir_y_enviar_cuenta_inexistente_lanza_error():
    with pytest.raises(correo.ErrorCorreo):
        correo.construir_y_enviar(999, "destino@ejemplo.com", "Asunto", "Cuerpo")
