"""El **apunte** fiscal: una línea de los libros registro de IVA (facturas expedidas o recibidas) tal como la necesitan el cálculo del 303 y los ficheros de la AEAT.

Todos los importes son **céntimos enteros** (con signo: una rectificativa o un abono llevan base/cuota negativas) y los porcentajes, **centésimas** (21 % = 2100): nada de coma flotante en el dinero.
Los códigos son los del formato electrónico oficial de los libros (tipo de factura F1…, clave de operación 01…, calificación S1/S2/N1/N2, exenciones E1…E6)."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

EXPEDIDAS, RECIBIDAS = "E", "R"
TIPOS_FACTURA = ("F1", "F2", "F3", "F4", "F5", "F6", "R1", "R2", "R3", "R4", "R5", "AJ", "SF", "DV", "LC")
RECTIFICATIVAS = ("R1", "R2", "R3", "R4", "R5", "AJ")


def periodo_de(fecha: date, mensual: bool = False) -> str:
    """El periodo de autoliquidación al que pertenece una fecha: «2T» (trimestral) o «05» (mensual)."""
    return f"{fecha.month:02d}" if mensual else f"{(fecha.month - 1) // 3 + 1}T"


def en_periodo(fecha: date | None, ejercicio: int, periodo: str) -> bool:
    return fecha is not None and fecha.year == ejercicio and periodo_de(fecha, periodo[-1] != "T") == periodo


@dataclass(frozen=True)
class Apunte:
    libro: str                                   # "E" expedidas · "R" recibidas
    tipo_factura: str
    fecha_expedicion: date
    numero: str = "1"
    serie: str = ""
    clave: str = "01"                            # clave de operación
    base: int = 0                                # céntimos
    tipo_iva: int = 0                            # centésimas de punto: 2100 = 21 %
    cuota: int = 0                               # céntimos (repercutida o soportada)
    total: int | None = None                     # total de la factura; por defecto base + cuota
    fecha_operacion: date | None = None
    contraparte_nombre: str = "CONTRAPARTE SL"
    contraparte_nif: str = "B87654321"
    contraparte_nif_tipo: str = ""               # "" = NIF español; "02" NIF-IVA intracomunitario, "03" pasaporte…
    contraparte_pais: str = ""
    # --- expedidas
    calificacion: str = "S1"                     # S1 sujeta no exenta · S2 sujeta con inversión del sujeto pasivo · N1/N2 no sujeta
    exenta: str = ""                             # E1…E6
    # --- recibidas
    fecha_recepcion: date | None = None          # por defecto, la de expedición
    isp: bool = False                            # inversión del sujeto pasivo
    bien_inversion: bool = False
    cuota_deducible: int | None = None           # por defecto, toda la cuota soportada
    deducible_periodo_posterior: bool = False
    periodo_deduccion: tuple[int, str] | None = None     # (ejercicio, "2T") cuando se deduce en otro periodo
    inmueble_situacion: str = ""                # situación del inmueble: 1 (resto de España) · 2 (foral) · 3 (sin referencia catastral) · 4 (extranjero) · 5 (no aplica)
    inmueble_referencia: str = ""                # referencia catastral (20 caracteres)
    # --- expedidas a comerciantes minoristas en recargo de equivalencia: el cliente (mayorista) repercute IVA y recargo
    recargo_pct: int = 0                         # tipo del recargo en centésimas: 520 = 5,2 %
    recargo_cuota: int = 0                       # céntimos

    @property
    def total_efectivo(self) -> int:
        """Total de la factura. Con inversión del sujeto pasivo o adquisición intracomunitaria (clave 09) el proveedor no repercute IVA: el total es la base y la cuota la autorrepercute el destinatario."""
        if self.total is not None:
            return self.total
        if self.calificacion == "S2" or self.isp or (self.libro == RECIBIDAS and self.clave == "09"):
            return self.base
        return self.base + self.cuota + self.recargo_cuota

    @property
    def deducible(self) -> int:
        return self.cuota if self.cuota_deducible is None else self.cuota_deducible

    def con(self, **cambios) -> "Apunte":
        return replace(self, **cambios)
