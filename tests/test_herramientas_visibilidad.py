"""Tests de la visibilidad de herramientas por tenant (backoffice → detalle
de tenant → Herramientas) — tanto a nivel de app/db.py como de las rutas
web (app/main.py:herramientas_vista(), app/rutas_api.py:listar_herramientas())
y del backoffice (app/rutas_backoffice.py:alternar_herramienta_tenant()).

Se construyó como alternativa nativa a desplegar un servicio de feature
flags aparte (Unleash/Flagsmith) — ver el plan de implementación: el
proyecto ya modela tenants y herramientas de forma nativa, así que ocultar
una herramienta para un tenant es una fila en una tabla, no un servicio
nuevo que mantener.
"""
from app import db, herramientas
from tests.conftest import iniciar_sesion_de_prueba

_HERRAMIENTA_EJEMPLO = herramientas.HERRAMIENTAS[0]["id"]


# --- app/db.py -----------------------------------------------------------

def test_herramienta_visible_por_defecto():
    tenant_id = db.crear_tenant("Lueira")
    assert db.herramientas_ocultas_de_tenant(tenant_id) == set()


def test_ocultar_y_mostrar_herramienta():
    tenant_id = db.crear_tenant("Lueira")
    db.ocultar_herramienta(tenant_id, _HERRAMIENTA_EJEMPLO)
    assert _HERRAMIENTA_EJEMPLO in db.herramientas_ocultas_de_tenant(tenant_id)

    db.mostrar_herramienta(tenant_id, _HERRAMIENTA_EJEMPLO)
    assert _HERRAMIENTA_EJEMPLO not in db.herramientas_ocultas_de_tenant(tenant_id)


def test_ocultar_herramienta_es_idempotente():
    tenant_id = db.crear_tenant("Lueira")
    db.ocultar_herramienta(tenant_id, _HERRAMIENTA_EJEMPLO)
    db.ocultar_herramienta(tenant_id, _HERRAMIENTA_EJEMPLO)  # no debe lanzar
    assert db.herramientas_ocultas_de_tenant(tenant_id) == {_HERRAMIENTA_EJEMPLO}


def test_mostrar_herramienta_ya_visible_es_idempotente():
    tenant_id = db.crear_tenant("Lueira")
    db.mostrar_herramienta(tenant_id, _HERRAMIENTA_EJEMPLO)  # no debe lanzar
    assert db.herramientas_ocultas_de_tenant(tenant_id) == set()


def test_ocultar_herramienta_aisla_entre_tenants():
    tenant_a = db.crear_tenant("Cliente Alfa")
    tenant_b = db.crear_tenant("Cliente Beta")
    db.ocultar_herramienta(tenant_a, _HERRAMIENTA_EJEMPLO)
    assert _HERRAMIENTA_EJEMPLO in db.herramientas_ocultas_de_tenant(tenant_a)
    assert _HERRAMIENTA_EJEMPLO not in db.herramientas_ocultas_de_tenant(tenant_b)


def test_borrar_tenant_limpia_sus_herramientas_ocultas():
    tenant_id = db.crear_tenant("Lueira")
    db.ocultar_herramienta(tenant_id, _HERRAMIENTA_EJEMPLO)
    db.borrar_tenant(tenant_id)  # no debe lanzar por la fila huérfana
    assert db.obtener_tenant(tenant_id) is None


# --- app/main.py:herramientas_vista() -------------------------------------

def test_herramientas_vista_oculta_solo_para_el_tenant_afectado(cliente):
    tenant_a = db.crear_tenant("Cliente Alfa")
    tenant_b = db.crear_tenant("Cliente Beta")
    db.ocultar_herramienta(tenant_a, _HERRAMIENTA_EJEMPLO)
    nombre_ejemplo = herramientas.HERRAMIENTAS[0]["nombre"]

    usuario_a = iniciar_sesion_de_prueba(cliente, "alfa@ejemplo.com", "contrasena123")
    db.asignar_tenant(usuario_a, tenant_a)
    resp_a = cliente.get("/herramientas")
    assert nombre_ejemplo.encode() not in resp_a.data

    cliente.post("/logout", follow_redirects=True)
    usuario_b = iniciar_sesion_de_prueba(cliente, "beta@ejemplo.com", "contrasena123")
    db.asignar_tenant(usuario_b, tenant_b)
    resp_b = cliente.get("/herramientas")
    assert resp_b.status_code == 200
    # El tenant B no tiene nada oculto: debe ver la herramienta de ejemplo.
    assert nombre_ejemplo.encode() in resp_b.data


def test_herramientas_vista_usuario_sin_tenant_ve_catalogo_completo(cliente):
    """"Catálogo completo" significa todas las DISPONIBLES -- las que
    todavía no están desplegadas (herramientas.disponible == False) no
    se muestran en absoluto (antes salían en gris con "Aún no
    disponible"; ver test_herramientas_no_disponibles_no_aparecen)."""
    iniciar_sesion_de_prueba(cliente, "sintenant@ejemplo.com", "contrasena123")
    resp = cliente.get("/herramientas")
    assert resp.status_code == 200
    for h in herramientas.HERRAMIENTAS:
        if h.get("disponible") is False:
            continue
        assert h["nombre"].encode() in resp.data


def test_herramientas_no_disponibles_no_aparecen(cliente):
    iniciar_sesion_de_prueba(cliente, "sintenant-nodisp@ejemplo.com", "contrasena123")
    resp = cliente.get("/herramientas")
    assert resp.status_code == 200
    no_disponibles = [h for h in herramientas.HERRAMIENTAS if h.get("disponible") is False]
    assert no_disponibles, "hace falta al menos una herramienta con disponible=False para que este test compruebe algo"
    for h in no_disponibles:
        assert h["nombre"].encode() not in resp.data
    assert "Aún no disponible".encode() not in resp.data


# --- app/rutas_api.py:listar_herramientas() (API móvil) -------------------

def test_api_herramientas_respeta_la_visibilidad_del_tenant(cliente):
    tenant_id = db.crear_tenant("Cliente Alfa")
    db.ocultar_herramienta(tenant_id, _HERRAMIENTA_EJEMPLO)

    resp = cliente.post("/api/v1/auth/registro", json={
        "email": "movil@ejemplo.com", "contrasena": "contrasena123",
    })
    datos = resp.get_json()["data"]
    db.asignar_tenant(datos["usuario"]["id"], tenant_id)

    resp = cliente.get("/api/v1/herramientas", headers={"Authorization": f"Bearer {datos['token']}"})
    assert resp.status_code == 200
    ids = {h["id"] for h in resp.get_json()["data"]}
    assert _HERRAMIENTA_EJEMPLO not in ids
    assert "chat" not in ids  # el filtro de siempre (cliente Matrix nativo) sigue aplicando


# --- app/rutas_backoffice.py:alternar_herramienta_tenant() ----------------

def _admin(cliente, email="admin@ejemplo.com"):
    usuario_id = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])
    return usuario_id
