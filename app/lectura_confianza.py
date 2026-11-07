"""Cuánta confianza merece cada dato leído de una factura (R4), con criterios que **no** dependen de que el modelo se crea sus propias respuestas:

* el dato sale de una factura electrónica (XML) o lo confirma el QR del ticket → 100;
* el dato aparece literalmente en la capa de texto del PDF → al menos 96 (está escrito en el documento);
* en cualquier otro caso, lo que dice el modelo, recortado por las comprobaciones: sin evidencia, 75 como mucho; con una cita que no contiene el valor, 40; un NIF con dígito de control erróneo, 30;
  importes que no cuadran con las líneas, 40; un dato que contradice al QR, 20.

La confianza global es la del dato más débil de los imprescindibles (número, fecha, total y NIF de la contraparte), y baja a 60 si hay comprobaciones propias que fallan y a 85 si hay avisos.
Funciones puras, sin base de datos ni red."""
from __future__ import annotations

from . import lectura_evidencias as ev

CAMPOS = tuple(ev.CAMPOS)
IMPRESCINDIBLES = ("numero", "fecha", "total")
TOPE_SIN_EVIDENCIA = 75
TOPE_CITA_INCOHERENTE = 40
TOPE_NIF_INVALIDO = 30
TOPE_NO_CUADRA = 40
TOPE_CONTRADICE_QR = 20
SUELO_EN_EL_TEXTO = 96
TOPE_CON_COMPROBACIONES = 60
TOPE_CON_AVISOS = 85


def _entero(valor, por_defecto: int = 70) -> int:
    try:
        return max(0, min(100, int(round(float(valor)))))
    except (TypeError, ValueError):
        return por_defecto


def puntuar(*, datos: dict, valores: dict[str, str], evidencias: dict[str, dict], fuente: str, texto_documento: str = "", qr: dict | None = None, campo_contraparte: str = "emisor_nif",
            nif_invalido: bool = False, cuadra: bool = True, comprobaciones: list[str] | None = None, avisos: list[str] | None = None) -> dict:
    """{"campos": {campo: 0-100}, "global": 0-100, "motivos": [por qué baja]}. `valores`: lo que finalmente se leyó de cada campo (número, fecha, total, emisor_nif, receptor_nif, base, iva)."""
    modelo = datos.get("confianza") if isinstance(datos.get("confianza"), dict) else {}
    qr = qr or {}
    campos: dict[str, int] = {}
    motivos: list[str] = []
    for c in CAMPOS:
        valor = valores.get(c, "")
        if not valor:
            continue
        if fuente == "xml":
            campos[c] = 100
            continue
        puntos = _entero(modelo.get(c))
        e = evidencias.get(c)
        if e is None:
            puntos = min(puntos, TOPE_SIN_EVIDENCIA)
        elif not e.get("coherente"):
            puntos = min(puntos, TOPE_CITA_INCOHERENTE)
            motivos.append(f"la cita de «{ev.CAMPOS[c].lower()}» no contiene el valor leído")
        if texto_documento and ev.coherente(c, texto_documento, valor):
            puntos = max(puntos, SUELO_EN_EL_TEXTO)
        dato_qr = {"numero": qr.get("numero"), "fecha": qr.get("fecha"), "total": qr.get("total"), "emisor_nif": qr.get("nif")}.get(c)
        if dato_qr:
            if _igual(c, valor, dato_qr):
                puntos = 100
            else:
                puntos = min(puntos, TOPE_CONTRADICE_QR)
                motivos.append(f"«{ev.CAMPOS[c].lower()}» no coincide con el QR de la factura")
        if c == campo_contraparte and nif_invalido:
            puntos = min(puntos, TOPE_NIF_INVALIDO)
            motivos.append("el dígito de control del NIF no es válido")
        if not cuadra and c in ("total", "base", "iva"):
            puntos = min(puntos, TOPE_NO_CUADRA)
        campos[c] = puntos
    claves = [c for c in (*IMPRESCINDIBLES, campo_contraparte) if valores.get(c)]
    faltan = [c for c in IMPRESCINDIBLES if not valores.get(c)]
    if faltan:
        motivos.append("falta: " + ", ".join(ev.CAMPOS[c].lower() for c in faltan))
    global_ = min((campos[c] for c in claves), default=0) if not faltan else 0
    if not cuadra:
        global_ = min(global_, TOPE_NO_CUADRA)
        motivos.append("las líneas no cuadran con el total")
    if comprobaciones:
        global_ = min(global_, TOPE_CON_COMPROBACIONES)
        motivos.append("hay comprobaciones propias que fallan")
    if avisos:
        global_ = min(global_, TOPE_CON_AVISOS)
    return {"campos": campos, "global": global_, "motivos": motivos}


def _igual(campo: str, leido: str, esperado: str) -> bool:
    if campo == "total":
        a, b = ev._centimos(leido), ev._centimos(esperado)
        return a is not None and a == b
    if campo == "fecha":
        return leido[:10] == esperado[:10]
    return ev._alnum(leido) == ev._alnum(esperado)


def nivel(puntos: int | None) -> str:
    """El semáforo de la pantalla: «alta» (90 o más), «media» (70-89) o «baja»."""
    if puntos is None:
        return "sin_dato"
    return "alta" if puntos >= 90 else ("media" if puntos >= 70 else "baja")
