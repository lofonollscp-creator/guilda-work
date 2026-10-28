"""Evidencias de la lectura de una factura con IA: de dónde sacó el modelo cada dato clave (el fragmento que cita y, si la foto lo permite, un recuadro sobre la imagen) y las comprobaciones que NO dependen del modelo.

La IA propone y la persona valida: la evidencia no prueba nada por sí sola, solo le ahorra buscar. Por eso cada cita se **contrasta con el valor que se le atribuye** (una cita que no contiene el número, la fecha
o el NIF leídos se marca como incoherente) y se hacen comprobaciones propias (dígito de control del NIF, IVA de cada línea, fecha futura). Los recuadros son aproximados: los pone el modelo y no se verifican.

Funciones puras: no tocan la base de datos (el duplicado de número lo mira `lectura_facturas`)."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

CAMPOS = {"numero": "Número de factura", "fecha": "Fecha", "emisor_nif": "NIF del emisor", "receptor_nif": "NIF del receptor", "total": "Total", "base": "Base imponible", "iva": "Cuota de IVA"}
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def _plano(texto) -> str:
    s = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", s).strip()


def _alnum(texto) -> str:
    return re.sub(r"[^a-z0-9]", "", _plano(texto))


def _centimos(token: str) -> int | None:
    """«1.210,00», «1,210.00», «121,5» o «121.00» → céntimos. None si no es un importe."""
    t = token.strip().strip(".,")
    if not re.fullmatch(r"\d[\d.,]*", t):
        return None
    if "," in t and "." in t:
        decimal = "," if t.rfind(",") > t.rfind(".") else "."
        t = t.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    else:
        for separador in (",", "."):
            if separador in t:
                partes = t.split(separador)
                t = t.replace(separador, "") if len(partes) > 2 or len(partes[-1]) == 3 else t.replace(separador, ".")
    try:
        return int((Decimal(t) * 100).to_integral_value())
    except InvalidOperation:
        return None


def _contiene_importe(texto: str, valor: str) -> bool:
    objetivo = _centimos(valor)
    if objetivo is None:
        return False
    return any(_centimos(t) == objetivo for t in re.findall(r"\d[\d.,]*\d|\d", texto or ""))


def _contiene_fecha(texto: str, valor: str) -> bool:
    try:
        f = date.fromisoformat(valor[:10])
    except ValueError:
        return False
    numeros = [int(n) for n in re.findall(r"\d+", texto or "")]
    anio = any(n == f.year or (n == f.year % 100 and n < 100) for n in numeros)
    dia = f.day in numeros
    mes = f.month in numeros or MESES[f.month - 1][:3] in _plano(texto)
    return anio and dia and mes


def coherente(campo: str, texto: str, valor: str) -> bool:
    """¿La cita contiene el valor que se le atribuye?"""
    if not valor or not texto:
        return False
    if campo in ("total", "base", "iva"):
        return _contiene_importe(texto, valor)
    if campo == "fecha":
        return _contiene_fecha(texto, valor)
    return len(_alnum(valor)) >= 1 and _alnum(valor) in _alnum(texto)


def _caja(valor) -> list[float] | None:
    """Recuadro `[x0, y0, x1, y1]` en fracciones de 0 a 1 de la imagen, o None si no es válido."""
    if not isinstance(valor, (list, tuple)) or len(valor) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in valor)
    except (TypeError, ValueError):
        return None
    if not all(0.0 <= v <= 1.0 for v in (x0, y0, x1, y1)) or x1 - x0 < 0.005 or y1 - y0 < 0.003:
        return None
    return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]


def limpiar(evidencias, valores: dict[str, str]) -> dict[str, dict]:
    """Las evidencias del modelo, validadas: `{campo: {"texto", "caja", "valor", "coherente"}}`. Se ignora lo que no sea un campo conocido o no traiga texto. `valores`: lo que finalmente se leyó de cada campo."""
    if not isinstance(evidencias, dict):
        return {}
    salida = {}
    for campo in CAMPOS:
        e = evidencias.get(campo)
        if not isinstance(e, dict):
            continue
        texto = re.sub(r"\s+", " ", str(e.get("texto") or "")).strip()[:160]
        if not texto:
            continue
        valor = valores.get(campo, "")
        salida[campo] = {"texto": texto, "caja": _caja(e.get("caja")), "valor": valor, "coherente": coherente(campo, texto, valor)}
    return salida


def avisos_de_evidencia(evidencias: dict[str, dict], criticos: tuple[str, ...]) -> list[str]:
    """Avisos para las notas de la factura: citas que no contienen su valor y, si el modelo dio alguna evidencia, los datos críticos que se quedaron sin ella. Sin ninguna evidencia no se avisa: no la trae
    todo modelo y la pantalla ya lo dice."""
    avisos = [f"La cita que da la IA para «{CAMPOS[c].lower()}» no contiene el valor leído ({e['valor']}): compruébalo en la factura." for c, e in evidencias.items() if not e["coherente"]]
    if evidencias:
        faltan = [CAMPOS[c].lower() for c in criticos if c not in evidencias]
        if faltan:
            avisos.append("Sin evidencia en la factura para: " + ", ".join(faltan) + ".")
    return avisos


def verificaciones(*, nif_contraparte: str, lineas: list[dict], fecha: str, hoy: date | None = None) -> list[str]:
    """Comprobaciones propias, sin el modelo: dígito de control del NIF, IVA de cada línea frente a su base y su porcentaje, y fecha futura. Cada texto dice qué mirar."""
    from .fiscal_modelos.validacion_apuntes import nif_espanol_valido
    hoy = hoy or date.today()
    salida = []
    if nif_contraparte and nif_espanol_valido(nif_contraparte) is False:
        salida.append(f"El dígito de control del NIF {nif_contraparte} no es válido: puede estar mal leído.")
    for i, l in enumerate(lineas, 1):
        base, pct, cuota = _centimos(l.get("base") or ""), l.get("pct_iva"), _centimos(l.get("cuota_iva") or "")
        try:
            pct = Decimal(str(pct).replace(",", ".")) if pct not in (None, "") else None
        except InvalidOperation:
            pct = None
        if base is not None and pct is not None and cuota is not None:
            esperada = int((Decimal(base) * pct / 100).to_integral_value())
            if abs(cuota - esperada) > 2:
                salida.append(f"Línea {i}: la cuota de IVA leída ({cuota / 100:.2f}) no cuadra con el {pct:g} % de la base ({esperada / 100:.2f}).")
    try:
        if fecha and date.fromisoformat(fecha[:10]) > hoy:
            salida.append("La fecha de la factura es posterior a hoy: puede estar mal leída.")
    except ValueError:
        pass
    return salida
