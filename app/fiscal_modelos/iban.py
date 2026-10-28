"""IBAN para el 303: la cuenta de la devolución o, en una rectificativa con casilla 111, la cuenta que pide el diseño oficial («se deben rellenar los datos de cuenta bancaria», Nota 3 de la página DID).

Función pura. Solo se admiten cuentas españolas y de los países SEPA de la lista, que son las que no piden banco, dirección ni ciudad (la «marca SEPA» 3, «resto de países», sí los pide y no se genera)."""
from __future__ import annotations

import re

# país -> longitud del IBAN (ISO 13616). Zona SEPA.
LONGITUDES = {"AD": 24, "AT": 20, "BE": 16, "BG": 22, "CH": 21, "CY": 28, "CZ": 24, "DE": 22, "DK": 18, "EE": 20, "ES": 24, "FI": 18, "FR": 27, "GB": 22, "GR": 27, "HR": 21, "HU": 28, "IE": 22,
              "IS": 26, "IT": 27, "LI": 21, "LT": 20, "LU": 20, "LV": 21, "MC": 27, "MT": 31, "NL": 18, "NO": 15, "PL": 28, "PT": 25, "RO": 24, "SE": 24, "SI": 19, "SK": 24, "SM": 27}
# Marca SEPA del diseño (Nota 2): 1 cuenta de España · 2 Unión Europea / SEPA · 3 resto de países
MARCA_ESPANA, MARCA_SEPA = "1", "2"


class IbanNoValido(ValueError):
    pass


def normalizar(iban: str) -> str:
    return re.sub(r"[\s-]", "", iban or "").upper()


def validar(iban: str) -> str:
    """El IBAN sin espacios y en mayúsculas, o `IbanNoValido` con el motivo (país no admitido, longitud o dígitos de control)."""
    n = normalizar(iban)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", n):
        raise IbanNoValido("El IBAN debe empezar por dos letras de país y dos dígitos de control, y solo lleva letras y números.")
    pais = n[:2]
    if pais not in LONGITUDES:
        raise IbanNoValido(f"El país {pais} no está entre los admitidos (cuentas españolas y de la zona SEPA).")
    if len(n) != LONGITUDES[pais]:
        raise IbanNoValido(f"Un IBAN de {pais} tiene {LONGITUDES[pais]} caracteres y este tiene {len(n)}.")
    if int("".join(str(int(c, 36)) for c in n[4:] + n[:4])) % 97 != 1:
        raise IbanNoValido("Los dígitos de control del IBAN no cuadran: revisa que esté bien copiado.")
    return n


def marca_sepa(iban: str) -> str:
    return MARCA_ESPANA if normalizar(iban).startswith("ES") else MARCA_SEPA
