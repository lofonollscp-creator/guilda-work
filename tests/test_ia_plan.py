"""Confirmación agrupada: «ejecutar_plan» (app/ia_herramientas.py). Una sola confirmación cubre varios pasos de contabilidad, a la vista y en orden."""
import pytest

from app import ia_herramientas as ih
from tests.test_herramientas_contabilidad import _anotar, _despacho


def _paso(herramienta, **argumentos):
    return {"herramienta": herramienta, "argumentos": argumentos}


def test_el_plan_siempre_pide_confirmacion_y_la_tarjeta_enseña_cada_paso_con_su_texto():
    assert ih.necesita_confirmacion("ejecutar_plan", modo_autonomo=True) and ih.necesita_confirmacion("ejecutar_plan", modo_autonomo=False)
    resumen = ih.resumen_de_confirmacion(1, "ejecutar_plan", {"titulo": "Cerrar T3", "pasos": [_paso("contabilidad_revisar_seguras", cliente_fiscal_id=3),
                                                                                              _paso("contabilidad_preguntar_al_cliente", factura_id=9, texto="¿Para qué fue este gasto?")]})
    assert "Cerrar T3" in resumen and "2 pasos" in resumen and "1. contabilidad_revisar_seguras(cliente_fiscal_id=3)" in resumen
    assert "¿Para qué fue este gasto?" in resumen and "mensaje a una persona de fuera del despacho" in resumen
    assert "no se puede ejecutar" in ih.resumen_de_confirmacion(1, "ejecutar_plan", {"titulo": "x", "pasos": [_paso("crear_tarea", titulo="a")]})


@pytest.mark.parametrize("pasos,motivo", [
    ([], "al menos un paso"), ("no es lista", "al menos un paso"), ([_paso("contabilidad_listar_facturas")], "no se puede incluir"),          # una consulta
    ([_paso("crear_tarea", titulo="x")], "no se puede incluir"), ([_paso("ejecutar_plan", pasos=[])], "no se puede incluir"), ([{"herramienta": "contabilidad_exportar"}], "argumentos"),
    ([_paso("contabilidad_revisar_seguras")] * 11, "como mucho 10"), ([_paso("inventada")], "no se puede incluir")])
def test_un_plan_que_no_vale_se_rechaza_con_su_motivo(pasos, motivo):
    t, u, c = _despacho("Despacho plan invalido")
    with pytest.raises(ih.ErrorHerramientaIA, match=motivo):
        ih.ejecutar(u, "ejecutar_plan", {"titulo": "x", "pasos": pasos})


def test_un_plan_ejecuta_sus_pasos_en_orden_con_los_permisos_de_cada_herramienta():
    t, u, c = _despacho("Despacho plan ok")
    f = _anotar(u, c)
    r = ih.ejecutar(u, "ejecutar_plan", {"titulo": "Regla y pregunta", "pasos": [
        _paso("contabilidad_guardar_regla", cliente_fiscal_id=c, tipo="proveedor", nif="A58818501", cuenta="62800000"),
        _paso("contabilidad_preguntar_al_cliente", factura_id=f["id"], texto="¿Para qué fue este gasto?"),
        _paso("contabilidad_revisar_seguras", cliente_fiscal_id=c, simular=True)]})
    assert r["completado"] and [p["paso"] for p in r["pasos"]] == [1, 2, 3] and r["pasos"][0]["resultado"]["cuenta"] == "62800000"
    assert ih.ejecutar(u, "contabilidad_mensajes_factura", {"factura_id": f["id"]})["mensajes"][0]["texto"] == "¿Para qué fue este gasto?"


def test_un_plan_se_para_en_el_primer_error_y_cuenta_lo_que_quedo_sin_hacer():
    t, u, c = _despacho("Despacho plan error")
    f = _anotar(u, c)
    r = ih.ejecutar(u, "ejecutar_plan", {"titulo": "Con fallo", "pasos": [
        _paso("contabilidad_cambiar_estado_factura", factura_id=f["id"], estado="descartada"),
        _paso("contabilidad_cambiar_estado_factura", factura_id=999999, estado="revisada"),
        _paso("contabilidad_exportar", cliente_fiscal_id=c)]})
    assert r["completado"] is False and r["fallo"]["paso"] == 2 and r["sin_ejecutar"] == ["contabilidad_exportar"] and "NO se ha deshecho" in r["aviso"]
    assert [p["paso"] for p in r["pasos"]] == [1] and ih.ejecutar(u, "contabilidad_ver_factura", {"factura_id": f["id"]})["estado"] == "descartada"


def test_quien_solo_audita_no_puede_usar_un_plan_para_saltarse_el_limite(monkeypatch):
    from app import acceso
    t, u, c = _despacho("Despacho plan auditor")
    f = _anotar(u, c)
    monkeypatch.setattr(acceso, "es_solo_auditor", lambda tenant, usuario: True)
    r = ih.ejecutar(u, "ejecutar_plan", {"titulo": "x", "pasos": [_paso("contabilidad_cambiar_estado_factura", factura_id=f["id"], estado="revisada")]})
    assert r["completado"] is False and "solo permite consultar" in r["fallo"]["mensaje"]


def test_el_plan_se_ofrece_con_las_palabras_de_contabilidad():
    ofrecidas = {t["function"]["name"] for t in ih.herramientas_para([{"role": "user", "content": "cierra el trimestre de este cliente: revisa las seguras y escribe a los clientes"}])}
    assert "ejecutar_plan" in ofrecidas
