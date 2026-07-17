"""Migración única (Fase 7a): traslada las contraseñas ya existentes en
`usuarios.contrasena_hash` (formato Werkzeug) a Ory Kratos, importándolas
tal cual — nadie tiene que cambiar su contraseña por este cambio.

Uso:
    python scripts/migrar_usuarios_a_kratos.py

Requiere Kratos levantado (`docker compose up -d kratos`) y alcanzable en
`app.kratos.KRATOS_ADMIN_URL`. Idempotente: los usuarios que ya tengan
`kratos_identity_id` se saltan; se puede volver a ejecutar sin duplicar
nada. El usuario "local" (`es_local = 1`, usado por `cli.py`/
`mcp_server.py`) se excluye explícitamente — su contraseña es aleatoria y
nadie la usa nunca para entrar de verdad.
"""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, kratos  # noqa: E402


def _b64_sin_relleno(datos: bytes) -> str:
    """Kratos decodifica pbkdf2 con `base64.RawStdEncoding` (sin `=` de relleno)."""
    return base64.b64encode(datos).rstrip(b"=").decode("ascii")


def _b64_con_relleno(datos: bytes) -> str:
    """Kratos decodifica scrypt con `base64.StdEncoding` (CON `=` de relleno,
    modo estricto) — a diferencia de pbkdf2. Confirmado leyendo
    `hash/hash_comparator.go` (`decodeScryptHash` vs `decodePbkdf2Hash`) en el
    código fuente de Kratos, no es un detalle documentado explícitamente."""
    return base64.b64encode(datos).decode("ascii")


def _hash_werkzeug_a_phc_kratos(contrasena_hash: str) -> str:
    """Convierte un hash de `werkzeug.security.generate_password_hash` al
    formato PHC que sabe importar Kratos. Werkzeug ha cambiado su método
    por defecto entre versiones (pbkdf2:sha256 en versiones antiguas,
    scrypt desde Werkzeug 2.3) — se soportan ambos, detectando el método
    por el propio hash guardado en vez de asumir uno fijo.

    Dos detalles de Kratos que NO son evidentes por su propio formato y que
    hicieron falta leer su código fuente para confirmar (`hash_comparator.go`):
    - El `ln=` de scrypt es el valor N tal cual (no `log2(N)`, pese a que ese
      es el significado habitual de "ln" en otras implementaciones PHC).
    - pbkdf2 espera base64 SIN relleno (`RawStdEncoding`), scrypt espera CON
      relleno (`StdEncoding` estricto) — cada uno un padding distinto."""
    metodo, salt, hash_hex = contrasena_hash.split("$")
    partes_metodo = metodo.split(":")
    algoritmo = partes_metodo[0]
    salt_bytes = salt.encode("utf-8")
    hash_bytes = bytes.fromhex(hash_hex)

    if algoritmo == "pbkdf2":
        _, digest, iteraciones = partes_metodo
        if digest != "sha256":
            raise ValueError(f"Digest pbkdf2 no soportado por este conversor: {digest}")
        return (
            f"$pbkdf2-sha256$i={iteraciones},l={len(hash_bytes)}"
            f"${_b64_sin_relleno(salt_bytes)}${_b64_sin_relleno(hash_bytes)}"
        )

    if algoritmo == "scrypt":
        _, n, r, p = partes_metodo
        return f"$scrypt$ln={n},r={r},p={p}${_b64_con_relleno(salt_bytes)}${_b64_con_relleno(hash_bytes)}"

    raise ValueError(f"Algoritmo de hash no soportado por este conversor: {algoritmo}")


def migrar() -> None:
    conn = db.get_connection()
    try:
        usuarios_pendientes = conn.execute(
            "SELECT id, email, contrasena_hash FROM usuarios "
            "WHERE kratos_identity_id IS NULL AND es_local = 0"
        ).fetchall()
    finally:
        conn.close()

    if not usuarios_pendientes:
        print("No hay usuarios pendientes de migrar.")
        return

    migrados, fallidos = 0, 0
    for usuario in usuarios_pendientes:
        try:
            hash_phc = _hash_werkzeug_a_phc_kratos(usuario["contrasena_hash"])
            identity_id = kratos.importar_identidad_con_hash(usuario["email"], hash_phc)
            db.vincular_kratos_id(usuario["id"], identity_id)
            migrados += 1
            print(f"  ✓ {usuario['email']} → {identity_id}")
        except (ValueError, kratos.ErrorKratos) as e:
            fallidos += 1
            print(f"  ✗ {usuario['email']}: {e}")

    print(f"\nMigrados: {migrados}. Fallidos: {fallidos}.")


if __name__ == "__main__":
    migrar()
