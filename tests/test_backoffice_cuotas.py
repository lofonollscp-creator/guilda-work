"""Cuotas y uso por despacho: usuarios del plan, almacenamiento, facturas del mes e IA, con avisos al 80 % y al 100 %."""
from datetime import datetime

import pytest

from app import almacen_objetos as ao, db, db_fiscal
from backoffice import cartera, cuotas
from tests.test_almacen_objetos import PDF, _despacho  # noqa: F401
from tests.test_backoffice_app import bo, entrar, post  # noqa: F401 -- fixture

AHORA = datetime(2026, 11, 15, 12, 0)


@pytest.fixture(autouse=True)
def _aislar(bo):
    yield
    ao.fijar_almacen(None, fijo=False)


def _fila(nombre):
    return next(f for f in cuotas.uso(AHORA) if f["nombre"] == nombre)


def test_sin_topes_todo_esta_ok_y_cuenta_el_uso():
    t, u, c = _despacho("Sin topes")
    db_fiscal.archivar_documento_cliente(u, c, "a.pdf", "application/pdf", PDF)
    f = _fila("Sin topes")
    assert f["peor"] == "ok" and f["usuarios"]["usado"] == 1 and f["almacenamiento"]["usado"] >= 0 and f["almacenamiento"]["limite"] is None


def test_los_niveles_aviso_y_excedido_siguen_el_porcentaje():
    t, u, c = _despacho("Con topes")
    cuotas.fijar(t, 100, 10, "jorge")
    conn = db.get_connection()
    conn.execute("INSERT INTO ia_consumo (tenant_id, mes, usadas) VALUES (?, ?, 85)", (t, "2026-11"))
    conn.execute("UPDATE tenants SET ia_limite_mensual = 100 WHERE id = ?", (t,))
    conn.commit()
    conn.close()
    f = _fila("Con topes")
    assert f["ia"]["nivel"] == "aviso" and f["ia"]["pct"] == 85 and f["peor"] == "aviso"
    conn = db.get_connection()
    conn.execute("UPDATE ia_consumo SET usadas = 100 WHERE tenant_id = ?", (t,))
    conn.commit()
    conn.close()
    assert _fila("Con topes")["peor"] == "excedido"
    avisos = cuotas.avisos(AHORA)
    assert [a["nombre"] for a in avisos] == ["Con topes"] and avisos[0]["nivel"] == "excedido" and "IA" in avisos[0]["motivos"][0]


def test_el_almacenamiento_cuenta_dentro_y_fuera_de_la_base(tmp_path):
    ao.fijar_almacen(ao.AlmacenFichero(tmp_path / "o"))
    t, u, c = _despacho("Mucho")
    db_fiscal.archivar_documento_cliente(u, c, "a.pdf", "application/pdf", PDF * 100)
    cuotas.fijar(t, 0, None)                                                 # tope 0 con uso: excedido
    f = _fila("Mucho")
    assert f["almacenamiento"]["limite"] == 0 and f["almacenamiento"]["nivel"] == "excedido"


def test_valores_negativos_se_rechazan_y_vacio_quita_el_tope():
    t, u, c = _despacho("Valida")
    with pytest.raises(ValueError):
        cuotas.fijar(t, -1, None)
    cuotas.fijar(t, 50, 5)
    cuotas.fijar(t, None, None)
    assert _fila("Valida")["almacenamiento"]["limite"] is None


def test_el_resumen_semanal_incluye_las_cuotas(bo):
    t, u, c = _despacho("Resumen")
    conn = db.get_connection()
    conn.execute("INSERT INTO ia_consumo (tenant_id, mes, usadas) VALUES (?, ?, 5)", (t, datetime.now().strftime("%Y-%m")))
    conn.execute("UPDATE tenants SET ia_limite_mensual = 5 WHERE id = ?", (t,))
    conn.commit()
    conn.close()
    texto = cartera.texto_resumen(cartera.construir_resumen())
    assert "CUOTAS" in texto and "Resumen [EXCEDIDO]" in texto


def test_pantalla_y_guardado_en_el_backoffice(bo):
    entrar(bo)
    t, u, c = _despacho("Pantalla cuotas")
    assert "Pantalla cuotas" in bo.get("/cuotas").get_data(as_text=True)
    assert post(bo, f"/tenants/{t}/cuotas", almacenamiento_mb="500", facturas_mes="").status_code == 302
    assert 'value="500"' in bo.get("/cuotas").get_data(as_text=True)
    post(bo, f"/tenants/{t}/cuotas", almacenamiento_mb="abc", facturas_mes="")
    assert 'value="500"' in bo.get("/cuotas").get_data(as_text=True)          # el valor inválido no pisó el guardado
