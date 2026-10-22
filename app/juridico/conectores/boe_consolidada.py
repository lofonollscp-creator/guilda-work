"""Conector «BOE · legislación consolidada»: normas con sus bloques (artículos) y las versiones de cada bloque.

API oficial documentada (https://www.boe.es/datosabiertos/api/api.php?lang=es) y **comprobada contra el servicio real el 23-oct-2026**:
- `GET /datosabiertos/api/legislacion-consolidada?from=AAAAMMDD&to=AAAAMMDD&offset=N&limit=N` -> `<response><data><item>` con `identificador`, `fecha_actualizacion` (AAAAMMDDThhmmssZ), `titulo`, rango…
  El filtro `from/to` es por **fecha de actualización**, no por fecha de la norma.
- `GET /datosabiertos/api/legislacion-consolidada/id/{ID}` -> `<data>` con `<metadatos>`, `<analisis>` (materias, notas, referencias anteriores/posteriores), `<metadata-eli>` y `<texto>`: una lista de
  `<bloque id tipo titulo>` y, dentro de cada bloque, una o varias `<version id_norma fecha_publicacion fecha_vigencia>` con `<p class=…>` (y `<blockquote>` anidados).

Vigencia de cada fragmento: `vigente_desde` es la `fecha_vigencia` de la versión; `vigente_hasta` solo se rellena si existe una versión posterior del MISMO bloque (el día anterior a la entrada en vigor
de la siguiente). Sin versión posterior queda `NULL` («vigente según la fuente hasta nueva versión»). Si una versión no trae `fecha_vigencia`, su vigencia es desconocida (`NULL`) y se explica.
La consolidación del BOE es **informativa**: la referencia oficial es la publicación original (se conserva `id_norma` de cada versión)."""
from __future__ import annotations

from datetime import date, timedelta

from lxml import etree

from ..corpus import DocumentoNuevo, FragmentoNuevo, fecha_iso, partir_parrafos
from ..http import ClienteHTTP, ErrorHTTP
from .base import Capacidades, Conector, ErrorConector, Original, PaginaDescubrimiento, Parseado, RefRegistro

BASE = "https://www.boe.es/datosabiertos/api/legislacion-consolidada"
TAMANO_PAGINA = 100
TIPOS_DE_BLOQUE_CON_TEXTO = {"precepto", "preambulo", "anexo", "firma", "nota_inicial", "nota_final", "disposicion", "parte_final", "otro", "indice"}
_VERBOS = {"DEROGA": "deroga", "MODIFICA": "modifica", "AÑADE": "anade", "SUPRIME": "suprime", "CORRIGE": "corrige", "DESARROLLA": "desarrolla", "DE CONFORMIDAD con": "de_conformidad_con",
           "CITA": "cita", "SE DICTA DE CONFORMIDAD": "de_conformidad_con", "PRORROGA": "prorroga", "SUSPENDE": "suspende", "ANULA": "anula"}


def analizador() -> etree.XMLParser:
    """XML de una fuente externa: sin entidades externas, sin red, sin árboles gigantes."""
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, load_dtd=False, dtd_validation=False)


def _texto(el, ruta: str) -> str | None:
    n = el.find(ruta)
    t = (n.text or "").strip() if n is not None else ""
    return t or None


def _parrafos(nodo) -> list[str]:
    """Texto de un bloque/versión: un párrafo por línea, incluidos los de `<blockquote>` anidados, en orden de documento."""
    salida = []
    for p in nodo.iter("p"):
        t = " ".join("".join(p.itertext()).split())
        if t:
            salida.append(t)
    return salida


def estado_normativo(meta) -> str:
    if _texto(meta, "estatus_anulacion") == "S" or _texto(meta, "judicialmente_anulada") == "S":
        return "anulada"
    if _texto(meta, "estatus_derogacion") == "S":
        return "derogada"
    if _texto(meta, "vigencia_agotada") == "S":
        return "vigencia_agotada"
    return "vigente"


class BoeConsolidada(Conector):
    id = "boe-consolidada"
    nombre = "BOE · legislación consolidada"
    coleccion = "legislacion"
    capacidades = Capacidades(descubrir=True, metadatos=True, contenido=True, actualizaciones="cursor", retiradas=False)
    dominios = frozenset({"www.boe.es"})

    def __init__(self, cliente: ClienteHTTP | None = None, tamano_pagina: int = TAMANO_PAGINA):
        self.http = cliente or ClienteHTTP(self.dominios)
        self.tamano_pagina = tamano_pagina

    # -- descubrir ----------------------------------------------------------------------------------------------------------------------------------------
    def discover(self, desde: str, hasta: str, cursor: str | None) -> PaginaDescubrimiento:
        offset = int(cursor or 0)
        url = f"{BASE}?from={desde.replace('-', '')}&to={hasta.replace('-', '')}&offset={offset}&limit={self.tamano_pagina}"
        r = self._get(url)
        if r.estado == 404:                                  # sin resultados en la ventana: no es un error
            return PaginaDescubrimiento(agotada=True)
        raiz = self._xml(r.cuerpo)
        items = raiz.findall("./data/item")
        refs = []
        for it in items:
            ident = _texto(it, "identificador")
            if not ident:
                continue
            refs.append(RefRegistro("boe-consolidada", ident, _texto(it, "fecha_actualizacion"), f"{BASE}/id/{ident}"))
        agotada = len(items) < self.tamano_pagina
        return PaginaDescubrimiento(registros=refs, siguiente_cursor=None if agotada else str(offset + len(items)), agotada=agotada,
                                    evidencia=[Original(r.cuerpo, "application/xml", url)])

    # -- descargar ----------------------------------------------------------------------------------------------------------------------------------------
    def fetch(self, ref: RefRegistro) -> Original:
        r = self._get(ref.localizador)
        if r.estado == 404:
            raise ErrorConector("La norma no existe en el BOE (404): puede estar retirada; se deja en cuarentena para revisarla.", transitorio=False)
        if r.estado != 200:
            raise ErrorConector(f"El BOE respondió {r.estado}.", transitorio=r.estado >= 500)
        raiz = self._xml(r.cuerpo)
        if raiz.find("./data/texto") is None or raiz.find("./data/metadatos") is None:
            raise ErrorConector("La respuesta no es una norma consolidada (falta `metadatos` o `texto`).", transitorio=False)
        return Original(r.cuerpo, "application/xml", ref.localizador)

    # -- analizar -----------------------------------------------------------------------------------------------------------------------------------------
    def parse(self, ref: RefRegistro, original: Original) -> Parseado:
        raiz = self._xml(original.contenido)
        meta = raiz.find("./data/metadatos")
        if meta is None:
            raise ErrorConector("Falta `metadatos`.")
        ident = _texto(meta, "identificador") or ref.id_externo
        if ident != ref.id_externo:
            raise ErrorConector(f"El identificador del documento ({ident}) no coincide con el solicitado ({ref.id_externo}).")
        titulo = _texto(meta, "titulo")
        if not titulo:
            raise ErrorConector("La norma no trae título.")
        ambito = meta.find("ambito")
        departamento = _texto(meta, "departamento")
        territorio = "ES" if (ambito is not None and ambito.get("codigo") == "1") else (departamento if ambito is not None and ambito.get("codigo") == "2" else None)
        materias = [(m.text or "").strip() for m in raiz.findall("./data/analisis/materias/materia") if (m.text or "").strip()]
        doc = DocumentoNuevo(
            fuente_id=self.id, id_externo=ident, coleccion="legislacion", titulo=titulo, materia="; ".join(materias[:6]) or None, emisor=departamento, territorio=territorio,
            rango=_texto(meta, "rango"), tipo="norma", url_canonica=_texto(meta, "url_html_consolidada") or _texto(meta, "url_eli"), eli=_texto(meta, "url_eli"),
            estado_normativo=estado_normativo(meta), fecha_publicacion=fecha_iso(_texto(meta, "fecha_publicacion")), fecha_resolucion=fecha_iso(_texto(meta, "fecha_disposicion")))
        advertencias: list[str] = []
        fragmentos = self._fragmentos(raiz, advertencias)
        if not fragmentos:
            raise ErrorConector("La norma no trae texto utilizable.")
        return Parseado(doc, fragmentos, self._relaciones(raiz), advertencias=advertencias)

    def _fragmentos(self, raiz, advertencias: list[str]) -> list[FragmentoNuevo]:
        salida: list[FragmentoNuevo] = []
        sin_vigencia = 0
        for bloque in raiz.findall("./data/texto/bloque"):
            tipo = bloque.get("tipo") or "otro"
            if tipo == "encabezado":                          # «CAPÍTULO II»: contexto, no un texto citable por sí mismo
                continue
            versiones = bloque.findall("version")
            if not versiones:
                continue
            etiqueta = (bloque.get("titulo") or bloque.get("id") or "Bloque").strip()
            if etiqueta.startswith("[") and etiqueta.endswith("]"):
                etiqueta = etiqueta.strip("[]").capitalize()
            desdes = [fecha_iso(v.get("fecha_vigencia")) for v in versiones]
            for i, v in enumerate(versiones):
                texto = "\n".join(_parrafos(v))
                if not texto.strip():
                    continue
                desde = desdes[i]
                hasta, origen = None, ("version_propia" if desde else None)
                if desde is None:
                    sin_vigencia += 1
                elif i + 1 < len(versiones) and desdes[i + 1]:
                    siguiente = date.fromisoformat(desdes[i + 1])
                    hasta, origen = (siguiente - timedelta(days=1)).isoformat(), "siguiente_version"
                    if hasta < desde:                         # datos incoherentes: no se inventa un intervalo
                        hasta, origen = None, None
                        advertencias.append(f"{etiqueta}: fechas de vigencia incoherentes.")
                partes = partir_parrafos(texto)
                for n, parte in enumerate(partes, 1):
                    loc = etiqueta if len(partes) == 1 else f"{etiqueta} (parte {n}/{len(partes)})"
                    salida.append(FragmentoNuevo(loc, parte, bloque.get("id"), desde, hasta, origen))
        if sin_vigencia:
            advertencias.append(f"{sin_vigencia} versión(es) de bloque sin fecha de vigencia: su aplicabilidad temporal es desconocida.")
        return salida

    def _relaciones(self, raiz) -> list[dict]:
        rel = []
        for direccion, ruta in (("anterior", "./data/analisis/referencias/anteriores/anterior"), ("posterior", "./data/analisis/referencias/posteriores/posterior")):
            for n in raiz.findall(ruta):
                destino, verbo = _texto(n, "id_norma"), (_texto(n, "relacion") or "").strip()
                if not destino or not verbo:
                    continue
                base = _VERBOS.get(verbo, _VERBOS.get(verbo.upper(), "afecta"))
                rel.append({"destino_externo": destino, "tipo": base if direccion == "anterior" else f"{base}_por", "evidencia": _texto(n, "texto")})
        return rel

    # -- utilidades ---------------------------------------------------------------------------------------------------------------------------------------
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
        estado = raiz.find("./status/code")
        if estado is not None and (estado.text or "").strip() not in ("200", ""):
            raise ErrorConector(f"El BOE devolvió un estado {estado.text}: {_texto(raiz, './status/text') or ''}", transitorio=(estado.text or "").startswith("5"))
        return raiz
