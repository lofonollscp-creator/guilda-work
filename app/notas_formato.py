"""Formato de las notas: un subconjunto pequeño y seguro de Markdown.

Se admite **negrita**, *cursiva*, listas (con "-", "*" o "1."), enlaces
[texto](https://...), direcciones http(s) sueltas (se convierten en enlace) y
saltos de línea. TODO el texto se escapa primero, así que no hay forma de
colar HTML, atributos ni `javascript:` -- las notas antiguas, en texto plano,
siguen siendo válidas. Sin dependencias nuevas (la app no usa `markdown`).
"""
import html
import re

from markupsafe import Markup

_ENLACE_O_URL = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)|(?<![\"'=>])(https?://[^\s<)]+)")
_NEGRITA = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_CURSIVA = re.compile(r"(?<![\*\w])\*(?=[^\s\*])(.+?)(?<=[^\s\*])\*(?![\*\w])")
_ITEM_LISTA = re.compile(r"^\s*[-*•]\s+(.*)$")
_ITEM_NUMERADO = re.compile(r"^\s*\d+[.)]\s+(.*)$")


def _enlaces(texto_escapado: str) -> str:
    def sustituir(m: re.Match) -> str:
        if m.group(2):
            etiqueta, url = m.group(1), m.group(2)
        else:
            url = m.group(3)
            # Los signos finales de puntuación no forman parte de la dirección.
            sobrante = ""
            while url and url[-1] in ".,;:!?":
                sobrante, url = url[-1] + sobrante, url[:-1]
            etiqueta = url
            return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{etiqueta}</a>{sobrante}'
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{etiqueta}</a>'
    return _ENLACE_O_URL.sub(sustituir, texto_escapado)


def _inline(linea: str) -> str:
    # Primero los enlaces: así ni la negrita ni la cursiva tocan el interior de
    # una dirección (por ejemplo, un "*" dentro de una URL).
    partes = []
    ultimo = 0
    escapada = html.escape(linea, quote=True)
    for m in _ENLACE_O_URL.finditer(escapada):
        partes.append(("txt", escapada[ultimo:m.start()]))
        partes.append(("enl", _enlaces(m.group(0))))
        ultimo = m.end()
    partes.append(("txt", escapada[ultimo:]))
    salida = []
    for tipo, trozo in partes:
        if tipo == "enl":
            salida.append(trozo)
        else:
            trozo = _NEGRITA.sub(r"<strong>\1</strong>", trozo)
            trozo = _CURSIVA.sub(r"<em>\1</em>", trozo)
            salida.append(trozo)
    return "".join(salida)


def nota_a_html(texto: str | None) -> Markup:
    """Devuelve HTML seguro (Markup) listo para pintar en una plantilla."""
    if not texto:
        return Markup("")
    bloques: list[str] = []
    parrafo: list[str] = []
    lista: list[str] = []
    tipo_lista: str | None = None

    def cerrar_parrafo():
        if parrafo:
            bloques.append("<p>" + "<br>".join(parrafo) + "</p>")
            parrafo.clear()

    def cerrar_lista():
        nonlocal tipo_lista
        if lista:
            etiqueta = "ol" if tipo_lista == "ol" else "ul"
            bloques.append(f"<{etiqueta}>" + "".join(f"<li>{i}</li>" for i in lista) + f"</{etiqueta}>")
            lista.clear()
        tipo_lista = None

    for linea in texto.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        item = _ITEM_LISTA.match(linea)
        numerado = None if item else _ITEM_NUMERADO.match(linea)
        if item or numerado:
            cerrar_parrafo()
            nuevo = "ul" if item else "ol"
            if tipo_lista not in (None, nuevo):
                cerrar_lista()
            tipo_lista = nuevo
            lista.append(_inline((item or numerado).group(1)))
        elif not linea.strip():
            cerrar_parrafo()
            cerrar_lista()
        else:
            cerrar_lista()
            parrafo.append(_inline(linea.strip()))
    cerrar_parrafo()
    cerrar_lista()
    return Markup("".join(bloques))
