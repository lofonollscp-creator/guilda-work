"""Marca del despacho (app/marca.py, app/rutas_marca.py): nombre, logo y color propios, con contraste y sin SVG."""
import io

import pytest
from PIL import Image

from app import db, marca
from tests.conftest import iniciar_sesion_de_prueba


def _png(lado=300, color=(200, 30, 30, 255), formato="PNG"):
    b = io.BytesIO(); Image.new("RGBA" if formato == "PNG" else "RGB", (lado, lado), color if formato == "PNG" else color[:3]).save(b, formato); return b.getvalue()


def _despacho(nombre="Despacho marca"):
    t = db.crear_tenant(nombre); u = db.crear_usuario_vinculado_a_kratos(f"mar-{nombre.replace(' ', '')}@ejemplo.com", f"k-{nombre}"); db.asignar_tenant(u, t)
    return t, u


def test_sin_personalizar_no_hay_marca():
    t, _ = _despacho()
    assert marca.obtener(t) is None and marca.obtener(None) is None and marca.logo(t) is None and marca.css(None).startswith("/* sin marca")


def test_guardar_nombre_color_y_logo_normaliza_el_logo():
    t, _ = _despacho()
    marca.guardar(t, nombre="  Gestoría   Luna ", color="#1A73E8", logo_subido=_png(600))
    m = marca.obtener(t)
    assert m["nombre"] == "Gestoría Luna" and m["color"] == "#1a73e8" and m["tiene_logo"] is True
    im = Image.open(io.BytesIO(marca.logo(t)))
    assert im.format == "PNG" and max(im.size) == 256
    marca.guardar(t, nombre="", color="", quitar_logo=True)
    assert marca.obtener(t) is None


def test_el_logo_conserva_el_que_habia_si_no_se_sube_otro():
    t, _ = _despacho()
    marca.guardar(t, nombre="A", logo_subido=_png(100))
    marca.guardar(t, nombre="B")
    assert marca.obtener(t)["tiene_logo"] is True and marca.obtener(t)["nombre"] == "B"
    marca.guardar(t, restablecer=True)
    assert marca.obtener(t) is None and marca.logo(t) is None


@pytest.mark.parametrize("contenido,fragmento", [
    (b"", "vacío"), (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "No se ha podido leer"), (b"no es una imagen", "No se ha podido leer"),
    (b"GIF89a" + b"\x00" * 50, "No se ha podido leer"), (b"x" * (400 * 1024 + 1), "pesa demasiado")])
def test_logos_no_validos(contenido, fragmento):
    with pytest.raises(ValueError, match=fragmento):
        marca.preparar_logo(contenido)


def test_gif_y_otros_formatos_reales_se_rechazan():
    b = io.BytesIO(); Image.new("RGB", (20, 20), "red").save(b, "GIF")
    with pytest.raises(ValueError, match="PNG, JPEG o WebP"):
        marca.preparar_logo(b.getvalue())
    assert marca.preparar_logo(_png(50, formato="JPEG"))[:4] == b"\x89PNG"


@pytest.mark.parametrize("color", ["rojo", "#fff", "#12345g", "123456", "#1234567", "url(x)"])
def test_colores_no_validos(color):
    t, _ = _despacho()
    with pytest.raises(ValueError, match="color"):
        marca.guardar(t, color=color)


@pytest.mark.parametrize("color", ["#a6e600", "#ffff00", "#ffffff", "#000000", "#1a73e8", "#7a0000", "#222222", "#ff00ff"])
def test_los_colores_derivados_siempre_se_leen(color):
    d = marca.colores_derivados(color)
    lum = marca._luminancia
    assert marca._contraste(lum(d["primary"]), lum(d["on_accent"])) >= 4.5, "texto sobre el botón de acento"
    assert marca._contraste(lum(d["texto_claro"]), 1.0) >= 4.5, "acento como texto en tema claro"
    assert marca._contraste(lum(d["texto_oscuro"]), 0.004) >= 4.0, "acento como texto en tema oscuro"


def test_css_solo_lleva_variables_de_color():
    c = marca.css({"color": "#1a73e8"})
    assert "--primary: #1a73e8" in c and "--on-accent" in c and 'data-theme="dark"' in c and "{" in c and "url(" not in c and "@import" not in c
    assert marca.css({"color": None, "nombre": "x"}).startswith("/* sin marca")


# --- Pantallas -----------------------------------------------------------------------------------------------------------------------------------

def test_solo_la_direccion_edita_la_marca(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "mar-1@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho marca web"); db.asignar_tenant(uid, t)
    assert cliente.get("/marca/").status_code == 403 and cliente.post("/marca/", data={"nombre": "X"}).status_code == 403
    assert marca.obtener(t) is None


def test_la_direccion_guarda_y_el_equipo_ve_la_marca(cliente, monkeypatch):
    uid = iniciar_sesion_de_prueba(cliente, "mar-2@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho marca web 2"); db.asignar_tenant(uid, t)
    monkeypatch.setattr("app.acceso.es_directivo", lambda u: True)
    assert "Marca del despacho" in cliente.get("/marca/").get_data(as_text=True)
    r = cliente.post("/marca/", data={"nombre": "Gestoría Luna", "usar_color": "1", "color": "#1a73e8", "logo": (io.BytesIO(_png(120)), "logo.png")}, content_type="multipart/form-data")
    assert r.status_code == 302 and marca.obtener(t)["nombre"] == "Gestoría Luna"
    html = cliente.get("/marca/").get_data(as_text=True)
    assert "Gestoría Luna" in html and "/marca/estilo.css" in html and "/marca/logo" in html
    assert cliente.get("/marca/estilo.css").get_data(as_text=True).count("#1a73e8") >= 1
    r = cliente.get("/marca/logo")
    assert r.status_code == 200 and r.mimetype == "image/png" and "sandbox" in r.headers["Content-Security-Policy"]
    r = cliente.post("/marca/", data={"nombre": "X", "color": "#ff", "usar_color": "1"})
    assert r.status_code == 200 and "color" in r.get_data(as_text=True)
    cliente.post("/marca/", data={"restablecer": "1"})
    assert marca.obtener(t) is None and cliente.get("/marca/logo").status_code == 404


def test_otro_despacho_no_ve_la_marca_ni_el_logo(cliente):
    t1, _ = _despacho("Despacho con marca"); marca.guardar(t1, nombre="Solo mía", logo_subido=_png(100))
    uid = iniciar_sesion_de_prueba(cliente, "mar-3@ejemplo.com", "contrasena123")
    t2 = db.crear_tenant("Despacho sin marca"); db.asignar_tenant(uid, t2)
    assert cliente.get("/marca/logo").status_code == 404 and "Solo mía" not in cliente.get("/correo/").get_data(as_text=True)


def test_sin_sesion_no_hay_recursos_de_marca(cliente):
    assert cliente.get("/marca/estilo.css").status_code == 302 and cliente.get("/marca/logo").status_code == 302


def test_sin_marca_el_menu_sigue_siendo_guilda_work(cliente):
    iniciar_sesion_de_prueba(cliente, "mar-4@ejemplo.com", "contrasena123")
    html = cliente.get("/correo/").get_data(as_text=True)
    assert "icon-rail-etiqueta\">Guilda Work<" in html and "/marca/estilo.css" not in html
