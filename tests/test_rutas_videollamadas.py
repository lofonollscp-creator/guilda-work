"""Ruta web de videollamadas (app/rutas_videollamadas.py): antes solo el
Asistente IA podia generar una sala de Jitsi Meet (mcp_tools.py), esta
vista es el formulario equivalente para un empleado sin pasar por un
prompt."""
from tests.conftest import iniciar_sesion_de_prueba

from app import db


def test_nueva_requiere_login(cliente):
    resp = cliente.get("/videollamadas/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_nueva_muestra_formulario(cliente):
    iniciar_sesion_de_prueba(cliente, "video-form@ejemplo.com", "contrasena123")
    resp = cliente.get("/videollamadas/")
    assert resp.status_code == 200
    assert "Crear sala y entrar" in resp.get_data(as_text=True)


def test_crear_sin_tenant_da_403(cliente):
    iniciar_sesion_de_prueba(cliente, "video-sin-tenant@ejemplo.com", "contrasena123")
    resp = cliente.post("/videollamadas/", data={})
    assert resp.status_code == 403


def test_crear_sin_jitsi_configurado_muestra_error(cliente, monkeypatch):
    from app import rutas_videollamadas

    usuario_id = iniciar_sesion_de_prueba(cliente, "video-sin-jitsi@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Video Sin Jitsi")
    db.asignar_tenant(usuario_id, tenant_id)
    monkeypatch.setattr(rutas_videollamadas.jitsi, "JITSI_JWT_APP_ID", None)
    monkeypatch.setattr(rutas_videollamadas.jitsi, "JITSI_JWT_APP_SECRET", None)

    resp = cliente.post("/videollamadas/", data={})
    assert resp.status_code == 200
    assert "no están configuradas" in resp.get_data(as_text=True)


def test_crear_sala_redirige_a_jitsi_con_jwt(cliente, monkeypatch):
    from app import rutas_videollamadas

    usuario_id = iniciar_sesion_de_prueba(cliente, "video-ok@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Video Ok")
    db.asignar_tenant(usuario_id, tenant_id)
    monkeypatch.setattr(rutas_videollamadas.jitsi, "JITSI_JWT_APP_ID", "guilda_work")
    monkeypatch.setattr(rutas_videollamadas.jitsi, "JITSI_JWT_APP_SECRET", "secreto-de-prueba")

    resp = cliente.post("/videollamadas/", data={"nombre_mostrado": "Juana"})
    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location.startswith(rutas_videollamadas.jitsi.JITSI_URL)
    assert "jwt=" in location
    assert "gestoria-video-ok-" in location


def test_crear_sala_sin_nombre_usa_email_del_usuario(cliente, monkeypatch):
    from app import rutas_videollamadas

    usuario_id = iniciar_sesion_de_prueba(cliente, "video-sin-nombre@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Video Sin Nombre")
    db.asignar_tenant(usuario_id, tenant_id)
    monkeypatch.setattr(rutas_videollamadas.jitsi, "JITSI_JWT_APP_ID", "guilda_work")
    monkeypatch.setattr(rutas_videollamadas.jitsi, "JITSI_JWT_APP_SECRET", "secreto-de-prueba")

    llamadas = {}
    original = rutas_videollamadas.jitsi.generar_jwt_sala

    def _espia(tenant, nombre_mostrado, sala, moderador=False):
        llamadas["nombre_mostrado"] = nombre_mostrado
        return original(tenant, nombre_mostrado, sala, moderador=moderador)
    monkeypatch.setattr(rutas_videollamadas.jitsi, "generar_jwt_sala", _espia)

    resp = cliente.post("/videollamadas/", data={})
    assert resp.status_code == 302
    assert llamadas["nombre_mostrado"] == "video-sin-nombre@ejemplo.com"
