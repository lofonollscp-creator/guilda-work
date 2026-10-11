"""Imágenes de Docker: lo que corre en producción va fijado por digest (`imagen:tag@sha256:...`). Un `:latest` sin fijar puede
cambiar solo en el siguiente `docker compose pull` y romper un servicio sin aviso."""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Servicios definidos en docker-compose.yml pero NO desplegados en este servidor (no hay imagen local ni contenedor).
# Antes de desplegar uno hay que fijarlo: `docker pull`, `docker image inspect --format '{{index .RepoDigests 0}}'` y
# poner ese digest en el compose; después se quita de esta lista. Una imagen nueva sin digest que NO esté aquí falla el test.
NO_DESPLEGADAS = {
    "baserow/baserow:latest",
    "binwiederhier/ntfy:latest",
    "caddy:latest",
    "chatwoot/chatwoot:latest",
    "collabora/code:latest",
    "docker.umami.is/umami-software/umami:postgresql-latest",
    "espocrm/espocrm:latest",
    "ghcr.io/coleifer/sqlite-web:latest",
    "ghcr.io/jitsi/jicofo:unstable",
    "ghcr.io/jitsi/jvb:unstable",
    "ghcr.io/jitsi/prosody:unstable",
    "ghcr.io/jitsi/web:unstable",
    "ghcr.io/paperless-ngx/paperless-ngx:latest",
    "listmonk/listmonk:latest",
    "memcached:alpine",
    "metabase/metabase:latest",
    "openproject/openproject:${OPENPROJECT_TAG:-15-slim}",
    "pgvector/pgvector:pg16",
    "portainer/portainer-ce:latest",
    "postgres:17-alpine",
}


def test_toda_imagen_desplegada_va_fijada_por_digest():
    imagenes = set(re.findall(r"^\s*image:\s*(\S+)", (RAIZ / "docker-compose.yml").read_text(encoding="utf-8"), re.M))
    sin_fijar = {i for i in imagenes if "@sha256" not in i}
    nuevas = sorted(sin_fijar - NO_DESPLEGADAS)
    assert not nuevas, f"imágenes sin digest que no están en NO_DESPLEGADAS (fíjalas): {nuevas}"


def test_la_lista_de_no_desplegadas_no_guarda_imagenes_que_ya_se_fijaron():
    imagenes = set(re.findall(r"^\s*image:\s*(\S+)", (RAIZ / "docker-compose.yml").read_text(encoding="utf-8"), re.M))
    obsoletas = sorted(i for i in NO_DESPLEGADAS if i not in imagenes or "@sha256" in i)
    assert not obsoletas, f"quítalas de NO_DESPLEGADAS (ya están fijadas o ya no existen): {obsoletas}"
