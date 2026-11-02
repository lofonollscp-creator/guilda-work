"""Votos y búsquedas sin resultado del centro de ayuda público: lo que se guarda, lo que se rechaza y que nada personal llega a la base."""
import pytest

from app import ayuda_metricas as am

ORIGEN = {"Origin": "https://help.guildawork.com"}


def _post(cliente, ruta, cuerpo, cabeceras=ORIGEN):
    return cliente.post(f"/ayuda-metricas/{ruta}", data=cuerpo, headers=cabeceras, content_type="text/plain")


def test_normaliza_y_descarta_lo_personal():
    assert am.normalizar_consulta("  Cómo   Firmar  ") == "cómo firmar"
    assert am.normalizar_consulta("a") is None
    assert am.normalizar_consulta("x" * 61) is None
    for personal in ("maria@ejemplo.com", "mi nif 12345678Z", "llamar 600 123 456", "https://x.com/a", "x1234567y"):
        assert am.normalizar_consulta(personal) is None, personal


def test_cuenta_las_veces_y_agrupa_por_idioma(cliente):
    assert am.registrar_busqueda("Vacaciones", "es") and am.registrar_busqueda("vacaciones ", "es") and am.registrar_busqueda("vacaciones", "en")
    filas = {(f["idioma"], f["consulta"]): f["veces"] for f in am.busquedas_sin_resultado()}
    assert filas == {("es", "vacaciones"): 2, ("en", "vacaciones"): 1}
    am.borrar_busqueda(am.busquedas_sin_resultado()[0]["id"])
    assert len(am.busquedas_sin_resultado()) == 1


def test_tope_de_textos_distintos(cliente, monkeypatch):
    monkeypatch.setattr(am, "MAX_CONSULTAS_DISTINTAS", 2)
    assert am.registrar_busqueda("uno", "es") and am.registrar_busqueda("dos", "es")
    assert not am.registrar_busqueda("tres", "es")
    assert am.registrar_busqueda("uno", "es")                       # los que ya existen siguen contando


def test_valoraciones_por_guia(cliente):
    for util in (True, True, False):
        assert am.registrar_valoracion("guilda-fiscal/empezar", "es", util)
    am.registrar_valoracion("mi-cuenta/notificaciones", "ca", False)
    g = {x["pagina"]: x for x in am.valoraciones_por_guia()}
    assert g["guilda-fiscal/empezar"]["pct_util"] == 67 and g["guilda-fiscal/empezar"]["votos"] == 3
    assert am.valoraciones_por_guia()[0]["pagina"] == "mi-cuenta/notificaciones"      # la menos útil primero
    assert [x["pagina"] for x in am.valoraciones_por_guia(minimo_votos=2)] == ["guilda-fiscal/empezar"]


@pytest.mark.parametrize("pagina", ["../etc/passwd", "sin-barra", "a/b/c", "A/B", "", "x/" + "y" * 200])
def test_rechaza_paginas_raras(cliente, pagina):
    assert not am.registrar_valoracion(pagina, "es", True)


def test_endpoint_acepta_texto_plano_sin_sesion(cliente):
    assert _post(cliente, "valoracion", '{"pagina": "guilda-fiscal/empezar", "idioma": "es", "util": true}').status_code == 204
    assert _post(cliente, "busqueda", '{"consulta": "turnos de noche", "idioma": "es"}').status_code == 204
    assert am.valoraciones_por_guia()[0]["votos"] == 1 and am.busquedas_sin_resultado()[0]["consulta"] == "turnos de noche"


def test_endpoint_rechaza_origen_ajeno_y_basura(cliente):
    cuerpo = '{"consulta": "turnos", "idioma": "es"}'
    assert _post(cliente, "busqueda", cuerpo, {"Origin": "https://malo.example"}).status_code == 400
    assert _post(cliente, "busqueda", "no es json").status_code == 400
    assert _post(cliente, "busqueda", '{"consulta": "correo@x.com", "idioma": "es"}').status_code == 400
    assert _post(cliente, "valoracion", '{"pagina": "a/b", "idioma": "es", "util": "si"}').status_code == 400   # util debe ser booleano
    assert _post(cliente, "valoracion", "x" * 3000).status_code == 400
    assert am.busquedas_sin_resultado() == [] and am.valoraciones_por_guia() == []


def test_sin_origen_tambien_vale(cliente):                          # curl, pruebas: no es una fuga, solo cuenta una vez
    assert _post(cliente, "busqueda", '{"consulta": "bolsa", "idioma": "fr"}', {}).status_code == 204

