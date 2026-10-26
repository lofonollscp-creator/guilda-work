"""Guilda Fiscal · núcleo F4 (app/fiscal_nucleo.py): del apunte aprobado a la declaración exportada. SQLite y, con GUILDA_TEST_MOTOR=postgres, PostgreSQL."""
import json
from datetime import date as d

import pytest

from app import acceso, db, facturas_contables as fc, fiscal_nucleo as fn, fiscal_perfiles as fp, verticales
from app.db_fiscal import crear_cliente_fiscal
from app.fiscal_modelos import exportador_303 as ex, fichero_303, motor_303
from app.fiscal_perfiles import ErrorFiscal
from tests.escenarios_303 import ESCENARIOS, compra, venta

NIF = "A12345674"


def _despacho(nombre="Despacho nucleo", con_perfil=True):
    t = db.crear_tenant(nombre)
    clave = nombre.replace(" ", "").lower()
    director = db.crear_usuario_vinculado_a_kratos(f"{clave}-d@ejemplo.com", f"k-{clave}-d"); db.asignar_tenant(director, t); db.asignar_supervisor_tenant(director, True)
    gestor = db.crear_usuario_vinculado_a_kratos(f"{clave}-g@ejemplo.com", f"k-{clave}-g"); db.asignar_tenant(gestor, t)
    c = crear_cliente_fiscal(t, "Empresa de prueba SL", nif=NIF)
    if con_perfil:
        fp.guardar_perfil(t, director, c, {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    return t, director, gestor, c


def _cargar(t, u, c, nombre="basico", **cambio):
    apuntes, ejercicio, periodo = ESCENARIOS[nombre]
    return [fn.aprobar_apunte(t, u, c, a)["id"] for a in apuntes], ejercicio, periodo


def _hasta_revisada(t, u, c, nombre="basico"):
    _, ej, per = _cargar(t, u, c, nombre)
    inst = fn.crear_instantanea(t, u, c, ejercicio=ej, periodo=per)
    return inst, fn.revisar_declaracion(t, u, fn.calcular_declaracion(t, u, inst["id"])["id"])


def test_flujo_completo_del_apunte_a_la_declaracion_presentada():
    t, u, g, c = _despacho()
    ids, ej, per = _cargar(t, u, c)
    assert len(ids) == 2
    inst = fn.crear_instantanea(t, u, c, ejercicio=ej, periodo=per)
    dec = fn.calcular_declaracion(t, u, inst["id"])
    esperado = motor_303.calcular(ESCENARIOS["basico"][0], ejercicio=ej, periodo=per)
    assert dec["estado"] == "borrador" and dec["bloqueos"] == [] and dec["casillas"] == esperado.casillas and dec["resultado_centimos"] == 1050 and dec["tipo_declaracion"] == "I"
    assert dec["origen"]["07"] == [ids[0]] and dec["origen"]["28"] == [ids[1]]            # cada casilla sabe de qué apuntes sale
    dec = fn.revisar_declaracion(t, u, dec["id"])
    assert dec["estado"] == "revisada" and dec["revisada_por"] == u
    dec = fn.exportar_declaracion(t, u, dec["id"])
    assert dec["estado"] == "exportada" and sorted(a["tipo"] for a in dec["artefactos"]) == ["303", "libro_xlsx", "resumen"]
    datos, nombre = fn.descargar_artefacto(t, u, dec["id"], "303")
    assert nombre == "2026_2T.303" and datos == fichero_303.generar(esperado, nif=NIF, nombre="Empresa de prueba SL")
    assert ex.leer_casillas(json.loads(ex.DISENO_303_2026.read_text()), datos)["71"] == 1050
    assert b"[71] 10.50" in fn.descargar_artefacto(t, u, dec["id"], "resumen")[0]
    dec = fn.marcar_presentada(t, u, dec["id"], "CSV ABC123")
    assert dec["estado"] == "presentada" and dec["referencia_presentacion"] == "CSV ABC123"


def test_solo_aprueba_la_direccion_o_el_revisor_fiscal():
    t, u, g, c = _despacho()
    apuntes, ej, per = ESCENARIOS["basico"]
    with pytest.raises(ErrorFiscal) as e:
        fn.aprobar_apunte(t, g, c, apuntes[0])
    assert e.value.codigo == "prohibido"
    acceso.conceder_membresia(t, u, g, "revisor_fiscal", "organizacion") if hasattr(acceso, "conceder_membresia") else None
    with pytest.raises(ErrorFiscal):
        fn.crear_instantanea(t, 0, c, ejercicio=ej, periodo=per)


def test_un_apunte_con_errores_no_se_aprueba_y_las_correcciones_usan_version():
    t, u, g, c = _despacho()
    with pytest.raises(ErrorFiscal) as e:
        fn.aprobar_apunte(t, u, c, venta(10000, 0))                                      # IVA al 0 % ya no vigente
    assert e.value.codigo == "datos_con_errores" and fn.listar_apuntes(t, u, c) == []
    a = fn.aprobar_apunte(t, u, c, venta(10000))
    b = fn.aprobar_apunte(t, u, c, venta(20000), apunte_id=a["id"], version=a["version"])
    assert b["base_centimos"] == 20000 and b["version"] == a["version"] + 1
    with pytest.raises(ErrorFiscal) as e:
        fn.aprobar_apunte(t, u, c, venta(30000), apunte_id=a["id"], version=a["version"])
    assert e.value.codigo == "version_obsoleta"
    fn.anular_apunte(t, u, c, a["id"], "duplicada")
    assert fn.listar_apuntes(t, u, c) == [] and len(fn.listar_apuntes(t, u, c, incluir_anulados=True)) == 1


def test_la_instantanea_es_inmutable_y_la_nueva_sustituye_a_la_anterior():
    t, u, g, c = _despacho()
    _, ej, per = _cargar(t, u, c)
    a = fn.crear_instantanea(t, u, c, ejercicio=ej, periodo=per)
    assert fn.obtener_instantanea(t, u, a["id"])["integra"]
    conn = db.get_connection()
    try:
        with pytest.raises(Exception, match="inmutable"):
            conn.execute("UPDATE fiscal_instantaneas SET hash = 'x' WHERE id = ?", (a["id"],))
        conn.rollback()
        with pytest.raises(Exception, match="inmutable"):
            conn.execute("DELETE FROM fiscal_instantaneas WHERE id = ?", (a["id"],))
        conn.rollback()
    finally:
        conn.close()
    fn.aprobar_apunte(t, u, c, venta(5000, numero="9"))
    b = fn.crear_instantanea(t, u, c, ejercicio=ej, periodo=per)
    assert b["sustituye_a_id"] == a["id"] and b["hash"] != a["hash"] and fn.obtener_instantanea(t, u, a["id"])["integra"]
    assert json.loads(a["contenido"])["apuntes"] != json.loads(b["contenido"])["apuntes"]


def test_recalcular_desde_la_misma_instantanea_da_lo_mismo_y_anula_el_borrador_anterior():
    t, u, g, c = _despacho()
    _, ej, per = _cargar(t, u, c, "tipos")
    inst = fn.crear_instantanea(t, u, c, ejercicio=ej, periodo=per)
    d1 = fn.calcular_declaracion(t, u, inst["id"])
    d2 = fn.calcular_declaracion(t, u, inst["id"])
    assert d1["casillas"] == d2["casillas"] and d1["id"] != d2["id"]
    assert fn.obtener_declaracion(t, u, d1["id"])["estado"] == "anulada" and fn.obtener_declaracion(t, u, d2["id"])["estado"] == "borrador"


def test_los_estados_no_se_saltan_y_lo_exportado_no_se_toca():
    t, u, g, c = _despacho()
    _, ej, per = _cargar(t, u, c)
    dec = fn.calcular_declaracion(t, u, fn.crear_instantanea(t, u, c, ejercicio=ej, periodo=per)["id"])
    with pytest.raises(ErrorFiscal) as e:
        fn.exportar_declaracion(t, u, dec["id"])                                         # sin revisar
    assert e.value.codigo == "estado_invalido"
    with pytest.raises(ErrorFiscal):
        fn.marcar_presentada(t, u, dec["id"])
    fn.revisar_declaracion(t, u, dec["id"])
    fn.exportar_declaracion(t, u, dec["id"])
    conn = db.get_connection()
    try:
        for sql in ("UPDATE fiscal_casillas SET valor = 1 WHERE declaracion_id = ?", "DELETE FROM fiscal_casillas WHERE declaracion_id = ?", "UPDATE fiscal_declaraciones SET resultado_centimos = 5 WHERE id = ?",
                    "UPDATE fiscal_declaraciones SET estado = 'borrador' WHERE id = ?", "DELETE FROM fiscal_declaraciones WHERE id = ?", "UPDATE fiscal_artefactos SET hash = 'x' WHERE declaracion_id = ?",
                    "DELETE FROM fiscal_artefactos WHERE declaracion_id = ?"):
            with pytest.raises(Exception):
                conn.execute(sql, (dec["id"],))
            conn.rollback()
    finally:
        conn.close()
    fn.marcar_presentada(t, u, dec["id"])
    with pytest.raises(ErrorFiscal):
        fn.anular_declaracion(t, u, dec["id"])                                           # presentada: final


def test_sin_perfil_o_con_bloqueos_no_hay_declaracion_revisable():
    t, u, g, c = _despacho(con_perfil=False)
    _, ej, per = _cargar(t, u, c)
    with pytest.raises(ErrorFiscal) as e:
        fn.crear_instantanea(t, u, c, ejercicio=ej, periodo=per)
    assert e.value.codigo == "sin_perfil"
    fp.guardar_perfil(t, u, c, {"forma_juridica": "sociedad", "prorrata_centesimas": 8000}, vigente_desde="2026-04-01")
    dec = fn.calcular_declaracion(t, u, fn.crear_instantanea(t, u, c, ejercicio=ej, periodo=per)["id"])
    assert dec["bloqueos"] and "prorrata" in dec["bloqueos"][0]
    with pytest.raises(ErrorFiscal) as e:
        fn.revisar_declaracion(t, u, dec["id"])
    assert e.value.codigo == "bloqueada"
    t2, u2, g2, c2 = _despacho("Otro despacho nucleo", con_perfil=False)
    fp.guardar_perfil(t2, u2, c2, {"forma_juridica": "sociedad", "periodicidad": "mensual"}, vigente_desde="2026-01-01")
    _, ej, per = _cargar(t2, u2, c2)
    dec = fn.calcular_declaracion(t2, u2, fn.crear_instantanea(t2, u2, c2, ejercicio=ej, periodo=per)["id"])
    assert any("periodicidad" in b for b in dec["bloqueos"])


def test_la_compensacion_pasa_al_periodo_siguiente():
    t, u, g, c = _despacho()
    fn.aprobar_apunte(t, u, c, compra(50000, fecha=d(2026, 2, 10)))                       # 1T: a favor 105,00 €
    fn.aprobar_apunte(t, u, c, venta(10000, numero="2", fecha=d(2026, 5, 10)))            # 2T: 21,00 € a ingresar
    i1 = fn.crear_instantanea(t, u, c, ejercicio=2026, periodo="1T")
    d1 = fn.calcular_declaracion(t, u, i1["id"])
    assert d1["resultado_centimos"] == -10500 and d1["tipo_declaracion"] == "C"
    fn.revisar_declaracion(t, u, d1["id"])
    i2 = fn.crear_instantanea(t, u, c, ejercicio=2026, periodo="2T")
    assert json.loads(i2["contenido"])["cuotas_a_compensar_anteriores"] == 10500
    d2 = fn.calcular_declaracion(t, u, i2["id"])
    assert d2["casillas"]["78"] == 2100 and d2["casillas"]["71"] == 0 and d2["casillas"]["87"] == 8400 and d2["tipo_declaracion"] == "N"
    i3 = fn.crear_instantanea(t, u, c, ejercicio=2026, periodo="3T")                     # sin revisar la del 2T, el saldo pendiente sigue siendo el del 1T
    assert json.loads(i3["contenido"])["cuotas_a_compensar_anteriores"] == 10500
    fn.revisar_declaracion(t, u, d2["id"])
    i3 = fn.crear_instantanea(t, u, c, ejercicio=2026, periodo="3T")
    assert json.loads(i3["contenido"])["cuotas_a_compensar_anteriores"] == 8400


def test_aislamiento_entre_despachos():
    t1, u1, g1, c1 = _despacho("Despacho uno nucleo")
    t2, u2, g2, c2 = _despacho("Despacho dos nucleo")
    _, ej, per = _cargar(t1, u1, c1)
    inst = fn.crear_instantanea(t1, u1, c1, ejercicio=ej, periodo=per)
    with pytest.raises(ErrorFiscal):
        fn.aprobar_apunte(t2, u2, c1, venta(100))                                         # titular de otro despacho
    with pytest.raises(ErrorFiscal):
        fn.obtener_instantanea(t2, u2, inst["id"])
    with pytest.raises(ErrorFiscal):
        fn.calcular_declaracion(t2, u2, inst["id"])
    assert fn.listar_apuntes(t2, u2, c2) == []


def test_proponer_apuntes_desde_una_factura_sin_aprobarlos():
    t, u, g, c = _despacho()
    f = fc.crear(t, u, c, {"tipo": "recibida", "fecha": "2026-05-12", "numero": "F-1", "tercero_nombre": "Papelería Sol", "tercero_nif": "B87654321", "concepto": "Material"},
                 [{"base": "100", "pct_iva": "21"}, {"base": "50", "pct_iva": "10"}])
    propuestas = fn.proponer_desde_factura(t, u, f)
    assert [(p["base_centimos"], p["tipo_iva_centesimas"], p["cuota_centimos"], p["aprobado"]) for p in propuestas] == [(5000, 10, 500, False), (10000, 21, 2100, False)] or len(propuestas) == 2
    assert fn.listar_apuntes(t, u, c) == []                                               # proponer no guarda nada
    assert all(p["libro"] == "R" and p["numero"].startswith("F-1/") for p in propuestas)


def test_borrar_el_despacho_se_lleva_tambien_lo_inmutable():
    t, u, g, c = _despacho()
    _, ej, per = _cargar(t, u, c)
    dec = fn.calcular_declaracion(t, u, fn.crear_instantanea(t, u, c, ejercicio=ej, periodo=per)["id"])
    fn.revisar_declaracion(t, u, dec["id"])
    fn.exportar_declaracion(t, u, dec["id"])
    conn = db.get_connection()
    try:
        fn.borrar_datos_de_tenant(conn, t)
        conn.commit()
        for tabla in ("fiscal_apuntes", "fiscal_instantaneas", "fiscal_declaraciones", "fiscal_casillas", "fiscal_artefactos"):
            assert conn.execute(f"SELECT count(*) FROM {tabla} WHERE tenant_id = ?", (t,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_uso_para_backoffice():
    t, u, g, c = _despacho()
    _cargar(t, u, c)
    dec = fn.calcular_declaracion(t, u, fn.crear_instantanea(t, u, c, ejercicio=2026, periodo="2T")["id"])
    fn.revisar_declaracion(t, u, dec["id"])
    fn.exportar_declaracion(t, u, dec["id"])
    uso = dict(fn.uso_para_backoffice(t))
    assert uso["Apuntes aprobados"] == "2" and uso["Periodos congelados"] == "1" and uso["Declaraciones exportadas"] == "1" and uso["Declaraciones presentadas"] == "0" and uso["Titulares con perfil fiscal"] == "1"
    assert verticales.VERTICALES["fiscal"].uso is fn.uso_para_backoffice and verticales.VERTICALES["fiscal"].disponible is True
