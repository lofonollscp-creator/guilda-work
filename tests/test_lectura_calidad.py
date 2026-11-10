"""Calidad de la lectura (R9): acierto por dato al revisar, fuentes, proveedores que más se corrigen y la página para la dirección."""
import json

from app import db, facturas_contables as fc, ia_asistente, lectura_calidad as lq, lectura_facturas as lf
from tests.test_facturas_contables import PDF, _despacho, _web
from tests.test_lectura_facturas import RESPUESTA, modelo  # noqa: F401 -- fixture


def _leida(t, u, c, sufijo=b"1", **cambios):
    fid = fc.subir_archivos(t, u, c, "recibida", [("f.pdf", "application/pdf", PDF + sufijo)])[0]
    lf.leer(t, u, fid)
    return fid


def test_lo_leido_se_guarda_y_al_revisar_sin_cambios_no_hay_correcciones(modelo):
    t, u, c = _despacho()
    fid = _leida(t, u, c)
    e = lf.evidencia_de(fc.obtener(t, u, fid))
    assert e["leido"]["numero"] == "2026/118" and e["leido"]["total"] == "12100" and e["leido"]["nif"] == "B87654321" and "correcciones" not in e
    fc.cambiar_estado(t, u, fid, "revisada")
    e = lf.evidencia_de(fc.obtener(t, u, fid))
    assert e["correcciones"] == {} and e["revisada_en"]


def test_si_la_persona_corrige_se_anota_que_dato_y_con_que_valor(modelo):
    t, u, c = _despacho()
    fid = _leida(t, u, c)
    fc.actualizar(t, u, fid, {"tipo": "recibida", "fecha": "2026-08-15", "numero": "2026/119", "tercero_nombre": "Papelería Sol S.L.", "tercero_nif": "B87654321"}, [{"base": "100,00", "pct_iva": "21"}])
    fc.cambiar_estado(t, u, fid, "revisada")
    corr = lf.evidencia_de(fc.obtener(t, u, fid))["correcciones"]
    assert set(corr) == {"numero", "fecha"} and corr["numero"] == {"leido": "2026/118", "final": "2026/119"}


def test_resumen_calcula_el_acierto_por_dato_las_fuentes_y_los_proveedores(modelo):
    t, u, c = _despacho()
    a = _leida(t, u, c, b"1")
    b = _leida(t, u, c, b"2")
    d = _leida(t, u, c, b"3")
    fc.cambiar_estado(t, u, a, "revisada")
    fc.actualizar(t, u, b, {"tipo": "recibida", "fecha": "2026-08-14", "numero": "OTRO-9", "tercero_nombre": "Papelería Sol S.L.", "tercero_nif": "B87654321"}, [{"base": "100,00", "pct_iva": "21"}])
    fc.cambiar_estado(t, u, b, "revisada")
    r = lq.resumen(t, "2020-01-01")
    assert r["total"] == 3 and r["pendientes_de_revisar"] == 1
    assert r["campos"]["numero"]["revisadas"] == 2 and r["campos"]["numero"]["corregidas"] == 1 and r["campos"]["numero"]["pct_acierto"] == 50
    assert r["campos"]["total"]["pct_acierto"] == 100
    f = r["por_fuente"]["imagen"]
    assert f["facturas"] == 3 and f["revisadas"] == 2 and f["sin_correcciones"] == 1 and f["pct_sin_correcciones"] == 50
    assert r["proveedores"][0]["nombre"] == "Papelería Sol S.L." and r["proveedores"][0]["correcciones"] == 1


def test_las_revisadas_solas_por_la_ia_no_cuentan_en_el_acierto(modelo):
    from app import ia_despacho
    t, u, c = _despacho()
    ia_despacho.guardar_config(t, solo_ue=False, claves_personales=True, facturas_modo="auto", umbral_confianza=50, por=u)
    fid = _leida(t, u, c, b"7")
    r = lq.resumen(t, "2020-01-01")
    assert r["total"] == 1 and r["auto"] + r["pendientes_de_revisar"] == 1
    assert r["campos"]["numero"]["revisadas"] == 0 and r["campos"]["numero"]["pct_acierto"] is None


def test_resumen_vacio_y_con_filtro_de_fecha(modelo):
    t, u, c = _despacho()
    _leida(t, u, c)
    assert lq.resumen(t, "2099-01-01")["total"] == 0
    assert lq.resumen(t, "2020-01-01")["total"] == 1


def test_la_pagina_de_calidad_es_para_la_direccion(cliente, monkeypatch):
    uid, t, c = _web(cliente, "calidad@ejemplo.com")
    html = cliente.get("/contabilidad/calidad").get_data(as_text=True)
    assert "Calidad de la lectura de facturas" in html and "Todavía no hay facturas leídas" in html
    assert cliente.get("/contabilidad/calidad?desde=basura").status_code == 200
    from app.main import app as flask_app
    from tests.conftest import iniciar_sesion_de_prueba
    web = flask_app.test_client()
    emp = iniciar_sesion_de_prueba(web, "emp-calidad@ejemplo.com", "contrasena123")
    db.asignar_tenant(emp, t)
    assert web.get("/contabilidad/calidad").status_code == 403
    assert "Calidad de la lectura" in cliente.get("/contabilidad/").get_data(as_text=True)


def test_la_pagina_enseña_los_numeros_con_facturas_leidas(cliente, monkeypatch):
    uid, t, c = _web(cliente, "calidad2@ejemplo.com")
    monkeypatch.setattr(lf, "configurada", lambda x: True)
    monkeypatch.setattr(ia_asistente, "completar_partes", lambda x, s, p, timeout=90: json.dumps(RESPUESTA))
    fid = fc.subir_archivos(t, uid, c, "recibida", [("f.pdf", "application/pdf", PDF + b"q")])[0]
    lf.leer(t, uid, fid)
    html = cliente.get("/contabilidad/calidad?desde=2020-01-01").get_data(as_text=True)
    assert "Imagen del documento" in html and "Acierto por dato" in html and "Facturas leídas" in html


def test_calidad_por_tipo_de_documento(modelo):
    t, u, c = _despacho()
    a = _leida(t, u, c, b"1")
    fc.cambiar_estado(t, u, a, "revisada")
    r = lq.resumen(t)
    assert r["por_tipo"]["recibida"]["facturas"] == 1 and r["por_tipo"]["despacho"]["revisadas"] == 1 and "abono" not in r["por_tipo"] and "sin_nif" not in r["por_tipo"]
    assert r["por_tipo"]["recibida"]["pct_sin_correcciones"] == 100
