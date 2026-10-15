"""Mensajes seguros por enlace público (app/mensajes_enlace.py) en el Gabinete de abogados y la Inmobiliaria."""
import pytest

from app import abogados as ab, db, inmobiliaria as im, mensajes_enlace as me, nucleo, verticales
from tests.test_abogados import _asunto, _despacho
from tests.test_inmobiliaria import _agencia, _piso


@pytest.fixture
def asunto(usuario_id):
    t, (u1, u2) = _despacho("Bufete mensajes")
    c, x = _asunto(t, u1)
    return t, u1, u2, x


def test_un_enlace_nace_sin_mensajes_y_solo_los_admite_si_se_pide(asunto):
    t, u1, u2, x = asunto
    solo_lectura = ab.crear_enlace(t, u1, x, 7)
    with pytest.raises(ValueError, match="no admite mensajes"):
        me.enviar_externo(ab.ID, solo_lectura, "Pepe", "Hola")
    assert ab.datos_publicos(solo_lectura)["permite_mensajes"] is False and ab.datos_publicos(solo_lectura)["mensajes"] == []
    con = ab.crear_enlace(t, u1, x, 7, permite_mensajes=True)
    assert ab.datos_publicos(con)["permite_mensajes"] is True
    assert [e["permite_mensajes"] for e in ab.listar_enlaces(t, x)] == [1, 0]


def test_la_persona_escribe_el_equipo_contesta_y_el_hilo_se_ve_en_las_dos_partes(asunto):
    t, u1, u2, x = asunto
    token = ab.crear_enlace(t, u1, x, 7, permite_mensajes=True)
    me.enviar_externo(ab.ID, token, "Cliente Uno", "¿Cuándo es la vista?")
    assert me.no_leidos(ab.ID, t, x) == 1
    ctx = me.contexto_panel(ab.ID, t, x)
    assert ctx["sin_leer"] == 1 and ctx["activo"] is True and ctx["mensajes"][0]["texto"] == "¿Cuándo es la vista?"
    assert me.no_leidos(ab.ID, t, x) == 0, "abrir el panel los marca como leídos"
    me.responder(ab.ID, t, u1, x, "El día 14 a las 10:00.")
    publico = ab.datos_publicos(token)["mensajes"]
    assert [(m["autor"], m["nombre"], m["texto"]) for m in publico] == [("externo", "Cliente Uno", "¿Cuándo es la vista?"), ("despacho", None, "El día 14 a las 10:00.")]


def test_el_equipo_del_expediente_recibe_un_aviso_y_quien_no_es_del_equipo_no(asunto):
    t, u1, u2, x = asunto
    assert nucleo.miembros_de(x) == [] and me._equipo_del_expediente(t, x) == [u1]                # sin equipo ni responsable, avisa a quien lo creó
    token = ab.crear_enlace(t, u1, x, 7, permite_mensajes=True)
    me.enviar_externo(ab.ID, token, None, "Una duda")
    avisos = [n for n in db.listar_notificaciones(u1, 10) if n["tipo"] == "portal_mensaje_nuevo"]
    assert len(avisos) == 1 and "Una duda" in avisos[0]["cuerpo"]
    assert [n for n in db.listar_notificaciones(u2, 10) if n["tipo"] == "portal_mensaje_nuevo"] == []


@pytest.mark.parametrize("texto,fragmento", [("", "escribe algo"), ("   ", "escribe algo"), ("x" * 2001, "máximo 2000")])
def test_el_mensaje_se_valida(asunto, texto, fragmento):
    t, u1, u2, x = asunto
    token = ab.crear_enlace(t, u1, x, 7, permite_mensajes=True)
    with pytest.raises(ValueError, match=fragmento):
        me.enviar_externo(ab.ID, token, "A", texto)
    with pytest.raises(ValueError, match="máximo 80"):
        me.enviar_externo(ab.ID, token, "n" * 81, "hola")
    assert me.hilo(ab.ID, t, x) == []


def test_tope_de_mensajes_al_dia_por_enlace(asunto, monkeypatch):
    t, u1, u2, x = asunto
    token = ab.crear_enlace(t, u1, x, 7, permite_mensajes=True)
    monkeypatch.setattr(me, "MAX_POR_DIA", 3)
    for i in range(3):
        me.enviar_externo(ab.ID, token, None, f"mensaje {i}")
    with pytest.raises(ValueError, match="muchos mensajes"):
        me.enviar_externo(ab.ID, token, None, "uno más")
    otro = ab.crear_enlace(t, u1, x, 7, permite_mensajes=True)                    # el tope es por enlace
    me.enviar_externo(ab.ID, otro, None, "desde otro enlace")


def test_un_enlace_revocado_o_caducado_corta_los_mensajes(asunto):
    t, u1, u2, x = asunto
    token = ab.crear_enlace(t, u1, x, 7, permite_mensajes=True)
    (e,) = ab.listar_enlaces(t, x)
    ab.revocar_enlace(t, u1, x, e["id"])
    with pytest.raises(ValueError, match="no admite mensajes"):
        me.enviar_externo(ab.ID, token, None, "hola")
    assert me.enlace_vivo_con_mensajes(ab.ID, t, x) is False
    with pytest.raises(ValueError, match="No hay ningún enlace activo"):
        me.responder(ab.ID, t, u1, x, "¿hay alguien?")
    me.enviar_externo(ab.ID, ab.crear_enlace(t, u1, x, 7, permite_mensajes=True), None, "de nuevo")          # un enlace nuevo vuelve a abrir el canal


def test_un_token_inventado_no_escribe_y_otro_modulo_no_vale(asunto):
    t, u1, u2, x = asunto
    token = ab.crear_enlace(t, u1, x, 7, permite_mensajes=True)
    with pytest.raises(ValueError, match="no admite mensajes"):
        me.enviar_externo(ab.ID, "inventado", None, "hola")
    with pytest.raises(ValueError, match="no admite mensajes"):
        me.enviar_externo(im.ID, token, None, "hola")               # el token de abogados no sirve en la tabla de inmobiliaria


def test_solo_quien_ve_el_expediente_puede_responder(asunto):
    t, u1, u2, x = asunto
    ab.crear_enlace(t, u1, x, 7, permite_mensajes=True)
    ajeno_t, (ajeno, _) = _despacho("Bufete ajeno mensajes")
    with pytest.raises(ValueError, match="Expediente no encontrado"):
        me.responder(ab.ID, ajeno_t, ajeno, x, "intruso")


def test_el_texto_va_escapado_en_la_pagina_publica(cliente, asunto):
    t, u1, u2, x = asunto
    token = ab.crear_enlace(t, u1, x, 7, permite_mensajes=True)
    me.enviar_externo(ab.ID, token, "<b>Yo</b>", "<script>alert(1)</script>")
    html = cliente.get(f"/asunto/{token}").get_data(as_text=True)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html and "<script>alert(1)</script>" not in html and "&lt;b&gt;Yo&lt;/b&gt;" in html


def test_la_pagina_publica_enseña_y_recibe_mensajes_solo_si_el_enlace_los_admite(cliente, asunto):
    t, u1, u2, x = asunto
    solo = ab.crear_enlace(t, u1, x, 7)
    assert "Mensajes con el despacho" not in cliente.get(f"/asunto/{solo}").get_data(as_text=True)
    assert cliente.post(f"/asunto/{solo}/mensajes", data={"texto": "hola"}).status_code == 400
    token = ab.crear_enlace(t, u1, x, 7, permite_mensajes=True)
    html = cliente.get(f"/asunto/{token}").get_data(as_text=True)
    assert "Mensajes con el despacho" in html and f"/asunto/{token}/mensajes" in html
    r = cliente.post(f"/asunto/{token}/mensajes", data={"nombre": "Marta", "texto": "Gracias por la información"})
    assert r.status_code == 302 and r.headers["Location"].endswith("#mensajes") and r.headers["Cache-Control"] == "no-store"
    assert "Gracias por la información" in cliente.get(f"/asunto/{token}").get_data(as_text=True)
    malo = cliente.post(f"/asunto/{token}/mensajes", data={"texto": " "})
    assert malo.status_code == 400 and "escribe algo" in malo.get_data(as_text=True)
    assert cliente.post("/asunto/inventado/mensajes", data={"texto": "hola"}).status_code == 404


def test_el_equipo_ve_el_hilo_en_el_panel_y_responde_desde_la_web(cliente, usuario_id):
    from tests.conftest import iniciar_sesion_de_prueba
    uid = iniciar_sesion_de_prueba(cliente, "abog-msg@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Bufete web mensajes"); db.asignar_tenant(uid, t); verticales.fijar_activo(t, "abogados", True)
    c, x = _asunto(t, uid)
    token = ab.crear_enlace(t, uid, x, 7, permite_mensajes=True)
    me.enviar_externo(ab.ID, token, "Marta", "¿Alguna novedad?")
    html = cliente.get(f"/expedientes/{x}").get_data(as_text=True)
    assert "Mensajes con la persona del enlace" in html and "¿Alguna novedad?" in html and "1 nuevo" in html
    r = cliente.post(f"/abogados/expedientes/{x}/mensajes", data={"texto": "Mañana te llamamos"})
    assert r.status_code == 302 and "error" not in r.headers["Location"]
    assert "Mañana te llamamos" in cliente.get(f"/asunto/{token}").get_data(as_text=True)
    assert "1 nuevo" not in cliente.get(f"/expedientes/{x}").get_data(as_text=True)
    r = cliente.post(f"/abogados/expedientes/{x}/mensajes", data={"texto": ""})
    assert "error" in r.headers["Location"]


# --- Inmobiliaria ----------------------------------------------------------------------------------------------------------------------------------

def test_el_propietario_tambien_puede_escribir_a_la_agencia(cliente, usuario_id):
    t, (u1, u2) = _agencia("Agencia mensajes")
    prop, iid, xid = _piso(t, u1)
    token = im.crear_enlace(t, u1, iid, 7, permite_mensajes=True)
    assert "Mensajes con el despacho" in cliente.get(f"/propietario/{token}").get_data(as_text=True)
    r = cliente.post(f"/propietario/{token}/mensajes", data={"nombre": "Propietario", "texto": "¿Hay ofertas?"})
    assert r.status_code == 302
    assert [m["texto"] for m in me.hilo(im.ID, t, xid)] == ["¿Hay ofertas?"]
    me.responder(im.ID, t, u1, xid, "Sí, una de 240.000.")
    assert "Sí, una de 240.000." in cliente.get(f"/propietario/{token}").get_data(as_text=True)
    solo = im.crear_enlace(t, u1, iid, 7)
    assert cliente.post(f"/propietario/{solo}/mensajes", data={"texto": "hola"}).status_code == 400
    assert me.hilo(im.ID, t, xid)[0]["texto"] == "¿Hay ofertas?" and len(me.hilo(ab.ID, t, xid)) == 0


def test_borrar_el_despacho_borra_sus_mensajes(asunto):
    t, u1, u2, x = asunto
    token = ab.crear_enlace(t, u1, x, 7, permite_mensajes=True)
    me.enviar_externo(ab.ID, token, None, "hola")
    db.borrar_tenant(t)
    conn = db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM mensajes_enlace").fetchone()[0] == 0
    conn.close()


def test_se_avisa_tambien_al_responsable_y_a_los_miembros_sin_repetir(asunto):
    t, u1, u2, x = asunto
    conn = db.get_connection(); conn.execute("UPDATE expedientes SET responsable_id = ? WHERE id = ?", (u2, x)); conn.execute("INSERT INTO expediente_miembros (expediente_id, usuario_id) VALUES (?, ?)", (x, u2)); conn.commit(); conn.close()
    assert me._equipo_del_expediente(t, x) == [u2]
    token = ab.crear_enlace(t, u1, x, 7, permite_mensajes=True)
    me.enviar_externo(ab.ID, token, None, "Hola")
    assert len([n for n in db.listar_notificaciones(u2, 10) if n["tipo"] == "portal_mensaje_nuevo"]) == 1
