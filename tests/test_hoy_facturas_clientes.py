"""«Hoy»: la sección de facturas de clientes por revisar (app/bandeja_hoy.py + facturas_contables.pendientes_por_cliente)."""
from datetime import date

from app import bandeja_hoy, db, facturas_contables as fc, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_facturas_contables import LINEA, PDF, _datos

HOY = date.today()


def _despacho(modulo=True):
    t = db.crear_tenant("Despacho hoy facturas")
    u = db.crear_usuario_vinculado_a_kratos("hoyfac1@ejemplo.com", "k-hoyfac1"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    if modulo:
        verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Uno SL", nif="B12345678")
    if modulo:
        fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8"})
    return t, u, c


def _seccion(cliente, uid, supervisor=True):
    with cliente.application.test_request_context():
        b = bandeja_hoy.reunir(uid, supervisor, HOY)
    return next((s for s in b["secciones"] if s["clave"] == "contabilizacion"), None)


def _envejecer(fid, dias):
    conn = db.get_connection()
    try:
        conn.execute("UPDATE facturas_contables SET creado_en = ? WHERE id = ?", (f"{date.fromordinal(HOY.toordinal() - dias).isoformat()}T09:00:00", fid))
        conn.commit()
    finally:
        conn.close()


def test_sin_el_modulo_no_hay_seccion(cliente):
    t, u, c = _despacho(modulo=False)
    assert _seccion(cliente, u) is None


def test_con_el_modulo_pero_sin_facturas_tampoco(cliente):
    t, u, c = _despacho()
    assert _seccion(cliente, u) is None


def test_un_cliente_con_facturas_por_revisar_sale_con_sus_cifras(cliente):
    t, u, c = _despacho()
    fc.crear(t, u, c, _datos(numero="1"), [LINEA])
    fc.crear(t, u, c, _datos(numero="2"), [LINEA])
    r = fc.crear(t, u, c, _datos(numero="3"), [LINEA]); fc.cambiar_estado(t, u, r, "revisada")
    fc.subir_archivos(t, u, c, "recibida", [("a.pdf", "application/pdf", PDF + b"1")])
    s = _seccion(cliente, u)
    item, = s["elementos"]
    assert item["titulo"] == "Cliente Uno SL" and item["url"] == f"/contabilidad/?cliente_id={c}"
    assert "Por revisar: 3" in item["detalle"] and "Por leer: 1" in item["detalle"] and "Para exportar: 1" in item["detalle"]
    assert item["urgencia"] == "info", "recién anotadas, ninguna del portal"


def test_las_del_portal_o_las_antiguas_son_urgentes(cliente):
    t, u, c = _despacho()
    fid = fc.crear(t, u, c, _datos(numero="1"), [LINEA])
    assert _seccion(cliente, u)["elementos"][0]["urgencia"] == "info"
    _envejecer(fid, bandeja_hoy.DIAS_FACTURA_ANTIGUA + 1)
    assert _seccion(cliente, u)["elementos"][0]["urgencia"] == "hoy"
    c2 = crear_cliente_fiscal(t, "Cliente Dos SL", nif="B87654321")
    fc.crear_desde_portal(c2, {"tipo": "recibida", "fecha": "2026-09-10", "numero": "P-1", "tercero_nombre": "X", "tercero_nif": "B1", "total": "10", "pct_iva": "21"})
    por_nombre = {i["titulo"]: i["urgencia"] for i in _seccion(cliente, u)["elementos"]}
    assert por_nombre == {"Cliente Uno SL": "hoy", "Cliente Dos SL": "hoy"}


def test_lo_exportado_o_descartado_ya_no_cuenta(cliente):
    t, u, c = _despacho()
    a = fc.crear(t, u, c, _datos(numero="1"), [LINEA]); fc.cambiar_estado(t, u, a, "descartada")
    b = fc.crear(t, u, c, _datos(numero="2"), [LINEA]); fc.cambiar_estado(t, u, b, "revisada")
    fc.exportar(t, u, c)
    assert _seccion(cliente, u) is None


def test_no_se_mezclan_despachos(cliente):
    t, u, c = _despacho()
    fc.crear(t, u, c, _datos(), [LINEA])
    t2 = db.crear_tenant("Otro despacho hoy")
    u2 = db.crear_usuario_vinculado_a_kratos("hoyfac2@ejemplo.com", "k-hoyfac2"); db.asignar_tenant(u2, t2)
    verticales.fijar_activo(t2, "contabilizacion", True)
    assert _seccion(cliente, u2) is None


def test_la_pagina_hoy_la_enseña(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "hoyfacweb@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho hoy facturas web"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente <b>Web</b>", nif="B12345678")
    fc.crear(t, uid, c, _datos(), [LINEA])
    html = cliente.get("/hoy/").get_data(as_text=True)
    assert "Facturas de clientes" in html and "Por revisar: 1" in html and "<b>Web</b>" not in html and "&lt;b&gt;Web" in html
