"""Aísla cada test en su propia base de datos SQLite temporal.

`db.py` guarda la ruta de la base de datos en el atributo de módulo
`DB_PATH`, y cada función abre/cierra su propia conexión a partir de ese
atributo — así que basta con parchearlo antes de cada test para que ningún
test toque nunca `data/registro.db` de verdad.

Fase 7a.6: los tests que ejercitan login/registro real (vía Kratos, ver
`app/kratos.py`) usan una instancia de Kratos DE VERDAD, separada de la de
desarrollo — no mocks. `docker-compose.test.yml` la levanta en los puertos
14433/14434; el fixture de sesión `kratos_test` de aquí abajo se encarga de
arrancarla, esperar a que esté lista, y apagarla al terminar toda la
sesión de tests. Como Kratos vive durante TODA la sesión (no se reinicia
por test, sería demasiado lento), el fixture `_limpiar_identidades_kratos`
borra todas las identidades después de cada test para que cada uno siga
viendo un Kratos "vacío", igual que ya pasa con la base de datos SQLite.
"""
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import keyring
import keyring.errors
import pytest

from app import db, kratos

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
KRATOS_TEST_PUBLIC_URL = "http://127.0.0.1:14433"
KRATOS_TEST_ADMIN_URL = "http://127.0.0.1:14434"


def _esperar_listo(url: str, timeout: float = 90) -> None:
    limite = time.time() + timeout
    ultimo_error: Exception | None = None
    while time.time() < limite:
        try:
            with urllib.request.urlopen(f"{url}/health/ready", timeout=3) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, OSError) as e:
            ultimo_error = e
        time.sleep(1)
    raise RuntimeError(f"Kratos de test no respondió a tiempo en {url}: {ultimo_error}")


@pytest.fixture(scope="session", autouse=True)
def kratos_test():
    subprocess.run(
        ["docker", "compose", "-f", "docker-compose.test.yml", "up", "-d"],
        cwd=RAIZ_PROYECTO, check=True, timeout=180,
    )
    _esperar_listo(KRATOS_TEST_PUBLIC_URL)
    _esperar_listo(KRATOS_TEST_ADMIN_URL)

    # Todo app/kratos.py pasa a hablar con la instancia de test durante
    # toda la sesión — no hace falta deshacerlo al final, el proceso de
    # pytest termina ahí mismo.
    kratos.KRATOS_PUBLIC_URL = KRATOS_TEST_PUBLIC_URL
    kratos.KRATOS_ADMIN_URL = KRATOS_TEST_ADMIN_URL

    yield

    subprocess.run(
        ["docker", "compose", "-f", "docker-compose.test.yml", "down", "-v"],
        cwd=RAIZ_PROYECTO, check=False, timeout=60,
    )


@pytest.fixture(autouse=True)
def _limpiar_identidades_kratos(kratos_test):
    yield
    try:
        with urllib.request.urlopen(
            f"{KRATOS_TEST_ADMIN_URL}/admin/identities?per_page=1000", timeout=5
        ) as resp:
            identidades = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return
    for identidad in identidades:
        try:
            peticion = urllib.request.Request(
                f"{KRATOS_TEST_ADMIN_URL}/admin/identities/{identidad['id']}", method="DELETE"
            )
            urllib.request.urlopen(peticion, timeout=5)
        except (urllib.error.URLError, OSError):
            pass


@pytest.fixture(autouse=True)
def base_de_datos_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(db, "BACKUPS_DIR", tmp_path / "backups")
    db.init_db()
    yield


@pytest.fixture
def usuario_id() -> int:
    """El 'usuario local' (mismo que resuelve la app de escritorio y el MCP),
    ya creado automáticamente por db.init_db() en base_de_datos_temporal."""
    return db.usuario_local_id()


@pytest.fixture
def cliente(base_de_datos_temporal):
    """Cliente de test de Flask para app/rutas_api.py (Fase 2). Se importa
    aquí dentro (no al nivel de módulo) para que la base de datos temporal
    ya esté activa cuando app.main se registre sus blueprints."""
    from app.auth import limiter
    from app.main import app as flask_app

    # SERVER_NAME fijado a 127.0.0.1:8000 (Fase 7a): las `ui_url`/
    # `default_browser_return_url` de deploy/kratos/kratos.yml apuntan ahí,
    # así que las redirecciones que Kratos manda de vuelta también lo
    # hacen — sin esto, el cliente de test de Werkzeug las trata como
    # "externas" y se niega a seguirlas (`follow_redirects=True` fallaría).
    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    # El límite de intentos en /auth/login y /auth/registro (Fase 3, contra
    # fuerza bruta) usa un almacén en memoria a nivel de proceso — sin
    # resetearlo aquí, los tests que registran varios usuarios de seguido se
    # agotarían la cuota entre sí y fallarían con 429 por algo ajeno a lo que
    # están probando.
    limiter.reset()
    with flask_app.test_client() as client:
        yield client


def iniciar_sesion_de_prueba(client, email: str, contrasena: str) -> int:
    """Crea un usuario real en Kratos + su fila local, e inicia sesión de
    verdad siguiendo el mismo camino que un navegador (GET /login → sigue
    la redirección hasta Kratos y de vuelta con `?flow=` → POST al proxy
    `/.ory/self-service/login`) — deja la cookie de sesión de Kratos puesta
    en `client`, lista para usar en peticiones posteriores a rutas con
    `@login_required`. Devuelve el `usuario_id` local ya vinculado."""
    identity_id = kratos.crear_identidad(email, contrasena)
    usuario_id = db.crear_usuario_vinculado_a_kratos(email, identity_id)

    resp = client.get("/login", follow_redirects=True)
    html = resp.get_data(as_text=True)
    flow_id = re.search(r"[?&]flow=([0-9a-f-]+)", resp.request.url).group(1)
    csrf = re.search(r'name="csrf_token" value="([^"]*)"', html).group(1)

    client.post(
        f"/.ory/self-service/login?flow={flow_id}",
        data={"csrf_token": csrf, "identifier": email, "password": contrasena, "method": "password"},
        follow_redirects=True,
    )
    return usuario_id


@pytest.fixture(autouse=True)
def keyring_en_memoria(monkeypatch):
    """Sustituye keyring por un almacén en memoria durante los tests, para no
    tocar el Windows Credential Manager real al probar app/correo.py."""
    almacen: dict[tuple[str, str], str] = {}

    def fake_set(servicio, usuario, contrasena):
        almacen[(servicio, usuario)] = contrasena

    def fake_get(servicio, usuario):
        return almacen.get((servicio, usuario))

    def fake_delete(servicio, usuario):
        if (servicio, usuario) not in almacen:
            raise keyring.errors.PasswordDeleteError("no password set")
        del almacen[(servicio, usuario)]

    monkeypatch.setattr(keyring, "set_password", fake_set)
    monkeypatch.setattr(keyring, "get_password", fake_get)
    monkeypatch.setattr(keyring, "delete_password", fake_delete)
    yield
