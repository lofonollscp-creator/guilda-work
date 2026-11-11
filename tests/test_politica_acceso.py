"""Política de acceso del despacho (Y8): exigir segundo factor o passkey con fecha límite, sin bloqueos bruscos y sin dejar fuera a nadie si Kratos falla."""
from datetime import date, timedelta

import pytest

from app import db, kratos, politica_acceso
from tests.conftest import iniciar_sesion_de_prueba

HOY = date(2026, 11, 11)


@pytest.fixture
def creds(monkeypatch):
    """Los métodos de acceso de cada identidad, simulados: `creds.por[identity_id] = {...}` o None (Kratos caído)."""
    class C:
        por: dict = {}
    c = C()
    monkeypatch.setattr(kratos, "credenciales_de", lambda ident: c.por[ident])
    politica_acceso._CACHE.clear()
    yield c
    politica_acceso._CACHE.clear()


def _ident(u):
    return db.obtener_usuario(u)["kratos_identity_id"]


def _usuario(t, email, ident, supervisor=False):
    """Una persona del despacho sin sesión (identidad inventada)."""
    u = db.crear_usuario_vinculado_a_kratos(email, ident)
    db.asignar_tenant(u, t)
    db.asignar_supervisor_tenant(u, supervisor)
    return u


def _con_sesion(cliente, t, email, supervisor=False):
    """Una persona del despacho que inicia sesión de verdad (la identidad la crea Kratos)."""
    u = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    db.asignar_tenant(u, t)
    db.asignar_supervisor_tenant(u, supervisor)
    return u


def test_fijar_exige_fecha_con_margen_y_se_puede_quitar():
    t = db.crear_tenant("Política margen")
    with pytest.raises(ValueError):
        politica_acceso.fijar(t, 1, True, "", hoy=HOY)                                                     # sin fecha
    with pytest.raises(ValueError):
        politica_acceso.fijar(t, 1, True, (HOY + timedelta(days=3)).isoformat(), hoy=HOY)                  # sin margen: sería un bloqueo brusco
    politica_acceso.fijar(t, 1, True, (HOY + timedelta(days=10)).isoformat(), hoy=HOY)
    assert politica_acceso.obtener(t) == {"exigir": True, "limite": (HOY + timedelta(days=10)).isoformat()}
    politica_acceso.fijar(t, 1, False, None, hoy=HOY)
    assert politica_acceso.obtener(t) == {"exigir": False, "limite": None}


def test_quien_cumple_no_ve_nada_y_quien_no_cumple_ve_los_dias_y_despues_queda_vencida(creds):
    t = db.crear_tenant("Política avisos")
    sin, totp, llave, caido = (_usuario(t, f"{n}@ejemplo.com", f"id-{n}") for n in ("sin", "totp", "llave", "caido"))
    creds.por = {"id-sin": {"password"}, "id-totp": {"password", "totp"}, "id-llave": {"passkey"}, "id-caido": None}
    assert politica_acceso.pendiente(sin, t, HOY) is None                                                  # política desactivada
    politica_acceso.fijar(t, sin, True, (HOY + timedelta(days=10)).isoformat(), hoy=HOY)
    assert politica_acceso.pendiente(sin, t, HOY) == {"limite": (HOY + timedelta(days=10)).isoformat(), "dias": 10, "vencida": False}
    assert politica_acceso.pendiente(totp, t, HOY) is None and politica_acceso.pendiente(llave, t, HOY) is None
    assert politica_acceso.pendiente(caido, t, HOY) is None                                                # Kratos caído: se da por cumplida
    assert politica_acceso.pendiente(sin, t, HOY + timedelta(days=11))["vencida"] is True
    assert politica_acceso.incumplen(t) == [sin]


def test_pasada_la_fecha_solo_se_puede_ir_a_activarlo_y_el_aviso_sale_antes(cliente, creds):
    t = db.crear_tenant("Política bloqueo")
    u = _con_sesion(cliente, t, "bloqueo@ejemplo.com")
    creds.por = {_ident(u): {"password"}}
    politica_acceso.fijar(t, u, True, (date.today() + timedelta(days=10)).isoformat())
    politica_acceso._CACHE.clear()
    html = cliente.get("/").get_data(as_text=True)
    assert "Tu despacho exige verificación en dos pasos o una passkey" in html and "Te quedan 10 días" in html   # el aviso, sin bloqueo
    conn = db.get_connection()
    conn.execute("UPDATE tenants SET segundo_factor_limite = ? WHERE id = ?", ((date.today() - timedelta(days=1)).isoformat(), t))
    conn.commit(); conn.close()
    politica_acceso._CACHE.clear()
    r = cliente.get("/tareas")
    assert r.status_code == 302 and "/ajustes/cuenta" in r.headers["Location"]                              # vencida: a activarlo
    assert cliente.get("/logout", follow_redirects=False).status_code in (200, 302, 405)                      # y salir siempre se puede
    creds.por = {_ident(u): {"password", "totp"}}
    politica_acceso._CACHE.clear()
    assert cliente.get("/tareas").status_code != 302 or "/ajustes/cuenta" not in cliente.get("/tareas").headers["Location"]


def test_la_pantalla_de_acceso_la_gestiona_la_direccion_y_valida_la_fecha(cliente, creds):
    t = db.crear_tenant("Política pantalla")
    u = _con_sesion(cliente, t, "dir@ejemplo.com", supervisor=True)
    creds.por = {_ident(u): {"password", "totp"}}
    html = cliente.get("/seguridad/acceso").get_data(as_text=True)
    assert "Exigir verificación al equipo" in html
    r = cliente.post("/seguridad/acceso/politica", data={"exigir": "1", "limite": (date.today() + timedelta(days=2)).isoformat()})
    assert "error=" in r.headers["Location"] and not politica_acceso.obtener(t)["exigir"]
    r = cliente.post("/seguridad/acceso/politica", data={"exigir": "1", "limite": (date.today() + timedelta(days=15)).isoformat()})
    assert "aviso=politica" in r.headers["Location"] and politica_acceso.obtener(t)["exigir"]
    db.asignar_supervisor_tenant(u, False)
    assert cliente.post("/seguridad/acceso/politica", data={"exigir": "1"}).status_code == 403


def test_el_acceso_de_la_app_movil_se_cierra_pasada_la_fecha_y_se_abre_al_cumplir(cliente, creds):
    t = db.crear_tenant("Política móvil")
    identidad = kratos.crear_identidad("movil-politica@ejemplo.com", "contrasena123")
    u = db.crear_usuario_vinculado_a_kratos("movil-politica@ejemplo.com", identidad)
    db.asignar_tenant(u, t)
    creds.por = {identidad: {"password"}}
    login = lambda: cliente.post("/api/v1/auth/login", json={"email": "movil-politica@ejemplo.com", "contrasena": "contrasena123"})
    politica_acceso.fijar(t, u, True, (date.today() + timedelta(days=10)).isoformat())
    assert login().status_code == 200                                                                      # antes de la fecha: entra
    conn = db.get_connection()
    conn.execute("UPDATE tenants SET segundo_factor_limite = ? WHERE id = ?", ((date.today() - timedelta(days=1)).isoformat(), t))
    conn.commit(); conn.close()
    politica_acceso._CACHE.clear()
    r = login()
    assert r.status_code == 403 and "dos pasos" in r.get_data(as_text=True)
    creds.por = {identidad: {"password", "passkey"}}
    politica_acceso._CACHE.clear()
    assert login().status_code == 200                                                                      # con passkey, entra
