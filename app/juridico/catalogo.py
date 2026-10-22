"""Catálogo de fuentes y conectores del asistente jurídico. Dar de alta una fuente no la habilita: eso exige una política con evidencia (`corpus.registrar_politica`) y una decisión humana."""
from __future__ import annotations

from . import corpus
from .conectores.base import Conector
from .conectores.boe_consolidada import BoeConsolidada
from .conectores.boe_diario import BoeDiario
from .conectores.reservados import CendojLicenciado, EurLexCellar, Hudoc, OnuJuris

CONECTORES: dict[str, type[Conector]] = {c.id: c for c in (BoeConsolidada, BoeDiario, CendojLicenciado, EurLexCellar, Hudoc, OnuJuris)}

# (id de fuente, URL de referencia, acceso). `todos`: fuente pública oficial que cualquier despacho con el módulo puede usar una vez habilitada; `explicito`: licenciada, cada despacho la activa.
CATALOGO = [
    ("boe-consolidada", "https://www.boe.es/datosabiertos/api/api.php?lang=es", "todos"),
    ("boe-diario-tc", "https://www.boe.es/datosabiertos/api/api.php?lang=es", "todos"),
    ("cendoj-licenciado", "https://www.poderjudicial.es/", "explicito"),
    ("eurlex-cellar", "https://eur-lex.europa.eu/content/help/data-reuse/webservice.html?locale=en", "todos"),
    ("hudoc", "https://www.echr.coe.int/hudoc-database", "todos"),
    ("onu-juris", "https://juris.ohchr.org/BasicSearch", "todos"),
]

# Lo que está comprobado contra el proveedor y lo que no: se enseña en «Fuentes».
VERIFICACION = {
    "boe-consolidada": "Formato inspeccionado contra el servicio real el 23-oct-2026; cliente probado con fixtures sintéticos. Condiciones: aviso legal del BOE (atribución; consolidación informativa).",
    "boe-diario-tc": "Formato del sumario y del documento XML inspeccionado contra el servicio real el 23-oct-2026; no es el fondo completo del TC, solo lo publicado en el BOE.",
    "cendoj-licenciado": "Solo el contrato de adaptador. Sin documentación técnica ni suministro autorizado: no hay cliente ni endpoint.",
    "eurlex-cellar": "Solo el contrato de adaptador. Pendiente: alta en EUR-Lex y validar WSDL y consultas CDM contra el servicio real.",
    "hudoc": "Reservado para una fase posterior; sin API pública de ingesta confirmada.",
    "onu-juris": "Reservado para una fase posterior; JURIS es un buscador y UHRI es otra colección (recomendaciones).",
}


def asegurar_catalogo(conn=None) -> None:
    for fuente_id, url, acceso in CATALOGO:
        c = CONECTORES[fuente_id]
        corpus.registrar_fuente(fuente_id, c.nombre, c.id, c.coleccion, url=url, acceso=acceso, conn=conn)


def crear_conector(fuente_id: str, **kw) -> Conector:
    clase = CONECTORES.get(fuente_id)
    if clase is None:
        raise corpus.ErrorCorpus(f"No hay conector para la fuente «{fuente_id}».")
    return clase(**kw) if kw else clase()
