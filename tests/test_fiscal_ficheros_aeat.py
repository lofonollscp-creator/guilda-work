"""Ficheros `.303` completos contra el simulador público de la AEAT (scripts/fiscal/grabar_ficheros_303.py): rectificativa, recargo de equivalencia, criterio de caja, prorrata general, resultado a compensar y
otros periodos. Cada uno se importó en el simulador, se validó («No existen errores») y se exportó de vuelta. Aquí, sin red: nuestro generador sigue produciendo EXACTAMENTE el mismo fichero que se probó, y ese
fichero difiere del que exporta la AEAT solo en los campos que son suyos (reservados, versión del programa y NIF de la entidad desarrolladora)."""
import json
from pathlib import Path

import pytest

from app.fiscal_modelos import exportador_303 as ex
from tests.escenarios_ficheros_303 import CASOS

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "aeat" / "ficheros_303"
DISENO = json.loads(ex.DISENO_303_2026.read_text(encoding="utf-8"))
DE_LA_AEAT = {("DP30300", 8), ("DP30300", 9), ("DP30300", 11), ("DP30303", 37)}       # reservado, versión del programa, NIF de la entidad desarrolladora, reservado de la página 3


def test_todos_los_ficheros_tienen_su_prueba_grabada():
    faltan = sorted(n for n in CASOS if not (FIXTURES / "aeat" / f"{n}.303").exists())
    assert not faltan, f"faltan por grabar: {faltan} (scripts/fiscal/grabar_ficheros_303.py)"


@pytest.mark.parametrize("nombre", sorted(CASOS))
def test_nuestro_fichero_es_el_que_la_aeat_acepto_y_solo_difiere_en_lo_suyo(nombre):
    nuestro = CASOS[nombre]()
    assert nuestro == (FIXTURES / "nuestro" / f"{nombre}.303").read_bytes(), "el generador cambió: vuelve a probar el fichero en el simulador y regraba"
    aeat = (FIXTURES / "aeat" / f"{nombre}.303").read_bytes()
    assert len(nuestro) == len(aeat) and b"\n" not in aeat
    assert {(h, n) for h, n, _d in ex.campos_distintos(DISENO, nuestro, aeat)} == DE_LA_AEAT


def test_lo_que_la_aeat_avisa_de_cada_fichero_queda_a_la_vista():
    """Solo avisos («revise…»), nunca errores; los que dependen del perfil (caja, recargo) están anotados."""
    for f in sorted(FIXTURES.glob("*.json")):
        datos = json.loads(f.read_text())
        assert all(a.startswith(("30", "31")) for a in datos["avisos"]), (f.name, datos["avisos"])
    assert any("recargo de equivalencia" in a for a in json.loads((FIXTURES / "recargo.json").read_text())["avisos"])
    assert any("criterio de Caja" in a for a in json.loads((FIXTURES / "caja.json").read_text())["avisos"])
