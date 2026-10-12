"""Tema y densidad guardados en la cuenta (te siguen entre dispositivos) y cambiables desde el asistente."""
import pytest

from app import db, ia_soporte
from tests.conftest import iniciar_sesion_de_prueba


def test_se_guardan_en_la_cuenta_y_se_aplican_al_cargar(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "apariencia@ejemplo.com", "contrasena123")
    r = cliente.post("/ajustes/apariencia", json={"tema": "dark", "densidad": "compacta"})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert db.apariencia_usuario(uid) == {"tema": "dark", "densidad": "compacta"}
    html = cliente.get("/ajustes").get_data(as_text=True)
    assert '"tema": "dark"' in html and '"densidad": "compacta"' in html, "base.html lo vuelca antes de pintar para que mande sobre el navegador"
    assert "apariencia.js" in html


@pytest.mark.parametrize("cuerpo", [{}, {"tema": "rojo"}, {"densidad": "enorme"}, {"tema": 3}, {"tema": None, "densidad": None}])
def test_valores_no_validos_se_rechazan_sin_tocar_nada(cliente, cuerpo):
    uid = iniciar_sesion_de_prueba(cliente, "apariencia-malo@ejemplo.com", "contrasena123")
    assert cliente.post("/ajustes/apariencia", json=cuerpo).status_code == 400
    assert db.apariencia_usuario(uid) == {"tema": None, "densidad": None}


def test_cambiar_solo_uno_no_pisa_el_otro(usuario_id):
    db.guardar_apariencia_usuario(usuario_id, "light", "compacta")
    db.guardar_apariencia_usuario(usuario_id, densidad="normal")
    assert db.apariencia_usuario(usuario_id) == {"tema": "light", "densidad": "normal"}
    db.guardar_apariencia_usuario(usuario_id, "morado", "gigante")
    assert db.apariencia_usuario(usuario_id) == {"tema": "light", "densidad": "normal"}


def test_requiere_sesion(cliente):
    assert cliente.post("/ajustes/apariencia", json={"tema": "dark"}).status_code in (302, 401)


def test_el_asistente_cambia_tema_y_densidad_de_su_cuenta(usuario_id):
    r = ia_soporte.cambiar_mis_ajustes(usuario_id, tema="dark", densidad="compacta")
    assert "error" not in r and any("apariencia" in c for c in r["cambiado"])
    assert (db.apariencia_usuario(usuario_id)["tema"], r["ajustes_ahora"]["densidad"]) == ("dark", "compacta")
    assert "error" in ia_soporte.cambiar_mis_ajustes(usuario_id, tema="fucsia")
    assert db.apariencia_usuario(usuario_id)["tema"] == "dark"


def test_los_scripts_avisan_a_la_cuenta():
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent / "app" / "static"
    assert "GuildaApariencia.guardar({ tema" in (raiz / "sidebar.js").read_text(encoding="utf-8")
    assert "GuildaApariencia.guardar({ densidad" in (raiz / "sidebar.js").read_text(encoding="utf-8")
    assert "GuildaApariencia.guardar({ tema: v })" in (raiz / "ajustes.js").read_text(encoding="utf-8")
