"""Color de acento de cada persona (botones, enlaces, foco): se elige de una lista cerrada en Perfil → Apariencia y se recuerda en su navegador (cookie; pasará a la cuenta cuando se pueda migrar el esquema).

Manda sobre el color del despacho (`marca.py`). Como allí, el texto sobre el acento y el acento como texto se calculan con contraste WCAG (>= 4,5:1) en tema claro y oscuro."""
from __future__ import annotations

from flask_babel import lazy_gettext as _l

from . import marca

COOKIE = "guilda-acento"
ACENTO_POR_DEFECTO = "lima"
# clave -> (nombre, color). «lima» es el acento de Guilda Work: no sobrescribe nada.
ACENTOS: dict[str, tuple] = {
    "lima": (_l("Lima"), "#a6e600"),
    "azul": (_l("Azul"), "#3b82f6"),
    "turquesa": (_l("Turquesa"), "#14b8a6"),
    "violeta": (_l("Violeta"), "#8b5cf6"),
    "rosa": (_l("Rosa"), "#ec4899"),
    "rojo": (_l("Rojo"), "#ef4444"),
    "naranja": (_l("Naranja"), "#f97316"),
    "ambar": (_l("Ámbar"), "#f5b400"),
}


def es_valido(clave) -> bool:
    return clave in ACENTOS


def css(clave: str | None) -> str:
    """Hoja de estilo (en línea) con las variables del acento; vacía si es el de por defecto."""
    if not clave or clave == ACENTO_POR_DEFECTO or clave not in ACENTOS:
        return ""
    d = marca.colores_derivados(ACENTOS[clave][1])
    base = f"--primary: {d['primary']}; --primary-dark: {d['primary_dark']}; --on-accent: {d['on_accent']};"
    claro = f"--primary-text: {d['texto_claro']}; --focus-ring: {d['texto_claro']};"
    oscuro = f"--primary-text: {d['texto_oscuro']}; --focus-ring: {d['texto_oscuro']};"
    return (f":root {{ {base} {claro} }}\n"
            f"@media (prefers-color-scheme: dark) {{ :root:not([data-theme=\"light\"]) {{ {base} {oscuro} }} }}\n"
            f':root[data-theme="dark"] {{ {base} {oscuro} }}\n')
