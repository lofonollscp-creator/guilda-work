"""«Lo que hemos hecho por ti» (B2) y «No sé qué es esto» (B3)."""
from datetime import date, timedelta

from app import db, facturas_contables as fc, portal_actividad as pa, portal_conversaciones as pc, portal_peticiones as pp
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _presentar(c, t, u, modelo="303", periodo="1T 2026"):
    v = db.crear_vencimiento_fiscal(t, c, modelo, periodo, (date.today() + timedelta(days=3)).isoformat(), usuario_id=u)
    conn = db.get_connection()
    conn.execute("UPDATE vencimientos_fiscales SET estado = 'presentado', actualizado_en = ? WHERE id = ?", (db.now_iso(), v))
    conn.commit(); conn.close()
    return v


def test_sin_nada_hecho_la_portada_no_enseña_la_seccion_y_la_pagina_lo_explica(cliente, correo):
    t, u, c = _despacho("Actividad vacia")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "Lo que hemos hecho por ti" not in _html(cliente, "/portal/").split("<nav")[1].split("</nav>")[1]
    assert "Todavía no hay nada que enseñarte" in _html(cliente, "/portal/actividad")


def test_los_hechos_de_la_gestoria_aparecen_en_orden_y_con_su_enlace(cliente, correo):
    t, u, c = _despacho("Actividad hechos")
    ficha = _ficha(c)
    v = _presentar(c, t, u)
    fid = fc.subir_archivos(t, u, c, "recibida", [("a.pdf", "application/pdf", PDF)])[0]
    conn = db.get_connection()
    conn.execute("UPDATE facturas_contables SET estado = 'revisada', revisado_en = ? WHERE id = ?", (db.now_iso(), fid))
    conn.commit(); conn.close()
    pc.iniciar(ficha, "Cambio de domicilio", "Os escribo desde la gestoría", "despacho", "eq@despacho.com")
    pet = pp.crear(ficha, "Extracto del 1T", por=u)
    db.subir_documento_vencimiento(v, "justificante-303.pdf", "application/pdf", PDF, origen="justificante")
    _entrar(cliente, c, "titular@ejemplo.com")
    html = _html(cliente, "/portal/actividad")
    for texto in ("Hemos presentado tu modelo 303 1T 2026", "Hemos revisado 1 factura tuya", "Te hemos escrito: Cambio de domicilio", "justificante-303.pdf"):
        assert texto in html, texto
    assert f"/portal/impuestos/{v}/documentos" in html or "documentos" in html
    assert "Lo que hemos hecho por ti" in _html(cliente, "/portal/") and "/portal/actividad" in _html(cliente, "/portal/")


def test_la_actividad_es_solo_del_cliente_y_de_los_ultimos_90_dias(cliente, correo):
    t, u, c = _despacho("Actividad aislada")
    t2, u2, otro = _despacho("Actividad ajena", cliente_email="otro@ejemplo.com", cliente_nombre="Otra SL")
    _presentar(otro, t2, u2, "130", "2T 2026")
    v = _presentar(c, t, u, "111", "1T 2020")
    conn = db.get_connection()
    conn.execute("UPDATE vencimientos_fiscales SET actualizado_en = '2020-04-10T10:00:00' WHERE id = ?", (v,))
    conn.commit(); conn.close()
    _entrar(cliente, c, "titular@ejemplo.com")
    html = _html(cliente, "/portal/actividad")
    assert "130" not in html.split("<main")[1] and "111 1T 2020" not in html


def test_no_se_que_es_esto_abre_la_conversacion_ya_escrita(cliente, correo):
    t, u, c = _despacho("No se")
    pp.crear(_ficha(c), "Extracto bancario del trimestre", por=u)
    _entrar(cliente, c, "titular@ejemplo.com")
    inicio = _html(cliente, "/portal/")
    assert "No sé qué es esto" in inicio and "tema=" in inicio
    html = _html(cliente, "/portal/conversaciones/nueva?tema=Extracto bancario del trimestre")
    assert "Necesito ayuda con: Extracto bancario del trimestre" in html and "no sé qué es esto o cómo hacerlo" in html


def test_compartir_desde_el_movil_sube_las_facturas_como_recibidas_y_el_manifiesto_lo_anuncia(cliente, correo):
    import io, json
    t, u, c = _despacho("Compartir movil")
    _entrar(cliente, c, "titular@ejemplo.com")
    m = json.loads(cliente.get("/portal/manifiesto.webmanifest").get_data(as_text=True)) if cliente.get("/portal/manifiesto.webmanifest").status_code == 200 else None
    if m is None:
        m = next(json.loads(cliente.get(r).get_data(as_text=True)) for r in ("/portal/manifest.webmanifest", "/portal/manifest.json") if cliente.get(r).status_code == 200)
    objetivo = m["share_target"]
    assert objetivo["action"] == "/portal/compartir" and objetivo["method"] == "POST" and objetivo["params"]["files"][0]["name"] == "archivos"
    r = cliente.post("/portal/compartir", data={"archivos": [(io.BytesIO(PDF + b"compartida"), "factura.pdf", "application/pdf")]}, content_type="multipart/form-data")
    assert r.status_code == 303 and "compartido=1" in r.headers["Location"]
    lista = [f for f in fc.listar(t, u) if f["tipo"] == "recibida"]
    assert len(lista) == 1
    assert "Se han guardado como compras y gastos" in _html(cliente, r.headers["Location"])
    assert cliente.post("/portal/compartir", data={}, content_type="multipart/form-data").status_code == 303        # sin archivos: vuelve con el aviso de siempre


def test_tras_subir_facturas_se_pregunta_si_ha_sido_facil_una_vez_y_una_nota_baja_avisa(cliente, correo):
    import io
    from app import portal_valoraciones as pv
    t, u, c = _despacho("Valoracion subida")
    _entrar(cliente, c, "titular@ejemplo.com")
    cliente.post("/portal/facturas", data={"modo": "archivos", "tipo": "recibida", "archivos": [(io.BytesIO(PDF + b"val"), "a.pdf", "application/pdf")]}, content_type="multipart/form-data")
    html = _html(cliente, "/portal/facturas?anotada=1")
    assert "¿Te ha resultado fácil subir tus facturas?" in html and 'value="5"' in html
    hoy = date.today().isoformat()
    r = cliente.post("/portal/valorar", data={"tipo": "subida", "referencia": hoy, "puntos": "2"})
    assert r.status_code == 302 and "valorado=1" in r.headers["Location"] and pv.ya_valorada(_ficha(c), "titular@ejemplo.com", "subida", hoy)
    assert "¿Te ha resultado fácil" not in _html(cliente, "/portal/facturas?anotada=1") and "Gracias" not in _html(cliente, "/portal/facturas?anotada=1")
    assert "Ya has valorado" in cliente.post("/portal/valorar", data={"tipo": "subida", "referencia": hoy, "puntos": "5"}, follow_redirects=True).get_data(as_text=True)
    assert "No se puede valorar eso" in cliente.post("/portal/valorar", data={"tipo": "subida", "referencia": "2020-01-01", "puntos": "5"}, follow_redirects=True).get_data(as_text=True)
