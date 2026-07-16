"""Tests de import/export de tareas en formato Outlook (.ics / .csv):
app/outlook_ics.py.
"""
import pytest

from app import db, outlook_ics


def _tarea_completa(usuario_id):
    return db.crear_tarea_outlook(
        usuario_id,
        "Llamar al banco",
        cuerpo="Preguntar por la hipoteca",
        prioridad="alta",
        fecha_inicio="2026-07-10",
        fecha_vencimiento="2026-07-15",
        categoria_outlook="Personal",
    )


# --- ICS ---------------------------------------------------------------------

def test_exportar_ics_contiene_los_campos_principales(usuario_id):
    _tarea_completa(usuario_id)
    ics = outlook_ics.exportar_ics(db.listar_tareas_outlook(usuario_id))
    assert "BEGIN:VTODO" in ics
    assert "SUMMARY:Llamar al banco" in ics
    assert "PRIORITY:1" in ics
    assert "CATEGORIES:Personal" in ics
    assert "DUE" in ics


def test_roundtrip_ics_exportar_e_importar_de_vuelta(usuario_id):
    tid = _tarea_completa(usuario_id)
    ics = outlook_ics.exportar_ics(db.listar_tareas_outlook(usuario_id))

    db.eliminar_tarea_outlook_definitivamente(usuario_id, tid)
    assert db.obtener_tarea_outlook(usuario_id, tid) is None

    resumen = outlook_ics.importar_ics(usuario_id, ics)
    assert resumen == {"creadas": 1, "actualizadas": 0, "omitidas": 0}

    tareas = db.listar_tareas_outlook(usuario_id)
    assert len(tareas) == 1
    t = tareas[0]
    assert t["asunto"] == "Llamar al banco"
    assert t["cuerpo"] == "Preguntar por la hipoteca"
    assert t["prioridad"] == "alta"
    assert t["categoria_outlook"] == "Personal"
    assert t["fecha_inicio"][:10] == "2026-07-10"
    assert t["fecha_vencimiento"][:10] == "2026-07-15"


def test_importar_ics_reconoce_uid_y_actualiza_en_vez_de_duplicar(usuario_id):
    tid = db.crear_tarea_outlook(usuario_id, "Tarea original", outlook_entry_id="UID-1")
    ics = (
        "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Test//ES\n"
        "BEGIN:VTODO\nUID:UID-1\nSUMMARY:Tarea renombrada\nSTATUS:COMPLETED\n"
        "PERCENT-COMPLETE:100\nEND:VTODO\nEND:VCALENDAR\n"
    )
    resumen = outlook_ics.importar_ics(usuario_id, ics)
    assert resumen == {"creadas": 0, "actualizadas": 1, "omitidas": 0}

    tareas = db.listar_tareas_outlook(usuario_id, estado="completada")
    assert len(tareas) == 1
    assert tareas[0]["id"] == tid
    assert tareas[0]["asunto"] == "Tarea renombrada"


def test_importar_ics_omite_vtodo_sin_asunto(usuario_id):
    ics = "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VTODO\nUID:X\nEND:VTODO\nEND:VCALENDAR\n"
    resumen = outlook_ics.importar_ics(usuario_id, ics)
    assert resumen == {"creadas": 0, "actualizadas": 0, "omitidas": 1}


def test_importar_ics_archivo_invalido_lanza_error_legible(usuario_id):
    with pytest.raises(outlook_ics.ErrorSincronizacionOutlook):
        outlook_ics.importar_ics(usuario_id, "esto no es un ics")


# --- CSV ---------------------------------------------------------------------

def test_roundtrip_csv_exportar_e_importar_de_vuelta(usuario_id):
    _tarea_completa(usuario_id)
    csv_texto = outlook_ics.exportar_csv_outlook(db.listar_tareas_outlook(usuario_id))
    assert "Subject" in csv_texto.splitlines()[0]

    db.eliminar_tarea_outlook_definitivamente(usuario_id, db.listar_tareas_outlook(usuario_id)[0]["id"])
    resumen = outlook_ics.importar_csv_outlook(usuario_id, csv_texto)
    assert resumen == {"creadas": 1, "actualizadas": 0, "omitidas": 0}

    tareas = db.listar_tareas_outlook(usuario_id)
    assert len(tareas) == 1
    t = tareas[0]
    assert t["asunto"] == "Llamar al banco"
    assert t["prioridad"] == "alta"
    assert t["categoria_outlook"] == "Personal"
    assert t["fecha_vencimiento"][:10] == "2026-07-15"


def test_importar_csv_acepta_variaciones_de_fecha_y_encabezado(usuario_id):
    csv_texto = (
        "Subject,Start Date,Due Date,Status,% Complete,Priority,Categories,Body,Date Completed\n"
        "Revisar informe,7/10/2026,7/15/2026,In Progress,50,High,Trabajo,,\n"
    )
    resumen = outlook_ics.importar_csv_outlook(usuario_id, csv_texto)
    assert resumen == {"creadas": 1, "actualizadas": 0, "omitidas": 0}

    t = db.listar_tareas_outlook(usuario_id)[0]
    assert t["estado"] == "en_progreso"
    assert t["prioridad"] == "alta"
    assert t["fecha_vencimiento"] == "2026-07-15"


def test_importar_csv_sin_columna_subject_lanza_error(usuario_id):
    with pytest.raises(outlook_ics.ErrorSincronizacionOutlook):
        outlook_ics.importar_csv_outlook(usuario_id, "Foo,Bar\n1,2\n")


def test_importar_csv_omite_filas_sin_asunto(usuario_id):
    csv_texto = "Subject,Priority\n,High\n"
    resumen = outlook_ics.importar_csv_outlook(usuario_id, csv_texto)
    assert resumen == {"creadas": 0, "actualizadas": 0, "omitidas": 1}
