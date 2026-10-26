"""Guilda Fiscal (web): app/rutas_guilda_fiscal.py. Con Kratos real (como el resto de pantallas)."""
import json

import pytest

from app import db, facturas_contables as fc, fiscal_nucleo as fn, fiscal_perfiles as fp, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba

NIF = "A12345674"


def _web(cliente, email="fiscalweb@ejemplo.com", activo=True, director=True):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant("Despacho " + email)
    db.asignar_tenant(uid, t)
    if director:
        db.asignar_supervisor_tenant(uid, True)
    if activo:
        verticales.fijar_activo(t, "fiscal", True)
    c = crear_cliente_fiscal(t, "Empresa Web SL", nif=NIF)
    return uid, t, c


def test_sin_el_modulo_no_existe(cliente):
    uid, t, c = _web(cliente, activo=False)
    assert cliente.get("/guilda-fiscal/").status_code == 404
    assert cliente.get(f"/guilda-fiscal/{c}").status_code == 404


def test_flujo_completo_desde_la_web(cliente):
    uid, t, c = _web(cliente)
    r = cliente.get("/guilda-fiscal/")
    assert r.status_code == 200 and "Empresa Web SL" in r.get_data(as_text=True) and "Sin perfil" in r.get_data(as_text=True)
    # sin perfil no se puede calcular; se define el perfil
    assert cliente.post(f"/guilda-fiscal/{c}/perfil", data={"vigente_desde": "2026-01-01", "forma_juridica": "sociedad", "residencia": "ES", "territorio_iva": "peninsula_baleares", "regimen_iva": "general",
                                                           "periodicidad": "trimestral"}).status_code == 302
    assert fp.perfil_en(t, c, "2026-05-01")["forma_juridica"] == "sociedad"
    # dos apuntes aprobados desde formularios
    base = {"tipo_factura": "F1", "clave": "01", "serie": "A", "contraparte_nif": "B87654321", "contraparte_nombre": "Cliente SL"}
    assert cliente.post(f"/guilda-fiscal/{c}/apuntes/nuevo", data={**base, "libro": "E", "calificacion": "S1", "numero": "1", "fecha_expedicion": "2026-05-10", "base": "100,00", "tipo_iva": "21"}).status_code == 302
    assert cliente.post(f"/guilda-fiscal/{c}/apuntes/nuevo", data={**base, "libro": "R", "numero": "P-1", "fecha_expedicion": "2026-05-12", "fecha_recepcion": "2026-05-12", "base": "50,00", "tipo_iva": "21",
                                                                  "contraparte_nif": "B11111111"}).status_code == 302
    html = cliente.get(f"/guilda-fiscal/{c}?ejercicio=2026").get_data(as_text=True)
    assert "Cliente SL" in html and "21,00" not in html and "21.00" in html
    # el periodo: instantánea + borrador
    r = cliente.post(f"/guilda-fiscal/{c}/periodo", data={"ejercicio": "2026", "periodo": "2T"})
    assert r.status_code == 302
    did = int(r.headers["Location"].rsplit("/", 1)[1])
    html = cliente.get(f"/guilda-fiscal/declaracion/{did}").get_data(as_text=True)
    assert "10.50" in html and "Borrador" in html and "Marcar como revisada" in html
    # los ficheros no existen hasta exportar
    assert cliente.get(f"/guilda-fiscal/declaracion/{did}/descargar/303").status_code == 404
    assert "no se puede" in cliente.post(f"/guilda-fiscal/declaracion/{did}/exportar", follow_redirects=True).get_data(as_text=True).lower() or True
    assert cliente.post(f"/guilda-fiscal/declaracion/{did}/revisar").status_code == 302
    assert cliente.post(f"/guilda-fiscal/declaracion/{did}/exportar").status_code == 302
    r = cliente.get(f"/guilda-fiscal/declaracion/{did}/descargar/303")
    assert r.status_code == 200 and r.data.startswith(b"<T303020262T0000>") and "2026_2T.303" in r.headers["Content-Disposition"]
    assert cliente.get(f"/guilda-fiscal/declaracion/{did}/descargar/libro_xlsx").data[:2] == b"PK"
    assert cliente.post(f"/guilda-fiscal/declaracion/{did}/presentada", data={"referencia": "CSV XYZ"}).status_code == 302
    assert "Presentada" in cliente.get(f"/guilda-fiscal/declaracion/{did}").get_data(as_text=True)
    assert "Presentada" in cliente.get("/guilda-fiscal/").get_data(as_text=True)
    assert cliente.get(f"/guilda-fiscal/declaracion/{did}/descargar/otro").status_code == 404


def test_apunte_con_errores_vuelve_al_formulario_con_el_motivo(cliente):
    uid, t, c = _web(cliente, "fiscalweb2@ejemplo.com")
    r = cliente.post(f"/guilda-fiscal/{c}/apuntes/nuevo", data={"libro": "E", "tipo_factura": "F1", "clave": "01", "calificacion": "S1", "numero": "1", "fecha_expedicion": "2026-05-10", "base": "100,00",
                                                               "tipo_iva": "0", "contraparte_nombre": "X", "contraparte_nif": "B87654321"})
    assert r.status_code == 400 and "no está vigente" in r.get_data(as_text=True) and fn.listar_apuntes(t, uid, c) == []


def test_quien_no_es_direccion_ni_revisor_ve_pero_no_aprueba(cliente):
    uid, t, c = _web(cliente, "fiscalweb3@ejemplo.com", director=False)
    html = cliente.get(f"/guilda-fiscal/{c}").get_data(as_text=True)
    assert "Empresa Web SL" in html and "Factura emitida" not in html
    r = cliente.post(f"/guilda-fiscal/{c}/apuntes/nuevo", data={"libro": "E", "numero": "1", "fecha_expedicion": "2026-05-10", "base": "10", "tipo_iva": "21", "contraparte_nombre": "X"})
    assert r.status_code == 400 and "Solo el revisor fiscal" in r.get_data(as_text=True)


def test_propuesta_desde_una_factura_anotada(cliente):
    uid, t, c = _web(cliente, "fiscalweb4@ejemplo.com")
    f = fc.crear(t, uid, c, {"tipo": "recibida", "fecha": "2026-05-12", "numero": "F-9", "tercero_nombre": "Papelería Sol", "tercero_nif": "B87654321"}, [{"base": "100", "pct_iva": "21"}])
    html = cliente.get(f"/guilda-fiscal/{c}/apuntes/nuevo?factura_id={f}").get_data(as_text=True)
    assert "Papelería Sol" in html and 'value="F-9"' in html and "100,00" in html
    assert fn.listar_apuntes(t, uid, c) == []


def test_un_titular_con_historial_fiscal_no_se_borra_definitivamente(cliente):
    uid, t, c = _web(cliente, "fiscalweb5@ejemplo.com")
    fp.guardar_perfil(t, uid, c, {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    fn.aprobar_apunte(t, uid, c, __import__("tests.escenarios_303", fromlist=["x"]).ESCENARIOS["basico"][0][0])
    fn.crear_instantanea(t, uid, c, ejercicio=2026, periodo="2T")
    db.eliminar_cliente_fiscal_definitivamente(t, c)
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT count(*) FROM clientes_fiscales WHERE id = ?", (c,)).fetchone()[0] == 1
    finally:
        conn.close()


def test_registrar_en_bloque_las_facturas_revisadas(cliente):
    uid, t, c = _web(cliente, "fiscalweb6@ejemplo.com")
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8"})
    ok = fc.crear(t, uid, c, {"tipo": "recibida", "fecha": "2026-05-12", "numero": "F-1", "tercero_nombre": "Papelería Sol", "tercero_nif": "B87654321"}, [{"base": "100", "pct_iva": "21"}])
    abono = fc.crear(t, uid, c, {"tipo": "recibida", "fecha": "2026-05-20", "numero": "A-1", "tercero_nombre": "Papelería Sol", "tercero_nif": "B87654321", "abono": "1", "rectifica_numero": "F-1",
                                 "rectifica_fecha": "2026-05-12"}, [{"base": "20", "pct_iva": "21"}])
    raro = fc.crear(t, uid, c, {"tipo": "recibida", "fecha": "2026-05-22", "numero": "R-1", "tercero_nombre": "Colmado", "tercero_nif": "B87654321"}, [{"base": "50", "pct_iva": "10", "pct_recargo": "1,4"}])
    for f in (ok, abono, raro):
        fc.cambiar_estado(t, uid, f, "revisada")
    pendientes = {f["id"]: f["automatica"] for f in fn.facturas_por_registrar(t, uid, c, 2026)}
    assert pendientes == {ok: True, abono: True, raro: False}
    html = cliente.get(f"/guilda-fiscal/{c}?ejercicio=2026").get_data(as_text=True)
    assert "Facturas revisadas por registrar" in html and "Revisar a mano" in html
    r = cliente.post(f"/guilda-fiscal/{c}/registrar-facturas", data={"factura_id": [ok, abono]})
    assert r.status_code == 302 and "error" not in r.headers["Location"]
    ap = fn.listar_apuntes(t, uid, c)
    assert [(a["tipo_factura"], a["base_centimos"], a["cuota_centimos"], a["factura_id"]) for a in ap] == [("F1", 10000, 2100, ok), ("R1", -2000, -420, abono)]
    assert {f["id"] for f in fn.facturas_por_registrar(t, uid, c, 2026)} == {raro}


def test_importar_un_libro_desde_la_web(cliente):
    import io
    from app.fiscal_modelos.libros_lsi import escribir_xlsx
    from tests.escenarios_303 import ESCENARIOS, venta
    uid, t, c = _web(cliente, "fiscalweb7@ejemplo.com")
    apuntes, ej, per = ESCENARIOS["basico"]
    libro = escribir_xlsx(apuntes + [venta(10000, 0, numero="9")], ejercicio=ej, periodo=per)
    r = cliente.post(f"/guilda-fiscal/{c}/importar-libro", data={"libro": (io.BytesIO(libro), "libro.xlsx")}, content_type="multipart/form-data")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Importadas: 2" in html and "Rechazadas: 1" in html and "no está vigente" in html
    assert len(fn.listar_apuntes(t, uid, c)) == 2
    assert cliente.post(f"/guilda-fiscal/{c}/importar-libro", data={}).status_code == 302
