"""Salud del portal desde el navegador (C2): opcional, solo contadores, sin datos de nadie."""
from datetime import date, timedelta

import pytest

from app import db, portal_telemetria as pt
from tests.test_facturas_contables import _web
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures


def test_las_rutas_se_normalizan_sin_numeros_ni_codigos_ni_consulta():
    assert pt.ruta_normalizada("/portal/facturas/123?trimestre=2026-T1#x") == "/portal/facturas/:id"
    assert pt.ruta_normalizada("/portal/compartido/abcDEF1234567890abcdef") == "/portal/compartido/:codigo"
    assert pt.ruta_normalizada("/portal/") == "/portal/" and pt.ruta_normalizada("/login") == "" and pt.ruta_normalizada("https://otro.com/portal/x") == ""


def test_apagada_por_defecto_no_registra_nada_y_encendida_cuenta_por_dia_y_pantalla():
    t, u, c = _despacho("Telemetria")
    assert pt.activa(t) is False and pt.registrar(t, {"tipo": "carga", "ruta": "/portal/", "ms": 800}) is False
    pt.fijar(t, True)
    assert pt.activa(t) is True
    for ms in (1000, 2000, 3000):
        assert pt.registrar(t, {"tipo": "carga", "ruta": "/portal/facturas", "ms": ms}) is True
    pt.registrar(t, {"tipo": "error", "ruta": "/portal/facturas", "mensaje": "Cannot read properties of undefined (reading 'x') en https://secreto.com/a?token=123 línea 456"})
    pt.registrar(t, {"tipo": "error", "ruta": "/portal/facturas", "mensaje": "Cannot read properties of undefined (reading 'x') en https://secreto.com/b?token=999 línea 789"})
    r = pt.resumen(t)
    assert r["pantallas"] == [{"ruta": "/portal/facturas", "cargas": 3, "media_ms": 2000, "max_ms": 3000}]
    assert len(r["errores"]) == 1 and r["errores"][0]["n"] == 2 and "secreto" not in r["errores"][0]["mensaje"] and "123" not in r["errores"][0]["mensaje"] and "token" not in r["errores"][0]["mensaje"]


def test_rechaza_lo_que_no_vale_y_olvida_lo_antiguo():
    t, u, c = _despacho("Telemetria mala")
    pt.fijar(t, True)
    for malo in ({"tipo": "otro", "ruta": "/portal/"}, {"tipo": "carga", "ruta": "/portal/", "ms": "mucho"}, {"tipo": "carga", "ruta": "/fuera", "ms": 5}, "texto", None, {"tipo": "carga", "ms": 5}):
        assert pt.registrar(t, malo) is False
    assert pt.registrar(t, {"tipo": "carga", "ruta": "/portal/", "ms": 999999999}) is True and pt.resumen(t)["pantallas"][0]["max_ms"] == pt.MAX_MS
    pt.registrar(t, {"tipo": "carga", "ruta": "/portal/vieja", "ms": 100}, dia=date.today() - timedelta(days=40))
    pt.registrar(t, {"tipo": "carga", "ruta": "/portal/", "ms": 100})                                            # al escribir se borra lo de más de 30 días
    assert all(p["ruta"] != "/portal/vieja" for p in pt.resumen(t, dias=60)["pantallas"])


def test_la_pagina_del_portal_solo_incluye_el_medidor_si_esta_encendida_y_el_endpoint_responde_204(cliente, correo):
    t, u, c = _despacho("Telemetria web")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "portal-telemetria" not in _html(cliente, "/portal/")
    pt.fijar(t, True)
    assert 'name="portal-telemetria"' in _html(cliente, "/portal/")
    assert cliente.post("/portal/telemetria", json={"tipo": "carga", "ruta": "/portal/cuenta", "ms": 450}).status_code == 204
    assert pt.resumen(t)["pantallas"][0]["ruta"] == "/portal/cuenta" and cliente.post("/portal/telemetria", data="no es json").status_code == 204
    pt.fijar(t, False)
    cliente.post("/portal/telemetria", json={"tipo": "carga", "ruta": "/portal/otra", "ms": 1})
    assert all(p["ruta"] != "/portal/otra" for p in pt.resumen(t)["pantallas"])


def test_el_equipo_lo_enciende_y_ve_las_pantallas_lentas_y_los_errores(cliente):
    uid, t, c = _web(cliente, email="telemetria-equipo@ejemplo.com")
    html = cliente.get("/fiscal/portal-adopcion").get_data(as_text=True)
    assert "Salud del portal" in html and "Tiempo de carga" not in html
    cliente.post("/fiscal/portal-adopcion/salud", data={"activo": "1"})
    pt.registrar(t, {"tipo": "carga", "ruta": "/portal/impuestos", "ms": 4200})
    pt.registrar(t, {"tipo": "error", "ruta": "/portal/impuestos", "mensaje": "boom"})
    html = cliente.get("/fiscal/portal-adopcion").get_data(as_text=True)
    assert "Tiempo de carga" in html and "/portal/impuestos" in html and "4200 ms" in html and "boom" in html
