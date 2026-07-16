"""Tests de app/rutas_api.py (Fase 2 de la app móvil: API REST con
autenticación por token). Cubre el flujo registro/login/token, un CRUD
básico por sección y el aislamiento cruzado entre usuarios (un token no
debe poder leer/tocar recursos de otro usuario)."""
from app import correo, db


class _ConexionImapFalsa:
    def logout(self):
        pass


def _mock_imap(monkeypatch):
    monkeypatch.setattr(correo, "_conectar_imap", lambda *a, **k: _ConexionImapFalsa())


def _registrar(cliente, email="a@ejemplo.com", contrasena="contrasena123"):
    resp = cliente.post("/api/v1/auth/registro", json={"email": email, "contrasena": contrasena})
    assert resp.status_code == 201
    return resp.get_json()["data"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- Auth --------------------------------------------------------------------

def test_registro_devuelve_token_utilizable(cliente):
    datos = _registrar(cliente)
    assert datos["token"]
    resp = cliente.get("/api/v1/categorias", headers=_auth(datos["token"]))
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "data": []}


def test_registro_duplicado_falla(cliente):
    _registrar(cliente, email="dup@ejemplo.com")
    resp = cliente.post("/api/v1/auth/registro", json={"email": "dup@ejemplo.com", "contrasena": "contrasena123"})
    assert resp.status_code == 409
    assert resp.get_json()["ok"] is False


def test_login_correcto_e_incorrecto(cliente):
    _registrar(cliente, email="b@ejemplo.com", contrasena="contrasena123")

    resp = cliente.post("/api/v1/auth/login", json={"email": "b@ejemplo.com", "contrasena": "mala"})
    assert resp.status_code == 401

    resp = cliente.post("/api/v1/auth/login", json={"email": "b@ejemplo.com", "contrasena": "contrasena123"})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["token"]


def test_sin_token_devuelve_401(cliente):
    resp = cliente.get("/api/v1/categorias")
    assert resp.status_code == 401
    assert resp.get_json()["ok"] is False


def test_logout_revoca_el_token(cliente):
    token = _registrar(cliente, email="c@ejemplo.com")["token"]
    assert cliente.post("/api/v1/auth/logout", headers=_auth(token)).status_code == 200
    resp = cliente.get("/api/v1/categorias", headers=_auth(token))
    assert resp.status_code == 401


# --- Categorías ----------------------------------------------------------------

def test_crud_categorias(cliente):
    token = _registrar(cliente, email="cat@ejemplo.com")["token"]
    h = _auth(token)

    resp = cliente.post("/api/v1/categorias", json={"nombre": "Guilda", "color": "#4a6cf7"}, headers=h)
    assert resp.status_code == 201
    categoria_id = resp.get_json()["data"]["id"]

    resp = cliente.get("/api/v1/categorias", headers=h)
    assert [c["nombre"] for c in resp.get_json()["data"]] == ["Guilda"]

    resp = cliente.post(f"/api/v1/categorias/{categoria_id}/favorito", headers=h)
    assert resp.get_json()["data"]["favorito"] == 1

    resp = cliente.delete(f"/api/v1/categorias/{categoria_id}", headers=h)
    assert resp.status_code == 200
    assert cliente.get("/api/v1/categorias", headers=h).get_json()["data"] == []


# --- Notas y tareas con duración -----------------------------------------------

def test_crear_nota_aparece_en_historial(cliente):
    token = _registrar(cliente, email="nota@ejemplo.com")["token"]
    h = _auth(token)

    resp = cliente.post("/api/v1/notas", json={"texto": "Nota de prueba"}, headers=h)
    assert resp.status_code == 201

    resp = cliente.get("/api/v1/historial", headers=h)
    filas = resp.get_json()["data"]
    assert len(filas) == 1
    assert filas[0]["texto"] == "Nota de prueba"
    assert filas[0]["origen"] == "nota"


def test_crear_y_finalizar_tarea(cliente):
    token = _registrar(cliente, email="tarea@ejemplo.com")["token"]
    h = _auth(token)
    categoria_id = cliente.post("/api/v1/categorias", json={"nombre": "Guilda"}, headers=h).get_json()["data"]["id"]

    resp = cliente.post(
        "/api/v1/tareas", json={"nombre": "Proceso", "categoria_id": categoria_id, "tipo": "duracion"}, headers=h,
    )
    assert resp.status_code == 201
    tarea_id = resp.get_json()["data"]["id"]

    resp = cliente.get("/api/v1/dashboard", headers=h)
    assert any(t["id"] == tarea_id for t in resp.get_json()["data"]["tareas_activas"])

    cliente.post(f"/api/v1/tareas/{tarea_id}/finalizar", headers=h)
    resp = cliente.get("/api/v1/dashboard", headers=h)
    assert resp.get_json()["data"]["tareas_activas"] == []


# --- Tareas Outlook --------------------------------------------------------------

def test_crud_tareas_outlook(cliente):
    token = _registrar(cliente, email="outlook@ejemplo.com")["token"]
    h = _auth(token)

    resp = cliente.post("/api/v1/tareas-outlook", json={"asunto": "Llamar a cliente"}, headers=h)
    assert resp.status_code == 201
    tarea_id = resp.get_json()["data"]["id"]

    resp = cliente.put(f"/api/v1/tareas-outlook/{tarea_id}", json={"prioridad": "alta"}, headers=h)
    assert resp.get_json()["data"]["prioridad"] == "alta"

    resp = cliente.post(f"/api/v1/tareas-outlook/{tarea_id}/completar", headers=h)
    assert resp.get_json()["data"]["estado"] == "completada"

    resp = cliente.delete(f"/api/v1/tareas-outlook/{tarea_id}", headers=h)
    assert resp.status_code == 200
    assert cliente.get("/api/v1/tareas-outlook", headers=h, query_string={"completadas": "1"}).get_json()["data"] == []


# --- Correo ----------------------------------------------------------------------

def test_crud_cuenta_correo_y_ajustes(cliente, monkeypatch):
    _mock_imap(monkeypatch)
    token = _registrar(cliente, email="correo@ejemplo.com")["token"]
    h = _auth(token)

    resp = cliente.post(
        "/api/v1/correo/cuentas",
        json={"nombre": "Trabajo", "protocolo": "imap", "host": "imap.ejemplo.com", "puerto": 993, "usuario": "yo@ejemplo.com", "contrasena": "x"},
        headers=h,
    )
    assert resp.status_code == 201
    cuenta_id = resp.get_json()["data"]["id"]

    assert len(cliente.get("/api/v1/correo/cuentas", headers=h).get_json()["data"]) == 1

    resp = cliente.post("/api/v1/correo/ajustes", json={"densidad": "compacta", "limite_mensajes": 100}, headers=h)
    assert resp.get_json()["data"]["densidad"] == "compacta"

    resp = cliente.delete(f"/api/v1/correo/cuentas/{cuenta_id}", headers=h)
    assert resp.status_code == 200
    assert cliente.get("/api/v1/correo/cuentas", headers=h).get_json()["data"] == []


def test_mensaje_de_correo_leer_y_destacar(cliente):
    token = _registrar(cliente, email="msg@ejemplo.com")["token"]
    usuario_id = db.obtener_usuario_por_email("msg@ejemplo.com")["id"]
    h = _auth(token)

    cuenta_id = db.crear_cuenta_correo(usuario_id, "Trabajo", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    db.guardar_mensaje_correo(
        cuenta_id=cuenta_id, uid="1", asunto="Hola", remitente="a@b.com", destinatarios="yo@ejemplo.com",
        fecha=None, cuerpo_texto="cuerpo", cuerpo_html=None,
    )
    mensaje_id = db.listar_mensajes_correo(cuenta_id)[0]["id"]

    resp = cliente.get(f"/api/v1/correo/mensajes/{mensaje_id}", headers=h)
    assert resp.status_code == 200
    assert resp.get_json()["data"]["asunto"] == "Hola"

    resp = cliente.post(f"/api/v1/correo/mensajes/{mensaje_id}/destacar", json={"destacado": True}, headers=h)
    assert resp.status_code == 200
    assert cliente.get(f"/api/v1/correo/mensajes/{mensaje_id}", headers=h).get_json()["data"]["destacado"] == 1


# --- Asistente IA -----------------------------------------------------------------

def test_ajustes_y_mensajes_ia(cliente):
    token = _registrar(cliente, email="ia@ejemplo.com")["token"]
    h = _auth(token)

    resp = cliente.get("/api/v1/ia/ajustes", headers=h)
    assert resp.status_code == 200
    assert resp.get_json()["data"]["api_key_configurada"] is False

    resp = cliente.post("/api/v1/ia/ajustes", json={"modelo": "anthropic/claude-sonnet-4.5", "api_key": "clave-secreta"}, headers=h)
    assert resp.status_code == 200

    resp = cliente.get("/api/v1/ia/ajustes", headers=h)
    assert resp.get_json()["data"]["modelo"] == "anthropic/claude-sonnet-4.5"
    assert resp.get_json()["data"]["api_key_configurada"] is True

    assert cliente.get("/api/v1/ia/mensajes", headers=h).get_json()["data"] == []
    assert cliente.post("/api/v1/ia/vaciar", headers=h).status_code == 200


# --- Aislamiento cruzado entre usuarios --------------------------------------------

def test_un_token_no_ve_ni_toca_recursos_de_otro_usuario(cliente):
    token_a = _registrar(cliente, email="usera@ejemplo.com")["token"]
    token_b = _registrar(cliente, email="userb@ejemplo.com")["token"]
    h_a, h_b = _auth(token_a), _auth(token_b)

    categoria_id = cliente.post("/api/v1/categorias", json={"nombre": "Solo de A"}, headers=h_a).get_json()["data"]["id"]

    # B no ve la categoría de A en su propio listado.
    assert cliente.get("/api/v1/categorias", headers=h_b).get_json()["data"] == []

    # B no puede eliminarla ni marcarla favorita adivinando el id: 404, no 403
    # (para no filtrar siquiera que el recurso existe).
    assert cliente.delete(f"/api/v1/categorias/{categoria_id}", headers=h_b).status_code == 404
    assert cliente.post(f"/api/v1/categorias/{categoria_id}/favorito", headers=h_b).status_code == 404

    # La categoría de A sigue intacta.
    assert len(cliente.get("/api/v1/categorias", headers=h_a).get_json()["data"]) == 1


def test_un_token_no_puede_leer_mensaje_de_correo_de_otro_usuario(cliente):
    token_a = _registrar(cliente, email="usera2@ejemplo.com")["token"]
    token_b = _registrar(cliente, email="userb2@ejemplo.com")["token"]
    usuario_a = db.obtener_usuario_por_email("usera2@ejemplo.com")["id"]

    cuenta_id = db.crear_cuenta_correo(usuario_a, "Trabajo", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    db.guardar_mensaje_correo(
        cuenta_id=cuenta_id, uid="1", asunto="Secreto de A", remitente="a@b.com", destinatarios="yo@ejemplo.com",
        fecha=None, cuerpo_texto="cuerpo", cuerpo_html=None,
    )
    mensaje_id = db.listar_mensajes_correo(cuenta_id)[0]["id"]

    resp = cliente.get(f"/api/v1/correo/mensajes/{mensaje_id}", headers=_auth(token_b))
    assert resp.status_code == 404
