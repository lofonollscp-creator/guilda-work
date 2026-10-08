#!/usr/bin/env python3
"""Fija en docker-compose.yml las imágenes que ya están en marcha con su resumen (digest), de forma
que `docker compose pull/up` no pueda traer otra versión sin que alguien lo decida.

    scripts/fijar_imagenes.py             muestra qué cambiaría (no escribe nada)
    scripts/fijar_imagenes.py --aplicar   reescribe docker-compose.yml
    scripts/fijar_imagenes.py --actualizar --aplicar
                                          también cambia el digest de las que ya lo tienen, al de la
                                          imagen que esté en marcha (para subir de versión: quita el digest
                                          a mano, `docker compose pull && up -d`, prueba y vuelve a fijar)

Solo toca imágenes con un contenedor en marcha (esa es la versión que se sabe que funciona):
las demás se quedan como están. `image: repo:etiqueta` pasa a `image: repo:etiqueta@sha256:...`;
la etiqueta se conserva para poder leer la versión, y Docker usa el digest."""
import argparse
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FICHERO = RAIZ / "docker-compose.yml"
LINEA_IMAGEN = re.compile(r"^(\s*image:\s*)(['\"]?)([^'\"\s#@]+)(@sha256:[0-9a-f]{64})?(['\"]?)(\s*(?:#.*)?)$")


def _docker(*args: str) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=True).stdout


def digests_en_marcha() -> dict[str, str]:
    """{imagen tal como la nombran los contenedores sin digest: 'repo@sha256:...'} de lo que está corriendo."""
    resultado: dict[str, str] = {}
    for nombre in _docker("ps", "--format", "{{.Names}}").split():
        configurada = _docker("inspect", nombre, "--format", "{{.Config.Image}}").strip().split("@")[0]
        id_imagen = _docker("inspect", nombre, "--format", "{{.Image}}").strip()
        digests = _docker("image", "inspect", id_imagen, "--format", "{{range .RepoDigests}}{{.}} {{end}}").split()
        repo = configurada.rsplit(":", 1)[0] if ":" in configurada.split("/")[-1] else configurada
        for d in digests:
            if d.split("@")[0] == repo or d.split("@")[0].endswith("/" + repo):
                resultado[configurada] = d.split("@")[1]
                break
    return resultado


def fijar(texto: str, digests: dict[str, str], actualizar: bool = False) -> tuple[str, list[str]]:
    cambios: list[str] = []
    salida = []
    for linea in texto.splitlines():
        m = LINEA_IMAGEN.match(linea)
        if m and "${" not in m.group(3):
            imagen = m.group(3)
            nuevo = digests.get(imagen)
            if nuevo and (m.group(4) is None or (actualizar and m.group(4)[1:] != nuevo)):
                linea = f"{m.group(1)}{m.group(2)}{imagen}@{nuevo}{m.group(5)}{m.group(6)}"
                cambios.append(imagen)
        salida.append(linea)
    return "\n".join(salida) + ("\n" if texto.endswith("\n") else ""), cambios


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aplicar", action="store_true", help="escribir el fichero")
    ap.add_argument("--actualizar", action="store_true", help="re-fijar también las que ya tienen digest")
    args = ap.parse_args()
    try:
        digests = digests_en_marcha()
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"No se ha podido consultar Docker: {e}", file=sys.stderr)
        return 1
    nuevo, cambios = fijar(FICHERO.read_text(encoding="utf-8"), digests, args.actualizar)
    for imagen in sorted(set(cambios)):
        print(f"  {imagen}  ->  @{digests[imagen][:19]}…  ({cambios.count(imagen)} línea(s))")
    print(f"{len(cambios)} línea(s) {'cambiadas' if args.aplicar else 'cambiarían'} en {FICHERO.name}.")
    if args.aplicar and cambios:
        FICHERO.write_text(nuevo, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
