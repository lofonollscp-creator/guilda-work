"""«Para empezar» del portal (Q6): lista viva de primeros pasos que se tachan solos, con progreso, y que desaparece al completarse o al pulsar «Entendido»."""
from app import facturas_contables as fc, portal_conversaciones as pc, portal_primeros_pasos as pp
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _pasos(http, ficha, **kw):
    with http.application.test_request_context():
        return pp.pasos(ficha, **{"con_facturas": True, "puede_subir": True, **kw})


def test_un_cliente_nuevo_ve_la_lista_con_su_progreso_y_un_unico_boton_destacado(cliente, correo):
    t, u, c = _despacho("Empezar nuevo")
    _entrar(cliente, c, "titular@ejemplo.com")
    html = _html(cliente, "/portal/")
    assert "portal-empezar" in html and "Para empezar" in html and "Has subido tu primera factura" in html and "Has escrito a tu gestoría" in html
    assert "1 de 3" in html and html.count('class="btn btn-primary" href="/portal/facturas"') == 1


def test_escribir_a_la_gestoria_tacha_el_paso_y_el_resumen_avanza(cliente, correo):
    t, u, c = _despacho("Empezar escribe")
    ficha = _ficha(c)
    antes = pp.resumen(_pasos(cliente, ficha))
    pc.iniciar(ficha, "Una duda", "Hola", "cliente", "titular@ejemplo.com")
    despues = pp.resumen(_pasos(cliente, ficha))
    assert despues["hechos"] == antes["hechos"] + 1
    assert next(p for p in _pasos(cliente, ficha) if p["clave"] == "contacto")["hecho"]


def test_con_todos_los_pasos_hechos_la_lista_no_sale(cliente, correo):
    t, u, c = _despacho("Empezar completo")
    ficha = _ficha(c)
    fc.subir_desde_portal(c, "recibida", [("a.pdf", "application/pdf", PDF)])
    pc.iniciar(ficha, "Una duda", "Hola", "cliente", "titular@ejemplo.com")
    assert pp.resumen(_pasos(cliente, ficha))["completo"]
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "portal-empezar" not in _html(cliente, "/portal/")


def test_entendido_oculta_la_lista(cliente, correo):
    t, u, c = _despacho("Empezar entendido")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "portal-empezar" in _html(cliente, "/portal/")
    cliente.post("/portal/bienvenida")
    assert "portal-empezar" not in _html(cliente, "/portal/")


def test_con_el_perfil_de_consulta_no_se_propone_escribir_ni_subir(cliente, correo):
    t, u, c = _despacho("Empezar consulta")
    lista = _pasos(cliente, _ficha(c), puede_subir=False, puede_escribir=False)
    assert [p["clave"] for p in lista] == ["datos"]
