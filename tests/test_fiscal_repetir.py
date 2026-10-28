"""Repetir un apunte cada mes (alquileres y gastos fijos): fechas, retención, numeración, idempotencia y límites."""
from datetime import date

import pytest

from app import db, fiscal_nucleo as fn, fiscal_perfiles as fp
from app.db_fiscal import crear_cliente_fiscal
from tests.escenarios_303 import compra, venta

NIF = "A12345674"
RET = {"modelo": "115", "clave": "", "base": 100000, "pct": 1900}


def _despacho(nombre="Despacho repetir"):
    t = db.crear_tenant(nombre)
    u = db.crear_usuario_vinculado_a_kratos("repetir@ejemplo.com", "k-repetir"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    c = crear_cliente_fiscal(t, "Empresa de prueba SL", nif=NIF)
    fp.guardar_perfil(t, u, c, {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    return t, u, c


def test_los_meses_se_cuentan_desde_la_fecha_original_y_recortan_el_dia():
    assert fn._mes_despues("2026-01-31", 1) == "2026-02-28" and fn._mes_despues("2026-01-31", 2) == "2026-03-31" and fn._mes_despues("2026-11-15", 3) == "2027-02-15"


def test_un_alquiler_se_repite_con_su_retencion_y_no_duplica():
    t, u, c = _despacho()
    ap = fn.aprobar_apunte(t, u, c, compra(100000, 2100, numero="ALQ-1", fecha=date(2026, 1, 5), clave="11", contraparte_nif="B22222222"), retencion=RET)
    r = fn.repetir_apunte(t, u, c, ap["id"], hasta="2026-04", hoy=date(2026, 10, 28))
    assert len(r["creados"]) == 3 and r["ya_existian"] == 0 and r["futuros"] == 0
    filas = [f for f in fn.listar_apuntes(t, u, c) if f["id"] in r["creados"]]
    assert [f["fecha_expedicion"] for f in filas] == ["2026-02-05", "2026-03-05", "2026-04-05"]
    assert [f["numero"] for f in filas] == ["ALQ-1-202602", "ALQ-1-202603", "ALQ-1-202604"]
    assert all(f["retencion_modelo"] == "115" and f["retencion_centimos"] == 19000 and f["clave"] == "11" for f in filas)
    # volver a lanzar no duplica; ampliar solo crea lo nuevo
    r2 = fn.repetir_apunte(t, u, c, ap["id"], hasta="2026-05", hoy=date(2026, 10, 28))
    assert len(r2["creados"]) == 1 and r2["ya_existian"] == 3
    # entran en la simulación del 115 del 1T (enero + febrero + marzo)
    assert fn.simular_retenciones(t, u, c, 2026, "1T")["115"].casillas["03"] == 3 * 19000


def test_no_se_crean_apuntes_con_fecha_futura():
    t, u, c = _despacho("Despacho repetir 2")
    ap = fn.aprobar_apunte(t, u, c, compra(50000, 2100, numero="G-1", fecha=date(2026, 8, 20)))
    r = fn.repetir_apunte(t, u, c, ap["id"], hasta="2026-12", hoy=date(2026, 10, 28))
    assert len(r["creados"]) == 2 and r["futuros"] == 2                      # septiembre y octubre; noviembre y diciembre aún no


def test_una_emitida_sigue_la_numeracion_de_la_serie():
    t, u, c = _despacho("Despacho repetir 3")
    ap = fn.aprobar_apunte(t, u, c, venta(30000, 2100, numero="A-0007", fecha=date(2026, 3, 1)))
    r = fn.repetir_apunte(t, u, c, ap["id"], hasta="2026-05", hoy=date(2026, 10, 28))
    assert [f["numero"] for f in fn.listar_apuntes(t, u, c) if f["id"] in r["creados"]] == ["A-0008", "A-0009"]


def test_limites_y_errores():
    t, u, c = _despacho("Despacho repetir 4")
    ap = fn.aprobar_apunte(t, u, c, compra(50000, 2100, numero="G-1", fecha=date(2026, 3, 20)))
    for malo in ("", "2026-3", "2026-03", "2025-12", "2027-06"):
        with pytest.raises(fn.ErrorFiscal):
            fn.repetir_apunte(t, u, c, ap["id"], hasta=malo, hoy=date(2026, 10, 28))
    with pytest.raises(fn.ErrorFiscal):
        fn.repetir_apunte(t, u, c, 99999, hasta="2026-05", hoy=date(2026, 10, 28))
    rect = fn.aprobar_apunte(t, u, c, venta(-1000, 2100, numero="R-1", tipo_factura="R1", fecha=date(2026, 3, 21)))
    with pytest.raises(fn.ErrorFiscal):
        fn.repetir_apunte(t, u, c, rect["id"], hasta="2026-05", hoy=date(2026, 10, 28))
