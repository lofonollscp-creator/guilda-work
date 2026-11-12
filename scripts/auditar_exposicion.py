#!/usr/bin/env python3
"""Qué ve el mundo de Guilda Work (AA4/AA5): cabeceras de seguridad de cada subdominio, puertos que escuchan hacia fuera y estado de CrowdSec.
Deja el resultado en data/backups/exposicion_estado.json, que lee el panel Salud. Solo hace GET a la raíz de cada sitio (separados un segundo, para no
disparar a CrowdSec) y lee `ss` y `cscli`: no cambia nada. Debe correr como root (lee el Caddyfile y usa cscli); sale con 1 si hay fallos.

  scripts/auditar_exposicion.py [--salida RUTA.json] [--hosts a.ejemplo.com b.ejemplo.com] [--sin-red]
Variables: GUILDA_PUERTOS_ESPERADOS (lista separada por comas; por defecto web, correo y OpenVPN), GUILDA_IPS_PROPIAS (IPs públicas del servidor además de las de sus interfaces)."""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PUERTOS_ESPERADOS = {22, 25, 80, 110, 143, 443, 465, 587, 993, 995, 1194, 4190, 7881}
SOFTWARE = ("server", "x-powered-by", "via")


def hosts_del_caddyfile(texto: str) -> list[str]:
    """Los sitios con nombre de dominio que sirve Caddy (sin comodines ni bloques como `(seguridad)`)."""
    return sorted({m.group(1) for m in re.finditer(r"(?m)^([a-z0-9][a-z0-9.-]*\.[a-z]{2,}) \{", texto)})


def evaluar_cabeceras(cabeceras: dict[str, str]) -> list[str]:
    """Qué falta o sobra en las cabeceras de una respuesta (claves en minúsculas)."""
    problemas = []
    if "strict-transport-security" not in cabeceras:
        problemas.append("sin HSTS")
    if cabeceras.get("x-content-type-options", "").lower() != "nosniff":
        problemas.append("sin nosniff")
    for c in SOFTWARE:
        if c in cabeceras:
            problemas.append(f"publica {c}: {cabeceras[c][:40]}")
    return problemas


def puertos_publicos(salida_ss: str) -> dict[int, str]:
    """{puerto: proceso} de lo que escucha en todas las interfaces (0.0.0.0, [::] o *), salida de `ss -ltnupH`."""
    visto: dict[int, str] = {}
    for linea in salida_ss.splitlines():
        partes = linea.split()
        if len(partes) < 5:
            continue
        local = partes[4]
        direccion, _, puerto = local.rpartition(":")
        if direccion not in ("0.0.0.0", "*", "[::]", "::") or not puerto.isdigit():
            continue
        proceso = re.search(r'"([^"]+)"', linea)
        visto[int(puerto)] = proceso.group(1) if proceso else "?"
    return visto


def puertos_permitidos_ufw(salida_ufw: str) -> tuple[bool, set[int]]:
    """(¿ufw activo?, puertos que deja pasar) de `ufw status`. Las reglas con rango (50000:50100/udp) se expanden."""
    if "Status: active" not in salida_ufw:
        return False, set()
    puertos: set[int] = set()
    for linea in salida_ufw.splitlines():
        m = re.match(r"^(\d+)(?::(\d+))?(?:/(?:tcp|udp))?\s+ALLOW", linea.strip())
        if m:
            puertos.update(range(int(m.group(1)), int(m.group(2) or m.group(1)) + 1))
    return True, puertos


def puertos_inesperados(visto: dict[int, str], esperados: set[int], ufw_activo: bool = False, permitidos: set[int] | None = None) -> tuple[list[str], list[str]]:
    """(alcanzables, filtrados). Un puerto inesperado que escucha hacia fuera es un fallo solo si el cortafuegos lo deja pasar (o no hay cortafuegos); si ufw lo bloquea es un aviso:
    escucha en todas las interfaces sin necesidad y conviene atarlo a 127.0.0.1. Los puertos publicados por Docker saltan ufw: por eso la lista de esperados es la referencia."""
    alcanzables, filtrados = [], []
    for p, proceso in sorted(visto.items()):
        if p in esperados:
            continue
        (alcanzables if (not ufw_activo or p in (permitidos or set())) else filtrados).append(f"{p} ({proceso})")
    return alcanzables, filtrados


def evaluar_crowdsec(decisiones: list[dict], ips_propias: set[str]) -> dict:
    """Resumen de las decisiones activas de CrowdSec y, sobre todo, si alguna IP nuestra está baneada (el servidor se dejaría fuera a sí mismo)."""
    activas = [d for d in decisiones if (d.get("type") or "ban") == "ban"]
    propias = sorted({d["value"] for d in activas if d.get("value") in ips_propias})
    return {"activas": len(activas), "propias_baneadas": propias, "por_escenario": dict(Counter(d.get("scenario", "?") for d in activas).most_common(6))}


def _decisiones_crowdsec() -> list[dict]:
    r = subprocess.run(["cscli", "decisions", "list", "-o", "json", "--limit", "0"], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:200] or "cscli falló")
    alertas = json.loads(r.stdout or "null") or []
    return [d for a in alertas for d in (a.get("decisions") or [])]


def _ips_propias() -> set[str]:
    ips = {x.strip() for x in os.environ.get("GUILDA_IPS_PROPIAS", "").split(",") if x.strip()}
    try:
        ips.update(subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5).stdout.split())
    except Exception:  # noqa: BLE001
        pass
    return ips


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _cabeceras_de(host: str) -> tuple[int | None, dict[str, str]]:
    abridor = urllib.request.build_opener(_SinRedireccion)
    try:
        r = abridor.open(urllib.request.Request(f"https://{host}/", headers={"User-Agent": "guilda-auditoria-exposicion"}), timeout=10)
    except urllib.error.HTTPError as e:
        r = e
    except Exception:  # noqa: BLE001
        return None, {}
    return r.status if hasattr(r, "status") else r.code, {k.lower(): v for k, v in r.headers.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida", default=str(RAIZ / "data" / "backups" / "exposicion_estado.json"))
    ap.add_argument("--hosts", nargs="*")
    ap.add_argument("--sin-red", action="store_true", help="no hace GET a los sitios (solo puertos y CrowdSec)")
    a = ap.parse_args()
    esperados = {int(x) for x in os.environ.get("GUILDA_PUERTOS_ESPERADOS", "").split(",") if x.strip()} or PUERTOS_ESPERADOS
    fallos: list[str] = []
    hosts_estado = []
    hosts = a.hosts
    if hosts is None:
        try:
            hosts = hosts_del_caddyfile(Path("/etc/caddy/Caddyfile").read_text(encoding="utf-8"))
        except OSError:
            hosts = []
    if not a.sin_red:
        for h in hosts:
            codigo, cab = _cabeceras_de(h)
            problemas = ["no responde"] if codigo is None else evaluar_cabeceras(cab)
            hosts_estado.append({"host": h, "codigo": codigo, "problemas": problemas})
            fallos += [f"{h}: {p}" for p in problemas]
            time.sleep(1)
    ss = subprocess.run(["ss", "-ltnupH"], capture_output=True, text=True, timeout=10).stdout
    try:
        ufw = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=10).stdout
    except OSError:
        ufw = ""
    activo, permitidos = puertos_permitidos_ufw(ufw)
    inesperados, filtrados = puertos_inesperados(puertos_publicos(ss), esperados, activo, permitidos)
    fallos += [f"puerto {p} abierto al exterior" for p in inesperados]
    try:
        crowdsec = evaluar_crowdsec(_decisiones_crowdsec(), _ips_propias())
        fallos += [f"CrowdSec tiene baneada una IP del propio servidor: {ip}" for ip in crowdsec["propias_baneadas"]]
    except Exception as e:  # noqa: BLE001
        crowdsec = {"error": f"{type(e).__name__}: {e}"[:200]}
    estado = {"fecha": datetime.now().isoformat(timespec="seconds"), "hosts": hosts_estado, "puertos_inesperados": inesperados, "puertos_filtrados": filtrados, "ufw_activo": activo, "crowdsec": crowdsec, "fallos": fallos}
    Path(a.salida).parent.mkdir(parents=True, exist_ok=True)
    Path(a.salida).write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
    for f in fallos:
        print("✗", f)
    print(f"{len(hosts_estado)} sitios, {len(inesperados)} puerto(s) inesperado(s), CrowdSec: {crowdsec.get('activas', '?')} decisiones activas, {len(fallos)} fallo(s).")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
