"""Registra un cliente OAuth2 en Ory Hydra (Fase 7b) — uso puntual, una vez
por herramienta externa que necesite iniciar sesión "con Guilda Work"
(Outline primero, OpenProject más adelante).

Uso:
    python scripts/registrar_cliente_hydra.py --nombre outline \
        --redirect-uri http://127.0.0.1:3001/auth/oidc.callback

Imprime `client_id`/`client_secret` una única vez (Hydra no vuelve a
mostrar el secreto después) — cópialos directamente a las variables de
entorno de la herramienta correspondiente en `docker-compose.yml`.

Requiere Hydra levantado (`docker compose up -d hydra`) y alcanzable en
`app.hydra.HYDRA_ADMIN_URL`."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import hydra  # noqa: E402


def registrar(nombre: str, redirect_uri: str) -> None:
    try:
        cuerpo = hydra.registrar_cliente(nombre, redirect_uri)
    except hydra.ErrorHydra as e:
        print(f"Error registrando el cliente: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Cliente '{nombre}' registrado en Hydra.")
    print(f"  client_id:     {cuerpo['client_id']}")
    print(f"  client_secret: {cuerpo['client_secret']}")
    print("\n(el secreto no se vuelve a mostrar — guárdalo ahora)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nombre", required=True, help="Nombre del cliente (p.ej. 'outline')")
    parser.add_argument("--redirect-uri", required=True, help="Redirect URI de callback OAuth2 de la herramienta")
    args = parser.parse_args()
    registrar(args.nombre, args.redirect_uri)
