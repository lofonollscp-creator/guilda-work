"""`GET /api/v1/hoy`: la bandeja única de la app móvil, con destinos tipados (API 1.5, S-01 del plan de la app móvil)."""
from datetime import date, timedelta

from app import api_areas, db
from tests.test_api_fiscal import _cliente_fiscal, _despacho
from tests.test_rutas_api import _auth


def _venc_mio(cliente, h, uid, cid, fecha):
    """Un vencimiento con la persona como responsable (en «Hoy» salen los de quien los lleva)."""
    r = cliente.post("/api/v1/fiscal/vencimientos", json={"cliente_id": cid, "modelo": "303", "periodo": "3T 2030", "fecha_limite": fecha, "usuario_id": uid}, headers=h)
    assert r.status_code == 201
    return r.get_json()["data"]["id"]


def _hoy(cliente, h, **cabeceras):
    r = cliente.get("/api/v1/hoy", headers={**h, **cabeceras})
    assert r.status_code == 200
    return r.get_json()["data"]


def test_requiere_token(cliente):
    assert cliente.get("/api/v1/hoy").status_code == 401


def test_sin_nada_pendiente_la_bandeja_va_vacia(cliente):
    h, _, t = _despacho(cliente, "vacio@ejemplo.com")
    d = _hoy(cliente, h)
    assert d["total"] == 0 and d["urgentes"] == 0 and d["secciones"] == [] and d["destacados"] == []
    assert d["despacho_id"] == t and d["generado_en"]


def test_cada_elemento_trae_destino_tipado_y_acciones(cliente):
    h, uid, _ = _despacho(cliente, "bandeja@ejemplo.com")
    ayer, hoy = (date.today() - timedelta(days=1)).isoformat(), date.today().isoformat()
    tarea = cliente.post("/api/v1/tareas-outlook", json={"asunto": "Llamar a Acme", "fecha_vencimiento": ayer}, headers=h).get_json()["data"]["id"]
    cid = _cliente_fiscal(cliente, h)
    vid = _venc_mio(cliente, h, uid, cid, hoy)
    d = _hoy(cliente, h)
    por_clave = {s["clave"]: s for s in d["secciones"]}
    assert {"tareas", "vencimientos"} <= set(por_clave)
    t = por_clave["tareas"]["elementos"][0]
    assert t["titulo"] == "Llamar a Acme" and t["urgencia"] == "vencido"
    assert t["destino"] == {"tipo": "tarea", "id": tarea} and t["acciones"] == ["abrir", "completar"] and t["url"].startswith("/")
    v = por_clave["vencimientos"]["elementos"][0]
    assert v["destino"] == {"tipo": "vencimiento", "id": vid, "cliente_fiscal_id": cid} and v["acciones"] == ["abrir", "presentar"]
    assert v["urgencia"] == "hoy"
    assert d["total"] >= 2 and d["urgentes"] >= 2
    assert d["destacados"][0]["urgencia"] == "vencido" and d["destacados"][0]["clave"] == "tareas"      # lo más urgente, primero
    assert all("destino" in e for s in d["secciones"] for e in s["elementos"])


def test_x_despacho_enseña_la_bandeja_del_despacho_elegido(cliente):
    h, uid, t1 = _despacho(cliente, "dos@ejemplo.com")
    t2 = db.crear_tenant("Segundo despacho")
    db.anadir_usuario_a_tenant(uid, t2)
    cid = _cliente_fiscal(cliente, h)
    _venc_mio(cliente, h, uid, cid, date.today().isoformat())
    assert "vencimientos" in {s["clave"] for s in _hoy(cliente, h)["secciones"]}
    otro = _hoy(cliente, h, **{"X-Despacho": str(t2)})
    assert otro["despacho_id"] == t2 and "vencimientos" not in {s["clave"] for s in otro["secciones"]}


def test_es_una_ruta_transversal_solo_para_tokens_sin_restriccion_de_areas():
    assert api_areas.area_de_ruta("/api/v1/hoy") == "transversal"
