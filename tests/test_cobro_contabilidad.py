"""Cobro por uso de Facturas para contabilizar (app/cobro_contabilidad.py, límite mensual, liquidación y backoffice)."""
import pytest

from app import cobro_contabilidad as cc, db, facturas_contables as fc, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_backoffice_app import bo, entrar, post  # noqa: F401
from tests.test_facturas_contables import LINEA, PDF, _datos


def _despacho(nombre="Despacho cobro", plan=None, modulo=True):
    t = db.crear_tenant(nombre)
    u = db.crear_usuario_vinculado_a_kratos(f"{nombre.lower().replace(' ', '')}@ejemplo.com", f"k-{nombre}"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    if modulo:
        verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Cobro SL", nif="B12345678")
    fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8"})
    if plan:
        conn = db.get_connection(); conn.execute("UPDATE tenants SET plan_id = ? WHERE id = ?", (plan, t)); conn.commit(); conn.close()
    return t, u, c


def _plan(nombre="Plan Pro"):
    return db.crear_plan_guilda(nombre, None, 9900, 5)


def _facturas(t, u, c, n, desde=0):
    return [fc.crear(t, u, c, _datos(numero=f"F-{desde + i}"), [LINEA]) for i in range(n)]


@pytest.mark.parametrize("texto,esperado", [("0,10", 10), ("0.1", 10), ("1.234,56", 123456), ("", 0), (" 2 € ", 200), ("0,05", 5)])
def test_euros_a_centimos(texto, esperado):
    assert cc.euros_a_centimos(texto) == esperado


@pytest.mark.parametrize("texto", ["abc", "-1", "99999999"])
def test_euros_no_validos(texto):
    with pytest.raises(ValueError):
        cc.euros_a_centimos(texto)


# --- Tarifas ----------------------------------------------------------------------------------------------------------------------------------

def test_sin_tarifa_no_hay_cargo_ni_limite():
    t, u, c = _despacho()
    _facturas(t, u, c, 3)
    r = cc.consumo(t)
    assert r["tarifa"] is None and r["unidades"] == 3 and r["extra"] == 0 and r["importe_centimos"] == 0 and r["limite_duro"] is None
    cc.comprobar_cupo(t, 1000)


def test_la_tarifa_propia_gana_a_la_del_plan_y_esta_a_la_general():
    plan = _plan()
    t, u, c = _despacho(plan=plan)
    assert cc.tarifa_de(t) is None
    cc.guardar_tarifa("defecto", 0, "anotadas", 10, 20)
    assert cc.tarifa_de(t)["origen"] == "defecto" and cc.tarifa_de(t)["incluidas"] == 10
    cc.guardar_tarifa("plan", plan, "anotadas", 50, 10)
    assert cc.tarifa_de(t)["origen"] == "plan" and cc.tarifa_de(t)["incluidas"] == 50
    cc.guardar_tarifa("tenant", t, "exportadas", 5, 30)
    x = cc.tarifa_de(t)
    assert (x["origen"], x["unidad"], x["incluidas"]) == ("tenant", "exportadas", 5)
    t2, *_ = _despacho("Otro despacho cobro")
    assert cc.tarifa_de(t2)["origen"] == "defecto", "sin plan ni tarifa propia, la general"


@pytest.mark.parametrize("args,fragmento", [(("otro", 0, "anotadas", 0, 0), "ámbito"), (("plan", 0, "anotadas", 0, 0), "plan o el despacho"), (("defecto", 5, "anotadas", 0, 0), "plan o el despacho"),
                                            (("defecto", 0, "raras", 0, 0), "unidad"), (("defecto", 0, "anotadas", -1, 0), "incluidas"), (("defecto", 0, "anotadas", "x", 0), "números"),
                                            (("defecto", 0, "anotadas", 0, 99999999), "precio"), (("defecto", 0, "anotadas", 10, 0, 5), "menor"),
                                            (("defecto", 0, "exportadas", 10, 0, 50), "solo se puede poner"), (("plan", 99999, "anotadas", 0, 0), "no existe"),
                                            (("tenant", 99999, "anotadas", 0, 0), "no existe")])
def test_validaciones_de_la_tarifa(args, fragmento):
    with pytest.raises(ValueError, match=fragmento):
        cc.guardar_tarifa(*args)
    assert cc.listar_tarifas() == []


def test_guardar_otra_vez_sustituye_y_borrar_quita():
    cc.guardar_tarifa("defecto", 0, "anotadas", 10, 20)
    cc.guardar_tarifa("defecto", 0, "anotadas", 30, 5, 100)
    assert [(x["incluidas"], x["precio_extra_centimos"], x["limite_duro"]) for x in cc.listar_tarifas()] == [(30, 5, 100)]
    assert cc.borrar_tarifa("defecto", 0) is True and cc.borrar_tarifa("defecto", 0) is False and cc.listar_tarifas() == []


# --- Medición ---------------------------------------------------------------------------------------------------------------------------------

def test_se_cobra_lo_que_pasa_de_lo_incluido():
    t, u, c = _despacho()
    cc.guardar_tarifa("tenant", t, "anotadas", 3, 25)
    _facturas(t, u, c, 5)
    r = cc.consumo(t)
    assert (r["unidades"], r["incluidas"], r["extra"], r["precio_extra_centimos"], r["importe_centimos"]) == (5, 3, 2, 25, 50)


def test_dentro_de_lo_incluido_no_se_cobra():
    t, u, c = _despacho()
    cc.guardar_tarifa("tenant", t, "anotadas", 10, 25)
    _facturas(t, u, c, 4)
    assert cc.consumo(t)["importe_centimos"] == 0 and cc.consumo(t)["extra"] == 0


def test_se_puede_contar_lo_exportado_en_vez_de_lo_anotado():
    t, u, c = _despacho()
    cc.guardar_tarifa("tenant", t, "exportadas", 1, 100)
    for fid in _facturas(t, u, c, 3):
        fc.cambiar_estado(t, u, fid, "revisada")
    assert cc.consumo(t)["unidades"] == 0
    fc.exportar(t, u, c)
    r = cc.consumo(t)
    assert (r["unidad"], r["unidades"], r["extra"], r["importe_centimos"]) == ("exportadas", 3, 2, 200)


def test_un_mes_distinto_no_cuenta_y_el_formato_se_valida():
    t, u, c = _despacho()
    _facturas(t, u, c, 2)
    assert cc.consumo(t, "2020-01")["unidades"] == 0
    for malo in ("2026", "2026-13", "abcd-ef", "2026/10"):
        with pytest.raises(ValueError, match="AAAA-MM"):
            cc.consumo(t, malo)


# --- Límite duro ---------------------------------------------------------------------------------------------------------------------------------

def test_el_limite_impide_anotar_mas_facturas_ese_mes():
    t, u, c = _despacho()
    cc.guardar_tarifa("tenant", t, "anotadas", 2, 10, 3)
    _facturas(t, u, c, 3)
    with pytest.raises(ValueError, match="límite de 3 facturas"):
        fc.crear(t, u, c, _datos(numero="F-9"), [LINEA])
    assert cc.consumo(t)["restantes"] == 0 and cc.consumo(t)["unidades"] == 3


def test_subir_archivos_se_comprueba_entero_antes_de_guardar_ninguno():
    t, u, c = _despacho()
    cc.guardar_tarifa("tenant", t, "anotadas", 1, 10, 3)
    _facturas(t, u, c, 2)
    archivos = [(f"{i}.pdf", "application/pdf", PDF + bytes([i])) for i in range(3)]
    with pytest.raises(ValueError, match="límite"):
        fc.subir_archivos(t, u, c, "recibida", archivos)
    assert cc.consumo(t)["unidades"] == 2
    assert len(fc.subir_archivos(t, u, c, "recibida", archivos[:1])) == 1


def test_al_cliente_del_portal_se_le_dice_que_avise_a_su_gestoria(cliente):
    t, u, c = _despacho()
    cc.guardar_tarifa("tenant", t, "anotadas", 0, 10, 0)
    with pytest.raises(ValueError, match="Tu gestoría no puede recibir más facturas"):
        fc.crear_desde_portal(c, {"tipo": "recibida", "fecha": "2026-09-10", "numero": "P-1", "tercero_nombre": "X", "tercero_nif": "B1", "total": "10", "pct_iva": "21"})
    with pytest.raises(ValueError, match="Tu gestoría"):
        fc.subir_desde_portal(c, "recibida", [("a.pdf", "application/pdf", PDF)])


def test_el_limite_es_de_cada_despacho_y_no_afecta_a_otro():
    t1, u1, c1 = _despacho("Despacho limite uno")
    t2, u2, c2 = _despacho("Despacho limite dos")
    cc.guardar_tarifa("tenant", t1, "anotadas", 0, 0, 0)
    with pytest.raises(ValueError):
        fc.crear(t1, u1, c1, _datos(), [LINEA])
    assert fc.crear(t2, u2, c2, _datos(), [LINEA])


# --- Liquidación ---------------------------------------------------------------------------------------------------------------------------------

def test_liquidar_solo_incluye_los_despachos_con_modulo_y_algo_que_contar():
    t1, u1, c1 = _despacho("Con uso")
    t2, u2, c2 = _despacho("Sin uso")
    t3, u3, c3 = _despacho("Sin modulo", modulo=False)
    cc.guardar_tarifa("defecto", 0, "anotadas", 1, 50)
    _facturas(t1, u1, c1, 3)
    filas = {f["tenant"]: f for f in cc.liquidar()}
    assert set(filas) == {"Con uso", "Sin uso"}, "Sin uso aparece porque tiene tarifa; sin módulo no"
    assert (filas["Con uso"]["unidades"], filas["Con uso"]["extra"], filas["Con uso"]["importe_centimos"], filas["Con uso"]["estado"]) == (3, 2, 100, "abierta")
    assert filas["Sin uso"]["importe_centimos"] == 0


def test_recalcular_actualiza_lo_abierto_y_no_toca_lo_cerrado():
    t, u, c = _despacho()
    cc.guardar_tarifa("tenant", t, "anotadas", 0, 10)
    mes = db.now_iso()[:7]
    _facturas(t, u, c, 2)
    assert cc.liquidar()[0]["importe_centimos"] == 20
    _facturas(t, u, c, 1, desde=10)
    assert cc.liquidar()[0]["importe_centimos"] == 30, "mientras está abierta se recalcula"
    assert cc.cerrar_mes(mes) == 1
    _facturas(t, u, c, 2, desde=20)
    assert cc.liquidar()[0]["importe_centimos"] == 30 and cc.liquidar()[0]["estado"] == "cerrada", "cerrada es una foto"
    cc.guardar_tarifa("tenant", t, "anotadas", 0, 99)
    assert cc.vista_del_mes(mes)[0]["importe_centimos"] == 30, "tampoco cambia al cambiar la tarifa"


def test_estados_de_la_liquidacion():
    t, u, c = _despacho()
    cc.guardar_tarifa("tenant", t, "anotadas", 0, 10)
    mes = db.now_iso()[:7]
    _facturas(t, u, c, 1)
    with pytest.raises(ValueError, match="calcúlala primero"):
        cc.cambiar_estado_liquidacion(t, mes, "cerrada")
    cc.liquidar()
    cc.cambiar_estado_liquidacion(t, mes, "cerrada")
    cc.cambiar_estado_liquidacion(t, mes, "abierta")
    cc.cambiar_estado_liquidacion(t, mes, "cerrada")
    cc.cambiar_estado_liquidacion(t, mes, "facturada")
    with pytest.raises(ValueError, match="ya facturada"):
        cc.cambiar_estado_liquidacion(t, mes, "abierta")
    with pytest.raises(ValueError, match="no válido"):
        cc.cambiar_estado_liquidacion(t, mes, "rara")


def test_la_vista_del_mes_enseña_lo_vivo_y_lo_congelado():
    t, u, c = _despacho()
    cc.guardar_tarifa("tenant", t, "anotadas", 1, 10, 50)
    _facturas(t, u, c, 3)
    f, = cc.vista_del_mes()
    assert (f["estado"], f["unidades"], f["extra"], f["limite_duro"], f["origen"]) == ("sin calcular", 3, 2, 50, "tenant")


def test_el_csv_se_puede_abrir_en_una_hoja_de_calculo_sin_formulas_ocultas():
    t, u, c = _despacho("=HYPERLINK(1)")
    cc.guardar_tarifa("tenant", t, "anotadas", 0, 5)
    _facturas(t, u, c, 2)
    cc.liquidar()
    lineas = cc.csv_del_mes(db.now_iso()[:7]).split("\r\n")
    assert lineas[0].startswith("Despacho;Mes;Unidad") and lineas[1].startswith("'=HYPERLINK(1);") and lineas[1].endswith(";2;0;2;0,05;0,10;abierta")


def test_borrar_el_despacho_borra_su_tarifa_propia_y_sus_liquidaciones():
    t, u, c = _despacho()
    cc.guardar_tarifa("tenant", t, "anotadas", 0, 10)
    cc.guardar_tarifa("defecto", 0, "anotadas", 0, 10)
    _facturas(t, u, c, 1)
    cc.liquidar()
    conn = db.get_connection()
    try:
        fc.borrar_datos_de_tenant(conn, t); conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM contabilidad_liquidaciones WHERE tenant_id = ?", (t,)).fetchone()[0] == 0
        assert [r["ambito"] for r in conn.execute("SELECT ambito FROM contabilidad_tarifas")] == ["defecto"]
    finally:
        conn.close()


# --- Lo que ve el despacho -----------------------------------------------------------------------------------------------------------------------

def test_el_despacho_ve_su_uso_frente_al_plan_en_la_lista_y_en_el_resumen(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "cobroweb@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho cobro web"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Web", nif="B12345678")
    assert "incluidas en tu plan" not in cliente.get("/contabilidad/").get_data(as_text=True), "sin tarifa no se enseña nada"
    cc.guardar_tarifa("tenant", t, "anotadas", 1, 25, 10)
    _facturas(t, uid, c, 3)
    html = cliente.get("/contabilidad/").get_data(as_text=True)
    assert "Facturas anotadas este mes: 3 de 1 incluidas en tu plan." in html and "Llevas 2 de más, a 0.25 € cada una" in html and "Límite del plan: 10 facturas al mes; te quedan 7." in html
    from app import consultas_contabilidad as cq
    plan = cq.resumen(t, uid)["plan"]
    assert (plan["usadas"], plan["incluidas"], plan["de_mas"], plan["precio_por_factura_de_mas"], plan["limite"], plan["restantes"]) == (3, 1, 2, 0.25, 10, 7)


# --- Backoffice -------------------------------------------------------------------------------------------------------------------------------------

def test_el_backoffice_gestiona_tarifas_liquidaciones_y_csv(bo):
    plan = _plan("Plan backoffice")
    t, u, c = _despacho("Despacho backoffice", plan=plan)
    entrar(bo)
    html = bo.get("/cobro-contabilizacion").get_data(as_text=True)
    assert "Cobro de contabilización" in html and "Despacho backoffice" in html and "Plan backoffice" in html
    r = post(bo, "/cobro-contabilizacion/tarifa", ambito="plan", referencia_id=plan, unidad="anotadas", incluidas="2", precio="0,10", limite="")
    assert r.status_code == 302 and cc.tarifa_de(t)["origen"] == "plan" and cc.tarifa_de(t)["precio_extra_centimos"] == 10
    r = post(bo, "/cobro-contabilizacion/tarifa", ambito="plan", referencia_id=plan, unidad="anotadas", incluidas="2", precio="abc")
    assert cc.tarifa_de(t)["precio_extra_centimos"] == 10, "una tarifa mala no pisa la buena"
    _facturas(t, u, c, 5)
    mes = db.now_iso()[:7]
    assert post(bo, "/cobro-contabilizacion/calcular", mes=mes).status_code == 302
    html = bo.get(f"/cobro-contabilizacion?mes={mes}").get_data(as_text=True)
    assert "0,30 €" in html and "ABIERTA" in html
    assert post(bo, "/cobro-contabilizacion/cerrar", mes=mes).status_code == 302
    assert "CERRADA" in bo.get(f"/cobro-contabilizacion?mes={mes}").get_data(as_text=True)
    post(bo, "/cobro-contabilizacion/estado", mes=mes, tenant_id=t, estado="facturada")
    assert "FACTURADA" in bo.get(f"/cobro-contabilizacion?mes={mes}").get_data(as_text=True)
    csv = bo.get(f"/cobro-contabilizacion.csv?mes={mes}")
    assert csv.status_code == 200 and "Despacho backoffice" in csv.get_data(as_text=True) and csv.headers["Cache-Control"] == "no-store" and "contabilizacion-" in csv.headers["Content-Disposition"]
    post(bo, "/cobro-contabilizacion/tarifa/borrar", ambito="plan", referencia_id=plan)
    assert cc.tarifa_de(t) is None
    assert bo.get("/cobro-contabilizacion?mes=mal").status_code == 200


def test_el_backoffice_exige_sesion(bo):
    for ruta in ("/cobro-contabilizacion", "/cobro-contabilizacion.csv"):
        assert bo.get(ruta).status_code in (302, 401)
