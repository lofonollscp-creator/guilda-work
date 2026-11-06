"""Tareas periódicas en el backoffice (K7): estado de cada una y relanzado manual de las seguras."""
import pytest

from app import db, salud, tareas_periodicas as tp
from tests.test_backoffice_app import bo, entrar, post  # noqa: F401 -- fixture


@pytest.fixture(autouse=True)
def _limpio():
    yield
    tp._en_marcha.clear()


def test_lista_todas_las_tareas_con_su_estado_y_marca_las_relanzables():
    salud.registrar_ok("recordatorios_portal", 21600, "3 enviado(s)")
    salud.registrar_error("vigilante_salud", 900, "RuntimeError: x")
    filas = {f["nombre"]: f for f in tp.listar()}
    assert set(filas) == set(salud.ETIQUETAS_LATIDOS)
    assert filas["recordatorios_portal"]["estado"] == salud.VERDE and filas["recordatorios_portal"]["relanzable"]
    assert filas["vigilante_salud"]["estado"] == salud.ROJO and filas["vigilante_salud"]["ultimo_error"]
    assert not filas["correo_sync"]["relanzable"] and filas["correo_sync"]["estado"] == salud.GRIS
    assert tp.listar()[0]["estado"] == salud.ROJO, "lo que falla sale primero"


def test_relanzar_ejecuta_la_pasada_y_anota_el_resultado(monkeypatch):
    llamadas = []
    monkeypatch.setitem(tp.RELANZABLES, "vigilante_salud", (lambda: llamadas.append(1) or "2 punto(s) avisado(s)", 900))
    assert tp.relanzar("vigilante_salud", esperar=True) is True and llamadas == [1]
    fila = {f["nombre"]: f for f in tp.listar()}["vigilante_salud"]
    assert fila["estado"] == salud.VERDE and "relanzada a mano" in fila["detalle"] and "2 punto(s)" in fila["detalle"]


def test_si_la_pasada_falla_queda_como_error_y_no_se_propaga(monkeypatch):
    def rota():
        raise RuntimeError("SMTP caído")
    monkeypatch.setitem(tp.RELANZABLES, "recordatorios_portal", (rota, 21600))
    assert tp.relanzar("recordatorios_portal", esperar=True) is True
    fila = {f["nombre"]: f for f in tp.listar()}["recordatorios_portal"]
    assert fila["estado"] == salud.ROJO and "SMTP caído" in fila["detalle"]
    assert tp._en_marcha == set(), "tras fallar se puede volver a lanzar"


def test_no_se_relanza_lo_que_no_esta_permitido_ni_dos_veces_a_la_vez():
    assert tp.relanzar("correo_sync") is False and tp.relanzar("inventada") is False
    tp._en_marcha.add("vigilante_salud")
    assert tp.relanzar("vigilante_salud") is False


def test_pantalla_y_accion_en_el_backoffice(bo, monkeypatch):
    monkeypatch.setitem(tp.RELANZABLES, "vigilante_salud", (lambda: "ok", 900))
    entrar(bo)
    html = bo.get("/tareas").get_data(as_text=True)
    assert "Tareas periódicas" in html and "Vigilante de salud" in html and "Relanzar ahora" in html
    assert post(bo, "/tareas/vigilante_salud/relanzar").status_code == 302
    assert post(bo, "/tareas/correo_sync/relanzar").status_code == 302
    import time
    for _ in range(50):
        if not tp._en_marcha:
            break
        time.sleep(0.05)
    assert "relanzada a mano" in bo.get("/tareas").get_data(as_text=True)
