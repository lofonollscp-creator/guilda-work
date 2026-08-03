"""Tests del cliente de ntfy (app/ntfy.py) — se mockean
ntfy._peticion/_conceder_acceso/subprocess.run, sin un ntfy de verdad.

El diseño en sí (usuario+ACL de topic nativos de ntfy; alta de usuario y
generación de token por API HTTP normal; concesión de ACL únicamente por
`docker exec` porque `ntfy access` es un comando de solo-servidor sin
equivalente HTTP, confirmado en su propia ayuda; aislamiento real
verificado en vivo con un token ajeno recibiendo 403 al publicar en un
topic que no es el suyo) se verificó en vivo contra un contenedor real
durante el desarrollo — ver el docstring del propio módulo. Aquí solo se
comprueba que app/ntfy.py ORQUESTA las llamadas correctas."""
import subprocess

import pytest

from app import ntfy as n


def _mock_admin_ok(monkeypatch):
    monkeypatch.setattr(n, "NTFY_ADMIN_USER", "admin")
    monkeypatch.setattr(n, "NTFY_ADMIN_PASSWORD", "secreto")


def _mock_subprocess_ok(monkeypatch):
    resultado = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    monkeypatch.setattr(n.subprocess, "run", lambda *a, **k: resultado)


# --- aprovisionar_tenant ----------------------------------------------------

def test_aprovisionar_tenant_sin_credenciales_lanza_error(monkeypatch):
    monkeypatch.setattr(n, "NTFY_ADMIN_USER", None)
    monkeypatch.setattr(n, "NTFY_ADMIN_PASSWORD", None)
    with pytest.raises(n.ErrorNtfy):
        n.aprovisionar_tenant(7, "Lueira")


def test_aprovisionar_tenant_completo_ok(monkeypatch):
    _mock_admin_ok(monkeypatch)
    _mock_subprocess_ok(monkeypatch)
    llamadas = []

    def fake_peticion(endpoint, *, usuario, contrasena, metodo="GET", cuerpo=None):
        llamadas.append((endpoint, usuario, metodo, cuerpo))
        if endpoint == "/v1/users":
            assert usuario == "admin" and contrasena == "secreto"
            assert cuerpo["username"] == "tenant_7"
            return {"success": True}
        if endpoint == "/v1/account/token":
            assert usuario == "tenant_7"
            return {"token": "tk_real123"}
        raise AssertionError(f"endpoint inesperado: {endpoint}")

    monkeypatch.setattr(n, "_peticion", fake_peticion)
    resultado = n.aprovisionar_tenant(7, "Cliente Alfa")

    assert resultado == {"topic": "guilda-cliente-alfa-7", "token": "tk_real123"}
    endpoints = [c[0] for c in llamadas]
    assert endpoints == ["/v1/users", "/v1/account/token"]


def test_aprovisionar_tenant_llama_a_conceder_acceso_con_el_topic_correcto(monkeypatch):
    _mock_admin_ok(monkeypatch)
    capturado = {}

    def fake_conceder(usuario, topic):
        capturado["args"] = (usuario, topic)

    def fake_peticion(endpoint, *, usuario, contrasena, metodo="GET", cuerpo=None):
        if endpoint == "/v1/users":
            return {"success": True}
        return {"token": "tk_x"}

    monkeypatch.setattr(n, "_peticion", fake_peticion)
    monkeypatch.setattr(n, "_conceder_acceso", fake_conceder)
    resultado = n.aprovisionar_tenant(3, "Beta")

    assert capturado["args"] == ("tenant_3", resultado["topic"])


def test_aprovisionar_tenant_usuario_ya_existente_da_error_claro(monkeypatch):
    _mock_admin_ok(monkeypatch)

    def fake_peticion(endpoint, *, usuario, contrasena, metodo="GET", cuerpo=None):
        raise n.ErrorNtfy("ntfy ha rechazado la petición a /v1/users (HTTP 409): conflict: user already exists")

    monkeypatch.setattr(n, "_peticion", fake_peticion)
    with pytest.raises(n.ErrorNtfy, match="ya existe"):
        n.aprovisionar_tenant(9, "Gamma")


def test_conceder_acceso_falla_lanza_error_legible(monkeypatch):
    resultado = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
    monkeypatch.setattr(n.subprocess, "run", lambda *a, **k: resultado)
    with pytest.raises(n.ErrorNtfy, match="boom"):
        n._conceder_acceso("tenant_1", "guilda-alfa-1")


# --- desaprovisionar_tenant --------------------------------------------------

def test_desaprovisionar_tenant_ejecuta_user_del(monkeypatch):
    capturado = {}

    def fake_run(cmd, **kwargs):
        capturado["cmd"] = cmd
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(n.subprocess, "run", fake_run)
    n.desaprovisionar_tenant(5)
    assert capturado["cmd"][-3:] == ["user", "del", "tenant_5"]


def test_desaprovisionar_tenant_falla_lanza_error(monkeypatch):
    _mock_subprocess_fail = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="no existe")
    monkeypatch.setattr(n.subprocess, "run", lambda *a, **k: _mock_subprocess_fail)
    with pytest.raises(n.ErrorNtfy, match="no existe"):
        n.desaprovisionar_tenant(5)


# --- enviar ------------------------------------------------------------------

class _RespuestaFalsa:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_enviar_construye_la_peticion_correcta(monkeypatch):
    capturado = {}

    def fake_urlopen(req, timeout=None):
        capturado["url"] = req.full_url
        capturado["headers"] = dict(req.headers)
        capturado["data"] = req.data
        return _RespuestaFalsa()

    monkeypatch.setattr(n.urllib.request, "urlopen", fake_urlopen)
    n.enviar("guilda-alfa-1", "tk_real", "Aviso", "Ha pasado algo", prioridad="high", click_url="https://x")

    assert capturado["url"] == f"{n.NTFY_URL}/guilda-alfa-1"
    assert capturado["headers"]["Authorization"] == "Bearer tk_real"
    assert capturado["headers"]["Title"] == "Aviso"
    assert capturado["headers"]["Priority"] == "high"
    assert capturado["headers"]["Click"] == "https://x"
    assert capturado["data"] == b"Ha pasado algo"


def test_enviar_error_http_lanza_errorntfy(monkeypatch):
    import urllib.error

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 403, "forbidden", {}, None)

    monkeypatch.setattr(n.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(n.ErrorNtfy):
        n.enviar("guilda-otro-2", "tk_ajeno", "Aviso", "Mensaje")
