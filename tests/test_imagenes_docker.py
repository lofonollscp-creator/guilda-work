"""Imágenes de Docker: lo que corre en producción va fijado por digest (`imagen:tag@sha256:...`). Un `:latest` sin fijar puede
cambiar solo en el siguiente `docker compose pull` y romper un servicio sin aviso."""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Imágenes sin digest a propósito. Todas las demás van fijadas (`imagen:tag@sha256:...`); para fijar una nueva sin descargarla:
#   docker buildx imagetools inspect imagen:tag --format '{{json .Manifest}}'   (campo «digest»)
# Una imagen nueva sin digest que NO esté aquí falla el test.
NO_DESPLEGADAS = {
    "openproject/openproject:${OPENPROJECT_TAG:-15-slim}",      # el tag es una variable de entorno: se fija al desplegar con OPENPROJECT_TAG=<tag>@sha256:...
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
