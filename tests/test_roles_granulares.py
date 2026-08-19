"""Rol general de "supervisor de tenant" (app/db.py:es_supervisor_tenant,
app/rutas_tiquets.py:_puede_supervisar_tiquet) -- mismo patrón que
gestor_fichajes, pero no scoped a un único módulo. Cubre: capa BD, el
toggle de backoffice, el aislamiento por tenant en tiquets, y que
token_required (app/auth.py) expone los flags a las rutas por token."""
from tests.conftest import iniciar_sesion_de_prueba

from app import db


# --- Capa BD -----------------------------------------------------------

def test_es_supervisor_tenant_por_defecto_false(usuario_id):
    assert db.es_supervisor_tenant(usuario_id) is False


def test_asignar_supervisor_tenant(usuario_id):
    db.asignar_supervisor_tenant(usuario_id, True)
    assert db.es_supervisor_tenant(usuario_id) is True
    db.asignar_supervisor_tenant(usuario_id, False)
    assert db.es_supervisor_tenant(usuario_id) is False


def test_usuario_pertenece_a_tenant():
    tenant_a = db.crear_tenant("Gestoria Roles A")
    tenant_b = db.crear_tenant("Gestoria Roles B")
    usuario_id = db.crear_usuario_vinculado_a_kratos("roles-pertenece@ejemplo.com", "kratos-roles-pertenece")
    db.asignar_tenant(usuario_id, tenant_a)
    assert db.usuario_pertenece_a_tenant(usuario_id, tenant_a) is True
    assert db.usuario_pertenece_a_tenant(usuario_id, tenant_b) is False


# --- Backoffice: toggle ---------------------------------------------------

def test_alternar_supervisor_tenant_requiere_admin(cliente):
    iniciar_sesion_de_prueba(cliente, "roles-no-admin@ejemplo.com", "contrasena123")
    otro_id = db.crear_usuario_vinculado_a_kratos("roles-objetivo@ejemplo.com", "kratos-roles-objetivo")
    resp = cliente.post(f"/backoffice/usuarios/{otro_id}/supervisor-tenant")
    assert resp.status_code == 403
    assert db.es_supervisor_tenant(otro_id) is False


def test_alternar_supervisor_tenant_como_admin(cliente):
    admin_id = iniciar_sesion_de_prueba(cliente, "roles-admin@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(admin_id)["email"])
    objetivo_id = db.crear_usuario_vinculado_a_kratos("roles-objetivo2@ejemplo.com", "kratos-roles-objetivo2")

    resp = cliente.post(f"/backoffice/usuarios/{objetivo_id}/supervisor-tenant")
    assert resp.status_code == 302
    assert db.es_supervisor_tenant(objetivo_id) is True

    cliente.post(f"/backoffice/usuarios/{objetivo_id}/supervisor-tenant")
    assert db.es_supervisor_tenant(objetivo_id) is False


# --- Aislamiento en tiquets ------------------------------------------------

def test_supervisor_puede_cambiar_estado_de_tiquet_de_su_propio_tenant(cliente):
    tenant_id = db.crear_tenant("Gestoria Tiquets Supervisor")
    creador_id = db.crear_usuario_vinculado_a_kratos("tiquets-creador@ejemplo.com", "kratos-tiquets-creador")
    db.asignar_tenant(creador_id, tenant_id)
    tiquet_id = db.crear_tiquet(creador_id, tipo="error", titulo="Algo falla")

    supervisor_id = iniciar_sesion_de_prueba(cliente, "tiquets-supervisor@ejemplo.com", "contrasena123")
    db.asignar_tenant(supervisor_id, tenant_id)
    db.asignar_supervisor_tenant(supervisor_id, True)

    resp = cliente.post(f"/tiquets/{tiquet_id}/estado", data={"estado": "en_revision"})
    assert resp.status_code == 302
    assert db.obtener_tiquet(tiquet_id)["estado"] == "en_revision"


def test_supervisor_no_puede_tocar_tiquet_de_otro_tenant(cliente):
    tenant_propio = db.crear_tenant("Gestoria Tiquets Supervisor Propio")
    tenant_ajeno = db.crear_tenant("Gestoria Tiquets Supervisor Ajeno")
    creador_ajeno_id = db.crear_usuario_vinculado_a_kratos("tiquets-creador-ajeno@ejemplo.com", "kratos-tiquets-creador-ajeno")
    db.asignar_tenant(creador_ajeno_id, tenant_ajeno)
    tiquet_id = db.crear_tiquet(creador_ajeno_id, tipo="error", titulo="Algo falla en otro tenant")

    supervisor_id = iniciar_sesion_de_prueba(cliente, "tiquets-supervisor-propio@ejemplo.com", "contrasena123")
    db.asignar_tenant(supervisor_id, tenant_propio)
    db.asignar_supervisor_tenant(supervisor_id, True)

    resp = cliente.post(f"/tiquets/{tiquet_id}/estado", data={"estado": "en_revision"})
    assert resp.status_code == 403
    assert db.obtener_tiquet(tiquet_id)["estado"] == "sin_revisar"


def test_usuario_normal_sin_supervisor_no_puede_cambiar_estado(cliente):
    tenant_id = db.crear_tenant("Gestoria Tiquets Normal")
    creador_id = iniciar_sesion_de_prueba(cliente, "tiquets-normal@ejemplo.com", "contrasena123")
    db.asignar_tenant(creador_id, tenant_id)
    tiquet_id = db.crear_tiquet(creador_id, tipo="error", titulo="Mi propio tiquet")

    resp = cliente.post(f"/tiquets/{tiquet_id}/estado", data={"estado": "en_revision"})
    assert resp.status_code == 403


def test_admin_puede_cambiar_estado_de_cualquier_tiquet(cliente):
    tenant_id = db.crear_tenant("Gestoria Tiquets Admin")
    creador_id = db.crear_usuario_vinculado_a_kratos("tiquets-creador-admin@ejemplo.com", "kratos-tiquets-creador-admin")
    db.asignar_tenant(creador_id, tenant_id)
    tiquet_id = db.crear_tiquet(creador_id, tipo="error", titulo="Algo falla")

    admin_id = iniciar_sesion_de_prueba(cliente, "tiquets-admin@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(admin_id)["email"])

    resp = cliente.post(f"/tiquets/{tiquet_id}/estado", data={"estado": "finalizado"})
    assert resp.status_code == 302
    assert db.obtener_tiquet(tiquet_id)["estado"] == "finalizado"


def test_supervisor_puede_asignar_prioridad_dentro_de_su_tenant(cliente):
    tenant_id = db.crear_tenant("Gestoria Tiquets Asignar")
    creador_id = db.crear_usuario_vinculado_a_kratos("tiquets-creador-asignar@ejemplo.com", "kratos-tiquets-creador-asignar")
    db.asignar_tenant(creador_id, tenant_id)
    tiquet_id = db.crear_tiquet(creador_id, tipo="error", titulo="Algo falla")

    supervisor_id = iniciar_sesion_de_prueba(cliente, "tiquets-supervisor-asignar@ejemplo.com", "contrasena123")
    db.asignar_tenant(supervisor_id, tenant_id)
    db.asignar_supervisor_tenant(supervisor_id, True)

    resp = cliente.post(f"/tiquets/{tiquet_id}/asignar", data={"prioridad": "alta"})
    assert resp.status_code == 302
    assert db.obtener_tiquet(tiquet_id)["prioridad"] == "alta"


# --- token_required expone los flags -------------------------------------

def test_token_required_expone_es_admin_gestor_y_supervisor(cliente):
    """Antes de este arreglo, token_required (app/auth.py) no fijaba
    g.es_admin/g.gestor_fichajes/g.supervisor_tenant en absoluto -- cualquier
    ruta por token (app móvil/API) que los leyera habría reventado con
    AttributeError. Se llama al decorador directamente dentro de un
    contexto de request de prueba (sin registrar ninguna ruta nueva en la
    app real -- Flask no permite añadir rutas tras el primer request, que
    el propio fixture `cliente` ya ha disparado a esta altura)."""
    from flask import g

    from app import auth
    from app.main import app as flask_app

    usuario_id = db.crear_usuario_vinculado_a_kratos("token-flags@ejemplo.com", "kratos-token-flags")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])
    db.asignar_supervisor_tenant(usuario_id, True)
    token = db.crear_token_api(usuario_id, "dispositivo de prueba")

    capturado = {}

    @auth.token_required
    def _vista_de_prueba():
        capturado["es_admin"] = g.es_admin
        capturado["gestor_fichajes"] = g.gestor_fichajes
        capturado["supervisor_tenant"] = g.supervisor_tenant
        return "ok"

    with flask_app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        resultado = _vista_de_prueba()

    assert resultado == "ok"
    assert capturado == {"es_admin": True, "gestor_fichajes": False, "supervisor_tenant": True}
