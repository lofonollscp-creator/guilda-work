"""Reglas por proveedor y cliente (facturas_contables.guardar_regla / sugerencias_de_reglas, /contabilidad/cliente/<id>/reglas)."""
import pytest

from app import db, facturas_contables as fc, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_facturas_contables import _datos

NIF = "B87654321"


def _despacho(**ajustes):
    t = db.crear_tenant("Despacho reglas")
    u = db.crear_usuario_vinculado_a_kratos("reglas1@ejemplo.com", "k-reglas1"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Reglas SL", nif="B12345678")
    fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8", **ajustes})
    return t, u, c


def _linea(t, u, fid):
    return fc.obtener(t, u, fid)["lineas"][0]


# --- Crear y validar ------------------------------------------------------------------------------------------------------------------------

def test_crear_una_regla_y_encontrarla_por_nif_aunque_se_escriba_distinto():
    t, u, c = _despacho()
    fc.guardar_regla(t, u, c, "proveedor", {"nif": "b-87654321", "nombre": "Sol SL", "cuenta_linea": "62200000", "pct_iva": "10", "concepto": "Material"})
    r = fc.regla_del_tercero(t, c, "recibida", " B87654321 ")
    assert (r["cuenta_linea"], r["pct_iva"], r["pct_retencion"], r["subtipo"], r["concepto"], r["nombre"]) == ("62200000", 1000, None, None, "Material", "Sol SL")
    assert fc.regla_del_tercero(t, c, "emitida", NIF) is None, "la de un proveedor no vale para sus ventas"
    assert fc.regla_del_tercero(t, c, "recibida", None) is None


def test_guardar_otra_vez_sustituye_y_no_duplica():
    t, u, c = _despacho()
    a = fc.guardar_regla(t, u, c, "proveedor", {"nif": NIF, "pct_iva": "21"})
    b = fc.guardar_regla(t, u, c, "proveedor", {"nif": NIF, "pct_iva": "4"})
    assert a == b and len(fc.listar_reglas(t, u, c)) == 1 and fc.listar_reglas(t, u, c)[0]["pct_iva"] == 400


@pytest.mark.parametrize("tipo,datos,fragmento", [
    ("otro", {"nif": NIF}, "proveedor o de un cliente"), ("proveedor", {"nif": ""}, "NIF"), ("proveedor", {"nif": NIF, "cuenta_linea": "12"}, "entre 3 y 12"),
    ("proveedor", {"nif": NIF, "pct_iva": "150"}, "porcentaje"), ("proveedor", {"nif": NIF, "pct_retencion": "70"}, "Retención"),
    ("proveedor", {"nif": NIF, "subtipo": "05"}, "no vale para facturas recibidas"), ("cliente", {"nif": NIF, "subtipo": "07"}, "no vale para facturas emitidas")])
def test_validaciones(tipo, datos, fragmento):
    t, u, c = _despacho()
    with pytest.raises(ValueError, match=fragmento):
        fc.guardar_regla(t, u, c, tipo, datos)
    assert fc.listar_reglas(t, u, c) == []


def test_el_criterio_de_caja_solo_tiene_sentido_en_proveedores():
    t, u, c = _despacho()
    fc.guardar_regla(t, u, c, "cliente", {"nif": NIF, "criterio_caja": "1"})
    assert fc.regla_del_tercero(t, c, "emitida", NIF)["criterio_caja"] == 0


def test_una_regla_es_del_cliente_fiscal_que_la_crea():
    t, u, c = _despacho()
    c2 = crear_cliente_fiscal(t, "Otro Cliente SL", nif="B11111111")
    fc.guardar_regla(t, u, c, "proveedor", {"nif": NIF, "cuenta_linea": "62200000"})
    assert fc.regla_del_tercero(t, c2, "recibida", NIF) is None


def test_no_se_toca_a_los_clientes_de_otro_despacho():
    t, u, c = _despacho()
    ajeno = crear_cliente_fiscal(db.crear_tenant("Ajeno reglas"), "Ajeno", nif="B99999999")
    with pytest.raises(ValueError, match="no encontrado"):
        fc.guardar_regla(t, u, ajeno, "proveedor", {"nif": NIF})
    with pytest.raises(ValueError, match="no encontrado"):
        fc.listar_reglas(t, u, ajeno)
    fc.guardar_regla(t, u, c, "proveedor", {"nif": NIF})
    assert fc.borrar_regla(t, u, c, fc.listar_reglas(t, u, c)[0]["id"]) is True
    assert fc.borrar_regla(t, u, c, 999999) is False


# --- Aplicar ----------------------------------------------------------------------------------------------------------------------------------

def test_la_regla_rellena_lo_que_la_linea_deja_en_blanco():
    t, u, c = _despacho()
    fc.guardar_regla(t, u, c, "proveedor", {"nif": NIF, "cuenta_linea": "62200000", "pct_iva": "10", "subtipo": "07", "concepto": "Material de oficina"})
    fid = fc.crear(t, u, c, _datos(tercero_nif=NIF, concepto=""), [{"base": "100"}])
    f = fc.obtener(t, u, fid)
    l = f["lineas"][0]
    assert (l["cuenta"], l["pct_iva"], l["cuota_iva"], l["subtipo"], f["concepto"], f["total_centimos"]) == ("62200000", 1000, 1000, "07", "Material de oficina", 11000)


def test_lo_escrito_en_la_factura_manda_sobre_la_regla():
    t, u, c = _despacho()
    fc.guardar_regla(t, u, c, "proveedor", {"nif": NIF, "cuenta_linea": "62200000", "pct_iva": "10", "subtipo": "07", "concepto": "Material"})
    fid = fc.crear(t, u, c, _datos(tercero_nif=NIF, concepto="Otro"), [{"base": "100", "pct_iva": "21", "cuenta": "60000000", "subtipo": "01"}])
    f = fc.obtener(t, u, fid)
    l = f["lineas"][0]
    assert (l["cuenta"], l["pct_iva"], l["subtipo"], f["concepto"]) == ("60000000", 2100, "01", "Otro")
    cero = _linea(t, u, fc.crear(t, u, c, _datos(numero="2", tercero_nif=NIF), [{"base": "100", "pct_iva": "0"}]))
    assert cero["pct_iva"] == 0, "un 0 escrito no se sustituye por la regla"


def test_la_regla_manda_sobre_el_regimen_del_cliente():
    t, u, c = _despacho(regimen_iva="exento", retencion_emitidas="15")
    fc.guardar_regla(t, u, c, "proveedor", {"nif": NIF, "subtipo": "01"})
    fc.guardar_regla(t, u, c, "cliente", {"nif": "A58818501", "pct_retencion": "7"})
    assert _linea(t, u, fc.crear(t, u, c, _datos(tercero_nif=NIF), [{"base": "100", "pct_iva": "21"}]))["subtipo"] == "01"
    assert _linea(t, u, fc.crear(t, u, c, _datos(numero="2", tercero_nif="B33333333"), [{"base": "100", "pct_iva": "21"}]))["subtipo"] == "07", "sin regla, el del régimen"
    e = _linea(t, u, fc.crear(t, u, c, _datos(tipo="emitida", numero="E1", tercero_nif="A58818501"), [{"base": "1000", "pct_iva": "21"}]))
    assert e["pct_retencion"] == 700, "7 % de la regla y no el 15 % del cliente"
    e2 = _linea(t, u, fc.crear(t, u, c, _datos(tipo="emitida", numero="E2", tercero_nif="B44444444"), [{"base": "1000", "pct_iva": "21"}]))
    assert e2["pct_retencion"] == 1500


def test_el_criterio_de_caja_de_la_regla_se_anade_a_las_recibidas():
    t, u, c = _despacho()
    fc.guardar_regla(t, u, c, "proveedor", {"nif": NIF, "criterio_caja": "1"})
    assert fc.obtener(t, u, fc.crear(t, u, c, _datos(tercero_nif=NIF), [{"base": "100", "pct_iva": "21"}]))["criterio_caja"] == 1
    assert fc.obtener(t, u, fc.crear(t, u, c, _datos(numero="2", tercero_nif="B33333333"), [{"base": "100", "pct_iva": "21"}]))["criterio_caja"] == 0


def test_editar_una_factura_tambien_aplica_la_regla():
    t, u, c = _despacho()
    fid = fc.crear(t, u, c, _datos(tercero_nif=NIF), [{"base": "100", "pct_iva": "21"}])
    fc.guardar_regla(t, u, c, "proveedor", {"nif": NIF, "cuenta_linea": "62200000"})
    fc.actualizar(t, u, fid, _datos(tercero_nif=NIF), [{"base": "100", "pct_iva": "21"}])
    assert _linea(t, u, fid)["cuenta"] == "62200000"


def test_sin_nif_no_hay_regla_que_aplicar():
    t, u, c = _despacho()
    fc.guardar_regla(t, u, c, "proveedor", {"nif": NIF, "cuenta_linea": "62200000"})
    fid = fc.crear(t, u, c, _datos(tercero_nif=None), [{"base": "100", "pct_iva": "21"}])
    assert _linea(t, u, fid)["cuenta"] is None


def test_la_cuenta_de_la_regla_sale_en_el_fichero():
    t, u, c = _despacho()
    fc.guardar_regla(t, u, c, "proveedor", {"nif": NIF, "cuenta_linea": "62200000"})
    fid = fc.crear(t, u, c, _datos(tercero_nif=NIF), [{"base": "100", "pct_iva": "21"}]); fc.cambiar_estado(t, u, fid, "revisada")
    detalle = [l for l in fc.exportar(t, u, c)["contenido"].decode("latin-1").split("\r\n") if l[:1] == "5" and l[14] == "9"][0]
    assert detalle[15:27] == "622000000000"


# --- Sugerencias --------------------------------------------------------------------------------------------------------------------------------

def _facturas(t, u, c, nif, n, **linea):
    return [fc.crear(t, u, c, _datos(numero=f"{nif}-{i}", tercero_nif=nif, tercero_nombre="Sol SL"), [{"base": "100", "pct_iva": "21", **linea}]) for i in range(n)]


def test_se_sugiere_lo_que_es_igual_en_todas_las_facturas():
    t, u, c = _despacho()
    _facturas(t, u, c, NIF, 3, cuenta="62200000", subtipo="01")
    s, = fc.sugerencias_de_reglas(t, u, c)
    assert (s["tipo"], s["nif"], s["facturas"], s["cuenta_linea"], s["pct_iva"], s["subtipo"], s["nombre"]) == ("proveedor", NIF, 3, "62200000", 2100, "01", "Sol SL")


def test_no_se_sugiere_lo_que_cambia_de_una_factura_a_otra():
    t, u, c = _despacho()
    fc.crear(t, u, c, _datos(numero="1", tercero_nif=NIF), [{"base": "100", "pct_iva": "21", "cuenta": "62200000"}])
    fc.crear(t, u, c, _datos(numero="2", tercero_nif=NIF), [{"base": "100", "pct_iva": "10", "cuenta": "62900000"}])
    s, = fc.sugerencias_de_reglas(t, u, c)
    assert s["cuenta_linea"] is None and s["pct_iva"] is None


def test_con_una_sola_factura_o_con_regla_o_descartadas_no_hay_sugerencia():
    t, u, c = _despacho()
    _facturas(t, u, c, "B11111111", 1)
    ids = _facturas(t, u, c, "B22222222", 2)
    fc.guardar_regla(t, u, c, "proveedor", {"nif": "B22222222"})
    d = _facturas(t, u, c, "B33333333", 2)
    for fid in d:
        fc.cambiar_estado(t, u, fid, "descartada")
    assert fc.sugerencias_de_reglas(t, u, c) == []


def test_crear_las_sugeridas_elegidas():
    t, u, c = _despacho()
    _facturas(t, u, c, NIF, 2, cuenta="62200000")
    _facturas(t, u, c, "B22222222", 2)
    assert fc.crear_reglas_sugeridas(t, u, c, [("proveedor", NIF), ("proveedor", "B00000000"), ("proveedor", NIF)]) == 1
    r = fc.regla_del_tercero(t, c, "recibida", NIF)
    assert r["aprendida"] == 1 and r["cuenta_linea"] == "62200000" and fc.regla_del_tercero(t, c, "recibida", "B22222222") is None


def test_borrar_el_despacho_borra_sus_reglas():
    t, u, c = _despacho()
    fc.guardar_regla(t, u, c, "proveedor", {"nif": NIF})
    conn = db.get_connection()
    try:
        fc.borrar_datos_de_tenant(conn, t); conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM contabilidad_reglas WHERE tenant_id = ?", (t,)).fetchone()[0] == 0
    finally:
        conn.close()


# --- Web ------------------------------------------------------------------------------------------------------------------------------------------

def test_flujo_web_anadir_editar_borrar_y_sugeridas(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "reglasweb@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho reglas web"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Web", nif="B12345678")
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8"})
    url = f"/contabilidad/cliente/{c}/reglas"
    assert "Reglas por proveedor" in cliente.get(f"/contabilidad/cliente/{c}/configuracion").get_data(as_text=True)
    assert "Todavía no hay reglas" in cliente.get(url).get_data(as_text=True)
    r = cliente.post(url, data={"accion": "nueva", "n_tipo": "proveedor", "n_nif": NIF, "n_nombre": "<b>Sol</b> SL", "n_cuenta_linea": "62200000", "n_pct_iva": "10"})
    html = r.get_data(as_text=True)
    assert "Regla creada" in html and "<b>Sol</b>" not in html and "&lt;b&gt;Sol" in html and 'value="62200000"' in html
    regla = fc.listar_reglas(t, uid, c)[0]
    r = cliente.post(url, data={"accion": "nueva", "n_tipo": "proveedor", "n_nif": "", "n_cuenta_linea": "12"})
    assert "NIF" in r.get_data(as_text=True) and len(fc.listar_reglas(t, uid, c)) == 1
    r = cliente.post(url, data={"accion": "guardar", f"r{regla['id']}_nif": NIF, f"r{regla['id']}_cuenta_linea": "62900000", f"r{regla['id']}_pct_iva": "21", f"r{regla['id']}_pct_retencion": "",
                                f"r{regla['id']}_subtipo": "", f"r{regla['id']}_concepto": "Compras", f"r{regla['id']}_criterio_caja": "1"})
    assert "Reglas guardadas" in r.get_data(as_text=True)
    nueva = fc.listar_reglas(t, uid, c)[0]
    assert (nueva["cuenta_linea"], nueva["pct_iva"], nueva["concepto"], nueva["criterio_caja"]) == ("62900000", 2100, "Compras", 1)
    fc.crear(t, uid, c, _datos(numero="1", tercero_nif="B55555555", tercero_nombre="Otro SL"), [{"base": "100", "pct_iva": "21"}])
    fc.crear(t, uid, c, _datos(numero="2", tercero_nif="B55555555", tercero_nombre="Otro SL"), [{"base": "100", "pct_iva": "21"}])
    html = cliente.get(url).get_data(as_text=True)
    assert "Sugeridas por sus facturas" in html and "B55555555" in html
    r = cliente.post(url, data={"accion": "sugeridas", "sugerida": "proveedor|B55555555"})
    assert "Reglas creadas: 1" in r.get_data(as_text=True) and fc.regla_del_tercero(t, c, "recibida", "B55555555")["aprendida"] == 1
    fid = fc.crear(t, uid, c, _datos(numero="9", tercero_nif=NIF), [{"base": "100"}])
    assert "regla de este proveedor" in cliente.get(f"/contabilidad/{fid}").get_data(as_text=True)
    r = cliente.post(url, data={"accion": "guardar", f"r{regla['id']}_borrar": "1"})
    assert fc.regla_del_tercero(t, c, "recibida", NIF) is None
    assert cliente.get("/contabilidad/cliente/999999/reglas").status_code == 404
