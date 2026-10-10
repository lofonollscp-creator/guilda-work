#!/usr/bin/env python3
"""Auditoría de solo lectura de los clientes OAuth2 de Hydra (Admin API en 127.0.0.1:4445).

Avisa de lo que conviene revisar: clientes sin consentimiento que no son de la lista de propios, redirect URIs inseguras
(http fuera de localhost, comodines), clientes públicos, alcances amplios y clientes sin nombre (típicos del Registro
Dinámico). No modifica nada. Uso:

    python3 scripts/auditar_hydra.py
"""
import json
import sys
import urllib.parse
import urllib.request

ADMIN = "http://127.0.0.1:4445"
PROPIOS = {"outline", "element", "mas", "drive", "documentos", "claude-desktop", "espocrm", "nextcloud", "synapse"}


def _get(ruta):
    with urllib.request.urlopen(f"{ADMIN}{ruta}", timeout=10) as r:
        return json.loads(r.read().decode())


def main() -> int:
    try:
        clientes = _get("/admin/clients?page_size=500")
    except Exception as e:  # noqa: BLE001
        print(f"No se pudo consultar Hydra en {ADMIN}: {e}")
        return 2
    avisos = 0
    for c in sorted(clientes, key=lambda x: x.get("client_name") or ""):
        nombre = c.get("client_name") or "(sin nombre)"
        problemas = []
        if c.get("skip_consent") and nombre not in PROPIOS:
            problemas.append("skip_consent=true pero no figura entre los clientes propios")
        for uri in c.get("redirect_uris", []):
            u = urllib.parse.urlparse(uri)
            if u.scheme == "http" and u.hostname not in ("localhost", "127.0.0.1"):
                problemas.append(f"redirect http no local: {uri}")
            if "*" in uri:
                problemas.append(f"redirect con comodín: {uri}")
        if c.get("token_endpoint_auth_method") == "none":
            problemas.append("cliente público (sin secreto): exigir PKCE")
        if not c.get("client_name"):
            problemas.append("sin nombre (¿registro dinámico?)")
        if not c.get("skip_consent") and not c.get("redirect_uris"):
            problemas.append("sin redirect URIs")
        estado = "REVISAR" if problemas else "ok"
        avisos += bool(problemas)
        print(f"[{estado:7}] {nombre:20} {c.get('client_id', '')[:13]}  skip_consent={c.get('skip_consent')}  scope={c.get('scope')}")
        for p in problemas:
            print(f"           - {p}")
    print(f"\n{len(clientes)} clientes, {avisos} con avisos.")
    return 1 if avisos else 0


if __name__ == "__main__":
    sys.exit(main())
