"""Panel de calidad del Asistente jurídico (J7): cuenta lo que ya registra cada consulta; solo lo ve la dirección."""
import json
from datetime import date, timedelta

import pytest

from app import db, verticales
from app.juridico import asistente, calidad
from tests.conftest import iniciar_sesion_de_prueba


@pytest.fixture
def despacho(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "calidad-j@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho calidad jurídica")
    db.asignar_tenant(uid, t)
    db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "juridico", True)
    return cliente, uid, t


def _ejecucion(t, uid, conv, estado, *, traza=None, latencia=1000, modelo="modelo-a", dias_atras=1, pregunta="¿Plazo del modelo 303?"):
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO jur_ejecuciones (tenant_id, conversacion_id, usuario_id, pregunta, estado, modelo, latencia_ms, traza, creada_en, terminada_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (t, conv, uid, pregunta, estado, modelo, latencia, json.dumps(traza) if traza is not None else None, (date.today() - timedelta(days=dias_atras)).isoformat() + "T10:00:00", (date.today() - timedelta(days=dias_atras)).isoformat() + "T10:00:05"))
        conn.commit()
    finally:
        conn.close()


def test_el_resumen_separa_las_causas_de_no_responder(despacho):
    _c, uid, t = despacho
    conv = asistente.crear_conversacion(t, uid)
    _ejecucion(t, uid, conv, "answered", traza={"recuperados": [{"ref": "R1"}], "llamadas_llm": 1}, latencia=2000)
    _ejecucion(t, uid, conv, "answered", traza={"recuperados": [{"ref": "R1"}], "llamadas_llm": 2}, latencia=4000)
    _ejecucion(t, uid, conv, "insufficient_evidence", traza={"recuperados": [], "llamadas_llm": 0}, latencia=300, modelo=None)
    _ejecucion(t, uid, conv, "insufficient_evidence", traza={"recuperados": [{"ref": "R1"}], "llamadas_llm": 3, "problemas_de_validacion": ["La cita R9 no respalda la afirmación 2: no aparece 21"]}, latencia=9000)
    _ejecucion(t, uid, conv, "needs_context", traza={"recuperados": [{"ref": "R1"}], "llamadas_llm": 1})
    _ejecucion(t, uid, conv, "answered", traza={"llamadas_llm": 1}, dias_atras=200)                                      # fuera del periodo
    r = calidad.resumen(t, 30)
    assert r["total"] == 5 and r["por_estado"]["answered"] == 2 and r["pct_respondidas"] == 40.0
    assert r["sin_fuentes"] == 1 and r["citas_rechazadas"] == 1 and r["reparadas"] == 2
    assert r["latencia_mediana_ms"] == 2000 and r["latencia_p95_ms"] == 9000 and r["modelos"][0] == ("modelo-a", 4)
    assert {q["causa"] for q in r["sin_respuesta"]} == {"sin_fuentes", "citas_rechazadas", "falta_contexto"}
    assert r["motivos_de_rechazo"] and "no aparece 21" not in r["motivos_de_rechazo"][0][0]                              # agrupa por tipo, sin los números de cada consulta


def test_un_despacho_no_ve_las_consultas_de_otro(despacho):
    _c, uid, t = despacho
    otro = db.crear_tenant("Otro despacho jurídico")
    conv = asistente.crear_conversacion(t, uid)
    _ejecucion(t, uid, conv, "answered", traza={"llamadas_llm": 1})
    assert calidad.resumen(otro, 30)["total"] == 0


def test_la_pantalla_solo_es_de_la_direccion(despacho):
    cliente, uid, t = despacho
    conv = asistente.crear_conversacion(t, uid)
    _ejecucion(t, uid, conv, "insufficient_evidence", traza={"recuperados": [], "llamadas_llm": 0}, pregunta="Pregunta sin fuentes")
    html = cliente.get("/juridico/calidad")
    assert html.status_code == 200
    cuerpo = html.get_data(as_text=True)
    assert "Calidad del asistente" in cuerpo and "Pregunta sin fuentes" in cuerpo and "/juridico/calidad" in cliente.get("/juridico/").get_data(as_text=True)
    db.asignar_supervisor_tenant(uid, False)
    assert cliente.get("/juridico/calidad").status_code == 403
    assert "/juridico/calidad" not in cliente.get("/juridico/").get_data(as_text=True)
