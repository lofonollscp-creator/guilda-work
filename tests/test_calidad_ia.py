"""AA7: resumen semanal de la calidad de la IA, histórico y su reflejo en el panel Salud."""
import json
from datetime import datetime, timedelta

from app import calidad_ia as c, db, salud

AHORA = datetime(2026, 11, 15, 12, 0)


def _a(global_=93.3, inyeccion=100.0, errores=0, casos=30):
    return {"casos": casos, "acierto_global": global_, "por_tipo": {"lectura": 100.0, "inyeccion": inyeccion}, "errores": [{"caso": f"c{i}", "error": "x"} for i in range(errores)], "fallos": [], "segundos_medios": 4.0}


def _f(global_=99.0, errores=0, casos=12):
    return {"casos": casos, "acierto_global": global_, "por_campo": {"total": 90.0}, "errores": [{"caso": f"c{i}", "error": "x"} for i in range(errores)], "fallos": []}


BASE_A = {"acierto_global": 93.3, "por_tipo": {"lectura": 100.0, "inyeccion": 100.0}}
BASE_F = {"acierto_global": 83.9, "por_campo": {"total": 90.0}}


def test_sin_cambios_no_hay_regresiones():
    r = c.resumir(_a(), _f(), BASE_A, BASE_F, "modelo-x", AHORA)
    assert r["regresiones"] == [] and r["inconclusas"] == [] and r["inyeccion"] == 100.0 and r["modelo"] == "modelo-x"


def test_una_bajada_grande_es_regresion_y_una_pequena_no():
    assert c.resumir(_a(global_=80.0), _f(), BASE_A, BASE_F)["regresiones"]
    assert not c.resumir(_a(global_=91.0), _f(), BASE_A, BASE_F)["regresiones"]
    leve = _a(); leve["por_tipo"]["lectura"] = 93.8                                      # un caso suelto de 16: ruido del modelo, no regresión
    assert not c.resumir(leve, _f(), BASE_A, BASE_F)["regresiones"]
    hundida = _a(); hundida["por_tipo"]["lectura"] = 70.0
    assert any("lectura" in x for x in c.resumir(hundida, _f(), BASE_A, BASE_F)["regresiones"])
    r = c.resumir(_a(inyeccion=66.7), _f(), BASE_A, BASE_F)
    assert any("inyeccion" in x for x in r["regresiones"])


def test_si_el_proveedor_no_responde_a_muchos_casos_la_evaluacion_es_inconclusa_y_no_regresion():
    r = c.resumir(_a(global_=40.0, errores=20), _f(), BASE_A, BASE_F)
    assert r["inconclusas"] == ["asistente"] and r["regresiones"] == []
    assert r["asistente"]["acierto_global"] is None and r["inyeccion"] is None          # sin cifras falsas


def test_historial_acotado():
    e = c.resumir(_a(), _f(), None, None, "m", AHORA)
    anterior = {"historial": [{"fecha": str(i)} for i in range(40)]}
    h = c.con_historial(e, anterior)["historial"]
    assert len(h) == c.MAX_HISTORIAL and h[-1]["asistente"] == 93.3


def _panel(tmp_path, monkeypatch, estado):
    monkeypatch.setattr(db, "BACKUPS_DIR", tmp_path)
    (tmp_path / "calidad_ia_estado.json").write_text(json.dumps(estado), encoding="utf-8")
    return salud._estado_calidad_ia(AHORA)


def test_panel_salud(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "BACKUPS_DIR", tmp_path)
    assert salud._estado_calidad_ia(AHORA)["estado"] == salud.GRIS
    bueno = c.resumir(_a(), _f(), BASE_A, BASE_F, "m", AHORA - timedelta(days=1))
    assert _panel(tmp_path, monkeypatch, bueno)["estado"] == salud.VERDE
    assert _panel(tmp_path, monkeypatch, c.resumir(_a(global_=80.0), _f(), BASE_A, BASE_F, "m", AHORA - timedelta(days=1)))["estado"] == salud.AMBAR
    assert _panel(tmp_path, monkeypatch, c.resumir(_a(), _f(global_=94.0), BASE_A, {"acierto_global": 94.0, "por_campo": {"total": 90.0}}, "m", AHORA - timedelta(days=1)))["estado"] == salud.AMBAR     # por debajo del 95 % aunque no empeore
    assert _panel(tmp_path, monkeypatch, c.resumir(_a(inyeccion=66.7), _f(), BASE_A, BASE_F, "m", AHORA - timedelta(days=1)))["estado"] == salud.ROJO
    assert _panel(tmp_path, monkeypatch, c.resumir(_a(errores=20), _f(), BASE_A, BASE_F, "m", AHORA - timedelta(days=1)))["estado"] == salud.AMBAR
    assert _panel(tmp_path, monkeypatch, c.resumir(_a(), _f(), BASE_A, BASE_F, "m", AHORA - timedelta(days=30)))["estado"] == salud.AMBAR


def test_el_panel_no_revienta_con_una_evaluacion_inconclusa(tmp_path, monkeypatch):
    inconclusa = c.resumir(_a(errores=20, global_=0.0), _f(errores=10, global_=0.0), BASE_A, BASE_F, "m", AHORA - timedelta(days=1))
    r = _panel(tmp_path, monkeypatch, inconclusa)
    assert r["estado"] == salud.AMBAR and "?" in r["detalle"] and "inconclusa" in r["detalle"].lower()
