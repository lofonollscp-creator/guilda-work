#!/usr/bin/env python3
"""Oráculo diferencial del cálculo del 303: sube un LIBRO DE REGISTRO (xlsx LSI, formato oficial de la AEAT) al SIMULADOR PÚBLICO del modelo 303 («Libros de registro» → «Importar libro de registro»), deja que la propia
AEAT calcule las casillas y descarga el `.303` que exporta, del que se leen los valores. Sirve para comparar, casilla a casilla, lo que calcula nuestro motor con lo que calcula la AEAT.

    .venv/bin/python scripts/fiscal/simulador_libros.py libro.xlsx --periodo 2T [--nif A12345674] [--exportar DIR]

Herramienta de DESARROLLO (Playwright + Chromium) que toca un servicio público: datos de PRUEBA, a mano o en una prueba marcada. Código de salida 0 libro aceptado · 1 el simulador lo rechaza · 2 no se pudo usar."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

URL = "https://www2.agenciatributaria.gob.es/wlpl/A303-FWME/E{ejercicio}/OPEN/index.zul"
NIF_PRUEBA = "A12345674"
NOMBRE_PRUEBA = "EMPRESA DE PRUEBA SL"


def _identificarse(pagina, periodo: str, nif: str, nombre: str) -> None:
    modal = pagina.locator(".nvmodal input")
    modal.nth(1).click()
    pagina.wait_for_timeout(500)
    pagina.locator(".z-comboitem:visible").filter(has_text=re.compile(rf"^\s*{periodo}\s*$")).first.click()
    pagina.wait_for_timeout(500)
    modal.nth(2).fill(nif)
    pagina.keyboard.press("Tab")                                        # al salir del NIF se habilita «Razón social» (o «Apellidos y nombre»)
    pagina.wait_for_timeout(2000)
    for i in (4, 3):
        if modal.nth(i).is_enabled():
            modal.nth(i).fill(nombre)
            break
    pagina.get_by_text("Aceptar", exact=True).first.click()
    pagina.wait_for_timeout(3000)


PREGUNTAS = {                                                                  # título del campo en la página de identificación -> respuesta por defecto (SI/NO)
    "Autoliquidación conjunta": "NO", "acogido al régimen especial del criterio de Caja": "NO", "destinatario de operaciones acogidas al régimen especial del criterio de caja": "NO",
    "declarado en concurso": "NO", "acogido voluntariamente al SII": "NO",
}


def _responder_identificacion(pagina, respuestas: dict[str, str]) -> None:
    """Contesta las preguntas habilitadas de «Identificación» (si no, el simulador da PAR018). Las deshabilitadas las rellena él solo."""
    for campo in pagina.query_selector_all("input.z-combobox-input"):
        if not campo.is_visible() or not campo.is_enabled() or campo.get_attribute("value"):
            continue
        titulo = campo.get_attribute("title") or campo.get_attribute("aria-label") or ""
        valor = next((v for k, v in respuestas.items() if k in titulo), None)
        if valor is None:
            continue
        campo.click()
        pagina.wait_for_timeout(500)
        pagina.locator(".z-comboitem:visible").filter(has_text=re.compile(rf"^\s*{valor}\s*$")).first.click()
        pagina.wait_for_timeout(500)


def _mensajes_dialogo(pagina) -> list[str]:
    texto = pagina.locator("[role=dialog]").first.inner_text()
    return [re.sub(r"\s+", " ", l).strip() for l in texto.split("\n") if re.match(r"\s*(\[(Ingreso|Gasto|Inversi)|Fichero validado|N[úu]mero de registros|No se puede|Error)", l)]


def probar(libro: str | Path, *, ejercicio: int = 2026, periodo: str = "2T", nif: str = NIF_PRUEBA, nombre: str = NOMBRE_PRUEBA, exportar_en: str | Path | None = None, espera_s: float = 9.0,
           respuestas: dict[str, str] | None = None) -> dict:
    """{aceptado, mensajes, exportado (ruta del .303 que genera la AEAT), resultado}."""
    from playwright.sync_api import sync_playwright

    res: dict = {"libro": str(libro), "aceptado": False, "mensajes": [], "exportado": None, "resultado": None}
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_context(viewport={"width": 1400, "height": 1100}, locale="es-ES", accept_downloads=True).new_page()
        try:
            pagina.goto(URL.format(ejercicio=ejercicio), wait_until="load", timeout=60000)
            pagina.wait_for_timeout(6000)
            _identificarse(pagina, periodo, nif, nombre)
            pagina.get_by_text("Libros de registro", exact=True).first.click()
            pagina.wait_for_timeout(2500)
            pagina.get_by_text("Importar libro de registro").first.click()
            pagina.wait_for_timeout(2500)
            pagina.query_selector_all("input[type=file]")[-1].set_input_files(str(libro))
            pagina.wait_for_timeout(int(espera_s * 1000))
            res["mensajes"] = _mensajes_dialogo(pagina)
            res["aceptado"] = any(m.startswith("Fichero validado") for m in res["mensajes"]) and not any(m.startswith(("[", "No se puede")) for m in res["mensajes"])
            if not res["aceptado"]:
                return res
            pagina.get_by_text("Aceptar", exact=True).last.click()
            pagina.wait_for_timeout(5000)
            _responder_identificacion(pagina, {**PREGUNTAS, **(respuestas or {})})
            if os.environ.get("GW_DEPURAR"):
                pagina.screenshot(path=os.environ["GW_DEPURAR"] + "/tras_aceptar.png", full_page=True)
            pagina.get_by_text("Seleccionar Ingreso/Devolución").first.click(timeout=8000)
            pagina.wait_for_timeout(2500)
            valor = pagina.evaluate("() => [...document.querySelectorAll('input')].map(i => i.value).filter(v => /^-?[\\d.]+,\\d{2}$/.test(v))[0] || null")
            res["resultado"] = valor
            if valor and valor.startswith("-"):                                  # resultado negativo: por defecto pide devolución (con IBAN); se elige «a compensar», que no necesita más datos
                pagina.locator("[role=dialog]").last.locator("input.z-combobox-input").first.click()
                pagina.wait_for_timeout(500)
                pagina.locator(".z-comboitem:visible").filter(has_text=re.compile("compens", re.I)).first.click()
                pagina.wait_for_timeout(800)
            if os.environ.get("GW_DEPURAR"):
                pagina.screenshot(path=os.environ["GW_DEPURAR"] + "/tras_seleccionar.png", full_page=True)
            if exportar_en:
                with pagina.expect_download(timeout=20000) as d:
                    pagina.locator("[role=dialog]").get_by_text("Exportar", exact=True).first.click()
                destino = Path(exportar_en) / d.value.suggested_filename
                destino.parent.mkdir(parents=True, exist_ok=True)
                d.value.save_as(str(destino))
                res["exportado"] = str(destino)
        finally:
            navegador.close()
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("libro")
    ap.add_argument("--ejercicio", type=int, default=2026)
    ap.add_argument("--periodo", default="2T")
    ap.add_argument("--nif", default=NIF_PRUEBA)
    ap.add_argument("--exportar", metavar="DIR")
    a = ap.parse_args(argv)
    try:
        r = probar(a.libro, ejercicio=a.ejercicio, periodo=a.periodo, nif=a.nif, exportar_en=a.exportar)
    except Exception as e:                                                                    # noqa: BLE001
        print(json.dumps({"error": f"no se pudo usar el simulador: {e}"[:300]}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r["aceptado"] else 1


if __name__ == "__main__":
    sys.exit(main())
