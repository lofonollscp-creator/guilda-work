"""Tope mensual de IA por despacho (con opción ilimitada) y su gestión desde el backoffice."""
from datetime import datetime

import pytest

from app import db, ia_asistente, ia_consumo
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_backoffice_app import bo, entrar, post  # noqa: F401 -- fixture


def _usuario(email, tenant=None):
    uid = db.crear_usuario_vinculado_a_kratos(email, "k-" + email)
    if tenant:
        db.asignar_tenant(uid, tenant)
    return uid


def test_ilimitado_cuenta_pero_no_bloquea():
    t = db.crear_tenant("Libre")
    u = _usuario("l@x.com", t)
    for _ in range(5):
        ia_consumo.reservar(u)
    e = ia_consumo.estado(t)
    assert (e["usadas"], e["ilimitado"], e["limite"], e["pct"], e["agotado"]) == (5, True, None, None, False)


def test_tope_se_respeta_y_es_por_despacho():
    a, b = db.crear_tenant("A"), db.crear_tenant("B")
    ua, ub = _usuario("a@x.com", a), _usuario("a2@x.com", a)
    u_b = _usuario("b@x.com", b)
    ia_consumo.fijar_limite(a, 3)
    ia_consumo.reservar(ua); ia_consumo.reservar(ub); ia_consumo.reservar(ua)      # el tope es del despacho, no del usuario
    with pytest.raises(ia_consumo.LimiteIA) as e:
        ia_consumo.reservar(ub)
    assert "3 consultas" in str(e.value)
    assert ia_consumo.estado(a)["usadas"] == 3 and ia_consumo.estado(a)["agotado"]   # el rechazo no cuenta
    ia_consumo.reservar(u_b)                                                          # B no se ve afectado


def test_cero_desactiva_y_subir_el_tope_reabre():
    t = db.crear_tenant("Cero")
    u = _usuario("c@x.com", t)
    ia_consumo.fijar_limite(t, 0)
    with pytest.raises(ia_consumo.LimiteIA) as e:
        ia_consumo.reservar(u)
    assert "no está activado" in str(e.value)
    ia_consumo.fijar_limite(t, 10)
    ia_consumo.reservar(u)
    ia_consumo.fijar_limite(t, None)
    assert ia_consumo.estado(t)["ilimitado"]


def test_se_renueva_cada_mes_y_el_historial_lo_recuerda():
    t = db.crear_tenant("Meses")
    u = _usuario("m@x.com", t)
    ia_consumo.fijar_limite(t, 1)
    ia_consumo.reservar(u, datetime(2026, 9, 30))
    with pytest.raises(ia_consumo.LimiteIA):
        ia_consumo.reservar(u, datetime(2026, 9, 30))
    ia_consumo.reservar(u, datetime(2026, 10, 1))                                     # mes nuevo: contador a cero
    assert [(h["mes"], h["usadas"]) for h in ia_consumo.historial(t)] == [("2026-10", 1), ("2026-09", 1)]


def test_usuario_sin_despacho_no_tiene_tope():
    u = _usuario("solo@x.com")
    ia_consumo.reservar(u)                                                            # no lanza ni escribe


def test_validacion_del_tope():
    t = db.crear_tenant("Valida")
    for malo in (-1, 2_000_000, "5"):
        with pytest.raises(ValueError):
            ia_consumo.fijar_limite(t, malo)
    with pytest.raises(ValueError):
        ia_consumo.fijar_limite(9999, 5)


def test_el_asistente_y_las_acciones_de_correo_respetan_el_tope(monkeypatch):
    t = db.crear_tenant("Asistente")
    u = _usuario("ia@x.com", t)
    ia_consumo.fijar_limite(t, 1)
    monkeypatch.setattr(ia_asistente, "obtener_api_keys", lambda uid: ["clave"])
    monkeypatch.setattr(db, "obtener_preferencias_ia", lambda uid: {"modelo": "modelo/x", "modo_autonomo": 0, "solo_lectura": 0})
    llamadas = []
    monkeypatch.setattr(ia_asistente, "_post_json_con_fallback", lambda *a, **k: llamadas.append(1) or {"choices": [{"message": {"content": " hola "}}]})
    assert ia_asistente.completar_texto(u, "s", "c") == "hola"
    with pytest.raises(ia_asistente.ErrorIA) as e:
        ia_asistente.completar_texto(u, "s", "c")
    assert "límite mensual" in str(e.value) and len(llamadas) == 1                      # ni se llamó al modelo
    with pytest.raises(ia_asistente.ErrorIA):
        ia_asistente.procesar_turno(u, "hola")
    assert [x for x in ia_asistente.procesar_turno_stream(u, "hola")][0]["tipo"] == "error"
    assert db.listar_mensajes_ia(u) == []                                              # tampoco se guardó el mensaje


def test_ajustes_de_ia_muestran_el_uso(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "uso@ejemplo.com", "una-clave-larga-1234")
    t = db.crear_tenant("Despacho uso")
    db.asignar_tenant(uid, t)
    assert "sin límite" in cliente.get("/ia/ajustes").get_data(as_text=True)
    ia_consumo.fijar_limite(t, 10)
    for _ in range(9):
        ia_consumo.reservar(uid)
    html = cliente.get("/ia/ajustes").get_data(as_text=True)
    assert "9 de 10 consultas usadas" in html and "pocas consultas" in html


def test_backoffice_fija_el_tope_y_lista_el_consumo(bo):
    entrar(bo)
    t = db.crear_tenant("Gastón")
    u = _usuario("g@x.com", t)
    ia_consumo.reservar(u)
    html = bo.get(f"/tenants/{t}").get_data(as_text=True)
    assert "Consumo de IA" in html and "ilimitado" in html
    post(bo, f"/tenants/{t}/ia-limite", limite="200")
    assert ia_consumo.estado(t)["limite"] == 200
    post(bo, f"/tenants/{t}/ia-limite", limite="abc")                                   # inválido: no cambia
    assert ia_consumo.estado(t)["limite"] == 200
    post(bo, f"/tenants/{t}/ia-limite", limite="0")
    assert ia_consumo.estado(t)["limite"] == 0
    post(bo, f"/tenants/{t}/ia-limite", ilimitado="1", limite="5")
    assert ia_consumo.estado(t)["ilimitado"]
    assert post(bo, "/tenants/9999/ia-limite", limite="5").status_code == 404
    pagina = bo.get("/consumo-ia").get_data(as_text=True)
    assert "Gastón" in pagina and "Ilimitado" in pagina
    assert "ia.limite" in bo.get("/actividad").get_data(as_text=True)
