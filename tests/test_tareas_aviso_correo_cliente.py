"""Aviso por correo al equipo cuando un cliente comenta en una tarea: opt-in, solo a su dueño, sin el texto, uno por hora y tarea."""
import pytest

from app import db, notificaciones_email as ne, tareas_trabajo as tt
from tests.test_tareas_portal_cliente import _comentar, _guardados, _mundo, _portal, _tarea_comentable


@pytest.fixture
def correo(monkeypatch):
    enviados = []
    monkeypatch.setattr(ne, "configurado", lambda: True)
    monkeypatch.setattr(ne, "_enviar", lambda destino, asunto, plano, html=None: enviados.append((destino, asunto, plano, html)))
    return enviados


def _activar(uid, valor=True):
    db.guardar_perfil_usuario(uid, avisos_cliente_por_correo=valor)


def test_por_defecto_no_se_manda_ningun_correo_al_equipo(cliente, correo):
    uid, t, c1, c2 = _mundo(cliente, "ac1@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    _comentar(_portal(cliente, c1), tid)
    assert correo == [] and len(_guardados(tid)) == 1


def test_con_el_aviso_activado_llega_un_correo_sin_el_texto_del_cliente(cliente, correo):
    uid, t, c1, c2 = _mundo(cliente, "ac2@ejemplo.com")
    _activar(uid)
    tid = _tarea_comentable(uid, t, c1, asunto="Reunir facturas")
    _comentar(_portal(cliente, c1), tid, "Mi número de cuenta es ES00 SECRETO")
    assert len(correo) == 1
    destino, asunto, plano, html = correo[0]
    assert destino == "ac2@ejemplo.com" and "comentado" in asunto.lower()
    assert "Cliente Uno" in plano and "Reunir facturas" in plano and f"/tareas/{tid}" in html
    assert "SECRETO" not in plano and "SECRETO" not in html                                       # el texto del cliente no viaja por correo


def test_como_mucho_un_correo_por_persona_y_tarea_cada_hora(cliente, correo):
    uid, t, c1, c2 = _mundo(cliente, "ac3@ejemplo.com")
    _activar(uid)
    tid = _tarea_comentable(uid, t, c1)
    otra = _tarea_comentable(uid, t, c1, asunto="Otra tarea")
    p = _portal(cliente, c1)
    for i in range(4):
        _comentar(p, tid, f"Duda {i}")
    assert len(correo) == 1                                                                        # cuatro comentarios, un correo
    _comentar(p, otra, "Otra duda")
    assert len(correo) == 2                                                                        # otra tarea, otro correo
    conn = db.get_connection()
    try:
        conn.execute("UPDATE tarea_avisos_correo SET enviado_en = '2000-01-01T00:00:00' WHERE tarea_id = ?", (tid,))
        conn.commit()
    finally:
        conn.close()
    _comentar(p, tid, "Pasada la hora")
    assert len(correo) == 3


def test_solo_avisa_a_quien_lo_activo_y_lleva_la_tarea(cliente, correo):
    uid, t, c1, c2 = _mundo(cliente, "ac4@ejemplo.com")
    ajeno = db.crear_usuario_vinculado_a_kratos("ac4-ajeno@ejemplo.com", "k-ac4-ajeno")
    db.asignar_tenant(ajeno, db.crear_tenant("Otro despacho ac4"))
    _activar(ajeno)                                                                                # lo tiene activado, pero ni la lleva ni la ve
    tid = _tarea_comentable(uid, t, c1)
    _comentar(_portal(cliente, c1), tid)
    assert correo == []                                                                            # el dueño no lo activó; el ajeno no recibe nada
    _activar(uid)
    _comentar(_portal(cliente, c1), tid, "Segundo")
    assert [c[0] for c in correo] == ["ac4@ejemplo.com"]


def test_sin_correo_saliente_configurado_el_comentario_se_guarda_igual(cliente, monkeypatch):
    uid, t, c1, c2 = _mundo(cliente, "ac5@ejemplo.com")
    _activar(uid)
    monkeypatch.setattr(ne, "configurado", lambda: False)
    tid = _tarea_comentable(uid, t, c1)
    assert _comentar(_portal(cliente, c1), tid).status_code == 302 and len(_guardados(tid)) == 1


def test_un_fallo_del_correo_no_estropea_el_comentario(cliente, monkeypatch):
    uid, t, c1, c2 = _mundo(cliente, "ac6@ejemplo.com")
    _activar(uid)
    monkeypatch.setattr(ne, "configurado", lambda: True)

    def roto(*a, **k):
        raise ne.ErrorNotificacionesEmail("SMTP caído")
    monkeypatch.setattr(ne, "_enviar", roto)
    tid = _tarea_comentable(uid, t, c1)
    assert _comentar(_portal(cliente, c1), tid).status_code == 302 and len(_guardados(tid)) == 1


def test_se_activa_desde_el_perfil(cliente):
    uid, t, c1, c2 = _mundo(cliente, "ac7@ejemplo.com")
    html = cliente.get("/ajustes/perfil").get_data(as_text=True)
    assert "Comentarios de clientes en tareas, por correo" in html and 'name="avisos_cliente_por_correo"' in html
    assert not db.obtener_perfil_usuario(uid)["avisos_cliente_por_correo"]
    assert cliente.post("/ajustes/perfil", data={"avisos_cliente_por_correo": "on"}).status_code == 302
    assert db.obtener_perfil_usuario(uid)["avisos_cliente_por_correo"] == 1
    cliente.post("/ajustes/perfil", data={})
    assert db.obtener_perfil_usuario(uid)["avisos_cliente_por_correo"] == 0
