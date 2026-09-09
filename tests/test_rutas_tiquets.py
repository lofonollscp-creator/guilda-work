"""Tiquets (app/rutas_tiquets.py, app/db.py): prioridad y asignación a
un responsable -- la única cobertura de tests que existía hasta ahora
para este módulo era indirecta (ver tests/test_perfil_usuario.py), así
que estos tests cubren específicamente lo añadido en esta ronda."""
from tests.conftest import iniciar_sesion_de_prueba

from app import db


# --- Capa BD -----------------------------------------------------------

def test_crear_tiquet_prioridad_por_defecto_normal(usuario_id):
    tiquet_id = db.crear_tiquet(usuario_id, tipo="error", titulo="Algo falla")
    tiquet = db.obtener_tiquet(tiquet_id)
    assert tiquet["prioridad"] == "normal"
    assert tiquet["usuario_asignado_id"] is None


def test_asignar_tiquet_cambia_prioridad_y_responsable(usuario_id):
    tiquet_id = db.crear_tiquet(usuario_id, tipo="error", titulo="Algo falla")
    db.asignar_tiquet(tiquet_id, "alta", usuario_id)
    tiquet = db.obtener_tiquet(tiquet_id)
    assert tiquet["prioridad"] == "alta"
    assert tiquet["usuario_asignado_id"] == usuario_id
    assert tiquet["asignado_email"] is not None


def test_asignar_tiquet_puede_quitar_el_responsable(usuario_id):
    tiquet_id = db.crear_tiquet(usuario_id, tipo="error", titulo="Algo falla")
    db.asignar_tiquet(tiquet_id, "alta", usuario_id)
    db.asignar_tiquet(tiquet_id, "normal", None)
    tiquet = db.obtener_tiquet(tiquet_id)
    assert tiquet["usuario_asignado_id"] is None


def test_listar_tiquets_ordena_por_prioridad_alta_primero(usuario_id):
    id_normal = db.crear_tiquet(usuario_id, tipo="error", titulo="Normal")
    id_baja = db.crear_tiquet(usuario_id, tipo="error", titulo="Baja")
    id_alta = db.crear_tiquet(usuario_id, tipo="error", titulo="Alta")
    db.asignar_tiquet(id_baja, "baja", None)
    db.asignar_tiquet(id_alta, "alta", None)

    tiquets = db.listar_tiquets()
    ids_en_orden = [t["id"] for t in tiquets if t["id"] in (id_normal, id_baja, id_alta)]
    assert ids_en_orden == [id_alta, id_normal, id_baja]


def test_listar_tiquets_filtra_por_prioridad(usuario_id):
    id_normal = db.crear_tiquet(usuario_id, tipo="error", titulo="Normal")
    id_alta = db.crear_tiquet(usuario_id, tipo="error", titulo="Alta")
    db.asignar_tiquet(id_alta, "alta", None)

    tiquets = db.listar_tiquets(prioridad="alta")
    assert [t["id"] for t in tiquets] == [id_alta]


def test_listar_tiquets_filtra_por_asignado(usuario_id):
    id_asignado = db.crear_tiquet(usuario_id, tipo="error", titulo="Asignado")
    db.crear_tiquet(usuario_id, tipo="error", titulo="Sin asignar")
    db.asignar_tiquet(id_asignado, "normal", usuario_id)

    tiquets = db.listar_tiquets(usuario_asignado_id=usuario_id)
    assert [t["id"] for t in tiquets] == [id_asignado]


# --- Capa ruta -----------------------------------------------------------

def test_asignar_requiere_login(cliente):
    resp = cliente.post("/tiquets/1/asignar", data={"prioridad": "alta"})
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_asignar_sin_ser_admin_da_403(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "tiquet-no-admin@ejemplo.com", "contrasena123")
    tiquet_id = db.crear_tiquet(usuario_id, tipo="error", titulo="Algo")
    resp = cliente.post(f"/tiquets/{tiquet_id}/asignar", data={"prioridad": "alta"})
    assert resp.status_code == 403


def test_asignar_como_admin_actualiza_prioridad_y_responsable(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "tiquet-admin@ejemplo.com", "contrasena123")
    db.hacer_admin("tiquet-admin@ejemplo.com")
    tiquet_id = db.crear_tiquet(usuario_id, tipo="error", titulo="Algo")

    resp = cliente.post(
        f"/tiquets/{tiquet_id}/asignar", data={"prioridad": "alta", "usuario_asignado_id": str(usuario_id)},
    )
    assert resp.status_code == 302
    tiquet = db.obtener_tiquet(tiquet_id)
    assert tiquet["prioridad"] == "alta"
    assert tiquet["usuario_asignado_id"] == usuario_id


def test_asignar_prioridad_invalida_usa_normal(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "tiquet-admin-2@ejemplo.com", "contrasena123")
    db.hacer_admin("tiquet-admin-2@ejemplo.com")
    tiquet_id = db.crear_tiquet(usuario_id, tipo="error", titulo="Algo")

    resp = cliente.post(f"/tiquets/{tiquet_id}/asignar", data={"prioridad": "urgentisima"})
    assert resp.status_code == 302
    assert db.obtener_tiquet(tiquet_id)["prioridad"] == "normal"


def test_tarjetas_filtra_por_prioridad_en_la_url(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "tiquet-filtro@ejemplo.com", "contrasena123")
    id_alta = db.crear_tiquet(usuario_id, tipo="error", titulo="Prioritario")
    db.crear_tiquet(usuario_id, tipo="error", titulo="Normalito")
    db.asignar_tiquet(id_alta, "alta", None)

    resp = cliente.get("/tiquets/?prioridad=alta")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Prioritario" in html
    assert "Normalito" not in html


# --- Notificación al asignar un tiquet --------------------------------------

def test_asignar_a_otro_usuario_le_notifica(cliente, monkeypatch):
    from app import rutas_tiquets

    admin_id = iniciar_sesion_de_prueba(cliente, "tiquet-notif-admin@ejemplo.com", "contrasena123")
    db.hacer_admin("tiquet-notif-admin@ejemplo.com")
    otro_id = db.crear_usuario("tiquet-notif-otro@ejemplo.com", "contrasena123")
    tiquet_id = db.crear_tiquet(admin_id, tipo="error", titulo="Algo que arreglar")

    llamadas = []
    monkeypatch.setattr(rutas_tiquets.notificaciones, "crear_y_enviar", lambda *a, **k: llamadas.append(a))

    resp = cliente.post(
        f"/tiquets/{tiquet_id}/asignar", data={"prioridad": "normal", "usuario_asignado_id": str(otro_id)},
    )
    assert resp.status_code == 302
    assert len(llamadas) == 1
    assert llamadas[0][0] == otro_id
    assert llamadas[0][1] == "tiquet_asignado"


def test_reasignar_al_mismo_usuario_no_vuelve_a_notificar(cliente, monkeypatch):
    from app import rutas_tiquets

    admin_id = iniciar_sesion_de_prueba(cliente, "tiquet-notif-admin2@ejemplo.com", "contrasena123")
    db.hacer_admin("tiquet-notif-admin2@ejemplo.com")
    otro_id = db.crear_usuario("tiquet-notif-otro2@ejemplo.com", "contrasena123")
    tiquet_id = db.crear_tiquet(admin_id, tipo="error", titulo="Algo")
    db.asignar_tiquet(tiquet_id, "normal", otro_id)  # ya asignado de antemano

    llamadas = []
    monkeypatch.setattr(rutas_tiquets.notificaciones, "crear_y_enviar", lambda *a, **k: llamadas.append(a))

    resp = cliente.post(
        f"/tiquets/{tiquet_id}/asignar", data={"prioridad": "alta", "usuario_asignado_id": str(otro_id)},
    )
    assert resp.status_code == 302
    assert not llamadas


def test_autoasignarse_no_notifica(cliente, monkeypatch):
    from app import rutas_tiquets

    admin_id = iniciar_sesion_de_prueba(cliente, "tiquet-notif-self@ejemplo.com", "contrasena123")
    db.hacer_admin("tiquet-notif-self@ejemplo.com")
    tiquet_id = db.crear_tiquet(admin_id, tipo="error", titulo="Algo")

    llamadas = []
    monkeypatch.setattr(rutas_tiquets.notificaciones, "crear_y_enviar", lambda *a, **k: llamadas.append(a))

    resp = cliente.post(
        f"/tiquets/{tiquet_id}/asignar", data={"prioridad": "normal", "usuario_asignado_id": str(admin_id)},
    )
    assert resp.status_code == 302
    assert not llamadas


def test_asignar_no_notifica_si_el_destinatario_desactivo_la_preferencia(cliente, monkeypatch):
    from app import rutas_tiquets

    admin_id = iniciar_sesion_de_prueba(cliente, "tiquet-notif-pref@ejemplo.com", "contrasena123")
    db.hacer_admin("tiquet-notif-pref@ejemplo.com")
    otro_id = db.crear_usuario("tiquet-notif-pref-otro@ejemplo.com", "contrasena123")
    db.guardar_perfil_usuario(otro_id, notificar_push_tiquets=False)
    tiquet_id = db.crear_tiquet(admin_id, tipo="error", titulo="Algo")

    llamadas = []
    monkeypatch.setattr(rutas_tiquets.notificaciones, "crear_y_enviar", lambda *a, **k: llamadas.append(a))

    resp = cliente.post(
        f"/tiquets/{tiquet_id}/asignar", data={"prioridad": "normal", "usuario_asignado_id": str(otro_id)},
    )
    assert resp.status_code == 302
    assert not llamadas
