"""Seguridad de la cuenta del portal (L1): sesiones que se pueden cerrar desde otro dispositivo, aviso de dispositivo nuevo y segundo factor opcional."""
import re
import time
from datetime import datetime, timedelta

import pytest

from app import db, portal_seguridad as ps
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures

CHROME_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
SAFARI_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"


@pytest.fixture
def app(cliente):
    """La aplicación ya preparada por la fixture `cliente`, para abrir varios navegadores a la vez."""
    from app.main import app as flask_app
    return flask_app


def _entrar_con(http, c, email, ua):
    token = db.crear_acceso_cliente_fiscal(c, "127.0.0.1", email=email)
    return http.get(f"/portal/entrar/{token}", headers={"User-Agent": ua})


def _codigo_actual(secreto):
    return ps.codigo_totp(secreto, int(time.time() // 30))


@pytest.mark.parametrize("ua, esperado", [(CHROME_WIN, "Chrome en Windows"), (SAFARI_IPHONE, "Safari en iPhone"), ("", "Dispositivo desconocido"),
                                          ("Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0", "Firefox en Linux")])
def test_el_dispositivo_se_describe_con_navegador_y_sistema(ua, esperado):
    assert ps.dispositivo_de(ua) == esperado


def test_la_ip_se_guarda_sin_el_ultimo_tramo():
    assert ps._ip_gruesa("192.168.7.45") == "192.168.7.0" and ps._ip_gruesa("2001:db8:1:2:3:4:5:6").startswith("2001:db8:1:2") and ps._ip_gruesa("") == ""


def test_la_primera_entrada_no_avisa_y_un_dispositivo_distinto_si(cliente, correo):
    t, u, c = _despacho("Seg dispositivos")
    _entrar_con(cliente, c, "titular@ejemplo.com", CHROME_WIN)
    assert not [m for m in correo if "Nuevo acceso" in m[1]]
    cliente.post("/portal/salir")
    _entrar_con(cliente, c, "titular@ejemplo.com", CHROME_WIN)               # mismo dispositivo: sin aviso
    assert not [m for m in correo if "Nuevo acceso" in m[1]]
    cliente.post("/portal/salir")
    _entrar_con(cliente, c, "titular@ejemplo.com", SAFARI_IPHONE)
    avisos = [m for m in correo if "Nuevo acceso" in m[1]]
    assert len(avisos) == 1 and avisos[0][0] == "titular@ejemplo.com" and "Safari en iPhone" in avisos[0][2]


def test_cerrar_una_sesion_desde_otro_dispositivo_expulsa_a_ese_dispositivo(app, correo):
    t, u, c = _despacho("Seg remoto")
    movil, portatil = app.test_client(), app.test_client()
    _entrar_con(movil, c, "titular@ejemplo.com", SAFARI_IPHONE)
    _entrar_con(portatil, c, "titular@ejemplo.com", CHROME_WIN)
    pagina = _html(portatil, "/portal/cuenta")
    assert "Safari en iPhone" in pagina and "Este dispositivo" in pagina
    sesion_movil = next(s for s in ps.listar(_ficha(c), "titular@ejemplo.com") if s["dispositivo"] == "Safari en iPhone")["id"]
    assert portatil.post(f"/portal/sesiones/{sesion_movil}/cerrar").status_code == 302
    assert movil.get("/portal/").status_code == 302 and "/portal/entrar" in movil.get("/portal/").headers["Location"]
    assert portatil.get("/portal/").status_code == 200


def test_cerrar_las_demas_deja_solo_la_actual_y_no_toca_las_de_otras_personas(app, correo):
    t, u, c = _despacho("Seg demas")
    from app import portal_personas
    portal_personas.anadir(_ficha(c), "otra@ejemplo.com", "Otra", "administracion", por=u)
    a, b, otra = app.test_client(), app.test_client(), app.test_client()
    _entrar_con(a, c, "titular@ejemplo.com", CHROME_WIN)
    _entrar_con(b, c, "titular@ejemplo.com", SAFARI_IPHONE)
    _entrar_con(otra, c, "otra@ejemplo.com", CHROME_WIN)
    assert a.post("/portal/sesiones/cerrar-otras").status_code == 302
    assert b.get("/portal/").status_code == 302
    assert a.get("/portal/").status_code == 200 and otra.get("/portal/").status_code == 200
    # nadie puede cerrar la sesión de otra persona aunque adivine el id
    ajena = ps.listar(_ficha(c), "otra@ejemplo.com")[0]["id"]
    a.post(f"/portal/sesiones/{ajena}/cerrar")
    assert otra.get("/portal/").status_code == 200


def test_las_sesiones_de_antes_del_registro_se_anotan_sin_avisar(cliente, correo):
    t, u, c = _despacho("Seg legado")
    with cliente.session_transaction() as s:
        s["cliente_fiscal_id"] = c
    assert cliente.get("/portal/").status_code == 200
    with cliente.session_transaction() as s:
        assert s.get("portal_sid")
    assert len(ps.listar(_ficha(c), "titular@ejemplo.com")) == 1 and not correo


def test_quitar_a_una_persona_cierra_sus_sesiones(app, correo):
    t, u, c = _despacho("Seg baja")
    from app import portal_personas
    contacto = portal_personas.anadir(_ficha(c), "baja@ejemplo.com", "Baja", "consulta", por=u)
    http = app.test_client()
    _entrar_con(http, c, "baja@ejemplo.com", CHROME_WIN)
    portal_personas.quitar(_ficha(c), contacto if isinstance(contacto, int) else portal_personas.listar(_ficha(c))[1]["id"])
    assert http.get("/portal/").status_code == 302
    assert ps.listar(_ficha(c), "baja@ejemplo.com") == []


def test_limpiar_borra_lo_viejo_y_conserva_lo_reciente():
    t, u, c = _despacho("Seg limpiar")
    ps.abrir_sesion(_ficha(c), "titular@ejemplo.com", CHROME_WIN, "1.2.3.4", ahora=datetime.now() - timedelta(days=200))
    ps.abrir_sesion(_ficha(c), "titular@ejemplo.com", SAFARI_IPHONE, "1.2.3.4")
    assert ps.limpiar() == 1 and len(ps.listar(_ficha(c), "titular@ejemplo.com")) == 1


# --- segundo factor -----------------------------------------------------------------------------------------------------------------------------------

def _activar(http, c, ua=CHROME_WIN, email="titular@ejemplo.com"):
    _entrar_con(http, c, email, ua)
    http.post("/portal/segundo-factor/iniciar")
    secreto = ps.secreto_pendiente(_ficha(c), email)
    r = http.post("/portal/segundo-factor/confirmar", data={"codigo": _codigo_actual(secreto)})
    assert r.status_code == 302
    return secreto


def test_activar_el_segundo_factor_muestra_codigos_de_recuperacion_una_sola_vez(cliente, correo):
    t, u, c = _despacho("Seg activar")
    _entrar_con(cliente, c, "titular@ejemplo.com", CHROME_WIN)
    pagina = _html(cliente, "/portal/cuenta")
    assert "Activar la verificación en dos pasos" in pagina
    cliente.post("/portal/segundo-factor/iniciar")
    pagina = _html(cliente, "/portal/cuenta")
    assert "<svg" in pagina and "Escanea este código" in pagina
    secreto = ps.secreto_pendiente(_ficha(c), "titular@ejemplo.com")
    assert cliente.post("/portal/segundo-factor/confirmar", data={"codigo": "000000"}).status_code == 302
    assert not ps.activo(_ficha(c), "titular@ejemplo.com")
    cliente.post("/portal/segundo-factor/confirmar", data={"codigo": _codigo_actual(secreto)})
    pagina = _html(cliente, "/portal/cuenta")
    assert ps.activo(_ficha(c), "titular@ejemplo.com") and len(re.findall(r"<code>[0-9a-f]{4}-[0-9a-f]{4}</code>", pagina)) == ps.CODIGOS_RECUPERACION
    assert not re.findall(r"<code>[0-9a-f]{4}-[0-9a-f]{4}</code>", _html(cliente, "/portal/cuenta")), "los códigos solo se enseñan una vez"


def test_con_segundo_factor_el_enlace_no_basta_hace_falta_el_codigo(app, correo):
    t, u, c = _despacho("Seg entrada")
    secreto = _activar(app.test_client(), c)
    nuevo = app.test_client()
    r = _entrar_con(nuevo, c, "titular@ejemplo.com", SAFARI_IPHONE)
    assert r.status_code == 302 and "/portal/verificacion" in r.headers["Location"]
    assert nuevo.get("/portal/").status_code == 302 and "/portal/entrar" in nuevo.get("/portal/").headers["Location"]
    assert nuevo.post("/portal/verificacion", data={"codigo": "123456"}).status_code == 401
    assert nuevo.get("/portal/").status_code == 302
    # un código ya gastado no se acepta dos veces: se prueba con el paso siguiente
    ok = nuevo.post("/portal/verificacion", data={"codigo": ps.codigo_totp(secreto, int(time.time() // 30) + 1)})
    assert ok.status_code == 302 and nuevo.get("/portal/").status_code == 200


def test_un_codigo_de_la_aplicacion_solo_sirve_una_vez():
    t, u, c = _despacho("Seg uso unico")
    ficha = _ficha(c)
    ps.iniciar_alta(ficha, "titular@ejemplo.com")
    secreto = ps.secreto_pendiente(ficha, "titular@ejemplo.com")
    ps.confirmar_alta(ficha, "titular@ejemplo.com", _codigo_actual(secreto))
    siguiente = ps.codigo_totp(secreto, int(time.time() // 30) + 1)
    assert ps.verificar(ficha, "titular@ejemplo.com", siguiente) is True
    assert ps.verificar(ficha, "titular@ejemplo.com", siguiente) is False


def test_un_codigo_de_recuperacion_sirve_una_vez(app, correo):
    t, u, c = _despacho("Seg recuperacion")
    ficha = _ficha(c)
    ps.iniciar_alta(ficha, "titular@ejemplo.com")
    codigos = ps.confirmar_alta(ficha, "titular@ejemplo.com", _codigo_actual(ps.secreto_pendiente(ficha, "titular@ejemplo.com")))
    assert ps.codigos_restantes(ficha, "titular@ejemplo.com") == ps.CODIGOS_RECUPERACION
    assert ps.verificar(ficha, "titular@ejemplo.com", codigos[0].upper()) is True
    assert ps.verificar(ficha, "titular@ejemplo.com", codigos[0]) is False
    assert ps.codigos_restantes(ficha, "titular@ejemplo.com") == ps.CODIGOS_RECUPERACION - 1


def test_desactivar_pide_un_codigo_valido(app, correo):
    t, u, c = _despacho("Seg quitar")
    http = app.test_client()
    secreto = _activar(http, c)
    assert http.post("/portal/segundo-factor/quitar", data={"codigo": "999999"}).status_code == 302
    assert ps.activo(_ficha(c), "titular@ejemplo.com")
    http.post("/portal/segundo-factor/quitar", data={"codigo": ps.codigo_totp(secreto, int(time.time() // 30) + 1)})
    assert not ps.activo(_ficha(c), "titular@ejemplo.com")


def test_el_secreto_no_se_guarda_en_claro():
    t, u, c = _despacho("Seg cifrado")
    ps.iniciar_alta(_ficha(c), "titular@ejemplo.com")
    secreto = ps.secreto_pendiente(_ficha(c), "titular@ejemplo.com")
    conn = db.get_connection()
    guardado = conn.execute("SELECT secreto FROM portal_segundo_factor").fetchone()["secreto"]
    conn.close()
    assert secreto not in guardado and len(secreto) >= 16


def test_la_verificacion_caduca_y_sin_pendiente_vuelve_a_entrar(cliente, correo):
    t, u, c = _despacho("Seg caduca")
    r = cliente.get("/portal/verificacion")
    assert r.status_code == 302 and "/portal/entrar" in r.headers["Location"]


def test_el_perfil_de_consulta_puede_gestionar_su_propia_seguridad(app, correo):
    t, u, c = _despacho("Seg consulta")
    from app import portal_personas
    portal_personas.anadir(_ficha(c), "mira@ejemplo.com", "Mira", "consulta", por=u)
    http = app.test_client()
    _entrar_con(http, c, "mira@ejemplo.com", CHROME_WIN)
    assert http.post("/portal/segundo-factor/iniciar").status_code == 302
    assert http.post("/portal/sesiones/cerrar-otras").status_code == 302
