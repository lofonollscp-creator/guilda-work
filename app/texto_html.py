"""HTML -> texto plano para INDEXAR y previsualizar correos. Sin dependencias de la app
(la usan tanto app/db.py, al migrar, como app/correo.py, al descargar)."""
import html as html_lib
import re

_BLOQUES_IGNORADOS = re.compile(r"<(script|style|head|title)\b[^>]*>.*?</\1\s*>|<!--.*?-->", re.IGNORECASE | re.DOTALL)
_MAX_CARACTERES = 200_000


def html_a_texto_indexable(contenido_html: str | None) -> str:
    """Texto visible de un HTML: sin estilos, scripts ni cabecera, con saltos de línea en los
    bloques y las entidades resueltas, limitado a 200.000 caracteres."""
    if not contenido_html:
        return ""
    texto = _BLOQUES_IGNORADOS.sub(" ", contenido_html)
    texto = re.sub(r"<br\s*/?>", "\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"</(p|div|h[1-6]|tr|table|li|blockquote)>", "\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = html_lib.unescape(texto).replace("\xa0", " ")
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n\s*\n+", "\n\n", texto).strip()
    return texto[:_MAX_CARACTERES]
