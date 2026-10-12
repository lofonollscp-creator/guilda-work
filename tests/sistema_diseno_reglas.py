"""Reglas del sistema de diseño (ver PLAN_MAESTRO.md §3) y su recuento por fichero. Lo usan tests/test_sistema_diseno.py y
scripts/sistema_diseno_base.py (que regenera tests/datos/sistema_diseno_base.json). Solo lee texto: no importa la aplicación."""
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BASE = RAIZ / "tests" / "datos" / "sistema_diseno_base.json"

# regla -> (descripción, expresión, dónde se busca: "html" plantillas, "js" ficheros .js propios)
REGLAS = {
    "dialogo_nativo": ("confirm()/alert()/prompt() del navegador: usar GuildaDS (ds.js)", re.compile(r"(?<![\w.])(?:window\.)?(?:confirm|alert|prompt)\("), ("html", "js")),
    "select_nativo": ("<select> sin componente del sistema", re.compile(r"<select\b"), ("html",)),
    "boton_sin_clase": ("<button> sin clase (usar boton() de _ds o una clase .btn)", re.compile(r"<button\b(?:(?!class=)[^>])*>"), ("html",)),
    "estilo_en_linea": ('style="…" en línea: usar una clase', re.compile(r'\sstyle="'), ("html",)),
    "fecha_nativa": ("<input type=date|datetime-local|time> sin selector de fecha del sistema", re.compile(r'<input\b[^>]*type="(?:date|datetime-local|time)"'), ("html",)),
}
# Siempre cero (sin línea base): rompen la política de contenido (CSP) o el diseño por completo.
PROHIBIDAS = {
    "manejador_en_linea": ("atributo on…= en línea: lo bloquea la CSP, usar data-* (csp_compat.js)", re.compile(r'\son(?:click|submit|change|input|load|error|keydown|keyup|mouseover|focus|blur)\s*=\s*"')),
    "etiqueta_obsoleta": ("etiqueta HTML obsoleta", re.compile(r"<(?:center|font|marquee|blink|big|strike)\b")),
}


def _ficheros(donde: str):
    if donde == "html":
        return [p for p in sorted((RAIZ / "app" / "templates").rglob("*.html")) if "_ds" not in p.parts]
    return [p for p in sorted((RAIZ / "app" / "static").glob("*.js")) if not p.name.endswith(".min.js") and p.name not in ("ds.js", "csp_compat.js")]


def _lineas_sin_fallback(texto: str) -> str:
    """Los diálogos nativos que quedan como alternativa en la misma línea que GuildaDS no cuentan."""
    return "\n".join(l for l in texto.splitlines() if "GuildaDS" not in l and not l.lstrip().startswith(("//", "*", "/*")))


def contar() -> dict[str, dict[str, int]]:
    cuenta: dict[str, dict[str, int]] = {}
    for regla, (_desc, patron, donde) in REGLAS.items():
        por_fichero: dict[str, int] = {}
        for d in donde:
            for p in _ficheros(d):
                texto = p.read_text(encoding="utf-8")
                if regla == "dialogo_nativo":
                    texto = _lineas_sin_fallback(texto)
                n = len(patron.findall(texto))
                if n:
                    por_fichero[str(p.relative_to(RAIZ))] = n
        cuenta[regla] = por_fichero
    return cuenta


def prohibidas() -> dict[str, list[str]]:
    halladas: dict[str, list[str]] = {}
    for regla, (_desc, patron) in PROHIBIDAS.items():
        for p in _ficheros("html"):
            if patron.search(p.read_text(encoding="utf-8")):
                halladas.setdefault(regla, []).append(str(p.relative_to(RAIZ)))
    return halladas


def cargar_base() -> dict[str, dict[str, int]]:
    return json.loads(BASE.read_text(encoding="utf-8")) if BASE.exists() else {}


def guardar_base(cuenta: dict[str, dict[str, int]]) -> None:
    BASE.parent.mkdir(parents=True, exist_ok=True)
    BASE.write_text(json.dumps(cuenta, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
