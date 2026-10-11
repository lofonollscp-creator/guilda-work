"""Restricciones de red de un token: IP permitidas y orígenes CORS."""
import asyncio

import pytest

from app import db, token_restricciones as tr


# --- validación -------------------------------------------------------------------------------------------------------------

def test_validar_origenes():
    assert tr.validar_origenes("https://Panel.Ejemplo.com, https://panel.ejemplo.com") == ["https://panel.ejemplo.com"]
    assert tr.validar_origenes(["http://localhost:3000", "https://a.es:8443"]) == ["http://localhost:3000", "https://a.es:8443"]
    assert tr.validar_origenes(None) == [] and tr.validar_origenes("") == []
    for malo in ("*", "https://*.ejemplo.com", "http://ejemplo.com", "https://ejemplo.com/ruta", "ejemplo.com", "https://u:p@ejemplo.com", "javascript:alert(1)"):
        with pytest.raises(ValueError):
            tr.validar_origenes(malo)
    with pytest.raises(ValueError, match="Máximo"):
        tr.validar_origenes([f"https://a{i}.es" for i in range(tr.MAX_ORIGENES + 1)])


def test_validar_ips_y_pertenencia():
    assert tr.validar_ips("203.0.113.7, 10.0.0.0/24\n2001:db8::1") == ["203.0.113.7", "10.0.0.0/24", "2001:db8::1"]
    with pytest.raises(ValueError):
        tr.validar_ips("no-es-una-ip")
    assert tr.ip_permitida("10.0.0.55", ["10.0.0.0/24"]) and not tr.ip_permitida("10.0.1.1", ["10.0.0.0/24"])
    assert tr.ip_permitida("1.2.3.4", []) and not tr.ip_permitida(None, ["10.0.0.0/24"]) and not tr.ip_permitida("basura", ["10.0.0.0/24"])


# --- IP permitidas en la API -------------------------------------------------------------------------------------------------

def _cab(token, **extra):
    return {"Authorization": f"Bearer {token}", **extra}


def test_un_token_con_ips_solo_funciona_desde_ellas(cliente):
    u = db.crear_usuario_vinculado_a_kratos("ip@x.com", "k-ip")
    tok = db.crear_token_api(u, "restringido", ips_permitidas="198.51.100.0/24")
    r = cliente.get("/api/v1/auth/me", headers=_cab(tok), environ_overrides={"REMOTE_ADDR": "203.0.113.9"})
    assert r.status_code == 403 and r.get_json()["codigo"] == "ip_no_permitida"
    assert cliente.get("/api/v1/auth/me", headers=_cab(tok), environ_overrides={"REMOTE_ADDR": "198.51.100.20"}).status_code == 200
    # un intento desde otra IP no cuenta como uso del token
    assert db.listar_tokens_api(u)[0]["ultima_ip"] == "198.51.100.20"


def test_un_token_con_ips_no_sirve_por_mcp(monkeypatch):
    import mcp_server_remoto as remoto

    u = db.crear_usuario_vinculado_a_kratos("ipm@x.com", "k-ipm")
    con = db.crear_token_api(u, "con ips", ips_permitidas="198.51.100.0/24")
    sin = db.crear_token_api(u, "sin ips")
    monkeypatch.setattr(remoto.hydra, "verificar_token", lambda t: None)
    verificador = remoto.VerificadorHydra()
    assert asyncio.run(verificador.verify_token(con)) is None
    assert asyncio.run(verificador.verify_token(sin)) is not None


# --- CORS --------------------------------------------------------------------------------------------------------------------

ORIGEN = "https://panel.ejemplo.com"


def test_preflight_solo_para_origenes_que_algun_token_admite(cliente):
    u = db.crear_usuario_vinculado_a_kratos("cors@x.com", "k-cors")
    db.crear_token_api(u, "panel", origenes_cors=ORIGEN)
    pedido = {"Origin": ORIGEN, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"}
    r = cliente.options("/api/v1/tareas", headers=pedido)
    assert r.status_code == 204 and r.headers["Access-Control-Allow-Origin"] == ORIGEN and "Origin" in r.headers["Vary"]
    assert "Authorization" in r.headers["Access-Control-Allow-Headers"] and "DELETE" in r.headers["Access-Control-Allow-Methods"]
    ajeno = cliente.options("/api/v1/tareas", headers={**pedido, "Origin": "https://malo.example"})
    assert ajeno.status_code == 204 and "Access-Control-Allow-Origin" not in ajeno.headers


def test_la_respuesta_lleva_cors_solo_si_el_token_admite_ese_origen(cliente):
    u = db.crear_usuario_vinculado_a_kratos("cors2@x.com", "k-cors2")
    con = db.crear_token_api(u, "panel", origenes_cors=ORIGEN)
    sin = db.crear_token_api(u, "otro")
    r = cliente.get("/api/v1/auth/me", headers=_cab(con, Origin=ORIGEN))
    assert r.headers["Access-Control-Allow-Origin"] == ORIGEN and "X-Request-Id" in r.headers["Access-Control-Expose-Headers"]
    assert "Access-Control-Allow-Origin" not in cliente.get("/api/v1/auth/me", headers=_cab(sin, Origin=ORIGEN)).headers
    assert "Access-Control-Allow-Origin" not in cliente.get("/api/v1/auth/me", headers=_cab(con, Origin="https://malo.example")).headers
    assert "Access-Control-Allow-Origin" not in cliente.get("/api/v1/auth/me", headers=_cab(con)).headers          # sin Origin: nada


def test_crear_token_por_la_api_con_restricciones(cliente):
    u = db.crear_usuario_vinculado_a_kratos("cors3@x.com", "k-cors3")
    base = _cab(db.crear_token_api(u, "admin"))
    r = cliente.post("/api/v1/tokens", json={"nombre": "web", "origenes_cors": [ORIGEN], "ips_permitidas": ["203.0.113.7"]}, headers=base)
    assert r.status_code == 201
    datos = r.get_json()["data"]
    assert datos["origenes_cors"] == [ORIGEN] and datos["ips_permitidas"] == ["203.0.113.7"]
    listado = {t["nombre_dispositivo"]: t for t in cliente.get("/api/v1/tokens", headers=base).get_json()["data"]}["web"]
    assert listado["origenes_cors"] == [ORIGEN] and listado["ips_permitidas"] == ["203.0.113.7"]
    malo = cliente.post("/api/v1/tokens", json={"origenes_cors": ["*"]}, headers=base)
    assert malo.status_code == 400 and malo.get_json()["codigo"] == "origenes_invalidos" and malo.get_json()["campo"] == "origenes_cors"
    malo = cliente.post("/api/v1/tokens", json={"ips_permitidas": ["999.1.1.1"]}, headers=base)
    assert malo.status_code == 400 and malo.get_json()["codigo"] == "ips_invalidas"
