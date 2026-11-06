"""Histórico del panel de salud (M1): muestras, tendencia por día, incidencias y la pantalla del backoffice."""
from datetime import datetime, timedelta

from app import salud, salud_historial as sh
from tests.test_backoffice_app import bo, entrar  # noqa: F401 -- fixture

AHORA = datetime(2026, 11, 20, 9, 0)


def _i(clave="disco", estado="verde", valor=None):
    return {"grupo": "Servidor", "clave": clave, "titulo": clave.capitalize(), "estado": estado, "detalle": "x", "valor": valor}


def test_registra_una_muestra_por_hora_salvo_que_cambie_el_estado():
    assert sh.registrar([_i(valor=40.0)], AHORA) == 1
    assert sh.registrar([_i(valor=41.0)], AHORA + timedelta(minutes=15)) == 0          # misma hora y mismo estado
    assert sh.registrar([_i(estado="rojo", valor=4.0)], AHORA + timedelta(minutes=30)) == 1   # cambia: se guarda al momento
    assert sh.registrar([_i(estado="rojo", valor=4.0)], AHORA + timedelta(hours=2)) == 1       # pasó más de una hora


def test_la_tendencia_toma_el_peor_estado_de_cada_dia_y_cuenta_los_rojos():
    sh.registrar([_i(estado="verde", valor=30.0)], AHORA - timedelta(days=2))
    sh.registrar([_i(estado="verde", valor=25.0)], AHORA - timedelta(days=1))
    sh.registrar([_i(estado="rojo", valor=3.0)], AHORA - timedelta(days=1, hours=-2))
    sh.registrar([_i(estado="verde", valor=28.0)], AHORA)
    t = sh.tendencias([_i()], 7, AHORA)["disco"]
    por_dia = {c["dia"]: c["estado"] for c in t["casillas"]}
    assert len(t["casillas"]) == 7
    assert por_dia["2026-11-19"] == "rojo" and por_dia["2026-11-18"] == "verde" and por_dia["2026-11-14"] is None
    assert (t["dias_con_datos"], t["dias_rojo"], t["sin_rojo_pct"]) == (3, 1, 67)
    assert t["serie"] == [30.0, 25.0, 3.0, 28.0] and t["puntos"].count(" ") == 3


def test_punto_sin_datos_no_rompe_y_sin_valores_no_hay_linea():
    t = sh.tendencias([_i("nuevo")], 30, AHORA)["nuevo"]
    assert t["dias_con_datos"] == 0 and t["sin_rojo_pct"] is None and t["puntos"] == ""


def test_incidencias_abiertas_y_cerradas():
    sh.registrar([_i("a", "verde")], AHORA - timedelta(hours=5))
    sh.registrar([_i("a", "rojo")], AHORA - timedelta(hours=4))
    sh.registrar([_i("a", "verde")], AHORA - timedelta(hours=1))
    sh.registrar([_i("b", "rojo")], AHORA - timedelta(minutes=30))
    tramos = {t["clave"]: t for t in sh.incidencias(7, AHORA)}
    assert tramos["a"]["minutos"] == 180 and not tramos["a"]["abierto"]
    assert tramos["b"]["abierto"] and tramos["b"]["hasta"] is None


def test_se_borra_lo_de_mas_de_90_dias():
    sh.registrar([_i("viejo")], AHORA - timedelta(days=100))
    sh.registrar([_i("nuevo")], AHORA)
    assert sh.tendencias([_i("viejo")], 90, AHORA)["viejo"]["dias_con_datos"] == 0


def test_el_vigilante_guarda_el_historico(monkeypatch):
    monkeypatch.setattr(salud, "panel", lambda ahora=None: [_i("disco", "verde", 50.0)])
    salud.vigilar(AHORA)
    assert sh.tendencias([_i("disco")], 7, AHORA)["disco"]["dias_con_datos"] == 1


def test_la_pantalla_enseña_la_tendencia(bo, monkeypatch):
    entrar(bo)
    monkeypatch.setattr(salud, "panel", lambda ahora=None: [_i("disco", "verde", 50.0)])
    sh.registrar([_i("disco", "rojo", 3.0)], datetime.now() - timedelta(hours=3))
    sh.registrar([_i("disco", "verde", 50.0)], datetime.now() - timedelta(hours=1))
    html = bo.get("/salud?dias=7").get_data(as_text=True)
    assert "casilla-rojo" in html and "sin rojo" in html and "Incidencias en rojo" in html
    assert bo.get("/salud?dias=999").status_code == 200
