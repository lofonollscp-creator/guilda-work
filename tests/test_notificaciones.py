"""Centro de notificaciones unificado: capa BD (app/db.py), el helper
crear_y_enviar (app/notificaciones.py) y el blueprint que sirve el
desplegable (app/rutas_notificaciones.py)."""
from tests.conftest import iniciar_sesion_de_prueba

from app import db, notificaciones


# --- Capa BD -----------------------------------------------------------

def test_crear_y_listar_notificacion(usuario_id):
    db.crear_notificacion(usuario_id, "correo_nuevo", "Correo nuevo", "Tienes 1 mensaje.", "/correo/")
    notis = db.listar_notificaciones(usuario_id)
    assert len(notis) == 1
    assert notis[0]["titulo"] == "Correo nuevo"
    assert notis[0]["leido_en"] is None


def test_contar_no_leidas_y_marcar_leidas(usuario_id):
    db.crear_notificacion(usuario_id, "correo_nuevo", "A", "a", None)
    db.crear_notificacion(usuario_id, "correo_nuevo", "B", "b", None)
    assert db.contar_notificaciones_no_leidas(usuario_id) == 2

    db.marcar_notificaciones_leidas(usuario_id)
    assert db.contar_notificaciones_no_leidas(usuario_id) == 0
    assert all(n["leido_en"] is not None for n in db.listar_notificaciones(usuario_id))


def test_listar_notificaciones_respeta_el_limite(usuario_id):
    for i in range(15):
        db.crear_notificacion(usuario_id, "correo_nuevo", f"N{i}", "x", None)
    assert len(db.listar_notificaciones(usuario_id, limite=10)) == 10


def test_notificaciones_son_privadas_por_usuario():
    otro_usuario_id = db.crear_usuario_vinculado_a_kratos("otro-notif@ejemplo.com", "kratos-otro-notif")
    db.crear_notificacion(db.usuario_local_id(), "correo_nuevo", "Mía", "x", None)
    assert db.listar_notificaciones(otro_usuario_id) == []
    assert db.contar_notificaciones_no_leidas(otro_usuario_id) == 0


# --- notificaciones.crear_y_enviar --------------------------------------

def test_crear_y_enviar_registra_y_manda_push(usuario_id, monkeypatch):
    llamadas = []
    monkeypatch.setattr(notificaciones.push, "enviar_a_usuario", lambda *a, **k: llamadas.append((a, k)))

    notificaciones.crear_y_enviar(usuario_id, "vencimiento_fiscal", "Título", "Cuerpo", url="/fiscal/x", datos={"a": 1})

    notis = db.listar_notificaciones(usuario_id)
    assert len(notis) == 1
    assert notis[0]["url"] == "/fiscal/x"
    assert len(llamadas) == 1
    assert llamadas[0][0] == (usuario_id, "Título", "Cuerpo", {"a": 1})


def test_crear_y_enviar_si_falla_el_registro_igual_manda_el_push(usuario_id, monkeypatch):
    monkeypatch.setattr(db, "crear_notificacion", lambda *a, **k: (_ for _ in ()).throw(Exception("bd caída")))
    llamadas = []
    monkeypatch.setattr(notificaciones.push, "enviar_a_usuario", lambda *a, **k: llamadas.append(a))

    notificaciones.crear_y_enviar(usuario_id, "correo_nuevo", "Título", "Cuerpo")
    assert len(llamadas) == 1


# --- Blueprint (app/rutas_notificaciones.py) ----------------------------

def test_recientes_requiere_login(cliente):
    resp = cliente.get("/notificaciones/recientes")
    assert resp.status_code == 302


def test_recientes_devuelve_las_del_usuario_actual(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "notif-recientes@ejemplo.com", "contrasena123")
    db.crear_notificacion(usuario_id, "correo_nuevo", "Aviso", "cuerpo", "/correo/")

    resp = cliente.get("/notificaciones/recientes")
    assert resp.status_code == 200
    datos = resp.get_json()
    assert len(datos) == 1
    assert datos[0]["titulo"] == "Aviso"
    assert datos[0]["leido"] is False


def test_recientes_no_marca_como_leidas_por_si_solo(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "notif-no-marca@ejemplo.com", "contrasena123")
    db.crear_notificacion(usuario_id, "correo_nuevo", "Aviso", "cuerpo", None)

    cliente.get("/notificaciones/recientes")
    assert db.contar_notificaciones_no_leidas(usuario_id) == 1


def test_marcar_leidas_marca_todas_las_del_usuario(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "notif-marcar@ejemplo.com", "contrasena123")
    db.crear_notificacion(usuario_id, "correo_nuevo", "A", "a", None)
    db.crear_notificacion(usuario_id, "correo_nuevo", "B", "b", None)

    resp = cliente.post("/notificaciones/marcar-leidas")
    assert resp.status_code == 200
    assert db.contar_notificaciones_no_leidas(usuario_id) == 0


def test_marcar_leidas_no_afecta_a_otro_usuario(cliente):
    usuario_a = iniciar_sesion_de_prueba(cliente, "notif-a@ejemplo.com", "contrasena123")
    otro_usuario_id = db.crear_usuario_vinculado_a_kratos("notif-otro@ejemplo.com", "kratos-notif-otro")
    db.crear_notificacion(otro_usuario_id, "correo_nuevo", "Ajena", "x", None)

    cliente.post("/notificaciones/marcar-leidas")
    assert db.contar_notificaciones_no_leidas(otro_usuario_id) == 1
