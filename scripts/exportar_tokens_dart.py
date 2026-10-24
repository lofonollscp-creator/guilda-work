"""Genera los tokens de diseño de la app móvil (`mobile/lib/diseno/tokens.g.dart`) desde la FUENTE ÚNICA de la web: las variables CSS de `app/static/style.css`.

    python3 scripts/exportar_tokens_dart.py             # regenera el fichero
    python3 scripts/exportar_tokens_dart.py --comprobar # falla (1) si lo versionado está desfasado de style.css

Solo biblioteca estándar. Lee `:root` (claro), el bloque oscuro de `@media (prefers-color-scheme: dark)` y `:root[data-theme="dark"]` (que deben coincidir: se
comprueba) y resuelve `var(--x)`. Antes la paleta se copiaba a mano («cualquier cambio de marca debe hacerse en LOS DOS SITIOS»); ahora el CI compara."""
import argparse
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CSS = RAIZ / "app/static/style.css"
SALIDA = RAIZ / "mobile/lib/diseno/tokens.g.dart"

# variable CSS → nombre Dart (solo los colores que usa la app).
COLORES = {
    "bg": "bg", "surface": "surface", "border": "border", "text": "text", "text-muted": "textMuted",
    "primary": "primary", "primary-dark": "primaryDark", "primary-text": "primaryText", "on-accent": "onAccent",
    "danger": "danger", "success": "success", "warning": "warning",
    "danger-text": "dangerText", "success-text": "successText", "warning-text": "warningText", "focus-ring": "focusRing",
}
# variable CSS → nombre Dart (medidas en px = dp).
MEDIDAS = {
    "space-1": "espacio1", "space-2": "espacio2", "space-3": "espacio3", "space-4": "espacio4", "space-5": "espacio5", "space-6": "espacio6",
    "radius-sm": "radioPequeno", "radius-md": "radioMedio", "radius-lg": "radioGrande",
}


def _bloque(css: str, inicio: str) -> str:
    """El contenido de la llave que abre justo después de `inicio` (con llaves anidadas)."""
    i = css.index(inicio) + len(inicio)
    j = css.index("{", i) if css[i:].lstrip()[:1] != "{" else css.index("{", i)
    nivel, k = 1, j + 1
    while nivel:
        nivel += {"{": 1, "}": -1}.get(css[k], 0)
        k += 1
    return css[j + 1:k - 1]


def _variables(bloque: str) -> dict[str, str]:
    sin_comentarios = re.sub(r"/\*.*?\*/", "", bloque, flags=re.S)
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"--([\w-]+)\s*:\s*([^;]+);", sin_comentarios)}


def leer(css_texto: str) -> tuple[dict[str, str], dict[str, str]]:
    """(variables claras, variables oscuras ya fusionadas con las claras), con `var()` resuelto."""
    claro = _variables(_bloque(css_texto, "\n:root "))
    media = _bloque(css_texto, "@media (prefers-color-scheme: dark)")
    oscuro_media = _variables(_bloque(media, ':root:not([data-theme="light"])'))
    oscuro_manual = _variables(_bloque(css_texto, '\n:root[data-theme="dark"] '))
    if oscuro_media != oscuro_manual:
        diferencias = sorted(k for k in set(oscuro_media) | set(oscuro_manual) if oscuro_media.get(k) != oscuro_manual.get(k))
        raise SystemExit(f"style.css: el modo oscuro automático y el manual difieren en: {', '.join(diferencias)}")
    return _resolver(claro), _resolver({**claro, **oscuro_media})


def _resolver(v: dict[str, str]) -> dict[str, str]:
    def uno(valor: str, nivel: int = 0) -> str:
        m = re.fullmatch(r"var\(--([\w-]+)\)", valor)
        if not m:
            return valor
        if nivel > 8 or m.group(1) not in v:
            raise SystemExit(f"style.css: no se puede resolver {valor}")
        return uno(v[m.group(1)], nivel + 1)
    return {k: uno(x) for k, x in v.items()}


def _color(valor: str) -> str:
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", valor)
    if not m:
        raise SystemExit(f"Color no admitido: {valor!r} (usa #rrggbb)")
    return f"Color(0xFF{m.group(1).upper()})"


def _px(valor: str) -> str:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)px", valor)
    if not m:
        raise SystemExit(f"Medida no admitida: {valor!r} (usa px)")
    return f"{float(m.group(1))}"


def generar(css_texto: str) -> str:
    claro, oscuro = leer(css_texto)
    L = ["// GENERADO desde app/static/style.css (scripts/exportar_tokens_dart.py). No editar a mano: cambia la web y vuelve a generar.", "import 'package:flutter/painting.dart';", ""]
    for clase, v, doc in (("TokensClaro", claro, "Tema claro."), ("TokensOscuro", oscuro, "Tema oscuro (lo no redefinido hereda del claro, como en la web).")):
        L += [f"/// {doc}", f"class {clase} {{", f"  {clase}._();"]
        for css, dart in COLORES.items():
            L.append(f"  static const {dart} = {_color(v[css])};")
        L += ["}", ""]
    L += ["/// Medidas comunes a los dos temas, en dp.", "class TokensMedidas {", "  TokensMedidas._();"]
    for css, dart in MEDIDAS.items():
        L.append(f"  static const {dart} = {_px(claro[css])};")
    L += ["}", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--comprobar", action="store_true")
    a = ap.parse_args()
    nuevo = generar(CSS.read_text())
    if a.comprobar:
        if not SALIDA.exists() or SALIDA.read_text() != nuevo:
            print("Los tokens de la app móvil están desfasados de style.css: ejecuta scripts/exportar_tokens_dart.py", file=sys.stderr)
            return 1
        print("Tokens al día", file=sys.stderr)
        return 0
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(nuevo)
    print(f"{SALIDA.relative_to(RAIZ)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
