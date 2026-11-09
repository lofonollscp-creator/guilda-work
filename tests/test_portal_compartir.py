"""Enlaces temporales para compartir un documento de la carpeta (D1) y carpeta con filtros y vista previa (D2)."""
import re
from datetime import datetime, timedelta

import pytest

from app import db, portal_compartir as pc, portal_personas
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _con_documento(nombre="Presentacion"):
    t, u, c = _despacho(nombre)
    from datetime import date
    v = db.crear_vencimiento_fiscal(t, c, "303", "1T 2026", f"{date.today().year}-04-20", usuario_id=u)
    db.subir_documento_vencimiento(v, "justificante-303.pdf", "application/pdf", PDF, origen="justificante")
    d = db.listar_documentos_vencimiento(v)[0]["id"]
    return t, u, c, v, d


def _crear(cliente, v, d, dias="7", maximo=5):
    return cliente.post("/portal/carpeta/compartir", data={"vencimiento_id": v, "documento_id": d, "dias": dias, "max_descargas": maximo, "anio": ""})


def _enlace_de(cliente):
    html = cliente.get("/portal/carpeta").get_data(as_text=True)
    return re.search(r'value="(http[^"]*/portal/compartido/[^"]+)"', html).group(1)


def test_se_crea_un_enlace_y_un_tercero_sin_sesion_lo_abre_y_descarga(cliente, correo):
    t, u, c, v, d = _con_documento("Compartir flujo")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert _crear(cliente, v, d).status_code == 302
    url = _enlace_de(cliente)
    assert "no se volverá a mostrar" not in cliente.get("/portal/carpeta").get_data(as_text=True)                  # el secreto solo se ve una vez
    tercero = cliente.application.test_client()
    ruta = "/portal/compartido/" + url.rsplit("/", 1)[1]
    pagina = tercero.get(ruta)
    assert pagina.status_code == 200 and "justificante-303.pdf" in pagina.get_data(as_text=True) and pagina.headers["Cache-Control"] == "no-store" and pagina.headers["Referrer-Policy"] == "no-referrer"
    assert pc.activos(_ficha(c))[0]["descargas"] == 0                                                              # abrir la página no gasta descargas
    r = tercero.post(ruta + "/descargar")
    assert r.status_code == 200 and r.data == PDF and "attachment" in r.headers["Content-Disposition"] and r.headers["X-Robots-Tag"].startswith("noindex")
    assert pc.activos(_ficha(c))[0]["descargas"] == 1


def test_el_secreto_no_se_guarda_en_claro_y_el_tope_de_descargas_se_respeta(cliente, correo):
    t, u, c, v, d = _con_documento("Compartir tope")
    _entrar(cliente, c, "titular@ejemplo.com")
    _crear(cliente, v, d, maximo=1)
    url = _enlace_de(cliente)
    token = url.rsplit("/", 1)[1]
    conn = db.get_connection()
    huellas = [f["huella"] for f in conn.execute("SELECT huella FROM portal_enlaces_compartidos").fetchall()]
    conn.close()
    assert huellas and all(token not in h and len(h) == 64 for h in huellas)
    tercero = cliente.application.test_client()
    assert tercero.post(f"/portal/compartido/{token}/descargar").status_code == 200
    assert tercero.post(f"/portal/compartido/{token}/descargar").status_code == 404 and tercero.get(f"/portal/compartido/{token}").status_code == 404
    assert "ya no está disponible" in tercero.get(f"/portal/compartido/{token}").get_data(as_text=True)


def test_caduca_y_se_puede_anular(cliente, correo):
    t, u, c, v, d = _con_documento("Compartir caduca")
    ficha = _ficha(c)
    token = pc.crear(ficha, v, d, "1", 5, "titular@ejemplo.com")
    assert pc.ver(token) is not None and pc.ver(token, ahora=datetime.now() + timedelta(days=2)) is None and pc.descargar(token, ahora=datetime.now() + timedelta(days=2)) is None
    _entrar(cliente, c, "titular@ejemplo.com")
    enlace = pc.activos(ficha)[0]["id"]
    cliente.post(f"/portal/carpeta/enlaces/{enlace}/anular", data={"anio": ""})
    assert pc.activos(ficha) == [] and pc.ver(token) is None


def test_solo_el_perfil_completo_comparte_y_solo_documentos_de_su_carpeta(cliente, correo):
    t, u, c, v, d = _con_documento("Compartir perfiles")
    t2, u2, c2, v2, d2 = _con_documento("Compartir ajeno")
    ficha = _ficha(c)
    portal_personas.anadir(ficha, "admin@ejemplo.com", "Admin", "administracion", por=u)
    portal_personas.anadir(ficha, "mira@ejemplo.com", "Mira", "consulta", por=u)
    cliente.post("/portal/salir"); _entrar(cliente, c, "admin@ejemplo.com")
    assert _crear(cliente, v, d).status_code == 403 and "Compartir" not in _html(cliente, "/portal/carpeta").split("car-docs")[1].split("</section>")[0]
    cliente.post("/portal/salir"); _entrar(cliente, c, "mira@ejemplo.com")
    assert _crear(cliente, v, d).status_code == 403
    cliente.post("/portal/salir"); _entrar(cliente, c, "titular@ejemplo.com")
    r = _crear(cliente, v2, d2)                                                                                    # el documento es de otro cliente
    assert r.status_code == 302 and pc.activos(ficha) == []
    with pytest.raises(pc.ErrorEnlace):
        pc.crear(ficha, v, d, "99", 5, "x")
    with pytest.raises(pc.ErrorEnlace):
        pc.crear(ficha, v, d, "7", 7, "x")


def test_la_carpeta_ofrece_filtros_vista_previa_y_enlaza_el_pdf_en_linea(cliente, correo):
    t, u, c, v, d = _con_documento("Carpeta filtros")
    _entrar(cliente, c, "titular@ejemplo.com")
    html = _html(cliente, "/portal/carpeta")
    assert "data-filtro-texto" in html and "data-filtro-tipo" in html and 'data-ver="' in html and "portal_carpeta.js" in html and "<dialog" in html
    r = cliente.get(f"/portal/vencimientos/{v}/documentos/{d}?ver=1")
    assert r.status_code == 200 and "inline" in r.headers["Content-Disposition"]
    assert "attachment" in cliente.get(f"/portal/vencimientos/{v}/documentos/{d}").headers["Content-Disposition"]
