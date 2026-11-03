"""La conversación activa del asistente se recuerda durante una petición (una pantalla la pedía 4 veces) y se olvida al cambiarla."""
from app import db
from app.main import app


def test_la_activa_se_recuerda_en_la_peticion_y_se_olvida_al_cambiar(cliente):
    uid = db.crear_usuario("memo-ia@ejemplo.com", "contrasena123")
    with app.test_request_context("/"):
        primera = db.conversacion_ia_activa_id(uid)
        assert db.conversacion_ia_activa_id(uid) == primera
        db.agregar_mensaje_ia(uid, "user", "hola")
        segunda = db.crear_conversacion_ia(uid)                      # la activa ya tiene mensajes: abre otra
        assert segunda != primera and db.conversacion_ia_activa_id(uid) == segunda
        assert db.activar_conversacion_ia(uid, primera) and db.conversacion_ia_activa_id(uid) == primera
        assert db.eliminar_conversacion_ia(uid, primera) and db.conversacion_ia_activa_id(uid) == segunda


def test_fuera_de_una_peticion_no_se_recuerda_nada(cliente):
    uid = db.crear_usuario("memo-ia2@ejemplo.com", "contrasena123")
    primera = db.conversacion_ia_activa_id(uid)
    db.agregar_mensaje_ia(uid, "user", "hola")
    segunda = db.crear_conversacion_ia(uid)
    assert db.conversacion_ia_activa_id(uid) == segunda != primera


def test_recordar_que_no_hay_ninguna_no_impide_abrir_una_al_escribir(cliente):
    uid = db.crear_usuario("memo-ia3@ejemplo.com", "contrasena123")
    with app.test_request_context("/"):
        assert db.conversacion_ia_activa_id(uid, crear=False) is None
        assert db.conversacion_ia_activa_id(uid, crear=False) is None
        abierta = db.conversacion_ia_activa_id(uid)                  # al escribir sí se abre
        assert abierta and db.conversacion_ia_activa_id(uid, crear=False) == abierta
