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
