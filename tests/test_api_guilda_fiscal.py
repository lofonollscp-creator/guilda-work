"""API REST de Guilda Fiscal (app/rutas_api_guilda_fiscal.py, área de token `guilda_fiscal`): solo consulta y simulación."""
from app import api_areas, db, fiscal_nucleo as fn, fiscal_perfiles as fp, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.escenarios_303 import ESCENARIOS
from tests.test_rutas_api import _auth, _registrar


def _despacho(cliente, email, modulo=True, supervisor=True):
    d = _registrar(cliente, email=email)
    u = d["usuario"]["id"]
    t = db.crear_tenant("Despacho " + email)
    db.asignar_tenant(u, t)
    if supervisor:
        db.asignar_supervisor_tenant(u, True)
    if modulo:
        verticales.fijar_activo(t, "fiscal", True)
    c = crear_cliente_fiscal(t, "Cliente API SL", nif="A12345674")
    return _auth(d["token"]), t, u, c


def _con_datos(t, u, c):
    fp.guardar_perfil(t, u, c, {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    for a in ESCENARIOS["basico"][0]:
        fn.aprobar_apunte(t, u, c, a)


def test_el_area_existe():
    assert api_areas.area_de_ruta("/api/v1/guilda-fiscal/titulares") == "guilda_fiscal"


def test_sin_modulo_es_404_y_sin_token_401(cliente):
    h, *_ = _despacho(cliente, "gfsinmod@ejemplo.com", modulo=False)
    for ruta in ("/api/v1/guilda-fiscal/titulares",):
        r = cliente.get(ruta, headers=h)
        assert r.status_code == 404 and r.get_json()["codigo"] == "no_encontrado"
        assert cliente.get(ruta).status_code == 401


def test_consulta_de_perfil_apuntes_comprobacion_y_simulacion(cliente):
    h, t, u, c = _despacho(cliente, "gfapi@ejemplo.com")
    _con_datos(t, u, c)
    tit = cliente.get("/api/v1/guilda-fiscal/titulares", headers=h).get_json()["data"]
    assert tit[0]["nombre"] == "Cliente API SL" and tit[0]["perfil"]["regimen_iva"] == "general" and tit[0]["apuntes_del_anio"] == 2
    assert cliente.get(f"/api/v1/guilda-fiscal/titulares/{c}/perfil", headers=h).get_json()["data"]["vigente"]["forma_juridica"] == "sociedad"
    ap = cliente.get(f"/api/v1/guilda-fiscal/titulares/{c}/apuntes?ejercicio=2026", headers=h).get_json()["data"]
    assert [(a["libro"], a["base"], a["cuota"]) for a in ap] == [("emitidas", 100.0, 21.0), ("recibidas", 50.0, 10.5)]
    comp = cliente.get(f"/api/v1/guilda-fiscal/titulares/{c}/comprobacion?ejercicio=2026", headers=h).get_json()["data"]
    assert comp["ok"] and comp["apuntes"] == 2
    sim = cliente.get(f"/api/v1/guilda-fiscal/titulares/{c}/simulacion-303?ejercicio=2026&periodo=2T", headers=h).get_json()["data"]
    assert sim["simulacion"] and sim["resultado"] == 10.5 and sim["casillas"]["71"] == 10.5 and sim["bloqueos"] == [] and "02" not in sim["casillas"]
    assert fn.listar_declaraciones(t, u, c) == []                                         # simular no crea nada


def test_simulacion_con_caso_no_soportado_da_bloqueos_no_numeros(cliente):
    h, t, u, c = _despacho(cliente, "gfapi2@ejemplo.com")
    fp.guardar_perfil(t, u, c, {"forma_juridica": "sociedad", "prorrata_especial": 1}, vigente_desde="2026-01-01")
    for a in ESCENARIOS["basico"][0]:
        fn.aprobar_apunte(t, u, c, a)
    sim = cliente.get(f"/api/v1/guilda-fiscal/titulares/{c}/simulacion-303?ejercicio=2026&periodo=2T", headers=h).get_json()["data"]
    assert sim["bloqueos"] and sim["casillas"] == {}


def test_declaraciones_y_errores(cliente):
    h, t, u, c = _despacho(cliente, "gfapi3@ejemplo.com")
    _con_datos(t, u, c)
    dec = fn.calcular_declaracion(t, u, fn.crear_instantanea(t, u, c, ejercicio=2026, periodo="2T")["id"])
    lista = cliente.get(f"/api/v1/guilda-fiscal/titulares/{c}/declaraciones", headers=h).get_json()["data"]
    assert [(x["id"], x["estado"], x["resultado"]) for x in lista] == [(dec["id"], "borrador", 10.5)]
    d = cliente.get(f"/api/v1/guilda-fiscal/declaraciones/{dec['id']}", headers=h).get_json()["data"]
    assert d["casillas"]["71"] == 10.5 and d["origen"]["07"] and d["ficheros"] == []
    assert cliente.get("/api/v1/guilda-fiscal/declaraciones/99999", headers=h).status_code == 404
    assert cliente.get(f"/api/v1/guilda-fiscal/titulares/{c}/simulacion-303?ejercicio=2026&periodo=9T", headers=h).status_code == 400
    assert cliente.get(f"/api/v1/guilda-fiscal/titulares/{c}/comprobacion", headers=h).status_code == 400


def test_la_api_no_ofrece_ninguna_forma_de_aprobar_ni_presentar(cliente):
    h, t, u, c = _despacho(cliente, "gfapi4@ejemplo.com")
    _con_datos(t, u, c)
    for metodo in ("post", "put", "patch", "delete"):
        for ruta in ("/api/v1/guilda-fiscal/titulares", f"/api/v1/guilda-fiscal/titulares/{c}/apuntes", "/api/v1/guilda-fiscal/declaraciones/1", f"/api/v1/guilda-fiscal/titulares/{c}/simulacion-303"):
            assert getattr(cliente, metodo)(ruta, headers=h, json={}).status_code in (404, 405)
