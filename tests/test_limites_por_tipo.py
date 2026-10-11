"""Límites de la API por tipo de petición: lecturas, escrituras y operaciones pesadas tienen cupos distintos."""
import pytest

from app import auth, db


@pytest.fixture(autouse=True)
def _limpio():
    auth.reiniciar_limite_api()


def _cab(token):
    return {"Authorization": f"Bearer {token}"}


def test_clasificacion_de_peticiones():
    t = auth.tipo_de_peticion
    assert t("GET", "/api/v1/tareas") == "lectura"
    for metodo in ("POST", "PUT", "PATCH", "DELETE"):
        assert t(metodo, "/api/v1/notas") == "escritura"
    for ruta in ("/api/v1/ia/mensaje", "/api/v1/ia/mensaje/stream", "/api/v1/ia/confirmar", "/api/v1/fichaje/admin/exportar.pdf",
                 "/api/v1/correo/cuentas/3/sincronizar", "/api/v1/correo/enviar", "/api/v1/importar/tareas"):
        assert t("POST" if "exportar" not in ruta else "GET", ruta) == "pesada", ruta
    assert t("GET", "/api/v1/ia/mensajes") == "lectura"      # leer el historial del chat no es una llamada al modelo


def test_las_escrituras_tienen_su_propio_tope_y_las_lecturas_siguen(cliente, monkeypatch):
    monkeypatch.setattr(auth, "API_LIMITE_ESCRITURAS_POR_MINUTO", 2)
    u = db.crear_usuario_vinculado_a_kratos("lim@x.com", "k-lim")
    h = _cab(db.crear_token_api(u, "t"))
    assert cliente.post("/api/v1/notas", json={"texto": "uno"}, headers=h).status_code == 201
    r = cliente.post("/api/v1/notas", json={"texto": "dos"}, headers=h)
    assert r.status_code == 201 and r.headers["X-RateLimit-Scope"] == "escritura" and r.headers["X-RateLimit-Remaining"] == "0"
    bloqueada = cliente.post("/api/v1/notas", json={"texto": "tres"}, headers=h)
    assert bloqueada.status_code == 429 and bloqueada.get_json()["codigo"] == "limite_excedido" and bloqueada.get_json()["cupo"] == "escritura"
    assert int(bloqueada.headers["Retry-After"]) >= 1
    leer = cliente.get("/api/v1/notas", headers=h)
    assert leer.status_code == 200 and leer.headers["X-RateLimit-Scope"] == "total"


def test_una_peticion_rechazada_no_gasta_cupo_total(cliente, monkeypatch):
    monkeypatch.setattr(auth, "API_LIMITE_ESCRITURAS_POR_MINUTO", 1)
    monkeypatch.setattr(auth, "API_LIMITE_POR_MINUTO", 5)
    u = db.crear_usuario_vinculado_a_kratos("lim2@x.com", "k-lim2")
    h = _cab(db.crear_token_api(u, "t"))
    cliente.post("/api/v1/notas", json={"texto": "a"}, headers=h)
    for _ in range(10):
        assert cliente.post("/api/v1/notas", json={"texto": "b"}, headers=h).status_code == 429
    # 1 escritura aceptada: quedan 4 del total para leer, no se gastaron en los 10 rechazos
    for _ in range(4):
        assert cliente.get("/api/v1/notas", headers=h).status_code == 200
    assert cliente.get("/api/v1/notas", headers=h).status_code == 429


def test_las_pesadas_tienen_el_cupo_mas_bajo_y_es_por_persona(cliente, monkeypatch):
    monkeypatch.setattr(auth, "API_LIMITE_PESADAS_POR_MINUTO", 1)
    a = db.crear_usuario_vinculado_a_kratos("pa@x.com", "k-pa")
    b = db.crear_usuario_vinculado_a_kratos("pb@x.com", "k-pb")
    ha, hb = _cab(db.crear_token_api(a, "t")), _cab(db.crear_token_api(b, "t"))
    cuenta = db.crear_cuenta_correo(a, "C", "imap", "h", 993, "a@x.com")
    cliente.post(f"/api/v1/correo/cuentas/{cuenta}/sincronizar", headers=ha)
    r = cliente.post(f"/api/v1/correo/cuentas/{cuenta}/sincronizar", headers=ha)
    assert r.status_code == 429 and r.get_json()["cupo"] == "pesada"
    assert cliente.post("/api/v1/notas", json={"texto": "x"}, headers=ha).status_code == 201     # las escrituras normales siguen
    cuenta_b = db.crear_cuenta_correo(b, "C", "imap", "h", 993, "b@x.com")
    assert cliente.post(f"/api/v1/correo/cuentas/{cuenta_b}/sincronizar", headers=hb).status_code != 429
