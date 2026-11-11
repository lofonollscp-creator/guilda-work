"""Passkeys del equipo con Kratos (W14), de punta a punta: un Kratos de pruebas en Docker con la configuración REAL de deploy/kratos (solo cambian puertos, dominio y base de datos), la app escuchando de verdad y un autenticador
virtual en el navegador. Entra con contraseña, añade una passkey en Ajustes, sale y vuelve a entrar solo con la passkey. Se salta si no hay Docker o no está la imagen de Kratos."""
import json
import pathlib
import subprocess
import time
import urllib.request

import pytest

IMAGEN = "oryd/kratos:v26.2.0"
PUBLICO, ADMIN = 14433, 14434
RAIZ = pathlib.Path(__file__).resolve().parents[2]
CONTRASENA = "Contrasena-larga-de-pruebas-123"


def _hay_docker() -> bool:
    try:
        subprocess.run(["docker", "image", "inspect", IMAGEN], check=True, capture_output=True, timeout=30)
        return True
    except Exception:  # noqa: BLE001
        return False


def _config_de_pruebas(puerto_app: str, destino: pathlib.Path) -> None:
    """La configuración real de Kratos con lo mínimo cambiado para un entorno aislado: base en memoria, otros puertos, la app de pruebas como interfaz y `localhost` como dominio de las passkeys."""
    s = (RAIZ / "deploy" / "kratos" / "kratos.yml").read_text(encoding="utf-8")
    s = s.replace("dsn: ${DSN}", "dsn: memory")
    s = s.replace("base_url: http://127.0.0.1:4433/", f"base_url: http://127.0.0.1:{PUBLICO}/\n    port: {PUBLICO}", 1).replace("base_url: http://127.0.0.1:4434/", f"base_url: http://127.0.0.1:{ADMIN}/\n    port: {ADMIN}", 1)
    s = s.replace("http://127.0.0.1:8000", f"http://localhost:{puerto_app}").replace("http://localhost:8000", f"http://127.0.0.1:{puerto_app}")      # (dos direcciones distintas: Kratos no admite orígenes repetidos)
    assert "id: app.guildawork.com" in s and "https://app.guildawork.com" in s, "la configuración real de Kratos ya no declara las passkeys"
    s = s.replace("id: app.guildawork.com", "id: localhost").replace("https://app.guildawork.com", f"http://localhost:{puerto_app}")
    s = s.replace("smtp://noreply:noreply@localhost:587/?skip_ssl_verify=true", "smtp://noreply:noreply@127.0.0.1:2525/?skip_ssl_verify=true")
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "kratos.yml").write_text(s, encoding="utf-8")
    (destino / "identity.schema.json").write_text((RAIZ / "deploy" / "kratos" / "identity.schema.json").read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run(["cp", "-r", str(RAIZ / "deploy" / "kratos" / "courier-templates"), str(destino / "courier-templates")], check=True)


@pytest.fixture
def kratos_pruebas(servidor, tmp_path):
    if not _hay_docker():
        pytest.skip("sin Docker o sin la imagen de Kratos")
    from app import kratos
    puerto = servidor.url.rsplit(":", 1)[1]
    _config_de_pruebas(puerto, tmp_path / "kratos")
    nombre = f"kratos-passkeys-pruebas-{puerto}"
    subprocess.run(["docker", "rm", "-f", nombre], capture_output=True)
    subprocess.run(["docker", "run", "-d", "--rm", "--name", nombre, "--network", "host", "-v", f"{tmp_path / 'kratos'}:/etc/config/kratos:ro", IMAGEN, "serve", "--config", "/etc/config/kratos/kratos.yml", "--sqa-opt-out"],
                   check=True, capture_output=True)
    try:
        for _ in range(60):
            try:
                if urllib.request.urlopen(f"http://127.0.0.1:{PUBLICO}/health/ready", timeout=2).status == 200:
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        else:
            raise RuntimeError("Kratos de pruebas no arranca: " + subprocess.run(["docker", "logs", nombre], capture_output=True, text=True).stdout[-800:])
        antes = (kratos.KRATOS_PUBLIC_URL, kratos.KRATOS_ADMIN_URL)
        kratos.KRATOS_PUBLIC_URL, kratos.KRATOS_ADMIN_URL = f"http://127.0.0.1:{PUBLICO}", f"http://127.0.0.1:{ADMIN}"
        servidor.app.config["SERVER_NAME"] = None
        try:
            yield type("KratosPruebas", (), {"admin": f"http://127.0.0.1:{ADMIN}", "origen": f"http://localhost:{puerto}"})
        finally:
            kratos.KRATOS_PUBLIC_URL, kratos.KRATOS_ADMIN_URL = antes
    finally:
        subprocess.run(["docker", "rm", "-f", nombre], capture_output=True)


def _crear_identidad(kp, email: str) -> None:
    cuerpo = json.dumps({"schema_id": "default", "traits": {"email": email}, "credentials": {"password": {"config": {"password": CONTRASENA}}}, "state": "active"}).encode()
    pet = urllib.request.Request(f"{kp.admin}/admin/identities", data=cuerpo, headers={"Content-Type": "application/json"}, method="POST")
    assert urllib.request.urlopen(pet, timeout=10).status == 201


def _autenticador_virtual(pagina) -> None:
    cdp = pagina.context.new_cdp_session(pagina)
    cdp.send("WebAuthn.enable")
    cdp.send("WebAuthn.addVirtualAuthenticator", {"options": {"protocol": "ctap2", "transport": "internal", "hasResidentKey": True, "hasUserVerification": True, "isUserVerified": True, "automaticPresenceSimulation": True}})


def test_se_añade_una_passkey_y_se_entra_solo_con_ella(servidor, kratos_pruebas, abrir):
    from app import db
    email = "equipo-passkey@ejemplo.com"
    _crear_identidad(kratos_pruebas, email)
    pagina, errores = abrir()
    _autenticador_virtual(pagina)
    # 1) Con contraseña, como siempre.
    pagina.goto(f"{kratos_pruebas.origen}/login")
    assert pagina.locator("[data-passkey-login]").count() == 1                         # la página ofrece la opción
    pagina.fill("#login-email", email)
    pagina.fill("#login-password", CONTRASENA)
    pagina.click("button.auth-submit[type=submit]")
    pagina.wait_for_load_state("load")
    assert "/login" not in pagina.url, pagina.url
    # 2) Añade la passkey en Ajustes.
    pagina.goto(f"{kratos_pruebas.origen}/ajustes-cuenta")
    assert "Passkeys: entrar con huella, cara o PIN" in pagina.content()
    boton = pagina.locator("[data-passkey-registrar]")
    boton.wait_for(state="visible", timeout=10000)
    boton.click()
    pagina.wait_for_load_state("load")
    pagina.wait_for_url("**/ajustes-cuenta**")
    assert pagina.locator("button[name=passkey_remove]").count() == 1, pagina.content()[-1500:]   # queda registrada: aparece con su botón de quitar
    # 3) Sale y vuelve a entrar solo con la passkey (sin escribir nada).
    pagina.context.clear_cookies()
    pagina.goto(f"{kratos_pruebas.origen}/login")
    entrar = pagina.locator("[data-passkey-login]")
    entrar.wait_for(state="visible", timeout=10000)
    entrar.click()
    pagina.wait_for_url(lambda u: "/login" not in u, timeout=15000)
    pagina.goto(f"{kratos_pruebas.origen}/ajustes-cuenta")
    assert "Passkeys: entrar con huella, cara o PIN" in pagina.content() and "/login" not in pagina.url      # la sesión es de verdad
    assert not [e for e in errores if "Content Security Policy" in e or "Refused" in e], errores
    assert db.obtener_usuario_por_email(email) is not None if hasattr(db, "obtener_usuario_por_email") else True
