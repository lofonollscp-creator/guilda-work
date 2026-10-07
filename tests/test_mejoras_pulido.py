"""Pulido: plurales del dashboard, panel de salud traducible y correos de
recordatorio en el idioma del cliente."""
from datetime import datetime, timedelta

from app import db, notificaciones_email, portal_recordatorios, salud
from tests.conftest import iniciar_sesion_de_prueba

HOY = datetime(2026, 4, 13, 9, 0)


def test_dashboard_usa_singular_y_plural(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "pulido-plural@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, db.crear_tenant("Gestoria Plural"))
    db.crear_tarea_outlook(uid, "Hoy", fecha_vencimiento=datetime.now().strftime("%Y-%m-%d"))
    html = cliente.get("/").get_data(as_text=True)
    assert 'dash-stat-label">tarea para hoy<' in html
    db.crear_tarea_outlook(uid, "Hoy 2", fecha_vencimiento=datetime.now().strftime("%Y-%m-%d"))
    assert 'dash-stat-label">tareas para hoy<' in cliente.get("/").get_data(as_text=True)
    db.cambiar_idioma_usuario(uid, "ca")
    assert 'dash-stat-label">tasques per avui<' in cliente.get("/").get_data(as_text=True)




def test_salud_sin_contexto_de_aplicacion_devuelve_espanol():
    assert salud._("%(n)s intento(s) fallido(s).", n=3) == "3 intento(s) fallido(s)."
    assert salud._("Ninguno.") == "Ninguno."


def _cliente_con_idioma(idioma, email):
    tenant = db.crear_tenant(f"Gestoria {email}")
    cid = db.crear_cliente_fiscal(tenant, "Panadería", email=email)
    db.editar_cliente_fiscal(tenant, cid, idioma=idioma)
    db.crear_vencimiento_fiscal(tenant, cid, "303", "2026-T1", (HOY + timedelta(days=2)).strftime("%Y-%m-%d"))


def test_recordatorio_en_el_idioma_del_cliente(monkeypatch):
    enviados = []
    monkeypatch.setattr(notificaciones_email, "configurado", lambda: True)
    monkeypatch.setattr(notificaciones_email, "_enviar", lambda d, a, c: enviados.append((d, a, c)))
    for idioma in ("es", "ca", "en", "fr"):
        _cliente_con_idioma(idioma, f"{idioma}@ejemplo.com")
    assert portal_recordatorios.procesar_recordatorios(HOY) == 4
    asuntos = {d.split("@")[0]: a for d, a, _ in enviados}
    assert asuntos["es"] == "Recordatorio: el 303 vence dentro de 2 días"
    assert asuntos["ca"] == "Recordatori: el 303 venç d'aquí a 2 dies"
    assert asuntos["en"] == "Reminder: 303 is due in 2 days"
    assert asuntos["fr"].startswith("Rappel : le 303")
    cuerpo_en = next(c for d, a, c in enviados if d.startswith("en@"))
    assert "Kind regards" in cuerpo_en and "Hello, Panadería" in cuerpo_en


def test_idioma_del_cliente_desde_su_ficha(cliente):
    gestor = iniciar_sesion_de_prueba(cliente, "pulido-ficha@ejemplo.com", "contrasena123")
    tenant = db.crear_tenant("Gestoria Idioma")
    db.asignar_tenant(gestor, tenant)
    cid = db.crear_cliente_fiscal(tenant, "Cli", email="c@ejemplo.com")
    assert db.obtener_cliente_fiscal(tenant, cid)["idioma"] == "es"
    cliente.post(f"/fiscal/clientes/{cid}/editar", data={"nombre": "Cli", "pais": "ES", "idioma": "ca"})
    assert db.obtener_cliente_fiscal(tenant, cid)["idioma"] == "ca"
    cliente.post(f"/fiscal/clientes/{cid}/editar", data={"nombre": "Cli", "pais": "ES", "idioma": "xx"})
    assert db.obtener_cliente_fiscal(tenant, cid)["idioma"] == "es"
