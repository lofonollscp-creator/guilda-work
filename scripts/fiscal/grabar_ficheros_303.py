#!/usr/bin/env python3
"""Importa en el SIMULADOR PÚBLICO de la AEAT cada fichero de `tests/escenarios_ficheros_303.py`, lo valida y guarda nuestro fichero y el que exporta el simulador en
`tests/fixtures/aeat/ficheros_303/{nuestro,aeat}/<nombre>.303` (más el resultado y los mensajes en `<nombre>.json`). Datos de PRUEBA (NIF A12345674). Tarda ~1 min por fichero.

    .venv/bin/python scripts/fiscal/grabar_ficheros_303.py [nombre ...] [--forzar]"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts" / "fiscal"))
DESTINO = RAIZ / "tests" / "fixtures" / "aeat" / "ficheros_303"


def main(argv=None) -> int:
    import simulador_aeat as sa
    from tests.escenarios_ficheros_303 import CASOS
    args = [a for a in (argv or sys.argv[1:]) if not a.startswith("--")]
    forzar = "--forzar" in (argv or sys.argv[1:])
    for sub in ("nuestro", "aeat"):
        (DESTINO / sub).mkdir(parents=True, exist_ok=True)
    fallos = 0
    for nombre, construir in CASOS.items():
        if args and nombre not in args:
            continue
        if (DESTINO / "aeat" / f"{nombre}.303").exists() and not forzar:
            continue
        nuestro = construir()
        with tempfile.TemporaryDirectory(prefix="gw-ficheros-") as tmp:
            ruta = Path(tmp) / f"{nombre}.303"
            ruta.write_bytes(nuestro)
            try:
                r = sa.probar(ruta, exportar_en=tmp, espera_s=10.0)
            except Exception as e:                                                  # noqa: BLE001
                print(f"{nombre}: no se pudo usar el simulador: {str(e)[:150]}")
                fallos += 1
                continue
            errores = [m for m in r["importacion"].get("mensajes", []) + r["validacion"] if m["codigo"] != "00001" and not m["codigo"].startswith(("30", "31"))]       # 30xxx y 31xxx son avisos («revise…»); el resto, errores
            if r["importacion"].get("rechazado") or errores or not r["exportado"]:
                print(f"{nombre}: el simulador NO lo acepta: {errores or r['importacion']}")
                fallos += 1
                continue
            (DESTINO / "aeat" / f"{nombre}.303").write_bytes(Path(r["exportado"]).read_bytes())
        (DESTINO / "nuestro" / f"{nombre}.303").write_bytes(nuestro)
        avisos = sorted({f"{m['codigo']} {m['descripcion']}" for m in r["validacion"] if m["codigo"] != "00001"})
        (DESTINO / f"{nombre}.json").write_text(json.dumps({"fichero": nombre, "resultado_aeat": r["resultado"], "avisos": avisos}, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{nombre}: aceptado · resultado {r['resultado']} · {len(avisos)} avisos")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
