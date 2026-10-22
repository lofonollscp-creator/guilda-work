"""Contrato común de los conectores de fuentes jurídicas (interfaz propia de Guilda Work, no la de ningún servidor oficial).

Un conector sabe **descubrir** qué hay o qué ha cambiado, **descargar** el original y **analizarlo** (metadatos, fragmentos con localizador, relaciones). No decide si puede usarse (eso es la política
de la fuente), no habla con el modelo de IA y nunca recibe URLs de fuera: solo las que él mismo construye o recibe de la fuente y valida contra su lista de dominios."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..corpus import DocumentoNuevo, FragmentoNuevo


class ErrorConector(Exception):
    """Fallo al descubrir, descargar o analizar. `transitorio` decide entre reintento y cuarentena."""

    def __init__(self, mensaje: str, *, transitorio: bool = False):
        super().__init__(mensaje)
        self.transitorio = transitorio


class ConectorNoDisponible(ErrorConector):
    """El conector existe como contrato pero no tiene transporte (falta contrato técnico, derechos o desarrollo)."""

    def __init__(self, mensaje: str):
        super().__init__(mensaje, transitorio=False)


@dataclass(frozen=True)
class Capacidades:
    descubrir: bool = False
    metadatos: bool = False
    contenido: bool = False
    busqueda_remota: bool = False
    actualizaciones: str = "none"            # cursor | time_window | snapshot | none
    retiradas: bool = False                  # la fuente da una señal fiable de retirada


@dataclass(frozen=True)
class RefRegistro:
    fuente_id: str
    id_externo: str
    actualizado_origen: str | None = None    # revisión de origen, si existe
    localizador: str = ""                     # URL o referencia de entrega validada, no arbitraria


@dataclass
class Original:
    contenido: bytes
    tipo_mime: str
    url: str


@dataclass
class PaginaDescubrimiento:
    registros: list[RefRegistro] = field(default_factory=list)
    retiradas: list[tuple[str, str | None]] = field(default_factory=list)      # (id externo, motivo)
    siguiente_cursor: str | None = None
    agotada: bool = True
    evidencia: list[Original] = field(default_factory=list)                     # manifiestos o sumarios descargados (se conservan con su hash)
    notas: dict = field(default_factory=dict)                                   # contadores informativos (días sin edición, descartados…)


@dataclass
class Parseado:
    documento: DocumentoNuevo
    fragmentos: list[FragmentoNuevo]
    relaciones: list[dict] = field(default_factory=list)
    calidad: str = "ok"
    advertencias: list[str] = field(default_factory=list)


class Conector:
    """Base. Un conector sin `descubrir` no finge sincronizar el corpus completo."""
    id: str = ""
    nombre: str = ""
    coleccion: str = ""
    capacidades = Capacidades()
    dominios: frozenset[str] = frozenset()

    def discover(self, desde: str, hasta: str, cursor: str | None) -> PaginaDescubrimiento:
        raise ConectorNoDisponible(f"El conector «{self.id}» no sabe descubrir documentos.")

    def fetch(self, ref: RefRegistro) -> Original:
        raise ConectorNoDisponible(f"El conector «{self.id}» no puede descargar contenido.")

    def parse(self, ref: RefRegistro, original: Original) -> Parseado:
        raise ConectorNoDisponible(f"El conector «{self.id}» no sabe analizar documentos.")
