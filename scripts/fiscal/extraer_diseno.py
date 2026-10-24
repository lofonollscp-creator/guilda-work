#!/usr/bin/env python3
"""Genera `app/fiscal_modelos/disenos/<modelo>_<ejercicio>_<revisión>.json` a partir del diseño de registro OFICIAL de la AEAT (xlsx) y lo verifica.

    python scripts/fiscal/extraer_diseno.py docs/fuentes-oficiales/aeat/DR303e26v101.xlsx app/fiscal_modelos/disenos/303_2026_v101.json

Código de salida: 0 coherente · 1 incoherencias en el propio diseño. No escribe nada si el diseño es incoherente."""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))


def main(argv=None) -> int:
    from app.fiscal_modelos import disenos_oficiales as d

    a = sys.argv[1:] if argv is None else argv
    if len(a) != 2:
        print(__doc__)
        return 2
    diseno = d.leer_diseno(a[0])
    problemas = d.comprobar(diseno)
    if problemas:
        print("El diseño oficial no es coherente consigo mismo:\n  " + "\n  ".join(problemas), file=sys.stderr)
        return 1
    Path(a[1]).write_text(json.dumps(diseno, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    campos = sum(len(p["campos"]) for p in diseno["paginas"])
    print(f"{a[1]}: {len(diseno['paginas'])} hojas, {campos} campos, sha256 {diseno['origen']['sha256'][:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
