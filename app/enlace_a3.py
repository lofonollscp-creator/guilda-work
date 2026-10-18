"""Fichero de enlace contable de entrada de a3asesor Eco / Con (SUENLACE.DAT): facturas emitidas y recibidas para que a3 las lea al importar (Utilidades › Importar/Exportar › Enlace contable).

Sigue el documento oficial de Wolters Kluwer «Enlace de entrada en a3asesor Eco y a3asesor Con para el SII» (descripción de registros 9.80): fichero ASCII secuencial de registros de **512 bytes** (510
caracteres más CR LF). Por factura va un registro de cabecera (tipo 1; tipo 2 si es un abono o rectificativa), uno de detalle de IVA (tipo 9) por cada tipo impositivo y, en las rectificativas, un registro
de ampliación (tipo 4) con la factura que se rectifica. Los registros dan de alta las cuentas que no existan en el plan. Las posiciones están fijadas campo a campo en `tests/test_enlace_a3.py` con la
numeración del documento (1 a 512). Este módulo no toca la base de datos: recibe datos ya validados."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

LONGITUD = 510                      # sin el salto de línea (los 2 últimos de los 512 bytes)
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


_NIF_ES = re.compile(r"^(\d{8}[A-Z]|[XYZ]\d{7}[A-Z]|[A-HJNPQRSUVW]\d{7}[0-9A-J])$")


def _rellenar(r: str) -> str:
    """Completa con espacios hasta la posición 508 y cierra el registro: moneda euros, indicador de generado y salto de línea."""
    assert len(r) <= 508, f"registro de {len(r)} caracteres antes del cierre"
    return r.ljust(508) + "E" + "N"


def numero_corto(numero) -> str:
    """El número que va en las 10 posiciones del registro: el propio si cabe; si no, sus 10 últimos caracteres (el número completo va en el campo ampliado para el SII, de 60)."""
    t = "" if numero is None else str(numero).strip()
    return t[-10:] if len(t) > 10 else t


def registro_cabecera(*, empresa, fecha, abono: bool, cuenta_tercero, digitos: int, tipo_factura: str, numero, concepto, total_centimos: int, nif, nombre, codigo_postal=None,
                      fecha_operacion=None, fecha_factura=None) -> str:
    """Registro de cabecera de factura (tipo 1; tipo 2 si `abono`). Posiciones del documento de a3 entre paréntesis."""
    nif_n = re.sub(r"[\s.\-]", "", str(nif or "")).upper()
    es_es = bool(_NIF_ES.match(nif_n))
    largo = "" if numero is None else str(numero).strip()
    r = ("5" + _empresa(empresa) + _fecha(fecha) + ("2" if abono else "1")                                      # 1, 2-6, 7-14, 15
         + _cuenta(cuenta_tercero, digitos) + _texto(nombre, 30) + str(tipo_factura)[:1] + _texto(numero_corto(numero), 10)   # 16-27, 28-57, 58, 59-68
         + "I" + _texto(concepto, 30) + _importe(abs(int(total_centimos))) + " " * 62                           # 69, 70-99, 100-113, 114-175 (reserva)
         + _texto(nif_n, 14) + (_texto(nombre, 40) + _texto(codigo_postal, 5) if nif_n else " " * 45) + "  "      # 176-189, 190-229, 230-234, 235-236
         + _fecha(fecha_operacion or fecha) + _fecha(fecha_factura or fecha)                                    # 237-244, 245-252
         + (_texto(largo, 60) if len(largo) > 10 else " " * 60) + " " * 61                                       # 253-312 (número ampliado SII), 313-373
         + ("ES" if nif_n and es_es else "  ") + ("02" if nif_n and es_es else "  "))                           # 374-375 país, 376-377 tipo de documento
    return _rellenar(r)


def registro_detalle(*, empresa, fecha, abono: bool, cuenta_contrapartida, digitos: int, numero, concepto, ultimo: bool, subtipo, base_centimos: int, pct_iva: int, cuota_iva: int,
                     pct_recargo: int = 0, cuota_recargo: int = 0, pct_retencion: int = 0, cuota_retencion: int = 0, sujeta_iva: bool = True, impreso=None, descripcion_cuenta=None,
                     cuenta_iva_soportado=None, cuenta_recargo_soportado=None, cuenta_retencion=None, cuenta_iva_repercutido=None, cuenta_recargo_repercutido=None) -> str:
    """Registro de detalle de IVA (tipo 9): una línea por tipo impositivo. `C` = cargo y `A` = abono en factura; los importes van en positivo (un abono que disminuye la factura original se informa
    en positivo, como dice el documento)."""
    r = ("5" + _empresa(empresa) + _fecha(fecha) + "9" + _cuenta(cuenta_contrapartida, digitos) + _texto(descripcion_cuenta, 30) + ("A" if abono else "C")   # 1..58
         + _texto(numero_corto(numero), 10) + ("U" if ultimo else "M") + _texto(concepto, 30) + _dos(subtipo, "01")                                          # 59-68, 69, 70-99, 100-101
         + _importe(abs(base_centimos)) + _porcentaje(pct_iva) + _importe(abs(cuota_iva)) + _porcentaje(pct_recargo) + _importe(abs(cuota_recargo))          # 102-153
         + _porcentaje(pct_retencion) + _importe(abs(cuota_retencion)) + _dos(impreso) + ("S" if sujeta_iva else "N")                                       # 154-175
         + " " * 3 + " " * 13                                                                                                                              # 176-178 (415, caja, IVA 0 %), 179-191 reserva
         + _cuenta_o_blancos(cuenta_iva_soportado, digitos) + _cuenta_o_blancos(cuenta_recargo_soportado, digitos) + _cuenta_o_blancos(cuenta_retencion, digitos)  # 192-227
         + _cuenta_o_blancos(cuenta_iva_repercutido, digitos) + _cuenta_o_blancos(cuenta_recargo_repercutido, digitos))                                       # 228-251
    return _rellenar(r)


def registro_ampliacion_rectificativa(*, empresa, fecha, fecha_rectificada, numero_rectificado, tipo_factura: str) -> str:
    """Registro tipo 4 de una rectificativa (obligatorio): fecha y número de la factura que se rectifica. Va después del último registro de detalle de la factura. `tipo_factura`: 1 emitida,
    2 recibida (se informa como E o R en el campo «tipo de factura»); «R» = resto de rectificativas."""
    r = ("5" + _empresa(empresa) + _fecha(fecha) + "4" + " " * 43 + _fecha(fecha_rectificada) + _texto(numero_rectificado, 60)       # 1-58, 59-66, 67-126
         + " " * 30 + " " * 0)                                                                                                         # 127-156 (DUA, cuenta de proveedor)
    r = r.ljust(156) + "R" + " " * 146                                                                                                   # 157 tipo de factura (R = resto de rectificativas), 158-303
    r = r + ("E" if str(tipo_factura) == EMITIDA else "R")                                                                              # 304 tipo de factura E/R
    r = r.ljust(509) + "N"
    assert len(r) == 510, f"ampliación de {len(r)} caracteres"
    return r


def generar(facturas: list[dict], *, empresa, digitos: int = 8) -> bytes:
    """El contenido de SUENLACE.DAT. Cada factura es un dict ya validado:
    `{tipo: 'emitida'|'recibida', abono, rectifica_fecha, rectifica_numero, fecha, fecha_operacion, numero, concepto, nif, nombre, cuenta_tercero, total_centimos, lineas: [{cuenta,
    descripcion_cuenta, subtipo, base_centimos, pct_iva, cuota_iva, pct_recargo, cuota_recargo, pct_retencion, cuota_retencion, sujeta_iva, impreso, cuenta_iva, cuenta_retencion}]}`.
    Devuelve los bytes en Latin-1, con CR LF al final de cada registro."""
    lineas = []
    for f in facturas:
        abono = bool(f.get("abono"))
        tipo = RECIBIDA if f.get("tipo") == "recibida" else EMITIDA
        lineas.append(registro_cabecera(empresa=empresa, fecha=f["fecha"], abono=abono, cuenta_tercero=f["cuenta_tercero"], digitos=digitos, tipo_factura=tipo, numero=f["numero"],
                                        concepto=f.get("concepto"), total_centimos=int(f["total_centimos"]), nif=f.get("nif"), nombre=f.get("nombre"),
                                        fecha_operacion=f.get("fecha_operacion"), fecha_factura=f["fecha"]))
        det = f["lineas"]
        for i, l in enumerate(det):
            repercutido = tipo == EMITIDA
            lineas.append(registro_detalle(empresa=empresa, fecha=f["fecha"], abono=abono, cuenta_contrapartida=l["cuenta"], digitos=digitos, numero=f["numero"], concepto=f.get("concepto"),
                                           ultimo=(i == len(det) - 1), subtipo=l.get("subtipo", "01"), base_centimos=l["base_centimos"], pct_iva=l.get("pct_iva", 0), cuota_iva=l.get("cuota_iva", 0),
                                           pct_recargo=l.get("pct_recargo", 0), cuota_recargo=l.get("cuota_recargo", 0), pct_retencion=l.get("pct_retencion", 0),
                                           cuota_retencion=l.get("cuota_retencion", 0), sujeta_iva=l.get("sujeta_iva", True), impreso=l.get("impreso"), descripcion_cuenta=l.get("descripcion_cuenta"),
                                           cuenta_iva_soportado=None if repercutido else l.get("cuenta_iva"), cuenta_iva_repercutido=l.get("cuenta_iva") if repercutido else None,
                                           cuenta_retencion=l.get("cuenta_retencion")))
        if abono:
            lineas.append(registro_ampliacion_rectificativa(empresa=empresa, fecha=f["fecha"], fecha_rectificada=f.get("rectifica_fecha"), numero_rectificado=f.get("rectifica_numero"), tipo_factura=tipo))
    return "".join(l + FIN_DE_LINEA for l in lineas).encode("latin-1")


def cuota(base_centimos: int, pct_centesimas: int) -> int:
    """Cuota de un tipo sobre una base, en céntimos, redondeando al céntimo (mitad hacia arriba)."""
    return int((Decimal(base_centimos) * Decimal(pct_centesimas) / Decimal(10000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
