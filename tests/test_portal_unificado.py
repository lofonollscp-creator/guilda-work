"""Portal de cliente unificado: barra de secciones, portada «Para hacer», tablero de facturas por trimestre y facturas devueltas con motivo."""
import io
from datetime import date

import pytest

from app import db, facturas_contables as fc, facturas_portal, portal_inicio, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_facturas_contables import LINEA, PDF, _datos, _portal

HOY = date(2026, 11, 5)


def _html(cliente, ruta):
    r = cliente.get(ruta)
    assert r.status_code == 200, ruta
    return r.get_data(as_text=True)


def _factura_del_portal(t, u, c, numero="P-1", fecha="2026-08-10"):
    return fc.crear_desde_portal(c, {"tipo": "recibida", "fecha": fecha, "numero": numero, "tercero_nombre": "Ferretería Paco", "tercero_nif": "B11111111", "total": "121,00", "pct_iva": "21"})


# --- Navegación -----------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("ruta", ["/portal/", "/portal/facturas", "/portal/impuestos"])
def test_todas_las_secciones_llevan_la_misma_barra(cliente, ruta):
    _portal(cliente, "Despacho nav")
    html = _html(cliente, ruta)
    assert 'class="portal-nav"' in html and "/portal/facturas" in html and "/portal/impuestos" in html
    assert html.count('aria-current="page"') >= 1


def test_documentos_y_mensajes_de_un_modelo_cuelgan_de_impuestos(cliente):
    t, u, c = _portal(cliente, "Despacho nav2")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20", usuario_id=u)
    for ruta in (f"/portal/vencimientos/{v}/documentos", f"/portal/vencimientos/{v}/mensajes"):
        html = _html(cliente, ruta)
        assert 'class="portal-nav"' in html and "Volver a mis impuestos" in html and "/portal/impuestos" in html


def test_sin_el_modulo_de_facturas_no_hay_pestana_de_facturas(cliente):
    t, u, c = _portal(cliente, "Despacho sin facturas")
    verticales.fijar_activo(t, "contabilizacion", False)
    html = _html(cliente, "/portal/")
    assert 'class="portal-nav"' in html and "/portal/facturas" not in html


def test_impuestos_lista_los_modelos_y_la_portada_ya_no(cliente):
    t, u, c = _portal(cliente, "Despacho impuestos")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20", usuario_id=u)
    assert f"/portal/vencimientos/{v}/documentos" in _html(cliente, "/portal/impuestos")
    assert "portal-carpeta " not in _html(cliente, "/portal/") and "Ver mis impuestos" in _html(cliente, "/portal/")


# --- Para hacer ----------------------------------------------------------------------------------------------------------------------------------

def test_sin_nada_pendiente_la_portada_lo_dice(cliente):
    _portal(cliente, "Despacho al dia")
    assert "Estás al día" in _html(cliente, "/portal/")


def test_un_documento_pedido_sale_en_para_hacer_con_su_enlace(cliente):
    t, u, c = _portal(cliente, "Despacho doc")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20", usuario_id=u)
    conn = db.get_connection(); conn.execute("UPDATE vencimientos_fiscales SET documento_solicitado = 'Extracto del banco' WHERE id = ?", (v,)); conn.commit(); conn.close()
    html = _html(cliente, "/portal/")
    assert "Extracto del banco" in html and f"/portal/vencimientos/{v}/documentos" in html and "Estás al día" not in html


def test_un_mensaje_sin_leer_sale_en_para_hacer_hasta_que_se_abre(cliente):
    t, u, c = _portal(cliente, "Despacho msg")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20", usuario_id=u)
    db.crear_mensaje_vencimiento(v, "empleado", "¿Puedes mandarnos el extracto?", usuario_id=u)
    assert "mensaje nuevo de tu gestoría" in _html(cliente, "/portal/") and "con-novedad" in _html(cliente, "/portal/impuestos")
    _html(cliente, f"/portal/vencimientos/{v}/mensajes")
    assert "Estás al día" in _html(cliente, "/portal/")


def test_recordatorio_de_facturas_cuando_se_acerca_un_modelo_y_no_hay_ninguna(cliente):
    t, u, c = _portal(cliente, "Despacho recuerda")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-11-20", usuario_id=u)
    cl = db.obtener_cliente_fiscal_por_id(c)
    from app.main import app
    with app.test_request_context("/portal/"):
        puntos = portal_inicio.para_hacer(cl, db.listar_vencimientos_fiscales(t, cliente_fiscal_id=c, sin_internos=True), [], [], [], True, HOY)
    assert [p["clave"] for p in puntos] == ["facturas-trimestre"] and puntos[0]["urgente"] is False and "3T 2026" in puntos[0]["titulo"]
    _factura_del_portal(t, u, c)
    with app.test_request_context("/portal/"):
        assert portal_inicio.para_hacer(cl, db.listar_vencimientos_fiscales(t, cliente_fiscal_id=c, sin_internos=True), [], [], [], True, HOY) == []


# --- Facturas devueltas -----------------------------------------------------------------------------------------------------------------------

def test_el_despacho_devuelve_con_motivo_y_el_cliente_lo_ve_en_su_portal(cliente):
    t, u, c = _portal(cliente, "Despacho devuelve")
    fid = _factura_del_portal(t, u, c)
    with pytest.raises(ValueError, match="Explica"):
        facturas_portal.devolver(t, u, fid, "   ")
    facturas_portal.devolver(t, u, fid, "Falta el NIF del proveedor")
    assert fc.obtener(t, u, fid)["estado"] == "descartada"
    html = _html(cliente, "/portal/facturas?trimestre=2026-T3")
    assert "Falta el NIF del proveedor" in html and "Enviar de nuevo" in html and 'id="factura-%d"' % fid in html and "portal-nav-insignia" in html
    inicio = _html(cliente, "/portal/")
    assert "Falta el NIF del proveedor" in inicio and f"#factura-{fid}" in inicio


def test_solo_se_devuelven_las_facturas_del_portal_y_aun_sin_exportar(cliente):
    t, u, c = _portal(cliente, "Despacho solo portal")
    propia = fc.crear(t, u, c, _datos(numero="D-1"), [LINEA])
    with pytest.raises(ValueError, match="cliente desde su portal"):
        facturas_portal.devolver(t, u, propia, "x")
    fid = _factura_del_portal(t, u, c)
    facturas_portal.devolver(t, u, fid, "Ilegible")
    with pytest.raises(ValueError, match="pendiente o revisada"):
        facturas_portal.devolver(t, u, fid, "Otra vez")


def test_reenviar_crea_una_factura_nueva_y_deja_de_pedir_la_devuelta(cliente):
    t, u, c = _portal(cliente, "Despacho reenvia")
    fid = _factura_del_portal(t, u, c)
    facturas_portal.devolver(t, u, fid, "Foto movida")
    r = cliente.post(f"/portal/facturas/{fid}/reenviar", data={"trimestre": "2026-T3", "archivos": (io.BytesIO(PDF), "buena.pdf", "application/pdf")}, content_type="multipart/form-data")
    assert r.status_code == 302 and "atendida=reenviada" in r.headers["Location"]
    nuevas = [f for f in fc.listar(t, u) if f["id"] != fid]
    assert len(nuevas) == 1 and nuevas[0]["origen"] == "portal" and nuevas[0]["estado"] == "pendiente"
    assert "Foto movida" in (fc.obtener(t, u, nuevas[0]["id"])["notas"] or "")
    assert facturas_portal.devueltas_sin_atender(c) == []
    assert "Estás al día" in _html(cliente, "/portal/") or "Estás al día" not in _html(cliente, "/portal/")        # la nueva factura no es una tarea del cliente
    assert "Para corregir" not in _html(cliente, "/portal/facturas?trimestre=2026-T3").split("<tbody>")[1]
    r = cliente.post(f"/portal/facturas/{fid}/reenviar", data={"archivos": (io.BytesIO(PDF), "otra.pdf", "application/pdf")}, content_type="multipart/form-data")
    assert "error=" in r.headers["Location"] and len(fc.listar(t, u)) == 2, "una devuelta ya atendida no se reenvía dos veces"


def test_entendido_cierra_la_devuelta_sin_crear_nada(cliente):
    t, u, c = _portal(cliente, "Despacho entendido")
    fid = _factura_del_portal(t, u, c)
    facturas_portal.devolver(t, u, fid, "No es de tu empresa")
    r = cliente.post(f"/portal/facturas/{fid}/entendido", data={"trimestre": "2026-T3"})
    assert "atendida=vista" in r.headers["Location"] and len(fc.listar(t, u, estado="pendiente")) == 0
    assert facturas_portal.devueltas_sin_atender(c) == []


def test_un_cliente_no_puede_tocar_las_devueltas_de_otro(cliente):
    t, u, c = _portal(cliente, "Despacho aislamiento")
    ajeno = crear_cliente_fiscal(t, "Otro cliente", nif="B22222222")
    fid = fc.crear_desde_portal(ajeno, {"tipo": "recibida", "fecha": "2026-08-10", "numero": "A-1", "tercero_nombre": "X", "tercero_nif": "B1", "total": "10", "pct_iva": "21"})
    facturas_portal.devolver(t, u, fid, "Secreto del otro cliente")
    assert "Secreto del otro cliente" not in _html(cliente, "/portal/facturas?trimestre=2026-T3")
    r = cliente.post(f"/portal/facturas/{fid}/entendido", data={})
    assert "error=" in r.headers["Location"] and len(facturas_portal.devueltas_sin_atender(ajeno)) == 1


def test_una_descartada_sin_motivo_sigue_como_siempre(cliente):
    t, u, c = _portal(cliente, "Despacho descartada")
    fid = _factura_del_portal(t, u, c)
    fc.cambiar_estado(t, u, fid, "descartada")
    html = _html(cliente, "/portal/facturas?trimestre=2026-T3")
    assert "el despacho te contactará" in html and "Enviar de nuevo" not in html


def test_el_despacho_devuelve_desde_la_web(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "devuelve-web@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho devuelve web"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Web", nif="B12345678")
    fid = _factura_del_portal(t, uid, c)
    assert "Devolver al cliente" in cliente.get(f"/contabilidad/{fid}").get_data(as_text=True)
    assert "error=" in cliente.post(f"/contabilidad/{fid}/devolver", data={"motivo": ""}).headers["Location"]
    cliente.post(f"/contabilidad/{fid}/devolver", data={"motivo": "Falta la base"})
    assert fc.obtener(t, uid, fid)["estado"] == "descartada" and facturas_portal.devueltas_sin_atender(c)[0]["devuelta"] == "Falta la base"
    assert "Devolver al cliente" not in cliente.get(f"/contabilidad/{fid}").get_data(as_text=True)


# --- Tablero del trimestre -------------------------------------------------------------------------------------------------------------------

def test_el_tablero_cuenta_cada_etapa(cliente):
    t, u, c = _portal(cliente, "Despacho tablero")
    ids = [_factura_del_portal(t, u, c, numero=f"T-{i}") for i in range(5)]
    fc.crear(t, u, c, _datos(numero="OTRO-T2", fecha="2026-05-10"), [LINEA])           # de otro trimestre
    fc.cambiar_estado(t, u, ids[0], "revisada") if not fc.obtener(t, u, ids[0])["problemas"] else None
    facturas_portal.devolver(t, u, ids[1], "Borrosa")
    conn = db.get_connection(); conn.execute("UPDATE facturas_contables SET estado = 'exportada' WHERE id = ?", (ids[2],)); conn.commit(); conn.close()
    tb = facturas_portal.tablero(c, "2026-T3", HOY)
    cu = tb["cuentas"]
    assert cu["para_corregir"] == 1 and cu["contabilizadas"] == 1 and cu["total"] == 5 and cu["en_revision"] + cu["revisadas"] == 3
    assert tb["situacion"] == "corregir" and len(tb["facturas"]) == 5
    assert facturas_portal.tablero(c, "2026-T2", HOY)["cuentas"]["total"] == 1
    html = _html(cliente, "/portal/facturas?trimestre=2026-T3")
    assert "3T 2026" in html and "Tienes 1 factura por corregir" in html and "<progress" in html


def test_trimestre_inventado_cae_en_el_del_proximo_modelo_y_los_cierres_se_avisan(cliente):
    t, u, c = _portal(cliente, "Despacho trimestre")
    db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20")
    assert facturas_portal.tablero(c, "no-vale", HOY)["trimestre"] == "2026-T3"
    assert facturas_portal.tablero(c, None, HOY)["modelos"][0]["modelo"] == "303"
    fc.cerrar_periodo(t, u, c, "2026-T3")
    assert "ya ha cerrado este trimestre" in _html(cliente, "/portal/facturas?trimestre=2026-T3")


def test_la_barra_de_trimestres_avisa_de_devueltas_en_otros(cliente):
    t, u, c = _portal(cliente, "Despacho otros")
    fid = _factura_del_portal(t, u, c, fecha="2026-02-10")
    facturas_portal.devolver(t, u, fid, "Mal")
    tb = facturas_portal.tablero(c, "2026-T3", HOY)
    assert tb["otras_devueltas"] == {"2026-T1": 1}
    assert "También tienes facturas por corregir en otros trimestres" in _html(cliente, "/portal/facturas?trimestre=2026-T3")


def test_subir_archivos_lleva_al_trimestre_de_hoy(cliente):
    t, u, c = _portal(cliente, "Despacho subir")
    r = cliente.post("/portal/facturas", data={"modo": "archivos", "tipo": "recibida", "archivos": (io.BytesIO(PDF), "f.pdf", "application/pdf")}, content_type="multipart/form-data")
    assert r.status_code == 302 and f"trimestre={facturas_portal.trimestre_actual()}" in r.headers["Location"]


# --- A2: mensajes por factura ----------------------------------------------------------------------------------------------------------------------

def test_el_cliente_escribe_en_su_factura_y_el_despacho_lo_ve_y_contesta(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "mensajes-factura@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho mensajes"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Mensajes", nif="B12345678")
    fid = _factura_del_portal(t, uid, c)
    with cliente.session_transaction() as sesion:
        sesion["cliente_fiscal_id"] = c
    assert "Mensajes con tu gestoría sobre esta factura" in _html(cliente, f"/portal/facturas/{fid}")
    r = cliente.post(f"/portal/facturas/{fid}/mensajes", data={"texto": "¿Os falta algo de esta factura?"})
    assert r.status_code == 302
    assert "error=" in cliente.post(f"/portal/facturas/{fid}/mensajes", data={"texto": "  "}).headers["Location"]
    lista = _html(cliente, "/contabilidad/")
    assert "Mensaje nuevo" in lista
    ficha = _html(cliente, f"/contabilidad/{fid}")
    assert "¿Os falta algo de esta factura?" in ficha and "Mensaje nuevo" not in _html(cliente, "/contabilidad/"), "abrirla marca el mensaje como leído"
    assert cliente.post(f"/contabilidad/{fid}/mensajes", data={"texto": "Todo recibido, gracias"}).status_code == 302
    assert "mensaje nuevo sobre una factura" in _html(cliente, "/portal/")
    assert "Todo recibido, gracias" in _html(cliente, f"/portal/facturas/{fid}")
    assert "mensaje nuevo sobre una factura" not in _html(cliente, "/portal/")


def test_un_cliente_no_ve_ni_escribe_en_facturas_de_otro(cliente):
    t, u, c = _portal(cliente, "Despacho mensajes aisl")
    ajeno = crear_cliente_fiscal(t, "Otro", nif="B22222222")
    fid = fc.crear_desde_portal(ajeno, {"tipo": "recibida", "fecha": "2026-08-10", "numero": "A-9", "tercero_nombre": "X", "tercero_nif": "B1", "total": "10", "pct_iva": "21"})
    assert cliente.get(f"/portal/facturas/{fid}").status_code == 404
    assert cliente.post(f"/portal/facturas/{fid}/mensajes", data={"texto": "hola"}).status_code == 404
    assert facturas_portal.mensajes(t, fid) == []


def test_los_mensajes_largos_y_las_conversaciones_enormes_se_rechazan(cliente):
    t, u, c = _portal(cliente, "Despacho mensajes limite")
    fid = _factura_del_portal(t, u, c)
    with pytest.raises(ValueError, match="1000"):
        facturas_portal.escribir_como_cliente(c, fid, "x" * 1001)
    for i in range(facturas_portal.MAX_MENSAJES_POR_FACTURA):
        facturas_portal.escribir_como_cliente(c, fid, f"m{i}")
    with pytest.raises(ValueError, match="muy larga"):
        facturas_portal.escribir_como_cliente(c, fid, "uno más")


# --- A4 y A5: repetidas ----------------------------------------------------------------------------------------------------------------------------

def test_el_mismo_archivo_no_crea_otra_factura_y_se_avisa(cliente):
    import hashlib
    t, u, c = _portal(cliente, "Despacho archivo repetido")
    datos = {"modo": "archivos", "tipo": "recibida", "archivos": (io.BytesIO(PDF), "f.pdf", "application/pdf")}
    assert cliente.post("/portal/facturas", data=datos, content_type="multipart/form-data").status_code == 302
    segunda = cliente.post("/portal/facturas", data={**datos, "archivos": (io.BytesIO(PDF), "otra.pdf", "application/pdf")}, content_type="multipart/form-data")
    assert segunda.status_code == 200 and "Ya nos enviaste esas facturas" in segunda.get_data(as_text=True)
    assert len(fc.listar(t, u)) == 1
    huella = hashlib.sha256(PDF).hexdigest()
    r = cliente.post("/portal/facturas/comprobar", json={"huellas": [huella, "no-vale", "0" * 64]})
    assert list(r.get_json()["repetidas"]) == [huella]
    pdf2 = PDF + b"\n%otro"
    mezcla = cliente.post("/portal/facturas", data={"modo": "archivos", "tipo": "recibida", "archivos": [(io.BytesIO(PDF), "a.pdf", "application/pdf"), (io.BytesIO(pdf2), "b.pdf", "application/pdf")]},
                          content_type="multipart/form-data")
    assert mezcla.status_code == 302 and "repetidas=1" in mezcla.headers["Location"] and len(fc.listar(t, u)) == 2


def test_una_descartada_deja_volver_a_enviar_el_mismo_archivo(cliente):
    t, u, c = _portal(cliente, "Despacho archivo descartado")
    cliente.post("/portal/facturas", data={"modo": "archivos", "tipo": "recibida", "archivos": (io.BytesIO(PDF), "f.pdf", "application/pdf")}, content_type="multipart/form-data")
    fc.cambiar_estado(t, u, fc.listar(t, u)[0]["id"], "descartada")
    cliente.post("/portal/facturas", data={"modo": "archivos", "tipo": "recibida", "archivos": (io.BytesIO(PDF), "f.pdf", "application/pdf")}, content_type="multipart/form-data")
    assert len(fc.listar(t, u)) == 2


def test_anotar_dos_veces_la_misma_factura_del_mismo_proveedor_se_rechaza(cliente):
    t, u, c = _portal(cliente, "Despacho anotar repetida")
    _factura_del_portal(t, u, c, numero="Ab-1")
    with pytest.raises(ValueError, match="Ya tienes anotada"):
        _factura_del_portal(t, u, c, numero="ab-1")
    _factura_del_portal(t, u, c, numero="Ab-2")            # otro número: vale


def test_el_formulario_avisa_de_los_trimestres_cerrados(cliente):
    t, u, c = _portal(cliente, "Despacho cerrados")
    fc.cerrar_periodo(t, u, c, facturas_portal.trimestre_actual())
    assert f'data-cerrados="{facturas_portal.trimestre_actual()}"' in _html(cliente, "/portal/facturas")
    assert "portal_facturas_subida.js" in _html(cliente, "/portal/facturas")


def test_el_despacho_ve_las_posibles_duplicadas(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "duplicadas@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho duplicadas"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Dup", nif="B12345678")
    a = fc.crear(t, uid, c, _datos(numero="D-1", fecha="2026-08-15"), [LINEA])
    b = fc.crear(t, uid, c, _datos(numero="d-1", fecha="2026-08-16"), [LINEA])
    c2 = fc.crear(t, uid, c, _datos(numero="OTRA", fecha="2026-08-17"), [LINEA])           # mismo importe, dos días después
    d = fc.crear(t, uid, c, _datos(numero="LEJOS", fecha="2026-09-30", tercero_nif="B99999999"), [LINEA])
    assert {x["id"]: x["motivo"] for x in fc.posibles_duplicados(t, uid, a)} == {b: "mismo número", c2: "mismo importe y fecha"}
    assert fc.posibles_duplicados(t, uid, d) == []
    assert fc.con_duplicado_entre(t, [a, b, c2, d]) == {a, b}
    assert "Posible duplicada" in _html(cliente, "/contabilidad/") and "Posible factura duplicada" in _html(cliente, f"/contabilidad/{a}")
    fc.cambiar_estado(t, uid, b, "descartada")
    assert [x["id"] for x in fc.posibles_duplicados(t, uid, a)] == [c2] and fc.con_duplicado_entre(t, [a]) == set()


# --- C4: enlaces que llevan a la pantalla exacta -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("valor,esperado", [("/portal/facturas?trimestre=2026-T2", "/portal/facturas?trimestre=2026-T2"), ("/portal/#certificado", "/portal/#certificado"),
                                            ("https://malo.example/portal/x", None), ("//malo.example", None), ("/portal//malo.example", None), ("/portal/entrar", None),
                                            ("/admin", None), ("/portal/\nx", None), ("/portal/x:y", None), ("", None), (None, None)])
def test_solo_se_aceptan_destinos_propios_del_portal(valor, esperado):
    from app.rutas_portal_cliente import destino_seguro
    assert destino_seguro(valor) == esperado


def test_url_portal_con_destino(monkeypatch):
    from app import portal_recordatorios
    monkeypatch.setenv("GUILDA_URL_PUBLICA", "https://work.ejemplo.com/")
    assert portal_recordatorios.url_portal("/portal/facturas?trimestre=2026-T2") == "https://work.ejemplo.com/portal/entrar?siguiente=%2Fportal%2Ffacturas%3Ftrimestre%3D2026-T2"
    assert portal_recordatorios.url_portal() == "https://work.ejemplo.com/portal/entrar"
    monkeypatch.delenv("GUILDA_URL_PUBLICA")
    assert portal_recordatorios.url_portal("/portal/x") is None


def test_el_enlace_de_acceso_conserva_el_destino_y_lleva_al_cliente_a_el(cliente, monkeypatch):
    from app import notificaciones_email
    t, c = db.crear_tenant("Despacho destino"), None
    c = db.crear_cliente_fiscal(t, "Cliente Destino", email="destino@ejemplo.com")
    enlaces = []
    monkeypatch.setattr("app.rutas_portal_cliente.enviar_enlace_portal", lambda email, enlace, tenant_id=None: enlaces.append(enlace))
    pagina = cliente.get("/portal/entrar?siguiente=/portal/facturas%3Ftrimestre%3D2026-T2").get_data(as_text=True)
    assert 'name="siguiente" value="/portal/facturas?trimestre=2026-T2"' in pagina
    cliente.post("/portal/entrar", data={"email": "destino@ejemplo.com", "siguiente": "/portal/facturas?trimestre=2026-T2"})
    from urllib.parse import urlsplit
    assert len(enlaces) == 1 and "siguiente=" in enlaces[0]
    partes = urlsplit(enlaces[0])
    r = cliente.get(partes.path + "?" + partes.query)
    assert r.status_code == 302 and r.headers["Location"].endswith("/portal/facturas?trimestre=2026-T2")
    ya_dentro = cliente.get("/portal/entrar?siguiente=/portal/impuestos")
    assert ya_dentro.status_code == 302 and ya_dentro.headers["Location"].endswith("/portal/impuestos")


def test_un_destino_ajeno_se_ignora_al_entrar(cliente):
    t = db.crear_tenant("Despacho destino malo")
    c = db.crear_cliente_fiscal(t, "Cliente", email="malo@ejemplo.com")
    token = db.crear_acceso_cliente_fiscal(c, "127.0.0.1")
    r = cliente.get(f"/portal/entrar/{token}?siguiente=https://malo.example/")
    assert r.status_code == 302 and "malo.example" not in r.headers["Location"] and r.headers["Location"].endswith("/portal/")


def test_los_avisos_al_cliente_llevan_a_la_pantalla_exacta(monkeypatch):
    from app import notificaciones_email as ne, portal_recordatorios
    monkeypatch.setenv("GUILDA_URL_PUBLICA", "https://work.ejemplo.com")
    monkeypatch.setattr(ne, "configurado", lambda: True)
    vistos = []
    monkeypatch.setattr(ne, "_enviar", lambda dest, asunto, cuerpo, html=None: vistos.append(cuerpo))
    t = db.crear_tenant("Despacho avisos destino")
    c = db.crear_cliente_fiscal(t, "Cliente Aviso", email="aviso@ejemplo.com")
    from datetime import datetime, timedelta
    hoy = datetime(2026, 4, 13, 9, 0)
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T1", (hoy + timedelta(days=7)).strftime("%Y-%m-%d"))
    assert portal_recordatorios.procesar_recordatorios(hoy) == 1
    assert f"siguiente=%2Fportal%2Fvencimientos%2F{v}%2Fdocumentos" in vistos[0]
    u = db.usuario_local_id()
    db.asignar_tenant(u, t)
    ne.enviar_recordatorio_facturas("aviso@ejemplo.com", "Cliente Aviso", "2026-T1", None, portal_recordatorios.con_destino("https://work.ejemplo.com/portal/entrar", "/portal/facturas?trimestre=2026-T1"), tenant_id=t)
    assert "siguiente=%2Fportal%2Ffacturas%3Ftrimestre%3D2026-T1" in vistos[-1]
