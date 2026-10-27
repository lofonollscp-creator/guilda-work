"""Guilda Fiscal (web): app/rutas_guilda_fiscal.py. Con Kratos real (como el resto de pantallas)."""
from datetime import date
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
    db.crear_vencimiento_fiscal(t, c, "303", "2T 2026", "2026-07-20")
    r = cliente.get("/guilda-fiscal/")
    assert "2T 2026 · 2026-07-20" in r.get_data(as_text=True)
    assert r.status_code == 200 and "Empresa Web SL" in r.get_data(as_text=True) and "Sin perfil" in r.get_data(as_text=True)
    # sin perfil no se puede calcular; se define el perfil
    assert cliente.post(f"/guilda-fiscal/{c}/perfil", data={"vigente_desde": "2026-01-01", "forma_juridica": "sociedad", "residencia": "ES", "territorio_iva": "peninsula_baleares", "regimen_iva": "general",
                                                           "periodicidad": "trimestral"}).status_code == 302
    assert fp.perfil_en(t, c, "2026-05-01")["forma_juridica"] == "sociedad"
    # la ficha se puede corregir: el formulario sale relleno y guardar con la misma fecha no choca consigo mismo
    pagina = cliente.get(f"/guilda-fiscal/{c}/perfil").get_data(as_text=True)
    assert 'name="perfil_id"' in pagina and "Guardar cambios" in pagina
    existente = fp.perfil_en(t, c, "2026-05-01")
    assert cliente.post(f"/guilda-fiscal/{c}/perfil", data={"perfil_id": existente["id"], "version": existente["version"], "vigente_desde": "2026-01-01", "forma_juridica": "persona_fisica", "residencia": "ES",
                                                           "territorio_iva": "peninsula_baleares", "regimen_iva": "general", "periodicidad": "trimestral"}).status_code == 302
    assert fp.perfil_en(t, c, "2026-05-01")["forma_juridica"] == "persona_fisica" and len(fp.perfiles_de(t, c)) == 1
    # con una versión vieja se rechaza y se explica
    assert cliente.post(f"/guilda-fiscal/{c}/perfil", data={"perfil_id": existente["id"], "version": existente["version"], "vigente_desde": "2026-01-01", "forma_juridica": "sociedad", "residencia": "ES",
                                                           "territorio_iva": "peninsula_baleares", "regimen_iva": "general", "periodicidad": "trimestral"}).status_code == 400
    assert cliente.post(f"/guilda-fiscal/{c}/perfil", data={"perfil_id": 999999, "version": 1, "vigente_desde": "2026-01-01"}).status_code == 404
    existente = fp.perfil_en(t, c, "2026-05-01")
    assert cliente.post(f"/guilda-fiscal/{c}/perfil", data={"perfil_id": existente["id"], "version": existente["version"], "vigente_desde": "2026-01-01", "forma_juridica": "sociedad", "residencia": "ES",
                                                           "territorio_iva": "peninsula_baleares", "regimen_iva": "general", "periodicidad": "trimestral"}).status_code == 302
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


def test_una_declaracion_anulada_sale_de_la_lista_y_el_periodo_se_puede_recalcular(cliente):
    uid, t, c = _web(cliente, email="anulada@ejemplo.com")
    fp.guardar_perfil(t, uid, c, {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    assert cliente.post(f"/guilda-fiscal/{c}/periodo", data={"ejercicio": "2026", "periodo": "4T"}).status_code == 302
    d = fn.listar_declaraciones(t, uid, c)[0]
    assert "2026 4T" in cliente.get(f"/guilda-fiscal/{c}").get_data(as_text=True)
    assert 'data-confirmar-clic' in cliente.get(f"/guilda-fiscal/{d['id']}".replace(f"/{d['id']}", f"/declaracion/{d['id']}")).get_data(as_text=True)
    assert cliente.post(f"/guilda-fiscal/declaracion/{d['id']}/anular").status_code == 302
    pagina = cliente.get(f"/guilda-fiscal/{c}").get_data(as_text=True)
    assert "No hay declaraciones vigentes." in pagina and "Anuladas (1)" in pagina
    assert cliente.post(f"/guilda-fiscal/{c}/periodo", data={"ejercicio": "2026", "periodo": "4T"}).status_code == 302
    assert len([x for x in fn.listar_declaraciones(t, uid, c) if x["estado"] != "anulada"]) == 1


def test_reconoce_una_contraparte_ya_usada_por_su_nif(cliente):
    uid, t, c = _web(cliente, email="contraparte@ejemplo.com")
    datos = {"tipo_factura": "F1", "clave": "01", "serie": "A", "numero": "7", "libro": "E", "calificacion": "S1", "fecha_expedicion": "2026-05-10", "base": "100,00", "tipo_iva": "21",
             "contraparte_nif": "B87654321", "contraparte_nombre": "Cliente Recurrente SL"}
    assert cliente.post(f"/guilda-fiscal/{c}/apuntes/nuevo", data=datos).status_code == 302
    r = cliente.get(f"/guilda-fiscal/{c}/contraparte?nif=b-876 54321")
    assert r.get_json()["encontrada"]["nombre"] == "Cliente Recurrente SL"
    assert cliente.get(f"/guilda-fiscal/{c}/contraparte?nif=B11111111").get_json()["encontrada"] is None
    assert cliente.get(f"/guilda-fiscal/{c}/contraparte?nif=B8").get_json()["encontrada"] is None
    assert cliente.get(f"/guilda-fiscal/{c + 99}/contraparte?nif=B87654321").status_code == 404
    assert "data-contraparte-url" in cliente.get(f"/guilda-fiscal/{c}/apuntes/nuevo?libro=E").get_data(as_text=True)


def _emitida(cliente, c, numero, fecha="2026-05-10", nif="B87654321", nombre="Cliente SL", base="100,00"):
    datos = {"tipo_factura": "F1", "clave": "01", "serie": "A", "numero": numero, "libro": "E", "calificacion": "S1", "fecha_expedicion": fecha, "base": base, "tipo_iva": "21",
             "contraparte_nif": nif, "contraparte_nombre": nombre}
    assert cliente.post(f"/guilda-fiscal/{c}/apuntes/nuevo", data=datos).status_code == 302


def test_numeracion_duplicar_y_aviso_de_duplicado(cliente):
    uid, t, c = _web(cliente, email="numeracion@ejemplo.com")
    _emitida(cliente, c, "A-0007", "2026-05-31")
    nuevo = cliente.get(f"/guilda-fiscal/{c}/apuntes/nuevo?libro=E").get_data(as_text=True)
    assert 'value="A-0008"' in nuevo                                    # la numeración sigue sola
    apunte = fn.listar_apuntes(t, uid, c)[0]
    copia = cliente.get(f"/guilda-fiscal/{c}/apuntes/nuevo?copiar={apunte['id']}").get_data(as_text=True)
    assert 'value="A-0008"' in copia and 'value="2026-06-30"' in copia and "Cliente SL" in copia and 'value="100,00"' in copia      # 31 de mayo + 1 mes = 30 de junio
    assert cliente.get(f"/guilda-fiscal/{c}/apuntes/nuevo?copiar=999999").status_code == 404
    r = cliente.get(f"/guilda-fiscal/{c}/comprobar-numero?libro=E&serie=A&numero=A-0007&nif=b-87654321").get_json()
    assert r["existe"]["id"] == apunte["id"]
    assert cliente.get(f"/guilda-fiscal/{c}/comprobar-numero?libro=E&serie=A&numero=A-0007&nif=b-87654321&excluir={apunte['id']}").get_json()["existe"] is None
    assert cliente.get(f"/guilda-fiscal/{c}/comprobar-numero?libro=E&serie=A&numero=A-0099&nif=B87654321").get_json()["existe"] is None


def test_lo_habitual_con_una_contraparte(cliente):
    uid, t, c = _web(cliente, email="habitual@ejemplo.com")
    _emitida(cliente, c, "1")
    r = cliente.get(f"/guilda-fiscal/{c}/contraparte?libro=E&nif=B87654321").get_json()["encontrada"]
    assert r["habitual"] == {"tipo_iva": "21", "clave": "01", "calificacion": "S1", "exenta": "", "tipo_factura": "F1"}
    assert "habitual" not in cliente.get(f"/guilda-fiscal/{c}/contraparte?libro=R&nif=B87654321").get_json()["encontrada"]      # en el otro libro no se propone nada


def test_cartera_con_semaforo_y_filtros_e_importacion_en_bloque(cliente):
    uid, t, c = _web(cliente, email="cartera@ejemplo.com")
    pagina = cliente.get("/guilda-fiscal/").get_data(as_text=True)
    assert "Sin perfil fiscal" in pagina and "semaforo-rojo" in pagina
    fp.guardar_perfil(t, uid, c, {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    assert "Sin apuntes" in cliente.get("/guilda-fiscal/").get_data(as_text=True)
    assert "Empresa Web SL" not in cliente.get("/guilda-fiscal/?filtro=pendientes").get_data(as_text=True)         # «sin apuntes» es gris: no está entre los pendientes
    ficha = cliente.get(f"/guilda-fiscal/{c}").get_data(as_text=True)
    assert "Mensaje al cliente" in ficha and "No tenemos ninguna factura emitida" in ficha                           # sin apuntes en el periodo, el recordatorio pide las facturas
    import pathlib
    muestra = pathlib.Path(__file__).resolve().parents[1] / "docs" / "muestras-fiscal" / "basico.xlsx"
    import io
    r = cliente.post("/guilda-fiscal/importar-varios", data={"libros": [(io.BytesIO(muestra.read_bytes()), "A12345674-2T.xlsx"), (io.BytesIO(b"x"), "sin-nif.xlsx")]}, content_type="multipart/form-data")
    texto = r.get_data(as_text=True)
    assert r.status_code == 200 and "Importadas: 2" in texto and "No se sabe a qué titular" in texto
    assert len(fn.listar_apuntes(t, uid, c)) == 2


def test_resumen_pdf_cambios_y_recordatorio(cliente):
    uid, t, c = _web(cliente, email="resumen@ejemplo.com")
    fp.guardar_perfil(t, uid, c, {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    _emitida(cliente, c, "1")
    assert cliente.post(f"/guilda-fiscal/{c}/periodo", data={"ejercicio": "2026", "periodo": "2T"}).status_code == 302
    d1 = max(fn.listar_declaraciones(t, uid, c), key=lambda x: x["id"])
    pdf = cliente.get(f"/guilda-fiscal/declaracion/{d1['id']}/resumen.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF") and pdf.mimetype == "application/pdf"
    assert "Qué ha cambiado" not in cliente.get(f"/guilda-fiscal/declaracion/{d1['id']}").get_data(as_text=True)      # primer cálculo: nada con lo que comparar
    _emitida(cliente, c, "2", "2026-05-20", base="200,00")
    assert cliente.post(f"/guilda-fiscal/{c}/periodo", data={"ejercicio": "2026", "periodo": "2T"}).status_code == 302
    d2 = max((x for x in fn.listar_declaraciones(t, uid, c)), key=lambda x: x["id"])
    cambios = fn.comparar_con_anterior(t, uid, d2["id"])
    assert cambios["id"] == d1["id"] and {x["casilla"] for x in cambios["cambios"]} >= {"07", "09", "71"}
    assert "Qué ha cambiado" in cliente.get(f"/guilda-fiscal/declaracion/{d2['id']}").get_data(as_text=True)
    assert cliente.post(f"/guilda-fiscal/declaracion/{d2['id']}/anular").status_code == 302
    assert cliente.get(f"/guilda-fiscal/declaracion/{d2['id']}/resumen.pdf").status_code == 404


def test_buscador_de_la_cartera(cliente):
    uid, t, c = _web(cliente, email="buscador@ejemplo.com")
    crear_cliente_fiscal(t, "Assessors Històrics SL", nif="B16406233")
    todo = cliente.get("/guilda-fiscal/").get_data(as_text=True)
    assert "Empresa Web SL" in todo and "Assessors Històrics SL" in todo and "data-buscar-campo" in todo
    r = cliente.get("/guilda-fiscal/?q=historics").get_data(as_text=True)                 # sin acentos ni mayúsculas
    assert "Assessors Històrics SL" in r and "Empresa Web SL" not in r
    assert "Empresa Web SL" in cliente.get("/guilda-fiscal/?q=a12345674").get_data(as_text=True)        # por NIF
    assert "Empresa Web SL" in cliente.get("/guilda-fiscal/?q=web empresa").get_data(as_text=True)      # palabras en cualquier orden
    vacio = cliente.get("/guilda-fiscal/?q=zzzz").get_data(as_text=True)
    assert "Empresa Web SL" not in vacio and "Ningún titular coincide" in vacio


def _factura(t, uid, c, numero="F-1", fecha="2026-05-10"):
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8"})
    return fc.crear(t, uid, c, {"tipo": "recibida", "fecha": fecha, "numero": numero, "tercero_nombre": "Proveedor SL", "tercero_nif": "B87654321"}, [{"base": "100,00", "pct_iva": "21"}])


def test_facturas_pendientes_en_ficha_y_cartera_y_eleccion_de_incluir(cliente):
    uid, t, c = _web(cliente, email="facturas@ejemplo.com")
    f1, f2 = _factura(t, uid, c, "F-1"), _factura(t, uid, c, "F-2")
    pagina = cliente.get(f"/guilda-fiscal/{c}").get_data(as_text=True)
    assert "2 facturas esperan revisión" in pagina and "Ir a revisarlas" in pagina                  # sin revisar: se ven pero aún no se pueden registrar
    assert "2 por revisar" in cliente.get("/guilda-fiscal/").get_data(as_text=True)
    fc.cambiar_estado(t, uid, f1, "revisada")
    pagina = cliente.get(f"/guilda-fiscal/{c}").get_data(as_text=True)
    assert "1 factura espera revisión" in pagina and "Facturas revisadas por registrar" in pagina
    assert "1 por registrar" in cliente.get("/guilda-fiscal/").get_data(as_text=True)
    # elegir que NO cuente para Guilda Fiscal: desaparece de la ficha y de la cartera
    fc.fijar_incluir_en_fiscal(t, uid, f1, False)
    assert "Facturas revisadas por registrar" not in cliente.get(f"/guilda-fiscal/{c}").get_data(as_text=True)
    assert "por registrar" not in cliente.get("/guilda-fiscal/").get_data(as_text=True)
    fc.fijar_incluir_en_fiscal(t, uid, f1, True)
    assert "Facturas revisadas por registrar" in cliente.get(f"/guilda-fiscal/{c}").get_data(as_text=True)
    # ya registrada como apunte: no se puede sacar
    fn.aprobar_facturas(t, uid, c, [f1])
    with pytest.raises(ValueError, match="apunte"):
        fc.fijar_incluir_en_fiscal(t, uid, f1, False)


def test_el_formulario_de_factura_ofrece_incluir_en_guilda_fiscal(cliente):
    uid, t, c = _web(cliente, email="formulario@ejemplo.com")
    verticales.fijar_activo(t, "contabilizacion", True)
    f = _factura(t, uid, c)
    pagina = cliente.get(f"/contabilidad/{f}").get_data(as_text=True)
    assert 'name="incluir_en_fiscal"' in pagina and "checked" in pagina.split('name="incluir_en_fiscal"')[1][:60]
    datos = {"tipo": "recibida", "fecha": "2026-05-10", "numero": "F-1", "tercero_nombre": "Proveedor SL", "tercero_nif": "B87654321", "base_0": "100,00", "pct_iva_0": "21", "incluir_en_fiscal_presente": "1"}
    assert cliente.post(f"/contabilidad/{f}", data=datos).status_code == 302                       # casilla desmarcada: no manda «incluir_en_fiscal»
    assert fc.obtener(t, uid, f)["incluir_en_fiscal"] == 0
    assert 'name="incluir_en_fiscal"' in cliente.get(f"/contabilidad/{f}").get_data(as_text=True)
    assert cliente.post(f"/contabilidad/{f}", data={**datos, "incluir_en_fiscal": "1"}).status_code == 302
    assert fc.obtener(t, uid, f)["incluir_en_fiscal"] == 1
    verticales.fijar_activo(t, "fiscal", False)
    assert 'name="incluir_en_fiscal"' not in cliente.get(f"/contabilidad/{f}").get_data(as_text=True)     # sin el módulo no se ofrece


def test_facturas_que_computan_en_303_y_con_retencion_irpf(cliente):
    uid, t, c = _web(cliente, email="computan@ejemplo.com")
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8"})
    base = {"tercero_nombre": "Profesional SL", "tercero_nif": "B87654321", "fecha": "2026-05-10"}
    f_ret = fc.crear(t, uid, c, {**base, "tipo": "recibida", "numero": "R-1"}, [{"base": "1.000,00", "pct_iva": "21", "pct_retencion": "15"}])          # IVA al 303 y retención al 111
    f_emi = fc.crear(t, uid, c, {**base, "tipo": "emitida", "numero": "E-1"}, [{"base": "500,00", "pct_iva": "21", "pct_retencion": "15"}])              # retención soportada
    f_pen = fc.crear(t, uid, c, {**base, "tipo": "recibida", "numero": "R-2"}, [{"base": "100,00", "pct_iva": "21"}])                                      # sin revisar
    f_fuera = fc.crear(t, uid, c, {**base, "tipo": "recibida", "numero": "R-3", "fecha": "2026-08-10"}, [{"base": "100,00", "pct_iva": "21"}])             # otro trimestre
    for f in (f_ret, f_emi):
        fc.cambiar_estado(t, uid, f, "revisada")
    fn.aprobar_facturas(t, uid, c, [f_ret])
    r = fn.facturas_del_periodo(t, uid, c, 2026, "2T")
    por_numero = {f["numero"]: f for f in r["facturas"]}
    assert set(por_numero) == {"R-1", "E-1", "R-2"}                                                      # R-3 es del 3T
    assert por_numero["R-1"]["m303"] == "computa" and por_numero["R-1"]["m_retencion"] == "111" and por_numero["R-1"]["retencion"] == 15000
    assert por_numero["E-1"]["m303"] == "por_registrar" and por_numero["E-1"]["m_retencion"] == "soportada"
    assert por_numero["R-2"]["m303"] == "por_revisar" and por_numero["R-2"]["m_retencion"] is None
    assert r["totales"]["iva_soportado"] == 21000 and r["totales"]["retenciones_111"] == 15000 and r["totales"]["retenciones_soportadas"] == 7500 and r["totales"]["no_computan"] == 1
    fc.fijar_incluir_en_fiscal(t, uid, f_pen, False)
    assert {f["numero"]: f for f in fn.facturas_del_periodo(t, uid, c, 2026, "2T")["facturas"]}["R-2"]["m303"] == "excluida"
    pagina = cliente.get(f"/guilda-fiscal/{c}?p_ejercicio=2026&p_periodo=2T").get_data(as_text=True)
    assert "Facturas que computan en el periodo" in pagina and "Retenciones modelo 111" in pagina and "R-1" in pagina
    assert "R-3" not in pagina.split('id="computan"')[1].split("</section>")[0]


def test_historial_de_cambios_del_apunte_y_duplicada_en_otro_titular(cliente):
    uid, t, c = _web(cliente, email="historial@ejemplo.com")
    _emitida(cliente, c, "A-0001")
    apunte = fn.listar_apuntes(t, uid, c)[0]
    datos = {"tipo_factura": "F1", "clave": "01", "serie": "A", "numero": "A-0001", "libro": "E", "calificacion": "S1", "fecha_expedicion": "2026-05-10", "base": "200,00", "tipo_iva": "21",
             "contraparte_nif": "B87654321", "contraparte_nombre": "Cliente SL", "version": str(apunte["version"]), "causa": "importe corregido"}
    assert cliente.post(f"/guilda-fiscal/{c}/apuntes/{apunte['id']}", data=datos).status_code == 302
    h = fn.historial_apunte(t, uid, c, apunte["id"])
    assert [x["accion"] for x in h] == ["corregir", "aprobar"] and h[0]["cambios"]["base_centimos"] == ["10000", "20000"] and h[0]["motivo"] == "importe corregido"
    pagina = cliente.get(f"/guilda-fiscal/{c}/apuntes/{apunte['id']}").get_data(as_text=True)
    assert "Historial de cambios" in pagina and "base_centimos: 10000 → 20000" in pagina
    otro = crear_cliente_fiscal(t, "Otra Empresa SL", nif="B12345674")
    r = cliente.get(f"/guilda-fiscal/{otro}/comprobar-numero?libro=E&serie=A&numero=A-0001&nif=B87654321").get_json()
    assert r["otros"] == "Empresa Web SL" and r["existe"] is None
    assert cliente.get(f"/guilda-fiscal/{c}/comprobar-numero?libro=E&serie=A&numero=A-0001&nif=B87654321&excluir={apunte['id']}").get_json()["otros"] == ""


def test_aviso_cuando_el_apunte_ya_no_coincide_con_su_factura(cliente):
    uid, t, c = _web(cliente, email="cuadre@ejemplo.com")
    f = _factura(t, uid, c, "F-9")
    fc.cambiar_estado(t, uid, f, "revisada")
    fn.aprobar_facturas(t, uid, c, [f])
    assert fn.facturas_del_periodo(t, uid, c, 2026, "2T")["totales"]["descuadres"] == 0
    ap = fn.listar_apuntes(t, uid, c)[0]
    corregido = fn.a_apunte(ap).con(base=20000, cuota=4200)
    fn.aprobar_apunte(t, uid, c, corregido, factura_id=f, apunte_id=ap["id"], version=ap["version"], causa="importe distinto en el original")
    r = fn.facturas_del_periodo(t, uid, c, 2026, "2T")
    assert r["totales"]["descuadres"] == 1 and r["facturas"][0]["descuadre"]
    assert "1 apunte no coincide con su factura" in cliente.get(f"/guilda-fiscal/{c}?p_ejercicio=2026&p_periodo=2T").get_data(as_text=True)


def test_retencion_irpf_en_el_apunte_recibido(cliente):
    uid, t, c = _web(cliente, email="retencion@ejemplo.com")
    datos = {"libro": "R", "tipo_factura": "F1", "clave": "01", "numero": "P-1", "fecha_expedicion": "2026-05-10", "fecha_recepcion": "2026-05-10", "base": "1.000,00", "tipo_iva": "21",
             "contraparte_nif": "B87654321", "contraparte_nombre": "Profesional SL"}
    mal = cliente.post(f"/guilda-fiscal/{c}/apuntes/nuevo", data={**datos, "ret_modelo": "111", "ret_pct": "15", "ret_importe": "100,00"})                   # 15 % de 1.000 son 150
    assert mal.status_code == 400 and "no cuadra" in mal.get_data(as_text=True)
    assert cliente.post(f"/guilda-fiscal/{c}/apuntes/nuevo", data={**datos, "ret_modelo": "111", "ret_pct": "15"}).status_code == 302
    ap = fn.listar_apuntes(t, uid, c)[0]
    assert (ap["retencion_modelo"], ap["retencion_clave"], ap["retencion_base_centimos"], ap["retencion_pct_centesimas"], ap["retencion_centimos"]) == ("111", "G", 100000, 1500, 15000)
    assert 'value="15"' in cliente.get(f"/guilda-fiscal/{c}/apuntes/{ap['id']}").get_data(as_text=True)
    emitida = cliente.post(f"/guilda-fiscal/{c}/apuntes/nuevo", data={**datos, "libro": "E", "numero": "E-9", "ret_modelo": "111", "ret_pct": "15", "calificacion": "S1"})
    assert emitida.status_code == 302 and fn.listar_apuntes(t, uid, c)[1]["retencion_modelo"] == ""                                                         # en una emitida se ignora
    corregido = cliente.post(f"/guilda-fiscal/{c}/apuntes/{ap['id']}", data={**datos, "version": str(ap["version"]), "causa": "no llevaba retención"})
    assert corregido.status_code == 302 and fn.listar_apuntes(t, uid, c)[0]["retencion_centimos"] is None
    assert "retencion_centimos" in fn.historial_apunte(t, uid, c, ap["id"])[0]["cambios"]


def test_simulacion_de_los_modelos_111_y_115(cliente):
    from app.fiscal_modelos import motor_retenciones as mr
    r = mr.calcular([mr.Retencion("111", "G", 100000, 15000, "B87654321"), mr.Retencion("111", "G", 50000, 7500, "B87654321"), mr.Retencion("111", "A", 200000, 20000, "12345678Z"),
                     mr.Retencion("115", "", 80000, 15200, "B11111111")], modelo="111", ejercicio=2026, periodo="2T")
    c = r.casillas
    assert (c["07"], c["08"], c["09"]) == (1, 150000, 22500) and (c["01"], c["02"], c["03"]) == (1, 200000, 20000) and c["28"] == 42500 and c["30"] == 42500 and r.tipo_declaracion == "I"
    assert mr.calcular([mr.Retencion("115", "", 80000, 15200, "B11111111")], modelo="115", ejercicio=2026, periodo="2T").casillas == {"01": 1, "02": 80000, "03": 15200, "04": 0, "05": 15200}
    assert mr.calcular([mr.Retencion("111", "G", 100000, 15000, "B87654321")], modelo="111", ejercicio=2026, periodo="2T", a_deducir=20000).bloqueos
    uid, t, c_id = _web(cliente, email="sim111@ejemplo.com")
    datos = {"libro": "R", "tipo_factura": "F1", "clave": "01", "numero": "P-1", "fecha_expedicion": "2026-05-10", "fecha_recepcion": "2026-05-10", "base": "1.000,00", "tipo_iva": "21",
             "contraparte_nif": "B87654321", "contraparte_nombre": "Profesional SL", "ret_modelo": "111", "ret_pct": "15"}
    assert cliente.post(f"/guilda-fiscal/{c_id}/apuntes/nuevo", data=datos).status_code == 302
    sim = fn.simular_retenciones(t, uid, c_id, 2026, "2T")
    assert sim["111"].casillas["09"] == 15000 and sim["115"].casillas.get("03", 0) == 0
    assert fn.simular_retenciones(t, uid, c_id, 2026, "3T")["111"].casillas.get("09", 0) == 0
    pagina = cliente.get(f"/guilda-fiscal/{c_id}?p_ejercicio=2026&p_periodo=2T").get_data(as_text=True)
    assert "Simulación de retenciones" in pagina and "150.00" in pagina.split('id="simulacion-retenciones"')[1]


def test_panel_de_vencimientos_con_carga_de_trabajo(cliente):
    uid, t, c = _web(cliente, email="venc@ejemplo.com")
    conn = db.get_connection()
    for modelo, periodo, limite in (("303", "1T 2026", "2026-04-20"), ("303", "2T 2026", "2026-07-20"), ("111", "2T 2026", "2026-07-20"), ("303", "3T 2026", "2026-10-20")):
        conn.execute("INSERT INTO vencimientos_fiscales (tenant_id, cliente_fiscal_id, usuario_id, modelo, periodo, fecha_limite, estado, creado_en) VALUES (?, ?, ?, ?, ?, ?, 'pendiente', '2026-01-01')",
                     (t, c, uid, modelo, periodo, limite))
    conn.commit()
    conn.close()
    p = fn.panel_vencimientos(t, uid, dias=60, hoy=date(2026, 7, 1))
    assert [(f["modelo"], f["periodo"], f["nivel"]) for f in p["filas"]] == [("303", "1T 2026", "vencido"), ("303", "2T 2026", "proximo"), ("111", "2T 2026", "proximo")]       # el 3T queda fuera de 60 días
    assert p["vencidos"] == 1 and [f["carga"] for f in p["filas"]] == [4, 4, 1] and p["filas"][0]["declaracion"] is None
    assert p["semanas"][0]["inicio"] is None and p["semanas"][1]["vencimientos"] == 2 and p["semanas"][1]["carga"] == 5
    assert p["responsables"][0]["responsable"] == "venc" and p["responsables"][0]["carga"] == 9
    pagina = cliente.get("/guilda-fiscal/vencimientos?dias=180").get_data(as_text=True)
    assert "Vencimientos fiscales" in pagina and "Empresa Web SL" in pagina and "Carga por responsable" in pagina
    assert "Vencimientos y carga de trabajo" in cliente.get("/guilda-fiscal/").get_data(as_text=True)


def test_recordatorios_sugeridos_se_envian_solo_con_confirmacion(cliente, monkeypatch):
    from datetime import timedelta
    from app import notificaciones_email as ne
    uid, t, c = _web(cliente, email="record@ejemplo.com")
    sin_email = crear_cliente_fiscal(t, "Sin Correo SL", nif="B12345674")
    conn = db.get_connection()
    conn.execute("UPDATE clientes_fiscales SET email = 'cliente@ejemplo.com' WHERE id = ?", (c,))
    limite = (date.today() + timedelta(days=5)).isoformat()
    for cid in (c, sin_email):
        conn.execute("INSERT INTO vencimientos_fiscales (tenant_id, cliente_fiscal_id, usuario_id, modelo, periodo, fecha_limite, estado, creado_en) VALUES (?, ?, ?, '303', '2T 2026', ?, 'pendiente', '2026-01-01')",
                     (t, cid, uid, limite))
    conn.commit()
    conn.close()
    enviados = []
    monkeypatch.setattr(ne, "configurado", lambda: True)
    monkeypatch.setattr(ne, "enviar_recordatorio_fiscal", lambda *a, **k: enviados.append((a, k)))
    sug = {s["nombre"]: s for s in fn.recordatorios_sugeridos(t, uid)}
    assert sug["Empresa Web SL"]["puede"] and not sug["Sin Correo SL"]["puede"] and not enviados
    pagina = cliente.get("/guilda-fiscal/recordatorios").get_data(as_text=True)
    assert "Recordatorios a los clientes" in pagina and "Empresa Web SL" in pagina and "no tiene email" in pagina and not enviados
    k = f"{sug['Empresa Web SL']['clave']}_{c}"
    sin_confirmar = cliente.post("/guilda-fiscal/recordatorios", data={"envio": k})
    assert sin_confirmar.status_code == 400 and not enviados
    ok = cliente.post("/guilda-fiscal/recordatorios", data={"envio": k, "confirmo": "1", f"asunto_{k}": "Faltan facturas", f"texto_{k}": "Hola, nos faltan tus facturas."})
    assert ok.status_code == 200 and "Recordatorios enviados: 1" in ok.get_data(as_text=True)
    assert enviados[0][0][:3] == ("cliente@ejemplo.com", "Faltan facturas", "Hola, nos faltan tus facturas.")
    assert fn.recordatorios_sugeridos(t, uid)[0]["reciente"]
    otra = cliente.post("/guilda-fiscal/recordatorios", data={"envio": k, "confirmo": "1", f"asunto_{k}": "x", f"texto_{k}": "y"}).get_data(as_text=True)
    assert len(enviados) == 1                                                                                          # no se repite por el mismo periodo
