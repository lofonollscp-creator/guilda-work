#!/usr/bin/env python3
"""Mapa por temas de HOSTING.md. La guía crece cronológicamente (cada mejora añade su sección); el bloque entre
`<!-- INDICE -->` y `<!-- /INDICE -->` la ordena por temas. `python scripts/indice_hosting.py` lo regenera y
`--comprobar` falla si alguna sección `##` no está en el mapa (lo usa tests/test_calidad_documentacion.py)."""
import re
import sys
from pathlib import Path

RUTA = Path(__file__).resolve().parent.parent / "HOSTING.md"
INICIO, FIN = "<!-- INDICE -->", "<!-- /INDICE -->"

# (tema, [prefijos de título]) — el orden de los temas es el de lectura; una sección nueva sin tema cae en «Otros».
TEMAS = [
    ("Poner el servidor en marcha", ["Elegir proveedor", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "Dimensionar", "Migrar de sslip.io"]),
    ("Resto del stack y copias de seguridad", ["8.", "9.", "Copia de seguridad con Restic"]),
    ("Producto y operación (backoffice)", ["Backoffice independiente", "Comunicados", "Modo mantenimiento", "Puesta en marcha guiada", "Tope de consumo"]),
    ("API, MCP y seguridad de acceso", ["10.", "API ", "API:", "Estado del servicio", "Revisión de seguridad", "Política de contenido", "Tokens de API", "Fase 0 de OAuth2", "Hydra sin", "MCP:", "OpenAPI", "SDK "]),
    ("Documentación y ayuda", ["Ayuda contextual"]),
    ("Otros", ["Fuera de alcance"]),
]


def anchor(titulo: str) -> str:
    """Ancla al estilo GitHub: minúsculas, sin signos, espacios a guiones."""
    t = titulo.strip().lower().replace("`", "")
    t = re.sub(r"[^\w\s-]", "", t, flags=re.UNICODE)
    return re.sub(r"\s", "-", t)


def secciones(texto: str) -> list[str]:
    """Títulos `## ` fuera de los bloques de código."""
    salida, dentro = [], False
    for linea in texto.splitlines():
        if linea.startswith("```"):
            dentro = not dentro
        elif not dentro and linea.startswith("## "):
            salida.append(linea[3:].strip())
    return salida


def tema_de(titulo: str) -> str:
    for tema, prefijos in TEMAS:
        if any(titulo.startswith(p) for p in prefijos):
            return tema
    return "Otros"


def construir(texto: str) -> str:
    por_tema: dict[str, list[str]] = {t: [] for t, _ in TEMAS}
    for s in secciones(texto):
        por_tema[tema_de(s)].append(s)
    lineas = [INICIO, "## Mapa por temas", "", "Esta guía está en orden cronológico; aquí está ordenada por temas.", ""]
    for tema, titulos in por_tema.items():
        if titulos:
            lineas.append(f"**{tema}**")
            lineas += [f"- [{t}](#{anchor(t)})" for t in titulos if t != "Mapa por temas"]
            lineas.append("")
    lineas.append(FIN)
    return "\n".join(lineas)


def main(comprobar: bool) -> int:
    texto = RUTA.read_text(encoding="utf-8")
    sin_bloque = re.sub(rf"{re.escape(INICIO)}.*?{re.escape(FIN)}\n*", "", texto, flags=re.S)
    nuevo = construir(sin_bloque)
    bloque = f"{nuevo}\n"
    # El mapa va justo después de la introducción (antes de la primera sección).
    primera = sin_bloque.index("\n## ") + 1
    resultado = sin_bloque[:primera] + bloque + "\n" + sin_bloque[primera:]
    if comprobar:
        if resultado != texto:
            print("El mapa por temas de HOSTING.md está desactualizado: ejecuta python scripts/indice_hosting.py")
            return 1
        return 0
    RUTA.write_text(resultado, encoding="utf-8")
    print("Mapa por temas actualizado.")
    return 0


if __name__ == "__main__":
    sys.exit(main("--comprobar" in sys.argv))
