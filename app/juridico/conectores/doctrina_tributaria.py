"""Conectores de doctrina tributaria administrativa: consultas de la Dirección General de Tributos (PETETE) y criterios del Tribunal Económico-Administrativo Central (DYCTEA).

Ninguno de los dos servicios tiene API documentada: se consultan sus pantallas públicas, que es lo que hace cualquier persona con un navegador, con un ritmo de peticiones bajo, una lista blanca de
dominio y tope de tamaño y de tiempo (cliente de `app/juridico/http.py`). Que existan estos conectores NO los habilita: hace falta registrar una política con su evidencia (aviso legal y condiciones de
reutilización, que revisa una persona) y habilitar la fuente. Formato comprobado contra los servicios reales el 3-nov-2026:

PETETE (DGT) · `https://petete.tributos.hacienda.gob.es/consultas/`
- `GET /consultas/` crea la sesión (cookie JSESSIONID).
- `GET /consultas/do/search?type1=on&type2=on&NMCMP_2=FECHA-SALIDA&VLCMP_2=dd/mm/aaaa..dd/mm/aaaa&OPCMP_2=.Y&tab=1|2&page=N` -> fragmento HTML con `<td id="doc_NNNN">` por consulta, el número en
  `<span class="NUM-CONSULTA">` («Número de consulta anulado» si se retiró), y `updateNumResults("tab", "N")` con el total. Pestaña 1 = consultas generales, 2 = vinculantes.
- `GET /consultas/do/document?query=…&order=&doc=NNNN&tab=T` (con la cookie y `X-Requested-With: XMLHttpRequest`; sin ellas responde 401) -> tabla con filas `NUM-CONSULTA`, `ORGANO`,
  `FECHA-SALIDA`, `NORMATIVA`, `DESCRIPCION-HECHOS`, `CUESTION-PLANTEADA` y `CONTESTACION-COMPL`.

DYCTEA (TEAC) · `https://serviciostelematicosext.hacienda.gob.es/TEAC/DYCTEA/`
- `GET criterios.aspx?s=1&rs=&rn=&ra=&fd=dd/mm/aaaa&fh=dd/mm/aaaa&u=&n=&p=&c1=&c2=&c3=&tc=&tr=&tp=&tf=&c=2&pg=N` -> 10 resultados por página (`<li class='resultadoCriterio'>` con el enlace
  `criterio.aspx?id=…` y «Se han obtenido N resultados.»). `c`: 0 vinculantes, 1 no vinculantes, 2 todos.
- `GET criterio.aspx?id=…` -> «Criterio X de Y de la resolución …», calificación, unidad resolutoria, fecha, asunto y texto del criterio.

Lo que se guarda es lo que la fuente publica; la doctrina administrativa no es jurisprudencia: se etiqueta como tal y la consulta vinculante lo es solo para quien la formuló (art. 89 LGT)."""
from __future__ import annotations

import html
import math
import re
import time
from datetime import date

from lxml import html as lhtml

from ..corpus import DocumentoNuevo, FragmentoNuevo, partir_parrafos
from ..http import ClienteHTTP, ErrorHTTP
from .base import Capacidades, Conector, ErrorConector, Original, PaginaDescubrimiento, Parseado, RefRegistro

PAUSA_ENTRE_PETICIONES = 0.8              # segundos: un ritmo humano, no un rastreo agresivo
MAX_PAGINAS_POR_DESCUBRIMIENTO = 1        # una página de resultados por llamada (el motor pide la siguiente con el cursor)


def _texto(nodo) -> str:
    """Texto plano de un nodo HTML: sin etiquetas ni comentarios, espacios colapsados; los párrafos se separan con salto de línea."""
    if nodo is None:
        return ""
    for malo in nodo.xpath(".//script|.//style"):
        malo.drop_tree()
    for br in nodo.xpath(".//br"):
        br.tail = "\n" + (br.tail or "")
    for p in nodo.xpath(".//p|.//div|.//li"):
        p.tail = "\n" + (p.tail or "")
    bruto = nodo.text_content()
    lineas = [" ".join(l.split()) for l in html.unescape(bruto).replace("\xa0", " ").split("\n")]
    return "\n".join(l for l in lineas if l).strip()


def _fecha_dmy(valor: str | None) -> str | None:
    m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*", valor or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def _dmy(iso: str) -> str:
    d = date.fromisoformat(iso)
    return d.strftime("%d/%m/%Y")


def _fragmentos(secciones: list[tuple[str, str]]) -> list[FragmentoNuevo]:
    salida = []
    for etiqueta, texto in secciones:
        partes = partir_parrafos(texto)
        for i, p in enumerate(partes, 1):
            salida.append(FragmentoNuevo(etiqueta if len(partes) == 1 else f"{etiqueta} (parte {i}/{len(partes)})", p))
    return salida


class DgtConsultas(Conector):
    id = "dgt-consultas"
    nombre = "DGT · consultas tributarias (PETETE)"
    coleccion = "doctrina"
    capacidades = Capacidades(descubrir=True, metadatos=True, contenido=True, actualizaciones="time_window", retiradas=False)
    dominios = frozenset({"petete.tributos.hacienda.gob.es"})
    BASE = "https://petete.tributos.hacienda.gob.es/consultas"

    def __init__(self, cliente: ClienteHTTP | None = None, pausa: float = PAUSA_ENTRE_PETICIONES, dormir=time.sleep):
        self.http = cliente or ClienteHTTP(self.dominios)
        self._pausa, self._dormir = pausa, dormir
        self._cookie: str | None = None

    def _get(self, url: str, cabeceras: dict | None = None):
        if self._pausa:
            self._dormir(self._pausa)
        try:
            return self.http.get(url, cabeceras or {"Accept": "text/html"})
        except ErrorHTTP as e:
            raise ErrorConector(str(e), transitorio=e.transitorio) from e

    def _sesion(self) -> str | None:
        """La cookie de sesión que pide el visor de documentos; se pide una vez por conector."""
        if self._cookie is None:
            r = self._get(self.BASE + "/")
            m = re.search(r"JSESSIONID=([A-Za-z0-9._-]+)", r.cabeceras.get("set-cookie", ""))
            self._cookie = m.group(1) if m else ""
        return self._cookie or None

    # -- descubrir: cursor «pestaña:página» -------------------------------------------------------------------------------------------------------------------
    def discover(self, desde: str, hasta: str, cursor: str | None) -> PaginaDescubrimiento:
        tab, pagina = (int(x) for x in cursor.split(":")) if cursor else (1, 1)
        rango = f"{_dmy(desde)}..{_dmy(hasta)}"
        url = f"{self.BASE}/do/search?type{tab}=on&NMCMP_2=FECHA-SALIDA&VLCMP_2={rango}&OPCMP_2=.Y&tab={tab}&page={pagina}"
        r = self._get(url)
        if r.estado == 408:
            raise ErrorConector("PETETE tarda demasiado: hay que acotar más la ventana de fechas.", transitorio=True)
        if r.estado != 200:
            raise ErrorConector(f"PETETE respondió {r.estado} a la búsqueda de la pestaña {tab}.", transitorio=r.estado >= 500)
        texto = r.cuerpo.decode("utf-8", "replace")
        if "no devuelve resultados" in texto:
            total, filas = 0, []
        else:
            m = re.search(r'updateNumResults\("\d",\s*"(\d+)"\)', texto)
            if not m:
                raise ErrorConector("La respuesta de PETETE no tiene el formato esperado (¿ha cambiado el servicio?).")
            total = int(m.group(1))
            filas = lhtml.fromstring(texto).xpath('//td[starts-with(@id, "doc_")]')
        refs, anuladas = [], 0
        for td in filas:
            doc_id = td.get("id", "")[4:]
            cabecera = _texto(td.xpath('.//span[contains(@class, "NUM-CONSULTA")]')[0]) if td.xpath('.//span[contains(@class, "NUM-CONSULTA")]') else ""
            num = cabecera.split()[0] if cabecera else ""
            if not doc_id.isdigit() or not num:
                continue
            if "anulado" in cabecera.lower():
                anuladas += 1
                continue
            refs.append(RefRegistro(self.id, num, None, f"tab={tab}&doc={doc_id}&rango={rango}"))
        mt = re.search(r'id="total_pages">(\d+)<', texto)
        paginas = int(mt.group(1)) if mt else max(1, math.ceil(total / 10))
        if pagina < paginas:
            siguiente, agotada = f"{tab}:{pagina + 1}", False
        elif tab == 1:
            siguiente, agotada = "2:1", False
        else:
            siguiente, agotada = None, True
        return PaginaDescubrimiento(registros=refs, siguiente_cursor=siguiente, agotada=agotada, evidencia=[Original(r.cuerpo, "text/html", url)], notas={"anuladas": anuladas, "total_pestana": total})

    # -- descargar ---------------------------------------------------------------------------------------------------------------------------------------------
    def fetch(self, ref: RefRegistro) -> Original:
        datos = dict(p.split("=", 1) for p in ref.localizador.split("&") if "=" in p)
        if not (datos.get("doc", "").isdigit() and datos.get("tab") in ("1", "2") and datos.get("rango")):
            raise ErrorConector("La referencia del registro no es válida.")
        cab = {"Accept": "text/html", "X-Requested-With": "XMLHttpRequest", "Referer": self.BASE + "/"}
        sesion = self._sesion()
        if sesion:
            cab["Cookie"] = f"JSESSIONID={sesion}"
        consulta = f" .EN FECHA-SALIDA ({datos['rango']})"
        from urllib.parse import quote
        url = f"{self.BASE}/do/document?query={quote(consulta)}&order=&doc={datos['doc']}&tab={datos['tab']}"
        r = self._get(url, cab)
        if r.estado == 401:                              # la sesión caducó: se pide otra y se reintenta una vez
            self._cookie = None
            sesion = self._sesion()
            if sesion:
                cab["Cookie"] = f"JSESSIONID={sesion}"
            r = self._get(url, cab)
        if r.estado != 200:
            raise ErrorConector(f"PETETE respondió {r.estado} al documento {ref.id_externo}.", transitorio=r.estado >= 500 or r.estado == 429)
        if b"NUM-CONSULTA" not in r.cuerpo or b"document doc_" not in r.cuerpo:
            raise ErrorConector("La respuesta no es el documento de una consulta (puede ser una página de error).")
        return Original(r.cuerpo, "text/html", f"{self.BASE}/?num_consulta={ref.id_externo}")

    # -- analizar ----------------------------------------------------------------------------------------------------------------------------------------------
    def parse(self, ref: RefRegistro, original: Original) -> Parseado:
        arbol = lhtml.fromstring(original.contenido.decode("utf-8", "replace"))
        campos = {}
        for fila in arbol.xpath('//table[contains(@class, "document")]//tr'):
            clase = (fila.get("class") or "").strip()
            valor = fila.xpath('./td[contains(@class, "value")]')
            if clase and valor:
                campos[clase] = _texto(valor[0])
        num = campos.get("NUM-CONSULTA", "")
        if num != ref.id_externo:
            raise ErrorConector(f"El número de la consulta ({num or 'vacío'}) no coincide con el solicitado ({ref.id_externo}).")
        fecha = _fecha_dmy(campos.get("FECHA-SALIDA"))
        vinculante = num.upper().startswith("V")
        tipo = "consulta_vinculante" if vinculante else "consulta_general"
        doc = DocumentoNuevo(
            fuente_id=self.id, id_externo=num, coleccion="doctrina", titulo=f"DGT · {'Consulta vinculante' if vinculante else 'Consulta general'} {num}", materia=None,
            emisor=campos.get("ORGANO") or "Dirección General de Tributos", territorio="ES", rango="Consulta vinculante" if vinculante else "Consulta general", tipo=tipo,
            url_canonica=f"{self.BASE}/?num_consulta={num}", fecha_publicacion=fecha, fecha_resolucion=fecha)
        secciones = [(et, campos[c]) for c, et in (("NORMATIVA", "Normativa"), ("DESCRIPCION-HECHOS", "Descripción de hechos"), ("CUESTION-PLANTEADA", "Cuestión planteada"),
                                                    ("CONTESTACION-COMPL", "Contestación completa")) if campos.get(c)]
        if not any(et == "Contestación completa" for et, _ in secciones):
            raise ErrorConector("La consulta no trae contestación: no se puede citar.")
        advertencias = ["Doctrina administrativa: la contestación vincula a la Administración tributaria solo en su relación con quien formuló la consulta (art. 89 LGT); no es jurisprudencia."] if vinculante else \
                       ["Consulta general: criterio de la Dirección General de Tributos, sin los efectos de una consulta vinculante."]
        if not fecha:
            advertencias.append("La fuente no indica una fecha de salida legible: no se ha supuesto ninguna.")
        return Parseado(doc, _fragmentos(secciones), [], advertencias=advertencias)


class TeacCriterios(Conector):
    id = "teac-dyctea"
    nombre = "TEAC · criterios (DYCTEA)"
    coleccion = "doctrina"
    capacidades = Capacidades(descubrir=True, metadatos=True, contenido=True, actualizaciones="time_window", retiradas=False)
    dominios = frozenset({"serviciostelematicosext.hacienda.gob.es"})
    BASE = "https://serviciostelematicosext.hacienda.gob.es/TEAC/DYCTEA"
    POR_PAGINA = 10

    def __init__(self, cliente: ClienteHTTP | None = None, pausa: float = PAUSA_ENTRE_PETICIONES, dormir=time.sleep):
        self.http = cliente or ClienteHTTP(self.dominios)
        self._pausa, self._dormir = pausa, dormir

    def _get(self, url: str):
        if self._pausa:
            self._dormir(self._pausa)
        try:
            return self.http.get(url, {"Accept": "text/html"})
        except ErrorHTTP as e:
            raise ErrorConector(str(e), transitorio=e.transitorio) from e

    def discover(self, desde: str, hasta: str, cursor: str | None) -> PaginaDescubrimiento:
        pagina = int(cursor) if cursor else 1
        url = (f"{self.BASE}/criterios.aspx?s=1&rs=&rn=&ra=&fd={_dmy(desde)}&fh={_dmy(hasta)}&u=&n=&p=&c1=&c2=&c3=&tc=&tr=&tp=&tf=&c=2&pg={pagina}")
        r = self._get(url)
        if r.estado != 200:
            raise ErrorConector(f"DYCTEA respondió {r.estado} a la búsqueda.", transitorio=r.estado >= 500)
        texto = r.cuerpo.decode("utf-8", "replace")
        if "No se ha encontrado ning" in texto:
            return PaginaDescubrimiento(agotada=True, evidencia=[Original(r.cuerpo, "text/html", url)])
        m = re.search(r"Se han obtenido\s+(\d+)\s+resultado", texto)
        if not m:
            raise ErrorConector("La respuesta de DYCTEA no tiene el formato esperado (¿ha cambiado el servicio?).")
        total = int(m.group(1))
        refs = []
        for a in lhtml.fromstring(texto).xpath("//li[@class='resultadoCriterio']//span[@class='resultadoCriterioTitulo']/a"):
            mid = re.search(r"criterio\.aspx\?id=([0-9/]+)", a.get("href", ""))
            if mid:
                refs.append(RefRegistro(self.id, mid.group(1), None, f"{self.BASE}/criterio.aspx?id={mid.group(1)}"))
        paginas = max(1, math.ceil(total / self.POR_PAGINA))
        agotada = pagina >= paginas
        return PaginaDescubrimiento(registros=refs, siguiente_cursor=None if agotada else str(pagina + 1), agotada=agotada, evidencia=[Original(r.cuerpo, "text/html", url)], notas={"total": total})

    def fetch(self, ref: RefRegistro) -> Original:
        if not re.fullmatch(r"[0-9/]+", ref.id_externo) or not ref.localizador.startswith(self.BASE + "/criterio.aspx?id="):
            raise ErrorConector("La referencia del registro no es válida.")
        r = self._get(ref.localizador)
        if r.estado != 200:
            raise ErrorConector(f"DYCTEA respondió {r.estado} al criterio {ref.id_externo}.", transitorio=r.estado >= 500 or r.estado == 429)
        if b"criterioDatosContenido" not in r.cuerpo:
            raise ErrorConector("La respuesta no es un criterio del TEAC (puede ser una página de error).")
        return Original(r.cuerpo, "text/html", ref.localizador)

    def parse(self, ref: RefRegistro, original: Original) -> Parseado:
        arbol = lhtml.fromstring(original.contenido.decode("utf-8", "replace"))

        def dato(id_div: str) -> str:
            nodos = arbol.xpath(f"//div[@id='{id_div}']")
            return _texto(nodos[0]) if nodos else ""

        titulo_div = dato("criterioDatosTitulo")
        mt = re.search(r"Criterio\s+(\d+)\s+de\s+(\d+)\s+de la resoluci[óo]n:?\s*(\S+)", titulo_div)
        if not mt:
            raise ErrorConector("El criterio no indica su resolución: no se puede identificar.")
        rg = mt.group(3)
        if rg.split("/")[:4] != ref.id_externo.split("/")[:4]:
            raise ErrorConector(f"La resolución del criterio ({rg}) no coincide con la solicitada ({ref.id_externo}).")
        calificacion = dato("criterioDatosCalificacion").replace("Calificación:", "").strip()
        unidad = dato("criterioDatosUnidad").replace("Unidad resolutoria:", "").strip()
        fecha = _fecha_dmy(dato("criterioDatosFecha").replace("Fecha de la resolución:", ""))
        asunto = dato("criterioDatosAsunto").replace("Asunto:", "", 1).strip()
        contenido = dato("criterioDatosContenido").replace("Criterio:", "", 1).strip()
        if not contenido:
            raise ErrorConector("El criterio no trae texto: no se puede citar.")
        doc = DocumentoNuevo(
            fuente_id=self.id, id_externo=ref.id_externo, coleccion="doctrina", titulo=f"{unidad or 'TEAC'} · Criterio {mt.group(1)} de la resolución {rg}", materia=None,
            emisor=unidad or "Tribunal Económico-Administrativo Central", territorio="ES", rango=calificacion or "Criterio", tipo="criterio_teac",
            url_canonica=f"{self.BASE}/criterio.aspx?id={ref.id_externo}", fecha_publicacion=fecha, fecha_resolucion=fecha)
        advertencias = [f"Calificación según la fuente: {calificacion}." if calificacion else "La fuente no indica la calificación del criterio.",
                        "Doctrina administrativa de un tribunal económico-administrativo: no es jurisprudencia."]
        return Parseado(doc, _fragmentos([(et, t) for et, t in (("Asunto", asunto), ("Criterio", contenido)) if t]), [], advertencias=advertencias)
