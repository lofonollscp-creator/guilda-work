#!/usr/bin/env python3
"""Evalúa cuánto acierta la lectura de facturas con el modelo configurado (W8). Manda los casos SINTÉTICOS de tests/evals/facturas_casos.json al proveedor que use la persona indicada, mide el acierto por campo y,
con --base, falla (código 1) si algo ha empeorado respecto a una evaluación anterior. Usa la clave de IA real: cuesta unas pocas consultas.

  scripts/evaluar_facturas.py --usuario 1 --salida eval-gpt4omini.json
  scripts/evaluar_facturas.py --usuario 1 --base eval-gpt4omini.json --margen 2
  scripts/evaluar_facturas.py --usuario 1 --modelo meta-llama/llama-3.3-70b-instruct:free   # compara otro modelo con la misma clave
"""
import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--usuario", type=int, required=True, help="id de la persona cuya configuración de IA se usa")
    ap.add_argument("--casos", help="otro fichero de casos (por defecto tests/evals/facturas_casos.json)")
    ap.add_argument("--salida", help="guarda el resultado en este fichero JSON")
    ap.add_argument("--base", help="evaluación anterior con la que comparar")
    ap.add_argument("--modelo", help="evalúa este modelo del proveedor de la persona (sin tocar su configuración) en vez del suyo; sirve para comparar modelos")
    ap.add_argument("--margen", type=float, default=2.0, help="puntos de bajada tolerados (por defecto 2)")
    a = ap.parse_args()
    from app import evals_facturas as ev, ia_asistente, lectura_facturas
    casos = ev.cargar_casos(a.casos)
    if a.modelo:
        original = ia_asistente.candidatos
        ia_asistente.candidatos = lambda uid, tarea: [{**c, "modelo": a.modelo} for c in original(uid, tarea)][:1]

    def leer(texto: str) -> dict:
        return lectura_facturas._json_de(ia_asistente.completar_partes(a.usuario, lectura_facturas.PROMPT_TEXTO, [{"type": "text", "text": "Extrae los datos de esta factura.\n\nTEXTO DEL DOCUMENTO:\n" + texto}]))
    r = ev.ejecutar(casos, leer)
    print(f"Acierto global: {r['acierto_global']} %  ({r['casos']} casos)")
    for campo, p in r["por_campo"].items():
        print(f"  {campo:14} {p:5.1f} %")
    for f in r["fallos"]:
        print(f"  ✗ {f['caso']}: {', '.join(f['campos'])}")
    for e in r["errores"]:
        print(f"  ! {e['caso']}: {e['error']}")
    if a.salida:
        Path(a.salida).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.base:
        peores = ev.comparar(r, json.loads(Path(a.base).read_text(encoding="utf-8")), a.margen)
        if peores:
            print("REGRESIÓN respecto a la base:\n  " + "\n  ".join(peores))
            return 1
        print("Sin regresión respecto a la base.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
