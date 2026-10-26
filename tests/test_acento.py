"""Color de acento por persona: lista cerrada, texto legible (WCAG >= 4,5:1) en tema claro y oscuro, y solo afecta a quien lo elige."""
import pytest

from app import acento, marca
from tests.conftest import iniciar_sesion_de_prueba


@pytest.mark.parametrize("clave", [k for k in acento.ACENTOS if k != acento.ACENTO_POR_DEFECTO])
def test_todo_acento_ofrecido_se_lee_en_claro_y_en_oscuro(clave):
    d = marca.colores_derivados(acento.ACENTOS[clave][1])
    lum = marca._luminancia
    assert marca._contraste(lum(d["primary"]), lum(d["on_accent"])) >= 4.5       # texto del botón sobre el acento
    assert marca._contraste(lum(d["texto_claro"]), lum("#f7f8fa")) >= 4.5         # enlaces sobre el fondo real de la página (gris claro, no blanco)
    assert marca._contraste(lum(d["texto_claro"]), 1.0) >= 4.5                    # y sobre las tarjetas blancas
    assert marca._contraste(lum(d["texto_oscuro"]), lum("#101113")) >= 4.5        # enlaces sobre las tarjetas oscuras


def test_el_acento_por_defecto_no_sobrescribe_nada():
    assert acento.css("lima") == "" and acento.css(None) == "" and acento.css("inventado") == ""


def test_elegir_acento_se_recuerda_en_el_navegador_y_se_pinta(cliente):
    iniciar_sesion_de_prueba(cliente, "acento@ejemplo.com", "contrasena123")
    assert "--primary: #8b5cf6" not in cliente.get("/ajustes/perfil").get_data(as_text=True)
    r = cliente.post("/ajustes/acento", data={"acento": "violeta"})
    assert r.status_code == 302 and "guilda-acento=violeta" in r.headers["Set-Cookie"]
    html = cliente.get("/ajustes/perfil").get_data(as_text=True)
    assert "--primary: #8b5cf6" in html and 'aria-checked="true"' in html
    cliente.post("/ajustes/acento", data={"acento": "no-existe"})
    assert "--primary: #8b5cf6" in cliente.get("/ajustes/perfil").get_data(as_text=True)
