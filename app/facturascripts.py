"""Cliente de FacturaScripts (Fase facturación) — a diferencia de
EspoCRM/Nextcloud (una instancia compartida con aislamiento lógico por
Equipo/Grupo), cada tenant tiene aquí su PROPIA instancia física + base
de datos: investigado el plugin oficial "MultiEmpresa" y confirmado que
NO restringe qué usuario ve qué empresa — solo aplica valores por
defecto diferenciados, no es un mecanismo de control de acceso. Con
datos económicos de por medio, apoyarse en eso no es aceptable.

## Aprovisionamiento (`aprovisionar_tenant`/`desaprovisionar_tenant`)

Sin precedente en el resto de `app/*.py`: aquí SÍ se orquesta Docker
desde Python (`docker run`/`docker exec`/`docker stop`/`docker rm` vía
`subprocess`) — el resto de integraciones solo hablan HTTP con
contenedores que ya existen de antemano en `docker-compose.yml`. Esto
funciona porque `serve.py` ya corre con privilegios normales de usuario
directamente en el host (fuera de Docker, ver `app/kratos.py`) — no es
una escalada de privilegios nueva, solo la primera vez que se usa ese
mismo nivel de acceso para crear contenedores en vez de solo llamarlos.
Requiere que el usuario del sistema que ejecuta `serve.py` esté en el
grupo `docker` (ver HOSTING.md 8.21).

Investigado en el código fuente real del instalador de FacturaScripts
(`Core/Controller/Installer.php`): SÍ documenta instalación desatendida
por un único `POST` con `unattended=1` — pero **verificado en vivo,
contra un contenedor real, que esa vía está rota en la versión
publicada actualmente** (`facturascripts/facturascripts:latest`, core
2026.41): `Plugins::deploy()` se ejecuta dentro de la misma petición
HTTP que aún no tiene `config.php` cargado en memoria, y revienta con
`Undefined constant FS_DEBUG` — 100% reproducible en contenedores
recién creados, no es un problema de los parámetros mandados (se probó
con varias combinaciones distintas).

**Solución encontrada y verificada en vivo**: en vez de la ruta HTTP del
instalador, se escribe `config.php`/`.htaccess` directamente en el
contenedor (`docker cp`/`docker exec`, contenido idéntico al que
`Installer::saveInstall()` generaría) y se dispara `Plugins::deploy()`
en un proceso PHP nuevo y aislado vía `docker exec ... php -r` — ahí
`config.php` sí se carga desde cero sin el problema de orden de
inicialización, y confirmado que arranca limpio (login real accesible,
usuario `admin` creado en la tabla `users`). El propio arranque de
FacturaScripts crea el esquema de tablas solo, con la base de datos ya
creada de antemano (ver más abajo).

Aislamiento real entre tenants: cada base de datos vive en el mismo
servidor PostgreSQL compartido (`postgres-facturascripts`,
`docker-compose.yml`), pero cada contenedor de FacturaScripts solo
conoce las credenciales de SU PROPIO rol — y ese rol tiene
`REVOKE CONNECT ... FROM PUBLIC` sobre su base, así que ni siquiera con
una fuga de credenciales de otro tenant se podría conectar sin más (hay
que ser ya el propio rol dueño, o superusuario).

## API de negocio (`listar_clientes`/`crear_cliente`/`listar_facturas`/`crear_factura`)

A diferencia del resto de `app/*.py`, estas funciones NO leen su URL/
credencial de una variable de entorno fija — cada tenant tiene las
suyas, guardadas en `tenants.facturascripts_url`/`facturascripts_api_key`
(`app/db.py`). Quien llama (`mcp_tools.py`) resuelve esas dos cosas por
tenant y las pasa explícitas — mismo criterio de desacoplo que el resto
de clientes de este módulo respecto a `app/db.py` (nunca lo importan
directamente).
"""
import json
import os
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

FACTURASCRIPTS_POSTGRES_HOST = "postgres-facturascripts"
FACTURASCRIPTS_POSTGRES_CONTENEDOR = "guilda-work-postgres-facturascripts"
FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD = os.environ.get("FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD")
FACTURASCRIPTS_RED_DOCKER = os.environ.get("FACTURASCRIPTS_RED_DOCKER", "eleganza_default")
PUERTO_BASE = 8100
TIMEOUT_SEGUNDOS = 10


class ErrorFacturaScripts(Exception):
    """Error legible para mostrar cuando FacturaScripts (o su
    aprovisionamiento) falla."""


def _puerto_tenant(tenant_id: int) -> int:
    return PUERTO_BASE + tenant_id


def _nombre_contenedor(tenant_id: int) -> str:
    return f"guilda-work-facturascripts-tenant-{tenant_id}"


def _nombre_rol(tenant_id: int) -> str:
    return f"fs_tenant_{tenant_id}"


def _nombre_bd(tenant_id: int) -> str:
    return f"facturascripts_tenant_{tenant_id}"


def _ejecutar_psql(sql: str) -> None:
    """Ejecuta SQL contra el Postgres compartido vía `docker exec`, mismo
    patrón que ya usa este proyecto para comandos de un solo uso dentro
    de un contenedor (ver app/chatwoot.py, alta del PlatformApp por
    consola de Rails)."""
    if not FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD:
        raise ErrorFacturaScripts("FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD no está configurada.")
    resultado = subprocess.run(
        [
            "docker", "exec", "-e", f"PGPASSWORD={FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD}",
            FACTURASCRIPTS_POSTGRES_CONTENEDOR,
            "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-c", sql,
        ],
        capture_output=True, text=True, timeout=30,
    )
    if resultado.returncode != 0:
        raise ErrorFacturaScripts(f"psql falló ejecutando '{sql}': {resultado.stderr.strip()}")


def _docker_run(tenant_id: int, db_user: str, db_pass: str, db_name: str) -> None:
    puerto = _puerto_tenant(tenant_id)
    resultado = subprocess.run(
        [
            "docker", "run", "-d",
            "--name", _nombre_contenedor(tenant_id),
            "--network", FACTURASCRIPTS_RED_DOCKER,
            "--restart", "unless-stopped",
            "-p", f"127.0.0.1:{puerto}:80",
            "facturascripts/facturascripts:latest",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if resultado.returncode != 0:
        raise ErrorFacturaScripts(f"'docker run' falló para el tenant {tenant_id}: {resultado.stderr.strip()}")


def _esperar_arranque(url: str, intentos: int = 15, espera_segundos: float = 2.0) -> None:
    for _ in range(intentos):
        try:
            with urllib.request.urlopen(url, timeout=5):
                return
        except (urllib.error.URLError, TimeoutError, ConnectionResetError):
            time.sleep(espera_segundos)
    raise ErrorFacturaScripts(f"El contenedor de FacturaScripts no respondió en {url} tras {intentos} intentos.")


def _escapar_php(valor: str) -> str:
    """Mismo escapado que Installer::escapeConfig() en el propio
    FacturaScripts — evita que una comilla o barra invertida (p. ej. en
    una contraseña generada) rompa el config.php resultante."""
    return valor.replace("\\", "\\\\").replace("'", "\\'")


def _generar_config_php(db_host: str, db_user: str, db_pass: str, db_name: str, admin_user: str, admin_pass: str) -> str:
    """Mismo formato que escribiría Installer::saveInstall() — reproducido
    aquí porque esa ruta HTTP está rota en la versión actual (ver
    docstring del módulo), no porque el formato en sí sea un secreto."""
    e = _escapar_php
    return (
        "<?php\n"
        "define('FS_COOKIES_EXPIRE', 31536000);\n"
        "define('FS_ROUTE', '');\n"
        "define('FS_DB_TYPE', 'postgresql');\n"
        f"define('FS_DB_HOST', '{e(db_host)}');\n"
        "define('FS_DB_PORT', 5432);\n"
        f"define('FS_DB_NAME', '{e(db_name)}');\n"
        f"define('FS_DB_USER', '{e(db_user)}');\n"
        f"define('FS_DB_PASS', '{e(db_pass)}');\n"
        "define('FS_DB_FOREIGN_KEYS', true);\n"
        "define('FS_DB_TYPE_CHECK', true);\n"
        "define('FS_PGSQL_SSL', '');\n"
        "define('FS_PGSQL_ENDPOINT', '');\n"
        "define('FS_LANG', 'es_ES');\n"
        "define('FS_TIMEZONE', 'Europe/Madrid');\n"
        "define('FS_HIDDEN_PLUGINS', '');\n"
        "define('FS_DISABLE_ADD_PLUGINS', false);\n"
        "define('FS_DISABLE_RM_PLUGINS', false);\n"
        "define('FS_DEBUG', false);\n"
        f"define('FS_INITIAL_USER', '{e(admin_user)}');\n"
        f"define('FS_INITIAL_PASS', '{e(admin_pass)}');\n"
    )


def _instalar(tenant_id: int, db_user: str, db_pass: str, db_name: str, admin_user: str, admin_pass: str) -> None:
    """Instala FacturaScripts escribiendo config.php/.htaccess
    directamente en el contenedor y disparando Plugins::deploy() por
    CLI — ver docstring del módulo para por qué no se usa la ruta HTTP
    documentada del instalador (rota en la versión actual)."""
    contenedor = _nombre_contenedor(tenant_id)
    config = _generar_config_php(FACTURASCRIPTS_POSTGRES_HOST, db_user, db_pass, db_name, admin_user, admin_pass)

    with tempfile.NamedTemporaryFile("w", suffix=".php", delete=False, encoding="utf-8") as f:
        f.write(config)
        ruta_temporal = f.name
    try:
        resultado = subprocess.run(
            ["docker", "cp", ruta_temporal, f"{contenedor}:/var/www/html/config.php"],
            capture_output=True, text=True, timeout=15,
        )
        if resultado.returncode != 0:
            raise ErrorFacturaScripts(f"No se ha podido copiar config.php al contenedor: {resultado.stderr.strip()}")
    finally:
        os.unlink(ruta_temporal)

    resultado = subprocess.run(
        [
            "docker", "exec", contenedor, "sh", "-c",
            "cp /var/www/html/htaccess-sample /var/www/html/.htaccess && "
            "mkdir -p /var/www/html/Plugins /var/www/html/Dinamic /var/www/html/MyFiles && "
            "chmod -R o+w /var/www/html",
        ],
        capture_output=True, text=True, timeout=15,
    )
    if resultado.returncode != 0:
        raise ErrorFacturaScripts(f"No se ha podido preparar el contenedor: {resultado.stderr.strip()}")

    resultado = subprocess.run(
        [
            "docker", "exec", "-w", "/var/www/html", contenedor, "php", "-r",
            "define('FS_FOLDER', '/var/www/html'); require 'vendor/autoload.php'; "
            "require 'config.php'; \\FacturaScripts\\Core\\Plugins::deploy(); echo 'DEPLOY_OK';",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if resultado.returncode != 0 or "DEPLOY_OK" not in resultado.stdout:
        raise ErrorFacturaScripts(f"Plugins::deploy() falló en el tenant {tenant_id}: {resultado.stderr.strip()}")

    # Plugins::deploy() corre como root (docker exec sin --user) y crea
    # sobre la marcha directorios de caché nuevos (MyFiles/Tmp/FileCache)
    # que el `chmod -R o+w` de más arriba no llegó a cubrir porque aún no
    # existían — Apache corre como www-data y sin este segundo chmod, el
    # propio arranque real deja warnings de "Permission denied" en cada
    # página (confirmado en vivo contra un tenant ya aprovisionado).
    resultado = subprocess.run(
        ["docker", "exec", contenedor, "chmod", "-R", "o+w", "/var/www/html"],
        capture_output=True, text=True, timeout=15,
    )
    if resultado.returncode != 0:
        raise ErrorFacturaScripts(f"No se han podido fijar permisos tras el deploy: {resultado.stderr.strip()}")


def _verificar_arranque_completo(url: str) -> None:
    """Comprueba que la app responde de verdad tras la instalación (no
    solo que el contenedor acepta conexiones, ver _esperar_arranque) —
    cualquier cosa menos 200/301/302 significa que algo del paso
    anterior no terminó de cuajar."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SEGUNDOS) as resp:
            estado = resp.status
    except urllib.error.HTTPError as e:
        estado = e.code
    if estado >= 500:
        raise ErrorFacturaScripts(f"FacturaScripts respondió con un error de servidor ({estado}) tras instalar en {url}.")


def aprovisionar_tenant(tenant_id: int, nombre_tenant: str) -> dict:
    """Crea el rol+base de datos, el contenedor y completa la instalación
    desatendida para un tenant nuevo. Devuelve {"url", "admin_user",
    "admin_pass"} para que quien llama (app/rutas_backoffice.py) los
    guarde con db.guardar_facturascripts() — este módulo nunca importa
    app/db.py directamente, mismo criterio que el resto de app/*.py."""
    if not FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD:
        raise ErrorFacturaScripts("FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD no está configurada.")

    rol = _nombre_rol(tenant_id)
    bd = _nombre_bd(tenant_id)
    db_pass = secrets.token_urlsafe(24)
    admin_user = "admin"
    admin_pass = secrets.token_urlsafe(16)

    _ejecutar_psql(f"CREATE ROLE {rol} LOGIN PASSWORD '{db_pass}';")
    _ejecutar_psql(f"CREATE DATABASE {bd} OWNER {rol};")
    _ejecutar_psql(f"REVOKE CONNECT ON DATABASE {bd} FROM PUBLIC;")

    _docker_run(tenant_id, rol, db_pass, bd)

    url = f"http://127.0.0.1:{_puerto_tenant(tenant_id)}/"
    _esperar_arranque(url)
    _instalar(tenant_id, rol, db_pass, bd, admin_user, admin_pass)
    _verificar_arranque_completo(url)

    return {"url": url, "admin_user": admin_user, "admin_pass": admin_pass}


def desaprovisionar_tenant(tenant_id: int) -> None:
    """Para al borrar un tenant (app/rutas_backoffice.py:borrar_tenant) —
    para/borra el contenedor y elimina su base de datos y rol. No falla
    si alguna pieza ya no existe (idempotente ante reintentos)."""
    subprocess.run(["docker", "stop", _nombre_contenedor(tenant_id)], capture_output=True, timeout=30)
    subprocess.run(["docker", "rm", _nombre_contenedor(tenant_id)], capture_output=True, timeout=30)
    if not FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD:
        return
    try:
        _ejecutar_psql(f"DROP DATABASE IF EXISTS {_nombre_bd(tenant_id)};")
        _ejecutar_psql(f"DROP ROLE IF EXISTS {_nombre_rol(tenant_id)};")
    except ErrorFacturaScripts:
        pass  # el contenedor/red puede no existir ya — no bloquea borrar el tenant


# --- API de negocio (Fase MCP) -----------------------------------------------

def _peticion(url: str, api_key: str, endpoint: str, *, metodo: str = "GET", cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    cabeceras = {"Accept": "application/json", "Token": api_key}
    if datos is not None:
        cabeceras["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{url.rstrip('/')}/api/3/{endpoint}", data=datos, headers=cabeceras, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            cuerpo_resp = resp.read().decode("utf-8")
            return resp.status, (json.loads(cuerpo_resp) if cuerpo_resp else {})
    except urllib.error.HTTPError as e:
        cuerpo_error = e.read().decode("utf-8")
        try:
            return e.code, json.loads(cuerpo_error)
        except json.JSONDecodeError:
            return e.code, {"error": cuerpo_error}
    except urllib.error.URLError as e:
        raise ErrorFacturaScripts(
            f"No se ha podido conectar con FacturaScripts ({url}). ¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError as e:
        raise ErrorFacturaScripts(f"Tiempo de espera agotado al contactar con FacturaScripts ({url}).")


def listar_clientes(url: str, api_key: str, texto: str | None = None, limite: int = 20) -> list[dict]:
    """Lista/busca clientes. [] si `url`/`api_key` están vacíos (tenant
    sin FacturaScripts aprovisionado todavía, o sin API Key guardada)."""
    if not url or not api_key:
        return []
    parametros = {"limit": limite}
    if texto:
        parametros["nombre_like"] = f"%{texto}%"
    estado, cuerpo = _peticion(url, api_key, f"clientes?{urllib.parse.urlencode(parametros)}")
    if estado != 200:
        mensaje = cuerpo.get("message") or cuerpo.get("error") or cuerpo
        raise ErrorFacturaScripts(f"No se han podido listar los clientes de FacturaScripts: {mensaje}")
    return cuerpo if isinstance(cuerpo, list) else cuerpo.get("data", [])


def crear_cliente(url: str, api_key: str, nombre: str, nif: str = "", email: str = "") -> dict:
    if not url or not api_key:
        raise ErrorFacturaScripts("Este tenant no tiene FacturaScripts configurado todavía.")
    estado, cuerpo = _peticion(
        url, api_key, "clientes", metodo="POST",
        cuerpo={"nombre": nombre, "cifnif": nif, "email": email},
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("message") or cuerpo.get("error") or cuerpo
        raise ErrorFacturaScripts(f"No se ha podido crear el cliente '{nombre}' en FacturaScripts: {mensaje}")
    return cuerpo


def listar_facturas(url: str, api_key: str, cliente_codigo: str | None = None, limite: int = 20) -> list[dict]:
    if not url or not api_key:
        return []
    parametros = {"limit": limite}
    if cliente_codigo:
        parametros["codcliente"] = cliente_codigo
    estado, cuerpo = _peticion(url, api_key, f"facturaclientes?{urllib.parse.urlencode(parametros)}")
    if estado != 200:
        mensaje = cuerpo.get("message") or cuerpo.get("error") or cuerpo
        raise ErrorFacturaScripts(f"No se han podido listar las facturas de FacturaScripts: {mensaje}")
    return cuerpo if isinstance(cuerpo, list) else cuerpo.get("data", [])


def crear_factura(url: str, api_key: str, cliente_codigo: str, lineas: list[dict]) -> dict:
    """`lineas`: lista de {"descripcion": str, "cantidad": float, "precio": float}."""
    if not url or not api_key:
        raise ErrorFacturaScripts("Este tenant no tiene FacturaScripts configurado todavía.")
    estado, cuerpo = _peticion(
        url, api_key, "crearFacturaCliente", metodo="POST",
        cuerpo={"codcliente": cliente_codigo, "lineas": lineas},
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("message") or cuerpo.get("error") or cuerpo
        raise ErrorFacturaScripts(f"No se ha podido crear la factura en FacturaScripts: {mensaje}")
    return cuerpo
