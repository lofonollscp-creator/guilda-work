"""API REST de Gabinete e Inmobiliaria (app/rutas_api_verticales.py), mensajes del enlace público (también por MCP/IA) y comprobación de certificados por API."""
from datetime import datetime, timedelta

import pytest

import mcp_tools
from app import abogados as ab
from app import api_areas, db, nucleo, verticales
from app import ia_herramientas as ih
from app import inmobiliaria as im
from app import mensajes_enlace
from tests.test_rutas_api import _auth, _registrar


def _despacho(cliente, email, modulo):
    d = _registrar(cliente, email=email)
    u = d["usuario"]["id"]
    t = db.crear_tenant("Despacho " + email)
    db.asignar_tenant(u, t)
    if modulo:
        verticales.fijar_activo(t, modulo, True)
    return _auth(d["token"]), t, u


def test_areas_y_herramientas_nuevas():
    f = api_areas.area_de_ruta
    assert f("/api/v1/abogados/vistas") == "abogados" and f("/api/v1/inmobiliaria/resumen") == "inmobiliaria"
    for n in ("mensajes_de_enlace", "responder_mensaje_de_enlace", "comprobar_certificado"):
        assert any(t.__name__ == n for t in mcp_tools.TOOLS), n


def test_sin_modulo_activo_es_404_y_sin_token_401(cliente):
    h, _t, _u = _despacho(cliente, "sinmod@ejemplo.com", None)
    for ruta in ("/api/v1/abogados/vistas", "/api/v1/inmobiliaria/resumen"):
        r = cliente.get(ruta, headers=h)
        assert r.status_code == 404 and r.get_json()["codigo"] == "no_encontrado"
        assert cliente.get(ruta).status_code == 401


def test_gabinete_por_api(cliente):
    h, t, u = _despacho(cliente, "bufete@ejemplo.com", "abogados")
    c = nucleo.crear_cliente(t, "Cliente Uno", nif="B12345678")
    x = nucleo.crear_expediente(t, u, c, "Reclamación", tipo="procedimiento_judicial")
    ab.registrar_movimiento(t, u, x, "provision", "1.000,00", "Provisión inicial", "2026-10-01")
    ab.anadir_parte(t, u, x, "contraparte", "Deudores S.A.", "A11111111")
    ab.crear_vista(t, u, x, (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%dT10:00"), "juicio", "Sala 3")
    p = cliente.get(f"/api/v1/abogados/expedientes/{x}/provision", headers=h).get_json()["data"]
    assert p["saldo_centimos"] == 100000 and p["provisiones"] == "1.000,00 €"
    assert [q["nif"] for q in cliente.get(f"/api/v1/abogados/expedientes/{x}/partes", headers=h).get_json()["data"]] == ["A11111111"]
    assert [v["lugar"] for v in cliente.get("/api/v1/abogados/vistas?dias=10", headers=h).get_json()["data"]] == ["Sala 3"]
    assert cliente.get("/api/v1/abogados/vistas?dias=1", headers=h).get_json()["data"] == []
    r = cliente.get("/api/v1/abogados/conflictos?nombre=Deudores S.A.&nif=A11111111", headers=h).get_json()["data"]
    assert r["hay_conflicto"] is True
    assert cliente.get("/api/v1/abogados/conflictos", headers=h).status_code == 400
    assert cliente.get("/api/v1/abogados/conflictos?nombre=x&como=otro", headers=h).status_code == 400
    assert cliente.get("/api/v1/abogados/expedientes/9999/provision", headers=h).status_code == 404


def test_un_despacho_ajeno_y_un_confidencial_no_se_ven(cliente):
    h1, t1, u1 = _despacho(cliente, "uno@ejemplo.com", "abogados")
    h2, _t2, _u2 = _despacho(cliente, "dos@ejemplo.com", "abogados")
    x = nucleo.crear_expediente(t1, u1, nucleo.crear_cliente(t1, "C"), "Asunto", tipo="procedimiento_judicial")
    assert cliente.get(f"/api/v1/abogados/expedientes/{x}/provision", headers=h1).status_code == 200
    assert cliente.get(f"/api/v1/abogados/expedientes/{x}/provision", headers=h2).status_code == 404
    assert cliente.get(f"/api/v1/abogados/expedientes/{x}/mensajes", headers=h2).status_code == 404
    assert cliente.post(f"/api/v1/abogados/expedientes/{x}/mensajes", json={"texto": "hola"}, headers=h2).status_code == 404


def test_inmobiliaria_por_api(cliente):
    h, t, u = _despacho(cliente, "agencia@ejemplo.com", "inmobiliaria")
    prop = nucleo.crear_cliente(t, "Propietario", nif="12345678Z")
    i, x = im.crear_inmueble(t, u, prop, "venta", "Calle Uno 1", municipio="Madrid", tipo="piso", habitaciones=3, precio="250.000")
    for e in ("valoracion", "mandato", "publicado"):
        nucleo.cambiar_estado_expediente(t, u, x, e)
    r = cliente.get("/api/v1/inmobiliaria/inmuebles?operacion=venta&municipio=Madrid", headers=h).get_json()["data"]
    assert [q["direccion"] for q in r] == ["Calle Uno 1"] and r[0]["precio"] == "250.000,00 €"
    assert cliente.get("/api/v1/inmobiliaria/inmuebles?operacion=alquiler", headers=h).get_json()["data"] == []
    d = im.crear_demanda(t, u, nucleo.crear_cliente(t, "Comprador"), "venta", municipios=["Madrid"], presupuesto_max="300.000")
    cr = cliente.get(f"/api/v1/inmobiliaria/demandas/{d}/cruces?minimo=1", headers=h).get_json()["data"]
    assert cr and cr[0]["inmueble"]["direccion"] == "Calle Uno 1" and cr[0]["motivos"]
    im.crear_visita(t, u, i, (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%dT11:00"), visitante="Visitante")
    assert [v["visitante_nombre"] for v in cliente.get("/api/v1/inmobiliaria/visitas", headers=h).get_json()["data"]] == ["Visitante"]
    assert cliente.get("/api/v1/inmobiliaria/resumen", headers=h).get_json()["data"]["inmuebles_activos"] == 1


@pytest.mark.parametrize("vertical,ruta", [("abogados", "abogados/expedientes"), ("inmobiliaria", "inmobiliaria/inmuebles")])
def test_mensajes_del_enlace_por_api_mcp_e_ia(cliente, vertical, ruta):
    h, t, u = _despacho(cliente, f"msg-{vertical}@ejemplo.com", vertical)
    if vertical == "abogados":
        x = nucleo.crear_expediente(t, u, nucleo.crear_cliente(t, "C"), "Asunto", tipo="procedimiento_judicial")
        token = ab.crear_enlace(t, u, x, permite_mensajes=True)
    else:
        _i, x = im.crear_inmueble(t, u, nucleo.crear_cliente(t, "P"), "venta", "Calle Uno 1", precio="100.000")
        token = im.crear_enlace(t, u, _i, permite_mensajes=True)
    url = f"/api/v1/{ruta}/{x}/mensajes"
    assert cliente.get(url, headers=h).get_json()["data"]["mensajes"] == []
    mensajes_enlace.enviar_externo(vertical, token, "Cliente Real", "¿Cómo va?")
    hilo = cliente.get(url, headers=h).get_json()["data"]
    assert hilo["admite_respuesta"] is True and hilo["sin_leer"] == 1 and hilo["mensajes"][0]["texto"] == "¿Cómo va?"
    assert cliente.get(url, headers=h).get_json()["data"]["sin_leer"] == 1, "leer por API no los marca como leídos"
    assert cliente.post(url, json={"texto": "Todo en orden"}, headers=h).status_code == 200
    assert cliente.post(url, json={"texto": " "}, headers=h).status_code == 400
    assert [m["autor"] for m in cliente.get(url, headers=h).get_json()["data"]["mensajes"]] == ["externo", "despacho"]
    assert ih.ejecutar(u, "mensajes_de_enlace", {"vertical": vertical, "expediente_id": x})["mensajes"][1]["texto"] == "Todo en orden"
    ih.ejecutar(u, "responder_mensaje_de_enlace", {"vertical": vertical, "expediente_id": x, "texto": "Desde la IA"})
    assert len(cliente.get(url, headers=h).get_json()["data"]["mensajes"]) == 3
    assert ih.necesita_confirmacion("responder_mensaje_de_enlace", modo_autonomo=False) and not ih.necesita_confirmacion("mensajes_de_enlace", modo_autonomo=False)
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(u, "mensajes_de_enlace", {"vertical": "otra", "expediente_id": x})


def test_responder_sin_enlace_que_admita_mensajes_falla(cliente):
    h, t, u = _despacho(cliente, "sinenlace@ejemplo.com", "abogados")
    x = nucleo.crear_expediente(t, u, nucleo.crear_cliente(t, "C"), "Asunto", tipo="procedimiento_judicial")
    ab.crear_enlace(t, u, x)                      # sin permitir mensajes
    assert cliente.get(f"/api/v1/abogados/expedientes/{x}/mensajes", headers=h).get_json()["data"]["admite_respuesta"] is False
    assert cliente.post(f"/api/v1/abogados/expedientes/{x}/mensajes", json={"texto": "hola"}, headers=h).status_code == 400


def test_comprobar_certificado_por_api(cliente):
    from app import certificados
    h, t, u = _despacho(cliente, "cert@ejemplo.com", None)
    assert cliente.post("/api/v1/certificados/999/comprobar", headers=h).status_code in (403, 404)
    _c = db.get_connection(); _c.execute("UPDATE usuarios SET custodio_certificados = 1 WHERE id = ?", (u,));  _c.commit(); _c.close()
    assert cliente.post("/api/v1/certificados/999/comprobar", headers=h).status_code == 404
    r = certificados.alta_rapida(t, u, tipo="dnie", caduca="2030-01-01", titular="Ana")
    resp = cliente.post(f"/api/v1/certificados/{r['id']}/comprobar", headers=h)
    assert resp.status_code == 400 and resp.get_json()["codigo"] == "certificado_no_valido"
    assert cliente.post(f"/api/v1/certificados/{r['id']}/comprobar").status_code == 401
