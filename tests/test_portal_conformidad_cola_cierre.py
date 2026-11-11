"""C1 (conformidad del cliente con su 303), D1 (cola de trabajo por riesgo) y D3 (cierre guiado del trimestre) de «Facturas para contabilizar» y el portal."""
import io
from datetime import date

import pytest

from app import cierre_trimestre, cola_contabilidad, conformidad_declaracion, db, facturas_contables as fc, facturas_portal, fiscal_nucleo as fn, fiscal_perfiles as fp, notificaciones_email, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba
from tests.escenarios_303 import ESCENARIOS
from tests.test_facturas_contables import LINEA, PDF, _datos


def _sin_campana(html):
    import re
    return re.sub(r'<details class="pv-campana.*?</details>', '', html, flags=re.S)                  # lo nuevo también sale en la campana, plegada


def _despacho(cliente, email, fiscal=True):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant("Despacho " + email); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    if fiscal:
        verticales.fijar_activo(t, "fiscal", True)
    c = crear_cliente_fiscal(t, "Cliente Conformidad SL", nif="A12345674", email="cliente-conf@ejemplo.com")
    return uid, t, c


def _declaracion_revisada(t, u, c):
    fp.guardar_perfil(t, u, c, {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    for a in ESCENARIOS["basico"][0]:
        fn.aprobar_apunte(t, u, c, a)
    d = fn.calcular_declaracion(t, u, fn.crear_instantanea(t, u, c, ejercicio=2026, periodo="2T")["id"])
    fn.revisar_declaracion(t, u, d["id"])
    return d["id"]


def _como_cliente(cliente, c):
    with cliente.session_transaction() as sesion:
        sesion["cliente_fiscal_id"] = c


@pytest.fixture
def correo(monkeypatch):
    enviados = []
    monkeypatch.setenv("GUILDA_URL_PUBLICA", "https://work.ejemplo.com")
    monkeypatch.setattr(notificaciones_email, "configurado", lambda: True)
    monkeypatch.setattr(notificaciones_email, "_enviar", lambda dest, asunto, cuerpo, html=None: enviados.append((dest, asunto, cuerpo)))
    return enviados


# --- C1: conformidad ---------------------------------------------------------------------------------------------------------------------------------

def test_sin_pedirla_el_cliente_no_ve_la_declaracion(cliente):
    uid, t, c = _despacho(cliente, "conf-sin@ejemplo.com")
    d = _declaracion_revisada(t, uid, c)
    _como_cliente(cliente, c)
    assert cliente.get(f"/portal/declaraciones/{d}").status_code == 404
    assert "Revisa tu modelo 303" not in _sin_campana(cliente.get("/portal/").get_data(as_text=True))


def test_flujo_completo_pedir_ver_y_dar_la_conformidad(cliente, correo):
    uid, t, c = _despacho(cliente, "conf-flujo@ejemplo.com")
    d = _declaracion_revisada(t, uid, c)
    ficha = cliente.get(f"/guilda-fiscal/declaracion/{d}").get_data(as_text=True)
    assert "Pedir conformidad al cliente" in ficha
    r = cliente.post(f"/guilda-fiscal/declaracion/{d}/pedir-conformidad")
    assert r.status_code == 302 and "conformidad=avisado" in r.headers["Location"]
    assert correo and correo[0][0] == "cliente-conf@ejemplo.com" and "Revisa tu modelo 303 de 2T 2026" in correo[0][1] and f"siguiente=%2Fportal%2Fdeclaraciones%2F{d}" in correo[0][2]
    assert "Pendiente de respuesta" in cliente.get(f"/guilda-fiscal/declaracion/{d}").get_data(as_text=True)

    _como_cliente(cliente, c)
    inicio = _sin_campana(cliente.get("/portal/").get_data(as_text=True))
    assert "Revisa tu modelo 303 de 2T 2026" in inicio and f"/portal/declaraciones/{d}" in inicio
    pagina = cliente.get(f"/portal/declaraciones/{d}").get_data(as_text=True)
    assert "Resultado" in pagina and "De acuerdo" in pagina and "Hay un error" in pagina and "IVA que has cobrado" in pagina
    assert "21.00 €" in pagina and "10.50 €" in pagina and "Suministros" not in pagina, "las cuotas devengada y deducible salen de la declaración"
    assert pagina.count("<tr>") >= 3, "y los apuntes que la componen, uno por fila"
    r = cliente.post(f"/portal/declaraciones/{d}/conformidad", data={"resultado": "conforme"})
    assert r.status_code == 302 and "respondida=conforme" in r.headers["Location"]
    assert "Revisa tu modelo 303" not in _sin_campana(cliente.get("/portal/").get_data(as_text=True))
    assert "Das tu conformidad" in cliente.get(f"/portal/declaraciones/{d}").get_data(as_text=True)
    assert "El cliente está de acuerdo" in cliente.get(f"/guilda-fiscal/declaracion/{d}").get_data(as_text=True)
    assert cliente.post(f"/portal/declaraciones/{d}/conformidad", data={"resultado": "conforme"}).headers["Location"].count("error=")


def test_el_cliente_dice_que_hay_un_error_y_el_despacho_lo_ve(cliente, correo):
    uid, t, c = _despacho(cliente, "conf-error@ejemplo.com")
    d = _declaracion_revisada(t, uid, c)
    conformidad_declaracion.pedir(t, uid, d)
    _como_cliente(cliente, c)
    assert "error=" in cliente.post(f"/portal/declaraciones/{d}/conformidad", data={"resultado": "error", "comentario": "  "}).headers["Location"]
    cliente.post(f"/portal/declaraciones/{d}/conformidad", data={"resultado": "error", "comentario": "Falta la factura de la luz"})
    ficha = cliente.get(f"/guilda-fiscal/declaracion/{d}").get_data(as_text=True)
    assert "El cliente dice que hay un error" in ficha and "Falta la factura de la luz" in ficha and "Volver a pedirla" in ficha
    conformidad_declaracion.pedir(t, uid, d)                                       # una petición nueva anula la respuesta anterior
    assert conformidad_declaracion.estado_de(t, d)["respuesta"] is None
    assert [p["id"] for p in conformidad_declaracion.pendientes_del_cliente(c)] == [d]


def test_solo_se_pide_con_la_declaracion_revisada_y_sin_bloqueos(cliente):
    uid, t, c = _despacho(cliente, "conf-estado@ejemplo.com")
    fp.guardar_perfil(t, uid, c, {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    for a in ESCENARIOS["basico"][0]:
        fn.aprobar_apunte(t, uid, c, a)
    d = fn.calcular_declaracion(t, uid, fn.crear_instantanea(t, uid, c, ejercicio=2026, periodo="2T")["id"])["id"]
    with pytest.raises(ValueError, match="revisada o exportada"):
        conformidad_declaracion.pedir(t, uid, d)                                    # en borrador no se enseña


def test_un_cliente_no_ve_la_declaracion_de_otro_ni_contesta_por_el(cliente):
    uid, t, c = _despacho(cliente, "conf-aisl@ejemplo.com")
    otro = crear_cliente_fiscal(t, "Otro SL", nif="B87654321", email="otro-conf@ejemplo.com")
    d = _declaracion_revisada(t, uid, c)
    conformidad_declaracion.pedir(t, uid, d)
    _como_cliente(cliente, otro)
    assert cliente.get(f"/portal/declaraciones/{d}").status_code == 404
    assert cliente.post(f"/portal/declaraciones/{d}/conformidad", data={"resultado": "conforme"}).status_code == 404
    assert conformidad_declaracion.estado_de(t, d)["respuesta"] is None
    assert conformidad_declaracion.pendientes_del_cliente(otro) == []


def test_sin_guilda_fiscal_no_hay_portal_de_declaraciones(cliente):
    uid, t, c = _despacho(cliente, "conf-nofiscal@ejemplo.com", fiscal=False)
    _como_cliente(cliente, c)
    assert cliente.get("/portal/declaraciones/1").status_code == 404


def test_si_cambia_el_resultado_despues_de_pedirla_se_avisa_a_las_dos_partes(cliente, correo):
    uid, t, c = _despacho(cliente, "conf-cambio@ejemplo.com")
    d = _declaracion_revisada(t, uid, c)
    conformidad_declaracion.pedir(t, uid, d)
    from app import auditoria
    auditoria.registrar(t, uid, "fiscal.conformidad.pedida", "fiscal_declaracion", d, {"resultado_centimos": 99999, "estado": "revisada"})
    _como_cliente(cliente, c)
    assert "ha cambiado la declaración" in cliente.get(f"/portal/declaraciones/{d}").get_data(as_text=True)
    assert "el resultado ha cambiado" in cliente.get(f"/guilda-fiscal/declaracion/{d}").get_data(as_text=True).lower()


# --- D1: cola de trabajo -------------------------------------------------------------------------------------------------------------------------

HOY = date(2026, 11, 5)


@pytest.mark.parametrize("dias,trabajo,riesgo", [(None, 10, "sin_plazo"), (-2, 3, "vencido"), (10, 300, "alto"), (1, 25, "alto"), (3, 25, "medio"), (6, 25, "medio"), (7, 25, "bajo"), (30, 25, "bajo"), (30, 0, "bajo")])
def test_el_riesgo_sale_de_los_dias_que_sobran(dias, trabajo, riesgo):
    assert cola_contabilidad.riesgo_de(dias, trabajo)[0] == riesgo


def test_la_cola_ordena_por_holgura_no_por_llegada(cliente):
    uid, t, c = _despacho(cliente, "cola@ejemplo.com")
    tranquilo = crear_cliente_fiscal(t, "A Tranquilo", nif="B11111111")
    agobiado = crear_cliente_fiscal(t, "Z Agobiado", nif="B22222222")
    sin_plazo = crear_cliente_fiscal(t, "M Sin plazo", nif="B33333333")
    nada = crear_cliente_fiscal(t, "N Nada", nif="B44444444")
    for _ in range(2):
        fc.crear(t, uid, tranquilo, _datos(numero=f"T-{_}", fecha="2026-08-15"), [LINEA])
    for i in range(30):
        fc.crear(t, uid, agobiado, _datos(numero=f"G-{i}", fecha="2026-08-15"), [LINEA])
    fc.crear(t, uid, sin_plazo, _datos(numero="S-1", fecha="2026-08-15"), [LINEA])
    db.crear_vencimiento_fiscal(t, tranquilo, "303", "2026-T3", "2026-12-20")
    db.crear_vencimiento_fiscal(t, agobiado, "303", "2026-T3", "2026-11-07")
    filas = cola_contabilidad.cola(t, uid, HOY)
    assert [f["nombre"] for f in filas] == ["Z Agobiado", "A Tranquilo", "M Sin plazo"]
    z = filas[0]
    assert z["trabajo"] == 30 and z["riesgo"] == "alto" and z["dias_hasta"] == 2 and z["holgura"] == 0 and z["plazo"]["modelo"] == "303"
    assert filas[1]["riesgo"] == "bajo" and filas[2]["riesgo"] == "sin_plazo"
    db.crear_vencimiento_fiscal(t, nada, "303", "2026-T3", "2026-11-08")
    assert "N Nada" not in [f["nombre"] for f in cola_contabilidad.cola(t, uid, HOY)]


def test_la_cola_cuenta_lo_que_espera_al_cliente_y_sus_mensajes(cliente):
    uid, t, c = _despacho(cliente, "cola2@ejemplo.com")
    f1 = fc.crear_desde_portal(c, {"tipo": "recibida", "fecha": "2026-08-10", "numero": "P-1", "tercero_nombre": "X", "tercero_nif": "B1", "total": "121,00", "pct_iva": "21"})
    f2 = fc.crear_desde_portal(c, {"tipo": "recibida", "fecha": "2026-08-11", "numero": "P-2", "tercero_nombre": "Y", "tercero_nif": "B2", "total": "121,00", "pct_iva": "21"})
    facturas_portal.devolver(t, uid, f1, "Ilegible")
    facturas_portal.escribir_como_cliente(c, f2, "¿Falta algo?")
    fila = cola_contabilidad.cola(t, uid, HOY)[0]
    assert (fila["devueltas"], fila["mensajes"], fila["por_revisar"], fila["del_portal"]) == (1, 1, 1, 1)
    facturas_portal.dar_por_vista(c, f1)
    assert cola_contabilidad.cola(t, uid, HOY)[0]["devueltas"] == 0


def test_la_pantalla_de_la_cola_carga_y_enlaza_desde_la_lista(cliente):
    uid, t, c = _despacho(cliente, "cola3@ejemplo.com")
    fc.crear(t, uid, c, _datos(numero="Q-1", fecha="2026-08-15"), [LINEA])
    assert "Cola de trabajo" in cliente.get("/contabilidad/").get_data(as_text=True)
    pagina = cliente.get("/contabilidad/cola").get_data(as_text=True)
    assert "Cliente Conformidad SL" in pagina and "Riesgo" in pagina


# --- D3: cierre guiado -----------------------------------------------------------------------------------------------------------------------------

def test_el_checklist_cuenta_lo_que_queda(cliente):
    uid, t, c = _despacho(cliente, "cierre@ejemplo.com")
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8"})
    fc.crear(t, uid, c, _datos(numero="C-1", fecha="2026-08-15"), [LINEA])
    fc.crear(t, uid, c, _datos(numero="c-1", fecha="2026-08-16"), [LINEA])
    p = fc.crear_desde_portal(c, {"tipo": "recibida", "fecha": "2026-08-20", "numero": "P-9", "tercero_nombre": "X", "tercero_nif": "B1", "total": "121,00", "pct_iva": "21"})
    facturas_portal.escribir_como_cliente(c, p, "Os mando otra")
    fc.subir_desde_portal(c, "recibida", [("a.pdf", "application/pdf", PDF)])
    c3 = {x["clave"]: x for x in cierre_trimestre.checklist(t, uid, c, "2026-T3")["puntos"]}
    assert c3["por_revisar"]["cuantos"] == 3 and c3["mensajes"]["cuantos"] == 1 and c3["duplicadas"]["cuantos"] == 2 and c3["a3"]["estado"] == "ok" and c3["sin_exportar"]["estado"] == "ok"
    assert cierre_trimestre.checklist(t, uid, c, "2026-T3")["listo"] is False
    hoy = {x["clave"]: x for x in cierre_trimestre.checklist(t, uid, c, fc.trimestre_de(date.today().isoformat()))["puntos"]}        # el archivo subido sin datos entra con la fecha de hoy
    assert hoy["por_leer"]["cuantos"] == 1


def test_no_se_cierra_con_pendientes_salvo_que_se_fuerce_y_se_avisa_al_cliente(cliente, correo):
    uid, t, c = _despacho(cliente, "cierre2@ejemplo.com")
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8"})
    fc.crear(t, uid, c, _datos(numero="K-1", fecha="2026-08-15"), [LINEA])
    pagina = cliente.get(f"/contabilidad/cierre?cliente_id={c}&trimestre=2026-T3").get_data(as_text=True)
    assert "Antes de cerrar" in pagina and "Facturas por revisar" in pagina and "Cerrar igualmente" in pagina
    with pytest.raises(ValueError, match="puntos pendientes"):
        cierre_trimestre.cerrar(t, uid, c, "2026-T3")
    r = cliente.post("/contabilidad/cierre", data={"cliente_id": c, "trimestre": "2026-T3", "forzar": "1"})
    assert r.status_code == 200 and "Trimestre cerrado" in r.get_data(as_text=True)
    assert fc.periodos_cerrados(t, c, ["2026-T3"]) and correo and correo[-1][0] == "cliente-conf@ejemplo.com" and "Hemos cerrado el trimestre 3T 2026" in correo[-1][1]
    assert "siguiente=%2Fportal%2Ffacturas%3Ftrimestre%3D2026-T3" in correo[-1][2]
    with pytest.raises(ValueError, match="ya está cerrado"):
        cierre_trimestre.cerrar(t, uid, c, "2026-T3", forzar=True)
    ev = [e for e in __import__("app.auditoria", fromlist=["x"]).listar(t, accion="contabilidad.cierre_guiado")]
    assert ev and ev[0]["detalle"]["forzado"] is True and ev[0]["detalle"]["pendientes"] == ["por_revisar"]


def test_un_trimestre_sin_pendientes_se_cierra_sin_forzar_y_el_cliente_ve_el_informe(cliente, correo):
    uid, t, c = _despacho(cliente, "cierre3@ejemplo.com")
    assert cierre_trimestre.checklist(t, uid, c, "2026-T2")["puntos"][0]["estado"] == "aviso", "sin facturas es un aviso, no un bloqueo"
    cierre_trimestre.cerrar(t, uid, c, "2026-T2")
    assert correo and "informe del trimestre" in correo[-1][2]
    _como_cliente(cliente, c)
    pagina = cliente.get("/portal/facturas?trimestre=2026-T2").get_data(as_text=True)
    assert "Ver el informe del trimestre" in pagina
    r = cliente.get("/portal/facturas/informe.pdf?trimestre=2026-T2")
    assert r.status_code == 200 and r.mimetype == "application/pdf" and r.data.startswith(b"%PDF")
    assert cliente.get("/portal/facturas/informe.pdf?trimestre=mal").status_code == 404


def test_sin_guilda_fiscal_no_hay_informe(cliente):
    uid, t, c = _despacho(cliente, "cierre4@ejemplo.com", fiscal=False)
    cierre_trimestre.cerrar(t, uid, c, "2026-T2")
    _como_cliente(cliente, c)
    assert "Ver el informe del trimestre" not in cliente.get("/portal/facturas?trimestre=2026-T2").get_data(as_text=True)
    assert cliente.get("/portal/facturas/informe.pdf?trimestre=2026-T2").status_code == 404


def test_solo_ve_el_cierre_de_un_cliente_quien_puede_verlo(cliente):
    uid, t, c = _despacho(cliente, "cierre5@ejemplo.com")
    ajeno = crear_cliente_fiscal(db.crear_tenant("Otro despacho"), "Ajeno SL", nif="B55555555")
    with pytest.raises(ValueError):
        cierre_trimestre.checklist(t, uid, ajeno, "2026-T2")
