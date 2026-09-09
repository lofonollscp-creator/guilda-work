"""Proxy hacia FacturaScripts en facturacion.guildawork.com
(app/rutas_facturacion_proxy.py): capa BD (facturacion_accesos, mismo
patrón que clientes_fiscales_accesos) y capa ruta (enlace de un solo uso
desde /facturacion/abrir, sesión propia del proxy, aislamiento entre
tenants -- FacturaScripts sigue pidiendo su propio login, esto solo
resuelve a qué instancia llegar)."""
from datetime import datetime, timedelta

from tests.conftest import iniciar_sesion_de_prueba

from app import db


# --- Capa BD: facturacion_accesos -------------------------------------------

def test_crear_y_consumir_token_de_un_solo_uso():
    tenant_id = db.crear_tenant("Gestoria Facturacion Token")
    usuario_id = db.crear_usuario("token-facturacion@ejemplo.com", "contrasena123")
    token = db.crear_acceso_facturacion(tenant_id, usuario_id)

    assert db.consumir_acceso_facturacion(token) == tenant_id
    # Segundo consumo del MISMO token: ya usado, no vuelve a dar el tenant.
    assert db.consumir_acceso_facturacion(token) is None


def test_token_inexistente_no_se_consume():
    assert db.consumir_acceso_facturacion("token-que-no-existe") is None


def test_token_caducado_no_se_consume(monkeypatch):
    tenant_id = db.crear_tenant("Gestoria Facturacion Caducado")
    usuario_id = db.crear_usuario("token-facturacion-caducado@ejemplo.com", "contrasena123")
    token = db.crear_acceso_facturacion(tenant_id, usuario_id)

    real_now_iso = db.now_iso
    futuro = (datetime.now() + timedelta(minutes=5)).isoformat(timespec="seconds")
    monkeypatch.setattr(db, "now_iso", lambda: futuro)
    try:
        assert db.consumir_acceso_facturacion(token) is None
    finally:
        monkeypatch.setattr(db, "now_iso", real_now_iso)


# --- Capa ruta: /facturacion/abrir -------------------------------------------

def test_abrir_facturacion_sin_url_configurada_da_404(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "sin-fs@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Sin FacturaScripts")
    db.asignar_tenant(usuario_id, tenant_id)

    resp = cliente.get("/facturacion/abrir")
    assert resp.status_code == 404


def test_abrir_facturacion_redirige_al_proxy_con_token(cliente):
    from app import rutas_facturacion_proxy

    usuario_id = iniciar_sesion_de_prueba(cliente, "con-fs@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Con FacturaScripts")
    db.asignar_tenant(usuario_id, tenant_id)
    db.guardar_facturascripts(tenant_id, "http://127.0.0.1:8107/", "admin", "clave-generada")

    resp = cliente.get("/facturacion/abrir")
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith(f"{rutas_facturacion_proxy.FACTURACION_ORIGIN}/entrar?token=")


def test_abrir_facturacion_sin_sesion_redirige_a_login(cliente):
    resp = cliente.get("/facturacion/abrir")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


# --- Capa ruta: /entrar y el proxy en sí ------------------------------------

def test_entrar_con_token_valido_fija_sesion_del_proxy(cliente):
    tenant_id = db.crear_tenant("Gestoria Proxy Entrar")
    usuario_id = db.crear_usuario("entrar-proxy@ejemplo.com", "contrasena123")
    token = db.crear_acceso_facturacion(tenant_id, usuario_id)

    resp = cliente.get(f"/facturacion-proxy/entrar?token={token}")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"
    with cliente.session_transaction() as sess:
        assert sess["facturacion_tenant_id"] == tenant_id


def test_entrar_con_token_invalido_no_fija_sesion(cliente):
    resp = cliente.get("/facturacion-proxy/entrar?token=no-existe")
    assert resp.status_code == 403
    with cliente.session_transaction() as sess:
        assert "facturacion_tenant_id" not in sess


def test_proxy_sin_sesion_de_facturacion_da_403(cliente):
    resp = cliente.get("/facturacion-proxy/")
    assert resp.status_code == 403


def test_proxy_reenvia_a_la_url_del_tenant_correcto(cliente, monkeypatch):
    from app import rutas_facturacion_proxy

    tenant_id = db.crear_tenant("Gestoria Proxy Reenvio")
    db.guardar_facturascripts(tenant_id, "http://127.0.0.1:8199/", "admin", "clave")

    peticiones = []

    class _RespuestaFalsa:
        def __init__(self):
            self.status = 200
            self.headers = {"Content-Type": "text/html"}

        def read(self):
            return b"<html>FacturaScripts</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _OpenerFalso:
        def open(self, peticion, timeout=None):
            peticiones.append(peticion.full_url)
            return _RespuestaFalsa()

    monkeypatch.setattr(rutas_facturacion_proxy, "_opener_sin_redireccion", lambda: _OpenerFalso())

    with cliente.session_transaction() as sess:
        sess["facturacion_tenant_id"] = tenant_id

    resp = cliente.get("/facturacion-proxy/index.php?page=Cliente")
    assert resp.status_code == 200
    assert peticiones == ["http://127.0.0.1:8199/index.php?page=Cliente"]


def test_proxy_sin_facturascripts_aprovisionado_da_404(cliente):
    tenant_id = db.crear_tenant("Gestoria Proxy Sin FS")

    with cliente.session_transaction() as sess:
        sess["facturacion_tenant_id"] = tenant_id

    resp = cliente.get("/facturacion-proxy/")
    assert resp.status_code == 404
