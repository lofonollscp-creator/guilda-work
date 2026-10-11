"""Política de seguridad de contenido (CSP) de la app: solo se ejecutan los scripts del propio sitio y los en línea que llevan el
nonce de ESA petición; no hay manejadores `on...=` ni `javascript:` (los sustituye static/csp_compat.js con atributos `data-*`).

Modo por variable de entorno `GUILDA_CSP`:
  - `reportar` (por defecto): se envía `Content-Security-Policy-Report-Only`; el navegador avisa a /csp-report de lo que bloquearía
    y no rompe nada. Es el modo para el primer despliegue: se mira el registro unos días y, si no hay avisos, se pasa a `forzar`.
  - `forzar`: `Content-Security-Policy`, el navegador BLOQUEA lo que incumpla.
  - `no`: sin CSP de scripts (queda solo `frame-ancestors`)."""
from __future__ import annotations

import logging
import os
import secrets

logger = logging.getLogger("guilda")

MODOS = ("reportar", "forzar", "no")


def modo() -> str:
    valor = os.environ.get("GUILDA_CSP", "reportar").strip().lower()
    return valor if valor in MODOS else "reportar"


def nuevo_nonce() -> str:
    return secrets.token_urlsafe(16)


def politica(nonce: str, con_informe: bool) -> str:
    """Solo las directivas que importan para scripts y marcos; el resto (imágenes, estilos, conexiones) queda como estaba.
    `worker-src blob:` lo necesita la prueba de trabajo del captcha (altcha crea su Worker desde un Blob)."""
    directivas = [
        f"script-src 'self' 'nonce-{nonce}'",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "frame-ancestors 'self'",
    ]
    if con_informe:
        directivas.append("report-uri /csp-report")
    return "; ".join(directivas)


def resumir_informe(cuerpo: dict | None) -> str:
    """Una línea para el registro a partir del informe del navegador (formato `csp-report`); nunca el contenido bloqueado entero."""
    informe = (cuerpo or {}).get("csp-report") or cuerpo or {}
    campos = ("violated-directive", "effective-directive", "blocked-uri", "document-uri", "source-file", "line-number")
    return " ".join(f"{c}={str(informe.get(c, ''))[:120]!r}" for c in campos if informe.get(c))
