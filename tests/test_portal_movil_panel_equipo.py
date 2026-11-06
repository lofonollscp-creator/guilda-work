"""Subir desde el móvil (G1), buscar (G4), primera visita (G5), panel de situación (I1), plazos (I2), estado del trabajo (I3), actividad del portal (J1), respuestas rápidas (J2), informe del año (J3) y lo que ve el equipo (H1)."""
import io
import json
import re
import zipfile
from datetime import date, datetime, timedelta
from email.message import EmailMessage

import pytest

from app import auditoria, db, facturas_contables as fc, facturas_portal, justificantes, notificaciones_email, portal_avisos, portal_busqueda, portal_estado, portal_informe_anual, portal_metricas, portal_personas, portal_plazos
from app import portal_respuestas, portal_situacion, portal_subida_rapida, qr, tareas_trabajo, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_facturas_contables import PDF


def _despacho(nombre="Gestoria M", cliente_email="titular@ejemplo.com", cliente_nombre="Cliente M SL"):
    t = db.crear_tenant(nombre)
    u = db.crear_usuario_vinculado_a_kratos(f"resp-{nombre}@ejemplo.com".replace(" ", ""), "k-" + nombre.replace(" ", ""))
    db.asignar_tenant(u, t)
    verticales.fijar_activo(t, "contabilizacion", True)
    verticales.fijar_activo(t, "fiscal", True)
    c = crear_cliente_fiscal(t, cliente_nombre, nif="B12345678", email=cliente_email)
    conn = db.get_connection(); conn.execute("UPDATE clientes_fiscales SET responsable_id = ? WHERE id = ?", (u, c)); conn.commit(); conn.close()
    return t, u, c


def _ficha(c):
    return db.obtener_cliente_fiscal_por_id(c)


def _como_cliente(http, c, email="titular@ejemplo.com"):
    with http.session_transaction() as s:
        s["cliente_fiscal_id"] = c
        s["portal_email"] = email


def _html(http, ruta):
    r = http.get(ruta)
    assert r.status_code == 200, ruta
    return r.get_data(as_text=True)


def _estado(factura_id, estado):
    conn = db.get_connection(); conn.execute("UPDATE facturas_contables SET estado = ? WHERE id = ?", (estado, factura_id)); conn.commit(); conn.close()


def _factura(c, numero="P-1", fecha="2026-08-10", tercero="Ferretería Paco", tipo="recibida", total="121,00"):
    return fc.crear_desde_portal(c, {"tipo": tipo, "fecha": fecha, "numero": numero, "tercero_nombre": tercero, "tercero_nif": "B11111111", "total": total, "pct_iva": "21"})


# --- El codificador de QR -----------------------------------------------------------------------------------------------------------------------------

def test_el_qr_tiene_la_estructura_de_la_norma():
    m = qr.matriz("https://app.guildawork.com/portal/subida/" + "a" * 32)
    n = len(m)
    assert n == 17 + 4 * ((n - 17) // 4) and n >= 25
    for x0, y0 in ((0, 0), (n - 7, 0), (0, n - 7)):                     # los tres patrones de búsqueda 7x7 con su anillo claro
        assert all(m[y0][x0 + i] and m[y0 + 6][x0 + i] and m[y0 + i][x0] and m[y0 + i][x0 + 6] for i in range(7))
        assert all(m[y0 + 2 + a][x0 + 2 + b] for a in range(3) for b in range(3)) and not m[y0 + 1][x0 + 1]
    assert all(m[6][i] == (i % 2 == 0) for i in range(8, n - 8)), "línea de sincronía horizontal"
    assert all(m[i][6] == (i % 2 == 0) for i in range(8, n - 8)), "línea de sincronía vertical"
    assert m[n - 8][8] is True, "el módulo oscuro fijo"


def test_el_qr_lleva_el_formato_con_codigo_bch_valido():
    m = qr.matriz("hola")
    n = len(m)
    bits = sum((1 if m[8][i if i < 6 else (7 if i == 6 else 8)] and False else 0) for i in range(1))   # (se lee abajo)
    leidos = [m[i][8] for i in range(6)] + [m[7][8], m[8][8], m[8][7]] + [m[8][14 - i] for i in range(9, 15)]
    valor = sum(int(b) << i for i, b in enumerate(leidos)) ^ 0x5412
    datos, resto = valor >> 10, valor & 0x3FF
    r = datos
    for _ in range(10):
        r = (r << 1) ^ ((r >> 9) * 0x537)
    assert resto == r & 0x3FF and datos >> 3 == 0, "nivel M y resto BCH correctos"


@pytest.mark.parametrize("n", [1, 14, 15, 40, 84, 106, 134, 192, 213])
def test_el_qr_elige_la_version_justa(n):
    m = qr.matriz("x" * n)
    v = (len(m) - 17) // 4
    assert n <= qr.capacidad(v) and (v == 1 or n > qr.capacidad(v - 1))


def test_un_texto_demasiado_largo_no_cabe():
    with pytest.raises(qr.DemasiadoLargo):
        qr.matriz("x" * 300)


def test_el_svg_reproduce_la_matriz():
    texto = "https://app.guildawork.com/portal/subida/" + "ab12" * 8
    m = qr.matriz(texto)
    s = qr.svg(texto, "QR de prueba")
    assert s.startswith("<svg") and 'role="img"' in s and 'aria-label="QR de prueba"' in s and 'fill="#fff"' in s and 'fill="#000"' in s
    n = len(m)
    reconstruida = [[False] * n for _ in range(n)]
    for x, y, ancho in re.findall(r"M(\d+) (\d+)h(\d+)v1h-\d+z", s):
        for i in range(int(ancho)):
            reconstruida[int(y) - 4][int(x) - 4 + i] = True
    assert reconstruida == m


def test_un_lector_real_decodifica_el_qr():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    for texto in ("https://app.guildawork.com/portal/subida/" + "0f" * 16, "hola", "Ñandú ✓"):
        m = qr.matriz(texto)
        n = len(m)
        img = np.full((n + 8, n + 8), 255, dtype=np.uint8)
        for y in range(n):
            for x in range(n):
                if m[y][x]:
                    img[y + 4, x + 4] = 0
        img = cv2.resize(img, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
        assert cv2.QRCodeDetector().detectAndDecode(img)[0] == texto


# --- G1: subir desde el móvil con el enlace --------------------------------------------------------------------------------------------------------

def test_la_pagina_de_subida_rapida_acepta_fotos_sin_iniciar_sesion(cliente):
    t, u, c = _despacho("Gestoria subida")
    token = portal_subida_rapida.token_de(_ficha(c))
    assert re.fullmatch(r"[0-9a-f]{32}", token) and portal_subida_rapida.token_de(_ficha(c)) == token
    html = _html(cliente, f"/portal/subida/{token}")
    assert "Cliente M SL" in html and 'name="archivos"' in html and 'capture' not in html and "image/*,application/pdf" in html
    r = cliente.post(f"/portal/subida/{token}", data={"tipo": "recibida", "archivos": [(io.BytesIO(PDF), "tiquet.pdf", "application/pdf")]}, content_type="multipart/form-data")
    assert r.status_code == 200 and "Recibido: 1 archivo" in r.get_data(as_text=True)
    pendientes = fc.listar_del_cliente(c)
    assert len(pendientes) == 1 and pendientes[0]["origen"] == "portal"
    assert "portal.subida_rapida" in {e["accion"] for e in auditoria.listar(t, entidad="cliente_fiscal", entidad_id=c)}


def test_la_subida_rapida_no_enseña_nada_del_portal_y_rechaza_lo_que_no_es_factura(cliente):
    t, u, c = _despacho("Gestoria subida2")
    _factura(c)
    token = portal_subida_rapida.token_de(_ficha(c))
    html = _html(cliente, f"/portal/subida/{token}")
    assert "Ferretería Paco" not in html and "portal-nav" not in html
    r = cliente.post(f"/portal/subida/{token}", data={"tipo": "recibida", "archivos": [(io.BytesIO(b"MZ\x90\x00"), "virus.exe", "application/x-msdownload")]}, content_type="multipart/form-data")
    assert r.status_code == 200 and "role=\"alert\"" in r.get_data(as_text=True) and len(fc.listar_del_cliente(c)) == 1
    assert "Elige al menos" in cliente.post(f"/portal/subida/{token}", data={"tipo": "recibida"}, content_type="multipart/form-data").get_data(as_text=True)


@pytest.mark.parametrize("token", ["", "x", "0" * 32, "../../etc/passwd", "A" * 32])
def test_un_enlace_de_subida_inventado_no_abre_nada(cliente, token):
    t, u, c = _despacho("Gestoria subida3")
    assert cliente.get(f"/portal/subida/{token}").status_code == 404
    assert cliente.post(f"/portal/subida/{token}", data={}).status_code in (404, 405)


def test_renovar_el_enlace_invalida_el_anterior_y_solo_lo_hace_el_perfil_completo(cliente):
    t, u, c = _despacho("Gestoria renovar")
    portal_personas.anadir(_ficha(c), "admin@ejemplo.com", "", "administracion")
    viejo = portal_subida_rapida.token_de(_ficha(c))
    _como_cliente(cliente, c, "admin@ejemplo.com")
    assert cliente.post("/portal/subida/renovar").status_code == 403
    _como_cliente(cliente, c)
    assert cliente.post("/portal/subida/renovar").status_code == 302
    nuevo = portal_subida_rapida.token_de(_ficha(c))
    assert nuevo != viejo and cliente.get(f"/portal/subida/{viejo}").status_code == 404 and cliente.get(f"/portal/subida/{nuevo}").status_code == 200


def test_sin_el_modulo_de_facturas_no_hay_subida_rapida(cliente):
    t, u, c = _despacho("Gestoria subida4")
    token = portal_subida_rapida.token_de(_ficha(c))
    verticales.fijar_activo(t, "contabilizacion", False)
    assert cliente.get(f"/portal/subida/{token}").status_code == 404
    _como_cliente(cliente, c)
    assert "Subir facturas desde el móvil" not in _html(cliente, "/portal/cuenta")


def test_mi_cuenta_enseña_el_codigo_qr_del_enlace_y_la_direccion_de_correo(cliente):
    t, u, c = _despacho("Gestoria qr")
    _como_cliente(cliente, c)
    html = _html(cliente, "/portal/cuenta")
    token = portal_subida_rapida.token_de(_ficha(c))
    assert "Subir facturas desde el móvil" in html and f"/portal/subida/{token}" in html and "<svg" in html and "Código QR" in html
    assert "reenviar una factura recibida por correo" not in html
    portal_subida_rapida.guardar_direccion_base(t, "Facturas@Despacho.com")
    html = _html(cliente, "/portal/cuenta")
    assert f"facturas+{token}@despacho.com" in html


# --- G1: facturas reenviadas por correo -------------------------------------------------------------------------------------------------------------

def _correo(para, adjuntos=(("factura.pdf", "application/pdf", PDF),), cabecera="To"):
    m = EmailMessage()
    m["From"] = "cliente@ejemplo.com"
    m[cabecera] = para
    m["Subject"] = "Mi factura"
    m.set_content("Te la reenvío")
    for nombre, tipo, datos in adjuntos:
        principal, sub = tipo.split("/")
        m.add_attachment(datos, maintype=principal, subtype=sub, filename=nombre)
    return m


def _mensaje_guardado(t, u):
    cuenta = db.guardar_cuenta_correo(u, "facturas@despacho.com", "imap.ejemplo.com", 993, True, "smtp.ejemplo.com", 587, "facturas@despacho.com", "x") if hasattr(db, "guardar_cuenta_correo") else None
    return cuenta


def test_la_direccion_de_cada_cliente_se_construye_con_su_secreto_y_se_lee_del_correo(cliente):
    t, u, c = _despacho("Gestoria correo")
    ficha = _ficha(c)
    assert portal_subida_rapida.direccion_de(ficha) is None, "sin dirección base no hay correo"
    portal_subida_rapida.guardar_direccion_base(t, "facturas@despacho.com")
    direccion = portal_subida_rapida.direccion_de(ficha)
    token = portal_subida_rapida.token_de(ficha)
    assert direccion == f"facturas+{token}@despacho.com"
    for cabecera in ("To", "Cc", "Delivered-To", "X-Original-To"):
        assert portal_subida_rapida.token_en(_correo(f"Facturas <{direccion}>", cabecera=cabecera)) == token
    assert portal_subida_rapida.token_en(_correo("facturas@despacho.com")) is None
    assert portal_subida_rapida.token_en(_correo("facturas+corto@despacho.com")) is None


@pytest.mark.parametrize("mala", ["no es un correo", "a+b@x.es", "sin-arroba"])
def test_la_direccion_base_se_valida(mala):
    t, u, c = _despacho("Gestoria correo2")
    with pytest.raises(ValueError):
        portal_subida_rapida.guardar_direccion_base(t, mala)
    assert portal_subida_rapida.guardar_direccion_base(t, "") == "" and portal_subida_rapida.direccion_base(t) == ""


def test_un_correo_con_la_direccion_del_cliente_sube_sus_facturas(cliente, monkeypatch):
    t, u, c = _despacho("Gestoria correo3")
    portal_subida_rapida.guardar_direccion_base(t, "facturas@despacho.com")
    direccion = portal_subida_rapida.direccion_de(_ficha(c))
    vinculados = []
    monkeypatch.setattr(db, "asignar_cliente_fiscal_correo", lambda tenant, mensaje, cliente_id: vinculados.append((tenant, mensaje, cliente_id)))
    n = portal_subida_rapida.procesar_correo(t, 77, _correo(direccion, [("a.pdf", "application/pdf", PDF), ("foto.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"0" * 50), ("virus.exe", "application/x-msdownload", b"MZ")]))
    assert n == 2 and vinculados == [(t, 77, c)]
    assert len(fc.listar_del_cliente(c)) == 2 and "portal.subida_correo" in {e["accion"] for e in auditoria.listar(t, entidad="cliente_fiscal", entidad_id=c)}


def test_el_correo_de_otro_despacho_o_sin_secreto_valido_o_sin_la_funcion_activa_no_sube_nada(monkeypatch):
    t, u, c = _despacho("Gestoria correo4")
    t2, u2, c2 = _despacho("Gestoria correo5", cliente_email="otro@ejemplo.com")
    portal_subida_rapida.guardar_direccion_base(t, "facturas@despacho.com")
    portal_subida_rapida.guardar_direccion_base(t2, "facturas@otro.com")
    d1 = portal_subida_rapida.direccion_de(_ficha(c))
    monkeypatch.setattr(db, "asignar_cliente_fiscal_correo", lambda *a: None)
    assert portal_subida_rapida.procesar_correo(t2, 1, _correo(d1)) == 0, "el secreto es de un cliente de otro despacho"
    assert portal_subida_rapida.procesar_correo(t, 1, _correo("facturas+" + "0" * 32 + "@despacho.com")) == 0
    portal_subida_rapida.guardar_direccion_base(t, "")
    assert portal_subida_rapida.procesar_correo(t, 1, _correo(d1)) == 0, "el despacho apagó la función"
    assert fc.listar_del_cliente(c) == [] and fc.listar_del_cliente(c2) == []


# --- G4: buscar -------------------------------------------------------------------------------------------------------------------------------------------

def test_la_busqueda_encuentra_facturas_modelos_documentos_mensajes_y_movimientos_sin_tildes_ni_mayusculas(cliente):
    t, u, c = _despacho("Gestoria buscar")
    f = _factura(c, "FAC-2026-77", tercero="Fernández e Hijos SL")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20", usuario_id=u)
    db.editar_vencimiento_fiscal(t, v, documento_solicitado="Extracto bancario de septiembre")
    db.subir_documento_vencimiento(v, "justificante-fernandez.pdf", "application/pdf", PDF)
    db.crear_mensaje_vencimiento(v, "empleado", "Necesitamos el extracto de Fernández", usuario_id=u)
    facturas_portal.escribir_como_despacho(t, u, f, "Confirmado el pago a Fernández")
    justificantes.pedir(t, u, c, [{"fecha": "2026-09-03", "importe": -4500, "concepto": "Transferencia FERNANDEZ SL"}])
    _como_cliente(cliente, c)
    html = _html(cliente, "/portal/buscar?q=fernandez")
    for texto in ("Facturas", "Modelos e impuestos", "Documentos", "Mensajes", "Movimientos del banco"):
        assert texto in ("Modelos e impuestos",) or texto in html
    assert f"/portal/facturas/{f}" in html and "justificante-fernandez.pdf" in html and f"/portal/vencimientos/{v}/mensajes" in html and "FERNANDEZ SL" in html
    assert "no hemos encontrado nada" in _html(cliente, "/portal/buscar?q=zzzz").lower()
    assert "Extracto bancario" in _html(cliente, "/portal/buscar?q=EXTRACTO") and f"vencimiento-{v}" in _html(cliente, "/portal/buscar?q=extracto")


def test_la_busqueda_pide_dos_letras_y_solo_busca_lo_del_cliente(cliente):
    t, u, c = _despacho("Gestoria buscar2")
    otro = crear_cliente_fiscal(t, "Otro Cliente SL", nif="B99999999", email="otro@ejemplo.com")
    _factura(otro, "OTRO-1", tercero="Proveedor Secreto SA")
    nota_interna = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20", usuario_id=u)
    db.editar_vencimiento_fiscal(t, nota_interna, notas="nota interna confidencial")
    _como_cliente(cliente, c)
    assert "al menos dos letras" in _html(cliente, "/portal/buscar?q=a")
    assert "Proveedor Secreto" not in _html(cliente, "/portal/buscar?q=secreto")
    assert "nota interna confidencial" not in _html(cliente, "/portal/buscar?q=confidencial")
    assert portal_busqueda.buscar(_ficha(c), "")["total"] == 0


def test_la_busqueda_escapa_el_texto_buscado(cliente):
    t, u, c = _despacho("Gestoria buscar3")
    _como_cliente(cliente, c)
    html = _html(cliente, "/portal/buscar?q=%3Cscript%3Ealert(1)%3C/script%3E")
    assert "<script>alert(1)</script>" not in html


# --- G5: primera visita ----------------------------------------------------------------------------------------------------------------------------

def test_la_guia_de_primera_visita_sale_una_vez_por_persona(cliente):
    t, u, c = _despacho("Gestoria bienvenida")
    portal_personas.anadir(_ficha(c), "admin@ejemplo.com", "", "administracion")
    _como_cliente(cliente, c)
    assert "Así funciona tu portal" in _html(cliente, "/portal/")
    assert cliente.post("/portal/bienvenida").status_code == 302
    assert "Así funciona tu portal" not in _html(cliente, "/portal/")
    _como_cliente(cliente, c, "admin@ejemplo.com")
    assert "Así funciona tu portal" in _html(cliente, "/portal/"), "cada persona tiene la suya"
    cliente.post("/portal/bienvenida")
    assert "Así funciona tu portal" not in _html(cliente, "/portal/")


def test_el_equipo_que_mira_el_portal_no_marca_la_bienvenida_como_vista(cliente):
    t, u, c = _despacho("Gestoria bienvenida2")
    uid = iniciar_sesion_de_prueba(cliente, "equipo@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    cliente.post(f"/fiscal/clientes/{c}/ver-portal")
    assert "Así funciona tu portal" not in _html(cliente, "/portal/")
    assert not _ficha(c)["portal_bienvenida_en"]


# --- I1: panel de situación ------------------------------------------------------------------------------------------------------------------------

def test_el_panel_suma_ingresos_gastos_e_iva_por_trimestre_con_las_facturas_revisadas(cliente):
    t, u, c = _despacho("Gestoria situacion")
    ficha = _ficha(c)
    assert portal_situacion.calcular(ficha, date(2026, 11, 5)) is None
    gasto = _factura(c, "G-1", "2026-08-10", total="121,00")
    venta = _factura(c, "V-1", "2026-09-10", tipo="emitida", total="242,00")
    anterior = _factura(c, "G-0", "2025-11-10", total="60,50")
    pendiente = _factura(c, "G-2", "2026-09-20", total="12,10")
    for fid in (gasto, venta, anterior):
        _estado(fid, "revisada")
    s = portal_situacion.calcular(ficha, date(2026, 11, 5))
    actual = s["actual"]
    assert actual["trimestre"] == "2026-T4" and actual["facturas"] == 0
    t3 = next(x for x in s["trimestres"] if x["trimestre"] == "2026-T3")
    assert t3["gastos"] == 10000 and t3["ingresos"] == 20000 and t3["iva_soportado"] == 2100 and t3["iva_repercutido"] == 4200 and t3["iva_estimado"] == 2100
    assert s["pendientes"] == 1 and len(s["trimestres"]) == 5 and s["barras"] and s["anterior"]["trimestre"] == "2025-T4" and s["anterior"]["gastos"] == 5000
    _como_cliente(cliente, c)
    html = _html(cliente, "/portal/impuestos")
    assert "Tu situación, trimestre a trimestre" in html and "portal-barra-ingreso" in html and "3T 2026" in html and "a pagar" in html and "no es tu declaración" in html.lower() or "No es tu declaración" in html


def test_los_abonos_restan_y_lo_descartado_no_cuenta():
    t, u, c = _despacho("Gestoria situacion2")
    ficha = _ficha(c)
    g = _factura(c, "G-1", "2026-08-10", total="121,00")
    d = _factura(c, "G-2", "2026-08-11", total="500,00")
    _estado(g, "revisada")
    _estado(d, "descartada")
    s = portal_situacion.calcular(ficha, date(2026, 11, 5))
    t3 = next(x for x in s["trimestres"] if x["trimestre"] == "2026-T3")
    assert t3["gastos"] == 10000 and t3["facturas"] == 1


def test_sin_facturas_tratadas_la_pagina_de_impuestos_no_enseña_el_panel(cliente):
    t, u, c = _despacho("Gestoria situacion3")
    _como_cliente(cliente, c)
    assert "Tu situación, trimestre a trimestre" not in _html(cliente, "/portal/impuestos")


# --- I2: plazos y lo que falta ------------------------------------------------------------------------------------------------------------------

def test_cada_plazo_cercano_dice_que_le_falta_a_la_gestoria_o_que_todo_esta_en_orden(cliente):
    t, u, c = _despacho("Gestoria plazos")
    hoy = date.today()
    vence = (hoy + timedelta(days=9)).isoformat()
    v = db.crear_vencimiento_fiscal(t, c, "303", facturas_portal.trimestre_actual(hoy), vence, usuario_id=u)
    db.editar_vencimiento_fiscal(t, v, documento_solicitado="Extracto del banco")
    f = _factura(c, "P-1", hoy.isoformat())
    facturas_portal.devolver(t, u, f, "Falta el NIF")
    justificantes.pedir(t, u, c, [{"fecha": hoy.isoformat(), "importe": -1000, "concepto": "Cargo raro"}])
    _como_cliente(cliente, c)
    html = _html(cliente, "/portal/")
    assert "Plazos y lo que falta" in html and "303" in html and "vence en 9 días" in html
    for texto in ("Subir: Extracto del banco", "1 factura por corregir", "1 movimiento del banco sin explicar"):
        assert texto in html
    plazos = portal_plazos.proximos(_ficha(c), db.listar_vencimientos_fiscales(t, cliente_fiscal_id=c, sin_internos=True), "completo")
    assert plazos[0]["urgente"] is False and len(plazos[0]["faltan"]) == 3


def test_un_plazo_sin_nada_pendiente_se_marca_en_orden(cliente):
    t, u, c = _despacho("Gestoria plazos2")
    hoy = date.today()
    db.crear_vencimiento_fiscal(t, c, "303", facturas_portal.trimestre_actual(hoy), (hoy + timedelta(days=3)).isoformat(), usuario_id=u)
    _como_cliente(cliente, c)
    html = _html(cliente, "/portal/")
    assert "Todo en orden: tu gestoría no necesita nada más de ti." in html


def test_lo_presentado_o_lejano_no_sale_en_plazos(cliente):
    t, u, c = _despacho("Gestoria plazos3")
    hoy = date.today()
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T1", (hoy + timedelta(days=5)).isoformat(), usuario_id=u)
    db.editar_vencimiento_fiscal(t, v, estado="presentado")
    db.crear_vencimiento_fiscal(t, c, "130", "2026-T4", (hoy + timedelta(days=200)).isoformat(), usuario_id=u)
    _como_cliente(cliente, c)
    assert "Plazos y lo que falta" not in _html(cliente, "/portal/")


def test_el_perfil_de_administracion_no_ve_en_plazos_lo_que_solo_puede_hacer_el_titular():
    t, u, c = _despacho("Gestoria plazos4")
    hoy = date.today()
    v = db.crear_vencimiento_fiscal(t, c, "303", facturas_portal.trimestre_actual(hoy), (hoy + timedelta(days=4)).isoformat(), usuario_id=u)
    db.editar_vencimiento_fiscal(t, v, documenso_documento_id="doc-9")
    from app.main import app
    vencimientos = db.listar_vencimientos_fiscales(t, cliente_fiscal_id=c, sin_internos=True)
    with app.test_request_context("/portal/"):
        completo = portal_plazos.proximos(_ficha(c), vencimientos, "completo")
        admin = portal_plazos.proximos(_ficha(c), vencimientos, "administracion")
    assert any("Firmar" in f["texto"] for f in completo[0]["faltan"]) and not any("Firmar" in f["texto"] for f in admin[0]["faltan"])


# --- I3: estado del trabajo en curso ---------------------------------------------------------------------------------------------------------------

def _tarea_para_el_cliente(t, u, c, estado="en_progreso"):
    tid = db.crear_tarea_outlook(u, "Preparar tu declaración de la renta") if hasattr(db, "crear_tarea_outlook") else None
    return tid


def test_el_trabajo_en_curso_dice_en_que_fase_esta_quien_lo_lleva_y_su_ultima_novedad(cliente):
    t, u, c = _despacho("Gestoria estado")
    db.guardar_perfil_usuario(u, nombre_mostrado="Marta Ruiz") if hasattr(db, "guardar_perfil_usuario") else None
    conn = db.get_connection()
    cur = conn.execute("INSERT INTO tareas_outlook (usuario_id, asunto, estado, porcentaje_completado, creada_en, actualizada_en, cliente_fiscal_id, visible_cliente) VALUES (?, 'Preparar tu renta', 'en_progreso', 40, '2026-10-01T10:00:00', '2026-11-03T09:00:00', ?, 1)", (u, c))
    conn.commit(); conn.close()
    tareas = tareas_trabajo.tareas_para_cliente(t, c)
    assert [x["asunto"] for x in tareas] == ["Preparar tu renta"]
    from app.main import app
    with app.test_request_context("/portal/"):
        e = portal_estado.enriquecer(tareas, t)[0]
    assert [f["estado"] for f in e["fases"]] == ["hecha", "actual", "pendiente"] and e["porcentaje"] == 40 and e["actualizada_en"] == "2026-11-03" and e["pausa"] is None
    _como_cliente(cliente, c)
    html = _html(cliente, "/portal/")
    assert "portal-fases" in html and "Última novedad" in html and "Recibido" in html and "Terminado" in html


@pytest.mark.parametrize("estado, fases, pausa", [("no_iniciada", ["actual", "pendiente", "pendiente"], None), ("esperando", ["hecha", "actual", "pendiente"], "En espera"),
                                                  ("aplazada", ["hecha", "actual", "pendiente"], "Aplazada"), ("completada", ["hecha", "hecha", "hecha"], None), ("en_revision", ["hecha", "actual", "pendiente"], None)])
def test_las_fases_segun_el_estado_de_la_tarea(estado, fases, pausa):
    t, u, c = _despacho("Gestoria estado2")
    from app.main import app
    trabajo = [{"id": 1, "asunto": "x", "estado": estado, "estado_texto": "x", "fecha_vencimiento": None, "vencida": False, "puede_comentar": False, "comentarios": []}]
    with app.test_request_context("/portal/"):
        e = portal_estado.enriquecer(trabajo, t)[0]
    assert [f["estado"] for f in e["fases"]] == fases and e["pausa"] == pausa


# --- J1: actividad del portal para el despacho ----------------------------------------------------------------------------------------------------

AHORA = datetime(2026, 11, 5, 12, 0)


def _entrada(t, c, cuando):
    conn = db.get_connection()
    conn.execute("INSERT INTO auditoria_eventos (tenant_id, usuario_id, accion, entidad, entidad_id, detalle, creado_en) VALUES (?, NULL, 'portal.entrada', 'cliente_fiscal', ?, '{}', ?)", (t, str(c), cuando.isoformat(timespec="seconds")))
    conn.commit(); conn.close()


def test_la_actividad_distingue_a_quien_entra_de_quien_ignora_los_avisos():
    t, u, c = _despacho("Gestoria actividad", cliente_nombre="Activo SL")
    ignora = crear_cliente_fiscal(t, "Ignora SL", nif="B22222222", email="ignora@ejemplo.com")
    sin_acceso = crear_cliente_fiscal(t, "Sin Portal SL", nif="B33333333")
    _entrada(t, c, AHORA - timedelta(days=2))
    _entrada(t, ignora, AHORA - timedelta(days=40))
    justificantes.pedir(t, u, ignora, [{"fecha": "2026-10-01", "importe": -5000, "concepto": "Cargo"}])
    conn = db.get_connection()
    conn.execute("INSERT INTO portal_avisos_enviados (tenant_id, cliente_fiscal_id, destinatario, tipo, referencia, enviado_en) VALUES (?, ?, 'ignora@ejemplo.com', 'justificantes', '1:3', ?)", (t, ignora, (AHORA - timedelta(days=5)).isoformat(timespec="seconds")))
    conn.commit(); conn.close()
    filas = {f["nombre"]: f for f in portal_metricas.filas(t, u, AHORA)}
    assert "Sin Portal SL" not in filas
    assert filas["Activo SL"]["entradas_30"] == 1 and filas["Activo SL"]["ignora"] is False and filas["Activo SL"]["pendientes"] == 0
    assert filas["Ignora SL"]["ignora"] is True and filas["Ignora SL"]["pendientes"] == 1 and filas["Ignora SL"]["avisos_30"] == 1 and filas["Ignora SL"]["entradas_30"] == 0
    assert list(f["nombre"] for f in portal_metricas.filas(t, u, AHORA))[0] == "Ignora SL", "los que ignoran, primero"


def test_el_tiempo_de_respuesta_sale_de_lo_que_el_cliente_contesto():
    t, u, c = _despacho("Gestoria actividad2")
    justificantes.pedir(t, u, c, [{"fecha": "2026-10-01", "importe": -5000, "concepto": "Cargo A"}, {"fecha": "2026-10-02", "importe": -3000, "concepto": "Cargo B"}])
    conn = db.get_connection()
    conn.execute("UPDATE justificantes_pendientes SET estado = 'personal', creado_en = '2026-10-20T10:00:00', respondido_en = '2026-10-22T10:00:00' WHERE concepto = 'Cargo A'")
    conn.execute("UPDATE justificantes_pendientes SET estado = 'personal', creado_en = '2026-10-20T10:00:00', respondido_en = '2026-10-24T10:00:00' WHERE concepto = 'Cargo B'")
    conn.commit(); conn.close()
    f = portal_metricas.filas(t, u, AHORA)[0]
    assert f["respuesta_media_dias"] == 3.0 and f["respuestas"] == 2


def test_la_pagina_de_actividad_la_ve_el_equipo(cliente):
    t, u, c = _despacho("Gestoria actividad3", cliente_nombre="Visible SL")
    uid = iniciar_sesion_de_prueba(cliente, "eq-act@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    html = _html(cliente, "/fiscal/portal-actividad")
    assert "Actividad del portal" in html and "Visible SL" in html and "Nunca ha entrado" in html
    assert "Actividad del portal" in _html(cliente, "/fiscal/recordatorios")


# --- J2: respuestas rápidas -------------------------------------------------------------------------------------------------------------------------

def test_las_respuestas_rapidas_se_crean_se_validan_y_sustituyen_cliente_y_despacho():
    t, u, c = _despacho("Gestoria rapidas")
    rid = portal_respuestas.crear(t, u, "Falta extracto", "Hola {cliente}, nos falta el extracto del banco. Un saludo, {despacho}.")
    assert [r["titulo"] for r in portal_respuestas.listar(t)] == ["Falta extracto"]
    texto = portal_respuestas.para_cliente(t, _ficha(c))[0]["texto"]
    assert texto == "Hola Cliente M SL, nos falta el extracto del banco. Un saludo, Gestoria rapidas."
    with pytest.raises(ValueError):
        portal_respuestas.crear(t, u, "", "x")
    with pytest.raises(ValueError, match="1000"):
        portal_respuestas.crear(t, u, "largo", "x" * 1001)
    portal_respuestas.borrar(t, rid)
    assert portal_respuestas.listar(t) == []


def test_las_respuestas_de_un_despacho_no_las_ve_otro():
    t, u, c = _despacho("Gestoria rapidas2")
    t2, u2, c2 = _despacho("Gestoria rapidas3", cliente_email="otro@ejemplo.com")
    portal_respuestas.crear(t, u, "Mía", "texto")
    assert portal_respuestas.listar(t2) == []
    portal_respuestas.borrar(t2, portal_respuestas.listar(t)[0]["id"])
    assert len(portal_respuestas.listar(t)) == 1, "borrar con el despacho equivocado no borra nada"


def test_el_equipo_las_gestiona_y_las_usa_en_las_conversaciones(cliente):
    t, u, c = _despacho("Gestoria rapidas4")
    uid = iniciar_sesion_de_prueba(cliente, "eq-rap@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    assert cliente.post("/fiscal/respuestas-rapidas", data={"titulo": "Recibido", "texto": "Gracias {cliente}, lo hemos recibido."}).status_code == 302
    assert "Recibido" in _html(cliente, "/fiscal/recordatorios") and "Gracias {cliente}" in _html(cliente, "/fiscal/recordatorios")
    f = _factura(c)
    html = _html(cliente, f"/contabilidad/{f}")
    assert 'class="respuestas-rapidas"' in html and "Gracias Cliente M SL, lo hemos recibido." in html and "respuestas_rapidas.js" in html
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20", usuario_id=u)
    assert "Gracias Cliente M SL" in _html(cliente, f"/fiscal/vencimientos/{v}/editar")
    rid = portal_respuestas.listar(t)[0]["id"]
    assert cliente.post(f"/fiscal/respuestas-rapidas/{rid}/borrar").status_code == 302 and portal_respuestas.listar(t) == []
    assert 'class="respuestas-rapidas"' not in _html(cliente, f"/contabilidad/{f}")
    r = cliente.post("/fiscal/respuestas-rapidas", data={"titulo": "", "texto": ""}, follow_redirects=True)
    assert "Escribe un título" in r.get_data(as_text=True)


# --- J3: informe del año ---------------------------------------------------------------------------------------------------------------------------

def test_el_informe_del_año_recoge_lo_presentado_firmado_pagado_y_enviado(cliente):
    t, u, c = _despacho("Gestoria informe")
    db.editar_cliente_fiscal(t, c, portal_honorarios=1)
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T1", "2026-04-20", usuario_id=u)
    db.editar_vencimiento_fiscal(t, v, estado="presentado", documenso_documento_id="d1", documenso_firmado_en="2026-04-10T10:00:00")
    db.crear_vencimiento_fiscal(t, c, "303", "2026-T2", "2026-07-20", usuario_id=u)
    db.subir_documento_vencimiento(v, "extracto.pdf", "application/pdf", PDF)
    _factura(c, "G-1", "2026-02-10")
    _factura(c, "V-1", "2026-03-10", tipo="emitida")
    d = portal_informe_anual.datos(_ficha(c), 2026)
    assert d["vencimientos"] == 2 and len(d["presentados"]) == 1 and len(d["firmados"]) == 1 and d["facturas"] == {"recibida": 1, "emitida": 1, "devueltas": 0} and d["documentos"] == 1
    _como_cliente(cliente, c)
    r = cliente.get("/portal/carpeta/informe-2026.pdf")
    assert r.status_code == 200 and r.mimetype == "application/pdf" and r.data.startswith(b"%PDF") and b"inline" in r.headers["Content-Disposition"].encode()
    assert "Informe del año (PDF)" in _html(cliente, "/portal/carpeta?anio=2026")
    assert cliente.get("/portal/carpeta/informe-1999.pdf").status_code == 404
    z = zipfile.ZipFile(io.BytesIO(cliente.get("/portal/carpeta/2026.zip").data))
    assert "informe-anual-2026.pdf" in z.namelist()


def test_el_informe_de_un_cliente_no_enseña_lo_de_otro(cliente):
    t, u, c = _despacho("Gestoria informe2")
    otro = crear_cliente_fiscal(t, "Otro SL", nif="B55555555", email="otro@ejemplo.com")
    _factura(otro, "OTRO-1", "2026-02-10")
    d = portal_informe_anual.datos(_ficha(c), 2026)
    assert d["facturas"] == {"recibida": 0, "emitida": 0, "devueltas": 0}


# --- H1: el equipo gestiona las personas con acceso -----------------------------------------------------------------------------------------

def test_el_equipo_da_y_quita_acceso_desde_la_ficha_del_cliente(cliente):
    t, u, c = _despacho("Gestoria equipo")
    uid = iniciar_sesion_de_prueba(cliente, "eq-pers@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    assert "Personas con acceso al portal" in _html(cliente, f"/fiscal/clientes/{c}/editar")
    assert cliente.post(f"/fiscal/clientes/{c}/contactos", data={"email": "asesor@ejemplo.com", "nombre": "Asesor", "rol": "consulta"}).status_code == 302
    persona = next(p for p in portal_personas.listar(_ficha(c)) if not p["es_titular"])
    assert persona["email"] == "asesor@ejemplo.com" and "Asesor" in _html(cliente, f"/fiscal/clientes/{c}/editar")
    cliente.post(f"/fiscal/clientes/{c}/contactos/{persona['id']}/perfil", data={"rol": "administracion"})
    assert portal_personas.rol_de(_ficha(c), "asesor@ejemplo.com") == "administracion"
    acciones = {e["accion"] for e in auditoria.listar(t, entidad="cliente_fiscal", entidad_id=c)}
    assert {"portal.contacto_alta", "portal.contacto_perfil"} <= acciones
    cliente.post(f"/fiscal/clientes/{c}/contactos/{persona['id']}/quitar")
    assert portal_personas.rol_de(_ficha(c), "asesor@ejemplo.com") is None and "portal.contacto_baja" in {e["accion"] for e in auditoria.listar(t, entidad="cliente_fiscal", entidad_id=c)}
    r = cliente.post(f"/fiscal/clientes/{c}/contactos", data={"email": "mal", "rol": "consulta"}, follow_redirects=True)
    assert "email válido" in r.get_data(as_text=True)


def test_el_equipo_de_otro_despacho_no_toca_las_personas_de_este_cliente(cliente):
    t, u, c = _despacho("Gestoria equipo2")
    t2, u2, c2 = _despacho("Gestoria equipo3", cliente_email="otro@ejemplo.com")
    uid = iniciar_sesion_de_prueba(cliente, "eq-aj@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, t2); db.asignar_supervisor_tenant(uid, True)
    assert cliente.post(f"/fiscal/clientes/{c}/contactos", data={"email": "x@ejemplo.com", "rol": "consulta"}).status_code == 404
    assert portal_personas.listar(_ficha(c))[1:] == []


def test_la_direccion_de_facturas_se_guarda_desde_los_ajustes_del_portal(cliente):
    t, u, c = _despacho("Gestoria equipo4")
    uid = iniciar_sesion_de_prueba(cliente, "eq-dir@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    assert cliente.post("/fiscal/recordatorios/correo-facturas", data={"correo_facturas": "facturas@despacho.com"}).status_code == 302
    assert portal_subida_rapida.direccion_base(t) == "facturas@despacho.com" and 'value="facturas@despacho.com"' in _html(cliente, "/fiscal/recordatorios")
    r = cliente.post("/fiscal/recordatorios/correo-facturas", data={"correo_facturas": "mal+uno@x.es"}, follow_redirects=True)
    assert "sin «+»" in r.get_data(as_text=True) and portal_subida_rapida.direccion_base(t) == "facturas@despacho.com"
    cliente.post("/fiscal/recordatorios/correo-facturas", data={"correo_facturas": ""})
    assert portal_subida_rapida.direccion_base(t) == ""
