"""Preguntar a los propios datos con fuentes (W6): solo contesta con lo encontrado, quita citas inventadas y avisa si no cita nada."""
import pytest

from app import busqueda, busqueda_respuestas as br, db, ia_asistente
from tests.conftest import iniciar_sesion_de_prueba

HITS = [{"id": "tarea-3", "tipo": "tarea", "texto": "Preparar el 303 de Ferretería Paco\nFalta el extracto del banco", "creada_en": "2026-11-02"},
        {"id": "mensaje-9", "tipo": "mensaje", "texto": "Duda sobre el IVA del tercer trimestre de Ferretería Paco: ¿deducimos la factura del taller?", "creada_en": "2026-11-05"},
        {"id": "nota-1", "tipo": "nota", "texto": "Recordar llamar a Paco", "creada_en": "2026-10-30"}]


def _falso(monkeypatch, hits=HITS, respuesta="Falta el extracto del banco [1] y preguntó por la factura del taller [2]."):
    vistos = []
    monkeypatch.setattr(busqueda, "buscar_hibrido", lambda uid, q, limite, tenant_id=None, tipos=None, con_respaldo=False: hits)
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda uid, sistema, contenido: vistos.append((sistema, contenido)) or respuesta)
    return vistos


def test_contesta_con_fuentes_numeradas_y_la_ia_solo_recibe_los_fragmentos(monkeypatch, app_context=None):
    from app.main import app
    vistos = _falso(monkeypatch)
    with app.test_request_context():
        r = br.responder(1, None, "¿Qué falta de Ferretería Paco?")
    assert r["respuesta"].startswith("Falta el extracto") and r["citadas"] == [1, 2] and r["sin_fuentes"] is False
    assert [f["n"] for f in r["fuentes"]] == [1, 2, 3] and r["fuentes"][0]["destino"] == "/tareas/3" and r["fuentes"][1]["destino"] == "/correo/9"
    sistema, cuerpo = vistos[0]
    assert "EXCLUSIVAMENTE" in sistema and "[1] (tarea) Preparar el 303" in cuerpo and "[2] (mensaje)" in cuerpo and "Pregunta: ¿Qué falta de Ferretería Paco?" in cuerpo


def test_las_citas_inventadas_se_quitan_y_una_respuesta_sin_citas_se_marca(monkeypatch):
    from app.main import app
    _falso(monkeypatch, respuesta="Dato cierto [1] y otro inventado [7], más [99].")
    with app.test_request_context():
        r = br.responder(1, None, "pregunta cualquiera")
    assert r["respuesta"] == "Dato cierto [1] y otro inventado , más ." and r["citadas"] == [1]
    _falso(monkeypatch, respuesta="Creo que sí, pero no sé de dónde.")
    with app.test_request_context():
        r = br.responder(1, None, "pregunta cualquiera")
    assert r["citadas"] == [] and r["sin_fuentes"] is True


def test_sin_resultados_o_sin_pregunta_no_se_llama_a_la_ia(monkeypatch):
    from app.main import app
    vistos = _falso(monkeypatch, hits=[])
    with app.test_request_context():
        with pytest.raises(br.ErrorPregunta, match="No he encontrado nada"):
            br.responder(1, None, "algo que no existe")
        with pytest.raises(br.ErrorPregunta, match="Escribe una pregunta"):
            br.responder(1, None, "  ")
    assert vistos == []


def test_la_pantalla_pregunta_y_enseña_respuesta_y_fuentes(cliente, monkeypatch):
    u = iniciar_sesion_de_prueba(cliente, "preguntar@ejemplo.com", "contrasena123")
    db.asignar_tenant(u, db.crear_tenant("Preguntar"))
    _falso(monkeypatch)
    monkeypatch.setattr(ia_asistente, "disponible", lambda uid, tarea="asistente": True)
    assert "Tu pregunta" in cliente.get("/ia/preguntar").get_data(as_text=True)
    html = cliente.post("/ia/preguntar", data={"pregunta": "¿Qué falta de Ferretería Paco?"}).get_data(as_text=True)
    assert "Falta el extracto del banco [1]" in html and 'href="/tareas/3"' in html and 'id="fuente-2"' in html and "no cita ninguna fuente" not in html
    _falso(monkeypatch, respuesta="Sin citas.")
    assert "no cita ninguna fuente" in cliente.post("/ia/preguntar", data={"pregunta": "otra pregunta"}).get_data(as_text=True)
