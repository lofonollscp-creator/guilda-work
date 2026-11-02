"""Documentos para firmar (app/documentos_firma.py): repasa los envíos pendientes en Documenso y anota (y avisa) los que ya se han firmado o rechazado. Es el RESPALDO del webhook
(`/webhooks/documenso`): corre cada media hora vía deploy/sincronizar-firmas.timer/.service.

Uso:
    .venv/bin/python scripts/sincronizar_firmas.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import documentos_firma, salud  # noqa: E402


def main() -> None:
    try:
        r = documentos_firma.sincronizar_pendientes()
    except Exception as e:
        salud.registrar_error("firmas_documenso", 2 * 3600, f"{type(e).__name__}: {e}")
        raise
    salud.registrar_ok("firmas_documenso", 2 * 3600, f"{r['revisados']} revisado(s), {r['firmados']} firmado(s), {r['rechazados']} rechazado(s)")
    print(f"Firmas: revisados {r['revisados']}; firmados {r['firmados']}; rechazados {r['rechazados']}")


if __name__ == "__main__":
    main()
