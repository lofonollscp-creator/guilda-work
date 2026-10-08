#!/usr/bin/env python3
"""Informe de solo lectura sobre qué corre en el servidor y qué sobra: memoria y disco por contenedor, contenedores
parados, volúmenes huérfanos, imágenes sin uso y, según los registros de Caddy, qué dominios reciben peticiones y
cuáles responden con errores 5xx (un dominio que casi solo da 502 suele tener el contenedor apagado o roto).

    scripts/auditar_contenedores.py [--dias 7]

NO borra ni para nada: al final propone comandos de limpieza para que los revises y los ejecutes tú."""
import argparse
import collections
import json
import subprocess
import sys


def _ejecutar(*args: str, timeout: int = 120) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _mib(texto: str) -> float:
    """'105.8MiB' / '1.2GiB' / '900kB' -> MiB."""
    texto = texto.strip()
    for sufijo, factor in (("GiB", 1024), ("MiB", 1), ("KiB", 1 / 1024), ("kB", 1 / 1024), ("MB", 0.95), ("GB", 972), ("B", 1 / 1048576)):
        if texto.endswith(sufijo):
            try:
                return float(texto[: -len(sufijo)]) * factor
            except ValueError:
                return 0.0
    return 0.0


def memoria_contenedores() -> list[tuple[str, float, str]]:
    filas = []
    for linea in _ejecutar("docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}").splitlines():
        partes = linea.split("\t")
        if len(partes) == 3:
            filas.append((partes[0], _mib(partes[1].split("/")[0]), partes[2]))
    return sorted(filas, key=lambda f: -f[1])


def contenedores_parados() -> list[tuple[str, str, str]]:
    filas = []
    for linea in _ejecutar("docker", "ps", "-a", "--filter", "status=exited", "--filter", "status=created", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}").splitlines():
        partes = linea.split("\t")
        if len(partes) == 3:
            filas.append(tuple(partes))
    return filas


def volumenes_huerfanos() -> list[tuple[str, str]]:
    """(nombre, tamaño) de los volúmenes que ningún contenedor usa."""
    nombres = set(_ejecutar("docker", "volume", "ls", "-q", "-f", "dangling=true").split())
    if not nombres:
        return []
    tamanos = {}
    for linea in _ejecutar("docker", "system", "df", "-v", "--format", "{{json .Volumes}}", timeout=300).splitlines():
        try:
            for v in json.loads(linea):
                tamanos[v["Name"]] = v.get("Size", "?")
        except (ValueError, TypeError, KeyError):
            continue
    return sorted(((n, tamanos.get(n, "?")) for n in nombres), key=lambda f: -_mib(f[1]) if f[1] != "?" else 0)


def imagenes_sin_uso() -> list[tuple[str, str]]:
    usadas = set(_ejecutar("docker", "ps", "-a", "--format", "{{.Image}}").split())
    filas = []
    for linea in _ejecutar("docker", "images", "--format", "{{.Repository}}:{{.Tag}}\t{{.Size}}").splitlines():
        nombre, _, tamano = linea.partition("\t")
        if nombre not in usadas and not nombre.startswith("<none>"):
            filas.append((nombre, tamano))
    return filas


def trafico_caddy(dias: int) -> list[tuple[str, int, int]]:
    """(dominio, peticiones, respuestas 5xx) en los últimos `dias` días, según el registro de acceso de Caddy."""
    total, errores = collections.Counter(), collections.Counter()
    salida = _ejecutar("journalctl", "-u", "caddy", "--since", f"-{dias} days", "--no-pager", "-o", "cat", timeout=300)
    for linea in salida.splitlines():
        try:
            j = json.loads(linea)
        except ValueError:
            continue
        if not str(j.get("logger", "")).startswith("http.log.access"):
            continue
        host = (j.get("request") or {}).get("host", "?").split(":")[0]
        total[host] += 1
        if 500 <= int(j.get("status") or 0) < 600:
            errores[host] += 1
    return sorted(((h, n, errores[h]) for h, n in total.items()), key=lambda f: -f[1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dias", type=int, default=7, help="ventana para el tráfico de Caddy (por defecto 7)")
    args = ap.parse_args()
    if not _ejecutar("docker", "version", "--format", "{{.Server.Version}}").strip():
        print("No se puede hablar con Docker (¿permisos?).", file=sys.stderr)
        return 1

    mem = _ejecutar("free", "-m").splitlines()
    if len(mem) > 1:
        total, usada = mem[1].split()[1:3]
        print(f"Memoria del servidor: {usada} MiB usados de {total} MiB\n")
    disco = _ejecutar("df", "-h", "/").splitlines()
    if len(disco) > 1:
        print("Disco (/): " + " ".join(disco[1].split()[1:5]) + "\n")

    en_marcha = memoria_contenedores()
    print(f"== Contenedores en marcha: {len(en_marcha)} ({sum(f[1] for f in en_marcha):.0f} MiB en total)")
    for nombre, mib, cpu in en_marcha:
        print(f"  {mib:8.1f} MiB  {cpu:>7}  {nombre}")

    parados = contenedores_parados()
    print(f"\n== Contenedores parados: {len(parados)}")
    for nombre, imagen, estado in parados:
        print(f"  {nombre}  ({imagen}) {estado}")

    huerfanos = volumenes_huerfanos()
    print(f"\n== Volúmenes que ningún contenedor usa: {len(huerfanos)}")
    for nombre, tamano in huerfanos[:25]:
        print(f"  {tamano:>9}  {nombre[:60]}")
    if len(huerfanos) > 25:
        print(f"  … y {len(huerfanos) - 25} más")

    sin_uso = imagenes_sin_uso()
    print(f"\n== Imágenes sin ningún contenedor: {len(sin_uso)}")
    for nombre, tamano in sin_uso:
        print(f"  {tamano:>9}  {nombre}")

    trafico = trafico_caddy(args.dias)
    print(f"\n== Peticiones por dominio en los últimos {args.dias} días (Caddy)")
    for host, n, e in trafico:
        marca = "  <-- casi todo errores" if n >= 20 and e / n >= 0.5 else ""
        print(f"  {n:7d}  {e:6d} 5xx  {host}{marca}")

    print("\nNada de esto se ha tocado. Para limpiar, revisa antes y ejecuta tú (de menos a más agresivo):")
    print("  docker container prune        # quita los parados")
    print("  docker volume ls -qf dangling=true   # lista; borra solo los que reconozcas: docker volume rm <nombre>")
    print("  docker image prune            # imágenes colgantes (las sin uso con nombre se quitan con docker rmi)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
