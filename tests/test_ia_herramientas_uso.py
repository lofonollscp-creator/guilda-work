"""AA8: uso de las herramientas del asistente en un despacho, sacado de los mensajes que ya se guardan."""
from datetime import datetime, timedelta

from app import db, ia_herramientas_uso as u
from tests.conftest import iniciar_sesion_de_prueba


def _despacho(cliente, email):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    tid = db.crear_tenant("Despacho " + email)
    db.asignar_tenant(uid, tid)
    return uid, tid


def _tool(uid, nombre, contenido):
    db.agregar_mensaje_ia(uid, "tool", contenido=contenido, tool_call_id=f"c{datetime.now().timestamp()}", nombre_herramienta=nombre)


def test_cuenta_usos_errores_y_rechazos_solo_del_despacho(cliente):
    uid, tid = _despacho(cliente, "uso-a@ejemplo.com")
    for _ in range(5):
        _tool(uid, "listar_tareas", '{"tareas": []}')
    for _ in range(2):
        _tool(uid, "crear_tiquet", '{"error": "falta el título"}')
    _tool(uid, "crear_tiquet", '{"id": 3}')
    _tool(uid, "eliminar_tarea", '{"rechazado": true, "motivo": "El usuario ha rechazado esta acción."}')
    r = u.resumen(tid)
    assert r["total"] == 9 and r["errores"] == 2 and r["rechazadas"] == 1 and r["distintas"] == 3
    por = {t["herramienta"]: t for t in r["mas_usadas"]}
    assert por["listar_tareas"]["llamadas"] == 5 and por["listar_tareas"]["escribe"] is False and por["crear_tiquet"]["escribe"] is True
    assert [t["herramienta"] for t in r["conflictivas"]] == ["crear_tiquet"]          # 2 de 3 fallan; eliminar_tarea tiene un solo uso: ruido


def test_otro_despacho_y_fechas_antiguas_no_cuentan(cliente):
    uid, tid = _despacho(cliente, "uso-b@ejemplo.com")
    _tool(uid, "listar_tareas", "{}")
    assert u.resumen(tid, ahora=datetime.now() + timedelta(days=60))["total"] == 0
    assert u.resumen(tid + 999)["total"] == 0


def test_la_seccion_solo_la_ve_la_direccion(cliente):
    uid, tid = _despacho(cliente, "uso-c@ejemplo.com")
    _tool(uid, "listar_tareas", "{}")
    html = cliente.get("/ia/ajustes").get_data(as_text=True)
    assert ("uso-herramientas" in html) == (db.es_admin(uid) or __import__("app.ia_despacho", fromlist=["x"]).es_direccion(uid))
