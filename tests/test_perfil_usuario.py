"""Capa BD del perfil de usuario (Fase G1: espacio de ajustes de usuario) --
tabla singleton usuario_perfil, mismo patrón que ia_preferencias."""
from app import db


def _usuario() -> int:
    return db.crear_usuario_vinculado_a_kratos("perfil-test@ejemplo.com", "kratos-perfil-test")


def test_perfil_por_defecto():
    usuario_id = _usuario()
    perfil = db.obtener_perfil_usuario(usuario_id)
    assert perfil["nombre_mostrado"] is None
    assert perfil["avatar_contenido"] is None
    assert perfil["notificar_push_vencimientos"] == 1
    assert perfil["notificar_push_tiquets"] == 1
    assert perfil["notificar_resumen_semanal"] == 0


def test_guardar_perfil_solo_actualiza_campos_pasados():
    usuario_id = _usuario()
    db.guardar_perfil_usuario(usuario_id, nombre_mostrado="Jorge V.")
    assert db.obtener_perfil_usuario(usuario_id)["nombre_mostrado"] == "Jorge V."

    db.guardar_perfil_usuario(usuario_id, notificar_push_tiquets=False)
    perfil = db.obtener_perfil_usuario(usuario_id)
    assert perfil["notificar_push_tiquets"] == 0
    assert perfil["nombre_mostrado"] == "Jorge V."  # no se pisa


def test_nombre_mostrado_usuario_atajo():
    usuario_id = _usuario()
    assert db.nombre_mostrado_usuario(usuario_id) is None
    db.guardar_perfil_usuario(usuario_id, nombre_mostrado="Jorge V.")
    assert db.nombre_mostrado_usuario(usuario_id) == "Jorge V."


def test_avatar_guardar_y_eliminar():
    usuario_id = _usuario()
    db.guardar_avatar_usuario(usuario_id, b"contenido-jpeg", "image/jpeg")
    perfil = db.obtener_perfil_usuario(usuario_id)
    assert perfil["avatar_contenido"] == b"contenido-jpeg"
    assert perfil["avatar_tipo_mime"] == "image/jpeg"

    db.eliminar_avatar_usuario(usuario_id)
    perfil = db.obtener_perfil_usuario(usuario_id)
    assert perfil["avatar_contenido"] is None
    assert perfil["avatar_tipo_mime"] is None
