"""Tests de las tareas al estilo Outlook (app/db.py: *_tarea_outlook y
la ampliación de papelera()/vaciar_papelera_antigua() para incluirlas).
"""
from datetime import datetime, timedelta

from app import db


def test_crear_y_listar_tarea_outlook(usuario_id):
    tid = db.crear_tarea_outlook(usuario_id, "Comprar billetes", prioridad="alta", fecha_vencimiento="2026-02-01")
    tareas = db.listar_tareas_outlook(usuario_id)
    assert len(tareas) == 1
    assert tareas[0]["id"] == tid
    assert tareas[0]["asunto"] == "Comprar billetes"
    assert tareas[0]["prioridad"] == "alta"
    assert tareas[0]["estado"] == "no_iniciada"
    assert tareas[0]["porcentaje_completado"] == 0


def test_editar_tarea_outlook_solo_toca_los_campos_indicados(usuario_id):
    tid = db.crear_tarea_outlook(usuario_id, "Original", prioridad="baja")
    db.editar_tarea_outlook(usuario_id, tid, asunto="Editado")
    tarea = db.obtener_tarea_outlook(usuario_id, tid)
    assert tarea["asunto"] == "Editado"
    assert tarea["prioridad"] == "baja"  # no tocado, se mantiene
    assert tarea["actualizada_en"] is not None


def test_completar_tarea_outlook(usuario_id):
    tid = db.crear_tarea_outlook(usuario_id, "Tarea")
    db.completar_tarea_outlook(usuario_id, tid)
    tarea = db.obtener_tarea_outlook(usuario_id, tid)
    assert tarea["estado"] == "completada"
    assert tarea["porcentaje_completado"] == 100
    assert tarea["fecha_completada"] is not None


def test_listar_tareas_outlook_filtra_por_estado_prioridad_categoria_y_texto(usuario_id):
    db.crear_tarea_outlook(usuario_id, "Llamar al banco", prioridad="alta", categoria_outlook="Personal")
    t2 = db.crear_tarea_outlook(usuario_id, "Revisar informe", prioridad="baja", categoria_outlook="Trabajo")
    db.completar_tarea_outlook(usuario_id, t2)

    assert len(db.listar_tareas_outlook(usuario_id, prioridad="alta")) == 1
    assert len(db.listar_tareas_outlook(usuario_id, categoria_outlook="Trabajo")) == 1
    assert len(db.listar_tareas_outlook(usuario_id, estado="completada")) == 1
    assert len(db.listar_tareas_outlook(usuario_id, texto="banco")) == 1
    assert len(db.listar_tareas_outlook(usuario_id, texto="no existe")) == 0


def test_listar_tareas_outlook_filtra_por_rango_de_vencimiento(usuario_id):
    db.crear_tarea_outlook(usuario_id, "Antes de rango", fecha_vencimiento="2026-01-01")
    db.crear_tarea_outlook(usuario_id, "Dentro de rango", fecha_vencimiento="2026-02-15")
    db.crear_tarea_outlook(usuario_id, "Después de rango", fecha_vencimiento="2026-03-01")

    dentro = db.listar_tareas_outlook(usuario_id, desde="2026-02-01", hasta="2026-02-28")
    assert [t["asunto"] for t in dentro] == ["Dentro de rango"]


def test_eliminar_y_restaurar_tarea_outlook(usuario_id):
    tid = db.crear_tarea_outlook(usuario_id, "Tarea")
    db.eliminar_tarea_outlook(usuario_id, tid)
    assert db.obtener_tarea_outlook(usuario_id, tid) is None
    assert any(item["origen"] == "tarea_outlook" and item["id"] == tid for item in db.papelera(usuario_id))

    db.restaurar_tarea_outlook(usuario_id, tid)
    assert db.obtener_tarea_outlook(usuario_id, tid) is not None
    assert not any(item["origen"] == "tarea_outlook" and item["id"] == tid for item in db.papelera(usuario_id))


def test_eliminar_tarea_outlook_definitivamente(usuario_id):
    tid = db.crear_tarea_outlook(usuario_id, "Tarea")
    db.eliminar_tarea_outlook(usuario_id, tid)
    db.eliminar_tarea_outlook_definitivamente(usuario_id, tid)
    assert not any(item["origen"] == "tarea_outlook" and item["id"] == tid for item in db.papelera(usuario_id))


def test_vaciar_papelera_antigua_incluye_tareas_outlook(monkeypatch, usuario_id):
    tid_vieja = db.crear_tarea_outlook(usuario_id, "Vieja")
    tid_reciente = db.crear_tarea_outlook(usuario_id, "Reciente")

    hace_40_dias = (datetime.now() - timedelta(days=40)).isoformat(timespec="microseconds")
    hace_1_dia = (datetime.now() - timedelta(days=1)).isoformat(timespec="microseconds")

    monkeypatch.setattr(db, "_marca_papelera", lambda: hace_40_dias)
    db.eliminar_tarea_outlook(usuario_id, tid_vieja)
    monkeypatch.setattr(db, "_marca_papelera", lambda: hace_1_dia)
    db.eliminar_tarea_outlook(usuario_id, tid_reciente)

    db.vaciar_papelera_antigua(dias=30)

    ids_en_papelera = {item["id"] for item in db.papelera(usuario_id) if item["origen"] == "tarea_outlook"}
    assert tid_vieja not in ids_en_papelera
    assert tid_reciente in ids_en_papelera


def test_listar_categorias_outlook(usuario_id):
    db.crear_tarea_outlook(usuario_id, "A", categoria_outlook="Trabajo")
    db.crear_tarea_outlook(usuario_id, "B", categoria_outlook="Personal")
    db.crear_tarea_outlook(usuario_id, "C", categoria_outlook="Trabajo")
    db.crear_tarea_outlook(usuario_id, "D")  # sin categoría

    assert db.listar_categorias_outlook(usuario_id) == ["Personal", "Trabajo"]


def test_obtener_tarea_outlook_por_entry_id(usuario_id):
    tid = db.crear_tarea_outlook(usuario_id, "Tarea", outlook_entry_id="ABC123")
    tarea = db.obtener_tarea_outlook_por_entry_id(usuario_id, "ABC123")
    assert tarea is not None
    assert tarea["id"] == tid
    assert db.obtener_tarea_outlook_por_entry_id(usuario_id, "NO-EXISTE") is None
