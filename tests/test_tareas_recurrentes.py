"""Tareas recurrentes (app/db.py: *_tarea_recurrente y
generar_tareas_recurrentes) -- reglas semanales/mensuales que generan
tareas_outlook automáticamente solo el día que les toca, y la capa ruta
que las gestiona (app/rutas_tareas.py)."""
import calendar
import re
from datetime import datetime

from tests.conftest import iniciar_sesion_de_prueba

from app import db


def test_crear_y_listar_tarea_recurrente(usuario_id):
    regla_id = db.crear_tarea_recurrente(usuario_id, "Revisar correo", "semanal", 0)
    reglas = db.listar_tareas_recurrentes(usuario_id)
    assert len(reglas) == 1
    assert reglas[0]["id"] == regla_id
    assert reglas[0]["asunto"] == "Revisar correo"
    assert reglas[0]["periodicidad"] == "semanal"
    assert reglas[0]["dia"] == 0
    assert reglas[0]["activa"] == 1


def test_alternar_activa_tarea_recurrente(usuario_id):
    regla_id = db.crear_tarea_recurrente(usuario_id, "Cierre mensual", "mensual", 1)
    db.alternar_activa_tarea_recurrente(usuario_id, regla_id)
    assert db.listar_tareas_recurrentes(usuario_id)[0]["activa"] == 0
    db.alternar_activa_tarea_recurrente(usuario_id, regla_id)
    assert db.listar_tareas_recurrentes(usuario_id)[0]["activa"] == 1


def test_eliminar_tarea_recurrente(usuario_id):
    regla_id = db.crear_tarea_recurrente(usuario_id, "Efímera", "semanal", 2)
    db.eliminar_tarea_recurrente(usuario_id, regla_id)
    assert db.listar_tareas_recurrentes(usuario_id) == []


def test_alternar_y_eliminar_de_otro_usuario_no_hacen_nada(usuario_id):
    regla_id = db.crear_tarea_recurrente(usuario_id, "Mía", "semanal", 0)
    otro_usuario_id = usuario_id + 999  # inexistente a propósito
    db.alternar_activa_tarea_recurrente(otro_usuario_id, regla_id)
    db.eliminar_tarea_recurrente(otro_usuario_id, regla_id)
    reglas = db.listar_tareas_recurrentes(usuario_id)
    assert len(reglas) == 1
    assert reglas[0]["activa"] == 1


def test_generar_tareas_recurrentes_solo_el_dia_que_toca_semanal(usuario_id):
    hoy_semana = datetime.now().weekday()
    otro_dia_semana = (hoy_semana + 1) % 7
    db.crear_tarea_recurrente(usuario_id, "Hoy toca", "semanal", hoy_semana)
    db.crear_tarea_recurrente(usuario_id, "Hoy no toca", "semanal", otro_dia_semana)
    creadas = db.generar_tareas_recurrentes()
    assert creadas == 1
    asuntos = {t["asunto"] for t in db.listar_tareas_outlook(usuario_id)}
    assert asuntos == {"Hoy toca"}


def test_generar_tareas_recurrentes_solo_el_dia_que_toca_mensual(usuario_id):
    hoy = datetime.now()
    otro_dia_mes = 1 if hoy.day != 1 else 2
    db.crear_tarea_recurrente(usuario_id, "Hoy toca", "mensual", hoy.day)
    db.crear_tarea_recurrente(usuario_id, "Hoy no toca", "mensual", otro_dia_mes)
    creadas = db.generar_tareas_recurrentes()
    assert creadas == 1
    asuntos = {t["asunto"] for t in db.listar_tareas_outlook(usuario_id)}
    assert asuntos == {"Hoy toca"}


def test_generar_tareas_recurrentes_dia_mensual_fuera_de_rango_usa_ultimo_dia_del_mes(usuario_id):
    hoy = datetime.now()
    ultimo_dia_mes = calendar.monthrange(hoy.year, hoy.month)[1]
    if hoy.day != ultimo_dia_mes:
        # Solo aplicable el último día del mes -- en cualquier otro día del
        # mes, una regla con dia=31 simplemente no le toca hoy todavía.
        db.crear_tarea_recurrente(usuario_id, "Fin de mes", "mensual", 31)
        assert db.generar_tareas_recurrentes() == 0
        return
    db.crear_tarea_recurrente(usuario_id, "Fin de mes", "mensual", 31)
    creadas = db.generar_tareas_recurrentes()
    assert creadas == 1


def test_generar_tareas_recurrentes_es_idempotente_el_mismo_dia(usuario_id):
    db.crear_tarea_recurrente(usuario_id, "Semanal", "semanal", datetime.now().weekday())
    db.generar_tareas_recurrentes()
    creadas_segunda_vez = db.generar_tareas_recurrentes()
    assert creadas_segunda_vez == 0
    assert len(db.listar_tareas_outlook(usuario_id)) == 1


def test_generar_tareas_recurrentes_ignora_reglas_pausadas(usuario_id):
    regla_id = db.crear_tarea_recurrente(usuario_id, "Pausada", "semanal", datetime.now().weekday())
    db.alternar_activa_tarea_recurrente(usuario_id, regla_id)
    creadas = db.generar_tareas_recurrentes()
    assert creadas == 0
    assert db.listar_tareas_outlook(usuario_id) == []


# --- Capa ruta ------------------------------------------------------------

def test_recurrentes_requiere_login(cliente):
    resp = cliente.get("/tareas/recurrentes")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_crear_pausar_y_eliminar_regla_desde_la_ruta(cliente):
    iniciar_sesion_de_prueba(cliente, "recurrentes@ejemplo.com", "contrasena123")

    resp = cliente.post("/tareas/recurrentes", data={"asunto": "Backup semanal", "periodicidad": "semanal", "dia": "0"})
    assert resp.status_code == 302

    resp = cliente.get("/tareas/recurrentes")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Backup semanal" in html

    match = re.search(r"/tareas/recurrentes/(\d+)/alternar", html)
    assert match is not None
    regla_id = match.group(1)

    resp = cliente.post(f"/tareas/recurrentes/{regla_id}/alternar")
    assert resp.status_code == 302
    assert "Pausada" in cliente.get("/tareas/recurrentes").get_data(as_text=True)

    resp = cliente.post(f"/tareas/recurrentes/{regla_id}/eliminar")
    assert resp.status_code == 302
    assert "Backup semanal" not in cliente.get("/tareas/recurrentes").get_data(as_text=True)


def test_crear_regla_sin_asunto_no_crea_nada(cliente):
    iniciar_sesion_de_prueba(cliente, "recurrentes-vacio@ejemplo.com", "contrasena123")
    cliente.post("/tareas/recurrentes", data={"asunto": "", "periodicidad": "semanal", "dia": "0"})
    assert "Todavía no tienes" in cliente.get("/tareas/recurrentes").get_data(as_text=True)
