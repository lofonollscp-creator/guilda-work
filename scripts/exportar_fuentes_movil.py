"""Genera las fuentes de la app móvil (`mobile/assets/fonts/*.ttf`) a partir de las MISMAS fuentes que sirve la web (`app/static/fonts/*.woff2`, OFL).

Flutter no lee `woff2` ni elige bien el peso en una fuente variable, así que se crean instancias estáticas por peso (Manrope 400/500/600/700, Inter 400/600
como respaldo de los glifos que le falten a Manrope, p. ej. «ŀ» del catalán) recortadas al alfabeto latino que usan es/ca/en/fr. Mantienen la cifra
tabular (`tnum`) para alinear horas e importes.

No forma parte de la aplicación ni de sus tests: se ejecuta a mano si cambian las fuentes de la web. Necesita `fonttools` y `brotli`
(no están en el entorno del servidor):

    python3 -m venv /tmp/fvenv && /tmp/fvenv/bin/pip install fonttools brotli
    /tmp/fvenv/bin/python scripts/exportar_fuentes_movil.py"""
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

RAIZ = Path(__file__).resolve().parent.parent
ORIGEN = RAIZ / "app/static/fonts"
DESTINO = RAIZ / "mobile/assets/fonts"

# Latín básico + Latín-1 + Latín extendido A + puntuación y símbolos de uso común (€, «», comillas, guiones, puntos suspensivos...).
UNICODES = list(range(0x20, 0x7F)) + list(range(0xA0, 0x180)) + list(range(0x2010, 0x2028)) + [0x2030, 0x2039, 0x203A, 0x20AC, 0x2122, 0x2190, 0x2192, 0x2212]

FUENTES = [
    ("ManropeVariable.woff2", "Manrope", {"wght": 400}, "Regular"),
    ("ManropeVariable.woff2", "Manrope", {"wght": 500}, "Medium"),
    ("ManropeVariable.woff2", "Manrope", {"wght": 600}, "SemiBold"),
    ("ManropeVariable.woff2", "Manrope", {"wght": 700}, "Bold"),
    ("InterVariable.woff2", "Inter", {"wght": 400, "opsz": 14}, "Regular"),
    ("InterVariable.woff2", "Inter", {"wght": 600, "opsz": 14}, "SemiBold"),
]


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    opciones = subset.Options()
    opciones.layout_features = ["tnum", "pnum", "kern", "liga", "calt", "locl"]
    opciones.notdef_outline = True
    opciones.flavor = None
    for archivo, familia, ejes, peso in FUENTES:
        f = TTFont(ORIGEN / archivo)
        f = instancer.instantiateVariableFont(f, ejes)
        s = subset.Subsetter(opciones)
        s.populate(unicodes=UNICODES)
        s.subset(f)
        f.flavor = None
        salida = DESTINO / f"{familia}-{peso}.ttf"
        f.save(salida)
        print(f"{salida.relative_to(RAIZ)}  {salida.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
