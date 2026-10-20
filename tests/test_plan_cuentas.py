"""Importar el plan de cuentas de a3 de un cliente (app/plan_cuentas.py, /contabilidad/cliente/<id>/plan): usar las subcuentas que ya existen en a3."""
import io

import pytest

from app import db, facturas_contables as fc, importador_clientes as imp, plan_cuentas as pc, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_facturas_contables import LINEA, _datos

CSV = ("Cuenta;Descripción;NIF\n"
       "40000001;PAPELERÍA SOL S.L.;B87654321\n"
       "40000002;Suministros Norte;B11111111\n"
       "43000001;CLIENTE FINAL SA;A58818501\n"
       "62900000;Gastos varios;\n"
       "57200000;Bancos;\n"
       "4000001;Cuenta de 7 dígitos;B22222222\n").encode()


def _despacho():
    t = db.crear_tenant("Despacho plan")
    u = db.crear_usuario_vinculado_a_kratos("plan1@ejemplo.com", "k-plan1"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Plan SL", nif="B12345678")
    fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8"})
    return t, u, c


def _importar(t, u, c, datos=CSV, nombre="plan.csv", confirmar=()):
    ident = pc.preparar(t, u, c, nombre, datos)
    return pc.importar(t, u, c, pc.cargar(t, u, c, ident), list(confirmar))


# --- Leer el archivo --------------------------------------------------------------------------------------------------------------------------

def test_se_leen_solo_proveedores_y_clientes_con_su_nif():
    r = pc.leer_registros("plan.csv", CSV)
    por = {x["cuenta"]: x for x in r["registros"]}
    assert set(por) == {"40000001", "40000002", "43000001", "4000001"} and r["ignoradas"] == 2
    assert por["40000001"] == {"cuenta": "40000001", "nombre": "PAPELERÍA SOL S.L.", "nif": "B87654321", "tipo": "proveedor"}
    assert por["43000001"]["tipo"] == "cliente" and r["avisos"] == []


def test_cabeceras_con_otros_nombres_y_columnas_en_otro_orden():
    r = pc.leer_registros("x.csv", "NIF/CIF,Código,Nombre cuenta\nB87654321,40000001,Sol\n".encode())
    assert r["registros"] == [{"cuenta": "40000001", "nombre": "Sol", "nif": "B87654321", "tipo": "proveedor"}]


def test_sin_nif_en_el_archivo_se_avisa():
    r = pc.leer_registros("x.csv", "Cuenta;Descripción\n40000001;Sol\n".encode())
    assert r["registros"][0]["nif"] == "" and any("NIF" in a for a in r["avisos"])


def test_sin_cabecera_una_columna_o_varias():
    uno = pc.leer_registros("x.txt", "40000001 PAPELERIA SOL\n43000002 CLIENTE UNO\n".encode())
    assert [(r["cuenta"], r["nombre"]) for r in uno["registros"]] == [("40000001", "PAPELERIA SOL"), ("43000002", "CLIENTE UNO")] and uno["avisos"]
    varios = pc.leer_registros("x.csv", "40000001;PAPELERIA SOL;B87654321\n43000002;CLIENTE UNO;\n".encode())
    assert varios["registros"][0]["nif"] == "B87654321" and varios["registros"][0]["nombre"] == "PAPELERIA SOL"


def test_excel():
    from openpyxl import Workbook
    libro = Workbook(); hoja = libro.active
    hoja.append(["Subcuenta", "Nombre", "CIF"]); hoja.append([40000001, "Papelería Sol", "B87654321"]); hoja.append([43000001, "Cliente", None])
    buf = io.BytesIO(); libro.save(buf)
    r = pc.leer_registros("plan.xlsx", buf.getvalue())
    assert [(x["cuenta"], x["nif"]) for x in r["registros"]] == [("40000001", "B87654321"), ("43000001", "")]


@pytest.mark.parametrize("nombre,datos,fragmento", [("x.csv", b"", "vacío"), ("x.pdf", b"abc", "Excel"), ("x.xls", b"abc", ".xls"), ("x.csv", b"Cuenta;Nombre\n62900000;Gastos\n", "ninguna subcuenta"),
                                                    ("x.xlsx", b"no es un zip", "Excel")])
def test_archivos_que_no_valen(nombre, datos, fragmento):
    with pytest.raises(imp.ErrorImportacion, match=fragmento):
        pc.leer_registros(nombre, datos)


# --- Coincidencias ----------------------------------------------------------------------------------------------------------------------------

def test_la_vista_previa_casa_por_nif_y_propone_por_nombre():
    t, u, c = _despacho()
    fc.crear(t, u, c, _datos(numero="1", tercero_nombre="Papelería Sol", tercero_nif="B87654321"), [LINEA])
    fc.crear(t, u, c, _datos(numero="2", tercero_nombre="Suministros Norte SL", tercero_nif="B99999999"), [LINEA])      # otro NIF, mismo nombre
    fc.crear(t, u, c, _datos(numero="3", tercero_nombre="Desconocido", tercero_nif="B55555555"), [LINEA])
    v = pc.previsualizar(t, u, c, pc.cargar(t, u, c, pc.preparar(t, u, c, "plan.csv", CSV)))
    assert (v["total"], v["validas"], v["otros_digitos"], v["digitos"]) == (4, 3, 1, 8)
    assert [(x["nif"], x["cuenta"]) for x in v["por_nif"]] == [("B87654321", "40000001")]
    assert [(x["nombre"], x["cuenta"]) for x in v["por_nombre"]] == [("Suministros Norte SL", "40000002")]


def test_un_nombre_que_casa_con_varias_cuentas_no_se_propone():
    t, u, c = _despacho()
    fc.crear(t, u, c, _datos(tercero_nombre="Sol", tercero_nif="B87654321"), [LINEA])
    dos = b"Cuenta;Nombre;NIF\n40000001;Sol SL;\n40000009;Sol S.L.;\n"
    v = pc.previsualizar(t, u, c, pc.cargar(t, u, c, pc.preparar(t, u, c, "p.csv", dos)))
    assert v["por_nombre"] == [] and v["por_nif"] == []


def test_si_ya_tiene_otra_subcuenta_recordada_manda_la_recordada_y_se_avisa():
    t, u, c = _despacho()
    fc.crear(t, u, c, _datos(tercero_nombre="Papelería Sol", tercero_nif="B87654321", tercero_cuenta="40000099"), [LINEA])
    v = pc.previsualizar(t, u, c, pc.cargar(t, u, c, pc.preparar(t, u, c, "plan.csv", CSV)))
    assert [x["recordada"] for x in v["difieren"]] == ["40000099"]
    _importar(t, u, c)
    f = fc.obtener(t, u, fc.crear(t, u, c, _datos(numero="9", tercero_nif="B87654321"), [LINEA]))
    assert fc.cuenta_efectiva(t, f) == "40000099"


# --- Importar y usar --------------------------------------------------------------------------------------------------------------------------

def test_importar_guarda_el_plan_y_la_factura_usa_la_subcuenta_de_a3():
    t, u, c = _despacho()
    r = _importar(t, u, c)
    assert r["cuentas"] == 3
    assert pc.resumen(t, u, c) == {"cuentas": 3, "proveedores": 2, "clientes": 1, "importado_en": pc.resumen(t, u, c)["importado_en"]}
    f = fc.obtener(t, u, fc.crear(t, u, c, _datos(tercero_nif="b-87654321"), [LINEA]))
    assert fc.cuenta_efectiva(t, f) == "40000001"
    e = fc.obtener(t, u, fc.crear(t, u, c, _datos(numero="E-1", tipo="emitida", tercero_nif="A58818501"), [LINEA]))
    assert fc.cuenta_efectiva(t, e) == "43000001"
    g = fc.obtener(t, u, fc.crear(t, u, c, _datos(numero="G-1", tercero_nif="A58818501"), [LINEA]))
    assert fc.cuenta_efectiva(t, g) == "40000000", "un cliente del plan no vale para una factura recibida"


def test_el_orden_es_factura_recordada_plan_generica():
    t, u, c = _despacho()
    _importar(t, u, c)
    a = fc.obtener(t, u, fc.crear(t, u, c, _datos(tercero_nif="B87654321", tercero_cuenta="40000555"), [LINEA]))
    assert fc.cuenta_efectiva(t, a) == "40000555"
    b = fc.obtener(t, u, fc.crear(t, u, c, _datos(numero="2", tercero_nif="B87654321"), [LINEA]))
    assert fc.cuenta_efectiva(t, b) == "40000555", "la recordada gana al plan"
    d = fc.obtener(t, u, fc.crear(t, u, c, _datos(numero="3", tercero_nif="B33333333"), [LINEA]))
    assert fc.cuenta_efectiva(t, d) == "40000000"


def test_el_fichero_sale_con_la_subcuenta_del_plan():
    t, u, c = _despacho()
    _importar(t, u, c)
    fid = fc.crear(t, u, c, _datos(tercero_nif="B87654321"), [LINEA]); fc.cambiar_estado(t, u, fid, "revisada")
    assert fc.exportar(t, u, c)["contenido"].decode("latin-1").split("\r\n")[0][15:27] == "400000010000"


def test_la_numeracion_automatica_respeta_el_plan():
    t, u, c = _despacho()
    _importar(t, u, c)                                          # existen 40000001 y 40000002
    fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8", "subcuentas_auto": "1"})
    for n, nif in (("1", "B87654321"), ("2", "B77777777")):    # el primero ya está en a3; el segundo es nuevo
        fc.cambiar_estado(t, u, fc.crear(t, u, c, _datos(numero=n, tercero_nif=nif), [LINEA]), "revisada")
    cuentas = [l[15:27] for l in fc.exportar(t, u, c)["contenido"].decode("latin-1").split("\r\n") if l[:1] == "5" and l[14] == "1"]
    assert cuentas == ["400000010000", "400000030000"], "el nuevo sigue tras la mayor del plan"
    assert [x["nif"] for x in fc.terceros_del_cliente(t, u, c)] == ["B77777777"], "solo se recuerda el que se numeró aquí"


def test_las_coincidencias_por_nombre_solo_se_recuerdan_si_se_confirman():
    t, u, c = _despacho()
    fc.crear(t, u, c, _datos(numero="1", tercero_nombre="Suministros Norte SL", tercero_nif="B99999999"), [LINEA])
    _importar(t, u, c)
    assert fc.terceros_del_cliente(t, u, c) == []
    r = _importar(t, u, c, confirmar=[0])
    assert r["por_nombre"] == 1 and [(x["nif"], x["cuenta"]) for x in fc.terceros_del_cliente(t, u, c)] == [("B99999999", "40000002")]
    assert _importar(t, u, c, confirmar=[7, -1])["por_nombre"] == 0, "índices que no existen se ignoran"


def test_importar_de_nuevo_sustituye_el_plan_y_borrar_lo_quita():
    t, u, c = _despacho()
    _importar(t, u, c)
    _importar(t, u, c, "Cuenta;Nombre;NIF\n40000050;Otro;B44444444\n".encode())
    assert pc.resumen(t, u, c)["cuentas"] == 1
    pc.borrar(t, u, c)
    assert pc.resumen(t, u, c)["cuentas"] == 0


def test_si_ninguna_subcuenta_tiene_los_digitos_del_cliente_no_se_importa():
    t, u, c = _despacho()
    ident = pc.preparar(t, u, c, "p.csv", b"Cuenta;Nombre\n4000001;Sol\n")
    with pytest.raises(ValueError, match="8 dígitos"):
        pc.importar(t, u, c, pc.cargar(t, u, c, ident), [])
    assert pc.resumen(t, u, c)["cuentas"] == 0


def test_una_importacion_es_privada_de_quien_la_subio_y_de_su_cliente():
    t, u, c = _despacho()
    ident = pc.preparar(t, u, c, "plan.csv", CSV)
    otro = db.crear_usuario_vinculado_a_kratos("plan2@ejemplo.com", "k-plan2"); db.asignar_tenant(otro, t)
    c2 = crear_cliente_fiscal(t, "Otro cliente", nif="B87654321")
    assert pc.cargar(t, otro, c, ident) is None and pc.cargar(t, u, c2, ident) is None and pc.cargar(t, u, c, ident) is not None
    t2 = db.crear_tenant("Otro despacho plan")
    assert pc.cargar(t2, u, c, ident) is None
    imp.descartar(ident)
    assert pc.cargar(t, u, c, ident) is None


def test_no_se_toca_el_plan_de_un_cliente_de_otro_despacho():
    t, u, c = _despacho()
    ajeno = crear_cliente_fiscal(db.crear_tenant("Ajeno plan"), "Ajeno", nif="B99999999")
    with pytest.raises(ValueError, match="no encontrado"):
        pc.resumen(t, u, ajeno)
    with pytest.raises(ValueError, match="no encontrado"):
        pc.borrar(t, u, ajeno)


def test_borrar_el_despacho_borra_sus_planes():
    t, u, c = _despacho()
    _importar(t, u, c)
    conn = db.get_connection()
    try:
        fc.borrar_datos_de_tenant(conn, t); conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM contabilidad_plan WHERE tenant_id = ?", (t,)).fetchone()[0] == 0
    finally:
        conn.close()


# --- Desde la web -----------------------------------------------------------------------------------------------------------------------------

def test_flujo_web_subir_revisar_e_importar(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "planweb@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho plan web"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Web", nif="B12345678")
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8"})
    fc.crear(t, uid, c, _datos(tercero_nombre="<b>Sol</b> SL", tercero_nif="B99999999"), [LINEA])
    url = f"/contabilidad/cliente/{c}/plan"
    assert "Importar el plan de cuentas" in cliente.get(f"/contabilidad/cliente/{c}/configuracion").get_data(as_text=True)
    assert "Todavía no has importado" in cliente.get(url).get_data(as_text=True)
    r = cliente.post(url, data={"accion": "subir"})
    assert "Elige el archivo" in r.get_data(as_text=True)
    r = cliente.post(url, data={"accion": "subir", "archivo": (io.BytesIO(b"nada que ver"), "x.pdf")}, content_type="multipart/form-data")
    assert "Excel" in r.get_data(as_text=True)
    csv = "Cuenta;Descripción;NIF\n40000001;<b>Sol</b> S.L.;\n43000001;Cliente;A58818501\n".encode()
    r = cliente.post(url, data={"accion": "subir", "archivo": (io.BytesIO(csv), "plan.csv")}, content_type="multipart/form-data")
    assert r.status_code == 302 and "importacion=" in r.headers["Location"]
    html = cliente.get(r.headers["Location"]).get_data(as_text=True)
    assert "Vista previa de la importación" in html and "Coincidencias solo por nombre" in html and "<b>Sol</b>" not in html and "&lt;b&gt;Sol" in html
    ident = r.headers["Location"].split("importacion=")[1]
    r = cliente.post(url, data={"accion": "importar", "importacion": ident, "nombre_ok": "0"})
    assert "Plan importado: 2 subcuentas" in r.get_data(as_text=True) and "confirmadas por nombre: 1" in r.get_data(as_text=True)
    assert "2 subcuentas (1 de proveedores, 1 de clientes)" in cliente.get(url).get_data(as_text=True)
    r = cliente.post(url, data={"accion": "importar", "importacion": ident})
    assert "caducado" in r.get_data(as_text=True)
    assert "Plan borrado" in cliente.post(url, data={"accion": "borrar"}).get_data(as_text=True)
    assert cliente.get(f"/contabilidad/cliente/999999/plan").status_code == 404
