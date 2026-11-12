#!/usr/bin/env python3
"""Detector de secretos antes de subirlos al repositorio (AA6). Mira lo que se va a commitear (`--staged`, por defecto) o todo lo que Git rastrea (`--arbol`).
Nunca imprime el secreto: solo fichero, línea y tipo. Sale con 1 si hay algo de confianza ALTA (claves privadas, claves de nube, tokens con prefijo conocido,
URLs con usuario y contraseña); lo de confianza media (`password = "…"`) solo avisa. Falsos positivos: pon `# secreto-permitido` en la línea, o la ruta/huella en
`.secretos-permitidos` (una por línea, `ruta` o `ruta:linea`).

  scripts/detectar_secretos.py             lo que está en el índice (para el hook de pre-commit: scripts/instalar_hook_secretos.sh)
  scripts/detectar_secretos.py --arbol     todo el árbol rastreado (auditoría puntual)"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ALTA = [
    ("clave privada", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY(?: BLOCK)?-----")),
    ("clave de acceso de AWS", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("token de OpenRouter/OpenAI/Anthropic", re.compile(r"\bsk-(?:or-v1-|ant-|proj-)?[A-Za-z0-9_\-]{32,}\b")),
    ("clave de Stripe en producción", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b")),
    ("token de GitHub", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{30,}\b")),
    ("token de Slack", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}\b")),
    ("clave de Google", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("URL con usuario y contraseña", re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@'\"]{2,}:[^/\s@'\"]{6,}@(?!localhost\b|127\.0\.0\.1\b)[a-z0-9.-]+")),
]
MEDIA = [
    ("asignación de contraseña o clave", re.compile(r"""(?ix)(?<![a-z])(?:password|passwd|contrasena|secret|api[_-]?key|token)[a-z_]*["']?\s*[:=]\s*["']([^"'\s$<{][^"'\s]{11,})["']""")),
]
# Valores que son marcadores y no secretos de verdad.
FALSOS = re.compile(r"(?i)passw|contrasena|cambia|ejemplo|example|tu[-_]|your[-_]|placeholder|xxxx|\*\*\*|dummy|prueba|test|fake|falsa|todo|changeme|secreto-de|<.+>|\$\{")
BINARIOS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".mo", ".woff", ".woff2", ".ttf", ".zip", ".gz", ".db", ".p12", ".pfx", ".lock", ".svg", ".xlsx", ".jar")


def permitidos() -> set[str]:
    f = RAIZ / ".secretos-permitidos"
    return {l.strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")} if f.exists() else set()


def revisar_linea(texto: str) -> list[tuple[str, str]]:
    """[(confianza, tipo)] de lo que parece un secreto en una línea."""
    if "secreto-permitido" in texto:
        return []
    hallazgos = []
    for tipo, patron in ALTA:
        m = patron.search(texto)
        if m and not FALSOS.search(m.group(0)):
            hallazgos.append(("alta", tipo))
    for tipo, patron in MEDIA:
        m = patron.search(texto)
        if m and not FALSOS.search(m.group(1)):
            hallazgos.append(("media", tipo))
    return hallazgos


def revisar_texto(ruta: str, texto: str, ok: set[str]) -> list[dict]:
    salida = []
    for n, linea in enumerate(texto.splitlines(), 1):
        if len(linea) > 2000 or ruta in ok or f"{ruta}:{n}" in ok:
            continue
        for confianza, tipo in revisar_linea(linea):
            if ruta.startswith("tests/") and tipo == "clave privada":      # las pruebas de «subir un fichero con una clave privada» la llevan de mentira
                continue
            salida.append({"ruta": ruta, "linea": n, "tipo": tipo, "confianza": confianza})
    return salida


def _git(*args: str) -> str:
    return subprocess.run(["git", "-c", f"safe.directory={RAIZ}", "-C", str(RAIZ), *args], capture_output=True, text=True, check=True).stdout


def contenido_a_revisar(arbol: bool):
    if arbol:
        for ruta in _git("ls-files").splitlines():
            if not ruta.lower().endswith(BINARIOS):
                try:
                    yield ruta, (RAIZ / ruta).read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
    else:
        for ruta in _git("diff", "--cached", "--name-only", "--diff-filter=ACM").splitlines():
            if not ruta.lower().endswith(BINARIOS):
                try:
                    yield ruta, _git("show", f":{ruta}")
                except (subprocess.CalledProcessError, UnicodeDecodeError):
                    continue


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arbol", action="store_true")
    a = ap.parse_args()
    ok = permitidos()
    hallazgos = [h for ruta, texto in contenido_a_revisar(a.arbol) for h in revisar_texto(ruta, texto, ok)]
    altas = [h for h in hallazgos if h["confianza"] == "alta"]
    for h in sorted(hallazgos, key=lambda x: (x["confianza"] != "alta", x["ruta"], x["linea"])):
        print(f"{'✗' if h['confianza'] == 'alta' else '!'} {h['ruta']}:{h['linea']}  {h['tipo']} ({h['confianza']})")
    if altas:
        print(f"\n{len(altas)} posible(s) secreto(s) de confianza alta. Quítalos del commit (y rota la clave si ya estuvo en un commit). Falso positivo: «# secreto-permitido» en la línea o .secretos-permitidos.")
        return 1
    print("Sin secretos de confianza alta." + (f" ({len(hallazgos)} aviso(s) de confianza media.)" if hallazgos else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
