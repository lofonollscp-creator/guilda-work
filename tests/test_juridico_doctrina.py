"""Conectores de doctrina tributaria (DGT · PETETE y TEAC · DYCTEA): estructura comprobada contra los servicios reales el 3-nov-2026, probada aquí con fixtures SINTÉTICAS (tests/fixtures_juridico)."""
import pytest

from app import db
from app.juridico import busqueda, corpus, ingesta
from app.juridico.conectores.base import ErrorConector, RefRegistro
from app.juridico.conectores.doctrina_tributaria import DgtConsultas, TeacCriterios
from app.juridico.http import ClienteHTTP
from tests.juridico_ayudas import TransporteFalso, fx, habilitar

PETETE = "https://petete.tributos.hacienda.gob.es/consultas"
DYCTEA = "https://serviciostelematicosext.hacienda.gob.es/TEAC/DYCTEA"
RANGO = "01/01/2099..31/01/2099"


class TransportePetete(TransporteFalso):
    """Como el servicio real: el documento solo se entrega con la cookie de sesión y la cabecera XHR; sin ellas, 401."""

    def __call__(self, url, cabeceras, timeout):
        if url == PETETE + "/":
            self.llamadas.append(url)
            return 200, {"Set-Cookie": "JSESSIONID=ABC123; Path=/consultas; HttpOnly"}, b"<html></html>"
        if "/do/document" in url:
            self.llamadas.append(url)
            if cabeceras.get("X-Requested-With") != "XMLHttpRequest" or "JSESSIONID=ABC123" not in cabeceras.get("Cookie", ""):
                return 401, {}, b"Unauthorized"
            return 200, {}, fx("dgt_documento_vinculante.html")
        return super().__call__(url, cabeceras, timeout)


def _petete():
    t = TransportePetete({
        f"{PETETE}/do/search?type1=on&NMCMP_2=FECHA-SALIDA&VLCMP_2={RANGO}&OPCMP_2=.Y&tab=1&page=1": (200, fx("dgt_busqueda_generales_vacia.html")),
        f"{PETETE}/do/search?type2=on&NMCMP_2=FECHA-SALIDA&VLCMP_2={RANGO}&OPCMP_2=.Y&tab=2&page=1": (200, fx("dgt_busqueda_vinculantes.html")),
    })
    return DgtConsultas(ClienteHTTP(DgtConsultas.dominios, transporte=t, dormir=lambda s: None, espera_base=0.0), pausa=0), t


def _teac(paginas=2):
    t = TransporteFalso({
        f"{DYCTEA}/criterios.aspx?s=1&rs=&rn=&ra=&fd=01/01/2099&fh=31/01/2099&u=&n=&p=&c1=&c2=&c3=&tc=&tr=&tp=&tf=&c=2&pg=1": (200, fx("teac_listado.html")),
        f"{DYCTEA}/criterios.aspx?s=1&rs=&rn=&ra=&fd=01/01/2099&fh=31/01/2099&u=&n=&p=&c1=&c2=&c3=&tc=&tr=&tp=&tf=&c=2&pg=2": (200, fx("teac_vacio.html")),
        f"{DYCTEA}/criterio.aspx?id=00/09001/2099/00/0/1": (200, fx("teac_criterio.html")),
    })
    return TeacCriterios(ClienteHTTP(TeacCriterios.dominios, transporte=t, dormir=lambda s: None, espera_base=0.0), pausa=0), t


def test_dgt_descubre_por_pestanas_y_salta_las_consultas_anuladas():
    c, _t = _petete()
    p1 = c.discover("2099-01-01", "2099-01-31", None)
    assert p1.registros == [] and p1.siguiente_cursor == "2:1" and not p1.agotada                # generales: sin resultados; sigue con las vinculantes
    p2 = c.discover("2099-01-01", "2099-01-31", "2:1")
    assert [r.id_externo for r in p2.registros] == ["V9001-99", "V9003-99"] and p2.agotada and p2.notas["anuladas"] == 1
    assert p2.registros[0].localizador == f"tab=2&doc=90001&rango={RANGO}"


def test_dgt_pide_la_sesion_una_vez_y_analiza_la_consulta():
    c, t = _petete()
    ref = RefRegistro("dgt-consultas", "V9001-99", None, f"tab=2&doc=90001&rango={RANGO}")
    p = c.parse(ref, c.fetch(ref))
    c.fetch(ref)
    assert t.llamadas.count(PETETE + "/") == 1                                                      # la cookie se reutiliza
    d = p.documento
    assert d.coleccion == "doctrina" and d.tipo == "consulta_vinculante" and d.fecha_resolucion == "2099-01-05" and d.emisor == "SG de Impuestos Sintéticos"
    assert d.url_canonica == PETETE + "/?num_consulta=V9001-99" and d.ecli is None
    assert [f.localizador for f in p.fragmentos] == ["Normativa", "Descripción de hechos", "Cuestión planteada", "Contestación completa"]
    assert "diez por ciento" in p.fragmentos[-1].texto and "\n" in p.fragmentos[-1].texto and any("art. 89 LGT" in a for a in p.advertencias)


def test_dgt_rechaza_referencias_ajenas_y_documentos_que_no_son_el_pedido():
    c, _t = _petete()
    with pytest.raises(ErrorConector):
        c.fetch(RefRegistro("dgt-consultas", "V9001-99", None, "tab=2&doc=../../etc&rango=x"))
    ref = RefRegistro("dgt-consultas", "V0000-00", None, f"tab=2&doc=90001&rango={RANGO}")
    with pytest.raises(ErrorConector, match="no coincide"):
        c.parse(ref, c.fetch(ref))


def test_teac_pagina_el_listado_y_analiza_el_criterio():
    c, _t = _teac()
    p1 = c.discover("2099-01-01", "2099-01-31", None)
    assert [r.id_externo for r in p1.registros] == ["00/09001/2099/00/0/1", "00/09002/2099/00/0/2"] and p1.siguiente_cursor == "2" and not p1.agotada and p1.notas["total"] == 12
    assert c.discover("2099-01-01", "2099-01-31", "2").agotada
    ref = p1.registros[0]
    p = c.parse(ref, c.fetch(ref))
    d = p.documento
    assert d.coleccion == "doctrina" and d.tipo == "criterio_teac" and d.rango == "Doctrina" and d.emisor == "TEAC" and d.fecha_resolucion == "2099-01-10"
    assert d.titulo == "TEAC · Criterio 1 de la resolución 00/09001/2099/00/00" and d.url_canonica == DYCTEA + "/criterio.aspx?id=00/09001/2099/00/0/1"
    assert [f.localizador for f in p.fragmentos] == ["Asunto", "Criterio"] and "cuatro años" in p.fragmentos[1].texto and "<" not in p.fragmentos[1].texto
    otra = RefRegistro("teac-dyctea", "00/00000/2099/00/0/1", None, ref.localizador)
    with pytest.raises(ErrorConector, match="no coincide"):
        c.parse(otra, c.fetch(ref))
    with pytest.raises(ErrorConector):
        c.fetch(RefRegistro("teac-dyctea", "00/09001/2099/00/0/1", None, "https://otro.dominio.es/criterio.aspx?id=1"))


def test_un_servicio_que_cambia_de_formato_se_detecta_y_no_se_inventa_nada():
    t = TransporteFalso({f"{DYCTEA}/criterios.aspx?s=1&rs=&rn=&ra=&fd=01/01/2099&fh=31/01/2099&u=&n=&p=&c1=&c2=&c3=&tc=&tr=&tp=&tf=&c=2&pg=1": (200, b"<html><body>otra cosa</body></html>")})
    c = TeacCriterios(ClienteHTTP(TeacCriterios.dominios, transporte=t, dormir=lambda s: None, espera_base=0.0), pausa=0)
    with pytest.raises(ErrorConector, match="formato esperado"):
        c.discover("2099-01-01", "2099-01-31", None)


def test_sin_politica_no_se_sincroniza_y_con_ella_la_doctrina_entra_en_la_biblioteca():
    from app.juridico import catalogo
    catalogo.asegurar_catalogo()
    assert {"dgt-consultas", "teac-dyctea"} <= {f["id"] for f in corpus.listar_fuentes()}
    assert all(not f["habilitada"] for f in corpus.listar_fuentes() if f["id"] in ("dgt-consultas", "teac-dyctea"))
    c, _t = _petete()
    r = ingesta.sincronizar("dgt-consultas", c, "2099-01-01", "2099-01-31")
    assert r["estado"] in ("bloqueada", "fallida") or r["contadores"].get("publicados", 0) == 0          # sin política no entra nada

    habilitar("dgt-consultas")
    t = db.crear_tenant("Despacho doctrina")
    c, _t = _petete()
    r = ingesta.sincronizar("dgt-consultas", c, "2099-01-01", "2099-01-31")
    assert r["estado"] in ("completa", "parcial")
    res = busqueda.buscar(t, "tipo reducido diez por ciento", colecciones=["doctrina"])
    assert any("V9001-99" in x["titulo"] for x in res["resultados"]), res
