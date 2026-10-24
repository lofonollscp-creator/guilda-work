#!/usr/bin/env python3
"""Graba el resultado de la AEAT para cada escenario de `tests/escenarios_303.py`: escribe el libro, lo sube al simulador público, exporta el `.303` que calcula la AEAT y guarda sus casillas en
`tests/fixtures/aeat/oraculo_libros/<escenario>.json`. Tarda ~1 min por escenario. Datos de PRUEBA (NIF A12345674).

    .venv/bin/python scripts/fiscal/grabar_oraculo.py [escenario ...] [--forzar]"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts" / "fiscal"))

DESTINO = RAIZ / "tests" / "fixtures" / "aeat" / "oraculo_libros"


def main(argv=None) -> int:
    from app.fiscal_modelos import exportador_303 as ex
    from app.fiscal_modelos.libros_lsi import escribir_xlsx
    from tests.escenarios_303 import ESCENARIOS
    import simulador_libros as sl
    args = [a for a in (argv or sys.argv[1:]) if not a.startswith("--")]
    forzar = "--forzar" in (argv or sys.argv[1:])
    diseno = json.loads(ex.DISENO_303_2026.read_text(encoding="utf-8"))
    DESTINO.mkdir(parents=True, exist_ok=True)
    fallos = 0
    for nombre, (apuntes, ejercicio, periodo) in ESCENARIOS.items():
        if args and nombre not in args:
            continue
        fichero = DESTINO / f"{nombre}.json"
        if fichero.exists() and (DESTINO / f"{nombre}.303").exists() and not forzar:
            continue
        with tempfile.TemporaryDirectory(prefix="gw-oraculo-") as tmp:
            libro = Path(tmp) / f"{nombre}.xlsx"
            libro.write_bytes(escribir_xlsx(apuntes, ejercicio=ejercicio, periodo=periodo))
            try:
                r = sl.probar(libro, ejercicio=ejercicio, periodo=periodo, exportar_en=tmp)
            except Exception as e:                                                  # noqa: BLE001
                print(f"{nombre}: no se pudo usar el simulador: {str(e)[:150]}")
                fallos += 1
                continue
            if not r["aceptado"]:
                print(f"{nombre}: el simulador rechaza el libro: {r['mensajes']}")
                fallos += 1
                continue
            exportado = Path(r["exportado"]).read_bytes()
            casillas = ex.leer_casillas(diseno, exportado)
            (DESTINO / f"{nombre}.303").write_bytes(exportado)
        fichero.write_text(json.dumps({"escenario": nombre, "ejercicio": ejercicio, "periodo": periodo, "resultado": r["resultado"], "casillas": casillas}, indent=1, sort_keys=True) + "\n")
        print(f"{nombre}: resultado {r['resultado']} · {len(casillas)} casillas")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
