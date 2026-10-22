"""Validación determinista de las respuestas del asistente jurídico: existencia de las citas, tipo de fuente correcto y respaldo léxico de cada afirmación.

Lo que esto SÍ garantiza: ninguna cita apunta a algo que no se recuperó; una afirmación jurídica solo se apoya en fuentes jurídicas y una afirmación sobre un adjunto solo en ese adjunto; los
números, artículos y años que menciona una afirmación aparecen en lo que cita; y los términos clave de la afirmación aparecen en lo citado.
Lo que NO garantiza: que la interpretación sea jurídicamente correcta ni que la fuente sea la más aplicable. Una cita existente puede no sostener una afirmación: por eso se combina con revisión
profesional («revisado» solo lo marca una persona autorizada) y no se presenta ninguna «certeza» ni porcentaje."""
from __future__ import annotations

import re
import unicodedata

MAX_AFIRMACIONES = 40
MAX_TEXTO = 1500
ESTADOS = {"answered", "needs_context", "insufficient_evidence"}
_NUMEROS = {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
            "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70,
            "ochenta": 80, "noventa": 90, "cien": 100, "mil": 1000}
_VACIAS = {"para", "como", "pero", "sobre", "entre", "desde", "hasta", "segun", "cuando", "donde", "porque", "tambien", "aunque", "siendo", "puede", "pueden", "deben", "debera", "tiene", "tienen",
           "estos", "estas", "otros", "otras", "dicho", "dicha", "mismo", "misma", "cada", "esta", "este", "esto", "dentro", "mediante", "conforme", "cuyo", "cuya", "serán", "sera", "seran", "haber"}


def _sin_acentos(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def numeros(texto: str) -> set[str]:
    """Cifras de un texto, incluidas las escritas con letra («quince» -> 15), normalizadas como cadenas sin ceros ni separadores de miles."""
    t = _sin_acentos(texto)
    salida = {str(int(m.replace(".", ""))) for m in re.findall(r"\d[\d.]*\d|\d", t) if m.replace(".", "").isdigit()}
    for palabra in re.findall(r"[a-z]+", t):
        if palabra in _NUMEROS:
            salida.add(str(_NUMEROS[palabra]))
        elif palabra.startswith("veinti") and {"uno": 1, "un": 1, **_NUMEROS}.get(palabra[6:], 99) < 10:        # veintiuno … veintinueve
            salida.add(str(20 + {"uno": 1, "un": 1, **_NUMEROS}[palabra[6:]]))
    return salida


def _claves(texto: str) -> set[str]:
    return {p[:6] for p in re.findall(r"[a-z]{6,}", _sin_acentos(texto)) if p not in _VACIAS}


def respaldo(afirmacion: str, textos_citados: list[str]) -> tuple[bool, str]:
    """(ok, motivo). Léxico y numérico: los números de la afirmación están en lo citado y comparte términos clave con ello."""
    union = " ".join(textos_citados)
    faltan = numeros(afirmacion) - numeros(union)
    if faltan:
        return False, f"cita no contiene la cifra {', '.join(sorted(faltan))}"
    claves = _claves(afirmacion)
    if claves:
        en_texto = _claves(union)
        comunes = claves & en_texto
        minimo = 1 if len(claves) <= 3 else 2
        if len(comunes) < minimo:
            return False, "la cita no comparte términos con la afirmación"
    return True, ""


def mejor_extracto(afirmacion: str, texto: str, maximo: int = 500) -> str:
    """El pasaje del fragmento más cercano a la afirmación (el servidor lo elige; nunca lo escribe el modelo)."""
    frases = [f.strip() for f in re.split(r"(?<=[.;:\n])\s+", texto) if f.strip()]
    if not frases:
        return texto[:maximo]
    claves = _claves(afirmacion) | {str(n) for n in numeros(afirmacion)}
    mejor = max(range(len(frases)), key=lambda i: (len(claves & (_claves(frases[i]) | numeros(frases[i]))), -i))
    salida = frases[mejor]
    i = mejor + 1
    while len(salida) < maximo // 2 and i < len(frases):
        salida += " " + frases[i]
        i += 1
    return salida[:maximo]


def esquema(respuesta) -> list[str]:
    """Errores de forma de la salida del modelo (tipos, longitudes). Lista vacía = bien formada."""
    errores = []
    if not isinstance(respuesta, dict):
        return ["La respuesta no es un objeto JSON."]
    if respuesta.get("status") not in ESTADOS:
        errores.append("`status` debe ser answered, needs_context o insufficient_evidence.")
    for campo in ("facts", "missing_facts", "limitations", "next_steps"):
        v = respuesta.get(campo, [])
        if not isinstance(v, list) or any(not isinstance(x, str) or len(x) > MAX_TEXTO for x in v) or len(v) > 40:
            errores.append(f"`{campo}` debe ser una lista de textos.")
    c = respuesta.get("conclusion")
    if c is not None and (not isinstance(c, str) or len(c) > 6000):
        errores.append("`conclusion` debe ser un texto o null.")
    claims = respuesta.get("claims", [])
    if not isinstance(claims, list) or len(claims) > MAX_AFIRMACIONES:
        errores.append("`claims` debe ser una lista.")
    else:
        for i, a in enumerate(claims):
            if not isinstance(a, dict) or not isinstance(a.get("text"), str) or not a["text"].strip() or len(a["text"]) > MAX_TEXTO:
                errores.append(f"claims[{i}].text no es válido.")
            elif a.get("kind", "legal") not in ("legal", "fact"):
                errores.append(f"claims[{i}].kind debe ser legal o fact.")
            elif not isinstance(a.get("citations"), list) or any(not isinstance(x, str) for x in a["citations"]):
                errores.append(f"claims[{i}].citations debe ser una lista de referencias.")
    return errores


def comprobar(respuesta: dict, contexto: dict[str, dict]) -> tuple[list[str], dict[int, str]]:
    """(problemas, evaluación por afirmación). `contexto`: referencia («F1», «P2») -> {tipo, texto}. Solo se comprueba lo que se va a presentar como respondido."""
    problemas, evaluacion = [], {}
    if respuesta["status"] != "answered":
        return problemas, evaluacion
    if not (respuesta.get("conclusion") or "").strip():
        problemas.append("Una respuesta `answered` necesita `conclusion`.")
    claims = respuesta.get("claims", [])
    if not claims:
        problemas.append("Una respuesta `answered` necesita al menos una afirmación con cita.")
    for i, a in enumerate(claims):
        refs = list(dict.fromkeys(a["citations"]))
        if not refs:
            problemas.append(f"La afirmación {i + 1} no tiene ninguna cita.")
            evaluacion[i] = "sin_cita"
            continue
        desconocidas = [r for r in refs if r not in contexto]
        if desconocidas:
            problemas.append(f"La afirmación {i + 1} cita referencias que no existen: {', '.join(desconocidas)}.")
            evaluacion[i] = "cita_inexistente"
            continue
        tipo = a.get("kind", "legal")
        validas = [r for r in refs if contexto[r]["tipo"] == ("legal_source" if tipo == "legal" else "private_attachment")]
        if not validas:
            problemas.append(f"La afirmación {i + 1} ({'jurídica' if tipo == 'legal' else 'sobre un adjunto'}) no se apoya en una fuente del tipo adecuado.")
            evaluacion[i] = "fuente_inadecuada"
            continue
        ok, motivo = respaldo(a["text"], [contexto[r]["texto"] for r in validas])
        evaluacion[i] = "respaldo_lexico" if ok else "sin_respaldo"
        if not ok:
            problemas.append(f"La afirmación {i + 1} no queda respaldada: {motivo}.")
    return problemas, evaluacion
