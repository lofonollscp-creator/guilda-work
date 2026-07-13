"""Tests de las tareas al estilo Outlook (app/db.py: *_tarea_outlook y
la ampliación de papelera()/vaciar_papelera_antigua() para incluirlas).
"""
from datetime import datetime, timedelta

from app import db


def test_crear_y_listar_tarea_outlook():
    tid = db.crear_tarea_outlook("Comprar billetes", prioridad="alta", fecha_vencimiento="2026-02-01")
    tareas = db.listar_tareas_outlook()
    assert len(tareas) == 1
    assert tareas[0]["id"] == tid
    assert tareas[0]["asunto"] == "Comprar billetes"
    assert tareas[0]["prioridad"] == "alta"
    assert tareas[0]["estado"] == "no_iniciada"
    assert tareas[0]["porcentaje_completado"] == 0


def test_editar_tarea_outlook_solo_toca_los_campos_indicados():
    tid = db.crear_tarea_outlook("Original", prioridad="baja")
    db.editar_tarea_outlook(tid, asunto="Editado")
    tarea = db.obtener_tarea_outlook(tid)
    assert tarea["asunto"] == "Editado"
    assert tarea["prioridad"] == "baja"  # no tocado, se mantiene
    assert tarea["actualizada_en"] is not None


def test_completar_tarea_outlook():
    tid = db.crear_tarea_outlook("Tarea")
    db.completar_tarea_outlook(tid)
    tarea = db.obtener_tarea_outlook(tid)
    assert tarea["estado"] == "completada"
    assert tarea["porcentaje_completado"] == 100
    assert tarea["fecha_completada"] is not None


def test_listar_tareas_outlook_filtra_por_estado_prioridad_categoria_y_texto():
    db.crear_tarea_outlook("Llamar al banco", prioridad="alta", categoria_outlook="Personal")
    t2 = db.crear_tarea_outlook("Revisar informe", prioridad="baja", categoria_outlook="Trabajo")
    db.completar_tarea_outlook(t2)

    assert len(db.listar_tareas_outlook(prioridad="alta")) == 1
    assert len(db.listar_tareas_outlook(categoria_outlook="Trabajo")) == 1
    assert len(db.listar_tareas_outlook(estado="completada")) == 1
    assert len(db.listar_tareas_outlook(texto="banco")) == 1
    assert len(db.listar_tareas_outlook(texto="no existe")) == 0


def test_listar_tareas_outlook_filtra_por_rango_de_vencimiento():
    db.crear_tarea_outlook("Antes de rango", fecha_vencimiento="2026-01-01")
    db.crear_tarea_outlook("Dentro de rango", fecha_vencimiento="2026-02-15")
    db.crear_tarea_outlook("Después de rango", fecha_vencimiento="2026-03-01")

    dentro = db.listar_tareas_outlook(desde="2026-02-01", hasta="2026-02-28")
    assert [t["asunto"] for t in dentro] == ["Dentro de rango"]


def test_eliminar_y_restaurar_tarea_outlook():
    tid = db.crear_tarea_outlook("Tarea")
    db.eliminar_tarea_outlook(tid)
    assert db.obtener_tarea_outlook(tid) is None
    assert any(item["origen"] == "tarea_outlook" and item["id"] == tid for item in db.papelera())

    db.restaurar_tarea_outlook(tid)
    assert db.obtener_tarea_outlook(tid) is not None
    assert not any(item["origen"] == "tarea_outlook" and item["id"] == tid for item in db.papelera())


def test_eliminar_tarea_outlook_definitivamente():
    tid = db.crear_tarea_outlook("Tarea")
    db.eliminar_tarea_outlook(tid)
    db.eliminar_tarea_outlook_definitivamente(tid)
    assert not any(item["origen"] == "tarea_outlook" and item["id"] == tid for item in db.papelera())


def test_vaciar_papelera_antigua_incluye_tareas_outlook(monkeypatch):
    tid_vieja = db.crear_tarea_outlook("Vieja")
    tid_reciente = db.crear_tarea_outlook("Reciente")

    hace_40_dias = (datetime.now() - timedelta(days=40)).isoformat(timespec="microseconds")
    hace_1_dia = (datetime.now() - timedelta(days=1)).isoformat(timespec="microseconds")

    monkeypatch.setattr(db, "_marca_papelera", lambda: hace_40_dias)
    db.eliminar_tarea_outlook(tid_vieja)
    monkeypatch.setattr(db, "_marca_papelera", lambda: hace_1_dia)
    db.eliminar_tarea_outlook(tid_reciente)

    db.vaciar_papelera_antigua(dias=30)

    ids_en_papelera = {item["id"] for item in db.papelera() if item["origen"] == "tarea_outlook"}
    assert tid_vieja not in ids_en_papelera
    assert tid_reciente in ids_en_papelera


def test_listar_categorias_outlook():
    db.crear_tarea_outlook("A", categoria_outlook="Trabajo")
    db.crear_tarea_outlook("B", categoria_outlook="Personal")
    db.crear_tarea_outlook("C", categoria_outlook="Trabajo")
    db.crear_tarea_outlook("D")  # sin categoría

    assert db.listar_categorias_outlook() == ["Personal", "Trabajo"]


def test_obtener_tarea_outlook_por_entry_id():
    tid = db.crear_tarea_outlook("Tarea", outlook_entry_id="ABC123")
    tarea = db.obtener_tarea_outlook_por_entry_id("ABC123")
    assert tarea is not None
    assert tarea["id"] == tid
    assert db.obtener_tarea_outlook_por_entry_id("NO-EXISTE") is None
