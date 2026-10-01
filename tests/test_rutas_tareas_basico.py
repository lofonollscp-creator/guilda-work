"""Creación básica de tareas (app/main.py: POST /tareas) -- sin
cobertura de ruta hasta ahora (solo a nivel de BD, ver tests/test_db.py)."""
from tests.conftest import iniciar_sesion_de_prueba

from app import db


def test_crear_tarea_categoria_id_no_numerico_no_da_500(cliente):
    """Bug encontrado en la auditoría de 2026-09-30: int(categoria_id)
    sin validar lanzaba ValueError sin capturar si el campo del
    formulario no era numérico."""
    iniciar_sesion_de_prueba(cliente, "tareas-categoria-mala@ejemplo.com", "contrasena123")
    resp = cliente.post("/tareas", data={"nombre": "Tarea con categoría rota", "categoria_id": "no-es-un-numero"})
    assert resp.status_code == 302  # redirige sin crear nada, no un 500


def test_crear_tarea_ok(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "tareas-ok@ejemplo.com", "contrasena123")
    categoria_id = db.crear_categoria(usuario_id, "Categoría de prueba")
    antes = len(db.tareas_activas(usuario_id))

    resp = cliente.post("/tareas", data={"nombre": "Tarea real", "categoria_id": str(categoria_id)})
    assert resp.status_code == 302
    assert len(db.tareas_activas(usuario_id)) == antes + 1
