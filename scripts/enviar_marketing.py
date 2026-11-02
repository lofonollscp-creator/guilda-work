"""Envíos de marketing del Comercial (app/marketing.py): manda los correos de los envíos programados, por lotes. Pensado para correr cada pocos minutos vía el timer systemd
deploy/marketing-envios.timer/.service.

Uso:
    .venv/bin/python scripts/enviar_marketing.py

Sin las variables MARKETING_SMTP_* (canal saliente propio, distinto del de los avisos del portal) no envía nada y lo dice. Antes de cada correo vuelve a comprobar el consentimiento."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import marketing, salud  # noqa: E402


def main() -> None:
    try:
        r = marketing.procesar_pendientes()
    except Exception as e:
        salud.registrar_error("marketing_envios", 3600, f"{type(e).__name__}: {e}")
        raise
    if r.get("sin_canal"):
        print("Canal de marketing sin configurar (MARKETING_SMTP_*): no se envía nada.")
        return
    salud.registrar_ok("marketing_envios", 3600, f"{r['enviados']} enviado(s), {r['errores']} con error, {r['omitidos']} omitido(s)")
    print(f"Marketing: enviados {r['enviados']}; con error {r['errores']}; omitidos {r['omitidos']}")


if __name__ == "__main__":
    main()
