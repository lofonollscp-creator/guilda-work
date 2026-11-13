"""Topes de IA por función (AD7): una función agotada no bloquea a las demás, y el consumo se cuenta por función."""
import pytest

from app import db, ia_consumo
from tests.test_api_fiscal import _despacho


def test_el_tope_de_una_funcion_no_bloquea_otra(cliente):
    h, uid, tenant = _despacho(cliente, "topes1@ejemplo.com")
    ia_consumo.fijar_tope_funcion(tenant, "facturas", 2)
    ia_consumo.reservar(uid, funcion="facturas")
    ia_consumo.reservar(uid, funcion="facturas")
    with pytest.raises(ia_consumo.LimiteIA, match="Lectura de facturas"):
        ia_consumo.reservar(uid, funcion="facturas")
    ia_consumo.reservar(uid, funcion="asistente")            # otras funciones siguen
    estado = {f["funcion"]: f for f in ia_consumo.estado_funciones(tenant)}
    assert estado["facturas"]["usadas"] == 2 and estado["facturas"]["limite"] == 2
    assert estado["asistente"]["usadas"] == 1 and estado["asistente"]["limite"] is None
    assert ia_consumo.estado(tenant)["usadas"] == 3          # y el general cuenta las tres


def test_sin_tope_propio_solo_cuenta_y_quitar_el_tope_lo_libera(cliente):
    h, uid, tenant = _despacho(cliente, "topes2@ejemplo.com")
    ia_consumo.fijar_tope_funcion(tenant, "correo", 0)
    with pytest.raises(ia_consumo.LimiteIA):
        ia_consumo.reservar(uid, funcion="correo")
    ia_consumo.fijar_tope_funcion(tenant, "correo", None)
    ia_consumo.reservar(uid, funcion="correo")
    with pytest.raises(ValueError):
        ia_consumo.fijar_tope_funcion(tenant, "inventada", 3)
