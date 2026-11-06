"""Lectura previa de facturas en el portal (L3): apagada por defecto, la enciende el despacho, nunca guarda nada y cuenta como consulta de IA."""
import json

import pytest

from app import db, ia_asistente, ia_consumo, lectura_facturas, portal_lectura_previa as plp
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, correo  # noqa: F401 -- fixtures

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200
LECTURA = {"emisor_nombre": "Papelería Sol SL", "emisor_nif": "b-12345674", "numero": "2026/118", "fecha": "2026-10-03", "total": "121,00", "lineas": []}


@pytest.fixture
def ia(monkeypatch):
    """La IA configurada y una respuesta fija; devuelve la lista de consultas que se hicieron."""
    consultas = []
    monkeypatch.setattr(lectura_facturas, "configurada", lambda uid: True)
    monkeypatch.setattr(ia_asistente, "completar_partes", lambda uid, prompt, partes: consultas.append(uid) or json.dumps(LECTURA))
    return consultas


def _subir(http, nombre="f.png", datos=PNG, tipo="image/png"):
    import io
    return http.post("/portal/facturas/leer-previa", data={"archivo": (io.BytesIO(datos), nombre, tipo)}, content_type="multipart/form-data")


def test_esta_apagada_por_defecto_y_el_despacho_la_enciende_y_apaga(cliente, ia):
    t, u, c = _despacho("LP defecto")
    assert not plp.activa(t) and not plp.disponible(_ficha(c))
    plp.fijar(t, True)
    assert plp.activa(t) and plp.disponible(_ficha(c))
    plp.fijar(t, False)
    assert not plp.activa(t)


def test_sin_ia_preparada_no_esta_disponible(cliente, monkeypatch):
    t, u, c = _despacho("LP sin ia")
    plp.fijar(t, True)
    monkeypatch.setattr(lectura_facturas, "configurada", lambda uid: False)
    assert not plp.disponible(_ficha(c))


def test_el_endpoint_lee_y_devuelve_los_datos_sin_guardar_nada(cliente, ia, correo):
    t, u, c = _despacho("LP lee")
    plp.fijar(t, True)
    _entrar(cliente, c, "titular@ejemplo.com")
    antes = db.get_connection().execute("SELECT COUNT(*) FROM facturas_contables").fetchone()[0]
    r = _subir(cliente)
    j = r.get_json()
    assert r.status_code == 200 and j["disponible"] and j["lectura"]["emisor"] == "Papelería Sol SL" and j["lectura"]["fecha"] == "2026-10-03" and j["lectura"]["total"] == "121.00"
    assert j["lectura"]["numero"] == "2026/118" and j["lectura"]["avisos"] == []
    assert db.get_connection().execute("SELECT COUNT(*) FROM facturas_contables").fetchone()[0] == antes
    assert ia == [u], "se lee con la IA de quien lleva al cliente"


def test_cuenta_como_consulta_de_ia_y_respeta_el_tope(cliente, ia, correo):
    t, u, c = _despacho("LP tope")
    plp.fijar(t, True)
    _entrar(cliente, c, "titular@ejemplo.com")
    _subir(cliente)
    assert ia_consumo.estado(t)["usadas"] == 1
    conn = db.get_connection(); conn.execute("UPDATE tenants SET ia_limite_mensual = 1 WHERE id = ?", (t,)); conn.commit(); conn.close()
    r = _subir(cliente)
    assert r.status_code == 422 and "no está disponible" in r.get_json()["error"] and len(ia) == 1


def test_avisa_de_lo_que_no_se_lee(cliente, monkeypatch, correo):
    t, u, c = _despacho("LP dudas")
    plp.fijar(t, True)
    monkeypatch.setattr(lectura_facturas, "configurada", lambda uid: True)
    monkeypatch.setattr(ia_asistente, "completar_partes", lambda uid, p, partes: json.dumps({"emisor_nombre": None, "numero": "7", "fecha": "ayer", "total": None}))
    _entrar(cliente, c, "titular@ejemplo.com")
    j = _subir(cliente).get_json()
    assert j["lectura"]["avisos"] == ["emisor", "fecha", "total"]


def test_si_el_modelo_falla_el_cliente_puede_enviar_igualmente(cliente, monkeypatch, correo):
    t, u, c = _despacho("LP falla")
    plp.fijar(t, True)
    monkeypatch.setattr(lectura_facturas, "configurada", lambda uid: True)
    def roto(uid, p, partes):
        raise ia_asistente.ErrorIA("caída", 500)
    monkeypatch.setattr(ia_asistente, "completar_partes", roto)
    _entrar(cliente, c, "titular@ejemplo.com")
    r = _subir(cliente)
    assert r.status_code == 422 and "enviarla igualmente" in r.get_json()["error"]


def test_apagada_o_con_perfil_de_consulta_el_endpoint_no_existe_para_el_cliente(cliente, ia, correo):
    from app import portal_personas
    t, u, c = _despacho("LP permisos")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert _subir(cliente).status_code == 404                              # apagada
    plp.fijar(t, True)
    portal_personas.anadir(_ficha(c), "mira@ejemplo.com", "Mira", "consulta", por=u)
    cliente.post("/portal/salir")
    _entrar(cliente, c, "mira@ejemplo.com")
    assert _subir(cliente).status_code == 403 and ia == []                 # el perfil de consulta no puede hacer POST


def test_archivos_que_no_son_facturas_o_demasiado_grandes_se_rechazan(cliente, ia, correo):
    t, u, c = _despacho("LP tipos")
    plp.fijar(t, True)
    _entrar(cliente, c, "titular@ejemplo.com")
    assert _subir(cliente, "x.txt", b"hola", "text/plain").status_code == 422
    assert _subir(cliente, "x.png", b"0" * (plp.MAX_BYTES + 10)).status_code == 422
    assert ia == []


def test_la_pagina_de_facturas_solo_ofrece_la_lectura_si_esta_activa(cliente, ia, correo):
    t, u, c = _despacho("LP pagina")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "data-url-leer" not in cliente.get("/portal/facturas").get_data(as_text=True)
    plp.fijar(t, True)
    assert "data-url-leer" in cliente.get("/portal/facturas").get_data(as_text=True)
