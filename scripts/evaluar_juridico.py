#!/usr/bin/env python3
"""Evalúa la RECUPERACIÓN del asistente jurídico con un conjunto anotado por un profesional (ver app/juridico/evaluacion.py y docs/asistente-juridico-piloto.md).

    .venv/bin/python scripts/evaluar_juridico.py conjunto.json --despacho 3 [--revision salida.json --usuario 5]

Solo LEE la base de datos (la recuperación); con --revision lanza las consultas con el modelo del usuario indicado y escribe las respuestas con la hoja de puntuación en blanco. No lo ejecutes contra la
base de producción sin avisar: --revision gasta consultas de IA."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.juridico import evaluacion, modulo  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("conjunto")
    p.add_argument("--despacho", type=int, required=True)
    p.add_argument("--revision", help="fichero de salida con las respuestas para que las puntúe una persona")
    p.add_argument("--usuario", type=int)
    a = p.parse_args()
    casos = evaluacion.cargar(a.conjunto)
    print(json.dumps(evaluacion.recuperacion(a.despacho, casos, embedder=modulo.embedder()), ensure_ascii=False, indent=2))
    if a.revision:
        if not a.usuario:
            p.error("--revision necesita --usuario")
        Path(a.revision).write_text(json.dumps(evaluacion.respuestas_para_revision(a.despacho, a.usuario, casos, embedder=modulo.embedder()), ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
