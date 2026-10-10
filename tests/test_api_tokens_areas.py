"""Tokens de API con áreas, caducidad, último uso y registro de llamadas; filtros de fecha en tareas de lista."""
from datetime import datetime, timedelta

import pytest

from app import api_areas, db
from tests.test_backoffice_app import bo, entrar, post  # noqa: F401 -- fixture
from tests.test_rutas_api import _auth, _registrar


def _usuario(cliente, email):
    datos = _registrar(cliente, email=email)
    return _auth(datos["token"]), datos["usuario"]["id"]


def _token(cliente, h, **cuerpo):
    r = cliente.post("/api/v1/tokens", json=cuerpo, headers=h)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["data"], _auth(r.get_json()["data"]["token"])


def test_clasificacion_de_rutas_por_area():
    f = api_areas.area_de_ruta
    assert f("/api/v1/notas/5/fijar") == "notas" and f("/api/v1/tareas-outlook/3/checklist") == "tareas"
    assert f("/api/v1/mi-dia") == "tareas" and f("/api/v1/proyectos") == "tareas" and f("/api/v1/correo/mensajes") == "correo"
    assert f("/api/v1/fiscal/clientes") == "fiscal" and f("/api/v1/ia/mensaje/stream") == "ia"
    assert f("/api/v1/historial") == "transversal" and f("/api/v1/sync") == "transversal" and f("/api/v1/ruta-nueva") == "transversal"
    assert f("/api/v1/tokens/3/uso") == "tokens" and f("/api/v1/auth/me") is None and f("/api/v1/openapi.json") is None
    assert api_areas.permite([], "/api/v1/historial") and not api_areas.permite(["notas"], "/api/v1/historial")
    assert api_areas.permite(["notas"], "/api/v1/auth/me") and not api_areas.permite(["notas"], "/api/v1/tokens")
    assert api_areas.validar_areas("notas, correo,notas") == ["correo", "notas"] and api_areas.validar_areas(None) == []
    with pytest.raises(ValueError):
        api_areas.validar_areas(["notas", "nave_espacial"])


def test_token_limitado_a_areas_solo_llega_a_ellas(cliente):
    h, u = _usuario(cliente, "a@ejemplo.com")
    db.asignar_tenant(u, db.crear_tenant("Despacho áreas"))
    cliente.post("/api/v1/notas", json={"texto": "secreta"}, headers=h)
    info, fisc = _token(cliente, h, nombre="integración fiscal", areas=["fiscal"])
    assert info["areas"] == ["fiscal"] and info["id"]
    assert cliente.get("/api/v1/fiscal/clientes", headers=fisc).status_code == 200
    r = cliente.get("/api/v1/notas", headers=fisc)
    assert r.status_code == 403 and r.get_json()["codigo"] == "token_area_no_permitida" and r.get_json()["areas"] == ["fiscal"]
    for ruta in ("/api/v1/historial", "/api/v1/sync", "/api/v1/dashboard", "/api/v1/buscar?q=x", "/api/v1/tokens"):
        assert cliente.get(ruta, headers=fisc).status_code == 403, ruta                  # transversales y tokens: solo sin restricción
    assert cliente.post("/api/v1/tokens", json={"areas": []}, headers=fisc).status_code == 403   # no puede crear uno más amplio
    assert cliente.get("/api/v1/auth/me", headers=fisc).status_code == 200                # identidad propia siempre
    assert cliente.get("/api/v1/openapi.json").status_code == 200
    assert cliente.get("/api/v1/notas", headers=h).status_code == 200                      # el token principal no cambia


def test_areas_y_permisos_se_combinan(cliente):
    h, _ = _usuario(cliente, "b@ejemplo.com")
    _, ro_notas = _token(cliente, h, permisos="solo_lectura", areas=["notas"])
    assert cliente.get("/api/v1/notas", headers=ro_notas).status_code == 200
    assert cliente.post("/api/v1/notas", json={"texto": "x"}, headers=ro_notas).get_json()["codigo"] == "token_solo_lectura"
    assert cliente.get("/api/v1/correo/cuentas", headers=ro_notas).get_json()["codigo"] == "token_area_no_permitida"


def test_validacion_al_crear(cliente):
    h, _ = _usuario(cliente, "v@ejemplo.com")
    r = cliente.post("/api/v1/tokens", json={"areas": ["inventada"]}, headers=h)
    assert r.status_code == 400 and r.get_json()["codigo"] == "areas_invalidas" and r.get_json()["campo"] == "areas"
    for dias in (0, -1, 99999, "7", True):
        r = cliente.post("/api/v1/tokens", json={"caduca_dias": dias}, headers=h)
        assert r.status_code == 400 and r.get_json()["codigo"] == "caducidad_invalida", dias
    r = cliente.post("/api/v1/tokens", json={"caduca_en": "2001-01-01T00:00:00"}, headers=h)
    assert r.status_code == 400 and "pasado" in r.get_json()["error"]
    r = cliente.post("/api/v1/tokens", json={"caduca_en": "no es fecha"}, headers=h)
    assert r.status_code == 400


def test_token_que_caduca_deja_de_valer_con_codigo_propio(cliente):
    h, _ = _usuario(cliente, "c@ejemplo.com")
    info, temporal = _token(cliente, h, caduca_dias=30)
    assert info["caduca_en"] > datetime.now().isoformat()
    assert cliente.get("/api/v1/notas", headers=temporal).status_code == 200
    conn = db.get_connection()
    conn.execute("UPDATE tokens_api SET caduca_en = ? WHERE id = ?", ((datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds"), info["id"]))
    conn.commit(); conn.close()
    r = cliente.get("/api/v1/notas", headers=temporal)
    assert r.status_code == 401 and r.get_json()["codigo"] == "token_caducado"
    assert cliente.get("/api/v1/notas", headers=h).status_code == 200                      # los demás siguen


def test_registro_de_uso_ip_y_listado(cliente):
    h, _ = _usuario(cliente, "u@ejemplo.com")
    info, tok = _token(cliente, h, nombre="Grafana", areas=["notas"])
    cliente.get("/api/v1/notas", headers=tok); cliente.get("/api/v1/notas", headers=tok)
    cliente.get("/api/v1/correo/cuentas", headers=tok)                                        # 403: cuenta como error
    uso = cliente.get(f"/api/v1/tokens/{info['id']}/uso", headers=h).get_json()["data"]
    assert uso == [{"dia": datetime.now().date().isoformat(), "llamadas": 3, "errores": 1}]
    fila = next(t for t in cliente.get("/api/v1/tokens", headers=h).get_json()["data"] if t["id"] == info["id"])
    assert fila["areas"] == ["notas"] and fila["llamadas_30d"] == 3 and fila["ultimo_uso_en"] and fila["ultima_ip"] and "token" not in fila
    otro, _ = _usuario(cliente, "u2@ejemplo.com")
    assert cliente.get(f"/api/v1/tokens/{info['id']}/uso", headers=otro).status_code == 404   # ajeno: no se ve
    assert cliente.get("/api/v1/tokens/999/uso", headers=h).status_code == 404


def test_revocar_corta_al_instante(cliente):
    h, _ = _usuario(cliente, "r@ejemplo.com")
    info, tok = _token(cliente, h)
    assert cliente.delete(f"/api/v1/tokens/{info['id']}", headers=h).status_code == 200
    assert cliente.get("/api/v1/notas", headers=tok).get_json()["codigo"] == "token_invalido"


def test_filtros_de_fecha_en_tareas_de_lista(cliente):
    h, _ = _usuario(cliente, "f@ejemplo.com")
    for asunto, fecha in (("Vieja", "2026-01-10"), ("Media", "2026-06-10"), ("Nueva", "2026-12-10")):
        cliente.post("/api/v1/tareas-outlook", json={"asunto": asunto, "fecha_vencimiento": fecha}, headers=h)
    r = cliente.get("/api/v1/tareas-outlook?desde=2026-05-01&hasta=2026-07-01", headers=h).get_json()["data"]
    assert [t["asunto"] for t in r] == ["Media"]
    assert len(cliente.get("/api/v1/tareas-outlook?desde=2026-05-01", headers=h).get_json()["data"]) == 2


def test_web_crea_token_con_areas_y_caducidad_y_lo_muestra_una_vez(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    uid = iniciar_sesion_de_prueba(cliente, "w@ejemplo.com", "una-clave-larga-1234")
    db.asignar_tenant(uid, db.crear_tenant("Despacho tokens"))
    r = cliente.post("/mis-dispositivos/token", data={"nombre": "Zapier", "permisos": "solo_lectura", "areas": ["fiscal", "notas"], "caduca_dias": "90"})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Zapier" in html and "fiscal, notas" in html and "Caduca el" in html
    t = db.listar_tokens_api(uid)[0]
    assert t["areas"] == '["fiscal", "notas"]' and t["caduca_en"]
    assert "Zapier" in cliente.get("/mis-dispositivos").get_data(as_text=True)
    assert cliente.post("/mis-dispositivos/token", data={"areas": ["inventada"]}).status_code == 400
    assert cliente.post("/mis-dispositivos/token", data={"caduca_dias": "0"}).status_code in (200, 400)


def test_backoffice_lista_y_revoca_tokens(bo):
    entrar(bo)
    t = db.crear_tenant("Despacho BO tokens")
    u = db.crear_usuario_vinculado_a_kratos("bo@ejemplo.com", "k-bo")
    db.asignar_tenant(u, t)
    tok = db.crear_token_api(u, "Integración X", "solo_lectura", areas=["fiscal"])
    tid = db.id_de_token(tok)
    db.registrar_uso_token(tid, 200); db.registrar_uso_token(tid, 500)
    html = bo.get("/tokens-api").get_data(as_text=True)
    assert "Integración X" in html and "Solo lectura" in html and "fiscal" in html and "2 llamadas" in html and "1 errores" in html
    assert "Integración X" not in bo.get(f"/tokens-api?tenant={t + 99}").get_data(as_text=True)
    assert post(bo, f"/tokens-api/{tid}/revocar").status_code == 302
    assert db.autenticar_token_completo(tok) is None
    assert post(bo, "/tokens-api/9999/revocar").status_code == 404
    assert "token_api.revocar" in bo.get("/actividad").get_data(as_text=True)
