"""¿Es una factura? (L17): antes de gastar una consulta de IA en un documento, se mira su texto (el del PDF, que es gratis) por si es otra cosa que ha llegado con las facturas: un extracto del banco, una nómina,
un contrato o un justificante de Hacienda. Es conservador a propósito: con cualquier rastro de factura (la palabra, una base imponible, una cuota de IVA) se lee como factura de siempre, y solo se aparta un
documento cuando varias señales de otro tipo coinciden y ninguna de factura aparece. Sin texto (una foto) no se decide nada."""
from __future__ import annotations

from . import lectura_evidencias

SENALES_DE_FACTURA = ("factura", "invoice", "base imponible", "cuota iva", "tipo de iva", "total factura", "factura simplificada", "albaran")
TIPOS = {
    "extracto": ("un extracto del banco", ("extracto", "saldo anterior", "saldo final", "saldo actual", "movimientos", "fecha valor", "cuaderno 43", "cargos", "abonos")),
    "nomina": ("una nómina", ("recibo de salarios", "nomina", "liquido a percibir", "devengos", "deducciones", "cotizacion a la seguridad social", "base de cotizacion")),
    "contrato": ("un contrato", ("contrato de", "las partes", "clausula", "estipulaciones", "reunidos", "en lo sucesivo", "ambas partes")),
    "hacienda": ("un justificante de Hacienda", ("agencia tributaria", "justificante de presentacion", "codigo seguro de verificacion", "modelo 303", "modelo 111", "modelo 130", "numero de justificante")),
}
MINIMO_DE_SENALES = 3                      # cuántas señales del mismo tipo hacen falta para apartar un documento


def tipo_de_documento(texto: str | None) -> tuple[str, str] | None:
    """(clave, cómo se llama) si el texto es claramente otra cosa que una factura; None si parece una factura, si no hay texto o si no está claro."""
    plano = lectura_evidencias._plano(texto or "")
    if len(plano) < 150 or any(s in plano for s in SENALES_DE_FACTURA):
        return None
    puntos = {clave: sum(1 for s in senales if s in plano) for clave, (_nombre, senales) in TIPOS.items()}
    mejor = max(puntos, key=puntos.get)
    empatados = [c for c, n in puntos.items() if n == puntos[mejor]]
    if puntos[mejor] < MINIMO_DE_SENALES or len(empatados) > 1:
        return None
    return mejor, TIPOS[mejor][0]
