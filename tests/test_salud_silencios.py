"""Acuse, silencio y responsable de los puntos del panel de salud (K5)."""
from datetime import datetime, timedelta

import pytest

from app import notificaciones_email, salud, salud_silencios as ss
from tests.test_backoffice_app import bo, entrar, post  # noqa: F401 -- fixture

AHORA = datetime(2026, 11, 20, 9, 0)


def _rojo(clave="restic", titulo="Copia de seguridad", estado=salud.ROJO):
    return {"grupo": "Copias", "clave": clave, "titulo": titulo, "estado": estado, "detalle": "falla"}


@pytest.fixture
def correos(monkeypatch):
    enviados = []
    monkeypatch.setattr(notificaciones_email, "enviar_alerta_interna", lambda asunto, cuerpo: enviados.append((asunto, cuerpo)))
    return enviados


def _panel(monkeypatch, items):
    monkeypatch.setattr(salud, "panel", lambda ahora=None: items)


def test_silenciar_exige_motivo_y_dias_validos():
    with pytest.raises(ValueError, match="motivo"):
        ss.silenciar("restic", 3, "no")
    with pytest.raises(ValueError, match="1, 3, 7 o 30"):
        ss.silenciar("restic", 5, "motivo válido")
    hasta = ss.silenciar("restic", 3, "  Se arregla el jueves  ", "jorge", ahora=AHORA)
    assert hasta == (AHORA + timedelta(days=3)).isoformat(timespec="seconds")
    assert ss.todos()["restic"]["motivo"] == "Se arregla el jueves" and ss.activos(AHORA) == {"restic"}


def test_un_punto_silenciado_no_avisa_y_otro_si(monkeypatch, correos):
    _panel(monkeypatch, [_rojo("restic"), _rojo("disco", "Disco")])
    ss.silenciar("restic", 1, "ya lo sabemos", "jorge", ahora=AHORA)
    assert salud.vigilar(AHORA) == ["disco"] and "Disco" in correos[0][1] and "Copia de seguridad" not in correos[0][1]


def test_el_silencio_caduca_con_su_fecha(monkeypatch, correos):
    _panel(monkeypatch, [_rojo()])
    ss.silenciar("restic", 1, "mantenimiento", "jorge", ahora=AHORA)
    assert salud.vigilar(AHORA + timedelta(hours=1)) == []
    assert salud.vigilar(AHORA + timedelta(days=1, hours=1)) == ["restic"]


def test_si_se_arregla_el_silencio_se_levanta_y_vuelve_a_avisar_si_falla(monkeypatch, correos):
    ss.silenciar("restic", 30, "ya lo sabemos", "jorge", ahora=AHORA)
    _panel(monkeypatch, [_rojo(estado=salud.VERDE)])
    assert salud.vigilar(AHORA + timedelta(hours=2)) == [] and ss.activos(AHORA + timedelta(hours=2)) == set()
    _panel(monkeypatch, [_rojo()])
    assert salud.vigilar(AHORA + timedelta(days=2)) == ["restic"]


def test_asignar_no_calla_nada_y_se_conserva_al_quitar_el_silencio(monkeypatch, correos):
    ss.asignar("restic", "  Marta  ", "jorge")
    _panel(monkeypatch, [_rojo()])
    assert salud.vigilar(AHORA) == ["restic"]
    ss.silenciar("restic", 1, "motivo válido", "jorge", ahora=AHORA)
    ss.quitar_silencio("restic", "jorge")
    assert ss.todos()["restic"]["asignado_a"] == "Marta" and ss.activos(AHORA) == set()
    ss.asignar("restic", "", "jorge")
    assert "restic" not in ss.todos(), "sin responsable ni silencio la fila desaparece"


def test_anotar_deja_el_silencio_y_el_responsable_en_cada_punto():
    ss.silenciar("restic", 7, "motivo válido", "jorge", ahora=datetime.now())
    ss.asignar("disco", "Marta", "jorge")
    items = ss.anotar([_rojo("restic"), _rojo("disco"), _rojo("otro")])
    assert items[0]["silencio"]["motivo"] == "motivo válido" and items[0]["asignado_a"] is None
    assert items[1]["silencio"] is None and items[1]["asignado_a"] == "Marta" and items[2]["silencio"] is None


def test_sin_la_tabla_el_vigilante_sigue_avisando(monkeypatch, correos):
    _panel(monkeypatch, [_rojo()])
    monkeypatch.setattr(ss, "activos", lambda ahora=None: (_ for _ in ()).throw(RuntimeError("sin tabla")))
    assert salud.vigilar(AHORA) == ["restic"]


def test_pantalla_silenciar_asignar_y_quitar(bo):
    entrar(bo)
    html = bo.get("/salud").get_data(as_text=True)
    clave = next(c for c in ("restic", "disco", "backup") if f'value="{c}"' in html) if 'name="clave"' in html else None
    assert clave, "con la base de pruebas hay al menos un punto en rojo o ámbar"
    r = post(bo, "/salud/silenciar", clave=clave, dias="3", motivo="")
    assert "motivo" in bo.get("/salud").get_data(as_text=True).lower()
    post(bo, "/salud/silenciar", clave=clave, dias="3", motivo="Ya lo sabemos, se arregla el jueves")
    assert "SILENCIADO" in bo.get("/salud").get_data(as_text=True)
    post(bo, "/salud/asignar", clave=clave, asignado_a="Marta")
    assert "Marta" in bo.get("/salud").get_data(as_text=True)
    post(bo, "/salud/silencio/quitar", clave=clave)
    assert "SILENCIADO" not in bo.get("/salud").get_data(as_text=True)
