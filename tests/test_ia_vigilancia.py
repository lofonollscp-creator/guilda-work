"""Vigilancia de la IA (Y11): la dirección recibe un aviso al cruzar el 80 % y el 100 % del tope y cuando un proveedor falla de forma sostenida; nunca más de una vez por umbral y mes."""
import pytest

from app import db, ia_consumo, ia_uso, ia_vigilancia, notificaciones


@pytest.fixture
def avisos(monkeypatch):
    enviados = []
    monkeypatch.setattr(notificaciones, "crear_y_enviar", lambda uid, tipo, titulo, cuerpo, **kw: enviados.append((uid, tipo, titulo)))
    return enviados


def _despacho(n):
    t = db.crear_tenant(f"Vigilancia {n}")
    direccion = db.crear_usuario_vinculado_a_kratos(f"dir-vig{n}@ejemplo.com", f"k-dir-vig{n}")
    equipo = db.crear_usuario_vinculado_a_kratos(f"eq-vig{n}@ejemplo.com", f"k-eq-vig{n}")
    for u in (direccion, equipo):
        db.asignar_tenant(u, t)
    db.asignar_supervisor_tenant(direccion, True)
    return t, direccion, equipo


def test_umbral_cruzado_solo_en_el_momento_exacto():
    assert ia_vigilancia.umbral_cruzado(7, 8, 10) == 80 and ia_vigilancia.umbral_cruzado(8, 9, 10) is None
    assert ia_vigilancia.umbral_cruzado(9, 10, 10) == 100 and ia_vigilancia.umbral_cruzado(0, 1, 10) is None
    assert ia_vigilancia.umbral_cruzado(0, 1, None) is None and ia_vigilancia.umbral_cruzado(0, 1, 0) is None
    assert ia_vigilancia.umbral_cruzado(0, 1, 1) == 100                                    # con un tope de 1, la primera consulta cruza los dos: se avisa del mayor


def test_el_consumo_avisa_a_la_direccion_una_vez_al_80_y_otra_al_100(avisos):
    t, direccion, equipo = _despacho(1)
    ia_consumo.fijar_limite(t, 10)
    for _ in range(7):
        ia_consumo.reservar(equipo)
    assert avisos == []
    ia_consumo.reservar(equipo)                                                            # la octava: 80 %
    assert [(a[0], a[1]) for a in avisos] == [(direccion, "ia_consumo")] and "80" in avisos[0][2]
    ia_consumo.reservar(equipo)
    assert len(avisos) == 1
    ia_consumo.reservar(equipo)                                                            # la décima: 100 %
    assert len(avisos) == 2 and "agotado" in avisos[1][2]
    with pytest.raises(ia_consumo.LimiteIA):
        ia_consumo.reservar(equipo)
    assert len(avisos) == 2                                                                # el rechazo no vuelve a avisar


def test_sin_tope_no_hay_avisos(avisos):
    t, direccion, equipo = _despacho(2)
    for _ in range(5):
        ia_consumo.reservar(equipo)
    assert avisos == []


def test_un_proveedor_que_falla_avisa_a_los_cinco_fallos_si_fallan_mas_de_las_que_salen_bien(avisos):
    t, direccion, equipo = _despacho(3)
    for _ in range(4):
        ia_uso.registrar_error(t, "openai", "asistente", "web")
    assert avisos == []
    ia_uso.registrar_error(t, "openai", "asistente", "web")
    assert [(a[0], a[1]) for a in avisos] == [(direccion, "ia_proveedor")] and "openai" in avisos[0][2]
    ia_uso.registrar_error(t, "openai", "asistente", "web")
    assert len(avisos) == 1                                                                # solo en el quinto
    t2, d2, _e2 = _despacho(4)
    for _ in range(30):
        ia_uso.registrar(t2, "openai", "gpt-4o-mini", "asistente", "web", {"prompt_tokens": 1, "completion_tokens": 1})
    for _ in range(5):
        ia_uso.registrar_error(t2, "openai", "asistente", "web")
    assert avisos[1:] == []                                                                # fallos esporádicos entre muchas consultas correctas: no hay nada que avisar
