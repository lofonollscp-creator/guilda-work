"""Motor del 303 (app/fiscal_modelos/motor_303.py) contra la AEAT: cada escenario de tests/escenarios_303.py se subió como libro al simulador público y su resultado quedó grabado;
aquí el motor debe dar EXACTAMENTE las mismas casillas (sin red). Para regrabar: scripts/fiscal/grabar_oraculo.py --forzar."""
import json
from datetime import date as d
from pathlib import Path

import pytest

from app.fiscal_modelos import exportador_303 as ex
from app.fiscal_modelos import motor_303 as m
from app.fiscal_modelos.apuntes import Apunte
from app.fiscal_modelos.disenos_oficiales import indice_casillas
from tests.escenarios_303 import ESCENARIOS, compra, venta

ORACULO = Path(__file__).resolve().parent / "fixtures" / "aeat" / "oraculo_libros"
DISENO = json.loads(ex.DISENO_303_2026.read_text(encoding="utf-8"))
# los «tipo %» (02, 05, 08, 157…) los rellena el formulario solo; el 65 (% atribuible al Estado) sí es resultado del cálculo
TIPOS_PORCENTAJE = {k for k, v in indice_casillas(DISENO).items() if v[0]["lon"] == 5} - {"65"}


def _sin_porcentajes(casillas: dict[str, int]) -> dict[str, int]:
    return {k: v for k, v in casillas.items() if k not in TIPOS_PORCENTAJE and v}


def _grabados():
    return sorted(p.stem for p in ORACULO.glob("*.json"))


def test_todos_los_escenarios_tienen_su_resultado_de_la_aeat_grabado():
    assert set(ESCENARIOS) <= set(_grabados()), f"faltan por grabar: {sorted(set(ESCENARIOS) - set(_grabados()))} (scripts/fiscal/grabar_oraculo.py)"


@pytest.mark.parametrize("nombre", sorted(ESCENARIOS))
def test_el_motor_da_las_mismas_casillas_que_la_aeat(nombre):
    f = ORACULO / f"{nombre}.json"
    if not f.exists():
        pytest.skip("sin grabar")
    apuntes, ejercicio, periodo = ESCENARIOS[nombre]
    esperado = json.loads(f.read_text())
    r = m.calcular(apuntes, ejercicio=ejercicio, periodo=periodo)
    assert r.calculable, r.bloqueos
    mio, aeat = _sin_porcentajes(r.casillas), _sin_porcentajes(esperado["casillas"])
    # el motor también calcula el 87 y el 110 (compensación), que el libro no trae: se comparan solo las que la AEAT calcula
    mio = {k: v for k, v in mio.items() if k in aeat or k not in ("78", "87", "110")}
    assert mio == aeat, f"{nombre}: diferencias {sorted(set(mio.items()) ^ set(aeat.items()))}"


# --- Reglas sin red ------------------------------------------------------------------------------------------------------------------------

def test_redondeo_mitad_hacia_arriba():
    assert m._redondear(5, 10) == 1 and m._redondear(4, 10) == 0 and m._redondear(-5, 10) == -1 and m._redondear(15, 10) == 2


def test_lo_no_soportado_se_bloquea_en_vez_de_inventar():
    r = m.calcular([venta(10000, 700)], ejercicio=2026, periodo="2T")                     # IVA al 7 %: no existe
    assert not r.calculable and "7" in r.bloqueos[0]
    r = m.calcular([venta(10000, clave="07")], ejercicio=2026, periodo="2T")              # criterio de caja
    assert not r.calculable
    r = m.calcular([compra(10000, cuota_deducible=500)], ejercicio=2026, periodo="2T")    # deducción parcial
    assert not r.calculable and "parcial" in r.bloqueos[0]
    for ajuste in ({"prorrata": True}, {"tributacion_foral": True}, {"criterio_caja": True}, {"regimen_simplificado": True}, {"recargo_equivalencia": True}):
        assert not m.calcular([], ejercicio=2026, periodo="2T", **ajuste).calculable


def test_un_apunte_de_otro_periodo_no_cuenta_y_trazabilidad_de_cada_casilla():
    ap = [venta(10000), venta(9999, numero="2", fecha=d(2026, 8, 1)), compra(5000)]
    r = m.calcular(ap, ejercicio=2026, periodo="2T")
    assert r.casillas["07"] == 10000 and r.casillas["28"] == 5000 and r.casillas["71"] == 1050
    assert r.origen["07"] == [0] and r.origen["28"] == [2]


def test_compensacion_de_periodos_anteriores():
    r = m.calcular([venta(10000)], ejercicio=2026, periodo="2T", cuotas_a_compensar_anteriores=1500)
    assert r.casillas["66"] == 2100 and r.casillas["78"] == 1500 and r.casillas["69"] == 600 and r.casillas.get("87", 0) == 0 and r.tipo_declaracion == "I"
    r = m.calcular([venta(1000)], ejercicio=2026, periodo="2T", cuotas_a_compensar_anteriores=5000)    # solo se aplica hasta la cuota del periodo
    assert r.casillas["78"] == 210 and r.casillas["87"] == 4790 and r.casillas["71"] == 0 and r.tipo_declaracion == "N"


def test_tipo_de_declaracion():
    assert m.calcular([], ejercicio=2026, periodo="2T").tipo_declaracion == "N"
    assert m.calcular([venta(1000)], ejercicio=2026, periodo="2T").tipo_declaracion == "I"
    assert m.calcular([compra(5000)], ejercicio=2026, periodo="2T").tipo_declaracion == "C"             # a favor: por defecto se compensa (como el simulador al elegir «a compensar»)
    assert m.calcular([compra(5000)], ejercicio=2026, periodo="2T", destino_negativo="D").tipo_declaracion == "D"
    with pytest.raises(m.ErrorDeCalculo):
        m.calcular([compra(5000)], ejercicio=2026, periodo="2T", destino_negativo="X")


def test_periodo_no_valido():
    with pytest.raises(m.ErrorDeCalculo):
        m.calcular([], ejercicio=2026, periodo="5T")


# --- Del motor al fichero .303 ---------------------------------------------------------------------------------------------------------------------

from app.fiscal_modelos import fichero_303 as f3  # noqa: E402


def test_el_fichero_generado_lleva_las_casillas_del_motor_y_nada_mas():
    apuntes, ejercicio, periodo = ESCENARIOS["tipos"]
    r = m.calcular(apuntes, ejercicio=ejercicio, periodo=periodo)
    datos = f3.generar(r, nif="A12345674", nombre="EMPRESA DE PRUEBA SL")
    leidas = ex.leer_casillas(DISENO, datos)
    esperadas = {k: v for k, v in r.casillas.items() if k not in ("110", "78", "87") or v}
    assert {k: v for k, v in leidas.items() if k not in TIPOS_PORCENTAJE} == {k: v for k, v in esperadas.items() if v}
    assert datos.startswith(b"<T303020262T0000>") and datos.endswith(b"</T303020262T0000>") and b"\n" not in datos


@pytest.mark.parametrize("nombre", sorted(ESCENARIOS))
def test_nuestro_fichero_es_el_que_exporta_la_aeat_salvo_identificacion_y_programa(nombre):
    exportado = ORACULO / f"{nombre}.303"
    if not exportado.exists():
        pytest.skip("sin grabar el .303 de la AEAT")
    apuntes, ejercicio, periodo = ESCENARIOS[nombre]
    r = m.calcular(apuntes, ejercicio=ejercicio, periodo=periodo)
    if periodo in ex.ULTIMOS:
        pytest.skip("último periodo")
    mio = f3.generar(r, nif="A12345674", nombre="EMPRESA DE PRUEBA SL")
    aeat = exportado.read_bytes()
    assert len(mio) == len(aeat)
    # solo puede cambiar lo que identifica al programa (reservado, versión y NIF de la entidad desarrolladora: 8, 9 y 11) y la zona «reservada para la AEAT» de la página 3 (37), que ella rellena
    distintos = {(h, n) for h, n, _ in ex.campos_distintos(DISENO, mio, aeat)}
    assert distintos <= {("DP30300", 8), ("DP30300", 9), ("DP30300", 11), ("DP30303", 37)}, distintos


def test_el_ultimo_periodo_se_genera_salvo_que_este_exonerado_del_390_sin_volumen():
    r = m.calcular([venta(10000, fecha=d(2026, 11, 2))], ejercicio=2026, periodo="4T")
    assert f3.generar(r, nif="A12345674", nombre="X").startswith(b"<T303020264T0000>")
    with pytest.raises(f3.FicheroNoGenerable):                                  # exonerado del 390: necesita el volumen de operaciones del año
        f3.generar(r, nif="A12345674", nombre="X", exonerado_390=True)
    with pytest.raises(f3.FicheroNoGenerable):
        f3.generar(m.calcular([venta(10000, 700)], ejercicio=2026, periodo="2T"), nif="A12345674", nombre="X")


def test_periodo_mensual():
    ap = [venta(10000, fecha=d(2026, 5, 4)), compra(2000, fecha=d(2026, 5, 20)), venta(9000, numero="2", fecha=d(2026, 6, 4))]
    r = m.calcular(ap, ejercicio=2026, periodo="05")
    assert r.casillas["07"] == 10000 and r.casillas["28"] == 2000 and r.casillas["71"] == 2100 - 420
    assert m.calcular(ap, ejercicio=2026, periodo="06").casillas["07"] == 9000


# --- En línea (opcional): lo que genera el motor lo acepta el simulador ------------------------------------------------------------------------

import importlib.util  # noqa: E402
import os  # noqa: E402

_ONLINE = os.environ.get("GUILDA_FISCAL_SIMULADOR") == "1" and importlib.util.find_spec("playwright") is not None


@pytest.mark.skipif(not _ONLINE, reason="prueba en línea contra el simulador público de la AEAT: GUILDA_FISCAL_SIMULADOR=1 y Playwright")
@pytest.mark.parametrize("nombre", ["basico", "rectificativas", "adquisicion_intracomunitaria"])
def test_el_simulador_acepta_el_fichero_del_motor_y_calcula_lo_mismo(nombre, tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "fiscal"))
    import simulador_aeat
    apuntes, ejercicio, periodo = ESCENARIOS[nombre]
    r = m.calcular(apuntes, ejercicio=ejercicio, periodo=periodo)
    fichero = tmp_path / f"{nombre}.303"
    fichero.write_bytes(f3.generar(r, nif="A12345674", nombre="EMPRESA DE PRUEBA SL"))
    res = simulador_aeat.probar(fichero, ejercicio=ejercicio)
    assert not res["importacion"]["rechazado"], res["importacion"]
    assert not [x for x in res["validacion"] if x["codigo"].startswith("E")], res["validacion"]
    esperado = json.loads((ORACULO / f"{nombre}.json").read_text())["resultado"]
    assert res["resultado"] == esperado
