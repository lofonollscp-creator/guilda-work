"""Facturas para contabilizar (app/facturas_contables.py y app/rutas_contabilidad.py): anotar, revisar y generar el fichero de a3."""
import io

import pytest

from app import acceso, db, facturas_contables as fc, nucleo, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba


def _despacho(a3=True):
    t = db.crear_tenant("Despacho conta")
    u = db.crear_usuario_vinculado_a_kratos("conta1@ejemplo.com", "k-conta1"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    verticales.fijar_activo(t, "gestoria", True)
    c = crear_cliente_fiscal(t, "Cliente Conta S.L.", nif="B12345678")
    if a3:
        fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8"})
    return t, u, c


def _datos(**kw):
    return {"tipo": "recibida", "fecha": "2026-08-15", "numero": "F-1", "tercero_nombre": "Papelería Sol", "tercero_nif": "B87654321", "concepto": "Material", **kw}


LINEA = {"base": "1.000,00", "pct_iva": "21"}


# --- Lectura de importes ------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("texto,esperado", [("1.234,56", 123456), ("1234,56", 123456), ("1234.56", 123456), ("500", 50000), ("0,5", 50), ("", 0), (" 99,90 € ", 9990)])
def test_importes(texto, esperado):
    assert fc.importe_a_centimos(texto) == esperado


@pytest.mark.parametrize("texto", ["abc", "-5", "1,2,3", "9999999999999"])
def test_importes_no_validos(texto):
    with pytest.raises(ValueError):
        fc.importe_a_centimos(texto)


@pytest.mark.parametrize("texto,esperado", [("21", 2100), ("21,5", 2150), ("4.00", 400), ("", 0), ("0", 0), ("5,2 %", 520)])
def test_porcentajes(texto, esperado):
    assert fc.porcentaje_a_centesimas(texto) == esperado


def test_rango_del_trimestre_y_trimestre_de():
    assert fc.rango_del_trimestre("2026-T3") == ("2026-07-01", "2026-09-30") and fc.rango_del_trimestre("2026-T4") == ("2026-10-01", "2026-12-31") and fc.rango_del_trimestre("2026-T1") == ("2026-01-01", "2026-03-31")
    assert fc.trimestre_de("2026-08-15") == "2026-T3" and fc.trimestre_de("2026-01-01") == "2026-T1" and fc.trimestre_de("2026-12-31") == "2026-T4"
    with pytest.raises(ValueError):
        fc.rango_del_trimestre("2026-T5")


# --- Alta, cuotas y total ------------------------------------------------------------------------------------------------------------------------

def test_crear_calcula_la_cuota_y_el_total():
    t, u, c = _despacho()
    f = fc.obtener(t, u, fc.crear(t, u, c, _datos(), [LINEA]))
    assert (f["estado"], f["total_centimos"], f["lineas"][0]["cuota_iva"], f["trimestre"]) == ("pendiente", 121000, 21000, "2026-T3")


def test_varias_lineas_recargo_retencion_y_suplidos():
    t, u, c = _despacho()
    f = fc.obtener(t, u, fc.crear(t, u, c, _datos(suplidos="50,00"), [{"base": "1000", "pct_iva": "21", "pct_retencion": "15"}, {"base": "200", "pct_iva": "10", "pct_recargo": "1,4"}]))
    # 1000 + 210 - 150  +  200 + 20 + 2,80  + 50
    assert f["total_centimos"] == 133280 and [l["cuota_retencion"] for l in f["lineas"]] == [15000, 0] and f["lineas"][1]["cuota_recargo"] == 280


def test_una_cuota_escrita_manda_sobre_la_calculada():
    t, u, c = _despacho()
    f = fc.obtener(t, u, fc.crear(t, u, c, _datos(), [{"base": "100,01", "pct_iva": "21", "cuota_iva": "21,01"}]))
    assert f["lineas"][0]["cuota_iva"] == 2101 and f["total_centimos"] == 12102


@pytest.mark.parametrize("datos,lineas,fragmento", [
    ({"tipo": "otra"}, [LINEA], "emitida o recibida"), ({"tercero_nombre": ""}, [LINEA], "nombre"), ({"numero": ""}, [LINEA], "número"), ({"fecha": "ayer"}, [LINEA], "fecha"),
    ({}, [], "al menos una línea"), ({}, [{"base": "", "pct_iva": "21"}], "base imponible"), ({}, [{"base": "abc"}], "importe"), ({}, [LINEA] * 9, "Como máximo"),
])
def test_validaciones_al_crear(datos, lineas, fragmento):
    t, u, c = _despacho()
    with pytest.raises(ValueError, match=fragmento):
        fc.crear(t, u, c, _datos(**datos), lineas)


def test_un_cliente_de_otro_despacho_no_existe():
    t, u, c = _despacho()
    t2 = db.crear_tenant("Otro despacho conta"); c2 = crear_cliente_fiscal(t2, "Ajeno", nif="B11111111")
    with pytest.raises(ValueError, match="Cliente no encontrado"):
        fc.crear(t, u, c2, _datos(), [LINEA])


# --- Revisión ---------------------------------------------------------------------------------------------------------------------------------------

def test_problemas_que_impiden_revisar():
    t, u, c = _despacho(a3=False)
    fid = fc.crear(t, u, c, _datos(numero="FACTURA-LARGA-123", tercero_nif=""), [LINEA])
    f = fc.obtener(t, u, fid)
    assert len(f["problemas"]) == 2 and any("código de empresa" in p for p in f["problemas"]) and any("NIF" in p for p in f["problemas"]), "un número largo ya no es un problema: va en el campo ampliado"
    with pytest.raises(ValueError, match="No se puede dar por revisada"):
        fc.cambiar_estado(t, u, fid, "revisada")


def test_una_cuota_que_no_cuadra_con_la_base_es_un_problema():
    t, u, c = _despacho()
    f = fc.obtener(t, u, fc.crear(t, u, c, _datos(), [{"base": "1000", "pct_iva": "21", "cuota_iva": "150"}]))
    assert any("no coincide" in p for p in f["problemas"])


def test_revisar_reabrir_descartar_y_editar():
    t, u, c = _despacho()
    fid = fc.crear(t, u, c, _datos(), [LINEA])
    fc.cambiar_estado(t, u, fid, "revisada")
    assert fc.obtener(t, u, fid)["estado"] == "revisada"
    fc.actualizar(t, u, fid, _datos(numero="F-2"), [LINEA])
    f = fc.obtener(t, u, fid)
    assert (f["estado"], f["numero"], f["revisado_por"]) == ("pendiente", "F-2", None), "editar obliga a revisar otra vez"
    fc.cambiar_estado(t, u, fid, "descartada")
    assert fc.obtener(t, u, fid)["estado"] == "descartada"
    fc.cambiar_estado(t, u, fid, "pendiente")
    with pytest.raises(ValueError):
        fc.cambiar_estado(t, u, fid, "exportada")


# --- Cuentas de terceros --------------------------------------------------------------------------------------------------------------------------

def test_la_subcuenta_escrita_se_recuerda_por_nif_y_si_no_hay_se_usa_la_generica():
    t, u, c = _despacho()
    f1 = fc.obtener(t, u, fc.crear(t, u, c, _datos(tercero_cuenta="40000123"), [LINEA]))
    assert fc.cuenta_efectiva(t, f1) == "40000123"
    f2 = fc.obtener(t, u, fc.crear(t, u, c, _datos(numero="F-2"), [LINEA]))
    assert fc.cuenta_efectiva(t, f2) == "40000123", "la recuerda por el NIF del proveedor"
    f3 = fc.obtener(t, u, fc.crear(t, u, c, _datos(numero="F-3", tercero_nif="B99999999"), [LINEA]))
    assert fc.cuenta_efectiva(t, f3) == "40000000", "proveedor desconocido: subcuenta genérica"
    f4 = fc.obtener(t, u, fc.crear(t, u, c, _datos(tipo="emitida", numero="E-1", tercero_nif="B87654321"), [LINEA]))
    assert fc.cuenta_efectiva(t, f4) == "43000000", "una emitida usa clientes, no proveedores, aunque el NIF coincida"


def test_validacion_de_la_configuracion():
    t, u, c = _despacho(a3=False)
    for datos, fragmento in (({"a3_empresa": "123456"}, "5 dígitos"), ({"a3_empresa": "1", "digitos": "2"}, "entre 4 y 12"), ({"a3_empresa": "1", "cuenta_gasto": "12"}, "3 y 12")):
        with pytest.raises(ValueError, match=fragmento):
            fc.guardar_configuracion(t, u, c, datos)
    cfg = fc.guardar_configuracion(t, u, c, {"a3_empresa": "00042", "digitos": "10", "cuenta_proveedores": "4000000000"})
    assert cfg["a3_empresa"] == "00042" and cfg["digitos"] == 10 and cfg["cuenta_gasto"] == "62900000"


# --- Exportar ---------------------------------------------------------------------------------------------------------------------------------------

def test_exportar_genera_el_fichero_marca_exportadas_y_guarda_el_lote():
    t, u, c = _despacho()
    ids = [fc.crear(t, u, c, _datos(numero=f"F-{i}", fecha=f"2026-0{i}-10"), [LINEA]) for i in (7, 8, 9)]
    for i in ids[:2]:
        fc.cambiar_estado(t, u, i, "revisada")
    r = fc.exportar(t, u, c, desde="2026-07-01", hasta="2026-09-30")
    assert (r["n_facturas"], r["n_registros"]) == (2, 4) and len(r["contenido"]) == 4 * 512
    lineas = r["contenido"].decode("latin-1").split("\r\n")[:-1]
    assert lineas[0][0] == "5" and lineas[0][1:6] == "00007" and lineas[0][6:14] == "20260710" and lineas[2][6:14] == "20260810" and lineas[0][15:27] == "400000000000"
    assert lineas[1][15:27] == "629000000000" and lineas[1][191:203] == "472000000000", "gasto e IVA soportado por defecto"
    assert [fc.obtener(t, u, i)["estado"] for i in ids] == ["exportada", "exportada", "pendiente"]
    assert fc.contenido_del_lote(t, u, r["lote"]) == r["contenido"]
    assert [l["n_facturas"] for l in fc.listar_lotes(t, u)] == [2]
    with pytest.raises(ValueError, match="No hay facturas revisadas"):
        fc.exportar(t, u, c)
    with pytest.raises(ValueError, match="ya se exportó"):
        fc.actualizar(t, u, ids[0], _datos(), [LINEA])


def test_exportar_sin_codigo_de_empresa_se_niega():
    t, u, c = _despacho(a3=False)
    with pytest.raises(ValueError, match="código de empresa"):
        fc.exportar(t, u, c)


def test_una_emitida_usa_ingreso_y_iva_repercutido():
    t, u, c = _despacho()
    fid = fc.crear(t, u, c, _datos(tipo="emitida", numero="E-1"), [LINEA]); fc.cambiar_estado(t, u, fid, "revisada")
    lineas = fc.exportar(t, u, c)["contenido"].decode("latin-1").split("\r\n")
    assert lineas[0][57] == "1" and lineas[0][15:27] == "430000000000" and lineas[1][15:27] == "700000000000" and lineas[1][227:239] == "477000000000" and lineas[1][191:203] == " " * 12


def test_un_abono_sale_con_registro_2_importes_positivos_y_registro_4_de_la_factura_rectificada():
    t, u, c = _despacho()
    fid = fc.crear(t, u, c, _datos(abono="1"), [LINEA])
    with pytest.raises(ValueError, match="factura que rectifica"):
        fc.cambiar_estado(t, u, fid, "revisada")
    fc.actualizar(t, u, fid, _datos(abono="1", rectifica_numero="F-0", rectifica_fecha="2026-07-01"), [LINEA]); fc.cambiar_estado(t, u, fid, "revisada")
    lineas = fc.exportar(t, u, c)["contenido"].decode("latin-1").split("\r\n")
    assert lineas[0][14] == "2" and lineas[1][57] == "A" and lineas[1][101:115] == "+0000001000.00"
    assert lineas[2][14] == "4" and lineas[2][58:66] == "20260701" and lineas[2][66:126].strip() == "F-0" and lineas[2][156] == "R"


def test_respeta_las_oficinas_y_los_despachos(monkeypatch):
    t, u, c = _despacho()
    fid = fc.crear(t, u, c, _datos(), [LINEA])
    t2 = db.crear_tenant("Otro despacho"); u2 = db.crear_usuario_vinculado_a_kratos("conta9@ejemplo.com", "k-conta9"); db.asignar_tenant(u2, t2)
    assert fc.obtener(t2, u2, fid) is None and fc.listar(t2, u2) == [] and fc.listar_lotes(t2, u2) == []
    monkeypatch.setattr(acceso, "clientes_visibles", lambda tenant, usuario: set())
    monkeypatch.setattr(acceso, "puede_ver_cliente", lambda tenant, usuario, cliente: False)
    assert fc.listar(t, u) == [] and fc.obtener(t, u, fid) is None
    with pytest.raises(ValueError):
        fc.crear(t, u, c, _datos(), [LINEA])


def test_borrar_el_cliente_fiscal_borra_sus_facturas_y_lotes():
    t, u, c = _despacho()
    fid = fc.crear(t, u, c, _datos(), [LINEA]); fc.cambiar_estado(t, u, fid, "revisada"); fc.exportar(t, u, c)
    db.eliminar_cliente_fiscal_definitivamente(t, c)
    conn = db.get_connection()
    assert [conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0] for tabla in ("facturas_contables", "facturas_contables_lineas", "contabilidad_lotes", "contabilidad_clientes")] == [0, 0, 0, 0]


# --- Pantallas ---------------------------------------------------------------------------------------------------------------------------------------

def _web(cliente, email="contaweb@ejemplo.com"):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant("Despacho " + email); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "gestoria", True)
    c = crear_cliente_fiscal(t, "Cliente Web", nif="B12345678")
    return uid, t, c


def test_flujo_completo_desde_la_web(cliente):
    uid, t, c = _web(cliente)
    assert "Facturas para contabilizar" in cliente.get("/contabilidad/").get_data(as_text=True)
    r = cliente.post("/contabilidad/cliente/%d/configuracion" % c, data={"a3_empresa": "12", "digitos": "8"})
    assert r.status_code == 302
    r = cliente.post("/contabilidad/nueva", data={"cliente_id": c, "tipo": "recibida", "fecha": "2026-08-20", "numero": "W-1", "tercero_nombre": "Proveedor Web", "tercero_nif": "B22222222",
                                                  "base_0": "250,00", "pct_iva_0": "21"})
    assert r.status_code == 302
    fid = int(r.headers["Location"].rsplit("/", 1)[1])
    html = cliente.get(f"/contabilidad/{fid}").get_data(as_text=True)
    assert "W-1" in html and "Proveedor Web" in html and "Marcar como revisada" in html
    assert cliente.post(f"/contabilidad/{fid}/estado", data={"estado": "revisada"}).status_code == 302
    lista = cliente.get(f"/contabilidad/?cliente_id={c}&trimestre=2026-T3").get_data(as_text=True)
    assert "1 revisada" in lista and "Generar SUENLACE.DAT" in lista
    r = cliente.post("/contabilidad/exportar", data={"cliente_id": c, "trimestre": "2026-T3"})
    assert r.status_code == 200 and "SUENLACE.DAT" in r.headers["Content-Disposition"] and len(r.data) == 1024 and r.headers["Cache-Control"] == "no-store"
    assert "1 exportada" in cliente.get(f"/contabilidad/?cliente_id={c}").get_data(as_text=True)
    lotes = cliente.get("/contabilidad/lotes").get_data(as_text=True)
    assert "Descargar" in lotes
    lote = fc.listar_lotes(t, uid)[0]["id"]
    assert cliente.get(f"/contabilidad/lotes/{lote}/descargar").data == r.data


def test_errores_de_formulario_se_muestran_sin_guardar(cliente):
    uid, t, c = _web(cliente, "contaerr@ejemplo.com")
    r = cliente.post("/contabilidad/nueva", data={"cliente_id": c, "tipo": "recibida", "fecha": "2026-08-20", "numero": "", "tercero_nombre": "X", "base_0": "10", "pct_iva_0": "21"})
    assert r.status_code == 400 and "Indica el número de factura" in r.get_data(as_text=True)
    assert fc.listar(t, uid) == []


def test_sin_gestoria_no_existe_y_hay_que_iniciar_sesion(cliente):
    assert cliente.get("/contabilidad/").status_code in (302, 401, 404)
    uid = iniciar_sesion_de_prueba(cliente, "sinconta@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho sin gestoria"); db.asignar_tenant(uid, t)
    verticales.fijar_activo(t, "gestoria", False)
    assert cliente.get("/contabilidad/").status_code == 404


def test_el_texto_de_la_factura_se_escapa(cliente):
    uid, t, c = _web(cliente, "contaxss@ejemplo.com")
    fc.crear(t, uid, c, _datos(tercero_nombre="<script>alert(1)</script>"), [LINEA])
    html = cliente.get("/contabilidad/").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_el_enlace_de_la_barra_lateral_sale_en_gestoria(cliente):
    _web(cliente, "contabarra@ejemplo.com")
    assert 'href="/contabilidad/"' in cliente.get("/").get_data(as_text=True)
