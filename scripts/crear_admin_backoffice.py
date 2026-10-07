"""Crea (o cambia la contraseña de) un administrador del backoffice.

    .venv/bin/python scripts/crear_admin_backoffice.py USUARIO [--nombre "Nombre"] [--cambiar]

Sin --contrasena, genera una contraseña aleatoria y la muestra UNA vez por
pantalla (no se guarda en claro en ningún sitio: solo su hash en
data/backoffice.db)."""
import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backoffice import auth  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("usuario")
    parser.add_argument("--nombre")
    parser.add_argument("--cambiar", action="store_true", help="cambia la contraseña de un administrador existente")
    parser.add_argument("--quitar-2fa", action="store_true", help="desactiva el segundo factor de ese administrador (si ha perdido el móvil y los códigos)")
    parser.add_argument("--contrasena", help="contraseña a usar (si se omite, se genera una aleatoria)")
    args = parser.parse_args()
    if args.quitar_2fa:
        conn = auth.conectar()
        try:
            admin = conn.execute("SELECT id FROM admins WHERE usuario = ?", (args.usuario.strip().lower(),)).fetchone()
        finally:
            conn.close()
        if admin is None:
            print("No existe ese administrador.", file=sys.stderr)
            return 1
        auth.desactivar_2fa(admin["id"])
        print("Segundo factor desactivado.")
        return 0
    contrasena = args.contrasena or secrets.token_urlsafe(18)
    try:
        if args.cambiar:
            if not auth.cambiar_contrasena(args.usuario, contrasena):
                print("No existe ese administrador.", file=sys.stderr)
                return 1
        else:
            auth.crear_admin(args.usuario, contrasena, args.nombre)
    except Exception as e:  # noqa: BLE001
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Usuario: {args.usuario.strip().lower()}")
    if not args.contrasena:
        print(f"Contraseña: {contrasena}")
        print("Guárdala ahora: no se vuelve a mostrar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
