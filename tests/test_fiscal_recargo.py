"""Recargo de equivalencia repercutido en facturas emitidas: casillas 16 a 26 del 303, validación, libro de la AEAT y bloqueo del 390."""
from datetime import date

import pytest

from app.fiscal_modelos import libros_lsi, motor_303, motor_390, validacion_apuntes
from app.fiscal_modelos.apuntes import Apunte
from tests.escenarios_303 import compra, venta


def _re(base, tipo, rec, **kw):
    return venta(base, tipo, recargo_pct=rec, recargo_cuota=(base * rec + 5000) // 10000, **kw)


def test_el_recargo_va_en_su_bloque_con_la_base_repetida_y_suma_en_la_27():
    r = motor_303.calcular([_re(100000, 2100, 520)], ejercicio=2026, periodo="2T")
    assert r.calculable, r.bloqueos
    c = r.casillas
    assert c["07"] == 100000 and c["09"] == 21000 and c["22"] == 100000 and c["24"] == 5200 and c["27"] == 26200 and c["71"] == 26200


@pytest.mark.parametrize("tipo, rec, base_c, cuota_c", [(400, 50, "168", "170"), (1000, 140, "19", "21"), (2100, 520, "22", "24"), (2100, 175, "156", "158")])
def test_cada_recargo_va_a_sus_casillas(tipo, rec, base_c, cuota_c):
    r = motor_303.calcular([_re(20000, tipo, rec)], ejercicio=2026, periodo="2T")
    assert r.calculable and r.casillas[base_c] == 20000 and r.casillas[cuota_c] == (20000 * rec + 5000) // 10000


def test_un_recargo_sin_casilla_se_bloquea():
    r = motor_303.calcular([_re(10000, 2100, 140)], ejercicio=2026, periodo="2T")
    assert not r.calculable and any("no tiene casilla" in b for b in r.bloqueos)


def test_el_abono_con_recargo_va_a_las_casillas_25_y_26():
    abono = venta(-10000, 2100, numero="9", tipo_factura="R1", recargo_pct=520, recargo_cuota=-520)
    r = motor_303.calcular([_re(100000, 2100, 520), abono], ejercicio=2026, periodo="2T")
    assert r.casillas["25"] == -10000 and r.casillas["26"] == -520 and r.casillas["27"] == 21000 + 5200 - 2100 - 520


def test_la_validacion_del_recargo():
    ok = _re(10000, 2100, 520)
    assert not validacion_apuntes.errores(validacion_apuntes.validar_apunte(ok, hoy=date(2026, 12, 1)))
    malo = venta(10000, 2100, recargo_pct=520, recargo_cuota=999)
    assert any(e.codigo == "recargo_no_cuadra" for e in validacion_apuntes.errores(validacion_apuntes.validar_apunte(malo, hoy=date(2026, 12, 1))))
    sin_tipo = venta(10000, 2100, recargo_cuota=520)
    assert any(e.codigo == "recargo_sin_tipo" for e in validacion_apuntes.errores(validacion_apuntes.validar_apunte(sin_tipo, hoy=date(2026, 12, 1))))
    total_mal = venta(10000, 2100, recargo_pct=520, recargo_cuota=520, total=12100)
    assert any(e.codigo == "total_no_cuadra" for e in validacion_apuntes.errores(validacion_apuntes.validar_apunte(total_mal, hoy=date(2026, 12, 1))))
    assert not [e for e in validacion_apuntes.errores(validacion_apuntes.validar_apunte(venta(10000, 2100, recargo_pct=520, recargo_cuota=520, total=12620), hoy=date(2026, 12, 1)))]
    recibida = compra(10000, recargo_pct=520, recargo_cuota=520)
    assert any(e.codigo == "recargo_en_recibida" for e in validacion_apuntes.errores(validacion_apuntes.validar_apunte(recibida, hoy=date(2026, 12, 1))))
    n1 = Apunte("E", "F1", date(2026, 5, 1), base=10000, calificacion="N1", recargo_pct=520, recargo_cuota=520)
    assert any(e.codigo == "recargo_sin_sujecion" for e in validacion_apuntes.errores(validacion_apuntes.validar_apunte(n1, hoy=date(2026, 12, 1))))


def test_el_total_del_libro_incluye_el_recargo_y_se_lee_de_vuelta():
    a = _re(10000, 2100, 520)
    assert a.total_efectivo == 10000 + 2100 + 520
    contenido = libros_lsi.escribir_xlsx([a], ejercicio=2026, periodo="2T")
    leidos, ilegibles = libros_lsi.leer_xlsx(contenido)
    assert not ilegibles and leidos[0].recargo_pct == 520 and leidos[0].recargo_cuota == 520 and leidos[0].total_efectivo == 12620


def test_el_390_con_recargo_repercutido_se_bloquea():
    r = motor_390.calcular([_re(10000, 2100, 520, fecha=date(2026, 5, 10))], ejercicio=2026)
    assert not r.calculable and any("recargo de equivalencia" in b for b in r.bloqueos)


def _despacho(nombre="Despacho recargo"):
    from app import db, fiscal_perfiles as fp
    from app.db_fiscal import crear_cliente_fiscal
    t = db.crear_tenant(nombre)
    u = db.crear_usuario_vinculado_a_kratos("recargo@ejemplo.com", "k-recargo"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    c = crear_cliente_fiscal(t, "Mayorista SL", nif="A12345674")
    fp.guardar_perfil(t, u, c, {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    return t, u, c


def test_del_apunte_con_recargo_al_fichero_303():
    import json
    from app import fiscal_nucleo as fn
    from app.fiscal_modelos import exportador_303 as ex
    t, u, c = _despacho()
    ap = fn.aprobar_apunte(t, u, c, _re(100000, 2100, 520))
    fila = next(a for a in fn.listar_apuntes(t, u, c, ejercicio=2026) if a["id"] == ap["id"])
    assert fila["recargo_pct_centesimas"] == 520 and fila["recargo_cuota_centimos"] == 5200
    dec = fn.calcular_declaracion(t, u, fn.crear_instantanea(t, u, c, ejercicio=2026, periodo="2T")["id"])
    assert dec["bloqueos"] == [] and dec["casillas"]["24"] == 5200 and dec["casillas"]["27"] == 26200
    fn.revisar_declaracion(t, u, dec["id"])
    fn.exportar_declaracion(t, u, dec["id"])
    fichero, _ = fn.descargar_artefacto(t, u, dec["id"], "303")
    casillas = ex.leer_casillas(json.loads(ex.DISENO_303_2026.read_text()), fichero)
    assert casillas["22"] == 100000 and casillas["24"] == 5200 and casillas["27"] == 26200 and casillas["71"] == 26200
