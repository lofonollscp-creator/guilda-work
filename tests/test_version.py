"""AA12: versión que corre y aviso de código commiteado sin desplegar."""
from datetime import datetime, timedelta

from app import salud, version

AHORA = datetime(2026, 11, 15, 12, 0)
COMMIT = {"hash": "abc1234", "asunto": "Arregla algo", "fecha": AHORA - timedelta(hours=2)}


def test_commit_anterior_al_arranque_no_esta_pendiente():
    v = version.estado(AHORA, AHORA - timedelta(hours=1), COMMIT)
    assert v["pendiente"] is False and v["hash"] == "abc1234" and v["corriendo_desde_s"] == 3600


def test_commit_posterior_al_arranque_esta_pendiente():
    assert version.estado(AHORA, AHORA - timedelta(hours=5), COMMIT)["pendiente"] is True
    assert version.estado(AHORA, COMMIT["fecha"] - timedelta(seconds=30), COMMIT)["pendiente"] is False        # menos de un minuto de margen


def test_sin_git_no_hay_estado(monkeypatch):
    monkeypatch.setattr(version, "ultimo_commit", lambda: None)
    assert version.estado() is None and salud._estado_version(AHORA)["estado"] == salud.GRIS


def test_el_panel_salud(monkeypatch):
    monkeypatch.setattr(version, "ultimo_commit", lambda: COMMIT)
    monkeypatch.setattr(version, "ARRANCADO", AHORA - timedelta(hours=1))
    r = salud._estado_version(AHORA)
    assert r["estado"] == salud.VERDE and "abc1234" in r["detalle"]
    monkeypatch.setattr(version, "ARRANCADO", AHORA - timedelta(hours=5))
    r = salud._estado_version(AHORA)
    assert r["estado"] == salud.AMBAR and "sin desplegar" in r["detalle"]


def test_el_ultimo_commit_real_se_lee_del_repositorio():
    c = version.ultimo_commit()
    assert c is None or (len(c["hash"]) >= 7 and isinstance(c["fecha"], datetime))
