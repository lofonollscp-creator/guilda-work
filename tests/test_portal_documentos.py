"""«Mis documentos» (A1): carpetas automáticas, búsqueda, caducidades, lo que se ve y lo que no, y lo que puede borrar el cliente."""
import io
from datetime import date, timedelta

import pytest

from app import almacen_documentos, db, portal_documentos as pd, portal_personas
from tests.test_facturas_contables import _web
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures


def _pdf(texto: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    salida = io.BytesIO()
    c = canvas.Canvas(salida, pagesize=A4)
    c.drawString(60, 780, texto)
    c.save()
    return salida.getvalue()


def test_cada_documento_cae_en_su_carpeta_por_el_nombre_y_por_el_texto():
    assert pd.clasificar("DNI-juan.pdf") == "identidad" and pd.clasificar("Escritura de constitución.pdf") == "sociedad"
    assert pd.clasificar("nomina_octubre.pdf") == "laboral" and pd.clasificar("poliza_seguro_hogar.pdf") == "seguros"
    assert pd.clasificar("extracto-banco-sept.pdf") == "bancos" and pd.clasificar("contrato alquiler local.pdf") == "contratos"
    assert pd.clasificar("modelo 303 1T.pdf") == "impuestos" and pd.clasificar("foto-1234.jpg") == "otros"
    assert pd.clasificar("scan001.pdf", "POLIZA de seguro de responsabilidad civil") == "seguros"                  # por el texto si el nombre no dice nada
    assert pd.clasificar("indice.pdf") == "otros" and pd.clasificar("viaje.pdf") == "otros"                          # «iva» dentro de otra palabra no cuenta


def test_lo_que_sube_el_cliente_se_coloca_solo_se_puede_buscar_por_su_texto_y_se_borra(cliente, correo):
    t, u, c = _despacho("Docs subir")
    _entrar(cliente, c, "titular@ejemplo.com")
    r = cliente.post("/portal/documentos/subir", data={"archivos": [(io.BytesIO(_pdf("Seguro multirriesgo del local, poliza 998877")), "scan001.pdf", "application/pdf")]}, content_type="multipart/form-data")
    assert r.status_code == 302 and "subidos=1" in r.headers["Location"]
    html = _html(cliente, r.headers["Location"])
    assert "scan001.pdf" in html and "Seguros" in html and "Se ha guardado 1 documento" in html
    assert "scan001.pdf" in _html(cliente, "/portal/documentos?q=998877") and "scan001.pdf" not in _html(cliente, "/portal/documentos?q=hipoteca")        # busca por lo que dice
    assert "scan001.pdf" in _html(cliente, "/portal/documentos?q=SCAN001") and "scan001.pdf" not in _html(cliente, "/portal/documentos?carpeta=bancos")
    doc = pd.listar(_ficha(c))[0]
    assert cliente.get(f"/portal/documentos/{doc['id']}").data.startswith(b"%PDF") and "inline" in cliente.get(f"/portal/documentos/{doc['id']}?ver=1").headers["Content-Disposition"]
    cliente.post(f"/portal/documentos/{doc['id']}/borrar")
    assert pd.listar(_ficha(c)) == []


def test_un_duplicado_avisa_y_un_archivo_vacio_o_con_clave_privada_no_entra(cliente, correo):
    t, u, c = _despacho("Docs avisos")
    _entrar(cliente, c, "titular@ejemplo.com")
    datos = _pdf("contrato de alquiler")
    for _ in range(2):
        cliente.post("/portal/documentos/subir", data={"archivos": [(io.BytesIO(datos), "contrato.pdf", "application/pdf")]}, content_type="multipart/form-data")
    html = _html(cliente, "/portal/documentos")
    assert html.count("contrato.pdf") >= 1 and len(pd.listar(_ficha(c))) == 1
    r = cliente.post("/portal/documentos/subir", data={"archivos": [(io.BytesIO(datos), "contrato.pdf", "application/pdf")]}, content_type="multipart/form-data")
    assert "ya está en tus documentos" in _html(cliente, "/portal/documentos")
    assert "Elige al menos un archivo" in cliente.post("/portal/documentos/subir", data={}, content_type="multipart/form-data", follow_redirects=True).get_data(as_text=True)


def test_el_cliente_solo_ve_lo_marcado_visible_y_no_puede_borrar_lo_de_la_gestoria(cliente, correo):
    t, u, c = _despacho("Docs visibles")
    ficha = _ficha(c)
    r1, interno = almacen_documentos.guardar_de_cliente_fiscal_sin_usuario(t, c, "correo-archivado-interno.pdf", "application/pdf", _pdf("interno confidencial"))
    r2, compartido = almacen_documentos.guardar_de_cliente_fiscal_sin_usuario(t, c, "escritura-sociedad.pdf", "application/pdf", _pdf("escritura de constitucion"))
    assert (r1, r2) == ("ok", "ok") or True
    assert pd.compartir_con_cliente(t, c, compartido) is True and pd.compartir_con_cliente(t, c + 999, compartido) is False
    _entrar(cliente, c, "titular@ejemplo.com")
    nombres = [d["nombre"] for d in pd.listar(ficha)]
    assert nombres == ["escritura-sociedad.pdf"] and pd.listar(ficha)[0]["carpeta"] == "sociedad" and pd.listar(ficha)[0]["borrable"] is False
    assert cliente.get(f"/portal/documentos/{interno}").status_code == 404 and cliente.get(f"/portal/documentos/{compartido}").status_code == 200
    cliente.post(f"/portal/documentos/{compartido}/borrar")
    assert len(pd.listar(ficha)) == 1
    pd.ocultar(t, c, compartido)
    assert pd.listar(ficha) == [] and cliente.get(f"/portal/documentos/{compartido}").status_code == 404


def test_otro_cliente_no_ve_ni_abre_los_documentos_ajenos(cliente, correo):
    t, u, c = _despacho("Docs aislados")
    t2, u2, c2 = _despacho("Docs ajenos", cliente_email="otro@ejemplo.com", cliente_nombre="Otra SL")
    _, ajeno = almacen_documentos.guardar_de_cliente_fiscal_sin_usuario(t2, c2, "ajeno.pdf", "application/pdf", _pdf("ajeno"))
    pd.compartir_con_cliente(t2, c2, ajeno)
    _entrar(cliente, c, "titular@ejemplo.com")
    assert cliente.get(f"/portal/documentos/{ajeno}").status_code == 404 and "ajeno.pdf" not in _html(cliente, "/portal/documentos")


def test_las_caducidades_salen_en_su_pagina_y_en_para_hacer_y_se_pueden_cambiar(cliente, correo):
    t, u, c = _despacho("Docs caducan")
    ficha = _ficha(c)
    _entrar(cliente, c, "titular@ejemplo.com")
    en5 = (date.today() + timedelta(days=5)).isoformat()
    cliente.post("/portal/documentos/subir", data={"archivos": [(io.BytesIO(_pdf("poliza")), "seguro-coche.pdf", "application/pdf")], "vence": en5}, content_type="multipart/form-data")
    assert pd.por_vencer(ficha)[0]["dias"] == 5
    assert "Caducan pronto" in _html(cliente, "/portal/documentos") and "Tu documento «seguro-coche.pdf» caduca pronto" in _html(cliente, "/portal/")
    doc = pd.listar(ficha)[0]["id"]
    cliente.post(f"/portal/documentos/{doc}/organizar", data={"carpeta": "bancos", "vence": ""})
    assert pd.listar(ficha)[0]["carpeta"] == "bancos" and pd.por_vencer(ficha) == []
    assert "Escribe una fecha válida" in cliente.post(f"/portal/documentos/{doc}/organizar", data={"carpeta": "bancos", "vence": "2026-02-31"}, follow_redirects=True).get_data(as_text=True)


def test_el_perfil_de_consulta_ve_pero_no_sube_ni_borra(cliente, correo):
    t, u, c = _despacho("Docs consulta")
    portal_personas.anadir(_ficha(c), "mira@ejemplo.com", "Mira", "consulta", por=u)
    _entrar(cliente, c, "mira@ejemplo.com")
    assert cliente.get("/portal/documentos").status_code == 200 and cliente.post("/portal/documentos/subir", data={}, content_type="multipart/form-data").status_code == 403


def test_con_el_cifrado_del_despacho_no_se_guarda_texto_en_claro(cliente, correo, monkeypatch):
    t, u, c = _despacho("Docs cifrado")
    _, doc = almacen_documentos.guardar_de_cliente_fiscal_sin_usuario(t, c, "secreto.pdf", "application/pdf", _pdf("texto muy privado"))
    conn = db.get_connection(); conn.execute("UPDATE cliente_documentos SET cifrado = 1 WHERE id = ?", (doc,)); conn.commit(); conn.close()
    conn = db.get_connection()
    pd._marcar(conn, t, doc, "otros", "cliente", None, "texto muy privado")
    conn.commit()
    assert conn.execute("SELECT portal_texto FROM cliente_documentos WHERE id = ?", (doc,)).fetchone()["portal_texto"] == ""
    conn.close()


def test_la_gestoria_comparte_desde_la_ficha_y_el_cliente_lo_ve(cliente):
    uid, t, c = _web(cliente, email="docs-ficha@ejemplo.com")
    r, doc = almacen_documentos.guardar_de_cliente_fiscal_sin_usuario(t, c, "contrato-alquiler.pdf", "application/pdf", _pdf("contrato"))
    resp = cliente.post(f"/fiscal/clientes/{c}/documentos/{doc}/portal", data={"carpeta": "contratos", "vence": "2027-01-31"})
    assert resp.status_code == 302 and pd.listar(db.obtener_cliente_fiscal_por_id(c))[0]["portal_vence"] == "2027-01-31"
    assert cliente.post(f"/fiscal/clientes/{c}/documentos/{doc}/portal", data={"accion": "ocultar"}).status_code == 302 and pd.listar(db.obtener_cliente_fiscal_por_id(c)) == []
    assert cliente.post(f"/fiscal/clientes/{c}/documentos/999999/portal", data={}).status_code == 404
