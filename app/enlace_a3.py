"""Fichero de enlace contable de a3 (SUENLACE.DAT): facturas emitidas y recibidas para que a3ECO / a3CON las lea al importar (Utilidades › Importar/Exportar › Enlace contable).

Es un texto de registros de ancho fijo: cada línea mide 254 caracteres más el salto de línea (256 bytes), en Latin-1. Por factura va un registro de cabecera (tipo 1; tipo 2 si es un abono o rectificativa)
y uno de detalle de IVA (tipo 9) por cada tipo impositivo; el último de cada factura lleva la marca «U» y los anteriores «M». Las posiciones de abajo siguen la implementación abierta de referencia
(Gest2A3Eco) y deben contrastarse con el manual «Enlace contable entrada» de Wolters Kluwer: ver `LONGITUD` y los tests, que fijan cada campo para poder ajustarlo en un único sitio si el manual
dice otra cosa. Este módulo no toca la base de datos: recibe datos ya validados."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

LONGITUD = 254                      # sin el salto de línea
FIN_DE_LINEA = "\r\n"
NOMBRE_FICHERO = "SUENLACE.DAT"
EMITIDA, RECIBIDA = "1", "2"        # «tipo de factura» del registro de cabecera

_SUSTITUCIONES = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "€": "EUR", "…": "...", " ": " "}


def _texto(valor, ancho: int) -> str:
    """Texto de `ancho` caracteres: una sola línea, recortado y rellenado con espacios por la derecha, y siempre representable en Latin-1."""
    t = "" if valor is None else str(valor).replace("\r", " ").replace("\n", " ").strip()
    for a, b in _SUSTITUCIONES.items():
        t = t.replace(a, b)
    t = unicodedata.normalize("NFC", t)
    t = t.encode("latin-1", "replace").decode("latin-1")
    return t[:ancho].ljust(ancho)


def _empresa(valor) -> str:
    d = re.sub(r"\D", "", str(valor or ""))
    return d.zfill(5)[-5:] if d else "00000"


def _fecha(valor) -> str:
    """AAAAMMDD. Acepta `date`, `datetime` o texto ISO; vacío → 00000000."""
    if not valor:
        return "00000000"
    if isinstance(valor, (date, datetime)):
        return valor.strftime("%Y%m%d")
    try:
        return datetime.fromisoformat(str(valor)[:10]).strftime("%Y%m%d")
    except ValueError:
        return "00000000"


def _cuenta(valor, digitos: int) -> str:
    """Subcuenta de 12 posiciones: solo dígitos, ajustada a los dígitos del plan (se recorta o se completa con ceros por la derecha) y completada con ceros hasta 12."""
    d = re.sub(r"\D", "", str(valor or ""))
    if not d:
        return " " * 12
    d = d[:digitos].ljust(digitos, "0")
    return d.ljust(12, "0")


def _cuenta_o_blancos(valor, digitos: int) -> str:
    return _cuenta(valor, digitos) if re.sub(r"\D", "", str(valor or "")) else " " * 12


def _importe(centimos: int, con_signo: bool = False) -> str:
    """14 posiciones: signo, 10 enteros, punto y 2 decimales (+0000001234.56). Sin `con_signo`, siempre positivo."""
    c = int(centimos or 0)
    signo = "-" if (c < 0 and con_signo) else "+"
    c = abs(c)
    return f"{signo}{c // 100:010d}.{c % 100:02d}"


def _porcentaje(centesimas: int) -> str:
    """5 posiciones: 21.00. `centesimas` en centésimas de punto (2100 = 21 %)."""
    c = abs(int(centesimas or 0))
    return f"{c // 100:02d}.{c % 100:02d}"


def _dos(valor, vacio: str = "  ") -> str:
    d = re.sub(r"\D", "", str(valor or ""))
    return d.zfill(2)[-2:] if d else vacio


def registro_cabecera(*, empresa, fecha, abono: bool, cuenta_tercero, digitos: int, tipo_factura: str, numero, concepto, total_centimos: int, referencia, nif, nombre,
                      fecha_operacion=None, fecha_factura=None) -> str:
    """Registro de cabecera de factura (tipo 1; tipo 2 si `abono`)."""
    r = ("4" + _empresa(empresa) + _fecha(fecha) + ("2" if abono else "1") + _cuenta(cuenta_tercero, digitos) + _texto(nombre, 30) + str(tipo_factura)[:1] + _texto(numero, 10) + "I"
         + _texto(concepto, 30) + _importe(total_centimos) + _texto(referencia, 30) + " " * 32 + _texto(nif, 14) + _texto(nombre, 40) + " " * 5 + "  "
         + _fecha(fecha_operacion) + _fecha(fecha_factura or fecha) + "E" + "N")
    assert len(r) == LONGITUD, f"cabecera de {len(r)} caracteres"
    return r


def registro_detalle(*, empresa, fecha, abono: bool, cuenta_contrapartida, digitos: int, numero, concepto, ultimo: bool, subtipo, base_centimos: int, pct_iva: int, cuota_iva: int,
                     pct_recargo: int = 0, cuota_recargo: int = 0, pct_retencion: int = 0, cuota_retencion: int = 0, sujeta_iva: bool = True, impreso=None,
                     cuenta_iva=None, cuenta_recargo=None, cuenta_retencion=None) -> str:
    """Registro de detalle de IVA (tipo 9): una línea por tipo impositivo. En un abono importes y cuotas van con signo negativo; la retención siempre va en positivo."""
    signo = -1 if abono else 1
    r = ("4" + _empresa(empresa) + _fecha(fecha) + "9" + _cuenta(cuenta_contrapartida, digitos) + " " * 30 + ("A" if abono else "C") + _texto(numero, 10) + ("U" if ultimo else "M")
         + _texto(concepto, 30) + _dos(subtipo, "01") + _importe(signo * abs(base_centimos), True) + _porcentaje(pct_iva) + _importe(signo * abs(cuota_iva), True)
         + _porcentaje(pct_recargo) + _importe(signo * abs(cuota_recargo), True) + _porcentaje(pct_retencion) + _importe(abs(cuota_retencion)) + _dos(subtipo, "01")
         + ("S" if sujeta_iva else "N") + _dos(impreso) + " " * 14 + _cuenta_o_blancos(cuenta_iva, digitos) + _cuenta_o_blancos(cuenta_recargo, digitos)
         + _cuenta_o_blancos(cuenta_retencion, digitos) + " " * 12 + " " * 12 + " " + "E" + "N")
    assert len(r) == LONGITUD, f"detalle de {len(r)} caracteres"
    return r


def generar(facturas: list[dict], *, empresa, digitos: int = 8) -> bytes:
    """El contenido de SUENLACE.DAT. Cada factura es un dict ya validado:
    `{tipo: 'emitida'|'recibida', fecha, fecha_operacion, numero, concepto, referencia, nif, nombre, cuenta_tercero, total_centimos, lineas: [{cuenta, subtipo, base_centimos, pct_iva, cuota_iva,
    pct_recargo, cuota_recargo, pct_retencion, cuota_retencion, sujeta_iva, impreso, cuenta_iva, cuenta_recargo, cuenta_retencion}]}`.
    Un total negativo (o `abono`) genera el registro de abono. Devuelve los bytes en Latin-1, con salto de línea CRLF en cada registro."""
    lineas = []
    for f in facturas:
        abono = bool(f.get("abono")) or int(f.get("total_centimos") or 0) < 0
        tipo = RECIBIDA if f.get("tipo") == "recibida" else EMITIDA
        lineas.append(registro_cabecera(empresa=empresa, fecha=f["fecha"], abono=abono, cuenta_tercero=f["cuenta_tercero"], digitos=digitos, tipo_factura=tipo, numero=f["numero"],
                                        concepto=f.get("concepto"), total_centimos=abs(int(f["total_centimos"])), referencia=f.get("referencia"), nif=f.get("nif"), nombre=f.get("nombre"),
                                        fecha_operacion=f.get("fecha_operacion"), fecha_factura=f["fecha"]))
        det = f["lineas"]
        for i, l in enumerate(det):
            lineas.append(registro_detalle(empresa=empresa, fecha=f["fecha"], abono=abono, cuenta_contrapartida=l["cuenta"], digitos=digitos, numero=f["numero"], concepto=f.get("concepto"),
                                           ultimo=(i == len(det) - 1), subtipo=l.get("subtipo", "01"), base_centimos=l["base_centimos"], pct_iva=l.get("pct_iva", 0), cuota_iva=l.get("cuota_iva", 0),
                                           pct_recargo=l.get("pct_recargo", 0), cuota_recargo=l.get("cuota_recargo", 0), pct_retencion=l.get("pct_retencion", 0),
                                           cuota_retencion=l.get("cuota_retencion", 0), sujeta_iva=l.get("sujeta_iva", True), impreso=l.get("impreso"), cuenta_iva=l.get("cuenta_iva"),
                                           cuenta_recargo=l.get("cuenta_recargo"), cuenta_retencion=l.get("cuenta_retencion")))
    return "".join(l + FIN_DE_LINEA for l in lineas).encode("latin-1")


def cuota(base_centimos: int, pct_centesimas: int) -> int:
    """Cuota de un tipo sobre una base, en céntimos, redondeando al céntimo (mitad hacia arriba)."""
    return int((Decimal(base_centimos) * Decimal(pct_centesimas) / Decimal(10000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
