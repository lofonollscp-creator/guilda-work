"""B1/B2 (justificantes del banco y tiquets), C2 (firma y pago de honorarios desde el portal) y C3 (carpeta del año)."""
import io
import json
import zipfile

import pytest

from app import db, documenso, facturas_contables as fc, honorarios, justificantes, notificaciones_email, portal_carpeta, portal_firma, portal_pagos, stripe_pagos, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_facturas_contables import PDF
from tests.test_portal_conformidad_cola_cierre import _como_cliente, _declaracion_revisada, correo  # noqa: F401  (fixture de correo)

MOVS = [{"fecha": "2026-08-14", "importe": -31240, "concepto": "PAGO TARJETA FERRETERIA PACO"}, {"fecha": "2026-08-20", "importe": 150000, "concepto": "TRANSFERENCIA CLIENTE X"}]


def _despacho(cliente, email, fiscal=True, contab=True):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant("Despacho " + email); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    if contab:
        verticales.fijar_activo(t, "contabilizacion", True)
    if fiscal:
        verticales.fijar_activo(t, "fiscal", True)
    c = crear_cliente_fiscal(t, "Cliente Justif SL", nif="A12345674", email="cliente-just@ejemplo.com")
    return uid, t, c


def _html(cliente, ruta):
    r = cliente.get(ruta)
    assert r.status_code == 200, ruta
    return r.get_data(as_text=True)


# --- B1: pedir y contestar ----------------------------------------------------------------------------------------------------------------------------

def test_el_despacho_pide_y_no_repite(cliente, correo):
    uid, t, c = _despacho(cliente, "just-pedir@ejemplo.com")
    r = justificantes.pedir(t, uid, c, MOVS)
    assert (r["nuevos"], r["repetidos"], r["avisado"]) == (2, 0, True)
    assert correo and "siguiente=%2Fportal%2Fjustificantes" in correo[0][2]
    r2 = justificantes.pedir(t, uid, c, MOVS + [{"fecha": "2026-08-21", "importe": -500, "concepto": "otro"}])
    assert (r2["nuevos"], r2["repetidos"], r2["avisado"]) == (1, 2, True)
    assert len(justificantes.pendientes_del_cliente(c)) == 3


@pytest.mark.parametrize("mov,mensaje", [({"fecha": "no", "importe": 5, "concepto": "x"}, "fecha o importe"), ({"fecha": "2026-08-14", "importe": 0, "concepto": "x"}, "importe"),
                                         ({"fecha": "2026-08-14", "importe": "abc", "concepto": "x"}, "fecha o importe")])
def test_movimientos_mal_formados_no_se_guardan(cliente, mov, mensaje):
    uid, t, c = _despacho(cliente, "just-mal@ejemplo.com")
    with pytest.raises(ValueError, match=mensaje):
        justificantes.pedir(t, uid, c, [mov])
    with pytest.raises(ValueError, match="al menos un"):
        justificantes.pedir(t, uid, c, [])
    assert justificantes.del_cliente(c) == []


def test_flujo_web_desde_la_conciliacion_hasta_la_respuesta_del_cliente(cliente, correo):
    uid, t, c = _despacho(cliente, "just-web@ejemplo.com")
    valores = [f"{m['fecha']}|{m['importe']}|{m['concepto']}" for m in MOVS]
    r = cliente.post(f"/guilda-fiscal/{c}/conciliacion/justificantes", data={"mov": valores})
    assert r.status_code == 302 and "/contabilidad/justificantes" in r.headers["Location"] and "pedidos=2" in r.headers["Location"]
    lista = _html(cliente, f"/contabilidad/justificantes?cliente_id={c}&pedidos=2&avisado=1")
    assert "FERRETERIA PACO" in lista and "Esperando al cliente" in lista and "Hemos avisado al cliente" in lista

    _como_cliente(cliente, c)
    assert "pregunta por 2 movimientos de tu banco" in _html(cliente, "/portal/")
    pagina = _html(cliente, "/portal/justificantes")
    assert "FERRETERIA PACO" in pagina and "Subir la factura" in pagina and "-312.40" in pagina
    primero = justificantes.pendientes_del_cliente(c)[-1]["id"] if False else min(j["id"] for j in justificantes.pendientes_del_cliente(c))
    r = cliente.post(f"/portal/justificantes/{primero}", data={"accion": "factura"}, content_type="multipart/form-data")
    assert "error=" in r.headers["Location"], "para subir la factura hay que adjuntarla"
    r = cliente.post(f"/portal/justificantes/{primero}", data={"accion": "factura", "comentario": "La de la ferretería", "archivos": (io.BytesIO(PDF), "f.pdf", "application/pdf")}, content_type="multipart/form-data")
    assert r.status_code == 302 and "contestado=factura" in r.headers["Location"]
    j = next(x for x in justificantes.del_cliente(c) if x["id"] == primero)
    assert j["estado"] == "con_factura" and j["factura_id"] and j["comentario"] == "La de la ferretería"
    f = fc.obtener(t, uid, j["factura_id"])
    assert f["origen"] == "portal" and f["tipo"] == "recibida" and "FERRETERIA PACO" in (f["notas"] or "")
    assert "pregunta por 1 movimiento de tu banco" in _html(cliente, "/portal/")
    despacho = _html(cliente, "/contabilidad/justificantes")
    assert "Ha subido la factura" in despacho and "La de la ferretería" in despacho


def test_un_ingreso_se_trata_como_factura_emitida(cliente):
    uid, t, c = _despacho(cliente, "just-ing@ejemplo.com")
    justificantes.pedir(t, uid, c, [MOVS[1]])
    j = justificantes.pendientes_del_cliente(c)[0]
    justificantes.responder(c, j["id"], "factura", "", [("v.pdf", "application/pdf", PDF)])
    assert fc.obtener(t, uid, justificantes.del_cliente(c)[0]["factura_id"])["tipo"] == "emitida"


def test_tiquet_personal_y_no_se(cliente):
    uid, t, c = _despacho(cliente, "just-otros@ejemplo.com")
    justificantes.pedir(t, uid, c, [{"fecha": "2026-08-%02d" % d, "importe": -100 * d, "concepto": f"mov {d}"} for d in (1, 2, 3)])
    a, b, d = (j["id"] for j in sorted(justificantes.pendientes_del_cliente(c), key=lambda x: x["fecha"]))
    justificantes.responder(c, a, "tiquet", "", [("t.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"0" * 100)])
    justificantes.responder(c, b, "personal")
    justificantes.responder(c, d, "no_se", "ni idea")
    est = {j["id"]: j for j in justificantes.del_cliente(c)}
    assert (est[a]["estado"], est[b]["estado"], est[d]["estado"]) == ("tiquet", "personal", "no_se") and est[d]["comentario"] == "ni idea"
    assert justificantes.pendientes_del_cliente(c) == []
    with pytest.raises(ValueError, match="ya no está pendiente"):
        justificantes.responder(c, a, "personal")
    nombre, tipo, contenido = justificantes.documento_de(t, uid, a)
    assert tipo == "image/png" and contenido.startswith(b"\x89PNG")


def test_un_cliente_no_contesta_los_justificantes_de_otro(cliente):
    uid, t, c = _despacho(cliente, "just-aisl@ejemplo.com")
    otro = crear_cliente_fiscal(t, "Otro SL", nif="B87654321", email="otro-j@ejemplo.com")
    justificantes.pedir(t, uid, c, [MOVS[0]])
    j = justificantes.pendientes_del_cliente(c)[0]["id"]
    with pytest.raises(ValueError, match="ya no está pendiente"):
        justificantes.responder(otro, j, "personal")
    _como_cliente(cliente, otro)
    assert "FERRETERIA" not in _html(cliente, "/portal/justificantes")
    assert "error=" in cliente.post(f"/portal/justificantes/{j}", data={"accion": "personal"}).headers["Location"]
    assert justificantes.pendientes_del_cliente(c)[0]["id"] == j


def test_el_cliente_anota_un_tiquet(cliente):
    uid, t, c = _despacho(cliente, "just-tiq@ejemplo.com")
    _como_cliente(cliente, c)
    r = cliente.post("/portal/justificantes/tiquet", data={"fecha": "2026-08-10", "importe": "12,50", "concepto": "Café con un cliente", "archivo": (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"1" * 50), "t.png", "image/png")},
                     content_type="multipart/form-data")
    assert r.status_code == 302 and "tiquet_anotado" in r.headers["Location"]
    j = justificantes.del_cliente(c)[0]
    assert (j["origen"], j["estado"], j["importe_centimos"]) == ("cliente", "tiquet", -1250)
    assert "Es un tiquet" in _html(cliente, f"/contabilidad/justificantes?cliente_id={c}")
    assert "Tiquet del cliente" in _html(cliente, "/contabilidad/justificantes")
    for datos, mensaje in (({"fecha": "2099-01-01", "importe": "5", "concepto": "x"}, "futura"), ({"fecha": "2026-08-10", "importe": "0", "concepto": "x"}, "importe"),
                           ({"fecha": "2026-08-10", "importe": "5", "concepto": " "}, "en qué"), ({"fecha": "2026-08-10", "importe": "12,50", "concepto": "café con un cliente"}, "Ya anotaste")):
        with pytest.raises(ValueError, match=mensaje):
            justificantes.anotar_tiquet(c, datos["fecha"], datos["importe"], datos["concepto"])


def test_el_despacho_resuelve_vuelve_a_pedir_y_descarta(cliente):
    uid, t, c = _despacho(cliente, "just-estado@ejemplo.com")
    justificantes.pedir(t, uid, c, MOVS)
    a, b = (j["id"] for j in justificantes.pendientes_del_cliente(c))
    justificantes.responder(c, a, "no_se", "no sé")
    cliente.post(f"/contabilidad/justificantes/{a}/estado", data={"estado": "resuelto"})
    assert next(j for j in justificantes.listar(t, uid) if j["id"] == a)["estado"] == "resuelto"
    cliente.post(f"/contabilidad/justificantes/{a}/estado", data={"estado": "pendiente"})
    j = next(j for j in justificantes.listar(t, uid) if j["id"] == a)
    assert j["estado"] == "pendiente" and j["comentario"] is None
    cliente.post(f"/contabilidad/justificantes/{b}/estado", data={"estado": "descartado"})
    assert b not in [x["id"] for x in justificantes.del_cliente(c)]
    with pytest.raises(ValueError, match="Estado no válido"):
        justificantes.cambiar_estado(t, uid, a, "exportada")
    otro_t = db.crear_tenant("Otro despacho")
    with pytest.raises(ValueError, match="No encontrado"):
        justificantes.cambiar_estado(otro_t, uid, a, "resuelto")


def test_el_cierre_del_trimestre_cuenta_los_justificantes(cliente):
    from app import cierre_trimestre
    uid, t, c = _despacho(cliente, "just-cierre@ejemplo.com")
    justificantes.pedir(t, uid, c, MOVS)
    puntos = {p["clave"]: p for p in cierre_trimestre.checklist(t, uid, c, "2026-T3")["puntos"]}
    assert puntos["justificantes_sin_contestar"]["cuantos"] == 2 and puntos["justificantes_sin_contestar"]["estado"] == "aviso" and puntos["justificantes_por_cerrar"]["estado"] == "ok"
    justificantes.responder(c, justificantes.pendientes_del_cliente(c)[0]["id"], "personal")
    puntos = {p["clave"]: p for p in cierre_trimestre.checklist(t, uid, c, "2026-T3")["puntos"]}
    assert puntos["justificantes_por_cerrar"]["estado"] == "pendiente" and puntos["justificantes_sin_contestar"]["cuantos"] == 1


def test_sin_contabilizacion_no_se_piden_justificantes(cliente):
    uid, t, c = _despacho(cliente, "just-nocontab@ejemplo.com", contab=False)
    assert cliente.post(f"/guilda-fiscal/{c}/conciliacion/justificantes", data={"mov": ["2026-08-14|-100|x"]}).status_code == 404


# --- C2: firma ----------------------------------------------------------------------------------------------------------------------------------------------

def _con_documento_a_firmar(cliente, email):
    uid, t, c = _despacho(cliente, email)
    db.guardar_documenso_api_key(t, "clave-de-prueba")
    v = db.crear_vencimiento_fiscal(t, c, "036", "2026-T3", "2026-12-20", usuario_id=uid)
    db.editar_vencimiento_fiscal(t, v, documenso_documento_id="env_1")
    return uid, t, c, v


def _envelope(estado="PENDING", firmado="NOT_SIGNED", email="cliente-just@ejemplo.com"):
    return {"status": estado, "recipients": [{"email": email, "role": "SIGNER", "signingStatus": firmado, "token": "tok123"}]}


def test_la_firma_pendiente_sale_en_para_hacer_y_lleva_a_la_pagina_de_firma(cliente, monkeypatch):
    uid, t, c, v = _con_documento_a_firmar(cliente, "firma1@ejemplo.com")
    monkeypatch.setattr(documenso, "obtener_documento", lambda clave, ident: _envelope())
    _como_cliente(cliente, c)
    inicio = _html(cliente, "/portal/")
    assert "documento por firmar: 036 2026-T3" in inicio and f"/portal/vencimientos/{v}/firma" in inicio
    pagina = _html(cliente, f"/portal/vencimientos/{v}/firma")
    assert "Firmar ahora" in pagina and f"{documenso.DOCUMENSO_URL}/sign/tok123" in pagina


def test_si_ya_firmo_se_anota_y_deja_de_pedirse(cliente, monkeypatch):
    uid, t, c, v = _con_documento_a_firmar(cliente, "firma2@ejemplo.com")
    monkeypatch.setattr(documenso, "obtener_documento", lambda clave, ident: _envelope("COMPLETED", "SIGNED"))
    _como_cliente(cliente, c)
    assert "Firmado" in _html(cliente, f"/portal/vencimientos/{v}/firma")
    assert db.obtener_vencimiento_fiscal(t, v)["documenso_firmado_en"]
    assert "documento por firmar" not in _html(cliente, "/portal/")


@pytest.mark.parametrize("envelope,texto", [(_envelope("REJECTED", "REJECTED"), "Rechazado"), (_envelope("PENDING", "SIGNED"), "Firmado")])
def test_otros_estados_de_la_firma(cliente, monkeypatch, envelope, texto):
    uid, t, c, v = _con_documento_a_firmar(cliente, f"firma3-{texto}@ejemplo.com")
    monkeypatch.setattr(documenso, "obtener_documento", lambda clave, ident: envelope)
    _como_cliente(cliente, c)
    assert texto in _html(cliente, f"/portal/vencimientos/{v}/firma")


def test_si_documenso_no_responde_no_se_rompe_nada(cliente, monkeypatch):
    uid, t, c, v = _con_documento_a_firmar(cliente, "firma4@ejemplo.com")
    def falla(*a):
        raise documenso.ErrorDocumenso("caído")
    monkeypatch.setattr(documenso, "obtener_documento", falla)
    _como_cliente(cliente, c)
    assert "no podemos comprobar" in _html(cliente, f"/portal/vencimientos/{v}/firma")
    assert "documento por firmar" in _html(cliente, "/portal/")


def test_la_firma_solo_es_del_propio_cliente(cliente, monkeypatch):
    uid, t, c, v = _con_documento_a_firmar(cliente, "firma5@ejemplo.com")
    otro = crear_cliente_fiscal(t, "Otro SL", nif="B87654321", email="otro-f@ejemplo.com")
    _como_cliente(cliente, otro)
    assert cliente.get(f"/portal/vencimientos/{v}/firma").status_code == 404
    sin_doc = db.crear_vencimiento_fiscal(t, otro, "303", "2026-T3", "2026-10-20")
    assert cliente.get(f"/portal/vencimientos/{sin_doc}/firma").status_code == 404


def test_el_webhook_deja_constancia_de_la_firma(monkeypatch):
    t = db.crear_tenant("Despacho webhook firma")
    db.guardar_documenso_api_key(t, "clave")
    c = crear_cliente_fiscal(t, "C", nif="B1")
    v = db.crear_vencimiento_fiscal(t, c, "036", "2026-T3", "2026-12-20")
    db.editar_vencimiento_fiscal(t, v, documenso_documento_id="env_wh")
    monkeypatch.setattr(documenso, "estado_documento", lambda clave, ident: "PENDING")
    assert portal_firma.marcar_por_documenso("env_wh") == 0
    monkeypatch.setattr(documenso, "estado_documento", lambda clave, ident: "COMPLETED")
    assert portal_firma.marcar_por_documenso("env_wh") == 1 and db.obtener_vencimiento_fiscal(t, v)["documenso_firmado_en"]


def test_enlace_de_firma_solo_del_firmante_que_no_ha_firmado():
    assert documenso.enlace_de_firma(_envelope(), "CLIENTE-just@ejemplo.com", "https://f.example/") == "https://f.example/sign/tok123"
    assert documenso.enlace_de_firma(_envelope(firmado="SIGNED"), "cliente-just@ejemplo.com") is None
    assert documenso.enlace_de_firma(_envelope(), "otro@ejemplo.com") is None


# --- C2: honorarios y pago -----------------------------------------------------------------------------------------------------------------------------

def _con_honorarios(cliente, email, visible=True, stripe=True):
    uid, t, c = _despacho(cliente, email)
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T2", "2026-07-20", usuario_id=uid)
    conn = db.get_connection()
    conn.execute("INSERT INTO honorarios_aplicados (tenant_id, vencimiento_id, cliente_fiscal_id, regla_nombre, concepto, importe_centimos, estado, confirmado_en) VALUES (?, ?, ?, 'Fija', 'Honorarios 303 2T 2026', 4500, 'confirmado', ?)",
                 (t, v, c, db.now_iso()))
    if visible:
        conn.execute("UPDATE clientes_fiscales SET portal_honorarios = 1 WHERE id = ?", (c,))
    if stripe:
        conn.execute("UPDATE tenants SET stripe_account_id = 'acct_prueba' WHERE id = ?", (t,))
    conn.commit(); conn.close()
    return uid, t, c, v


def test_los_honorarios_solo_se_enseñan_si_el_despacho_lo_activa(cliente, monkeypatch):
    monkeypatch.setattr(stripe_pagos, "configurado", lambda: True)
    uid, t, c, v = _con_honorarios(cliente, "pago0@ejemplo.com", visible=False)
    _como_cliente(cliente, c)
    assert "Honorarios" not in _html(cliente, "/portal/impuestos") and "honorarios pendiente" not in _html(cliente, "/portal/")
    assert "error=" in cliente.post(f"/portal/vencimientos/{v}/pagar").headers["Location"]


def test_el_cliente_ve_el_importe_y_paga_con_stripe(cliente, monkeypatch):
    monkeypatch.setattr(stripe_pagos, "configurado", lambda: True)
    llamadas = []
    monkeypatch.setattr(stripe_pagos, "crear_sesion_pago", lambda cuenta, importe, concepto, ok, cancel, moneda="eur", metadata=None: llamadas.append((cuenta, importe, concepto, ok, cancel, metadata)) or "https://checkout.stripe.test/s1")
    uid, t, c, v = _con_honorarios(cliente, "pago1@ejemplo.com")
    _como_cliente(cliente, c)
    assert "1 pago de honorarios pendiente" in _html(cliente, "/portal/")
    pagina = _html(cliente, "/portal/impuestos")
    assert "45.00 €" in pagina and "Pagar con tarjeta" in pagina
    r = cliente.post(f"/portal/vencimientos/{v}/pagar")
    assert r.status_code == 303 and r.headers["Location"] == "https://checkout.stripe.test/s1"
    cuenta, importe, concepto, ok, cancel, meta = llamadas[0]
    assert (cuenta, importe, meta) == ("acct_prueba", 4500, {"vencimiento_id": v}) and "Honorarios 303 2T 2026" in concepto and "pago=ok" in ok and "pago=cancelado" in cancel


def test_un_pago_ya_hecho_no_se_repite_y_aparece_pagado(cliente, monkeypatch):
    monkeypatch.setattr(stripe_pagos, "configurado", lambda: True)
    monkeypatch.setattr(stripe_pagos, "crear_sesion_pago", lambda *a, **k: pytest.fail("no debe abrir otro pago"))
    uid, t, c, v = _con_honorarios(cliente, "pago2@ejemplo.com")
    db.registrar_pago_vencimiento(v, "cs_1", 4500)
    _como_cliente(cliente, c)
    pagina = _html(cliente, "/portal/impuestos")
    assert "Pagado" in pagina and "Pagar con tarjeta" not in pagina and "honorarios pendiente" not in _html(cliente, "/portal/")
    assert "error=" in cliente.post(f"/portal/vencimientos/{v}/pagar").headers["Location"]


def test_sin_stripe_se_enseña_el_importe_pero_no_el_boton(cliente, monkeypatch):
    monkeypatch.setattr(stripe_pagos, "configurado", lambda: True)
    uid, t, c, v = _con_honorarios(cliente, "pago3@ejemplo.com", stripe=False)
    _como_cliente(cliente, c)
    pagina = _html(cliente, "/portal/impuestos")
    assert "45.00 €" in pagina and "Pagar con tarjeta" not in pagina and "te indicará cómo pagarlo" in pagina


def test_si_stripe_falla_el_cliente_ve_un_mensaje(cliente, monkeypatch):
    monkeypatch.setattr(stripe_pagos, "configurado", lambda: True)
    def falla(*a, **k):
        raise stripe_pagos.ErrorStripe("caído")
    monkeypatch.setattr(stripe_pagos, "crear_sesion_pago", falla)
    uid, t, c, v = _con_honorarios(cliente, "pago4@ejemplo.com")
    _como_cliente(cliente, c)
    r = cliente.post(f"/portal/vencimientos/{v}/pagar")
    assert r.status_code == 302 and "error=" in r.headers["Location"]


def test_el_pago_de_otro_cliente_no_se_abre(cliente, monkeypatch):
    monkeypatch.setattr(stripe_pagos, "configurado", lambda: True)
    monkeypatch.setattr(stripe_pagos, "crear_sesion_pago", lambda *a, **k: pytest.fail("no debe abrir el pago de otro"))
    uid, t, c, v = _con_honorarios(cliente, "pago5@ejemplo.com")
    otro = crear_cliente_fiscal(t, "Otro SL", nif="B87654321", email="otro-p@ejemplo.com")
    _como_cliente(cliente, otro)
    assert cliente.post(f"/portal/vencimientos/{v}/pagar").status_code == 404


def test_la_ficha_activa_los_honorarios_en_el_portal(cliente):
    uid, t, c = _despacho(cliente, "pago6@ejemplo.com")
    assert "Enseñar en su portal los honorarios" in _html(cliente, f"/fiscal/clientes/{c}/editar")
    cliente.post(f"/fiscal/clientes/{c}/editar", data={"nombre": "Cliente Justif SL", "nif": "A12345674", "email": "cliente-just@ejemplo.com", "portal_honorarios": "on", "recordatorios_portal": "on", "pais": "ES"})
    assert db.obtener_cliente_fiscal_por_id(c)["portal_honorarios"] == 1


# --- C3: carpeta del año ---------------------------------------------------------------------------------------------------------------------------------

def _con_carpeta(cliente, email):
    uid, t, c = _despacho(cliente, email)
    d = _declaracion_revisada(t, uid, c)
    from app import fiscal_nucleo as fn
    fn.exportar_declaracion(t, uid, d)
    fn.marcar_presentada(t, uid, d, justificante="3030000000123")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2T 2026", "2026-07-20", usuario_id=uid)
    db.subir_documento_vencimiento(v, "justificante-303.pdf", "application/pdf", PDF, origen="justificante")
    db.subir_documento_vencimiento(v, "constancia.pdf", "application/pdf", PDF + b"x", origen="constancia")
    db.subir_documento_vencimiento(v, "mi-extracto.pdf", "application/pdf", PDF + b"y", origen="cliente")
    fc.crear_desde_portal(c, {"tipo": "recibida", "fecha": "2026-05-10", "numero": "P-1", "tercero_nombre": "X", "tercero_nif": "B1", "total": "10", "pct_iva": "21"})
    return uid, t, c, v, d


def test_la_carpeta_reune_justificantes_informes_y_resumenes(cliente):
    uid, t, c, v, d = _con_carpeta(cliente, "carpeta1@ejemplo.com")
    _como_cliente(cliente, c)
    pagina = _html(cliente, "/portal/carpeta?anio=2026")
    assert "Mi carpeta de 2026" in pagina and "justificante-303.pdf" in pagina and "constancia.pdf" in pagina and "mi-extracto.pdf" not in pagina
    assert "Informe del 2T 2026" in pagina and "Modelo 303 · 2T 2026" in pagina and "Descargar todo el año" in pagina
    assert 'class="portal-nav"' in pagina and "/portal/carpeta" in pagina
    pdf = cliente.get(f"/portal/carpeta/resumen/{d}.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    assert cliente.get("/portal/facturas/informe.pdf?trimestre=2026-T2").data.startswith(b"%PDF")


def test_el_zip_del_año_lleva_todo_lo_visible(cliente):
    uid, t, c, v, d = _con_carpeta(cliente, "carpeta2@ejemplo.com")
    _como_cliente(cliente, c)
    r = cliente.get("/portal/carpeta/2026.zip")
    assert r.status_code == 200 and r.mimetype == "application/zip"
    nombres = zipfile.ZipFile(io.BytesIO(r.data)).namelist()
    assert any(n.startswith("justificantes/303-") and n.endswith("justificante-303.pdf") for n in nombres) and any(n.endswith("constancia.pdf") for n in nombres)
    assert "informes/informe-2026-T2.pdf" in nombres and "resumenes/303-2026-2T.pdf" in nombres and not any("extracto" in n for n in nombres)
    assert cliente.get("/portal/carpeta/1999.zip").status_code == 404


def test_la_carpeta_es_solo_del_cliente(cliente):
    uid, t, c, v, d = _con_carpeta(cliente, "carpeta3@ejemplo.com")
    otro = crear_cliente_fiscal(t, "Otro SL", nif="B87654321", email="otro-c@ejemplo.com")
    _como_cliente(cliente, otro)
    assert "justificante-303.pdf" not in _html(cliente, "/portal/carpeta")
    assert cliente.get(f"/portal/carpeta/resumen/{d}.pdf").status_code == 404
    assert cliente.get("/portal/carpeta/2026.zip").status_code == 404


def test_una_declaracion_no_presentada_no_va_a_la_carpeta(cliente):
    uid, t, c = _despacho(cliente, "carpeta4@ejemplo.com")
    d = _declaracion_revisada(t, uid, c)
    fc.crear_desde_portal(c, {"tipo": "recibida", "fecha": "2026-05-10", "numero": "P-1", "tercero_nombre": "X", "tercero_nif": "B1", "total": "10", "pct_iva": "21"})
    _como_cliente(cliente, c)
    assert "Modelo 303 ·" not in _html(cliente, "/portal/carpeta?anio=2026")
    assert cliente.get(f"/portal/carpeta/resumen/{d}.pdf").status_code == 404


def test_sin_nada_la_carpeta_lo_dice(cliente):
    uid, t, c = _despacho(cliente, "carpeta5@ejemplo.com", fiscal=False)
    _como_cliente(cliente, c)
    assert "Todavía no hay nada en la carpeta" in _html(cliente, "/portal/carpeta")
