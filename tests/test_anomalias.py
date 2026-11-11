"""Alertas de anomalías (W7): cada regla salta cuando toca, no salta cuando no, y explica por qué."""
from datetime import date, timedelta

import pytest

from app import anomalias, db, facturas_contables as fc, verticales

HOY = date(2026, 11, 11)


_N = [0]


def _t():
    _N[0] += 1
    t = db.crear_tenant(f"Anomalías {_N[0]}")
    verticales.fijar_activo(t, "contabilizacion", True)
    return t, db.crear_cliente_fiscal(t, "Cliente Alertas SL", email="a@ejemplo.com")


def _f(c, dias_atras, total="100,00", tipo="recibida", nombre="Proveedor", nif="B11111111", num=None):
    f = (HOY - timedelta(days=dias_atras)).isoformat()
    return fc.crear_desde_portal(c, {"tipo": tipo, "fecha": f, "numero": num or f"N-{dias_atras}-{total}", "tercero_nombre": nombre, "tercero_nif": nif, "total": total, "pct_iva": "21"})


def _tipos(t):
    return [a["tipo"] for a in anomalias.detectar(t, HOY)]


def test_un_cliente_que_dejo_de_subir_facturas_salta_y_uno_regular_no():
    t, c = _t()
    for d in (220, 190, 160, 130, 100):                      # una cada 30 días y la última hace 100 (más del triple del intervalo)
        _f(c, d)
    assert _tipos(t) == ["sin_facturas"]
    a = anomalias.detectar(t, HOY)[0]
    assert a["datos"]["dias_sin"] == 100 and a["datos"]["intervalo_habitual"] == 30
    t2, c2 = _t()
    for d in (90, 60, 30, 5):                                # al día
        _f(c2, d)
    assert "sin_facturas" not in _tipos(t2)


def test_un_cliente_con_pocas_facturas_no_genera_alerta():
    t, c = _t()
    _f(c, 200); _f(c, 150)
    assert _tipos(t) == []


def test_un_gasto_muy_por_encima_de_lo_habitual_salta_con_su_media():
    t, c = _t()
    for i in range(10):
        _f(c, 100 - i * 5, total=f"{100 + i},00", nombre=f"Proveedor {i}", nif=f"B2222222{i}")
    _f(c, 3, total="2500,00", nombre="Reformas Raras", nif="B33333333")
    alertas = [a for a in anomalias.detectar(t, HOY) if a["tipo"] == "gasto_atipico"]
    assert len(alertas) == 1 and alertas[0]["datos"]["importe"] == 250000 and alertas[0]["datos"]["proveedor"] == "Reformas Raras"


def test_un_gasto_normal_o_con_pocas_anteriores_no_salta():
    t, c = _t()
    for i in range(10):
        _f(c, 100 - i * 5, total=f"{100 + i},00", nombre=f"P{i}", nif=f"B2222222{i}")
    _f(c, 3, total="130,00", nombre="Normal", nif="B44444444")
    assert "gasto_atipico" not in _tipos(t)
    t2, c2 = _t()
    for i in range(3):
        _f(c2, 50 - i, total="100,00", nombre=f"P{i}", nif=f"B5555555{i}")
    _f(c2, 2, total="5000,00", nombre="Grande", nif="B66666666")
    assert "gasto_atipico" not in _tipos(t2)                 # sin histórico suficiente no se opina


def test_dos_facturas_iguales_cercanas_son_posible_duplicado():
    t, c = _t()
    _f(c, 10, total="250,00", num="A-1")
    _f(c, 9, total="250,00", num="A-2")
    _f(c, 8, total="250,00", nombre="Otro", nif="B77777777", num="A-3")        # otro proveedor: no cuenta
    d = [a for a in anomalias.detectar(t, HOY) if a["tipo"] == "duplicada"]
    assert len(d) == 1 and d[0]["severidad"] == "alta"


def test_vencimientos_sin_documentacion_y_vencidos():
    t, c = _t()
    v1 = db.crear_vencimiento_fiscal(t, c, "303", "3T", (HOY + timedelta(days=2)).isoformat())
    v2 = db.crear_vencimiento_fiscal(t, c, "111", "3T", (HOY + timedelta(days=6)).isoformat())
    v3 = db.crear_vencimiento_fiscal(t, c, "115", "3T", (HOY - timedelta(days=4)).isoformat())
    v4 = db.crear_vencimiento_fiscal(t, c, "130", "3T", (HOY + timedelta(days=30)).isoformat())
    conn = db.get_connection()
    for v in (v1, v2, v4):
        conn.execute("UPDATE vencimientos_fiscales SET documento_solicitado = 'Extracto del banco' WHERE id = ?", (v,))
    conn.commit(); conn.close()
    por = {(a["tipo"], a["modelo"]): a for a in anomalias.detectar(t, HOY)}
    assert por[("vencimiento_sin_documentos", "303")]["severidad"] == "alta" and por[("vencimiento_sin_documentos", "111")]["severidad"] == "media"
    assert por[("vencido_sin_presentar", "115")]["datos"]["dias"] == 4
    assert ("vencimiento_sin_documentos", "130") not in por                              # vence en 30 días: todavía no
    db.subir_documento_vencimiento(v1, "extracto.pdf", "application/pdf", b"%PDF-1.4\n%%EOF")
    assert ("vencimiento_sin_documentos", "303") not in {(a["tipo"], a.get("modelo")) for a in anomalias.detectar(t, HOY)}      # ya llegó algo




def test_la_pantalla_de_alertas_las_enseña_con_su_explicacion(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    t = db.crear_tenant("Anomalías web")
    u = iniciar_sesion_de_prueba(cliente, "alertas-web@ejemplo.com", "contrasena123")
    db.asignar_tenant(u, t)
    c = db.crear_cliente_fiscal(t, "Cliente Web SL", email="w@ejemplo.com")
    v = db.crear_vencimiento_fiscal(t, c, "303", "3T", (date.today() - timedelta(days=3)).isoformat())
    html = cliente.get("/fiscal/alertas").get_data(as_text=True)
    assert "Modelo 303 de Cliente Web SL sin presentar" in html and "La fecha límite pasó hace 3 días." in html and f"/fiscal/vencimientos/{v}/editar" in html
    db.eliminar_vencimiento_fiscal(t, v) if hasattr(db, "eliminar_vencimiento_fiscal") else None
