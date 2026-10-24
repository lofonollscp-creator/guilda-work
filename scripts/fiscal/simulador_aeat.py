#!/usr/bin/env python3
"""Valida un fichero `.303` contra el SIMULADOR PÚBLICO del modelo 303 de la AEAT (sin certificado) y, si se pide, descarga lo que el propio formulario exporta de vuelta para compararlo byte a byte.

    .venv/bin/python scripts/fiscal/simulador_aeat.py fichero.303 [--exportar DIR] [--ejercicio 2026]

Es una herramienta de DESARROLLO (necesita Playwright + Chromium: `requirements-e2e.txt`) y toca un servicio público de la AEAT: se usa a mano o en una prueba marcada, nunca en cada ejecución de la suite, y siempre
con datos de PRUEBA. No presenta nada: el simulador (OPEN) no tiene presentación. Qué hace: abre el simulador → «Importar» → sube el fichero → recoge los errores/avisos de la importación → «Validar» → recoge
los de la validación → con `--exportar`, pulsa «Seleccionar Ingreso/Devolución» → «Exportar» y guarda el `.303` que genera la AEAT.

Salida: JSON con `importacion` (rechazado o no, errores), `validacion` (errores y avisos con su código), `resultado` (importe que calcula la AEAT) y, con `--exportar`, `exportado` (ruta). Código de salida:
0 importado y validado sin errores · 1 hay errores · 2 no se pudo usar el simulador."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

URL = "https://www2.agenciatributaria.gob.es/wlpl/A303-FWME/E{ejercicio}/OPEN/index.zul"
CODIGO = re.compile(r"^(?:[EW]\d{6}|\d{5}|[A-Z]{3,6}\d{0,3}|PAR\d+|FRECH|\d{3}M\d{3})$")

JS_FILAS = """() => [...document.querySelectorAll('tr')].map(tr => [...tr.children].map(c => (c.innerText || '').replace(/\\s+/g, ' ').trim())).filter(c => c.length >= 3)"""


def _mensajes(pagina) -> list[dict]:
    """Las filas de la tabla «Errores y avisos»: `{linea, codigo, descripcion, gravedad}`; la gravedad sale del icono (aviso/error/correcto) cuando se puede."""
    out = []
    for celdas in pagina.evaluate(JS_FILAS):
        util = [c for c in celdas if c]
        for i, c in enumerate(util):
            if CODIGO.match(c) and i + 1 < len(util) and len(util[i + 1]) > 8:
                linea = util[i - 1] if i > 0 and re.fullmatch(r"-|\d+", util[i - 1]) else ""
                out.append({"linea": linea, "codigo": c, "descripcion": util[i + 1]})
                break
    vistos, unicos = set(), []
    for m in out:
        k = (m["codigo"], m["descripcion"])
        if k not in vistos:
            vistos.add(k)
            unicos.append(m)
    return unicos


def probar(fichero: str | Path, *, ejercicio: int = 2026, exportar_en: str | Path | None = None, espera_s: float = 5.0) -> dict:
    from playwright.sync_api import sync_playwright

    resultado: dict = {"fichero": str(fichero), "importacion": {}, "validacion": [], "resultado": None, "exportado": None}
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_context(viewport={"width": 1400, "height": 1100}, locale="es-ES", accept_downloads=True).new_page()
        try:
            pagina.goto(URL.format(ejercicio=ejercicio), wait_until="load", timeout=60000)
            pagina.wait_for_timeout(int(espera_s * 1000))
            pagina.get_by_text("Importar", exact=True).first.click()
            pagina.wait_for_timeout(2000)
            pagina.query_selector("input[type=file]").set_input_files(str(fichero))
            pagina.wait_for_timeout(int(espera_s * 1000))
            importacion = _mensajes(pagina)
            rechazado = any(m["codigo"] == "FRECH" for m in importacion)
            resultado["importacion"] = {"rechazado": rechazado, "mensajes": importacion}
            if rechazado or any(m["codigo"].startswith("E") for m in importacion):
                return resultado
            try:
                pagina.get_by_text("Volver a la página principal").first.click(timeout=1500)
            except Exception:                                                                # noqa: BLE001
                pass
            pagina.get_by_text("Validar", exact=True).first.click(timeout=8000)
            pagina.wait_for_timeout(int(espera_s * 1000 * 0.8))
            resultado["validacion"] = _mensajes(pagina)
            pagina.get_by_text("Seleccionar Ingreso/Devolución").first.click(timeout=8000)
            pagina.wait_for_timeout(2500)
            m = re.search(r"Resultado\s*([-\d.,]+)", pagina.inner_text("body"))
            valor = pagina.evaluate("() => [...document.querySelectorAll('input')].map(i => i.value).filter(v => /^-?[\\d.]+,\\d{2}$/.test(v))[0] || null")
            resultado["resultado"] = valor or (m.group(1) if m else None)
            if exportar_en:
                with pagina.expect_download(timeout=20000) as d:
                    pagina.get_by_text("Exportar", exact=True).first.click()
                destino = Path(exportar_en) / d.value.suggested_filename
                destino.parent.mkdir(parents=True, exist_ok=True)
                d.value.save_as(str(destino))
                resultado["exportado"] = str(destino)
        finally:
            navegador.close()
    return resultado


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fichero")
    ap.add_argument("--ejercicio", type=int, default=2026)
    ap.add_argument("--exportar", metavar="DIR", help="guarda aquí el .303 que exporta el propio simulador")
    a = ap.parse_args(argv)
    try:
        r = probar(a.fichero, ejercicio=a.ejercicio, exportar_en=a.exportar)
    except Exception as e:                                                                    # noqa: BLE001
        print(json.dumps({"error": f"no se pudo usar el simulador: {e}"[:300]}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(r, ensure_ascii=False, indent=1))
    errores = [m for m in r["importacion"].get("mensajes", []) + r["validacion"] if m["codigo"].startswith(("E", "FRECH")) or "M0" in m["codigo"]]
    return 1 if (r["importacion"].get("rechazado") or errores) else 0


if __name__ == "__main__":
    sys.exit(main())
