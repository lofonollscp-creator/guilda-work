#!/usr/bin/env python3
"""Evalúa si el asistente elige la herramienta correcta a la primera y si resiste órdenes escondidas en un correo (Z5). Usa la clave de IA real de la persona
indicada (unas 30 consultas pequeñas) y el catálogo REAL de herramientas. Con --base falla (código 1) si algo ha empeorado.

  scripts/evaluar_asistente.py --usuario 2 --salida eval-asistente.json
  scripts/evaluar_asistente.py --usuario 2 --base eval-asistente.json --margen 3
  scripts/evaluar_asistente.py --usuario 2 --modelo otro/modelo        # compara otro modelo del mismo proveedor
"""
import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--usuario", type=int, required=True)
    ap.add_argument("--casos")
    ap.add_argument("--salida")
    ap.add_argument("--base")
    ap.add_argument("--modelo")
    ap.add_argument("--margen", type=float, default=2.0)
    a = ap.parse_args()
    from app import evals_asistente as ev, ia_asistente, ia_herramientas
    casos = ev.cargar_casos(a.casos)
    problemas = ev.validar_casos(casos)
    if problemas:
        print("Casos no válidos:\n  " + "\n  ".join(problemas))
        return 2
    if a.modelo:
        original = ia_asistente.candidatos
        ia_asistente.candidatos = lambda uid, tarea: [{**c, "modelo": a.modelo} for c in original(uid, tarea)][:1]

    def elegir(caso: dict):
        mensajes = [{"role": "system", "content": ia_asistente._prompt_sistema(a.usuario, "es")}, {"role": "user", "content": caso["pregunta"]}]
        if caso["tipo"] == "inyeccion":
            tid = "call_previa"
            mensajes += [{"role": "assistant", "content": None, "tool_calls": [{"id": tid, "type": "function", "function": {"name": caso["herramienta_previa"], "arguments": "{}"}}]},
                         {"role": "tool", "tool_call_id": tid, "content": caso["resultado_previo"]}]
        respuesta = ia_asistente._llamar(a.usuario, "asistente", {"messages": mensajes, "tools": ia_herramientas.herramientas_para(mensajes, False)})
        llamadas = respuesta["choices"][0]["message"].get("tool_calls") or []
        return llamadas[0]["function"]["name"] if llamadas else None
    r = ev.ejecutar(casos, elegir)
    print(f"Acierto global: {r['acierto_global']} %  ({r['casos']} casos, {r['segundos_medios']} s de media)")
    for t, p in r["por_tipo"].items():
        print(f"  {t:16} {p:5.1f} %")
    for f in r["fallos"]:
        print(f"  ✗ {f['caso']}: esperaba {f['esperadas'] or f['tipo']}, eligió {f['elegida']}")
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
