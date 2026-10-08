"""scripts/fijar_imagenes.py: reescribe solo las líneas `image:` de lo que está en marcha, sin tocar nada más."""
import importlib.util
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("fijar_imagenes", RAIZ / "scripts" / "fijar_imagenes.py")
fijar_imagenes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fijar_imagenes)

A, B = "sha256:" + "a" * 64, "sha256:" + "b" * 64
COMPOSE = """services:
  web:
    image: nextcloud:latest   # comentario
  db:
    image: "postgres:16-alpine"
  viejo:
    image: redis:7-alpine@%s
  libre:
    image: openproject/openproject:${TAG:-15}
  parado:
    image: otra/imagen:latest
  extra:
    command: image: no es una linea de imagen
""" % A


def test_fija_lo_que_esta_en_marcha_y_nada_mas():
    nuevo, cambios = fijar_imagenes.fijar(COMPOSE, {"nextcloud:latest": B, "postgres:16-alpine": B, "redis:7-alpine": B})
    assert cambios == ["nextcloud:latest", "postgres:16-alpine"]
    assert f"image: nextcloud:latest@{B}   # comentario" in nuevo and f'image: "postgres:16-alpine@{B}"' in nuevo
    assert f"redis:7-alpine@{A}" in nuevo                         # ya fijada: se respeta
    assert "image: otra/imagen:latest\n" in nuevo and "${TAG:-15}" in nuevo and "command: image: no es" in nuevo
    assert nuevo.count("\n") == COMPOSE.count("\n")


def test_es_idempotente_y_actualizar_cambia_el_digest():
    una, _ = fijar_imagenes.fijar(COMPOSE, {"nextcloud:latest": B})
    dos, cambios = fijar_imagenes.fijar(una, {"nextcloud:latest": B})
    assert dos == una and cambios == []
    tres, cambios = fijar_imagenes.fijar(una, {"nextcloud:latest": A}, actualizar=True)
    assert cambios == ["nextcloud:latest"] and f"nextcloud:latest@{A}" in tres and B not in tres


def test_el_compose_real_no_tiene_latest_sin_digest_entre_lo_que_corre():
    """Lo que se fijó sigue fijado (la comprobación de imágenes sin fijar del backoffice lo da por bueno)."""
    from backoffice import dependencias
    sin_fijar = {i["imagen"] for i in dependencias.imagenes_sin_fijar(RAIZ)}
    assert "nextcloud:latest" not in sin_fijar and "postgres:16-alpine" not in sin_fijar
