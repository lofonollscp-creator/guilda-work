"""NIF que la IA no devuelve aunque están en el documento (AC2).

Con el texto del PDF a mano, un NIF suelto bajo el nombre («JORGE… / 39400648S») o un NIF-IVA europeo en la cabecera («EU VAT IE4276970QH») se le escapan a los modelos pequeños. Aquí se buscan en el texto
SOLO los que superan el dígito de control (NIF/CIF/NIE españoles) o tienen el formato de su país (NIF-IVA de la UE), y se asignan a la parte que no lo tenía por cercanía a su nombre. Nunca se pisa un NIF que ya
haya devuelto el modelo, ni se usa el mismo para el emisor y el receptor. También avisa del NIF leído que no aparece en el texto (una lectura inventada)."""
from __future__ import annotations

import re

from . import facturas_control as control
from .fiscal_identidad import nif_valido_es

_ESPANOL = re.compile(r"(?<![A-Z0-9])(?:ES[\s-]?)?([XYZ]\d{7}[A-Z]|\d{8}[A-Z]|[A-HJNPQRSUVW]\d{7}[0-9A-J])(?![A-Z0-9])")
_UE = re.compile(r"(?<![A-Z0-9])((?:AT|BE|BG|CY|CZ|DE|DK|EE|EL|FI|FR|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK)[A-Z0-9]{8,12})(?![A-Z0-9])")
ANTES, DESPUES = 60, 140                         # caracteres de distancia al nombre donde se acepta un NIF: antes (cabecera con el NIF-IVA) o después (debajo del nombre)


def sin_es(nif: str | None) -> str:
    """El NIF sin espacios ni guiones y sin el prefijo «ES» si lo que queda es un NIF español válido (ESB12345674 → B12345674)."""
    n = re.sub(r"[\s.\-]", "", str(nif or "")).upper()
    return n[2:] if n.startswith("ES") and len(n) == 11 and nif_valido_es(n[2:]) else n


def _limpio(texto: str) -> str:
    """El texto en mayúsculas con los NIF escritos «B-85049435», «B 85049435» o «12345678-Z» pegados (misma longitud de línea no importa: se usa para buscar)."""
    t = texto.upper()
    t = re.sub(r"(?<![A-Z0-9])([A-HJNPQRSUVWXYZ])[\s-](\d{7}[0-9A-J])(?![A-Z0-9])", r"\1\2", t)
    return re.sub(r"(?<![A-Z0-9])(\d{8})[\s-]([A-Z])(?![A-Z0-9])", r"\1\2", t)


def candidatos(texto: str) -> list[tuple[int, str]]:
    """[(posición, NIF)] de los NIF españoles con dígito de control correcto y los NIF-IVA europeos con formato correcto que hay en el texto."""
    t = _limpio(texto)
    salida = [(m.start(), m.group(1)) for m in _ESPANOL.finditer(t) if nif_valido_es(m.group(1))]
    for m in _UE.finditer(t):
        if control.nif_ue_con_formato(m.group(1)):
            salida.append((m.start(), m.group(1)))
    return sorted(salida)


def _posiciones(texto_mayus: str, nombre: str) -> list[tuple[int, int]]:
    n = re.sub(r"\s+", " ", nombre or "").strip().upper()
    for fragmento in (n, n[:14]):
        if len(fragmento) < 4:
            continue
        patron = re.escape(fragmento).replace(r"\ ", r"\s+")
        encontrados = [(m.start(), m.end()) for m in re.finditer(patron, texto_mayus)]
        if encontrados:
            return encontrados
    return []


def _mas_cercano(cands: list[tuple[int, str]], posiciones: list[tuple[int, int]], usados: set[str]) -> str | None:
    mejor, distancia = None, 10 ** 9
    for ini, fin in posiciones:
        for pos, nif in cands:
            if nif in usados:
                continue
            d = pos - fin if pos >= fin else ini - pos
            if (pos >= fin and d <= DESPUES) or (pos < fin and d <= ANTES):
                if d < distancia:
                    mejor, distancia = nif, d
    return mejor


def completar(datos: dict, texto: str) -> list[str]:
    """Rellena emisor_nif / receptor_nif cuando el modelo los dejó vacíos y el documento los tiene junto al nombre. Devuelve los avisos (el NIF leído que no está en el texto)."""
    avisos: list[str] = []
    if not texto or len(texto) < 40:
        return avisos
    plano = re.sub(r"[\s.\-]", "", texto).upper()
    for parte in ("emisor", "receptor"):
        leido = sin_es(datos.get(f"{parte}_nif"))
        if leido and leido not in plano and len(leido) >= 8:
            avisos.append(f"El NIF leído del {parte} ({leido}) no aparece en el texto del documento: compruébalo.")
    cands = candidatos(texto)
    usados = {sin_es(datos.get("emisor_nif")), sin_es(datos.get("receptor_nif"))} - {""}
    t = _limpio(texto)
    faltan = [p for p in ("emisor", "receptor") if not datos.get(f"{p}_nif") and datos.get(f"{p}_nombre")]
    for parte in faltan:
        nif = _mas_cercano(cands, _posiciones(t, datos[f"{parte}_nombre"]), usados)
        if nif:
            datos[f"{parte}_nif"] = nif
            usados.add(nif)
            avisos.append(f"El modelo no devolvió el NIF del {parte}: se ha tomado del texto del documento ({nif}). Compruébalo.")
    pendientes = [p for p in faltan if not datos.get(f"{p}_nif")]
    sueltos = {n for _p, n in cands} - usados
    if len(pendientes) == 1 and len(sueltos) == 1:                     # solo falta uno y en todo el documento sobra uno: es ese
        nif = next(iter(sueltos))
        datos[f"{pendientes[0]}_nif"] = nif
        avisos.append(f"El modelo no devolvió el NIF del {pendientes[0]}: se ha tomado del texto del documento ({nif}). Compruébalo.")
    return avisos
