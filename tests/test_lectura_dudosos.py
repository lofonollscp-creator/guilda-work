"""«Mira primero» (W5): la revisión de una factura leída con IA enseña antes los datos de los que la IA no está segura."""
import json
import re
from datetime import date

from app import db, facturas_contables as fc, lectura_facturas, verticales
from tests.conftest import iniciar_sesion_de_prueba


def test_los_campos_dudosos_salen_de_menos_a_mas_fiable_y_sin_el_nif_propio():
    ev = {"confianza": {"numero": 95, "fecha": 80, "emisor_nif": 55, "receptor_nif": 40, "total": 70, "base": 90, "iva": 100}}
    assert [d["campo"] for d in lectura_facturas.campos_dudosos(ev, "recibida")] == ["emisor_nif", "total", "fecha"]      # el receptor es el propio cliente: no se mira
    assert [d["campo"] for d in lectura_facturas.campos_dudosos(ev, "emitida")] == ["receptor_nif", "total", "fecha"]
    assert lectura_facturas.campos_dudosos(None) == [] and lectura_facturas.campos_dudosos({"confianza": {"total": 95}}) == []
    assert lectura_facturas.campos_dudosos(ev, umbral=60)[0] == {"campo": "emisor_nif", "confianza": 55}


def test_la_pantalla_de_revision_enseña_los_dudosos_primero(cliente):
    t = db.crear_tenant("Dudosos")
    u = iniciar_sesion_de_prueba(cliente, "dudosos@ejemplo.com", "contrasena123")
    db.asignar_tenant(u, t)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = db.crear_cliente_fiscal(t, "Cliente Dudoso SL", email="d@ejemplo.com")
    f = fc.crear_desde_portal(c, {"tipo": "recibida", "fecha": date.today().isoformat(), "numero": "D-1", "tercero_nombre": "Proveedor", "tercero_nif": "B11111111", "total": "121,00", "pct_iva": "21"})
    ev = {"origen": "texto", "campos": {}, "verificaciones": [], "confianza": {"numero": 98, "fecha": 97, "emisor_nif": 62, "receptor_nif": 99, "total": 71, "base": 95, "iva": 96}, "motivos": []}
    conn = db.get_connection()
    conn.execute("UPDATE facturas_contables SET lectura = 'ia', lectura_evidencia = ?, lectura_confianza = 75, lectura_fuente = 'texto' WHERE id = ?", (json.dumps(ev), f))
    conn.commit(); conn.close()
    html = cliente.get(f"/contabilidad/{f}").get_data(as_text=True)
    botones = re.findall(r'data-ir-campo="(\w+)">([^<]+)<', html)
    assert [b[0] for b in botones] == ["emisor_nif", "total"] and "NIF / CIF · 62 %" in botones[0][1] and "Total · 71 %" in botones[1][1]
    assert "Mira primero:" in html and "contabilidad_dudosos.js" in html
    conn = db.get_connection(); conn.execute("UPDATE facturas_contables SET estado = 'revisada' WHERE id = ?", (f,)); conn.commit(); conn.close()
    assert "data-ir-campo" not in cliente.get(f"/contabilidad/{f}").get_data(as_text=True)          # ya revisada: no hay nada que mirar primero
