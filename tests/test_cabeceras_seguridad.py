"""La app principal no se puede enmarcar desde otra web ni deja que el navegador adivine tipos."""


def test_las_paginas_y_la_api_llevan_cabeceras_de_seguridad(cliente):
    for ruta in ("/login", "/api/v1/health", "/docs/"):
        r = cliente.get(ruta, follow_redirects=False)
        assert r.headers["X-Content-Type-Options"] == "nosniff", ruta
        assert r.headers["X-Frame-Options"] == "SAMEORIGIN", ruta
        assert "frame-ancestors 'self'" in r.headers["Content-Security-Policy"] and "object-src 'none'" in r.headers["Content-Security-Policy"], ruta
        assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin", ruta


def test_hsts_solo_cuando_la_peticion_llego_por_https(cliente):
    assert "Strict-Transport-Security" not in cliente.get("/api/v1/health").headers
    r = cliente.get("/api/v1/health", headers={"X-Forwarded-Proto": "https"})
    assert r.headers["Strict-Transport-Security"] == "max-age=31536000"


# --- CSP de scripts con nonce ---------------------------------------------------------------------------------------------------

import re

import pytest

from app import db, seguridad_csp
from tests.conftest import iniciar_sesion_de_prueba


def test_por_defecto_la_csp_de_scripts_va_en_modo_informe_con_nonce_distinto_por_peticion(cliente, monkeypatch):
    monkeypatch.delenv("GUILDA_CSP", raising=False)
    a = cliente.get("/login").headers
    b = cliente.get("/login").headers
    informe = a["Content-Security-Policy-Report-Only"]
    assert "script-src 'self' 'nonce-" in informe and "worker-src 'self' blob:" in informe and "report-uri /csp-report" in informe
    assert "frame-ancestors 'self'" in a["Content-Security-Policy"]                # lo seguro se hace cumplir ya
    assert re.search(r"nonce-([\w-]+)", a["Content-Security-Policy-Report-Only"]).group(1) != re.search(r"nonce-([\w-]+)", b["Content-Security-Policy-Report-Only"]).group(1)


def test_modo_forzar_y_modo_no(cliente, monkeypatch):
    monkeypatch.setenv("GUILDA_CSP", "forzar")
    h = cliente.get("/login").headers
    assert "script-src 'self' 'nonce-" in h["Content-Security-Policy"] and "Content-Security-Policy-Report-Only" not in h
    monkeypatch.setenv("GUILDA_CSP", "no")
    h = cliente.get("/login").headers
    assert "script-src" not in h["Content-Security-Policy"] and "Content-Security-Policy-Report-Only" not in h
    monkeypatch.setenv("GUILDA_CSP", "inventado")
    assert seguridad_csp.modo() == "reportar"


def test_el_nonce_de_la_cabecera_es_el_de_los_scripts_en_linea_de_la_pagina(cliente, monkeypatch):
    monkeypatch.setenv("GUILDA_CSP", "forzar")
    iniciar_sesion_de_prueba(cliente, "csp@ejemplo.com", "contrasena123")
    encontrados = 0
    for ruta in ("/", "/fichaje/", "/tareas/calendario", "/historial", "/herramientas", "/fiscal/clientes"):
        r = cliente.get(ruta)
        nonce = re.search(r"nonce-([\w-]+)", r.headers["Content-Security-Policy"]).group(1)
        for etiqueta in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", r.get_data(as_text=True)):
            assert f'nonce="{nonce}"' in etiqueta, (ruta, etiqueta)
            encontrados += 1
    assert encontrados >= 3, "no se encontró ningún script en línea que comprobar"


def test_ninguna_pantalla_tiene_manejadores_en_linea_ni_scripts_sin_nonce(cliente, monkeypatch):
    """Lo que la CSP estricta bloquearía: atributos on…=, href=javascript: y <script> en línea sin nonce, en TODAS las pantallas."""
    from app.main import app
    uid = iniciar_sesion_de_prueba(cliente, "csp2@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, db.crear_tenant("Despacho CSP"))
    db.crear_categoria(uid, "Proyecto CSP", None)
    db.crear_tarea_outlook(uid, "Tarea CSP")
    from tests.test_accesibilidad import _paginas_get
    revisadas, malas = 0, []
    for ruta in sorted(_paginas_get(app)):
        r = cliente.get(ruta)
        if r.status_code != 200 or "text/html" not in r.headers.get("Content-Type", ""):
            continue
        revisadas += 1
        html = r.get_data(as_text=True)
        if re.search(r"<[a-zA-Z][^>]*\s(on[a-z]+)=[\"']", html):
            malas.append((ruta, "manejador on…="))
        if re.search(r"href=[\"']\s*javascript:", html, re.I):
            malas.append((ruta, "href=javascript:"))
        nonce = re.search(r"nonce-([\w-]+)", r.headers.get("Content-Security-Policy-Report-Only", "") + r.headers.get("Content-Security-Policy", ""))
        for etiqueta in re.findall(r"<script(?![^>]*\bsrc=)(?![^>]*type=\"application/json\")[^>]*>", html):
            if not nonce or f'nonce="{nonce.group(1)}"' not in etiqueta:
                malas.append((ruta, "<script> sin nonce"))
    assert revisadas >= 15 and not malas, malas


def test_el_informe_de_csp_se_registra_sin_exigir_sesion(cliente, caplog):
    import logging
    caplog.set_level(logging.WARNING, logger="guilda")
    cuerpo = '{"csp-report": {"violated-directive": "script-src-elem", "blocked-uri": "inline", "document-uri": "https://app/x", "line-number": 7}}'
    r = cliente.post("/csp-report", data=cuerpo, content_type="application/csp-report")
    assert r.status_code == 204
    assert any("script-src-elem" in rec.getMessage() and "inline" in rec.getMessage() for rec in caplog.records)
    assert cliente.post("/csp-report", data="no es json", content_type="text/plain").status_code == 204        # basura: se ignora sin romper
