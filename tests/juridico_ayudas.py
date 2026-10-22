"""Ayudas de las pruebas del asistente jurídico: transporte HTTP falso con las fixtures SINTÉTICAS y alta rápida de fuentes con política."""
from pathlib import Path

from app import db
from app.juridico import catalogo, corpus
from app.juridico.conectores.boe_consolidada import BoeConsolidada
from app.juridico.conectores.boe_diario import BoeDiario
from app.juridico.http import ClienteHTTP

FIXTURES = Path(__file__).parent / "fixtures_juridico"
BASE_C = "https://www.boe.es/datosabiertos/api/legislacion-consolidada"


def fx(nombre: str) -> bytes:
    return (FIXTURES / nombre).read_bytes()


class TransporteFalso:
    """URL -> (estado, cuerpo). Cuenta las llamadas y permite programar fallos (lista de estados antes del bueno)."""

    def __init__(self, respuestas: dict | None = None):
        self.respuestas = dict(respuestas or {})
        self.llamadas: list[str] = []
        self.fallos: dict[str, list] = {}

    def __call__(self, url, cabeceras, timeout):
        self.llamadas.append(url)
        cola = self.fallos.get(url)
        if cola:
            accion = cola.pop(0)
            if isinstance(accion, Exception):
                raise accion
            return accion, {"Retry-After": "0"}, b""
        for prefijo, (estado, cuerpo) in self.respuestas.items():
            if url == prefijo or (prefijo.endswith("*") and url.startswith(prefijo[:-1])):
                return estado, {"Content-Type": "application/xml"}, cuerpo
        return 404, {}, b""


def cliente(transporte: TransporteFalso) -> ClienteHTTP:
    return ClienteHTTP({"www.boe.es"}, transporte=transporte, dormir=lambda s: None, espera_base=0.0)


def transporte_boe() -> TransporteFalso:
    return TransporteFalso({
        f"{BASE_C}?from=20990101&to=20990131&offset=0&limit=100": (200, fx("boe_consolidada_lista.xml")),
        f"{BASE_C}/id/BOE-A-2099-0001": (200, fx("boe_norma_sintetica_1.xml")),
        f"{BASE_C}/id/BOE-A-2099-0002": (200, fx("boe_norma_sintetica_2.xml")),
        "https://www.boe.es/datosabiertos/api/boe/sumario/20990110": (200, fx("boe_sumario_tc.xml")),
        "https://www.boe.es/diario_boe/xml.php?id=BOE-A-2099-9101": (200, fx("boe_doc_tc_sentencia.xml")),
        "https://www.boe.es/diario_boe/xml.php?id=BOE-A-2099-9102": (200, fx("boe_doc_tc_auto.xml")),
    })


def conector_consolidada(t: TransporteFalso | None = None, **kw) -> BoeConsolidada:
    return BoeConsolidada(cliente(t or transporte_boe()), **kw)


def conector_diario(t: TransporteFalso | None = None) -> BoeDiario:
    return BoeDiario(cliente(t or transporte_boe()))


def habilitar(fuente_id: str, *, almacenar=True, indexar=True, llm=True, citar=True) -> None:
    """Asegura el catálogo, registra una política de PRUEBA con evidencia y habilita la fuente (solo en tests)."""
    catalogo.asegurar_catalogo()
    corpus.registrar_politica(fuente_id, evidencia="Política de prueba: fixtures sintéticas, solo en tests.", almacenar=almacenar, indexar=indexar, enviar_llm=llm, citar=citar, atribucion="Fuente de prueba")
    if almacenar and indexar:
        corpus.habilitar_fuente(fuente_id, True)


def despacho(nombre: str = "Despacho jurídico") -> int:
    return db.crear_tenant(nombre)
