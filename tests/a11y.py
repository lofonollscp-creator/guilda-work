"""Auditoría de accesibilidad estática (reglas WCAG que se pueden comprobar sin navegador) sobre el HTML renderizado.

No sustituye a una prueba con lector de pantalla, pero atrapa lo que más se repite: controles sin nombre, imágenes sin texto
alternativo, ids duplicados, referencias rotas, saltos de encabezados, diálogos sin etiqueta... Se usa desde test_accesibilidad.py."""
from __future__ import annotations

from html.parser import HTMLParser

_VACIOS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_SIN_NOMBRE_NECESARIO = {"hidden", "submit", "reset", "button", "image"}


class _Nodo:
    def __init__(self, etiqueta, atributos, padre):
        self.etiqueta, self.a, self.padre, self.hijos, self.texto = etiqueta, dict(atributos), padre, [], ""

    def texto_total(self) -> str:
        return (self.texto + " " + " ".join(h.texto_total() for h in self.hijos)).strip()

    def ancestros(self):
        n = self.padre
        while n is not None:
            yield n
            n = n.padre


class _Arbol(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.raiz = _Nodo("raiz", [], None)
        self.actual = self.raiz
        self.todos: list[_Nodo] = []

    def handle_starttag(self, tag, attrs):
        n = _Nodo(tag, attrs, self.actual)
        self.actual.hijos.append(n)
        self.todos.append(n)
        if tag not in _VACIOS:
            self.actual = n

    def handle_startendtag(self, tag, attrs):
        n = _Nodo(tag, attrs, self.actual)
        self.actual.hijos.append(n)
        self.todos.append(n)

    def handle_endtag(self, tag):
        n = self.actual
        while n is not None and n.etiqueta != tag:
            n = n.padre
        if n is not None and n.padre is not None:
            self.actual = n.padre

    def handle_data(self, data):
        if self.actual.etiqueta not in ("script", "style"):
            self.actual.texto += data


def analizar(html: str) -> list[str]:
    """Lista de incumplimientos encontrados (vacía = limpia)."""
    arbol = _Arbol()
    arbol.feed(html)
    nodos = arbol.todos
    problemas: list[str] = []
    ids = [n.a["id"] for n in nodos if n.a.get("id")]
    por_id = {n.a["id"]: n for n in nodos if n.a.get("id")}
    etiquetas_for = {n.a["for"] for n in nodos if n.etiqueta == "label" and n.a.get("for")}

    html_tag = next((n for n in nodos if n.etiqueta == "html"), None)
    if html_tag is None or not html_tag.a.get("lang"):
        problemas.append("<html> sin atributo lang")
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        problemas.append(f"id duplicado: {dup}")
    mains = [n for n in nodos if n.etiqueta == "main" or n.a.get("role") == "main"]
    if len(mains) != 1:
        problemas.append(f"debe haber un único <main> (hay {len(mains)})")

    def nombre_accesible(n: _Nodo) -> str:
        if n.a.get("aria-label", "").strip():
            return n.a["aria-label"]
        for ref in n.a.get("aria-labelledby", "").split():
            if ref in por_id and por_id[ref].texto_total():
                return por_id[ref].texto_total()
        if n.a.get("title", "").strip():
            return n.a["title"]
        if n.etiqueta in ("input", "textarea") and n.a.get("placeholder", "").strip():
            return n.a["placeholder"]       # axe lo admite como último recurso (el navegador lo usa de nombre)
        return ""

    def oculto(n: _Nodo) -> bool:
        return any(("hidden" in x.a) or x.a.get("aria-hidden") == "true" for x in (n, *n.ancestros()))

    for n in nodos:
        e = n.etiqueta
        if oculto(n):
            continue        # fuera del árbol de accesibilidad: no se anuncia ni se enfoca
        if e == "img" and "alt" not in n.a and n.a.get("role") not in ("presentation", "none"):
            problemas.append(f"<img src={n.a.get('src', '')[:40]!r}> sin alt")
        if e in ("input", "select", "textarea"):
            tipo = (n.a.get("type") or "text").lower()
            if e == "input" and tipo in _SIN_NOMBRE_NECESARIO:
                if tipo in ("submit", "reset", "button") and not (n.a.get("value") or nombre_accesible(n)):
                    problemas.append(f"<input type={tipo}> sin texto")
                continue
            envuelto = any(a.etiqueta == "label" for a in n.ancestros())
            if not (nombre_accesible(n) or envuelto or (n.a.get("id") and n.a["id"] in etiquetas_for)):
                problemas.append(f"control sin etiqueta: <{e} name={n.a.get('name', '')!r} type={tipo} id={n.a.get('id', '')!r} class={n.a.get('class', '')[:30]!r} placeholder={n.a.get('placeholder', '')[:25]!r}>")
        if e == "button" and not (n.texto_total() or nombre_accesible(n)):
            problemas.append(f"<button> sin nombre (id={n.a.get('id', '')!r} class={n.a.get('class', '')[:30]!r})")
        if e == "a" and n.a.get("href") is not None and not (n.texto_total() or nombre_accesible(n)):
            if not any(h.etiqueta == "img" and h.a.get("alt") for h in _descendientes(n)):
                problemas.append(f"enlace sin nombre: href={n.a.get('href', '')[:50]!r}")
        if e == "iframe" and not nombre_accesible(n):
            problemas.append("<iframe> sin title")
        if n.a.get("tabindex", "").strip().isdigit() and int(n.a["tabindex"]) > 0:
            problemas.append(f"tabindex positivo en <{e}>")
        if n.a.get("role") == "dialog" and not nombre_accesible(n):
            problemas.append("role=dialog sin nombre accesible")
        if n.a.get("role") == "dialog" and n.a.get("aria-modal") != "true":
            problemas.append("role=dialog sin aria-modal=true")
        for atributo in ("aria-labelledby", "aria-describedby", "aria-controls"):
            for ref in n.a.get(atributo, "").split():
                if ref not in por_id:
                    problemas.append(f"{atributo} apunta a un id inexistente: {ref}")
        if e == "label" and n.a.get("for") and n.a["for"] not in por_id:
            problemas.append(f"<label for={n.a['for']!r}> sin control")
        if e == "table" and not any(h.etiqueta == "th" for h in _descendientes(n)):
            problemas.append("<table> sin <th>")
    niveles = [int(n.a.get("aria-level") or n.etiqueta[1]) for n in nodos if n.etiqueta in ("h1", "h2", "h3", "h4", "h5", "h6")]
    for anterior, siguiente in zip(niveles, niveles[1:]):
        if siguiente > anterior + 1:
            problemas.append(f"salto de encabezado h{anterior} → h{siguiente}")
            break
    if not any(n.etiqueta == "h1" and not ("hidden" in n.a) for n in nodos):
        problemas.append("la página no tiene <h1>")
    return problemas


def _descendientes(n: _Nodo):
    for h in n.hijos:
        yield h
        yield from _descendientes(h)


def _luminancia(hexcolor: str) -> float:
    h = hexcolor.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    canales = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lineales = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canales]
    return 0.2126 * lineales[0] + 0.7152 * lineales[1] + 0.0722 * lineales[2]


def contraste(a: str, b: str) -> float:
    la, lb = _luminancia(a), _luminancia(b)
    claro, oscuro = max(la, lb), min(la, lb)
    return (claro + 0.05) / (oscuro + 0.05)
