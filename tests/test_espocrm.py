"""Tests del cliente de EspoCRM (app/espocrm.py) — mismo criterio que el
resto de integraciones sin SSO (openproject.py/metabase.py): se mockea
espocrm._peticion, sin un EspoCRM de verdad."""
from app import espocrm


def test_crear_equipo_sin_api_key_no_hace_nada(monkeypatch):
    monkeypatch.setattr(espocrm, "ESPOCRM_API_KEY", None)
    assert espocrm.crear_equipo("Lueira") is None


def test_crear_equipo_devuelve_id_si_se_crea(monkeypatch):
    monkeypatch.setattr(espocrm, "ESPOCRM_API_KEY", "clave-de-prueba")

    def fake_peticion(url, *, metodo="GET", cuerpo=None):
        assert metodo == "POST"
        assert cuerpo == {"name": "Lueira"}
        return 201, {"id": "equipo-abc"}

    monkeypatch.setattr(espocrm, "_peticion", fake_peticion)

    assert espocrm.crear_equipo("Lueira") == "equipo-abc"


def test_crear_equipo_ya_existente_es_idempotente(monkeypatch):
    """Si POST falla (nombre duplicado), se busca por nombre y se
    devuelve el id existente en vez de fallar — mismo patrón que
    openproject._buscar_por_email."""
    monkeypatch.setattr(espocrm, "ESPOCRM_API_KEY", "clave-de-prueba")

    llamadas = []

    def fake_peticion(url, *, metodo="GET", cuerpo=None):
        llamadas.append((metodo, url))
        if metodo == "POST":
            return 400, {"message": "ya existe"}
        return 200, {"list": [{"id": "equipo-existente"}]}

    monkeypatch.setattr(espocrm, "_peticion", fake_peticion)

    assert espocrm.crear_equipo("Lueira") == "equipo-existente"
    assert llamadas[0][0] == "POST"
    assert llamadas[1][0] == "GET"


def test_crear_equipo_error_real_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(espocrm, "ESPOCRM_API_KEY", "clave-de-prueba")

    def fake_peticion(url, *, metodo="GET", cuerpo=None):
        if metodo == "POST":
            return 500, {"message": "error interno"}
        return 200, {"list": []}

    monkeypatch.setattr(espocrm, "_peticion", fake_peticion)

    try:
        espocrm.crear_equipo("Lueira")
        assert False, "debería haber lanzado ErrorEspoCRM"
    except espocrm.ErrorEspoCRM as e:
        assert "error interno" in str(e)
