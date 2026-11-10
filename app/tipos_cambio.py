"""Facturas en otra divisa (L9): el tipo de cambio de referencia del Banco Central Europeo del día de la factura (o el último anterior, porque el BCE no publica fines de semana ni festivos) y la conversión a
euros de lo que lee la IA. Si el BCE no contesta, o no cotiza esa moneda, no se convierte nada y la factura sigue avisando de que está en otra moneda: nunca se inventa un cambio."""
from __future__ import annotations

import csv
import io
import re
import urllib.request
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{moneda}.EUR.SP00.A?startPeriod={ini}&endPeriod={fin}&format=csvdata"
TIMEOUT_SEGUNDOS = 6
VENTANA_DIAS = 10                       # cuántos días hacia atrás se miran para encontrar un día con cotización
_cache: dict[tuple[str, str], tuple[Decimal, str] | None] = {}


def _descargar(url: str) -> str:
    peticion = urllib.request.Request(url, headers={"Accept": "text/csv", "User-Agent": "guilda-work"})
    with urllib.request.urlopen(peticion, timeout=TIMEOUT_SEGUNDOS) as r:
        return r.read(200_000).decode("utf-8", "replace")


def cambio(moneda: str, fecha: str) -> tuple[Decimal, str] | None:
    """(unidades de `moneda` por 1 euro, día de esa cotización) para una fecha AAAA-MM-DD, o None si no se pudo saber."""
    moneda = str(moneda or "").upper()
    if not re.fullmatch(r"[A-Z]{3}", moneda) or moneda == "EUR":
        return None
    try:
        dia = date.fromisoformat(str(fecha)[:10])
    except ValueError:
        return None
    clave = (moneda, dia.isoformat())
    if clave in _cache:
        return _cache[clave]
    try:
        texto = _descargar(URL.format(moneda=moneda, ini=(dia - timedelta(days=VENTANA_DIAS)).isoformat(), fin=dia.isoformat()))
        filas = [(f["TIME_PERIOD"], Decimal(f["OBS_VALUE"])) for f in csv.DictReader(io.StringIO(texto)) if f.get("TIME_PERIOD") and f.get("OBS_VALUE")]
    except (OSError, ValueError, InvalidOperation, KeyError):
        return None                                                     # sin red o sin respuesta válida: no se guarda en la caché para reintentar
    filas = [(d, v) for d, v in filas if d <= dia.isoformat() and v > 0]
    res = max(filas) if filas else None
    res = (res[1], res[0]) if res else None
    _cache[clave] = res
    return res


def _decimal(valor) -> Decimal | None:
    try:
        return Decimal(str(valor).replace(",", ".")) if valor not in (None, "") else None
    except InvalidOperation:
        return None


def _a_euros(valor, tasa: Decimal) -> str | None:
    d = _decimal(valor)
    return None if d is None else f"{(d / tasa).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"


def convertir(datos: dict) -> str | None:
    """Si la factura leída está en otra moneda y el BCE da el cambio de su fecha, pasa a euros (en su sitio) las bases, cuotas, suplidos y total, y devuelve el aviso que lo cuenta. None si ya está en
    euros o no se pudo convertir (entonces no se toca nada)."""
    moneda = re.sub(r"[^A-Z]", "", str(datos.get("moneda") or "EUR").upper())[:3] or "EUR"
    if moneda == "EUR":
        return None
    c = cambio(moneda, datos.get("fecha") or "")
    if c is None:
        return None
    tasa, dia = c
    original = _decimal(datos.get("total"))
    for l in datos.get("lineas") if isinstance(datos.get("lineas"), list) else []:
        if isinstance(l, dict):
            for campo in ("base", "cuota_iva"):
                if l.get(campo) not in (None, ""):
                    l[campo] = _a_euros(l[campo], tasa)
    for campo in ("suplidos", "total"):
        if datos.get(campo) not in (None, ""):
            datos[campo] = _a_euros(datos[campo], tasa)
    datos["moneda"] = "EUR"
    detalle = f" (el total original era {original} {moneda})" if original is not None else ""
    return f"La factura estaba en {moneda}: se ha pasado a euros con el cambio del BCE del {dia} (1 EUR = {tasa.normalize():f} {moneda}){detalle}. Compruébalo, y el IVA si el proveedor es de fuera de la UE."
