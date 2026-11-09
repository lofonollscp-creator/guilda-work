"""Passkeys del portal (C1): alta desde Mi cuenta, entrada sin correo, baja, y todo lo que no debe colarse (otro origen, otro desafío, passkey de alguien sin acceso, sin verificación de usuario)."""
import pytest

pytest.importorskip("webauthn")

from app import db, portal_passkeys as pk, portal_personas
from tests.passkeys_ayudas import Autenticador
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures


def _json(r):
    return r.get_json()


def _registrar(http, auth, nombre="Mi móvil"):
    opciones = _json(http.post("/portal/passkey/registro/opciones"))
    return http.post("/portal/passkey/registro/verificar", json={"nombre": nombre, "credencial": auth.crear(opciones)})


def test_se_registra_una_passkey_desde_mi_cuenta_y_aparece_en_la_lista(cliente, correo):
    t, u, c = _despacho("Passkey alta")
    _entrar(cliente, c, "titular@ejemplo.com")
    r = _registrar(cliente, Autenticador())
    assert r.status_code == 200 and _json(r) == {"ok": True}
    html = _html(cliente, "/portal/cuenta")
    assert "Mi móvil" in html and "data-passkey-alta" in html and "Todavía no tienes ninguna passkey" not in html


def test_entrar_con_la_passkey_abre_la_sesion_sin_pedir_el_enlace_ni_el_segundo_factor(cliente, correo):
    t, u, c = _despacho("Passkey entrar")
    _entrar(cliente, c, "titular@ejemplo.com")
    auth = Autenticador()
    _registrar(cliente, auth)
    cliente.post("/portal/salir")
    assert cliente.get("/portal/").status_code in (302, 308, 401, 200) and "Mi móvil" not in _html(cliente, "/portal/entrar")
    opciones = _json(cliente.post("/portal/passkey/entrar/opciones"))
    r = cliente.post("/portal/passkey/entrar/verificar", json={"credencial": auth.firmar(opciones)})
    assert r.status_code == 200 and _json(r)["ok"] is True and _json(r)["url"] == "/portal/"
    assert "Para hacer" in _html(cliente, "/portal/")


def test_un_desafio_solo_vale_una_vez_y_un_origen_distinto_se_rechaza(cliente, correo):
    t, u, c = _despacho("Passkey replay")
    _entrar(cliente, c, "titular@ejemplo.com")
    auth = Autenticador()
    _registrar(cliente, auth)
    cliente.post("/portal/salir")
    opciones = _json(cliente.post("/portal/passkey/entrar/opciones"))
    firma = auth.firmar(opciones)
    assert cliente.post("/portal/passkey/entrar/verificar", json={"credencial": firma}).status_code == 200
    cliente.post("/portal/salir")
    assert cliente.post("/portal/passkey/entrar/verificar", json={"credencial": firma}).status_code == 400            # sin desafío nuevo
    opciones = _json(cliente.post("/portal/passkey/entrar/opciones"))
    r = cliente.post("/portal/passkey/entrar/verificar", json={"credencial": auth.firmar(opciones, origen="https://phishing.example")})
    assert r.status_code == 400 and cliente.get("/portal/").status_code == 302


def test_una_passkey_sin_verificacion_de_usuario_no_vale(cliente, correo):
    t, u, c = _despacho("Passkey sin uv")
    _entrar(cliente, c, "titular@ejemplo.com")
    r = _registrar(cliente, Autenticador(verificacion=False))
    assert r.status_code == 400 and pk.listar(_ficha(c), "titular@ejemplo.com") == []


def test_una_passkey_desconocida_o_de_quien_ya_no_tiene_acceso_se_rechaza(cliente, correo):
    t, u, c = _despacho("Passkey sin acceso")
    ficha = _ficha(c)
    portal_personas.anadir(ficha, "temporal@ejemplo.com", "Temporal", "administracion", por=u)
    cliente.post("/portal/salir")
    _entrar(cliente, c, "temporal@ejemplo.com")
    auth = Autenticador()
    _registrar(cliente, auth)
    cliente.post("/portal/salir")
    opciones = _json(cliente.post("/portal/passkey/entrar/opciones"))
    assert cliente.post("/portal/passkey/entrar/verificar", json={"credencial": Autenticador().firmar(opciones)}).status_code == 400        # nunca registrada
    contacto = next(p for p in portal_personas.listar(ficha) if p["email"] == "temporal@ejemplo.com")
    portal_personas.quitar(ficha, contacto["id"])
    assert pk.listar(ficha, "temporal@ejemplo.com") == []                                                                                  # al quitarla, sus passkeys se van con ella
    opciones = _json(cliente.post("/portal/passkey/entrar/opciones"))
    assert cliente.post("/portal/passkey/entrar/verificar", json={"credencial": auth.firmar(opciones)}).status_code == 400


def test_se_puede_quitar_y_solo_las_propias(cliente, correo):
    t, u, c = _despacho("Passkey quitar")
    _entrar(cliente, c, "titular@ejemplo.com")
    _registrar(cliente, Autenticador())
    ficha = _ficha(c)
    pid = pk.listar(ficha, "titular@ejemplo.com")[0]["id"]
    assert cliente.post(f"/portal/passkey/{pid + 999}/quitar").status_code == 302 and len(pk.listar(ficha, "titular@ejemplo.com")) == 1
    cliente.post(f"/portal/passkey/{pid}/quitar")
    assert pk.listar(ficha, "titular@ejemplo.com") == []


def test_el_contador_avanza_y_no_se_admite_una_credencial_clonada(cliente, correo):
    t, u, c = _despacho("Passkey contador")
    _entrar(cliente, c, "titular@ejemplo.com")
    auth = Autenticador()
    _registrar(cliente, auth)
    cliente.post("/portal/salir")
    for _ in range(2):
        opciones = _json(cliente.post("/portal/passkey/entrar/opciones"))
        assert cliente.post("/portal/passkey/entrar/verificar", json={"credencial": auth.firmar(opciones)}).status_code == 200
        cliente.post("/portal/salir")
    auth.contador = 0                                                                                  # un clon que empieza de cero
    opciones = _json(cliente.post("/portal/passkey/entrar/opciones"))
    assert cliente.post("/portal/passkey/entrar/verificar", json={"credencial": auth.firmar(opciones)}).status_code == 400


def test_la_pantalla_de_entrada_ofrece_el_boton(cliente, correo):
    assert "data-passkey-entrar" in _html(cliente, "/portal/entrar")
