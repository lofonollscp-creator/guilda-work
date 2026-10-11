"""Estado del servicio para monitores (`GET /api/v1/health`) y alerta por ráfaga de errores 5xx."""
from datetime import datetime, timedelta

import pytest

from app import db, notificaciones_email, salud

AHORA = datetime(2026, 10, 11, 12, 0)


# --- /api/v1/health --------------------------------------------------------------------------------------------------------

def test_health_es_publico_y_no_cuenta_nada_de_nadie(cliente):
    r = cliente.get("/api/v1/health")
    assert r.status_code == 200 and r.headers["X-API-Version"]
    datos = r.get_json()
    assert datos["ok"] is True and datos["data"] == {"estado": "ok", "version_api": r.headers["X-API-Version"], "base_de_datos": "ok"}


def test_health_da_503_si_la_base_de_datos_no_responde(cliente, monkeypatch):
    def _roto():
        raise RuntimeError("disco lleno")
    monkeypatch.setattr(db, "get_connection", _roto)
    r = cliente.get("/api/v1/health")
    assert r.status_code == 503 and r.get_json()["codigo"] == "servicio_no_disponible"


def test_health_figura_en_el_openapi_como_publico(cliente):
    op = cliente.get("/api/v1/openapi.json").get_json()["paths"]["/api/v1/health"]["get"]
    assert op["security"] == [] and op["x-area"] and "monitor" in op["description"].lower()


def test_health_no_exige_area_a_un_token_limitado(cliente):
    u = db.crear_usuario_vinculado_a_kratos("h@x.com", "k-h")
    tok = db.crear_token_api(u, "solo notas", "solo_lectura", areas=["notas"])
    assert cliente.get("/api/v1/health", headers={"Authorization": f"Bearer {tok}"}).status_code == 200


# --- errores 5xx ------------------------------------------------------------------------------------------------------------

def test_una_respuesta_500_se_anota_con_la_plantilla_de_la_ruta(cliente, monkeypatch):
    u = db.crear_usuario_vinculado_a_kratos("e@x.com", "k-e")
    tok = db.crear_token_api(u, "t", "completo")

    def _falla(*a, **k):
        raise RuntimeError("fallo inesperado")
    monkeypatch.setattr(db, "obtener_usuario", _falla)
    r = cliente.get("/api/v1/auth/me?secreto=1", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 500
    resumen = db.resumen_errores_servidor("2000-01-01T00:00:00")
    assert resumen["total"] == 1 and resumen["ruta"] == "GET /api/v1/auth/me" and "secreto" not in resumen["ruta"]


def test_los_errores_antiguos_se_purgan():
    conn = db.get_connection()
    conn.execute("INSERT INTO errores_servidor (creado_en, metodo, ruta, estado) VALUES (?, 'GET', '/viejo', 500)",
                 ((datetime.now() - timedelta(days=db.ERRORES_SERVIDOR_RETENCION_DIAS + 1)).isoformat(timespec="seconds"),))
    conn.commit(); conn.close()
    db.registrar_error_servidor("GET", "/nuevo", 502)
    assert db.resumen_errores_servidor("2000-01-01T00:00:00")["total"] == 1


# --- panel de salud y vigilante ----------------------------------------------------------------------------------------------

def _anotar(n, minutos_atras=1):
    conn = db.get_connection()
    for i in range(n):
        conn.execute("INSERT INTO errores_servidor (creado_en, metodo, ruta, estado) VALUES (?, 'POST', '/api/v1/correo/enviar', 500)",
                     ((AHORA - timedelta(minutes=minutos_atras)).isoformat(timespec="seconds"),))
    conn.commit(); conn.close()


def _estado():
    return {i["clave"]: i for i in salud.panel(AHORA)}["errores_servidor"]


def test_el_panel_pasa_de_verde_a_ambar_y_a_rojo_segun_la_rafaga():
    assert _estado()["estado"] == salud.VERDE
    _anotar(salud.ERRORES_AMBAR)
    assert _estado()["estado"] == salud.AMBAR and "POST /api/v1/correo/enviar" in _estado()["detalle"]
    _anotar(salud.ERRORES_ROJO)
    assert _estado()["estado"] == salud.ROJO


def test_los_errores_fuera_de_la_ventana_no_cuentan():
    _anotar(50, minutos_atras=salud.ERRORES_VENTANA_MIN + 5)
    assert _estado()["estado"] == salud.VERDE


def test_el_vigilante_avisa_una_sola_vez_al_dia_de_una_rafaga(monkeypatch):
    enviados = []
    monkeypatch.setattr(notificaciones_email, "enviar_alerta_interna", lambda asunto, cuerpo: enviados.append((asunto, cuerpo)))
    _anotar(salud.ERRORES_ROJO)
    assert "errores_servidor" in salud.vigilar(AHORA)
    assert salud.vigilar(AHORA) == []
    assert len(enviados) == 1 and "Errores del servidor" in enviados[0][1]


# --- copia externa (Restic) ---------------------------------------------------------------------------------------------------

def _estado_restic(tmp_path, monkeypatch, contenido=None):
    import json
    monkeypatch.setattr(db, "BACKUPS_DIR", tmp_path)
    if contenido is not None:
        (tmp_path / "restic_estado.json").write_text(json.dumps(contenido), encoding="utf-8")
    return {i["clave"]: i for i in salud.panel(AHORA)}["restic"]


def test_sin_fichero_de_estado_la_copia_externa_sale_gris(tmp_path, monkeypatch):
    assert _estado_restic(tmp_path, monkeypatch)["estado"] == salud.GRIS


def test_la_copia_externa_pasa_de_verde_a_ambar_y_rojo_con_la_edad(tmp_path, monkeypatch):
    def ok(horas, errores=()):
        return {"ultimo_ok": (AHORA - timedelta(hours=horas)).isoformat(), "objetivos": 26, "errores": list(errores)}
    assert _estado_restic(tmp_path, monkeypatch, ok(5))["estado"] == salud.VERDE
    assert _estado_restic(tmp_path, monkeypatch, ok(40))["estado"] == salud.AMBAR
    assert _estado_restic(tmp_path, monkeypatch, ok(24 * 4))["estado"] == salud.ROJO
    con_fallo = _estado_restic(tmp_path, monkeypatch, ok(5, ["postgres:kratos"]))
    assert con_fallo["estado"] == salud.AMBAR and "postgres:kratos" in con_fallo["detalle"]
    nunca = _estado_restic(tmp_path, monkeypatch, {"ultimo_ok": None, "errores": ["host"], "objetivos": 3})
    assert nunca["estado"] == salud.ROJO
