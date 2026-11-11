"""Copiloto en contexto (W2): la ficha del cliente enseña qué toca ahora, se ejecuta desde allí y deja la pregunta lista para el asistente."""
import re
from datetime import date, timedelta

from app import db, ia_propuestas as ip, verticales
from tests.conftest import iniciar_sesion_de_prueba


def _web(cliente, email):
    u = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant(f"Copiloto {email}")
    db.asignar_tenant(u, t)
    verticales.fijar_activo(t, "contabilizacion", True)
    ip._ULTIMA_GENERACION.clear()
    return u, t


def test_la_ficha_enseña_las_propuestas_y_avisos_de_ese_cliente_y_solo_de_el(cliente):
    u, t = _web(cliente, "copiloto@ejemplo.com")
    fid = db.crear_cliente_fiscal(t, "Cliente Copiloto SL", email="c@ejemplo.com")
    otro = db.crear_cliente_fiscal(t, "Otro Cliente SL", email="o@ejemplo.com")
    cid = db.obtener_cliente_fiscal(t, fid)["cliente_id"]
    db.crear_vencimiento_fiscal(t, fid, "303", "3T", (date.today() - timedelta(days=2)).isoformat())            # alerta: vencido sin presentar
    db.crear_vencimiento_fiscal(t, otro, "111", "3T", (date.today() - timedelta(days=2)).isoformat())          # de otro cliente
    v = db.crear_vencimiento_fiscal(t, fid, "130", "3T", (date.today() + timedelta(days=5)).isoformat())
    conn = db.get_connection()
    conn.execute("UPDATE vencimientos_fiscales SET documento_solicitado = 'Libro de ingresos' WHERE id = ?", (v,))
    conn.commit(); conn.close()
    html = cliente.get(f"/clientes/{cid}").get_data(as_text=True)
    assert "Qué toca ahora con este cliente" in html
    assert "Modelo 303 de Cliente Copiloto SL sin presentar" in html and "Modelo 111" not in html
    assert "El modelo 130 (3T) vence en 5 días" in html and "Falta por llegar: Libro de ingresos." in html
    assert "/ia/?q=" in html and "Preguntar al asistente sobre este cliente" in html


def test_crear_tarea_desde_la_ficha_ejecuta_la_propuesta_y_vuelve_a_la_ficha(cliente):
    u, t = _web(cliente, "copiloto-2@ejemplo.com")
    fid = db.crear_cliente_fiscal(t, "Cliente Dos SL", email="c2@ejemplo.com")
    cid = db.obtener_cliente_fiscal(t, fid)["cliente_id"]
    db.crear_vencimiento_fiscal(t, fid, "303", "3T", (date.today() - timedelta(days=2)).isoformat())
    html = cliente.get(f"/clientes/{cid}").get_data(as_text=True)
    accion = re.search(r'action="(/ia/propuestas/\d+/aprobar)"><input type="hidden" name="volver" value="([^"]+)"', html)
    r = cliente.post(accion.group(1), data={"volver": accion.group(2)})
    assert r.status_code == 302 and r.headers["Location"].startswith(f"/clientes/{cid}") and "aviso=aprobada" in r.headers["Location"]
    assert "Qué toca ahora" not in cliente.get(f"/clientes/{cid}").get_data(as_text=True)                 # ya hecha: no insiste
    assert ip.contar(t) == 0
    r = cliente.post(accion.group(1).replace("aprobar", "rechazar"), data={"volver": "//evil.example/x"})
    assert "evil.example" not in r.headers["Location"]                                                  # el destino de vuelta solo puede ser local


def test_un_cliente_sin_nada_pendiente_no_enseña_la_caja(cliente):
    u, t = _web(cliente, "copiloto-3@ejemplo.com")
    fid = db.crear_cliente_fiscal(t, "Cliente Tres SL", email="c3@ejemplo.com")
    cid = db.obtener_cliente_fiscal(t, fid)["cliente_id"]
    assert "Qué toca ahora" not in cliente.get(f"/clientes/{cid}").get_data(as_text=True)
