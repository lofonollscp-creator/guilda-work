"""Tests del cliente/aprovisionador de FacturaScripts (app/facturascripts.py)
— se mockean subprocess.run (docker cp/exec/run/psql) y urllib (espera de
arranque + verificación final + API), sin Docker ni FacturaScripts de
verdad.

El flujo de instalación real (`_instalar`) se verificó en vivo contra un
contenedor de verdad durante el desarrollo — ver el docstring del propio
módulo para el porqué de escribir config.php/.htaccess directamente en
vez de usar la ruta HTTP documentada del instalador (rota en la versión
publicada actual). Aquí solo se comprueba que app/facturascripts.py
ORQUESTA los comandos correctos, no que FacturaScripts en sí funcione."""
import types

import pytest

from app import facturascripts as fs


class _RespuestaFalsa:
    def __init__(self, texto: str = "", status: int = 200):
        self._texto = texto
        self.status = status

    def read(self):
        return self._texto.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _resultado_proceso_ok(stdout: str = ""):
    return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def _mock_subprocess_e_instalacion_ok(monkeypatch):
    """Mockea subprocess.run para que toda la secuencia de
    aprovisionamiento (psql/docker run/docker cp/docker exec) tenga
    éxito, y devuelve la lista de comandos capturados."""
    llamadas = []

    def fake_run(cmd, **kwargs):
        llamadas.append(cmd)
        if cmd[:2] == ["docker", "exec"] and "php" in cmd:
            return _resultado_proceso_ok(stdout="DEPLOY_OK")
        return _resultado_proceso_ok()

    monkeypatch.setattr(fs.subprocess, "run", fake_run)
    monkeypatch.setattr(fs.urllib.request, "urlopen", lambda *a, **k: _RespuestaFalsa(""))
    # tempfile real (el contenido en sí no importa, es un archivo local)
    return llamadas


# --- Aprovisionamiento --------------------------------------------------------

def test_aprovisionar_tenant_sin_password_postgres_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(fs, "FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD", None)
    with pytest.raises(fs.ErrorFacturaScripts):
        fs.aprovisionar_tenant(1, "Lueira")


def test_aprovisionar_tenant_completo_ok(monkeypatch):
    monkeypatch.setattr(fs, "FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD", "clave-admin")
    llamadas = _mock_subprocess_e_instalacion_ok(monkeypatch)

    resultado = fs.aprovisionar_tenant(7, "Lueira")

    assert resultado["url"] == "http://127.0.0.1:8107/"
    assert resultado["admin_user"] == "admin"
    assert resultado["admin_pass"]  # generada, no vacía

    # 3 psql (CREATE ROLE, CREATE DATABASE, REVOKE CONNECT) + docker run +
    # docker cp (config.php) + docker exec (htaccess/carpetas) + docker
    # exec (Plugins::deploy)
    psql = [c for c in llamadas if "psql" in c]
    assert len(psql) == 3
    assert any(c[:2] == ["docker", "run"] for c in llamadas)
    assert any(c[:2] == ["docker", "cp"] for c in llamadas)
    assert any(c[:2] == ["docker", "exec"] and "php" in c for c in llamadas)


def test_aprovisionar_tenant_psql_falla_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(fs, "FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD", "clave-admin")
    monkeypatch.setattr(
        fs.subprocess, "run",
        lambda cmd, **k: types.SimpleNamespace(returncode=1, stdout="", stderr="rol ya existe"),
    )
    with pytest.raises(fs.ErrorFacturaScripts):
        fs.aprovisionar_tenant(1, "Lueira")


def test_aprovisionar_tenant_plugins_deploy_falla_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(fs, "FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD", "clave-admin")

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["docker", "exec"] and "php" in cmd:
            return types.SimpleNamespace(returncode=1, stdout="", stderr="Fatal error")
        return _resultado_proceso_ok()

    monkeypatch.setattr(fs.subprocess, "run", fake_run)
    monkeypatch.setattr(fs.urllib.request, "urlopen", lambda *a, **k: _RespuestaFalsa(""))
    with pytest.raises(fs.ErrorFacturaScripts):
        fs.aprovisionar_tenant(1, "Lueira")


def test_aprovisionar_tenant_error_de_servidor_tras_instalar_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(fs, "FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD", "clave-admin")
    _mock_subprocess_e_instalacion_ok(monkeypatch)

    import urllib.error

    llamadas_urlopen = {"n": 0}

    def fake_urlopen(*a, **k):
        llamadas_urlopen["n"] += 1
        if llamadas_urlopen["n"] == 1:
            return _RespuestaFalsa("")  # _esperar_arranque: ok
        raise urllib.error.HTTPError("http://x", 500, "Internal Server Error", {}, None)

    monkeypatch.setattr(fs.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(fs.ErrorFacturaScripts):
        fs.aprovisionar_tenant(1, "Lueira")


def test_generar_config_php_escapa_comillas_y_barras(monkeypatch):
    contenido = fs._generar_config_php("host", "user", "pa'ss\\word", "db", "admin", "pass")
    assert "pa\\'ss\\\\word" in contenido
    assert "define('FS_DEBUG', false);" in contenido


def test_desaprovisionar_tenant_llama_a_docker_y_psql(monkeypatch):
    monkeypatch.setattr(fs, "FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD", "clave-admin")
    llamadas = []

    def fake_run(cmd, **kwargs):
        llamadas.append(cmd)
        return _resultado_proceso_ok()

    monkeypatch.setattr(fs.subprocess, "run", fake_run)
    fs.desaprovisionar_tenant(3)

    assert any(c[:2] == ["docker", "stop"] for c in llamadas)
    assert any(c[:2] == ["docker", "rm"] for c in llamadas)
    assert any("DROP DATABASE" in " ".join(c) for c in llamadas)
    assert any("DROP ROLE" in " ".join(c) for c in llamadas)


def test_desaprovisionar_tenant_sin_password_no_falla(monkeypatch):
    monkeypatch.setattr(fs, "FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD", None)
    monkeypatch.setattr(fs.subprocess, "run", lambda cmd, **k: _resultado_proceso_ok())
    fs.desaprovisionar_tenant(3)  # no debe lanzar nada


# --- API de negocio ------------------------------------------------------------

def test_listar_clientes_sin_url_o_api_key_devuelve_vacio():
    assert fs.listar_clientes("", "clave") == []
    assert fs.listar_clientes("http://127.0.0.1:8107/", "") == []


def test_listar_clientes_ok(monkeypatch):
    monkeypatch.setattr(fs, "_peticion", lambda url, key, ep, **k: (200, [{"codcliente": "1", "nombre": "Ana"}]))
    resultado = fs.listar_clientes("http://127.0.0.1:8107/", "clave")
    assert resultado == [{"codcliente": "1", "nombre": "Ana"}]


def test_crear_cliente_sin_configurar_lanza_excepcion():
    with pytest.raises(fs.ErrorFacturaScripts):
        fs.crear_cliente("", "", "Ana")


def test_crear_cliente_ok(monkeypatch):
    def fake_peticion(url, key, ep, *, metodo="GET", cuerpo=None):
        assert metodo == "POST"
        assert cuerpo["nombre"] == "Ana"
        return 200, {"codcliente": "5"}

    monkeypatch.setattr(fs, "_peticion", fake_peticion)
    assert fs.crear_cliente("http://127.0.0.1:8107/", "clave", "Ana")["codcliente"] == "5"


def test_crear_factura_ok(monkeypatch):
    def fake_peticion(url, key, ep, *, metodo="GET", cuerpo=None):
        assert ep == "crearFacturaCliente"
        assert cuerpo["codcliente"] == "5"
        return 200, {"idfactura": "99"}

    monkeypatch.setattr(fs, "_peticion", fake_peticion)
    lineas = [{"descripcion": "Servicio", "cantidad": 1, "precio": 100}]
    assert fs.crear_factura("http://127.0.0.1:8107/", "clave", "5", lineas)["idfactura"] == "99"


def test_crear_factura_error_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(fs, "_peticion", lambda *a, **k: (500, {"message": "fallo"}))
    with pytest.raises(fs.ErrorFacturaScripts):
        fs.crear_factura("http://127.0.0.1:8107/", "clave", "5", [])
