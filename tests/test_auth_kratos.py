"""Fase 7a: login/registro/logout reales contra Ory Kratos (instancia de
test real, ver tests/conftest.py — sin mocks)."""
import re

from tests.conftest import iniciar_sesion_de_prueba


def test_login_real_permite_entrar_a_una_pagina_protegida(cliente):
    iniciar_sesion_de_prueba(cliente, "kratos-login@ejemplo.com", "contrasena123")
    resp = cliente.get("/", follow_redirects=True)
    assert resp.status_code == 200
    assert "Iniciar sesi" not in resp.get_data(as_text=True)


def test_sin_sesion_redirige_a_login(cliente):
    resp = cliente.get("/", follow_redirects=True)
    assert resp.status_code == 200
    assert "Iniciar sesi" in resp.get_data(as_text=True)


def test_bootstrap_del_flujo_de_login_es_una_redireccion_relativa(cliente):
    """El primer GET /login (sin ?flow=) tiene que quedarse en el MISMO
    origen -- si algún día vuelve a redirigir directo a Kratos
    (/.ory/self-service/login/browser) sin pasar por el bootstrap
    server-side (app/main.py:_flujo_o_redirigir), Kratos acabaría
    rebotando al navegador a su SELFSERVICE_FLOWS_LOGIN_UI_URL fijo
    -- que es lo que rompía la sesión independiente del backoffice en
    otro subdominio (ver HOSTING.md)."""
    resp = cliente.get("/login")
    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location.startswith("/login?flow=")
    # Y la cookie anti-CSRF del flujo ya viene puesta en esta misma
    # respuesta -- si no, el POST de después del siguiente hop falla la
    # validación CSRF de Kratos (bug real corregido en
    # kratos.iniciar_flujo, antes descartaba las Set-Cookie).
    assert "csrf_token" in resp.headers.get("Set-Cookie", "")


def test_iniciar_flujo_devuelve_la_cookie_anti_csrf(cliente):
    """kratos.iniciar_flujo() -- hasta ahora sin ningún llamador, con un
    bug real que nunca se había disparado: siempre devolvía un diccionario
    vacío de cabeceras en vez de las Set-Cookie reales de Kratos."""
    from app import kratos

    ubicacion, cabeceras_set_cookie = kratos.iniciar_flujo("login", {})
    assert "flow=" in ubicacion
    assert cabeceras_set_cookie
    assert any("csrf_token" in c for c in cabeceras_set_cookie)


def test_login_con_contrasena_incorrecta_muestra_error(cliente):
    from app import db, kratos

    identity_id = kratos.crear_identidad("kratos-mal@ejemplo.com", "contrasena123")
    db.crear_usuario_vinculado_a_kratos("kratos-mal@ejemplo.com", identity_id)

    resp = cliente.get("/login", follow_redirects=True)
    html = resp.get_data(as_text=True)
    flow_id = re.search(r"[?&]flow=([0-9a-f-]+)", resp.request.url).group(1)
    csrf = re.search(r'name="csrf_token" value="([^"]*)"', html).group(1)

    resp = cliente.post(
        f"/.ory/self-service/login?flow={flow_id}",
        data={"csrf_token": csrf, "identifier": "kratos-mal@ejemplo.com", "password": "incorrecta", "method": "password"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "incorrect" in resp.get_data(as_text=True).lower() or "credentials" in resp.get_data(as_text=True).lower()

    # No ha entrado: la home sigue pidiendo login.
    resp = cliente.get("/", follow_redirects=True)
    assert "Iniciar sesi" in resp.get_data(as_text=True)


def test_logout_cierra_la_sesion(cliente):
    iniciar_sesion_de_prueba(cliente, "kratos-logout@ejemplo.com", "contrasena123")
    resp = cliente.get("/", follow_redirects=True)
    assert "Iniciar sesi" not in resp.get_data(as_text=True)

    cliente.post("/logout", follow_redirects=True)

    resp = cliente.get("/", follow_redirects=True)
    assert "Iniciar sesi" in resp.get_data(as_text=True)


def test_registro_real_crea_usuario_e_inicia_sesion(cliente):
    resp = cliente.get("/registro", follow_redirects=True)
    html = resp.get_data(as_text=True)
    flow_id = re.search(r"[?&]flow=([0-9a-f-]+)", resp.request.url).group(1)
    csrf = re.search(r'name="csrf_token" value="([^"]*)"', html).group(1)

    # Contraseña deliberadamente no trivial: Kratos rechaza en el propio
    # flujo de self-service (no en la Admin API) las contraseñas que
    # aparecen en filtraciones conocidas (comprobación contra
    # haveibeenpwned) — "contrasena123", usada en el resto de tests vía
    # Kratos.crear_identidad (Admin API, sin esa comprobación), no vale
    # aquí porque este test sí pasa por el registro real de verdad.
    resp = cliente.post(
        f"/.ory/self-service/registration?flow={flow_id}",
        data={
            "csrf_token": csrf,
            "traits.email": "kratos-registro@ejemplo.com",
            "password": "Xk9#mQ2vL8pR-noBreached",
            "method": "password",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    from app import db

    assert db.obtener_usuario_por_email("kratos-registro@ejemplo.com") is not None

    resp = cliente.get("/", follow_redirects=True)
    assert "Iniciar sesi" not in resp.get_data(as_text=True)
