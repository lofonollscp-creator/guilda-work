"""Avisos a la dirección del despacho cuando pasa del 80 % o del 100 % de un tope de su plan (M4)."""
from datetime import datetime

import pytest

from app import db
from backoffice import cuotas
from tests.test_almacen_objetos import _despacho as _despacho_base
from tests.test_backoffice_app import bo, entrar, post  # noqa: F401 -- fixture

AHORA = datetime(2026, 11, 15, 12, 0)


def _despacho(nombre):
    t, u, c = _despacho_base(nombre)
    db.asignar_supervisor_tenant(u, True)          # la dirección es quien recibe el aviso
    return t, u, c


def _ia(t, usadas, limite=100):
    conn = db.get_connection()
    conn.execute("DELETE FROM ia_consumo WHERE tenant_id = ? AND mes = ?", (t, "2026-11"))
    conn.execute("INSERT INTO ia_consumo (tenant_id, mes, usadas) VALUES (?, ?, ?)", (t, "2026-11", usadas))
    conn.execute("UPDATE tenants SET ia_limite_mensual = ? WHERE id = ?", (limite, t))
    conn.commit()
    conn.close()


@pytest.fixture
def mandados():
    return []


@pytest.fixture
def enviar(mandados):
    return lambda destino, despacho, metricas, url, tenant_id=None: mandados.append((destino, despacho, [(m["metrica"], m["nivel"]) for m in metricas], tenant_id))


def test_apagado_por_defecto(bo, monkeypatch, enviar, mandados):
    monkeypatch.delenv("GUILDA_AVISOS_CUOTA", raising=False)
    t, u, c = _despacho("Cuota apagada")
    _ia(t, 85)
    assert cuotas.avisar_despachos(AHORA, enviar=enviar) == 0 and mandados == []


def test_avisa_una_vez_al_mes_por_limite_y_nivel(bo, monkeypatch, enviar, mandados):
    monkeypatch.setenv("GUILDA_AVISOS_CUOTA", "1")
    t, u, c = _despacho("Cuota ia")
    _ia(t, 85)
    n = cuotas.avisar_despachos(AHORA, enviar=enviar)
    assert n >= 1 and any(m[1] == "Cuota ia" and m[2] == [("ia", "aviso")] for m in mandados)
    antes = len(mandados)
    assert cuotas.avisar_despachos(AHORA, enviar=enviar) == 0 and len(mandados) == antes          # ya avisado este mes
    _ia(t, 100)                                                                                    # pasa al 100 %: se avisa otra vez
    cuotas.avisar_despachos(AHORA, enviar=enviar)
    assert any(m[1] == "Cuota ia" and m[2] == [("ia", "excedido")] for m in mandados)
    assert len(mandados) > antes

def test_sin_topes_o_por_debajo_del_80_no_se_avisa(bo, monkeypatch, enviar, mandados):
    monkeypatch.setenv("GUILDA_AVISOS_CUOTA", "1")
    t, u, c = _despacho("Cuota holgada")
    _ia(t, 50)
    cuotas.avisar_despachos(AHORA, enviar=enviar)
    assert not any(m[1] == "Cuota holgada" for m in mandados)


def test_un_destino_que_falla_no_frena_el_resto(bo, monkeypatch):
    monkeypatch.setenv("GUILDA_AVISOS_CUOTA", "1")
    t, u, c = _despacho("Cuota fallo")
    _ia(t, 90)
    llamadas = []

    def roto(destino, despacho, metricas, url, tenant_id=None):
        llamadas.append(destino)
        raise RuntimeError("smtp")
    cuotas.avisar_despachos(AHORA, enviar=roto)                 # no lanza
    assert llamadas


def test_el_boton_avisa_aunque_la_funcion_este_apagada(bo, monkeypatch):
    monkeypatch.delenv("GUILDA_AVISOS_CUOTA", raising=False)
    enviados = []
    monkeypatch.setattr("app.notificaciones_email.enviar_aviso_cuota", lambda *a, **k: enviados.append(a))
    t, u, c = _despacho("Cuota boton")
    _ia(t, 90)
    entrar(bo)
    r = post(bo, f"/tenants/{t}/cuotas/avisar")
    assert r.status_code == 302
    assert enviados and enviados[0][1] == "Cuota boton" and enviados[0][2][0]["metrica"] == "ia"


def test_el_correo_se_construye_en_los_tres_idiomas():
    from app import notificaciones_email as ne
    capturado = {}
    import unittest.mock as m
    with m.patch.object(ne, "_enviar", lambda d, a, plano, html: capturado.update(plano=plano, asunto=a)):
        ne.enviar_aviso_cuota("a@b.c", "Despacho X", [{"metrica": "ia", "usado": 90, "limite": 100, "pct": 90, "nivel": "aviso"}], "https://x")
    assert "90 de 100" in capturado["plano"] and "Despacho X" in capturado["plano"]
