"""API REST de «Facturas para contabilizar» (app/rutas_api_contabilidad.py, área de token `contabilidad`)."""
from app import api_areas, db, facturas_contables as fc, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.test_rutas_api import _auth, _registrar

LINEAS = [{"base": "1.000,00", "pct_iva": "21"}]


def _despacho(cliente, email, modulo=True, supervisor=True):
    d = _registrar(cliente, email=email)
    u = d["usuario"]["id"]
    t = db.crear_tenant("Despacho " + email)
    db.asignar_tenant(u, t)
    if supervisor:
        db.asignar_supervisor_tenant(u, True)
    if modulo:
        verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente API SL", nif="B12345678")
    fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8"})
    return _auth(d["token"]), t, u, c


def _factura(cliente, h, c, **kw):
    cuerpo = {"cliente_fiscal_id": c, "tipo": "recibida", "fecha": "2026-08-15", "numero": "F-1", "tercero_nombre": "Papelería Sol", "tercero_nif": "B87654321", "lineas": LINEAS, **kw}
    return cliente.post("/api/v1/contabilidad/facturas", json=cuerpo, headers=h)


def test_el_area_existe():
    assert api_areas.area_de_ruta("/api/v1/contabilidad/facturas") == "contabilidad"


def test_sin_modulo_es_404_y_sin_token_401(cliente):
    h, *_ = _despacho(cliente, "apisinmod@ejemplo.com", modulo=False)
    for ruta in ("/api/v1/contabilidad/facturas", "/api/v1/contabilidad/resumen"):
        r = cliente.get(ruta, headers=h)
        assert r.status_code == 404 and r.get_json()["codigo"] == "no_encontrado"
        assert cliente.get(ruta).status_code == 401


def test_anotar_ver_listar_y_revisar(cliente):
    h, t, u, c = _despacho(cliente, "apiconta@ejemplo.com")
    r = _factura(cliente, h, c)
    assert r.status_code == 201
    f = r.get_json()["data"]
    assert (f["numero"], f["total"], f["estado"], f["tipo"], f["cliente"]) == ("F-1", 1210.0, "pendiente", "recibida", "Cliente API SL")
    assert f["lineas"][0]["base"] == 1000.0 and f["lineas"][0]["cuota_iva"] == 210.0 and f["lineas"][0]["pct_iva"] == 21.0
    fid = f["id"]
    assert cliente.get(f"/api/v1/contabilidad/facturas/{fid}", headers=h).get_json()["data"]["problemas"] == []
    lista = cliente.get("/api/v1/contabilidad/facturas?estado=pendiente&trimestre=2026-T3", headers=h).get_json()["data"]
    assert [x["id"] for x in lista] == [fid]
    assert cliente.get("/api/v1/contabilidad/facturas?estado=exportada", headers=h).get_json()["data"] == []
    r = cliente.post(f"/api/v1/contabilidad/facturas/{fid}/estado", json={"estado": "revisada"}, headers=h)
    assert r.status_code == 200 and r.get_json()["data"]["estado"] == "revisada"
    assert cliente.post(f"/api/v1/contabilidad/facturas/{fid}/estado", json={"estado": "exportada"}, headers=h).status_code == 400


def test_errores_de_validacion(cliente):
    h, t, u, c = _despacho(cliente, "apierr@ejemplo.com")
    assert _factura(cliente, h, c, lineas=[]).status_code == 400
    assert _factura(cliente, h, c, tipo="otra").status_code == 400
    assert _factura(cliente, h, c, fecha="ayer").status_code == 400
    assert _factura(cliente, h, 999999).status_code == 404
    assert cliente.get("/api/v1/contabilidad/facturas?estado=x", headers=h).status_code == 400
    assert cliente.get("/api/v1/contabilidad/facturas?trimestre=x", headers=h).status_code == 400
    assert cliente.get("/api/v1/contabilidad/facturas/999999", headers=h).status_code == 404


def test_el_regimen_y_las_reglas_se_aplican_tambien_por_api(cliente):
    h, t, u, c = _despacho(cliente, "apiregla@ejemplo.com")
    fc.guardar_regla(t, u, c, "proveedor", {"nif": "B87654321", "cuenta_linea": "62200000", "pct_iva": "10"})
    f = _factura(cliente, h, c, lineas=[{"base": "100"}]).get_json()["data"]
    assert f["lineas"][0]["cuenta"] == "62200000" and f["total"] == 110.0


def test_un_despacho_no_ve_las_facturas_de_otro(cliente):
    h1, t1, u1, c1 = _despacho(cliente, "apiuno@ejemplo.com")
    h2, t2, u2, c2 = _despacho(cliente, "apidos@ejemplo.com")
    fid = _factura(cliente, h1, c1).get_json()["data"]["id"]
    assert cliente.get(f"/api/v1/contabilidad/facturas/{fid}", headers=h2).status_code == 404
    assert cliente.get("/api/v1/contabilidad/facturas", headers=h2).get_json()["data"] == []
    assert cliente.post(f"/api/v1/contabilidad/facturas/{fid}/estado", json={"estado": "descartada"}, headers=h2).status_code == 404


def test_resumen_y_comprobar_y_exportar_y_bajar_el_fichero(cliente):
    h, t, u, c = _despacho(cliente, "apiexp@ejemplo.com")
    f1 = _factura(cliente, h, c).get_json()["data"]["id"]
    _factura(cliente, h, c, numero="F-2")
    cliente.post(f"/api/v1/contabilidad/facturas/{f1}/estado", json={"estado": "revisada"}, headers=h)
    r = cliente.get("/api/v1/contabilidad/resumen", headers=h).get_json()["data"]
    assert (r["por_revisar"], r["para_exportar"]) == (1, 1) and r["clientes"][0]["cliente"] == "Cliente API SL"
    chequeo = cliente.get(f"/api/v1/contabilidad/clientes/{c}/comprobar?trimestre=2026-T3", headers=h).get_json()["data"]
    assert chequeo["ok"] is True and chequeo["facturas"] == 1 and chequeo["errores"] == [] and chequeo["registros"] == 2
    assert cliente.get(f"/api/v1/contabilidad/facturas/{f1}", headers=h).get_json()["data"]["estado"] == "revisada", "comprobar no marca nada"
    e = cliente.post(f"/api/v1/contabilidad/clientes/{c}/exportar", json={"trimestre": "2026-T3"}, headers=h)
    assert e.status_code == 200
    lote = e.get_json()["data"]
    assert lote["facturas"] == 1 and lote["registros"] == 2
    fichero = cliente.get(f"/api/v1/contabilidad/lotes/{lote['lote']}/fichero", headers=h)
    assert fichero.status_code == 200 and len(fichero.data) == 1024 and "SUENLACE.DAT" in fichero.headers["Content-Disposition"] and fichero.headers["Cache-Control"] == "no-store"
    assert cliente.post(f"/api/v1/contabilidad/clientes/{c}/exportar", json={}, headers=h).status_code == 400, "ya no queda nada que exportar"
    assert cliente.get("/api/v1/contabilidad/lotes/999999/fichero", headers=h).status_code == 404


def test_no_se_exporta_un_periodo_cerrado_por_api(cliente):
    h, t, u, c = _despacho(cliente, "apicerr@ejemplo.com")
    fid = _factura(cliente, h, c).get_json()["data"]["id"]
    cliente.post(f"/api/v1/contabilidad/facturas/{fid}/estado", json={"estado": "revisada"}, headers=h)
    fc.cerrar_periodo(t, u, c, "2026-T3")
    r = cliente.post(f"/api/v1/contabilidad/clientes/{c}/exportar", json={}, headers=h)
    assert r.status_code == 400 and "cerrados" in r.get_json()["error"]
    assert cliente.get(f"/api/v1/contabilidad/facturas/{fid}", headers=h).get_json()["data"]["periodo_cerrado"].startswith("cerrado a mano")
    assert cliente.get(f"/api/v1/contabilidad/clientes/{c}/comprobar", headers=h).get_json()["data"]["periodos_cerrados"][0]["trimestre"] == "2026-T3"


def test_quien_solo_audita_puede_mirar_pero_no_cambiar(cliente, monkeypatch):
    h, t, u, c = _despacho(cliente, "apiaud@ejemplo.com")
    fid = _factura(cliente, h, c).get_json()["data"]["id"]
    from app import acceso
    monkeypatch.setattr(acceso, "es_solo_auditor", lambda tenant, usuario: True)
    assert cliente.get(f"/api/v1/contabilidad/facturas/{fid}", headers=h).status_code == 200
    assert _factura(cliente, h, c, numero="F-9").status_code == 400
    assert cliente.post(f"/api/v1/contabilidad/facturas/{fid}/estado", json={"estado": "revisada"}, headers=h).status_code == 400
    assert cliente.post(f"/api/v1/contabilidad/clientes/{c}/exportar", json={}, headers=h).status_code == 400


def test_leer_con_ia_sin_modelo_da_un_error_claro_y_con_modelo_rellena(cliente, monkeypatch):
    from app import ia_asistente, lectura_facturas as lf
    h, t, u, c = _despacho(cliente, "apiia@ejemplo.com")
    fid = fc.subir_archivos(t, u, c, "recibida", [("f.pdf", "application/pdf", b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF")])[0]
    r = cliente.post(f"/api/v1/contabilidad/facturas/{fid}/leer", headers=h)
    assert r.status_code == 400 and "OpenRouter" in r.get_json()["error"]
    monkeypatch.setattr(lf, "configurada", lambda uid: True)
    monkeypatch.setattr(ia_asistente, "completar_partes", lambda uid, sistema, partes, timeout=90: '{"emisor_nif": "B87654321", "emisor_nombre": "Sol", "receptor_nif": "B12345678", "numero": "X-1", "fecha": "2026-08-14", '
                                                                                                    '"lineas": [{"base": 100, "pct_iva": 21}], "total": 121}')
    r = cliente.post(f"/api/v1/contabilidad/facturas/{fid}/leer", headers=h)
    assert r.status_code == 200
    d = r.get_json()["data"]
    assert d["numero"] == "X-1" and d["total"] == 121.0 and d["lectura"] == "ia" and d["avisos_de_la_lectura"] == []


def test_el_documento_openapi_incluye_las_rutas(cliente):
    spec = cliente.get("/api/v1/openapi.json").get_json()
    for ruta in ("/api/v1/contabilidad/facturas", "/api/v1/contabilidad/facturas/{factura_id}", "/api/v1/contabilidad/resumen", "/api/v1/contabilidad/clientes/{cliente_fiscal_id}/comprobar",
                 "/api/v1/contabilidad/clientes/{cliente_fiscal_id}/exportar", "/api/v1/contabilidad/lotes/{lote_id}/fichero"):
        assert ruta in spec["paths"], ruta
    assert "requestBody" in spec["paths"]["/api/v1/contabilidad/facturas"]["post"]
