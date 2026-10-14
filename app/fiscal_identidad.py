"""Identificación fiscal de los clientes (especificación de control fiscal, RF-01): normalización, validación del formato español (NIF, NIE y CIF con su dígito de control)
y la regla de **no duplicar** un cliente dentro de la asesoría cuando coinciden país e identificación normalizada.

La unicidad solo se impone cuando la identificación es **válida** (o, en otros países, razonablemente identificativa): un valor de relleno como «B123» no impide dar de alta
dos clientes, pero tampoco se toma por una identificación. Una excepción documentada (`nif_duplicado_autorizado`) permite tener dos fichas con el mismo NIF (perfil histórico,
situación especial) sin fusionarlas. Nunca se fusionan clientes por parecido de nombre."""
from __future__ import annotations

import re

_LETRAS_DNI = "TRWAGMYFPDXBNJZSQVHLCKE"
_CIF = re.compile(r"^([ABCDEFGHJNPQRSUVW])(\d{7})([0-9A-J])$")
_DNI = re.compile(r"^(\d{8})([A-Z])$")
_NIE = re.compile(r"^([XYZ])(\d{7})([A-Z])$")


class ClienteDuplicado(ValueError):
    """Ya hay otro cliente de la asesoría con esa identificación fiscal (en ese país). `existente_id` y `existente_nombre` dicen cuál."""
    def __init__(self, nif: str, existente_id: int, existente_nombre: str):
        super().__init__(f"Ya existe un cliente con la identificación fiscal {nif}: «{existente_nombre}» (n.º {existente_id}). Si es una situación especial, autoriza el duplicado con una justificación.")
        self.existente_id, self.existente_nombre = existente_id, existente_nombre


def normalizar(texto: str | None) -> str:
    """Mayúsculas y solo letras y números: «b-16.406 233» → «B16406233»."""
    return re.sub(r"[^0-9A-Z]", "", (texto or "").upper())


def _control_cif(digitos: str) -> int:
    pares = sum(int(d) for d in digitos[1::2])
    impares = sum(sum(divmod(int(d) * 2, 10)) for d in digitos[0::2])
    return (10 - (pares + impares) % 10) % 10


def nif_valido_es(texto: str | None) -> bool:
    n = normalizar(texto)
    if m := _DNI.match(n):
        return _LETRAS_DNI[int(m.group(1)) % 23] == m.group(2)
    if m := _NIE.match(n):
        return _LETRAS_DNI[int(str(" XYZ".index(m.group(1)) - 1) + m.group(2)) % 23] == m.group(3)
    if m := _CIF.match(n):
        control = _control_cif(m.group(2))
        esperado_letra, esperado_digito = "JABCDEFGHI"[control], str(control)
        if m.group(1) in "PQRSNW":
            return m.group(3) == esperado_letra
        if m.group(1) in "ABEH":
            return m.group(3) == esperado_digito
        return m.group(3) in (esperado_letra, esperado_digito)
    return False


def clave_unica(nif: str | None, pais: str | None = "ES") -> str | None:
    """La identificación normalizada que se usa para detectar duplicados, o `None` si no procede imponerla (vacía, de relleno o sin formato reconocible)."""
    n = normalizar(nif)
    if not n:
        return None
    if (pais or "ES").upper() == "ES":
        return n if nif_valido_es(n) else None
    return n if len(n) >= 6 and any(c.isdigit() for c in n) else None


def formato_dudoso(nif: str | None, pais: str | None = "ES") -> bool:
    """True si hay una identificación escrita pero no se reconoce como válida (para avisar, sin impedir guardar)."""
    return bool(normalizar(nif)) and clave_unica(nif, pais) is None and (pais or "ES").upper() == "ES"
