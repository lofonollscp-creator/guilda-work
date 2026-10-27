"""Rectificativa del 303: la regla de las casillas 70, 109 y 111 según las instrucciones oficiales, el bloque «Rectificativa» del fichero y el camino completo desde un 303 presentado."""
import json

import pytest

from app import db, fiscal_nucleo as fn, fiscal_perfiles as fp
from app.db_fiscal import crear_cliente_fiscal
from app.fiscal_modelos import exportador_303 as ex, fichero_303, motor_303
from app.fiscal_modelos.motor_303 import Resultado303
from tests.escenarios_303 import ESCENARIOS, compra, venta

NIF = "A12345674"
JUSTIFICANTE = "3030000000123"


def _r(c69):
    r = Resultado303(2026, "2T", casillas={"69": c69, "71": c69})
    return r


def test_primera_rectificativa_que_sigue_a_ingresar():
    r = _r(3150)
    motor_303.aplicar_rectificativa(r, {"69": 1050})
    assert r.casillas["70"] == 1050 and r.casillas["71"] == 2100 and "111" not in r.casillas and "109" not in r.casillas and r.tipo_declaracion == "I"


def test_la_rectificativa_que_pasa_a_favor_del_titular_lleva_la_casilla_111():
    r = _r(-3150)
    motor_303.aplicar_rectificativa(r, {"69": 1050}, destino_negativo="D")
    assert r.casillas["70"] == 1050 and r.casillas["71"] == -4200 and r.casillas["111"] == 1050 and r.tipo_declaracion == "D"
    # si lo que queda a favor no llega a lo que constaba a ingresar, la 111 es ese menor importe
    r = _r(400)
    motor_303.aplicar_rectificativa(r, {"69": 1050})
    assert r.casillas["71"] == -650 and r.casillas["111"] == 650 and r.tipo_declaracion == "C"


def test_la_rectificada_con_resultado_negativo_solo_lleva_la_109_si_la_devolucion_se_acordo():
    r = _r(200)
    motor_303.aplicar_rectificativa(r, {"69": -300})
    assert "70" not in r.casillas and "109" not in r.casillas and r.casillas["71"] == 200
    r = _r(200)
    motor_303.aplicar_rectificativa(r, {"69": -300}, devolucion_acordada=True)
    assert r.casillas["109"] == 300 and r.casillas["71"] == 500 and r.tipo_declaracion == "I"
    r = _r(0)
    motor_303.aplicar_rectificativa(r, {"69": 0})
    assert r.casillas["71"] == 0 and r.tipo_declaracion == "N"
    with pytest.raises(motor_303.ErrorDeCalculo):
        motor_303.aplicar_rectificativa(_r(-5), {"69": 0}, destino_negativo="X")


def test_el_fichero_de_una_rectificativa_lleva_el_bloque_del_diseno_oficial():
    diseno = json.loads(ex.DISENO_303_2026.read_text())
    r = _r(-3150)
    motor_303.aplicar_rectificativa(r, {"69": 1050})
    datos = fichero_303.generar(r, nif=NIF, nombre="Empresa SL", justificante_anterior=JUSTIFICANTE)
    pagina = next(p for p in ex.descomponer(diseno, datos)["paginas"] if p["hoja"] == "DP30303")["campos"]
    assert pagina[31] == "X" and pagina[32] == JUSTIFICANTE and pagina[35] == "X" and pagina[36] == " "
    casillas = ex.leer_casillas(diseno, datos)
    assert casillas["70"] == 1050 and casillas["111"] == 1050 and casillas["71"] == -4200
    normal = fichero_303.generar(_r(100), nif=NIF, nombre="Empresa SL")
    assert next(p for p in ex.descomponer(diseno, normal)["paginas"] if p["hoja"] == "DP30303")["campos"][31] == " "
    for malo in ("123", "30300000001AB", "30300000001234"):
        with pytest.raises(fichero_303.FicheroNoGenerable):
            fichero_303.generar(r, nif=NIF, nombre="Empresa SL", justificante_anterior=malo)


def _despacho(nombre="Despacho rectificativa"):
    t = db.crear_tenant(nombre)
    clave = nombre.replace(" ", "").lower()
    director = db.crear_usuario_vinculado_a_kratos(f"{clave}-d@ejemplo.com", f"k-{clave}-d"); db.asignar_tenant(director, t); db.asignar_supervisor_tenant(director, True)
    c = crear_cliente_fiscal(t, "Empresa de prueba SL", nif=NIF)
    fp.guardar_perfil(t, director, c, {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    return t, director, c


def _presentada(t, u, c):
    for a in ESCENARIOS["basico"][0]:
        fn.aprobar_apunte(t, u, c, a)
    inst = fn.crear_instantanea(t, u, c, ejercicio=2026, periodo="2T")
    dec = fn.calcular_declaracion(t, u, inst["id"])
    fn.revisar_declaracion(t, u, dec["id"])
    fn.exportar_declaracion(t, u, dec["id"])
    return fn.marcar_presentada(t, u, dec["id"], JUSTIFICANTE)


def test_de_un_303_presentado_a_su_rectificativa_presentada():
    t, u, c = _despacho()
    original = _presentada(t, u, c)
    assert original["resultado_centimos"] == 1050
    # el periodo presentado no se vuelve a calcular como si fuera el primero
    with pytest.raises(fn.ErrorFiscal) as e:
        fn.crear_instantanea(t, u, c, ejercicio=2026, periodo="2T")
    assert e.value.codigo == "periodo_presentado"
    # se descubre otra venta del trimestre
    fn.aprobar_apunte(t, u, c, venta(10000, numero="2"))
    with pytest.raises(fn.ErrorFiscal):
        fn.rectificar_declaracion(t, u, original["id"], justificante="123")
    rect = fn.rectificar_declaracion(t, u, original["id"], justificante=JUSTIFICANTE)
    assert rect["estado"] == "borrador" and rect["rectifica_a_id"] == original["id"] and rect["justificante_anterior"] == JUSTIFICANTE and rect["vencimiento_id"] is None
    assert rect["casillas"]["69"] == 3150 and rect["casillas"]["70"] == 1050 and rect["casillas"]["71"] == rect["resultado_centimos"] == 2100 and rect["tipo_declaracion"] == "I"
    # compara con la presentada, no con borradores intermedios
    cambios = fn.comparar_con_anterior(t, u, rect["id"])
    assert cambios["id"] == original["id"] and cambios["resultado_antes"] == 1050 and cambios["resultado_ahora"] == 2100
    # solo una rectificativa viva por declaración
    with pytest.raises(fn.ErrorFiscal) as e:
        fn.rectificar_declaracion(t, u, original["id"], justificante=JUSTIFICANTE)
    assert e.value.codigo == "ya_rectificada"
    fn.revisar_declaracion(t, u, rect["id"])
    exportada = fn.exportar_declaracion(t, u, rect["id"])
    fichero, _ = fn.descargar_artefacto(t, u, exportada["id"], "303")
    pagina = next(p for p in ex.descomponer(json.loads(ex.DISENO_303_2026.read_text()), fichero)["paginas"] if p["hoja"] == "DP30303")["campos"]
    assert pagina[31] == "X" and pagina[32] == JUSTIFICANTE
    assert b"RECTIFICATIVA" in fn.descargar_artefacto(t, u, exportada["id"], "resumen")[0]
    presentada = fn.marcar_presentada(t, u, rect["id"], "3030000000999")
    assert presentada["estado"] == "presentada"
    # una rectificativa no se rectifica otra vez
    with pytest.raises(fn.ErrorFiscal) as e:
        fn.rectificar_declaracion(t, u, rect["id"], justificante="3030000000999")
    assert e.value.codigo == "no_soportado"


def test_una_rectificativa_a_favor_del_titular_y_solo_se_rectifica_lo_presentado():
    t, u, c = _despacho("Despacho rectificativa 2")
    original = _presentada(t, u, c)
    fn.aprobar_apunte(t, u, c, compra(40000, numero="P-9"))                    # 8.400 de IVA soportado más: el trimestre queda a favor
    rect = fn.rectificar_declaracion(t, u, original["id"], justificante=JUSTIFICANTE, destino_negativo="D")
    assert rect["casillas"]["69"] == 1050 - 8400 and rect["casillas"]["70"] == 1050 and rect["casillas"]["111"] == 1050
    assert rect["casillas"]["71"] == rect["resultado_centimos"] == -7350 - 1050 and rect["tipo_declaracion"] == "D"
    # un borrador o una exportada sin presentar se anula y se recalcula: no se rectifica
    with pytest.raises(fn.ErrorFiscal) as e:
        fn.rectificar_declaracion(t, u, rect["id"], justificante=JUSTIFICANTE)
    assert e.value.codigo == "estado_invalido"


def test_la_compensacion_de_periodos_posteriores_cuenta_una_sola_declaracion_por_periodo():
    t, u, c = _despacho("Despacho rectificativa 3")
    for a in (venta(10000, fecha=__import__("datetime").date(2026, 2, 3)), compra(60000, numero="P-1", fecha=__import__("datetime").date(2026, 2, 4))):
        fn.aprobar_apunte(t, u, c, a)
    inst = fn.crear_instantanea(t, u, c, ejercicio=2026, periodo="1T")
    primera = fn.calcular_declaracion(t, u, inst["id"])                      # 2.100 - 12.600 = -10.500 a compensar
    assert primera["resultado_centimos"] == -10500
    fn.revisar_declaracion(t, u, primera["id"]); fn.exportar_declaracion(t, u, primera["id"]); fn.marcar_presentada(t, u, primera["id"], JUSTIFICANTE)
    rect = fn.rectificar_declaracion(t, u, primera["id"], justificante=JUSTIFICANTE)
    fn.revisar_declaracion(t, u, rect["id"])
    # con las dos (original y rectificativa) revisadas, el 2T parte de lo pendiente de UNA sola, no de la suma
    inst2 = fn.crear_instantanea(t, u, c, ejercicio=2026, periodo="2T")
    assert inst2["id"] and fn.obtener_instantanea(t, u, inst2["id"])["datos"]["cuotas_a_compensar_anteriores"] == 10500
