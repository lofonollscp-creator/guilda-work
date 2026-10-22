"""Conector «BOE · diario» para las resoluciones del Tribunal Constitucional publicadas en el BOE.

Esto NO es el fondo completo del TC ni jurisprudencia ordinaria: es lo que el BOE publica del TC (sentencias, autos y declaraciones). La sección de Administración de Justicia (anuncios) y los demás
departamentos no se ingieren. Cobertura real = lo que haya descubierto y publicado este conector (se enseña en «Fuentes»).

Formato comprobado contra el servicio real el 23-oct-2026:
- `GET /datosabiertos/api/boe/sumario/AAAAMMDD` -> `<response><data><sumario><diario><seccion codigo nombre><departamento codigo nombre>[<epigrafe nombre>]<item><identificador/><titulo/>
  <url_pdf/><url_html/><url_xml/>`. Un día sin edición (domingos…) responde 404: se clasifica como «sin edición», no como error.
- `GET /diario_boe/xml.php?id=BOE-A-…` -> `<documento><metadatos>…</metadatos><analisis/><texto><p class=…>`.

Candidato = ítem de un departamento cuyo nombre contiene «TRIBUNAL CONSTITUCIONAL» (y no es un ministerio) cuyo título es una sentencia, un auto o una declaración. El resto de ítems del TC
(nombramientos, convocatorias, correcciones) se descartan y se cuentan. ECLI y número de recurso solo se guardan si constan literalmente en el texto; nunca se componen."""
from __future__ import annotations

import re
from datetime import date, timedelta

from lxml import etree

from ..corpus import DocumentoNuevo, FragmentoNuevo, fecha_iso, partir_parrafos
from ..http import ClienteHTTP, ErrorHTTP
from .base import Capacidades, Conector, ErrorConector, Original, PaginaDescubrimiento, Parseado, RefRegistro
from .boe_consolidada import analizador

BASE_API = "https://www.boe.es/datosabiertos/api/boe/sumario"
_ECLI = re.compile(r"ECLI:ES:TC:\d{4}:\d+A?")
_TIPO = [("sentencia", re.compile(r"\bSentencia\s+\d+/\d{4}", re.I)), ("auto", re.compile(r"\bAuto\s+\d+/\d{4}", re.I)), ("declaracion", re.compile(r"\bDeclaraci[óo]n\s+\d+/\d{4}", re.I))]
_SECCION = re.compile(r"^(?:[IVX]{1,4}\.\s*)?(ANTECEDENTES|FUNDAMENTOS? JUR[ÍI]DICOS?|FALLO|PARTE DISPOSITIVA|VOTO PARTICULAR|ACUERDO|JUICIO|ANTECEDENTES DE HECHO|RAZONAMIENTOS JUR[ÍI]DICOS?)\b", re.I)
_NUMERADO = re.compile(r"^(\d{1,3})\.\s")
_RECURSO = re.compile(r"(?:Recurso|Cuesti[óo]n|Conflicto)[^.]{0,80}?\d+-\d{4}", re.I)


def tipo_de_titulo(titulo: str) -> str | None:
    """sentencia | auto | declaracion si el título lo dice con su numeración; None si no es una resolución judicial del TC."""
    for nombre, patron in _TIPO:
        if patron.search(titulo or ""):
            return nombre
    return None


def es_departamento_del_tc(nombre: str) -> bool:
    n = (nombre or "").upper()
    return "TRIBUNAL CONSTITUCIONAL" in n and not n.startswith("MINISTERIO") and "FISCAL" not in n


class BoeDiario(Conector):
    id = "boe-diario-tc"
    nombre = "BOE · resoluciones del Tribunal Constitucional publicadas"
    coleccion = "jurisprudencia"
    capacidades = Capacidades(descubrir=True, metadatos=True, contenido=True, actualizaciones="time_window", retiradas=False)
    dominios = frozenset({"www.boe.es"})

    def __init__(self, cliente: ClienteHTTP | None = None):
        self.http = cliente or ClienteHTTP(self.dominios)

    # -- descubrir: una página = un día --------------------------------------------------------------------------------------------------------------------
    def discover(self, desde: str, hasta: str, cursor: str | None) -> PaginaDescubrimiento:
        dia = date.fromisoformat(cursor) if cursor else date.fromisoformat(desde)
        fin = date.fromisoformat(hasta)
        if dia > fin:
            return PaginaDescubrimiento(agotada=True)
        url = f"{BASE_API}/{dia.strftime('%Y%m%d')}"
        r = self._get(url)
        siguiente = (dia + timedelta(days=1)).isoformat()
        agotada = dia >= fin
        if r.estado == 404:
            return PaginaDescubrimiento(siguiente_cursor=None if agotada else siguiente, agotada=agotada, notas={"dias_sin_edicion": 1})
        if r.estado != 200:
            raise ErrorConector(f"El BOE respondió {r.estado} al sumario del {dia}.", transitorio=r.estado >= 500)
        raiz = self._xml(r.cuerpo)
        refs, descartados = [], 0
        for dep in raiz.iter("departamento"):
            if not es_departamento_del_tc(dep.get("nombre", "")):
                continue
            for it in dep.iter("item"):
                ident = (it.findtext("identificador") or "").strip()
                titulo = (it.findtext("titulo") or "").strip()
                if not ident:
                    continue
                if tipo_de_titulo(titulo) is None:
                    descartados += 1
                    continue
                url_xml = (it.findtext("url_xml") or "").strip()
                if not url_xml:                                   # un formato ausente se registra, no se construye por plantilla
                    descartados += 1
                    continue
                refs.append(RefRegistro(self.id, ident, dia.strftime("%Y%m%d"), url_xml))
        return PaginaDescubrimiento(registros=refs, siguiente_cursor=None if agotada else siguiente, agotada=agotada, evidencia=[Original(r.cuerpo, "application/xml", url)],
                                    notas={"descartados": descartados})

    # -- descargar ----------------------------------------------------------------------------------------------------------------------------------------
    def fetch(self, ref: RefRegistro) -> Original:
        r = self._get(ref.localizador)
        if r.estado != 200:
            raise ErrorConector(f"El BOE respondió {r.estado} al documento {ref.id_externo}.", transitorio=r.estado >= 500 or r.estado == 429)
        raiz = self._xml(r.cuerpo)
        if raiz.tag != "documento" or raiz.find("metadatos") is None or raiz.find("texto") is None:
            raise ErrorConector("La respuesta no es un documento del BOE (puede ser una página de error).", transitorio=False)
        return Original(r.cuerpo, "application/xml", ref.localizador)

    # -- analizar -----------------------------------------------------------------------------------------------------------------------------------------
    def parse(self, ref: RefRegistro, original: Original) -> Parseado:
        raiz = self._xml(original.contenido)
        meta = raiz.find("metadatos")
        ident = (meta.findtext("identificador") or "").strip() if meta is not None else ""
        if ident != ref.id_externo:
            raise ErrorConector(f"El identificador del documento ({ident or 'vacío'}) no coincide con el solicitado ({ref.id_externo}).")
        titulo = (meta.findtext("titulo") or "").strip()
        dep = (meta.findtext("departamento") or "").strip()
        tipo = tipo_de_titulo(titulo)
        if not es_departamento_del_tc(dep) or tipo is None:
            raise ErrorConector("El documento no es una resolución del Tribunal Constitucional (emisor o tipo no coinciden con el candidato).")
        parrafos = []
        for p in raiz.find("texto").iter("p"):
            t = " ".join("".join(p.itertext()).split())
            if t:
                parrafos.append((p.get("class") or "", t))
        if not parrafos:
            raise ErrorConector("La resolución no trae texto.")
        texto_completo = "\n".join(t for _c, t in parrafos)
        ecli = next(iter(_ECLI.findall(texto_completo + " " + titulo)), None)
        recurso = _RECURSO.search(titulo)
        pub = fecha_iso(meta.findtext("fecha_publicacion"))
        doc = DocumentoNuevo(
            fuente_id=self.id, id_externo=ident, coleccion="jurisprudencia", titulo=titulo, materia=None, emisor="Tribunal Constitucional", territorio="ES", rango=tipo.capitalize(), tipo=tipo,
            url_canonica=f"https://www.boe.es/diario_boe/txt.php?id={ident}", ecli=ecli, fecha_publicacion=pub, fecha_resolucion=fecha_iso(meta.findtext("fecha_disposicion")))
        advertencias = []
        if recurso:
            advertencias.append(f"Referencia procesal en el título: {recurso.group(0)}")
        if ecli is None:
            advertencias.append("El texto publicado no incluye un ECLI: no se ha compuesto uno.")
        fragmentos = self._fragmentos(parrafos, advertencias)
        if not fragmentos:
            raise ErrorConector("No se han podido extraer fragmentos citables de la resolución.")
        return Parseado(doc, fragmentos, [], advertencias=advertencias)

    @staticmethod
    def _fragmentos(parrafos: list[tuple[str, str]], advertencias: list[str]) -> list[FragmentoNuevo]:
        """Cabecera, antecedentes, fundamentos jurídicos, fallo y votos. Un voto particular lleva siempre su etiqueta: no es el criterio de la mayoría."""
        seccion, bloques, actual = "Cabecera", [], None

        def abrir(loc: str):
            nonlocal actual
            actual = {"loc": loc, "txt": []}
            bloques.append(actual)

        abrir("Cabecera")
        voto = False
        for clase, t in parrafos:
            m = _SECCION.match(t) if (clase.startswith("centro") or len(t) < 90) else None
            if m:
                nombre = m.group(1).upper()
                voto = voto or nombre.startswith("VOTO PARTICULAR")
                seccion = {"ANTECEDENTES": "Antecedentes", "ANTECEDENTES DE HECHO": "Antecedentes", "FALLO": "Fallo", "PARTE DISPOSITIVA": "Fallo", "ACUERDO": "Acuerdo",
                           "JUICIO": "Fundamentos jurídicos"}.get(nombre, "Fundamentos jurídicos" if "JUR" in nombre else ("Voto particular" if nombre.startswith("VOTO") else nombre.capitalize()))
                abrir(seccion if seccion in ("Fallo", "Acuerdo", "Voto particular") else seccion)
                continue
            n = _NUMERADO.match(t)
            if n and seccion in ("Antecedentes", "Fundamentos jurídicos", "Voto particular"):
                etiqueta = {"Antecedentes": "Antecedente", "Fundamentos jurídicos": "FJ", "Voto particular": "Voto particular, ap."}[seccion]
                abrir(f"{etiqueta} {n.group(1)}")
            actual["txt"].append(t)
        salida = []
        for b in bloques:
            texto = "\n".join(b["txt"]).strip()
            if not texto:
                continue
            etiqueta = b["loc"]
            if etiqueta.startswith("Voto particular"):
                etiqueta = f"Voto particular (no es el criterio de la mayoría) · {etiqueta.replace('Voto particular, ap. ', 'ap. ').replace('Voto particular', '').strip(' ·')}".strip(" ·")
            partes = partir_parrafos(texto)
            for i, p in enumerate(partes, 1):
                salida.append(FragmentoNuevo(etiqueta if len(partes) == 1 else f"{etiqueta} (parte {i}/{len(partes)})", p))
        if voto:
            advertencias.append("Incluye voto(s) particular(es): se etiquetan y no representan el criterio de la mayoría.")
        return salida

    def _get(self, url: str):
        try:
            return self.http.get(url, {"Accept": "application/xml"})
        except ErrorHTTP as e:
            raise ErrorConector(str(e), transitorio=e.transitorio) from e

    @staticmethod
    def _xml(contenido: bytes):
        try:
            raiz = etree.fromstring(contenido, analizador())
        except etree.XMLSyntaxError as e:
            raise ErrorConector(f"La respuesta no es XML válido: {e}", transitorio=False) from e
        if raiz.tag == "response":
            estado = raiz.find("./status/code")
            if estado is not None and (estado.text or "").strip() not in ("200", ""):
                raise ErrorConector(f"El BOE devolvió un estado {estado.text}.", transitorio=(estado.text or "").startswith("5"))
        return raiz
