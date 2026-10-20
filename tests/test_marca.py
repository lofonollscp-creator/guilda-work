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


# --- Correos que salen en nombre del despacho ----------------------------------------------------------------------------------------------------

from app import correo_diseno, notificaciones_email as ne


def test_sin_marca_el_correo_es_el_de_siempre():
    plano, html = correo_diseno.construir("Hola", ["Texto"], boton=("Abrir", "https://x.test/a"))
    assert correo_diseno.ACENTO in html and "email-logo.png" in html and 'alt="Guilda Work"' in html and "Guilda Work ·" in html
    assert correo_diseno.construir("Hola", ["Texto"], boton=("Abrir", "https://x.test/a"), marca=None) == (plano, html)


def test_con_marca_el_correo_lleva_su_color_su_logo_y_su_nombre():
    marca_d = {"nombre": "Gestoría Luna", "color": "#1a73e8", "logo_url": "https://app.test/marca/p/abc.png"}
    plano, html = correo_diseno.construir("Hola", ["Texto"], boton=("Abrir", "https://x.test/a"), cita="Un documento", codigo="123456", marca=marca_d)
    assert "#1a73e8" in html and correo_diseno.ACENTO not in html
    assert 'src="https://app.test/marca/p/abc.png"' in html and 'alt="Gestoría Luna"' in html and "email-logo.png" not in html
    assert "Gestoría Luna" in html and "Guilda Work" not in html and plano.rstrip().endswith("Gestoría Luna")
    assert "color:#ffffff;text-decoration:none" in html or "color:#0a0a0a;text-decoration:none" in html


def test_la_marca_sin_color_ni_logo_solo_cambia_el_nombre():
    _, html = correo_diseno.construir("Hola", ["Texto"], boton=("Abrir", "https://x.test/a"), marca={"nombre": "Luna", "color": None, "logo_url": None})
    assert correo_diseno.ACENTO in html and "email-logo.png" in html and 'alt="Luna"' in html


def test_el_nombre_de_la_marca_no_puede_inyectar_html():
    _, html = correo_diseno.construir("Hola", ["x"], marca={"nombre": '"><script>alert(1)</script>', "color": None, "logo_url": 'x" onerror="alert(1)'})
    assert "<script>alert" not in html and 'onerror="alert' not in html


def test_para_correo_firma_el_enlace_del_logo_y_la_ruta_publica_lo_sirve():
    t, _ = _despacho("Despacho marca correo")
    assert marca.para_correo(t) is None and marca.para_correo(None) is None
    marca.guardar(t, nombre="Luna", color="#1a73e8", logo_subido=_png(80))
    m = marca.para_correo(t)
    assert m["nombre"] == "Luna" and m["color"] == "#1a73e8" and "/marca/p/" in m["logo_url"] and m["logo_url"].endswith(".png")
    token = m["logo_url"].rsplit("/", 1)[1][:-4]
    assert marca.tenant_de_token(token) == t and marca.tenant_de_token(token + "x") is None and marca.tenant_de_token("basura") is None
    marca.guardar(t, nombre="Luna", color="#1a73e8", quitar_logo=True)                      # sin logo no hay enlace
    assert marca.para_correo(t)["logo_url"] is None


def _ruta_alterada(ruta: str) -> str:
    """La misma ruta con la firma estropeada. Se cambia la PRIMERA letra de la firma: la última de una firma de 160 bits solo lleva 4 bits útiles y cambiarla daba por buena la firma
    alrededor de un 7 % de las veces (según el momento en que se creara el token), lo que hacía el test intermitente."""
    cuerpo, extension = ruta[:-4], ruta[-4:]
    payload, firma = cuerpo.rsplit(".", 1)
    return payload + "." + ("A" if firma[0] != "A" else "B") + firma[1:] + extension


def test_el_logo_publico_se_ve_sin_sesion_solo_con_el_enlace_firmado(cliente):
    t, _ = _despacho("Despacho marca publica")
    marca.guardar(t, nombre="Luna", logo_subido=_png(80))
    url = marca.para_correo(t)["logo_url"]
    ruta = "/marca/p/" + url.rsplit("/marca/p/", 1)[1]
    r = cliente.get(ruta)
    assert r.status_code == 200 and r.mimetype == "image/png" and r.data[:4] == b"\x89PNG" and "sandbox" in r.headers["Content-Security-Policy"]
    assert cliente.get(_ruta_alterada(ruta)).status_code == 404 and cliente.get("/marca/p/inventado.png").status_code == 404
    marca.guardar(t, nombre="Luna", quitar_logo=True)
    assert cliente.get(ruta).status_code == 404


def test_un_enlace_de_logo_no_sirve_el_de_otro_despacho(cliente):
    t1, _ = _despacho("Despacho marca A"); t2, _ = _despacho("Despacho marca B")
    marca.guardar(t1, logo_subido=_png(80, color=(255, 0, 0, 255))); marca.guardar(t2, logo_subido=_png(80, color=(0, 0, 255, 255)))
    token1 = marca.para_correo(t1)["logo_url"].rsplit("/", 1)[1]
    assert cliente.get("/marca/p/" + token1).data != cliente.get("/marca/p/" + marca.para_correo(t2)["logo_url"].rsplit("/", 1)[1]).data


def _capturar(monkeypatch):
    enviados = []
    monkeypatch.setattr(ne, "_enviar", lambda destino, asunto, plano, html=None: enviados.append((destino, asunto, plano, html)))
    return enviados


@pytest.mark.parametrize("llamar", [
    lambda t: ne.enviar_enlace_portal("c@x.test", "https://x.test/e", tenant_id=t),
    lambda t: ne.enviar_solicitud_documento("c@x.test", "El modelo 303", "https://x.test/p", tenant_id=t),
    lambda t: ne.enviar_enlace_pago("c@x.test", "Honorarios", "https://pay.test/x", tenant_id=t),
    lambda t: ne.enviar_respuesta_portal("c@x.test", "Ya lo tenemos", "https://x.test/p", tenant_id=t),
    lambda t: ne.enviar_recordatorio_vencimiento("c@x.test", "Cliente SL", "303", "2026-3T", "2026-10-20", 7, "https://x.test/p", "Gestoría Luna", tenant_id=t),
    lambda t: ne.enviar_aviso_certificado("c@x.test", "Cliente SL", "FNMT", "2026-12-01", 30, "https://x.test/p", "Gestoría Luna", tenant_id=t),
])
def test_los_correos_a_clientes_llevan_la_marca_del_despacho(monkeypatch, llamar):
    t, _ = _despacho("Despacho marca clientes")
    marca.guardar(t, nombre="Gestoría Luna", color="#1a73e8", logo_subido=_png(80))
    enviados = _capturar(monkeypatch)
    llamar(None)
    llamar(t)
    sin, con = enviados
    assert "#1a73e8" not in sin[3] and "email-logo.png" in sin[3]
    assert "#1a73e8" in con[3] and "/marca/p/" in con[3] and "email-logo.png" not in con[3]
    assert "Guilda Work" not in con[1]


def test_si_la_marca_falla_el_correo_sale_igual_con_el_diseno_de_siempre(monkeypatch):
    enviados = _capturar(monkeypatch)
    monkeypatch.setattr(marca, "para_correo", lambda t: (_ for _ in ()).throw(RuntimeError("roto")))
    ne.enviar_enlace_portal("c@x.test", "https://x.test/e", tenant_id=1)
    assert len(enviados) == 1 and "email-logo.png" in enviados[0][3]


def test_el_enlace_del_portal_se_manda_con_la_marca_del_despacho_del_cliente(monkeypatch, cliente):
    t = db.crear_tenant("Despacho marca portal")
    marca.guardar(t, nombre="Gestoría Luna", color="#1a73e8")
    db.crear_cliente_fiscal(t, "Cliente SL", email="cliente@x.test")
    from app import rutas_portal_cliente
    llamadas = []
    monkeypatch.setattr(rutas_portal_cliente, "enviar_enlace_portal", lambda email, enlace, **kw: llamadas.append((email, kw)))
    cliente.post("/portal/entrar", data={"email": "cliente@x.test"})
    assert llamadas == [("cliente@x.test", {"tenant_id": t})]
