"""OAuth2 de correo (Gmail / Microsoft 365): URL con PKCE, canje, renovación, XOAUTH2 y el flujo web.
El proveedor se sustituye por una función; la conexión IMAP por un servidor falso."""
import base64
import json
import urllib.parse

import keyring
import pytest

from app import correo, correo_oauth, db
from tests.conftest import iniciar_sesion_de_prueba


def _jwt(carga: dict) -> str:
    cuerpo = base64.urlsafe_b64encode(json.dumps(carga).encode()).rstrip(b"=").decode()
    return f"x.{cuerpo}.y"


@pytest.fixture(autouse=True)
def configurado(monkeypatch):
    for p in ("GOOGLE", "MICROSOFT"):
        monkeypatch.setenv(f"GUILDA_OAUTH_{p}_CLIENT_ID", f"id-{p}")
        monkeypatch.setenv(f"GUILDA_OAUTH_{p}_CLIENT_SECRET", f"secreto-{p}")
    correo_oauth._cache.clear()
    guardado = {}
    monkeypatch.setattr(keyring, "set_password", lambda s, k, v: guardado.__setitem__((s, k), v))
    monkeypatch.setattr(keyring, "get_password", lambda s, k: guardado.get((s, k)))
    monkeypatch.setattr(keyring, "delete_password", lambda s, k: guardado.pop((s, k), None))
    return guardado


class Proveedor:
    """Sustituye a _post_form y anota las peticiones."""

    def __init__(self, monkeypatch):
        self.peticiones = []
        self.respuestas = []
        monkeypatch.setattr(correo_oauth, "_post_form", self)

    def __call__(self, url, datos):
        self.peticiones.append((url, datos))
        return self.respuestas.pop(0)


def test_disponibilidad_segun_entorno(monkeypatch):
    assert [p["clave"] for p in correo_oauth.proveedores_disponibles()] == ["google", "microsoft"]
    monkeypatch.delenv("GUILDA_OAUTH_MICROSOFT_CLIENT_SECRET")
    assert correo_oauth.disponible("google") and not correo_oauth.disponible("microsoft") and not correo_oauth.disponible("otro")


def test_url_de_autorizacion_con_pkce_y_pistas():
    verificador, desafio = correo_oauth.nuevo_pkce()
    assert len(verificador) >= 43 and "=" not in desafio
    url = correo_oauth.url_autorizacion("google", "https://x/cb", "estado1", desafio, "ana@gmail.com")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert url.startswith("https://accounts.google.com/") and q["code_challenge_method"] == ["S256"] and q["code_challenge"] == [desafio]
    assert q["access_type"] == ["offline"] and "https://mail.google.com/" in q["scope"][0] and q["login_hint"] == ["ana@gmail.com"] and q["state"] == ["estado1"]
    ms = correo_oauth.url_autorizacion("microsoft", "https://x/cb", "e", desafio)
    assert "/common/oauth2/v2.0/authorize" in ms and "IMAP.AccessAsUser.All" in ms and "offline_access" in ms
    with pytest.raises(correo_oauth.ErrorOAuth):
        correo_oauth.url_autorizacion("microsoft" if False else "inventado", "u", "e", desafio)


def test_tenant_de_microsoft_configurable(monkeypatch):
    monkeypatch.setenv("GUILDA_OAUTH_MICROSOFT_TENANT", "mi-despacho.onmicrosoft.com")
    assert "/mi-despacho.onmicrosoft.com/oauth2" in correo_oauth.url_autorizacion("microsoft", "u", "e", "d")


def test_canjear_codigo(monkeypatch):
    p = Proveedor(monkeypatch)
    p.respuestas = [(200, {"access_token": "AT", "refresh_token": "RT", "expires_in": 3599, "id_token": _jwt({"email": "Ana@Gmail.com"})})]
    r = correo_oauth.canjear_codigo("google", "codigo", "https://x/cb", "verif")
    assert r == {"refresh_token": "RT", "access_token": "AT", "expira_en": 3599, "email": "ana@gmail.com"}
    url, datos = p.peticiones[0]
    assert url == "https://oauth2.googleapis.com/token" and datos["code_verifier"] == "verif" and datos["client_secret"] == "secreto-GOOGLE"
    # Microsoft: el correo puede venir en preferred_username
    p.respuestas = [(200, {"access_token": "AT", "refresh_token": "RT", "id_token": _jwt({"preferred_username": "luis@empresa.com"})})]
    assert correo_oauth.canjear_codigo("microsoft", "c", "u", "v")["email"] == "luis@empresa.com"


@pytest.mark.parametrize("respuesta,texto", [
    ((400, {"error": "invalid_grant"}), "no ha aceptado"),
    ((200, {"access_token": "AT", "id_token": _jwt({"email": "a@b.c"})}), "acceso permanente"),         # sin refresh_token
    ((200, {"access_token": "AT", "refresh_token": "RT", "id_token": "basura"}), "dirección de correo"),
    ((200, {"access_token": "AT", "refresh_token": "RT", "id_token": _jwt({"email": "sin-arroba"})}), "dirección de correo"),
])
def test_canje_con_problemas(monkeypatch, respuesta, texto):
    Proveedor(monkeypatch).respuestas = [respuesta]
    with pytest.raises(correo_oauth.ErrorOAuth, match=texto):
        correo_oauth.canjear_codigo("google", "c", "u", "v")


def test_token_de_acceso_se_renueva_se_cachea_y_rota_el_refresh(monkeypatch, configurado):
    p = Proveedor(monkeypatch)
    correo_oauth.guardar_refresh_token(5, "RT1")
    p.respuestas = [(200, {"access_token": "A1", "expires_in": 3600, "refresh_token": "RT2"})]
    t = correo_oauth.token_de_acceso(5, "microsoft", "imap")
    assert t == "A1" and isinstance(t, correo_oauth.TokenOAuth) and configurado[("guilda-work-correo", "cuenta-5")] == "RT2"
    assert correo_oauth.token_de_acceso(5, "microsoft", "imap") == "A1" and len(p.peticiones) == 1          # de la caché
    assert "IMAP.AccessAsUser.All" in p.peticiones[0][1]["scope"]
    p.respuestas = [(200, {"access_token": "S1", "expires_in": 3600})]
    assert correo_oauth.token_de_acceso(5, "microsoft", "smtp") == "S1" and "SMTP.Send" in p.peticiones[1][1]["scope"]
    # caducado: vuelve a pedir
    correo_oauth._cache[(5, "imap")] = ("viejo", 0)
    p.respuestas = [(200, {"access_token": "A2", "expires_in": 3600})]
    assert correo_oauth.token_de_acceso(5, "microsoft", "imap") == "A2"


def test_autorizacion_revocada_o_perdida(monkeypatch):
    p = Proveedor(monkeypatch)
    with pytest.raises(correo_oauth.ErrorOAuth, match="Vuelve a conectarla"):
        correo_oauth.token_de_acceso(9, "google")                                    # sin token guardado
    correo_oauth.guardar_refresh_token(9, "RT")
    p.respuestas = [(400, {"error": "invalid_grant"})]
    with pytest.raises(correo_oauth.ErrorOAuth, match="caducado o se ha revocado"):
        correo_oauth.token_de_acceso(9, "google")
    p.respuestas = [(503, {})]
    with pytest.raises(correo_oauth.ErrorOAuth, match="Se reintentará"):             # caída del proveedor: no es lo mismo que revocado
        correo_oauth.token_de_acceso(9, "google")


def test_cadena_xoauth2():
    assert correo_oauth.cadena_xoauth2("a@b.c", "TOK") == "user=a@b.c\x01auth=Bearer TOK\x01\x01"


# --- conexión con XOAUTH2 -----------------------------------------------------------------

class ImapFalso:
    def __init__(self):
        self.autenticaciones = []

    def authenticate(self, mecanismo, funcion):
        self.autenticaciones.append((mecanismo, funcion(b"")))

    def login(self, *a):
        raise AssertionError("no debe usarse la contraseña")

    def logout(self):
        pass


def test_imap_usa_xoauth2_con_token_y_login_con_contrasena(monkeypatch):
    fake = ImapFalso()
    monkeypatch.setattr(correo.imaplib, "IMAP4_SSL", lambda *a, **k: fake)
    correo._conectar_imap("h", 993, True, "ana@gmail.com", correo_oauth.TokenOAuth("TOK"))
    assert fake.autenticaciones == [("XOAUTH2", b"user=ana@gmail.com\x01auth=Bearer TOK\x01\x01")]

    class Normal(ImapFalso):
        def login(self, u, c):
            self.entro = (u, c)
    n = Normal()
    monkeypatch.setattr(correo.imaplib, "IMAP4_SSL", lambda *a, **k: n)
    correo._conectar_imap("h", 993, True, "u", "clave")
    assert n.entro == ("u", "clave") and n.autenticaciones == []


def test_smtp_usa_xoauth2(monkeypatch):
    llamadas = []

    class SmtpFalso:
        def __init__(self, *a, **k): pass
        def starttls(self): llamadas.append("starttls")
        def ehlo_or_helo_if_needed(self): llamadas.append("ehlo")
        def auth(self, mecanismo, funcion): llamadas.append((mecanismo, funcion()))
        def login(self, *a): raise AssertionError("no debe usarse la contraseña")

    monkeypatch.setattr(correo.smtplib, "SMTP", SmtpFalso)
    correo._conectar_smtp("smtp.gmail.com", 587, True, "ana@gmail.com", correo_oauth.TokenOAuth("TOK"))
    assert llamadas == ["starttls", "ehlo", ("XOAUTH2", "user=ana@gmail.com\x01auth=Bearer TOK\x01\x01")]


# --- flujo web ----------------------------------------------------------------------------

def test_flujo_completo_crea_la_cuenta_oauth(cliente, monkeypatch, configurado):
    uid = iniciar_sesion_de_prueba(cliente, "oa-1@x.com", "contrasena123")
    assert "Conectar Gmail" in cliente.get("/correo/cuentas").get_data(as_text=True)
    r = cliente.get("/correo/oauth/google/iniciar", query_string={"nombre": "Mi Gmail"})
    assert r.status_code == 302 and r.headers["Location"].startswith("https://accounts.google.com/")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["Location"]).query)
    estado = q["state"][0]
    Proveedor(monkeypatch).respuestas = [(200, {"access_token": "AT", "refresh_token": "RT", "id_token": _jwt({"email": "ana@gmail.com"})})]
    fake = ImapFalso()
    monkeypatch.setattr(correo.imaplib, "IMAP4_SSL", lambda *a, **k: fake)
    r = cliente.get("/correo/oauth/google/callback", query_string={"state": estado, "code": "abc"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/correo/cuentas")
    cuentas = db.listar_cuentas_correo(uid)
    assert len(cuentas) == 1
    c = cuentas[0]
    assert (c["nombre"], c["usuario"], c["host"], c["smtp_host"], c["auth_tipo"]) == ("Mi Gmail", "ana@gmail.com", "imap.gmail.com", "smtp.gmail.com", "google")
    assert configurado[("guilda-work-correo", f"cuenta-{c['id']}")] == "RT" and fake.autenticaciones
    html = cliente.get("/correo/cuentas").get_data(as_text=True)
    assert "OAuth2" in html and "Reconectar" in html
    # reconectar la misma dirección no duplica la cuenta y renueva el token
    cliente.get("/correo/oauth/google/iniciar")
    estado2 = cliente.get("/correo/oauth/google/iniciar").headers["Location"].split("state=")[1].split("&")[0]
    Proveedor(monkeypatch).respuestas = [(200, {"access_token": "AT2", "refresh_token": "RT2", "id_token": _jwt({"email": "ana@gmail.com"})})]
    cliente.get("/correo/oauth/google/callback", query_string={"state": estado2, "code": "def"})
    assert len(db.listar_cuentas_correo(uid)) == 1 and configurado[("guilda-work-correo", f"cuenta-{c['id']}")] == "RT2"


def test_el_callback_rechaza_estado_malo_errores_y_proveedores_sin_configurar(cliente, monkeypatch):
    iniciar_sesion_de_prueba(cliente, "oa-2@x.com", "contrasena123")
    assert "no es válida" in cliente.get("/correo/oauth/google/callback", query_string={"state": "x", "code": "c"}).get_data(as_text=True)       # sin inicio previo
    cliente.get("/correo/oauth/google/iniciar")
    assert "no es válida" in cliente.get("/correo/oauth/google/callback", query_string={"state": "falso", "code": "c"}).get_data(as_text=True)
    estado = cliente.get("/correo/oauth/google/iniciar").headers["Location"].split("state=")[1].split("&")[0]
    assert "No se ha concedido" in cliente.get("/correo/oauth/google/callback", query_string={"state": estado, "error": "access_denied"}).get_data(as_text=True)
    monkeypatch.delenv("GUILDA_OAUTH_GOOGLE_CLIENT_ID")
    assert cliente.get("/correo/oauth/google/iniciar").status_code == 404
    assert cliente.get("/correo/oauth/otro/iniciar").status_code == 404
    assert "Conectar Gmail" not in cliente.get("/correo/cuentas").get_data(as_text=True)


def test_sincronizar_cuenta_oauth_usa_el_token(cliente, monkeypatch):
    uid = iniciar_sesion_de_prueba(cliente, "oa-3@x.com", "contrasena123")
    cuenta = db.crear_cuenta_correo(uid, "G", "imap", "imap.gmail.com", 993, "ana@gmail.com", auth_tipo="google")
    correo_oauth.guardar_refresh_token(cuenta, "RT")
    Proveedor(monkeypatch).respuestas = [(200, {"access_token": "AT", "expires_in": 3600})]
    fake = ImapFalso()
    monkeypatch.setattr(correo.imaplib, "IMAP4_SSL", lambda *a, **k: fake)
    conn = correo._conectar_imap_cuenta(db.obtener_cuenta_correo(uid, cuenta))
    assert conn is fake and fake.autenticaciones[0][1] == b"user=ana@gmail.com\x01auth=Bearer AT\x01\x01"
    # al borrar la cuenta se limpia la caché
    correo.eliminar_cuenta(uid, cuenta)
    assert (cuenta, "imap") not in correo_oauth._cache


def test_token_revocado_en_sincronizacion_da_un_error_legible(cliente, monkeypatch):
    uid = iniciar_sesion_de_prueba(cliente, "oa-4@x.com", "contrasena123")
    cuenta = db.crear_cuenta_correo(uid, "G", "imap", "imap.gmail.com", 993, "ana@gmail.com", auth_tipo="google")
    correo_oauth.guardar_refresh_token(cuenta, "RT")
    Proveedor(monkeypatch).respuestas = [(400, {"error": "invalid_grant"})]
    with pytest.raises(correo.ErrorCorreo, match="caducado o se ha revocado"):
        correo.sincronizar_bandeja(uid, cuenta)


def test_db_rechaza_un_tipo_de_autenticacion_desconocido():
    uid = db.crear_usuario("oa-5@x.com", "contrasena123")
    with pytest.raises(ValueError):
        db.crear_cuenta_correo(uid, "x", "imap", "h", 993, "u", auth_tipo="otro")
