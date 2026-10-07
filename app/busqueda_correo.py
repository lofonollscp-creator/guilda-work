"""Operadores en la búsqueda de correo: «de:ana asunto:factura adjunto: antes:2026-10-01 cliente:"Sol SL"».
Función pura: separa lo que son operadores del texto libre y resuelve cliente/categoría por nombre.
Lo que no se entiende se deja en el texto (nunca se pierde una búsqueda) y lo que no se puede resolver se avisa."""
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta

_TROZO = re.compile(r'(?<![^\s])([^\s:"]{1,12}):(?:"([^"]*)"|(\S*))')

# alias -> operador canónico
_ALIAS = {
    "de": "de", "from": "de", "remitente": "de", "des": "de", "von": "de",
    "para": "para", "to": "para", "per": "para", "pour": "para",
    "asunto": "asunto", "subject": "asunto", "assumpte": "asunto", "objet": "asunto",
    "adjunto": "adjunto", "attachment": "adjunto", "adjunt": "adjunto", "piece": "adjunto", "pièce": "adjunto", "tiene": "tiene", "has": "tiene", "te": "tiene",
    "es": "es", "is": "es", "és": "es", "est": "es",
    "antes": "antes", "before": "antes", "abans": "antes", "avant": "antes",
    "despues": "despues", "después": "despues", "after": "despues", "despres": "despues", "després": "despues", "apres": "despues", "après": "despues",
    "cliente": "cliente", "client": "cliente",
    "categoria": "categoria", "categoría": "categoria", "etiqueta": "categoria", "label": "categoria", "category": "categoria", "catégorie": "categoria",
}
_ESTADOS = {
    "noleido": "no_leido", "nuevo": "no_leido", "unread": "no_leido", "nollegit": "no_leido", "nonlu": "no_leido",
    "destacado": "destacado", "starred": "destacado", "flagged": "destacado", "destacat": "destacado", "favori": "destacado",
}
_ADJUNTOS = {"adjunto", "adjuntos", "attachment", "attachments", "adjunt", "adjunts", "piece", "pièce"}


def _plano(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto or "")
    return re.sub(r"[^a-z0-9]+", "", "".join(c for c in base if not unicodedata.combining(c)).lower())


@dataclass
class Consulta:
    texto: str = ""
    filtros: dict = field(default_factory=dict)         # nombres de argumentos de db.listar_mensajes_correo
    solo_no_leidos: bool = False
    sin_resolver: list = field(default_factory=list)    # «cliente:Foo» sin coincidencia única


def _fecha(valor: str) -> str | None:
    """YYYY-MM-DD, o YYYY-MM (el primer día del mes); None si no es una fecha."""
    for formato in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(valor, formato).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _resolver(valor: str, opciones) -> int | None:
    """Id si hay una única coincidencia exacta o, si no, una única que contenga el texto (sin acentos ni mayúsculas)."""
    buscado = _plano(valor)
    if not buscado:
        return None
    exactas = [i for i, nombre in opciones if _plano(nombre) == buscado]
    if len(exactas) == 1:
        return exactas[0]
    contienen = [i for i, nombre in opciones if buscado in _plano(nombre)]
    return contienen[0] if len(contienen) == 1 else None


def interpretar(q: str, categorias=(), clientes=()) -> Consulta:
    """`categorias` y `clientes`: listas de (id, nombre)."""
    resultado = Consulta()
    q = (q or "")[:500]
    restos = []
    ultimo = 0
    for m in _TROZO.finditer(q):
        operador = _ALIAS.get(m.group(1).lower())
        valor = (m.group(2) if m.group(2) is not None else m.group(3) or "").strip()
        entendido = True
        if operador in ("de", "para", "asunto") and valor:
            resultado.filtros[{"de": "remitente", "para": "destinatarios", "asunto": "asunto"}[operador]] = valor
        elif operador == "adjunto" and not valor or (operador == "tiene" and valor.lower() in _ADJUNTOS):
            resultado.filtros["con_adjuntos"] = True
        elif operador == "es" and _ESTADOS.get(_plano(valor)):
            if _ESTADOS[_plano(valor)] == "no_leido":
                resultado.solo_no_leidos = True
            else:
                resultado.filtros["solo_destacados"] = True
        elif operador in ("antes", "despues") and _fecha(valor):
            resultado.filtros["hasta" if operador == "antes" else "desde"] = _fecha(valor)
            if operador == "antes":
                # «antes del 1 de octubre» no incluye ese día: se resta uno para usar «hasta» inclusivo
                resultado.filtros["hasta"] = (datetime.strptime(_fecha(valor), "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        elif operador in ("cliente", "categoria") and valor:
            encontrado = _resolver(valor, clientes if operador == "cliente" else categorias)
            if encontrado is None:
                resultado.sin_resolver.append(f"{m.group(1)}:{valor}")
            else:
                resultado.filtros["cliente_fiscal_id" if operador == "cliente" else "categoria_id"] = encontrado
        else:
            entendido = False
        if entendido:
            restos.append(q[ultimo:m.start()])
            ultimo = m.end()
    restos.append(q[ultimo:])
    resultado.texto = " ".join(" ".join(restos).split())
    return resultado
