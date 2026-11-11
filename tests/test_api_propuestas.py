"""API de la bandeja de propuestas (W15): listar, aprobar y rechazar con token; solo lectura no resuelve; áreas; aislamiento entre despachos."""
from app import api_areas, db, ia_propuestas as ip
from tests.test_api_fiscal import _despacho
from tests.test_rutas_api import _auth


def _cliente_de(t, nombre="Cliente API SL"):
    return db.crear_cliente_fiscal(t, nombre, email="api@ejemplo.com")


def test_requiere_token(cliente):
    assert cliente.get("/api/v1/propuestas").status_code == 401
    assert cliente.post("/api/v1/propuestas/1/aprobar").status_code == 401


def test_listar_aprobar_y_rechazar_por_la_api(cliente):
    h, uid, t = _despacho(cliente, "api-prop@ejemplo.com")
    c = _cliente_de(t)
    a = ip.proponer(t, clave="a", tipo="tarea", titulo="Llamar al cliente", detalle="Falta el extracto", origen="alerta", cliente_fiscal_id=c, prioridad="alta")
    b = ip.proponer(t, clave="b", tipo="tarea", titulo="Revisar el IVA", origen="facturas", cliente_fiscal_id=c)
    lista = cliente.get("/api/v1/propuestas", headers=h).get_json()["data"]["propuestas"]
    assert [p["id"] for p in lista] == [a, b] and lista[0]["prioridad"] == "alta" and lista[0]["cliente_id"] == c and "datos" not in lista[0]
    r = cliente.post(f"/api/v1/propuestas/{a}/aprobar", headers=h)
    assert r.status_code == 200 and r.get_json()["data"]["estado"] == "aprobada" and r.get_json()["data"]["resultado"].startswith("tarea:")
    assert cliente.post(f"/api/v1/propuestas/{a}/aprobar", headers=h).status_code == 409                     # ya resuelta
    r = cliente.post(f"/api/v1/propuestas/{b}/rechazar", headers=h)
    assert r.get_json()["data"]["estado"] == "rechazada"
    assert cliente.get("/api/v1/propuestas", headers=h).get_json()["data"]["propuestas"] == []
    assert cliente.post("/api/v1/propuestas/9999/aprobar", headers=h).status_code == 404


def test_un_token_de_solo_lectura_lista_pero_no_resuelve(cliente):
    h, uid, t = _despacho(cliente, "api-prop-ro@ejemplo.com")
    pid = ip.proponer(t, clave="a", tipo="tarea", titulo="Algo", cliente_fiscal_id=_cliente_de(t))
    r = cliente.post("/api/v1/tokens", json={"nombre": "solo lectura", "permisos": "solo_lectura"}, headers=h)
    assert r.status_code == 201
    ro = _auth(r.get_json()["data"]["token"])
    assert len(cliente.get("/api/v1/propuestas", headers=ro).get_json()["data"]["propuestas"]) == 1
    assert cliente.post(f"/api/v1/propuestas/{pid}/aprobar", headers=ro).status_code == 403
    assert ip.obtener(t, pid)["estado"] == "pendiente"


def test_las_propuestas_son_del_area_ia_y_no_se_ven_entre_despachos(cliente):
    assert api_areas.area_de_ruta("/api/v1/propuestas") == "ia" and api_areas.area_de_ruta("/api/v1/propuestas/3/aprobar") == "ia"
    h1, u1, t1 = _despacho(cliente, "api-prop-1@ejemplo.com")
    h2, u2, t2 = _despacho(cliente, "api-prop-2@ejemplo.com")
    pid = ip.proponer(t1, clave="a", tipo="tarea", titulo="De otro despacho", cliente_fiscal_id=_cliente_de(t1))
    assert cliente.get("/api/v1/propuestas", headers=h2).get_json()["data"]["propuestas"] == []
    assert cliente.post(f"/api/v1/propuestas/{pid}/aprobar", headers=h2).status_code == 404
    r = cliente.post("/api/v1/tokens", json={"nombre": "solo notas", "areas": ["notas"]}, headers=h1)
    solo_notas = _auth(r.get_json()["data"]["token"])
    assert cliente.get("/api/v1/propuestas", headers=solo_notas).status_code == 403                  # un token limitado a otra área no llega
