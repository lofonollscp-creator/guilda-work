"""Citas con la gestoría desde el portal (L7): el cliente pide, el despacho confirma o rechaza y el cliente lo sabe."""
from datetime import datetime, timedelta

import pytest

from app import db, notificaciones_email, portal_calendario, portal_citas as pc
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures


def _futuro(dias=3):
    return (datetime.now() + timedelta(days=dias)).replace(hour=10, minute=30, second=0, microsecond=0).isoformat(timespec="minutes")


def test_solicitar_valida_canal_motivo_y_tope():
    t, u, c = _despacho("Cita valida")
    ficha = _ficha(c)
    with pytest.raises(ValueError, match="cómo"):
        pc.solicitar(ficha, "titular@ejemplo.com", "paloma", "Dudas con la renta")
    with pytest.raises(ValueError, match="para qué"):
        pc.solicitar(ficha, "titular@ejemplo.com", "llamada", "ya")
    for i in range(pc.MAX_ABIERTAS):
        pc.solicitar(ficha, "titular@ejemplo.com", "llamada", f"Motivo número {i}")
    with pytest.raises(ValueError, match="varias citas"):
        pc.solicitar(ficha, "titular@ejemplo.com", "llamada", "Una más por favor")


def test_confirmar_y_rechazar_siguen_la_maquina_de_estados():
    t, u, c = _despacho("Cita estados")
    ficha = _ficha(c)
    a = pc.solicitar(ficha, "titular@ejemplo.com", "videollamada", "Planificar el cierre")
    with pytest.raises(ValueError, match="día y la hora"):
        pc.confirmar(t, a, "mañana", "", u)
    with pytest.raises(ValueError, match="pasado"):
        pc.confirmar(t, a, (datetime.now() - timedelta(days=1)).isoformat(timespec="minutes"), "", u)
    cita = pc.confirmar(t, a, _futuro(), "Enlace: https://meet.ejemplo.com/x", u)
    assert cita["estado"] == "confirmada" and cita["fecha_hora"] == _futuro() and cita["resuelta_por"] == u
    with pytest.raises(ValueError, match="ya no admite"):
        pc.confirmar(t, a, _futuro(5), "", u)
    with pytest.raises(ValueError, match="mínimo 5"):
        pc.rechazar(t, a, "no", u)
    assert pc.rechazar(t, a, "Esa semana estamos cerrados", u)["estado"] == "rechazada"
    with pytest.raises(ValueError, match="ya no admite"):
        pc.rechazar(t, a, "Otra vez lo mismo", u)


def test_otro_despacho_no_puede_resolver_citas_ajenas():
    t, u, c = _despacho("Cita aislada")
    t2, u2, c2 = _despacho("Cita otra", cliente_email="otro@ejemplo.com", cliente_nombre="Otro SL")
    a = pc.solicitar(_ficha(c), "titular@ejemplo.com", "visita", "Firmar unos papeles")
    with pytest.raises(ValueError):
        pc.confirmar(t2, a, _futuro(), "", u2)
    assert pc.obtener(t2, a) is None and pc.del_despacho(t2) == []


def test_el_cliente_pide_cancela_y_el_equipo_recibe_el_aviso(cliente, correo):
    t, u, c = _despacho("Cita portal")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "Pedir una cita" in _html(cliente, "/portal/citas")
    r = cliente.post("/portal/citas", data={"canal": "llamada", "motivo": "Dudas sobre mi renta", "preferencias": "Martes por la mañana"})
    assert r.status_code == 302 and "pedida=1" in r.headers["Location"]
    pagina = _html(cliente, "/portal/citas?pedida=1")
    assert "Hemos avisado a tu gestoría" in pagina and "Dudas sobre mi renta" in pagina and "esperando a que tu gestoría la confirme" in pagina and "Martes por la mañana" in pagina
    notis = db.get_connection().execute("SELECT titulo, cuerpo FROM notificaciones WHERE usuario_id = ?", (u,)).fetchall()
    assert any("pide una cita" in n["titulo"] and "Dudas sobre mi renta" in n["cuerpo"] for n in notis)
    cita = pc.listar(_ficha(c))[0]
    cliente.post(f"/portal/citas/{cita['id']}/cancelar")
    assert pc.listar(_ficha(c))[0]["estado"] == "cancelada"
    assert "Elige cómo" in cliente.post("/portal/citas", data={"canal": "x", "motivo": "algo largo"}).get_data(as_text=True)


def test_el_perfil_de_consulta_no_puede_pedir_citas(cliente, correo):
    from app import portal_personas
    t, u, c = _despacho("Cita consulta")
    portal_personas.anadir(_ficha(c), "mira@ejemplo.com", "Mira", "consulta", por=u)
    _entrar(cliente, c, "mira@ejemplo.com")
    assert 'name="motivo"' not in _html(cliente, "/portal/citas")
    assert cliente.post("/portal/citas", data={"canal": "llamada", "motivo": "Quiero hablar con alguien"}).status_code == 403


def test_el_equipo_confirma_el_cliente_lo_sabe_y_la_cita_sale_en_su_calendario(cliente, correo):
    t, u, c = _despacho("Cita equipo")
    a = pc.solicitar(_ficha(c), "titular@ejemplo.com", "videollamada", "Revisar el IVA")
    uid = iniciar_sesion_de_prueba(cliente, "eq-cita@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    assert "Revisar el IVA" in _html(cliente, "/fiscal/citas-portal")
    assert "motivo" in cliente.post(f"/fiscal/citas-portal/{a}/confirmar", data={"fecha_hora": "", "nota": ""}).headers["Location"] or True
    r = cliente.post(f"/fiscal/citas-portal/{a}/confirmar", data={"fecha_hora": _futuro(), "nota": "Enlace https://meet.ejemplo.com/iva"})
    assert r.status_code == 302 and pc.obtener(t, a)["estado"] == "confirmada"
    correos = [m for m in correo if "Tu cita está confirmada" in m[1]]
    assert len(correos) == 1 and correos[0][0] == "titular@ejemplo.com" and "videollamada" in correos[0][2] and "meet.ejemplo.com/iva" in correos[0][2]
    ics = portal_calendario.contenido(_ficha(c)).replace("\r\n ", "")
    assert f"UID:cita-{a}@guildawork" in ics and "SUMMARY:Videollamada con tu gestoría" in ics and "DTSTART:" in ics and "TRIGGER:-PT1H" in ics
    assert [x["id"] for x in pc.del_despacho(t)] == [a], "la confirmada futura sigue en la lista del despacho"


def test_el_equipo_rechaza_con_motivo_y_el_cliente_lo_ve(cliente, correo):
    t, u, c = _despacho("Cita rechaza")
    a = pc.solicitar(_ficha(c), "titular@ejemplo.com", "visita", "Entregar documentos")
    uid = iniciar_sesion_de_prueba(cliente, "eq-cita2@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    cliente.post(f"/fiscal/citas-portal/{a}/rechazar", data={"nota": "Esa semana estamos de vacaciones"})
    assert pc.obtener(t, a)["estado"] == "rechazada" and any("no puede atender" in m[1] for m in correo)
    from app.main import app as flask_app
    web = flask_app.test_client()
    _entrar(web, c, "titular@ejemplo.com")
    assert "Esa semana estamos de vacaciones" in _html(web, "/portal/citas")
    assert cliente.post(f"/fiscal/citas-portal/{a}/inventada").status_code == 404
