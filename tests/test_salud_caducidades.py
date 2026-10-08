"""Panel de salud: caducidad de certificados HTTPS y de lo que configure el administrador (secretos, dominios...)."""
from datetime import date, datetime, timedelta

import pytest

from app import salud

AHORA = datetime(2026, 10, 8, 12, 0)


@pytest.fixture(autouse=True)
def limpiar(monkeypatch):
    salud._CACHE_CERTIFICADOS.clear()
    monkeypatch.delenv("GUILDA_CERT_HOSTS", raising=False)
    monkeypatch.delenv("GUILDA_CADUCIDADES", raising=False)
    monkeypatch.delenv("GUILDA_URL_PUBLICA", raising=False)


def test_hosts_vigilados(monkeypatch):
    assert salud._hosts_certificados() == []
    monkeypatch.setenv("GUILDA_URL_PUBLICA", "https://app.ejemplo.com:8443/portal")
    assert salud._hosts_certificados() == ["app.ejemplo.com"]
    monkeypatch.setenv("GUILDA_CERT_HOSTS", " a.com, b.com ,,")
    assert salud._hosts_certificados() == ["a.com", "b.com"]


@pytest.mark.parametrize("dias,estado", [(60, salud.VERDE), (22, salud.VERDE), (21, salud.AMBAR), (8, salud.AMBAR), (7, salud.ROJO), (0, salud.ROJO), (-3, salud.ROJO)])
def test_estado_del_certificado_segun_los_dias(monkeypatch, dias, estado):
    monkeypatch.setenv("GUILDA_CERT_HOSTS", "app.ejemplo.com")
    monkeypatch.setattr(salud, "_caducidad_certificado", lambda host: AHORA + timedelta(days=dias, hours=1))
    [i] = salud._estado_certificados(AHORA)
    assert i["estado"] == estado and i["clave"] == "cert:app.ejemplo.com" and "app.ejemplo.com" in i["titulo"] and "Caduca el" in i["detalle"]


def test_un_certificado_que_no_verifica_es_rojo_y_se_cachea(monkeypatch):
    monkeypatch.setenv("GUILDA_CERT_HOSTS", "roto.ejemplo.com,otro.ejemplo.com")
    llamadas = []

    def falso(host):
        llamadas.append(host)
        if host == "roto.ejemplo.com":
            raise OSError("certificate verify failed: certificate has expired")
        return AHORA + timedelta(days=90)
    monkeypatch.setattr(salud, "_caducidad_certificado", falso)
    items = {i["clave"]: i for i in salud._estado_certificados(AHORA)}
    assert items["cert:roto.ejemplo.com"]["estado"] == salud.ROJO and "certificate has expired" in items["cert:roto.ejemplo.com"]["detalle"]
    assert items["cert:otro.ejemplo.com"]["estado"] == salud.VERDE
    salud._estado_certificados(AHORA)
    assert llamadas == ["roto.ejemplo.com", "otro.ejemplo.com"]                         # la segunda vez sale de la caché


def test_caducidades_configuradas(monkeypatch):
    monkeypatch.setenv("GUILDA_CADUCIDADES", "Secreto de Microsoft=2028-10-01; Dominio=2026-11-20 ;Roto=ayer;=2027-01-01;Pasado=2026-10-01;Cerca=2026-10-15")
    items = {i["titulo"]: i for i in salud._estado_caducidades(AHORA)}
    assert set(items) == {"Secreto de Microsoft", "Dominio", "Pasado", "Cerca"}
    assert items["Secreto de Microsoft"]["estado"] == salud.VERDE and items["Dominio"]["estado"] == salud.AMBAR
    assert items["Cerca"]["estado"] == salud.ROJO and "en 7 días" in items["Cerca"]["detalle"]
    assert items["Pasado"]["estado"] == salud.ROJO and "Caducó el 2026-10-01 (hace 7 días)" in items["Pasado"]["detalle"]


def test_el_panel_las_incluye_y_el_vigilante_avisa_de_lo_rojo(monkeypatch):
    monkeypatch.setenv("GUILDA_CADUCIDADES", "Secreto X=2026-10-10")
    monkeypatch.setenv("GUILDA_CERT_HOSTS", "ok.ejemplo.com")
    monkeypatch.setattr(salud, "_caducidad_certificado", lambda host: AHORA + timedelta(days=100))
    items = {i["clave"]: i for i in salud.panel(AHORA)}
    assert items["caduca:Secreto X"]["estado"] == salud.ROJO and items["cert:ok.ejemplo.com"]["estado"] == salud.VERDE
    assert items["caduca:Secreto X"]["grupo"] == "Servidor"


def test_una_comprobacion_que_revienta_sale_en_gris(monkeypatch):
    monkeypatch.setenv("GUILDA_CERT_HOSTS", "x.ejemplo.com")
    monkeypatch.setattr(salud, "_caducidad_certificado", lambda host: (_ for _ in ()).throw(RuntimeError("boom")))
    [i] = salud._estado_certificados(AHORA)
    assert i["estado"] == salud.ROJO                                                     # un error de verificación es rojo, no un fallo del panel
    monkeypatch.setattr(salud, "_estado_disco", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    items = salud.panel(AHORA)
    assert any(i["clave"] == "disco" and i["estado"] == salud.GRIS for i in items)                  # una comprobación rota no tumba el panel
