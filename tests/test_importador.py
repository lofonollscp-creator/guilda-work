"""Tests de app/importador.py."""
import json

import pytest

from app import db, importador


def test_importar_json_crea_menu_notas_y_tareas(usuario_id):
    contenido = json.dumps({
        "registros": [
            {
                "origen": "nota", "texto_o_nombre": "Llamada a cliente", "categoria": "Lueira",
                "timestamp_inicio": "2026-01-01T10:00:00", "timestamp_fin": None,
                "tipo": None, "duracion_segundos": None,
            },
            {
                "origen": "tarea", "texto_o_nombre": "Reunión rápida", "categoria": "Lueira",
                "timestamp_inicio": "2026-01-01T11:00:00", "timestamp_fin": None,
                "tipo": "instantanea", "duracion_segundos": None,
            },
            {
                "origen": "tarea", "texto_o_nombre": "Proceso de despliegue", "categoria": "Guilda",
                "timestamp_inicio": "2026-01-01T09:00:00", "timestamp_fin": "2026-01-01T10:30:00",
                "tipo": "duracion", "duracion_segundos": 5400,
            },
        ]
    })

    resumen = importador.importar_json(usuario_id, contenido)

    assert resumen == {"notas": 1, "tareas": 2, "omitidos": 0}
    nombres_menus = {c["nombre"] for c in db.listar_categorias(usuario_id)}
    assert nombres_menus == {"Lueira", "Guilda"}

    historial = db.historial(usuario_id)
    assert len(historial) == 3
    tarea_duracion = next(f for f in historial if f["texto"] == "Proceso de despliegue")
    assert tarea_duracion["duracion_segundos"] == 5400
    assert tarea_duracion["estado"] == "finalizada"


def test_importar_json_omite_filas_invalidas_sin_abortar(usuario_id):
    contenido = json.dumps({
        "registros": [
            {"origen": "nota", "texto_o_nombre": "", "categoria": "Guilda", "timestamp_inicio": "2026-01-01T10:00:00"},
            {"origen": "nota", "texto_o_nombre": "Válida", "categoria": "Guilda", "timestamp_inicio": "no-es-una-fecha"},
            {"origen": "tarea", "texto_o_nombre": "Sin fin", "categoria": "Guilda", "tipo": "duracion",
             "timestamp_inicio": "2026-01-01T09:00:00", "timestamp_fin": None},
            {"origen": "nota", "texto_o_nombre": "Esta sí vale", "categoria": "Guilda",
             "timestamp_inicio": "2026-01-01T10:00:00"},
        ]
    })

    resumen = importador.importar_json(usuario_id, contenido)

    assert resumen == {"notas": 1, "tareas": 0, "omitidos": 3}


def test_importar_json_rechaza_formato_no_reconocido(usuario_id):
    with pytest.raises(importador.ErrorImportacion):
        importador.importar_json(usuario_id, "{}")
    with pytest.raises(importador.ErrorImportacion):
        importador.importar_json(usuario_id, "esto no es json")


def test_importar_json_recalcula_duracion_si_falta(usuario_id):
    contenido = json.dumps({
        "registros": [
            {
                "origen": "tarea", "texto_o_nombre": "Proceso", "categoria": "Guilda",
                "timestamp_inicio": "2026-01-01T09:00:00", "timestamp_fin": "2026-01-01T09:30:00",
                "tipo": "duracion", "duracion_segundos": None,
            },
        ]
    })

    importador.importar_json(usuario_id, contenido)

    tarea = db.historial(usuario_id)[0]
    assert tarea["duracion_segundos"] == 1800


def test_importar_csv_equivalente_al_json(usuario_id):
    contenido = (
        "origen,id,texto_o_nombre,tipo,estado,categoria,timestamp_inicio,timestamp_fin,duracion_segundos\n"
        "nota,1,Nota de prueba,,,Guilda,2026-01-01T10:00:00,,\n"
        "tarea,2,Proceso,duracion,finalizada,Guilda,2026-01-01T09:00:00,2026-01-01T09:15:00,900\n"
    )

    resumen = importador.importar_csv(usuario_id, contenido)

    assert resumen == {"notas": 1, "tareas": 1, "omitidos": 0}


def test_importar_csv_rechaza_columnas_inesperadas(usuario_id):
    with pytest.raises(importador.ErrorImportacion):
        importador.importar_csv(usuario_id, "columna_a,columna_b\n1,2\n")


def test_importar_reutiliza_menu_existente_por_nombre(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    contenido = json.dumps({
        "registros": [
            {"origen": "nota", "texto_o_nombre": "Nota", "categoria": "Guilda",
             "timestamp_inicio": "2026-01-01T10:00:00"},
        ]
    })

    importador.importar_json(usuario_id, contenido)

    assert len(db.listar_categorias(usuario_id)) == 1
    assert db.listar_categorias(usuario_id)[0]["id"] == cid
