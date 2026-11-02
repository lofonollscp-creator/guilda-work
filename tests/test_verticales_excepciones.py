"""Excepciones al plan de un despacho (app/verticales.py): motivo obligatorio, prueba con caducidad, vuelta al plan e historial."""
from datetime import date, timedelta

import pytest

from app import db, verticales


def _despacho():
    return db.crear_tenant("Despacho Excepciones")


def test_la_excepcion_exige_motivo_y_queda_en_el_historial():
    t = _despacho()
    with pytest.raises(ValueError, match="motivo"):
        verticales.fijar_activo(t, "abogados", True, motivo=" ", por="jorge")
    assert not verticales.esta_activo(t, "abogados") and verticales.historial_de(t) == []
    verticales.fijar_activo(t, "abogados", True, motivo="Piloto con el cliente", por="jorge")
    assert verticales.esta_activo(t, "abogados")
    h = verticales.historial_de(t)
    assert [(x["accion"], x["motivo"], x["por"]) for x in h] == [("activar", "Piloto con el cliente", "jorge")]
    estado = next(e for e in verticales.estado_para_backoffice(t) if e["id"] == "abogados")
    assert estado["motivo"] == "manual" and estado["excepcion_motivo"] == "Piloto con el cliente" and estado["excepcion_por"] == "jorge" and not estado["caducada"]


def test_prueba_de_dias_caduca_sola_y_se_puede_volver_al_plan():
    t = _despacho()
    hasta = verticales.prueba_de_dias(t, "abogados", 30, motivo="Prueba de 30 días", por="jorge")
    assert hasta == (date.today() + timedelta(days=30)).isoformat() and verticales.esta_activo(t, "abogados")
    assert verticales.historial_de(t)[0]["accion"] == "prueba" and verticales.historial_de(t)[0]["activo_hasta"] == hasta
    futuro = (date.today() + timedelta(days=31)).isoformat() + "T00:00:00"
    assert "abogados" not in verticales.activos_de(t, ahora=futuro, usar_cache=False)          # pasada la fecha, vuelve al plan sin que nadie haga nada
    with pytest.raises(ValueError, match="1 a 365"):
        verticales.prueba_de_dias(t, "abogados", 0, motivo="x" * 5, por="jorge")
    verticales.quitar_ajuste_manual(t, "abogados", motivo="Acabó el piloto", por="jorge")
    assert not verticales.esta_activo(t, "abogados")
    assert [x["accion"] for x in verticales.historial_de(t)] == ["volver_al_plan", "prueba"]
    with pytest.raises(ValueError):
        verticales.fijar_activo(t, "astrologia", True, motivo="no existe", por="jorge")


def test_cada_despacho_tiene_su_historial():
    a, b = _despacho(), db.crear_tenant("Otro despacho")
    verticales.fijar_activo(a, "abogados", True, motivo="Para A", por="jorge")
    assert len(verticales.historial_de(a)) == 1 and verticales.historial_de(b) == []
