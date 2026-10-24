"""Lo que la cola sin conexión de la app móvil exige a la API de fichaje y notas: reenviar con el mismo `cliente_uuid` (y la misma `Idempotency-Key`) no duplica,
y `marca_tiempo` / `creada_en` conservan la hora real en la que se pulsó. Contrato que usa `mobile/lib/funciones/fichaje` y `mobile/lib/funciones/notas`."""
from datetime import datetime, timedelta

from app import db
from tests.test_api_tareas import _usuario


def _arranque(cliente, correo):
    t = db.crear_tenant("Despacho offline")
    h, uid = _usuario(cliente, correo, t)
    # Para fichar hace falta tener rellenados el nombre completo y el DNI/NIE («Mis datos»).
    assert cliente.post("/api/v1/fichaje/mis-datos", json={"nombre_completo": "Ana Pla Ros", "dni_nie": "12345678Z"}, headers=h).status_code in (200, 201)
    return h, uid


def test_fichar_dos_veces_con_el_mismo_cliente_uuid_ficha_una_sola_vez(cliente):
    h, _ = _arranque(cliente, "fichar-uuid@ejemplo.com")
    cuerpo = {"tipo": "entrada", "cliente_uuid": "11111111-1111-4111-8111-111111111111"}
    a = cliente.post("/api/v1/fichaje/marcar", json=cuerpo, headers=h)
    b = cliente.post("/api/v1/fichaje/marcar", json=cuerpo, headers=h)
    assert a.status_code == 200 and b.status_code == 200
    assert a.get_json()["data"]["estado"] == b.get_json()["data"]["estado"] == "dentro"
    hoy = datetime.now().date().isoformat()
    filas = cliente.get(f"/api/v1/fichaje/historial?desde={hoy}&hasta={hoy}", headers=h).get_json()["data"]
    assert len([f for f in filas if f["tipo"] == "entrada"]) == 1


def test_fichar_sin_conexion_conserva_la_hora_de_la_pulsacion(cliente):
    h, _ = _arranque(cliente, "fichar-hora@ejemplo.com")
    pulsada = (datetime.now() - timedelta(hours=2)).replace(microsecond=0).isoformat()
    r = cliente.post("/api/v1/fichaje/marcar", json={"tipo": "entrada", "marca_tiempo": pulsada, "cliente_uuid": "22222222-2222-4222-8222-222222222222"}, headers=h)
    assert r.status_code == 200
    hoy = datetime.now().date().isoformat()
    filas = cliente.get(f"/api/v1/fichaje/historial?desde={hoy}&hasta={hoy}", headers=h).get_json()["data"]
    entradas = [f for f in filas if f["tipo"] == "entrada"]
    assert len(entradas) == 1 and entradas[0]["marca_tiempo"].startswith(pulsada[:16])           # la de la pulsación, no la de cuando llegó


def test_la_secuencia_se_valida_por_orden_de_llegada(cliente):
    h, _ = _arranque(cliente, "fichar-secuencia@ejemplo.com")
    assert cliente.post("/api/v1/fichaje/marcar", json={"tipo": "entrada", "cliente_uuid": "33333333-3333-4333-8333-333333333333"}, headers=h).status_code == 200
    mal = cliente.post("/api/v1/fichaje/marcar", json={"tipo": "entrada", "cliente_uuid": "44444444-4444-4444-8444-444444444444"}, headers=h)
    assert mal.status_code == 400 and "entrada" in mal.get_json()["error"]          # el rechazo que la cola enseña como «rechazado» sin bloquear los siguientes
    assert cliente.post("/api/v1/fichaje/marcar", json={"tipo": "salida", "cliente_uuid": "55555555-5555-4555-8555-555555555555"}, headers=h).status_code == 200


def test_nota_rapida_con_cliente_uuid_y_hora_de_creacion_no_se_duplica(cliente):
    h, _ = _arranque(cliente, "nota-uuid@ejemplo.com")
    cuerpo = {"texto": "Llamar al gestor", "creada_en": "2026-10-24T09:00:00", "cliente_uuid": "66666666-6666-4666-8666-666666666666"}
    a = cliente.post("/api/v1/notas", json=cuerpo, headers=h)
    b = cliente.post("/api/v1/notas", json=cuerpo, headers=h)
    assert a.status_code in (200, 201) and b.status_code in (200, 201)
    notas = [n for n in cliente.get("/api/v1/notas", headers=h).get_json()["data"] if n["texto"] == "Llamar al gestor"]
    assert len(notas) == 1 and notas[0]["creada_en"].startswith("2026-10-24T09:00")
