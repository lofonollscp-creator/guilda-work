"""Marketing del Comercial (app/marketing.py): lee el buzón donde llegan los rebotes (`MARKETING_IMAP_*`) y trae de Brevo y Mailchimp las bajas y los rebotes; deja como «rebotados» o «de baja» los correos afectados.
Corre cada 15 minutos vía deploy/procesar-rebotes.timer/.service. Sin las variables no hace nada y lo dice.

Uso:
    .venv/bin/python scripts/procesar_rebotes.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import marketing, salud  # noqa: E402


def main() -> None:
    try:
        r = marketing.revisar_buzon_de_rebotes()
        p = marketing.sincronizar_proveedores()
    except Exception as e:
        salud.registrar_error("marketing_rebotes", 3600, f"{type(e).__name__}: {e}")
        raise
    if r.get("sin_buzon"):
        print("Buzón de rebotes sin configurar (MARKETING_IMAP_*): no se lee nada.")
    else:
        print(f"Rebotes: mensajes leídos {r['leidos']}; rebotes registrados {r['rebotes']}")
    print(f"Proveedores: envíos revisados {p['envios']}; bajas {p['bajas']}; rebotes {p['rebotes']}; con error {p['errores']}")
    salud.registrar_ok("marketing_rebotes", 3600, f"{r.get('leidos', 0)} mensaje(s) leído(s), {r.get('rebotes', 0)} rebote(s); proveedores: {p['bajas']} baja(s), {p['rebotes']} rebote(s)")


if __name__ == "__main__":
    main()
