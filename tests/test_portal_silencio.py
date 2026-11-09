"""«No molestar» y respeto al nivel de avisos en las notificaciones al móvil (C2)."""
import json
from datetime import datetime

import pytest

from app import portal_push, portal_silencio as ps, push
from tests.test_portal_personas_avisos import SUSCRIPCION, _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures


@pytest.fixture
def push_activo(monkeypatch):
    enviados = []
    monkeypatch.setattr(push, "VAPID_PUBLICA", "clave-vapid-publica")
    monkeypatch.setattr(push, "VAPID_PRIVADA", "clave-vapid-privada")
    monkeypatch.setattr(push, "_enviar_web", lambda sus, carga: enviados.append(json.loads(sus)["endpoint"]) or True)
    return enviados


def test_la_franja_cruza_la_medianoche_y_respeta_los_extremos():
    noche = {"desde": "22:00", "hasta": "08:00"}
    dia = {"desde": "13:00", "hasta": "15:00"}
    def a(h, m=0):
        return datetime(2026, 11, 9, h, m)
    assert ps.dentro(noche, a(23)) and ps.dentro(noche, a(2)) and ps.dentro(noche, a(22, 0)) and not ps.dentro(noche, a(8, 0)) and not ps.dentro(noche, a(12))
    assert ps.dentro(dia, a(14)) and not ps.dentro(dia, a(15)) and not ps.dentro(dia, a(9))
    assert not ps.dentro(None, a(3))


def test_guardar_valida_y_vaciar_quita_la_franja(cliente, correo):
    t, u, c = _despacho("Silencio guardar")
    ficha = _ficha(c)
    ps.guardar(ficha, "titular@ejemplo.com", "22:00", "08:00")
    assert ps.obtener(ficha, "titular@ejemplo.com") == {"desde": "22:00", "hasta": "08:00"}
    ps.guardar(ficha, "titular@ejemplo.com", "23:00", "07:30")                                       # actualiza, no duplica
    assert ps.obtener(ficha, "titular@ejemplo.com")["desde"] == "23:00"
    for malo in (("25:00", "08:00"), ("22:00", ""), ("22:00", "22:00"), ("ab", "cd")):
        with pytest.raises(ValueError):
            ps.guardar(ficha, "titular@ejemplo.com", *malo)
    ps.guardar(ficha, "titular@ejemplo.com", "", "")
    assert ps.obtener(ficha, "titular@ejemplo.com") is None


def test_dentro_de_la_franja_no_suena_el_movil_pero_el_aviso_queda_en_avisos(cliente, push_activo, monkeypatch):
    t, u, c = _despacho("Silencio push")
    _entrar(cliente, c, "titular@ejemplo.com")
    cliente.post("/portal/push/suscribir", json=SUSCRIPCION)
    ficha = _ficha(c)
    ps.guardar(ficha, "titular@ejemplo.com", "00:00", "23:59")                                       # toda la jornada salvo el último minuto
    monkeypatch.setattr(ps, "datetime", type("D", (datetime,), {"now": classmethod(lambda cls: datetime(2026, 11, 9, 12, 0))}))
    assert portal_push.enviar(ficha, "Factura devuelta", "Falta el NIF", "/portal/facturas") == 0 and push_activo == []
    assert "Factura devuelta" in _html(cliente, "/portal/avisos")
    ps.guardar(ficha, "titular@ejemplo.com", "", "")
    assert portal_push.enviar(ficha, "Otra", "x", "/portal/facturas") == 1


def test_quien_elige_solo_el_resumen_no_recibe_notificaciones_y_quien_elige_urgentes_solo_las_urgentes(cliente, push_activo):
    t, u, c = _despacho("Silencio nivel")
    _entrar(cliente, c, "titular@ejemplo.com")
    cliente.post("/portal/push/suscribir", json=SUSCRIPCION)
    cliente.post("/portal/preferencias", data={"avisos": "resumen"})
    assert portal_push.enviar(_ficha(c), "a", "b", "/portal/") == 0
    cliente.post("/portal/preferencias", data={"avisos": "urgente"})
    assert portal_push.enviar(_ficha(c), "a", "b", "/portal/") == 0 and portal_push.enviar(_ficha(c), "a", "b", "/portal/", urgente=True) == 1
    cliente.post("/portal/preferencias", data={"avisos": "todo"})
    assert portal_push.enviar(_ficha(c), "a", "b", "/portal/") == 1


def test_el_formulario_de_mi_cuenta_guarda_la_franja_y_avisa_de_un_error(cliente, push_activo):
    t, u, c = _despacho("Silencio web")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "No molestar" in _html(cliente, "/portal/cuenta")
    cliente.post("/portal/cuenta/silencio", data={"desde": "22:00", "hasta": "08:00"})
    assert ps.obtener(_ficha(c), "titular@ejemplo.com") == {"desde": "22:00", "hasta": "08:00"}
    assert 'value="22:00"' in _html(cliente, "/portal/cuenta")
    r = cliente.post("/portal/cuenta/silencio", data={"desde": "99:00", "hasta": "08:00"}, follow_redirects=True)
    assert "Escribe las dos horas" in r.get_data(as_text=True)
