"""Aísla cada test en su propia base de datos SQLite temporal.

`db.py` guarda la ruta de la base de datos en el atributo de módulo
`DB_PATH`, y cada función abre/cierra su propia conexión a partir de ese
atributo — así que basta con parchearlo antes de cada test para que ningún
test toque nunca `data/registro.db` de verdad.

Fase 7a.6: los tests que ejercitan login/registro real (vía Kratos, ver
`app/kratos.py`) usan una instancia de Kratos DE VERDAD, separada de la de
desarrollo — no mocks. `docker-compose.test.yml` la levanta con un nombre de
proyecto y un par de puertos libres propios de cada ejecución (dos pytest
simultáneos no se pisan); el fixture de sesión `kratos_test` de aquí abajo se encarga de
arrancarla, esperar a que esté lista, y apagarla al terminar toda la
sesión de tests. Como Kratos vive durante TODA la sesión (no se reinicia
por test, sería demasiado lento), el fixture `_limpiar_identidades_kratos`
borra todas las identidades después de cada test para que cada uno siga
viendo un Kratos "vacío", igual que ya pasa con la base de datos SQLite.
"""
import atexit
import json
import os
import re
import signal
import socket
import sys
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


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# Puertos y proyecto de docker compose propios de ESTA ejecución de pytest
# (ver el comentario de docker-compose.test.yml).
KRATOS_TEST_PUBLIC_PORT = _puerto_libre()
KRATOS_TEST_ADMIN_PORT = _puerto_libre()
while KRATOS_TEST_ADMIN_PORT == KRATOS_TEST_PUBLIC_PORT:
    KRATOS_TEST_ADMIN_PORT = _puerto_libre()
KRATOS_TEST_PUBLIC_URL = f"http://127.0.0.1:{KRATOS_TEST_PUBLIC_PORT}"
KRATOS_TEST_ADMIN_URL = f"http://127.0.0.1:{KRATOS_TEST_ADMIN_PORT}"
COMPOSE_TEST = ["docker", "compose", "-p", f"guilda-test-{os.getpid()}", "-f", "docker-compose.test.yml"]
ENTORNO_COMPOSE_TEST = {
    **os.environ,
    "KRATOS_TEST_PUBLIC_PORT": str(KRATOS_TEST_PUBLIC_PORT),
    "KRATOS_TEST_ADMIN_PORT": str(KRATOS_TEST_ADMIN_PORT),
}


def _bajar_kratos_test() -> None:
    """Apaga y borra (contenedores, red y volúmenes) el Kratos de ESTA ejecución. Es idempotente: se llama al terminar la sesión, desde `atexit` y si el arranque falla a medias."""
    subprocess.run([*COMPOSE_TEST, "down", "-v", "--remove-orphans"], cwd=RAIZ_PROYECTO, check=False, timeout=90, env=ENTORNO_COMPOSE_TEST,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


_PROYECTO_DE_PRUEBA = re.compile(r"^guilda-test-(\d+)$")


def _pid_vivo(pid: int) -> bool:
    return Path(f"/proc/{pid}").exists()


def limpiar_kratos_huerfanos(ejecutar=subprocess.run, pid_vivo=_pid_vivo) -> list[str]:
    """Quita los Kratos de prueba que dejó una ejecución de pytest que murió sin limpiar (SIGKILL, corte del terminal, fallo al arrancar): proyectos `guilda-test-<pid>` cuyo pid ya no existe.
    Nunca toca el de una ejecución en marcha (su pid sigue vivo) ni nada que no se llame exactamente así (los contenedores `guilda-work-*` de producción quedan fuera). Devuelve los proyectos limpiados."""
    r = ejecutar(["docker", "ps", "-a", "--format", '{{.Label "com.docker.compose.project"}}'], capture_output=True, text=True, check=False, timeout=30)
    limpiados = []
    for proyecto in sorted({linea.strip() for linea in (r.stdout or "").splitlines()}):
        m = _PROYECTO_DE_PRUEBA.match(proyecto)
        if not m or pid_vivo(int(m.group(1))):
            continue
        etiqueta = f"label=com.docker.compose.project={proyecto}"
        ids = ejecutar(["docker", "ps", "-aq", "--filter", etiqueta], capture_output=True, text=True, check=False, timeout=30).stdout.split()
        if ids:
            ejecutar(["docker", "rm", "-f", "-v", *ids], check=False, timeout=90, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ejecutar(["docker", "network", "rm", f"{proyecto}_default"], check=False, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        limpiados.append(proyecto)
    return limpiados


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


SIN_KRATOS = os.environ.get("GUILDA_SIN_KRATOS") == "1"


def pytest_configure(config):
    config.addinivalue_line("markers", "kratos: necesita la instancia real de Kratos (login/registro reales)")


def pytest_collection_modifyitems(config, items):
    """Marca como `kratos` los tests que necesitan Kratos de verdad (los que usan el
    cliente HTTP `cliente`, o cuyo fichero inicia sesión real / habla con kratos).
    Con GUILDA_SIN_KRATOS=1 (scripts/probar.sh --rapida) se saltan y Kratos ni se
    arranca: es el modo rápido para comprobar lógica de datos sin Docker."""
    huella = ("iniciar_sesion_de_prueba", "kratos_test", "crear_identidad")
    cache: dict[str, bool] = {}
    descartados = []
    for item in items:
        ruta = str(item.fspath)
        if ruta not in cache:
            cache[ruta] = any(h in Path(ruta).read_text(encoding="utf-8", errors="ignore") for h in huella)
        if "cliente" in item.fixturenames or cache[ruta]:
            item.add_marker(pytest.mark.kratos)
            if SIN_KRATOS:
                descartados.append(item)
    if descartados:
        config.hook.pytest_deselected(items=descartados)
        items[:] = [i for i in items if i not in descartados]


@pytest.fixture(scope="session", autouse=True)
def kratos_test():
    if SIN_KRATOS:
        yield
        return
    limpiar_kratos_huerfanos()          # restos de ejecuciones anteriores que murieron sin limpiar
    atexit.register(_bajar_kratos_test)  # también si pytest termina por una excepción o una señal que lo hace salir
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # `kill` o el límite de tiempo de un terminal: sale por la vía normal y limpia
    try:
        subprocess.run(
            [*COMPOSE_TEST, "up", "-d"],
            cwd=RAIZ_PROYECTO, check=True, timeout=180, env=ENTORNO_COMPOSE_TEST,
        )
        _esperar_listo(KRATOS_TEST_PUBLIC_URL)
        _esperar_listo(KRATOS_TEST_ADMIN_URL)

        # Todo app/kratos.py pasa a hablar con la instancia de test durante
        # toda la sesión — no hace falta deshacerlo al final, el proceso de
        # pytest termina ahí mismo.
        kratos.KRATOS_PUBLIC_URL = KRATOS_TEST_PUBLIC_URL
        kratos.KRATOS_ADMIN_URL = KRATOS_TEST_ADMIN_URL

        yield
    finally:
        _bajar_kratos_test()            # si `up` o la espera fallan a medias, lo ya levantado se quita igual


@pytest.fixture(autouse=True)
def _limpiar_identidades_kratos(kratos_test):
    yield
    if SIN_KRATOS:
        return
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


@pytest.fixture(scope="session")
def _plantilla_bd(tmp_path_factory):
    """Esquema ya creado UNA vez por sesión: init_db() (decenas de tablas y
    migraciones) tarda ~0,2 s y se repetía en cada uno de los ~1500 tests; copiar
    el fichero ya inicializado es casi instantáneo y deja exactamente lo mismo."""
    import sqlite3
    ruta = tmp_path_factory.mktemp("plantilla") / "plantilla.db"
    original = db.DB_PATH
    db.DB_PATH = ruta
    try:
        db.init_db()
    finally:
        db.DB_PATH = original
    db.cerrar_conexiones_compartidas()      # la plantilla se copia: ninguna conexión del pool puede quedar abierta sobre ella
    conexion = sqlite3.connect(ruta)
    conexion.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conexion.execute("PRAGMA journal_mode = DELETE")
    conexion.close()
    return ruta


@pytest.fixture(autouse=True)
def base_de_datos_temporal(tmp_path, monkeypatch, _plantilla_bd):
    import shutil
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(db, "BACKUPS_DIR", tmp_path / "backups")
    shutil.copyfile(_plantilla_bd, db.DB_PATH)
    db._ULTIMO_ACCESO_ANOTADO.clear()  # memoria del proceso: no puede arrastrarse de un test a otro
    from app import acceso
    acceso.invalidar()                 # ídem: la caché de «¿este despacho usa oficinas?» va por id de despacho, y cada test reinicia los ids
    db.init_db()  # sobre el esquema ya hecho solo repasa lo idempotente (algunos tests dependen de ello)
    yield
    db.cerrar_conexiones_compartidas()      # y no se acumulan conexiones a ficheros que ya no existirán
    # Cada test deja de ocupar disco al terminar: con ~2.500 tests y un esquema de cientos de tablas, las copias de la base acumuladas llenaban el /tmp del VPS (un tmpfs de 3,8 GB).
    for sufijo in ("", "-wal", "-shm", "-journal"):
        (tmp_path / f"test.db{sufijo}").unlink(missing_ok=True)
    shutil.rmtree(tmp_path / "backups", ignore_errors=True)


@pytest.fixture(autouse=True)
def _reiniciar_contador_captcha():
    """El contador de fallos de login del captcha de respaldo
    (app/rutas_kratos_proxy.py) es un diccionario a nivel de módulo, no
    algo que dependa de la base de datos temporal -- sin resetearlo entre
    tests, un test que provoca 3 fallos de login desde 127.0.0.1 (la IP
    por defecto del cliente de test, sin X-Forwarded-For) deja esa IP
    marcada para el resto de la sesión de pytest, y CUALQUIER test
    posterior que inicie sesión de verdad (vía iniciar_sesion_de_prueba,
    sin campo altcha) desde esa misma IP se queda sin sesión sin motivo
    aparente. Mismo criterio de aislamiento que ya aplica
    base_de_datos_temporal a data/registro.db."""
    from app import rutas_kratos_proxy

    rutas_kratos_proxy._fallos_por_ip.clear()
    yield
    rutas_kratos_proxy._fallos_por_ip.clear()


@pytest.fixture(autouse=True)
def _despachos_bloqueados():
    """Los desbloqueos del cifrado viven en memoria del proceso: ningún test puede heredar el de otro (los ids de despacho se repiten entre tests)."""
    from app import cifrado_despacho

    cifrado_despacho.bloquear_todo()
    yield
    cifrado_despacho.bloquear_todo()


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
    from app import auth as _auth_api
    _auth_api.reiniciar_limite_api()
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


@pytest.fixture(autouse=True)
def webhooks_sin_hilo_de_fondo(monkeypatch):
    """El hilo de entrega de webhooks no debe arrancar en los tests: viviría más que cada base temporal y haría
    peticiones reales. Los tests de webhooks llaman a `eventos.procesar_pendientes()` a mano."""
    from app import eventos

    monkeypatch.setattr(eventos, "iniciar_worker", lambda: None)


@pytest.fixture(autouse=True)
def sin_tocar_contenedores_ni_datos_de_produccion(monkeypatch, tmp_path):
    """CAUSA RAÍZ de las «caídas» de FacturaScripts que el vigilante reparaba cada pocos minutos: con una base temporal el primer tenant
    es siempre el 1, y los tests de «borrar tenant» llamaban al `facturascripts.desaprovisionar_tenant(1)` REAL, que hace `docker stop` +
    `docker rm` del contenedor de producción `guilda-work-facturascripts-tenant-1` y `rmtree` de sus datos (MyFiles/Plugins/Dinamic) en el
    segundo disco. Cada ejecución de la suite tumbaba el FacturaScripts del despacho.

    Dos capas: (1) los nombres de contenedor y la carpeta de datos de FacturaScripts apuntan a nombres/rutas de prueba; (2) red de seguridad
    general: cualquier `docker stop/rm/kill/restart` sobre un contenedor `guilda-work-*` (los de producción) aborta el test con un error claro."""
    import subprocess

    from app import facturascripts

    monkeypatch.setattr(facturascripts, "_nombre_contenedor", lambda tenant_id: f"guilda-test-facturascripts-tenant-{tenant_id}")
    monkeypatch.setattr(facturascripts, "FACTURASCRIPTS_DATOS_HOST", str(tmp_path / "facturascripts-tenants"))

    ejecutar_real = subprocess.run

    def ejecutar_con_guarda(argumentos, *args, **kwargs):
        if isinstance(argumentos, (list, tuple)) and argumentos[:1] == ["docker"] and len(argumentos) > 1:
            verbo = next((a for a in argumentos[1:] if not a.startswith("-")), "")
            if verbo in {"stop", "rm", "kill", "restart", "rmi", "down"} and any(str(a).startswith("guilda-work-") for a in argumentos):
                raise RuntimeError(f"Un test intentó tocar un contenedor de PRODUCCIÓN: {' '.join(map(str, argumentos))}")
        return ejecutar_real(argumentos, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", ejecutar_con_guarda)


@pytest.fixture(autouse=True)
def correo_sin_hilos_de_empuje(monkeypatch):
    """`correo._encolar_y_lanzar` lanza un hilo que espera 1,5 s y procesa las operaciones de la cuenta N. Con bases temporales los ids se
    repiten (cuenta 1 en cada test), así que el hilo de un test anterior podía aplicar las operaciones del siguiente y descuadrar su
    recuento (apareció al acelerar la suite con -n). Los tests que lo necesitan llaman a `procesar_operaciones_cuenta` a mano."""
    from app import correo

    monkeypatch.setattr(correo, "_SIN_SEGUNDO_PLANO", True)
