"""Portal de facturas: el camino de cada factura, varias fotos como una sola factura y corrección en un toque (Q1, Q2)."""
import io

from PIL import Image

from app import facturas_contables as fc, facturas_portal as fp, pdf_facturas
from tests.test_facturas_contables import PDF, _portal


def _foto(color="white", tam=(300, 400)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", tam, color).save(b, "JPEG")
    return b.getvalue()


def _paso(lista, clave):
    return next(p for p in lista if p["clave"] == clave)


def test_los_pasos_de_una_factura_segun_su_estado():
    pendiente_sin_leer = fp.pasos_de({"estado": "pendiente", "lectura": "pendiente"})
    assert [p["hecho"] for p in pendiente_sin_leer] == [True, False, False, False] and _paso(pendiente_sin_leer, "leida")["actual"]
    leida = fp.pasos_de({"estado": "pendiente", "lectura": "ia"})
    assert [p["hecho"] for p in leida] == [True, True, False, False] and _paso(leida, "revisada")["actual"]
    escrita_a_mano = fp.pasos_de({"estado": "pendiente", "lectura": None})
    assert [p["hecho"] for p in escrita_a_mano] == [True, True, False, False]
    assert [p["hecho"] for p in fp.pasos_de({"estado": "revisada", "lectura": "ia"})] == [True, True, True, False]
    contabilizada = fp.pasos_de({"estado": "exportada", "lectura": "ia"})
    assert all(p["hecho"] for p in contabilizada) and not any(p["actual"] for p in contabilizada)
    assert fp.pasos_de({"estado": "descartada", "lectura": "ia"}) == []


def test_la_lista_del_portal_enseña_el_camino_de_cada_factura(cliente):
    t, u, c = _portal(cliente)
    cliente.post("/portal/facturas", data={"modo": "archivos", "tipo": "recibida", "archivos": [(io.BytesIO(PDF + b"x"), "a.pdf", "application/pdf")]}, content_type="multipart/form-data")
    html = cliente.get("/portal/facturas").get_data(as_text=True)
    assert 'class="portal-pasos"' in html and "Recibida" in html and "Leída" in html and "Revisada" in html and "Contabilizada" in html and 'aria-current="step"' in html


def test_varias_fotos_de_una_misma_factura_se_juntan_en_un_pdf(cliente):
    t, u, c = _portal(cliente)
    fotos = [(io.BytesIO(_foto(col)), f"p{i}.jpg", "image/jpeg") for i, col in enumerate(("white", "lightgray", "beige"))]
    r = cliente.post("/portal/facturas", data={"modo": "archivos", "tipo": "recibida", "misma_factura": "1", "archivos": fotos}, content_type="multipart/form-data")
    assert r.status_code == 302
    fs = fc.listar(t, u, cliente_fiscal_id=c)
    assert len(fs) == 1                                                                              # UNA factura, no tres
    from app import almacen_documentos
    doc = almacen_documentos.leer_de_cliente_fiscal(t, c, fs[0]["documento_id"], u)
    assert doc["tipo_mime"] == "application/pdf" and doc["contenido"][:5] == b"%PDF-" and pdf_facturas.numero_de_paginas(bytes(doc["contenido"])) == 3


def test_sin_la_casilla_cada_foto_sigue_siendo_una_factura(cliente):
    t, u, c = _portal(cliente)
    fotos = [(io.BytesIO(_foto(col)), f"p{i}.jpg", "image/jpeg") for i, col in enumerate(("white", "beige"))]
    cliente.post("/portal/facturas", data={"modo": "archivos", "tipo": "recibida", "archivos": fotos}, content_type="multipart/form-data")
    assert len(fc.listar(t, u, cliente_fiscal_id=c)) == 2


def test_juntar_paginas_exige_que_todo_sean_fotos_y_avisa_con_claridad(cliente):
    t, u, c = _portal(cliente)
    mezcla = [(io.BytesIO(_foto()), "a.jpg", "image/jpeg"), (io.BytesIO(PDF + b"z"), "b.pdf", "application/pdf")]
    r = cliente.post("/portal/facturas", data={"modo": "archivos", "tipo": "recibida", "misma_factura": "1", "archivos": mezcla}, content_type="multipart/form-data")
    assert r.status_code == 200 and "todos los archivos deben ser fotos" in r.get_data(as_text=True) and fc.listar(t, u, cliente_fiscal_id=c) == []


def test_imagenes_a_pdf_respeta_el_limite_de_peso_y_no_acepta_basura():
    import random
    ruido = Image.effect_noise((2200, 3000), 90).convert("RGB")
    b = io.BytesIO(); ruido.save(b, "PNG")
    pdf = pdf_facturas.imagenes_a_pdf([b.getvalue(), b.getvalue()], limite_bytes=3_000_000)
    assert pdf is None or len(pdf) <= 3_000_000
    assert pdf_facturas.imagenes_a_pdf([b"esto no es una imagen"]) is None and pdf_facturas.imagenes_a_pdf([]) is None
    uno = pdf_facturas.imagenes_a_pdf([_foto()])
    assert uno[:5] == b"%PDF-" and pdf_facturas.numero_de_paginas(uno) == 1


def test_la_pagina_ofrece_juntar_y_avisa_de_reflejos_y_poca_luz(cliente):
    t, u, c = _portal(cliente)
    html = cliente.get("/portal/facturas").get_data(as_text=True)
    assert "data-misma-factura" in html and 'name="misma_factura"' in html and "data-txt-reflejos" in html and "data-txt-oscura" in html and "data-auto-enviar" not in html
    js = cliente.get("/static/portal_facturas_subida.js").get_data(as_text=True)
    assert "function luz(" in js and "ofrecerJuntar" in js and "data-auto-enviar" in js


def test_respuestas_rapidas_del_cliente_solo_si_la_gestoria_escribio_la_ultima(cliente):
    t, u, c = _portal(cliente)
    f = fc.crear_desde_portal(c, {"tipo": "recibida", "fecha": "2026-08-10", "numero": "P-1", "tercero_nombre": "Ferretería", "tercero_nif": "B11111111", "total": "121,00", "pct_iva": "21"})
    assert "Respuestas rápidas" not in cliente.get(f"/portal/facturas/{f}").get_data(as_text=True)
    fp.escribir_como_despacho(t, u, f, "¿Es un gasto de la empresa?")
    html = cliente.get(f"/portal/facturas/{f}").get_data(as_text=True)
    assert "Respuestas rápidas" in html and "Es un gasto personal." in html
    assert cliente.post(f"/portal/facturas/{f}/mensajes", data={"texto": "Es un gasto de la empresa."}).status_code == 302
    assert [m["autor"] for m in fp.mensajes(t, f)] == ["empleado", "cliente"]
    assert "Respuestas rápidas" not in cliente.get(f"/portal/facturas/{f}").get_data(as_text=True), "ya contestó: no se le vuelven a ofrecer"


def test_las_preguntas_rapidas_del_despacho_salen_en_la_ficha_y_se_envian(cliente):
    from tests.test_facturas_contables import _web
    uid, t, c = _web(cliente, "preguntas@ejemplo.com")
    f = fc.crear(t, uid, c, {"tipo": "recibida", "fecha": "2026-08-10", "numero": "Q-7", "tercero_nombre": "Ferretería", "tercero_nif": "B11111111", "concepto": "x"}, [{"base": "10,00", "pct_iva": "21"}])
    html = cliente.get(f"/contabilidad/{f}").get_data(as_text=True)
    assert "Pedir el concepto" in html and "Preguntas rápidas al cliente" in html
    pregunta = "¿Para qué fue este gasto? Necesitamos el concepto para contabilizar la factura Q-7 de Ferretería."
    assert cliente.post(f"/contabilidad/{f}/mensajes", data={"texto": pregunta}).status_code == 302
    assert [m["texto"] for m in fp.mensajes(t, f)] == [pregunta]
