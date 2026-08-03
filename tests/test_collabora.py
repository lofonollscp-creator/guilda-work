"""Tests del bootstrap de Collabora Online (app/collabora.py) — se mockea
subprocess.run, sin un Nextcloud/Collabora de verdad.

El diseño en sí (Collabora como motor de render sin estado, aislamiento
100% heredado de Nextcloud, sin aprovisionamiento por tenant; el bootstrap
de richdocuments es CLI-only vía `docker exec`, sin equivalente HTTP) se
verificó en vivo durante el desarrollo, de punta a punta contra un
Nextcloud y un Collabora reales — ver el docstring del propio módulo.
Aquí solo se comprueba que app/collabora.py ORQUESTA los comandos `occ`
correctos."""
import subprocess

import pytest

from app import collabora as c


def _mock_occ_ok(monkeypatch):
    llamadas = []

    def fake_run(cmd, **kwargs):
        llamadas.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(c.subprocess, "run", fake_run)
    return llamadas


def test_bootstrap_richdocuments_ejecuta_los_tres_comandos_occ_en_orden(monkeypatch):
    monkeypatch.setattr(c, "NEXTCLOUD_CONTENEDOR", "guilda-work-nextcloud")
    monkeypatch.setattr(c, "COLLABORA_WOPI_URL", "http://collabora:9980")
    llamadas = _mock_occ_ok(monkeypatch)

    c.bootstrap_richdocuments()

    assert len(llamadas) == 3
    assert llamadas[0] == ["docker", "exec", "-u", "www-data", "guilda-work-nextcloud", "php", "occ", "app:install", "richdocuments"]
    assert llamadas[1] == [
        "docker", "exec", "-u", "www-data", "guilda-work-nextcloud", "php", "occ",
        "config:app:set", "richdocuments", "wopi_url", "--value", "http://collabora:9980",
    ]
    assert llamadas[2] == ["docker", "exec", "-u", "www-data", "guilda-work-nextcloud", "php", "occ", "richdocuments:activate-config"]


def test_bootstrap_richdocuments_usa_el_contenedor_configurado(monkeypatch):
    monkeypatch.setattr(c, "NEXTCLOUD_CONTENEDOR", "otro-contenedor-nextcloud")
    llamadas = _mock_occ_ok(monkeypatch)

    c.bootstrap_richdocuments()

    assert all("otro-contenedor-nextcloud" in cmd for cmd in llamadas)


def test_bootstrap_richdocuments_falla_si_app_install_falla(monkeypatch):
    def fake_run(cmd, **kwargs):
        if "app:install" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="no se pudo instalar")
        raise AssertionError("no debería llegar a los siguientes comandos si el primero falla")

    monkeypatch.setattr(c.subprocess, "run", fake_run)
    with pytest.raises(c.ErrorCollabora, match="no se pudo instalar"):
        c.bootstrap_richdocuments()


def test_bootstrap_richdocuments_falla_si_activate_config_falla(monkeypatch):
    def fake_run(cmd, **kwargs):
        if "richdocuments:activate-config" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="WOPI server no detectado", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(c.subprocess, "run", fake_run)
    with pytest.raises(c.ErrorCollabora, match="WOPI server no detectado"):
        c.bootstrap_richdocuments()
