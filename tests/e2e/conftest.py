"""Pruebas de navegador (Playwright + Chromium) de los flujos críticos. Se saltan solas si Playwright o su navegador no están instalados (ver HOSTING.md, «Pruebas de navegador»).

Cómo funcionan: la aplicación arranca de verdad en un puerto libre de 127.0.0.1 (con la base de datos temporal de siempre, nunca la real) y Chromium la recorre como una persona. El equipo inicia sesión
por el camino real de Kratos con el cliente de pruebas de Flask y sus cookies se pasan al navegador; el cliente del portal entra con su enlace de un solo uso."""
import importlib.util
import os
import threading

import pytest

# No se recogen (ni se importan) si no se piden con GUILDA_E2E=1 (lo pone scripts/probar_navegador.sh) o si Playwright no está instalado: así la suite normal no se entera de que existen.
if not os.environ.get("GUILDA_E2E") or importlib.util.find_spec("playwright") is None:
    collect_ignore_glob = ["test_*.py"]
    ACTIVO = False
else:
    ACTIVO = True

if ACTIVO:
    from playwright.sync_api import Error as ErrorPlaywright
    from playwright.sync_api import sync_playwright
    from werkzeug.serving import make_server

    from tests.conftest import iniciar_sesion_de_prueba



    @pytest.fixture(scope="session")
    def playwright_sesion():
        with sync_playwright() as p:
            yield p


    @pytest.fixture(scope="session")
    def chromium(playwright_sesion):
        try:
            navegador = playwright_sesion.chromium.launch()
        except ErrorPlaywright as e:
            pytest.skip(f"Chromium no está disponible ({str(e).splitlines()[0]}): playwright install chromium")
        yield navegador
        navegador.close()


    @pytest.fixture
    def servidor(cliente):
        """La app escuchando de verdad. `cliente` (fixture de siempre) deja lista la base de datos temporal, Kratos de pruebas y el límite de intentos reiniciado."""
        from app.main import app as flask_app
        servidor = make_server("127.0.0.1", 0, flask_app, threaded=True)
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        yield type("Servidor", (), {"url": f"http://127.0.0.1:{servidor.server_port}", "app": flask_app, "cliente": cliente})
        servidor.shutdown()


    def _errores_de_la_pagina(pagina) -> list[str]:
        errores: list[str] = []
        pagina.on("pageerror", lambda e: errores.append(f"JS: {e}"))
        pagina.on("console", lambda m: errores.append(f"consola: {m.text}") if m.type == "error" else None)
        return errores


    @pytest.fixture
    def abrir(chromium, servidor):
        """`abrir()` crea un contexto de navegador nuevo (otra persona) y devuelve (página, errores de JS)."""
        contextos = []

        def _abrir():
            contexto = chromium.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
            contextos.append(contexto)
            pagina = contexto.new_page()
            return pagina, _errores_de_la_pagina(pagina)

        yield _abrir
        for c in contextos:
            c.close()


    @pytest.fixture
    def entrar_como_equipo(servidor):
        """Inicia sesión como esa persona (usuario real en Kratos) y le pone a la página las cookies resultantes. Devuelve el id de usuario."""
        def _entrar(pagina, email: str, contrasena: str = "contrasena123", despacho: int | None = None, direccion: bool = False) -> int:
            from app import db
            cliente_http = servidor.app.test_client()
            servidor.app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")      # Kratos de pruebas redirige a 127.0.0.1:8000: solo mientras se inicia sesión
            try:
                uid = iniciar_sesion_de_prueba(cliente_http, email, contrasena)
            finally:
                servidor.app.config["SERVER_NAME"] = None
            if despacho:
                db.asignar_tenant(uid, despacho)
            if direccion:
                db.asignar_supervisor_tenant(uid, True)
            cookies = [{"name": c.key, "value": c.value, "url": servidor.url} for c in cliente_http._cookies.values()]
            pagina.context.add_cookies(cookies)
            return uid
        return _entrar
