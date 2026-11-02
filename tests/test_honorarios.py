"""Honorarios por tramos de los vencimientos fiscales (app/honorarios.py): reglas con prioridad, tres formas de calcular, propuesta, confirmación y permisos."""
from datetime import date

import pytest

from app import db, fiscal_nucleo as fn, fiscal_perfiles as fp, honorarios as h
from app.db_fiscal import crear_cliente_fiscal, crear_vencimiento_fiscal, marcar_presentado_vencimiento_fiscal
from tests.escenarios_303 import venta


def _despacho(nombre="Despacho Honorarios", forma="sociedad"):
    t = db.crear_tenant(nombre)
    clave = nombre.replace(" ", "").lower()
    u = db.crear_usuario_vinculado_a_kratos(f"{clave}@ejemplo.com", f"k-{clave}"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    c = crear_cliente_fiscal(t, "Titular SL", nif="12345678Z")
    fp.guardar_perfil(t, u, c, {"forma_juridica": forma}, vigente_desde="2026-01-01")
    return t, u, c


def _con_apuntes(t, u, c, n, mes=5):
    for i in range(n):
        fn.aprobar_apunte(t, u, c, venta(10000, 2100, numero=f"H-{mes}-{i}", fecha=date(2026, mes, 10)))


def _venc(t, u, c, modelo="303", periodo="2T 2026"):
    return crear_vencimiento_fiscal(t, c, modelo, periodo, "2026-07-20", usuario_id=u)


def test_fijo_por_apunte_y_tramos_calculan_en_centimos():
    fijo = {"calculo": "fijo", "importe_centimos": 5000, "activa": 1, "modelo": "", "forma_juridica": "", "tramos": []}
    assert h._importe(fijo, 40)[0] == 5000
    por = {"calculo": "por_apunte", "importe_centimos": 2000, "unidad_centimos": 150, "minimo_centimos": 4000, "tramos": []}
    assert h._importe(por, 10)[0] == 4000 and h._importe(por, 10)[1]["minimo_aplicado"] is True      # 20 + 15 = 35 < 40
    assert h._importe(por, 30)[0] == 6500 and h._importe(por, 30)[1]["minimo_aplicado"] is False
    tr = {"calculo": "tramos", "tramos": [{"hasta": 10, "importe_centimos": 6000}, {"hasta": 50, "importe_centimos": 9000}, {"hasta": None, "importe_centimos": 12000}]}
    assert [h._importe(tr, n)[0] for n in (0, 10, 11, 50, 51, 500)] == [6000, 6000, 9000, 9000, 12000, 12000]


def test_los_tramos_se_validan():
    for malos in ([], [{"hasta": 10, "importe": "5"}], [{"hasta": None, "importe": "5"}, {"hasta": 10, "importe": "6"}],
                  [{"hasta": 10, "importe": "5"}, {"hasta": 10, "importe": "6"}, {"hasta": None, "importe": "7"}], [{"hasta": "x", "importe": "5"}, {"hasta": None, "importe": "7"}]):
        with pytest.raises(h.ErrorHonorarios):
            h._tramos(malos)
    assert h._tramos([{"hasta": 10, "importe": "60,00"}, {"hasta": "", "importe": "45"}]) == [{"hasta": 10, "importe_centimos": 6000}, {"hasta": None, "importe_centimos": 4500}]
    assert h.tramos_desde_texto("hasta 10: 60,00\nresto: 45,00") == [{"hasta": 10, "importe": "60,00"}, {"hasta": None, "importe": "45,00"}]
    with pytest.raises(h.ErrorHonorarios):
        h.tramos_desde_texto("diez: 5")
    assert h.tramos_a_texto(h._tramos(h.tramos_desde_texto("hasta 10: 60,05\nresto: 45"))) == "hasta 10: 60,05\nresto: 45,00"


def test_aplica_la_primera_regla_activa_que_encaja():
    t, u, c = _despacho()
    general = h.crear_regla(t, u, {"nombre": "Cualquier modelo", "prioridad": 50, "calculo": "fijo", "importe": "30"})
    h.crear_regla(t, u, {"nombre": "303 sociedades", "prioridad": 10, "modelo": "303", "forma_juridica": "sociedad", "calculo": "fijo", "importe": "80"})
    h.crear_regla(t, u, {"nombre": "303 autónomos", "prioridad": 5, "modelo": "303", "forma_juridica": "persona_fisica", "calculo": "fijo", "importe": "60"})
    assert h.simular(t, "303", "sociedad", 3)["importe_centimos"] == 8000
    assert h.simular(t, "303", "persona_fisica", 3)["importe_centimos"] == 6000
    assert h.simular(t, "130", "sociedad", 3)["regla"]["nombre"] == "Cualquier modelo"
    h.alternar_regla(t, u, general)
    sin = h.simular(t, "130", "sociedad", 3)
    assert sin["regla"] is None and sin["importe_centimos"] is None and "Ninguna regla" in sin["motivo"]
    assert [r["nombre"] for r in h.listar_reglas(t)] == ["303 autónomos", "303 sociedades", "Cualquier modelo"]


def test_el_periodo_acota_los_apuntes_que_se_cuentan():
    assert h.rango_del_periodo("2T 2026") == ("2026-04-01", "2026-06-30") and h.rango_del_periodo("2026-T4") == ("2026-10-01", "2026-12-31")
    assert h.rango_del_periodo("2025") == ("2025-01-01", "2025-12-31") and h.rango_del_periodo("mayo") is None
    t, u, c = _despacho()
    _con_apuntes(t, u, c, 3, mes=5)
    _con_apuntes(t, u, c, 2, mes=2)
    assert h.contar_apuntes(t, c, "2T 2026") == 3 and h.contar_apuntes(t, c, "1T 2026") == 2 and h.contar_apuntes(t, c, "2026") == 5 and h.contar_apuntes(t, c, "mayo") is None


def test_propuesta_y_confirmacion_de_un_vencimiento():
    t, u, c = _despacho()
    h.crear_regla(t, u, {"nombre": "303 por tramos", "modelo": "303", "calculo": "tramos", "tramos": [{"hasta": 5, "importe": "50"}, {"hasta": None, "importe": "90"}]})
    _con_apuntes(t, u, c, 7)
    v = _venc(t, u, c)
    p = h.proponer(t, u, v)
    assert p["apuntes"] == 7 and p["importe_centimos"] == 9000 and p["desglose"]["tramo"] == 2 and p["forma_juridica"] == "sociedad" and p["aplicado"] is None
    assert h.pendientes_de_confirmar(t, u) == []                      # sigue pendiente de presentar
    marcar_presentado_vencimiento_fiscal(t, v, u)
    assert [x["vencimiento"]["id"] for x in h.pendientes_de_confirmar(t, u)] == [v]
    a = h.confirmar(t, u, v)
    ap = h.aplicado_de(t, v)
    assert ap["id"] == a and ap["importe_centimos"] == 9000 and ap["regla_nombre"] == "303 por tramos" and ap["concepto"] == "Honorarios modelo 303 2T 2026" and ap["unidades"] == 7
    assert h.pendientes_de_confirmar(t, u) == []
    with pytest.raises(h.ErrorHonorarios, match="ya tiene"):
        h.confirmar(t, u, v)
    # cambiar la regla después no toca lo confirmado
    h.editar_regla(t, u, h.listar_reglas(t)[0]["id"], {"nombre": "303 nueva", "modelo": "303", "calculo": "fijo", "importe": "1"})
    assert h.aplicado_de(t, v)["importe_centimos"] == 9000 and h.aplicado_de(t, v)["regla_nombre"] == "303 por tramos"


def test_importe_a_mano_conserva_el_calculo_y_sin_regla_hay_que_indicarlo():
    t, u, c = _despacho()
    v = _venc(t, u, c)
    with pytest.raises(h.ErrorHonorarios, match="Ninguna regla"):
        h.confirmar(t, u, v)
    h.crear_regla(t, u, {"nombre": "Fijo", "calculo": "fijo", "importe": "100"})
    h.confirmar(t, u, v, importe="85,50")
    ap = h.aplicado_de(t, v)
    assert ap["importe_centimos"] == 8550 and ap["desglose"]["calculado_centimos"] == 10000 and ap["desglose"]["ajustado_a_mano"] is True
    v2 = _venc(t, u, c, "130", "2T 2026")
    h.eliminar_regla(t, u, h.listar_reglas(t)[0]["id"])
    h.confirmar(t, u, v2, importe="40")
    assert h.aplicado_de(t, v2)["regla_nombre"] == "A mano" and h.aplicado_de(t, v2)["importe_centimos"] == 4000


def test_facturar_y_anular_con_sus_reglas():
    t, u, c = _despacho()
    h.crear_regla(t, u, {"nombre": "Fijo", "calculo": "fijo", "importe": "100"})
    v = _venc(t, u, c)
    a = h.confirmar(t, u, v)
    with pytest.raises(h.ErrorHonorarios, match="referencia"):
        h.marcar_facturado(t, u, a, " ")
    h.marcar_facturado(t, u, a, "F2026-0042")
    assert h.aplicado_de(t, v)["estado"] == "facturado" and h.aplicado_de(t, v)["referencia_factura"] == "F2026-0042"
    with pytest.raises(h.ErrorHonorarios):
        h.marcar_facturado(t, u, a, "otra")                         # ya facturado
    with pytest.raises(h.ErrorHonorarios, match="motivo"):
        h.anular(t, u, a, "")
    h.anular(t, u, a, "Factura emitida por error")
    assert h.aplicado_de(t, v) is None and h.aplicados(t, u, estado="anulado")[0]["anulado_motivo"] == "Factura emitida por error"
    h.confirmar(t, u, v)                                           # tras anular se puede fijar de nuevo
    assert h.aplicado_de(t, v)["estado"] == "confirmado"


def test_solo_la_direccion_gestiona_y_cada_despacho_ve_lo_suyo():
    t, u, c = _despacho()
    h.crear_regla(t, u, {"nombre": "Fijo", "calculo": "fijo", "importe": "100"})
    v = _venc(t, u, c)
    otra = db.crear_usuario_vinculado_a_kratos("preparador@ejemplo.com", "k-prep"); db.asignar_tenant(otra, t)
    with pytest.raises(h.ErrorHonorarios, match="dirección"):
        h.crear_regla(t, otra, {"nombre": "X", "calculo": "fijo", "importe": "1"})
    with pytest.raises(h.ErrorHonorarios, match="dirección"):
        h.confirmar(t, otra, v)
    t2, u2, _ = _despacho("Otro Despacho")
    assert h.listar_reglas(t2) == []
    with pytest.raises(h.ErrorHonorarios):
        h.proponer(t2, u2, v)                                      # un vencimiento de otro despacho no existe
    with pytest.raises(h.ErrorHonorarios):
        h.alternar_regla(t2, u2, h.listar_reglas(t)[0]["id"])


def test_importes_invalidos_se_rechazan():
    t, u, _ = _despacho()
    for malo in ({"nombre": "", "calculo": "fijo", "importe": "1"}, {"nombre": "x", "calculo": "raro"}, {"nombre": "x", "calculo": "fijo", "importe": "abc"}, {"nombre": "x", "calculo": "fijo"},
                 {"nombre": "x", "calculo": "fijo", "importe": "1", "forma_juridica": "otro"}, {"nombre": "x", "calculo": "fijo", "importe": "1", "prioridad": 0},
                 {"nombre": "x", "calculo": "por_apunte", "importe": "1"}):
        with pytest.raises(h.ErrorHonorarios):
            h.crear_regla(t, u, malo)
    assert h.euros(123456) == "1.234,56 €" and h.euros(None) == "—"
