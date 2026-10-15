"""Vistas personalizables del correo (app/correo_vista.py): tamaño de letra, disposición, ancho de lista y vista previa."""
import pytest

from app import correo_vista, db
from tests.conftest import iniciar_sesion_de_prueba


def test_limpiar_solo_deja_lo_valido():
    assert correo_vista.limpiar(tam_letra="grande", disposicion="inferior", ancho_lista="400", vista_previa=False) == {
        "tam_letra": "grande", "disposicion": "inferior", "ancho_lista": 400, "vista_previa": 0}
    assert correo_vista.limpiar(tam_letra="enorme", disposicion="diagonal", ancho_lista="abc") == {}
    assert correo_vista.limpiar() == {}


@pytest.mark.parametrize("entrada,esperado", [(0, 0), (-5, 0), (100, 280), (5000, 720), (500, 500)])
def test_el_ancho_se_acota_y_cero_es_automatico(entrada, esperado):
    assert correo_vista.limpiar(ancho_lista=entrada)["ancho_lista"] == esperado


def test_escala_del_cuerpo_html():
    assert correo_vista.con_escala("<p>x</p>", 1.0) == "<p>x</p>" and correo_vista.con_escala(None, 1.3) is None
    assert correo_vista.con_escala("<p>x</p>", 1.15).startswith("<style>html{zoom:1.15}</style>")


def _usuario(cliente, email):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    cuenta = db.crear_cuenta_correo(uid, "Trabajo", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    return uid, cuenta


def test_por_defecto_las_preferencias_son_las_de_siempre(cliente):
    uid, _ = _usuario(cliente, "vista-def@ejemplo.com")
    v = correo_vista.para_plantilla(db.obtener_preferencias_correo(uid))
    assert v == {"letra": "normal", "disposicion": "tres", "ancho_lista": None, "escala": 1.0, "vista_previa": True}


def test_guardar_desde_ajustes_y_verlo_en_la_bandeja(cliente):
    uid, cuenta = _usuario(cliente, "vista-aj@ejemplo.com")
    r = cliente.post("/correo/ajustes/preferencias", data={"densidad": "normal", "limite_mensajes": "50", "tam_letra": "muy_grande", "disposicion": "inferior", "ancho_lista": "450"})
    assert r.status_code == 302
    p = db.obtener_preferencias_correo(uid)
    assert (p["tam_letra"], p["disposicion"], p["ancho_lista"], p["vista_previa"]) == ("muy_grande", "inferior", 450, 0)       # casilla sin marcar = sin extracto
    db.guardar_mensaje_correo(cuenta_id=cuenta, uid="1", asunto="Hola", remitente="a@b.com", destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="x", cuerpo_html=None)
    html = cliente.get(f"/correo/?cuenta_id={cuenta}").get_data(as_text=True)
    assert 'data-letra="muy_grande"' in html and 'data-disposicion="inferior"' in html and "--correo-ancho-lista: 450px" in html and "sin-vista-previa" in html


def test_un_formulario_antiguo_sin_campos_de_vista_no_los_borra(cliente):
    uid, _ = _usuario(cliente, "vista-ant@ejemplo.com")
    cliente.post("/correo/ajustes/preferencias", data={"densidad": "normal", "limite_mensajes": "50", "tam_letra": "grande", "vista_previa": "on"})
    cliente.post("/correo/ajustes/preferencias", data={"densidad": "compacta", "limite_mensajes": "60"})
    p = db.obtener_preferencias_correo(uid)
    assert (p["tam_letra"], p["vista_previa"], p["densidad"]) == ("grande", 1, "compacta")


def test_el_divisor_guarda_el_ancho(cliente):
    uid, _ = _usuario(cliente, "vista-div@ejemplo.com")
    assert cliente.post("/correo/ajustes/ancho-lista", data={"ancho": "512"}).status_code == 204
    assert db.obtener_preferencias_correo(uid)["ancho_lista"] == 512
    cliente.post("/correo/ajustes/ancho-lista", data={"ancho": "9999"})
    assert db.obtener_preferencias_correo(uid)["ancho_lista"] == 720


def test_el_cuerpo_html_lleva_la_escala_y_solo_lista_abre_a_pantalla_completa(cliente):
    uid, cuenta = _usuario(cliente, "vista-cu@ejemplo.com")
    m = db.guardar_mensaje_correo(cuenta_id=cuenta, uid="1", asunto="Hola", remitente="a@b.com", destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="x", cuerpo_html="<p>Hola</p>")
    cliente.post("/correo/ajustes/preferencias", data={"densidad": "normal", "limite_mensajes": "50", "tam_letra": "grande", "disposicion": "tres"})
    html = cliente.get(f"/correo/?cuenta_id={cuenta}&mensaje_id={m}").get_data(as_text=True)
    assert "zoom:1.15" in html and "es-pantalla-completa" not in html
    cliente.post("/correo/ajustes/preferencias", data={"densidad": "normal", "limite_mensajes": "50", "tam_letra": "normal", "disposicion": "lista"})
    html = cliente.get(f"/correo/?cuenta_id={cuenta}&mensaje_id={m}").get_data(as_text=True)
    assert "es-pantalla-completa" in html and "zoom:" not in html
    assert "es-pantalla-completa" not in cliente.get(f"/correo/?cuenta_id={cuenta}").get_data(as_text=True)


def test_el_movil_distingue_lista_y_mensaje_y_siempre_hay_volver(cliente):
    uid, cuenta = _usuario(cliente, "vista-mov@ejemplo.com")
    m = db.guardar_mensaje_correo(cuenta_id=cuenta, uid="1", asunto="Hola", remitente="a@b.com", destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="x", cuerpo_html=None)
    sin = cliente.get(f"/correo/?cuenta_id={cuenta}").get_data(as_text=True)
    con = cliente.get(f"/correo/?cuenta_id={cuenta}&mensaje_id={m}").get_data(as_text=True)
    import re
    abrir = lambda h: re.search(r'<div class="correo-shell[^"]*"', h).group(0)
    assert "con-mensaje" not in abrir(sin) and "con-mensaje" in abrir(con) and 'class="correo-lectura-volver"' in con


def test_el_mensaje_lleva_cabecera_fija_y_el_iframe_ajusta_su_altura_sin_scripts(cliente):
    uid, cuenta = _usuario(cliente, "vista-fija@ejemplo.com")
    m = db.guardar_mensaje_correo(cuenta_id=cuenta, uid="1", asunto="Hola", remitente="a@b.com", destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="x", cuerpo_html="<p>Hola</p>")
    html = cliente.get(f"/correo/?cuenta_id={cuenta}&mensaje_id={m}").get_data(as_text=True)
    assert 'class="correo-lectura-fija"' in html and html.index("correo-lectura-fija") < html.index("correo-ribbon") < html.index("correo-lectura-asunto")
    assert 'sandbox="allow-same-origin"' in html and "allow-scripts" not in html.split("<iframe", 1)[1].split(">", 1)[0] and "data-autoaltura" in html
