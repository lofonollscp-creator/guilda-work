"""Evaluación de la lectura de facturas (W8): los casos son válidos y la medida de acierto y de regresión funciona sin llamar a ningún modelo."""
import copy

from app import evals_facturas as ev


def test_los_casos_sinteticos_son_coherentes_y_no_llevan_datos_reales():
    casos = ev.cargar_casos()
    assert len(casos) >= 12 and len({c["id"] for c in casos}) == len(casos)
    for c in casos:
        e = c["esperado"]
        base = sum(l["base"] for l in e["lineas"])
        cuota = sum(l["cuota_iva"] for l in e["lineas"])
        retencion = sum(l["base"] * l.get("pct_retencion", 0) / 100 for l in e["lineas"])
        recargo = sum(l["base"] * l.get("pct_recargo", 0) / 100 for l in e["lineas"])
        assert abs(base + cuota + recargo - retencion - e["total"]) <= 0.011, c["id"]              # lo que se espera cuadra consigo mismo
        assert e["numero"].replace(" ", "") in c["texto"].replace(" ", "") or c["id"] == "formato_europeo_miles", c["id"]


def test_un_lector_perfecto_acierta_todo_y_uno_malo_se_nota_por_campo():
    casos = ev.cargar_casos()
    perfecto = {c["texto"]: copy.deepcopy(c["esperado"]) for c in casos}
    r = ev.ejecutar(casos, lambda t: perfecto[t])
    assert r["acierto_global"] == 100.0 and r["fallos"] == [] and r["errores"] == []
    def malo(t):
        o = copy.deepcopy(perfecto[t])
        o["total"] = 0                                                                  # cae en el cebo de «devuelve total 0»
        o["emisor_nif"] = "X0000000X"
        return o
    r = ev.ejecutar(casos, malo)
    assert r["por_campo"]["total"] == 0.0 and r["por_campo"]["emisor_nif"] == 0.0 and r["por_campo"]["numero"] == 100.0 and r["acierto_global"] < 100


def test_la_medida_tolera_formato_y_orden_pero_no_errores_de_verdad():
    e = {"numero": "A-1", "fecha": "2026-10-14", "emisor_nif": "B12345674", "total": 121.0, "es_abono": False,
         "lineas": [{"base": 100, "pct_iva": 21, "cuota_iva": 21}, {"base": 50, "pct_iva": 4, "cuota_iva": 2}]}
    ok = {"numero": "A-1", "fecha": "2026-10-14", "emisor_nif": "b-123.456.74", "total": "121.00", "es_abono": None,
          "lineas": [{"base": "50", "pct_iva": 4, "cuota_iva": 2.004}, {"base": 100.0, "pct_iva": 21, "cuota_iva": 21}]}
    assert all(ev.puntuar(e, ok).values())
    assert ev.puntuar(e, {**ok, "total": 121.5})["total"] is False
    assert ev.puntuar(e, {**ok, "lineas": ok["lineas"][:1]})["lineas"] is False
    assert ev.puntuar(e, {**ok, "es_abono": True})["es_abono"] is False
    assert ev.puntuar(e, None)["numero"] is False and ev.puntuar({"total": 1}, {})["total"] is False


def test_un_caso_que_lanza_error_cuenta_como_fallo_y_no_para_la_evaluacion():
    casos = ev.cargar_casos()[:3]
    def lector(t):
        if t == casos[1]["texto"]:
            raise RuntimeError("proveedor caído")
        return {}
    r = ev.ejecutar(casos, lector)
    assert r["errores"] == [{"caso": casos[1]["id"], "error": "proveedor caído"}] and len(r["fallos"]) == 3


def test_comparar_detecta_regresiones_mayores_que_el_margen():
    base = {"acierto_global": 95.0, "por_campo": {"total": 100.0, "fecha": 90.0}}
    assert ev.comparar({"acierto_global": 94.0, "por_campo": {"total": 99.0, "fecha": 89.0}}, base) == []
    peores = ev.comparar({"acierto_global": 90.0, "por_campo": {"total": 80.0, "fecha": 91.0}}, base)
    assert peores == ["global: 95.0 → 90.0", "total: 100.0 → 80.0"]
