"""Comparador de modelos (P7): se prueban varios modelos sobre facturas ya revisadas y se mide acierto, tiempo y coste."""
import json

import pytest

from app import db, facturas_contables as fc, ia_asistente, ia_comparador as cmp, ia_despacho as dz, ia_proveedores as pv, ia_trabajos as tr, lectura_facturas as lf
from tests.test_facturas_contables import PDF, _despacho
from tests.test_lectura_facturas import RESPUESTA, modelo  # noqa: F401 -- fixture


@pytest.fixture(autouse=True)
def _sin_esperas(monkeypatch):
    monkeypatch.setattr(tr, "_esperar_ritmo", lambda proveedor: None)


def _con_dos_modelos(t, u):
    dz.guardar(t, "openai", activo=True, modelo_asistente="gpt-4o-mini", modelo_facturas="gpt-4o-mini", claves_nuevas=["sk-despacho-aaaaaaaaaa"], por=u)
    dz.guardar(t, "anthropic", activo=True, modelo_asistente="claude-haiku-5-5", modelo_facturas="claude-haiku-5-5", claves_nuevas=["sk-ant-despacho-bbbbbbbb"], por=u)


def _revisada(t, u, c, n, modelo):
    fid = fc.subir_archivos(t, u, c, "recibida", [("f.pdf", "application/pdf", PDF + bytes([n]))])[0]
    lf.leer(t, u, fid)
    fc.cambiar_estado(t, u, fid, "revisada")
    return fid


def _respuesta(datos):
    return {"choices": [{"message": {"role": "assistant", "content": json.dumps(datos)}}], "usage": {"prompt_tokens": 1000, "completion_tokens": 100}}


def test_la_muestra_son_facturas_leidas_con_ia_y_revisadas_a_mano(modelo):
    t, u, c = _despacho()
    a, b = _revisada(t, u, c, 1, modelo), _revisada(t, u, c, 2, modelo)
    sin_revisar = fc.subir_archivos(t, u, c, "recibida", [("g.pdf", "application/pdf", PDF + b"x")])[0]
    lf.leer(t, u, sin_revisar)
    assert cmp.muestra_posible(t, u, 10) == [b, a] and cmp.muestra_posible(t, u, 1) == [b]


def test_lanzar_exige_dos_modelos_y_una_muestra(modelo):
    t, u, c = _despacho()
    with pytest.raises(ValueError, match="al menos dos"):
        cmp.lanzar(t, u, 5, [0, 1])
    _con_dos_modelos(t, u)
    assert [m["proveedor"] for m in cmp.modelos_disponibles(u)] == ["openai", "anthropic"]
    with pytest.raises(ValueError, match="Elige al menos dos"):
        cmp.lanzar(t, u, 5, [0])
    with pytest.raises(ValueError, match="Todavía no hay facturas"):
        cmp.lanzar(t, u, 5, [0, 1])


def test_la_comparacion_mide_acierto_tiempo_y_coste_por_modelo(modelo, monkeypatch):
    t, u, c = _despacho()
    _con_dos_modelos(t, u)
    _revisada(t, u, c, 1, modelo)
    _revisada(t, u, c, 2, modelo)

    def falso(proveedor, modelo_id, payload, clave, url_base=None, timeout=30):
        datos = dict(RESPUESTA)
        if proveedor == "anthropic":
            datos["numero"] = "MAL-LEIDO"                                   # este modelo falla un dato
        return _respuesta(datos)
    monkeypatch.setattr(pv, "llamar", falso)
    lote, n = cmp.lanzar(t, u, 10, [0, 1])
    assert n == 2
    while tr.procesar_uno():
        pass
    r = cmp.resultado(t, lote)
    assert r["progreso"]["terminado"] and r["progreso"]["hechas"] == 2
    por_nombre = {m["nombre"]: m for m in r["modelos"]}
    ok, mal = por_nombre["openai · gpt-4o-mini"], por_nombre["anthropic · claude-haiku-5-5"]
    assert ok["facturas"] == 2 and ok["campos"]["numero"] == 100 and ok["acierto_pct"] > mal["acierto_pct"] and mal["campos"]["numero"] == 0 and mal["campos"]["total"] == 100
    assert r["mejor"] == "openai · gpt-4o-mini" and r["modelos"][0]["nombre"] == "openai · gpt-4o-mini"
    assert ok["coste_medio_usd"] == pytest.approx((1000 * 0.15 + 100 * 0.60) / 1_000_000) and mal["coste_medio_usd"] is None and mal["sin_tarifa"] == 2          # claude-haiku-5-5 aún sin tarifa
    assert ok["segundos_medios"] is not None


def test_un_modelo_que_falla_no_impide_medir_a_los_otros(modelo, monkeypatch):
    t, u, c = _despacho()
    _con_dos_modelos(t, u)
    _revisada(t, u, c, 1, modelo)

    def falso(proveedor, modelo_id, payload, clave, url_base=None, timeout=30):
        if proveedor == "anthropic":
            raise ia_asistente.ErrorIA("caído", codigo_http=500)
        return _respuesta(RESPUESTA)
    monkeypatch.setattr(pv, "llamar", falso)
    lote, _ = cmp.lanzar(t, u, 5, [0, 1])
    while tr.procesar_uno():
        pass
    por_nombre = {m["nombre"]: m for m in cmp.resultado(t, lote)["modelos"]}
    assert por_nombre["openai · gpt-4o-mini"]["facturas"] == 1 and por_nombre["anthropic · claude-haiku-5-5"]["errores"] == 1 and por_nombre["anthropic · claude-haiku-5-5"]["acierto_pct"] is None


def test_la_comparacion_no_toca_las_facturas_ni_gasta_el_tope_y_se_anota_como_otras(modelo, monkeypatch):
    from app import ia_uso
    t, u, c = _despacho()
    _con_dos_modelos(t, u)
    fid = _revisada(t, u, c, 1, modelo)
    antes = fc.obtener(t, u, fid)
    monkeypatch.setattr(pv, "llamar", lambda *a, **k: _respuesta({**RESPUESTA, "numero": "OTRO"}))
    cmp.lanzar(t, u, 5, [0, 1])
    while tr.procesar_uno():
        pass
    despues = fc.obtener(t, u, fid)
    assert (despues["numero"], despues["estado"], despues["total_centimos"]) == (antes["numero"], antes["estado"], antes["total_centimos"])
    assert {f["tarea"] for f in ia_uso.resumen(t)["filas"]} == {"otras"}


def test_la_pagina_es_para_la_direccion_y_enseña_el_resultado(cliente, monkeypatch):
    from tests.test_facturas_contables import _web
    from tests.conftest import iniciar_sesion_de_prueba
    uid, t, c = _web(cliente, "comparar@ejemplo.com")
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8"})                  # sin la configuración de a3 una factura no se puede revisar
    monkeypatch.setattr(lf, "configurada", lambda x: True)
    monkeypatch.setattr(ia_asistente, "completar_partes", lambda x, s, p, timeout=90: json.dumps(RESPUESTA))
    assert "al menos dos modelos" in cliente.get("/contabilidad/comparar").get_data(as_text=True)
    _con_dos_modelos(t, uid)
    fid = fc.subir_archivos(t, uid, c, "recibida", [("f.pdf", "application/pdf", PDF + b"w")])[0]
    lf.leer(t, uid, fid)
    cliente.post(f"/contabilidad/{fid}/estado", data={"estado": "revisada"})
    monkeypatch.setattr(pv, "llamar", lambda *a, **k: _respuesta(RESPUESTA))
    assert "Hay 1 factura disponible" in cliente.get("/contabilidad/comparar").get_data(as_text=True)
    r = cliente.post("/contabilidad/comparar", data={"modelo": ["0", "1"], "n": "5"})
    assert r.status_code == 302 and "lote=" in r.headers["Location"]
    while tr.procesar_uno():
        pass
    html = cliente.get(r.headers["Location"]).get_data(as_text=True)
    assert "El que más acierta" in html and "gpt-4o-mini" in html and "1 de 1 facturas probadas" in html
    assert cliente.get(f"/contabilidad/comparar/{r.headers['Location'].split('lote=')[1]}.json").get_json()["mejor"]
    assert cliente.post("/contabilidad/comparar", data={"modelo": ["0"]}).status_code == 200
    from app.main import app as flask_app
    web = flask_app.test_client()
    emp = iniciar_sesion_de_prueba(web, "emp-comparar@ejemplo.com", "contrasena123")
    db.asignar_tenant(emp, t)
    assert web.get("/contabilidad/comparar").status_code == 403 and web.post("/contabilidad/comparar", data={}).status_code == 403
