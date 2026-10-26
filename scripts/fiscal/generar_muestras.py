#!/usr/bin/env python3
"""Genera libros registro de PRUEBA (.xlsx, formato AEAT) para probar Guilda Fiscal desde la pantalla «Importar un libro registro», con el resultado que debe dar el 303 (el que calcula la propia AEAT).

    .venv/bin/python scripts/fiscal/generar_muestras.py docs/muestras-fiscal

Todo es inventado (NIF de prueba A12345674, contrapartes ficticias). Escribe un `.xlsx` por escenario y un `LEEME.md` con las casillas esperadas de cada uno."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

ELEGIDOS = {
    "basico": "Una venta de 100 € al 21 % y una compra de 50 € al 21 %.",
    "tipos": "Ventas al 4 %, 10 % y 21 %.",
    "rectificativas": "Ventas, un abono (R1) y una compra rectificada: casillas 14 y 15, y 40 y 41.",
    "otros_trimestres": "Facturas de 1T, 2T y 3T: el 303 del 2T solo cuenta las suyas.",
    "bien_inversion": "Una compra de un bien de inversión (casillas 30 y 31).",
    "adquisicion_intracomunitaria": "Compra a un proveedor francés (se devenga y se deduce: casillas 10, 11, 36 y 37).",
    "inversion_sujeto_pasivo": "Compra con inversión del sujeto pasivo (casillas 12, 13, 28 y 29).",
    "alquiler_local_comercial": "Alquiler de un local de negocio al 21 % con referencia catastral, y su gasto.",
    "alquiler_vivienda_exento": "Alquiler de vivienda exento (no entra en la cuota) junto a una venta normal.",
    "alquiler_turistico_al_10": "Alquiler turístico (servicio de hospedaje) al 10 %.",
    "resultado_negativo": "Más IVA soportado que repercutido: sale a favor.",
}
CASILLAS_CLAVE = ("07", "09", "01", "03", "04", "06", "10", "11", "12", "13", "14", "15", "27", "28", "29", "30", "31", "36", "37", "40", "41", "45", "46", "59", "60", "120", "122", "71")


def main(argv=None) -> int:
    from app.fiscal_modelos.libros_lsi import escribir_xlsx
    from tests.escenarios_303 import ESCENARIOS
    destino = Path((argv or sys.argv[1:] or ["muestras-fiscal"])[0])
    destino.mkdir(parents=True, exist_ok=True)
    oraculo = RAIZ / "tests" / "fixtures" / "aeat" / "oraculo_libros"
    lineas = ["# Libros de prueba para Guilda Fiscal", "",
              "Todo inventado. Crea un titular de prueba con NIF **A12345674** (nombre «Empresa de prueba SL»), dale un **perfil fiscal** (sociedad, régimen general, trimestral, vigente desde 2026-01-01) y, en su ficha, "
              "usa **Importar un libro registro** con cada fichero. Después **Calcular un periodo** (ejercicio 2026, periodo 2T) y compara con lo esperado: es lo que calcula la propia AEAT con ese mismo libro.", "",
              "| Fichero | Qué prueba | Casillas esperadas (2T 2026) | Resultado (casilla 71) |", "|---|---|---|---|"]
    for nombre, que in ELEGIDOS.items():
        apuntes, ejercicio, periodo = ESCENARIOS[nombre]
        (destino / f"{nombre}.xlsx").write_bytes(escribir_xlsx(apuntes, ejercicio=ejercicio, periodo=periodo))
        g = json.loads((oraculo / f"{nombre}.json").read_text())
        esperadas = " · ".join(f"[{k}] {g['casillas'][k] / 100:.2f}" for k in CASILLAS_CLAVE if k in g["casillas"] and k != "71")
        lineas.append(f"| `{nombre}.xlsx` | {que} | {esperadas} | **{g['casillas'].get('71', 0) / 100:.2f} €** |")
    lineas += ["", "Nota: los libros están pensados para **un solo titular de prueba cada vez** (se importan sobre apuntes vacíos). Para repetir con otro fichero, crea otro titular de prueba o anula los apuntes anteriores.",
               "Una fila idéntica a otra ya aprobada no se duplica. El 4T no se prueba todavía (la AEAT no lo permite hasta enero de 2027)."]
    (destino / "LEEME.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"{len(ELEGIDOS)} libros en {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
