"""Repara identidades de Kratos SIN dirección de recuperación/verificación.

Las cuentas creadas antes de que el esquema de identidad declarase `recovery.via` / `verification.via` (o por una vía que no las generó)
no tienen esas direcciones, y para Kratos son «desconocidas»: «¿Olvidaste tu contraseña?» muestra «te hemos mandado un código» pero no manda
ningún correo (Kratos no revela qué direcciones existen). Volver a guardar la identidad con sus mismos datos hace que Kratos las genere.
No toca contraseñas ni segundos factores (la Admin API conserva las credenciales si no se envían).

    .venv/bin/python scripts/reparar_direcciones_kratos.py                  # solo lista las afectadas
    .venv/bin/python scripts/reparar_direcciones_kratos.py --aplicar        # las repara todas
    .venv/bin/python scripts/reparar_direcciones_kratos.py --aplicar --email gestio@guilda.cat

Usa KRATOS_ADMIN_URL (por defecto http://127.0.0.1:4434)."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

ADMIN = os.environ.get("KRATOS_ADMIN_URL", "http://127.0.0.1:4434").rstrip("/")


def _http(metodo: str, ruta: str, cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(f"{ADMIN}{ruta}", data=datos, method=metodo, headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(peticion, timeout=15) as r:
            return r.status, json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "{}")


def identidades():
    """Todas las identidades (Kratos ≥ 1.x pagina con `page_size` y `page_token`; la cabecera `Link` trae el token de la siguiente página)."""
    token = ""
    while True:
        peticion = urllib.request.Request(f"{ADMIN}/admin/identities?page_size=250" + (f"&page_token={token}" if token else ""), headers={"Accept": "application/json"})
        with urllib.request.urlopen(peticion, timeout=15) as r:
            lote = json.loads(r.read() or "[]")
            enlace = r.headers.get("Link", "")
        yield from lote
        siguiente = [t for t in enlace.split(",") if 'rel="next"' in t]
        if not lote or not siguiente:
            return
        token = siguiente[0].split("page_token=")[1].split("&")[0].split(">")[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--email", help="solo esta cuenta")
    args = ap.parse_args()
    afectadas = [i for i in identidades()
                 if not i.get("recovery_addresses") and (i.get("traits") or {}).get("email") and (not args.email or i["traits"]["email"].lower() == args.email.lower())]
    if not afectadas:
        print("Ninguna identidad sin dirección de recuperación.")
        return 0
    for i in afectadas:
        email = i["traits"]["email"]
        if not args.aplicar:
            print(f"SIN DIRECCIÓN: {email}  (usa --aplicar para repararla)")
            continue
        estado, cuerpo = _http("PUT", f"/admin/identities/{i['id']}", {"schema_id": i["schema_id"], "traits": i["traits"], "state": i.get("state", "active")})
        _, despues = _http("GET", f"/admin/identities/{i['id']}")
        ok = estado == 200 and bool(despues.get("recovery_addresses"))
        print(f"{'REPARADA' if ok else 'FALLO'}: {email} (HTTP {estado}; direcciones de recuperación ahora: {len(despues.get('recovery_addresses') or [])})")
        if not ok:
            print("  ", str(cuerpo)[:300], file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
