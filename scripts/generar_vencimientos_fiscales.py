"""Recurrencia automática del calendario fiscal (Fase F4 de la ampliación,
ver /Users/jvelasco/.claude/plans/eventual-herding-kitten.md) -- pensado
para correr a diario vía el timer systemd
deploy/vencimientos-fiscales.timer/.service, NO como hilo dentro de
serve.py (a diferencia de _recordatorio_vencimientos_fiscales en
app/main.py, que sigue siendo el hilo que manda los pushes).

Uso:
    .venv/bin/python scripts/generar_vencimientos_fiscales.py

No necesita ningún parámetro: recorre TODOS los tenants, genera lo que
falte para los clientes con `generacion_automatica` activado (opt-in,
apagado por defecto) y sanea el estado `fuera_plazo`. Idempotente --
ejecutarlo varias veces seguidas no duplica nada (ver
db.generar_vencimientos_automaticos()).

Requiere las mismas variables de entorno que serve.py (lee
/etc/guilda-work.env vía EnvironmentFile= en el .service, ver
deploy/vencimientos-fiscales.service) -- no hace falta que este script
cargue ningún .env por su cuenta, igual que scripts/reindexar_embeddings.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402


def main() -> None:
    creados = db.generar_vencimientos_automaticos()
    saneados = db.sanear_vencimientos_fuera_plazo()
    print(f"Vencimientos fiscales generados automáticamente: {creados}")
    print(f"Vencimientos marcados fuera de plazo: {saneados}")


if __name__ == "__main__":
    main()
