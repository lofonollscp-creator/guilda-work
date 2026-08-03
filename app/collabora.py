"""Bootstrap de Collabora Online (CODE, motor LibreOffice, protocolo
WOPI) como editor de documentos de Nextcloud (Drive) — ver
docker-compose.yml (servicio `collabora`) y HOSTING.md.

## Sin aislamiento propio ni aprovisionamiento por tenant

Collabora es un motor de render SIN ESTADO: Nextcloud le manda "edita
este documento con este token de acceso firmado" (protocolo WOPI),
Collabora edita y llama de vuelta para guardar — no guarda nada propio
por tenant. Los Group Folders y permisos de usuario que ya existen en
Nextcloud (ver `app/nextcloud.py`) siguen siendo el único límite de
acceso real. Por eso este módulo no tiene `aprovisionar_tenant()`: la
configuración de abajo se hace UNA VEZ al desplegar, no por tenant.

## Bootstrap — verificado en vivo, CLI-only sin equivalente HTTP

Instalar y activar la app `richdocuments` de Nextcloud (que habla WOPI
con Collabora) solo se puede hacer con el propio `occ` de Nextcloud —
no existe una API HTTP equivalente (mismo tipo de limitación que
`ntfy access`, ver `app/ntfy.py`), así que se ejecuta por `docker exec`
contra el contenedor de Nextcloud, mismo patrón que
`app/ntfy.py:_conceder_acceso`/`app/facturascripts.py:_ejecutar_psql`.

Verificado en vivo contra un Nextcloud y un Collabora reales: los tres
comandos de `bootstrap_richdocuments()` dejan
`occ richdocuments:activate-config` confirmando
`Detected WOPI server: Collabora Online Development Edition` con
capacidades válidas, sin ningún paso manual en la UI.

Idempotente: `app:install` sobre una app ya instalada y
`config:app:set`/`richdocuments:activate-config` repetidos no fallan,
solo confirman el estado ya correcto (comportamiento propio de `occ`,
no algo que este módulo tenga que manejar aparte).
"""
import os
import subprocess

NEXTCLOUD_CONTENEDOR = os.environ.get("NEXTCLOUD_CONTENEDOR", "guilda-work-nextcloud")
COLLABORA_WOPI_URL = os.environ.get("COLLABORA_WOPI_URL", "http://collabora:9980")


class ErrorCollabora(Exception):
    """Error legible para mostrar cuando el bootstrap de Collabora falla."""


def _occ(*args: str) -> None:
    resultado = subprocess.run(
        ["docker", "exec", "-u", "www-data", NEXTCLOUD_CONTENEDOR, "php", "occ", *args],
        capture_output=True, text=True, timeout=120,
    )
    if resultado.returncode != 0:
        raise ErrorCollabora(f"'occ {' '.join(args)}' falló: {resultado.stderr.strip() or resultado.stdout.strip()}")


def bootstrap_richdocuments() -> None:
    """Instala richdocuments, lo apunta al contenedor de Collabora y
    activa/valida la configuración. Paso de despliegue, se llama UNA
    VEZ (ver HOSTING.md), no desde `crear_tenant()` — no hay nada por
    tenant que aprovisionar (ver docstring del módulo)."""
    _occ("app:install", "richdocuments")
    _occ("config:app:set", "richdocuments", "wopi_url", "--value", COLLABORA_WOPI_URL)
    _occ("richdocuments:activate-config")
