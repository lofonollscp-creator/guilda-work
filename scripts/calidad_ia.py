#!/usr/bin/env python3
"""Evalúa a la vez la lectura de facturas y el asistente con el modelo configurado (AA7) y deja el resultado en data/backups/calidad_ia_estado.json para el panel Salud.
No cuenta en el límite mensual de IA. Usa la IA de la persona GUILDA_EVAL_USUARIO (por defecto 2). Lo lanza deploy/calidad-ia.timer cada semana; a mano necesita /etc/guilda-work.env.

  scripts/calidad_ia.py [--usuario N] [--salida RUTA.json]"""
import argparse
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
EVALS = RAIZ / "tests" / "evals"


def _json(ruta: Path):
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--usuario", type=int, default=int(os.environ.get("GUILDA_EVAL_USUARIO", "2")))
    ap.add_argument("--salida", default=str(RAIZ / "data" / "backups" / "calidad_ia_estado.json"))
    a = ap.parse_args()
    from app import calidad_ia, evals_asistente, evals_facturas, ia_asistente
    modelo = (ia_asistente.candidatos(a.usuario, "asistente") or [{}])[0].get("modelo", "")
    with ia_asistente.sin_consumo():
        r_asistente = evals_asistente.ejecutar(evals_asistente.cargar_casos(), evals_asistente.elegir_con_ia(a.usuario))
        r_facturas = evals_facturas.ejecutar(evals_facturas.cargar_casos(), evals_facturas.leer_con_ia(a.usuario))
    estado = calidad_ia.resumir(r_asistente, r_facturas, _json(EVALS / "base_asistente.json"), _json(EVALS / "base_nvidia-nemotron-free_2026-11-11.json"), modelo)
    estado = calidad_ia.con_historial(estado, _json(Path(a.salida)))
    Path(a.salida).parent.mkdir(parents=True, exist_ok=True)
    Path(a.salida).write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Asistente {estado['asistente']['acierto_global']} % (inyección {estado['inyeccion']} %) · Facturas {estado['facturas']['acierto_global']} % · modelo {modelo or '?'}")
    for r in estado["regresiones"]:
        print("REGRESIÓN:", r)
    for n in estado["inconclusas"]:
        print(f"INCONCLUSA ({n}): demasiados casos sin respuesta del proveedor")
    return 1 if estado["regresiones"] else 0


if __name__ == "__main__":
    sys.exit(main())
