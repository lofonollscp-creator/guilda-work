#!/usr/bin/env python3
"""Ensayo mensual de restauración de la base de datos de producción (M5): una copia que nunca se ha restaurado no es una copia.

Levanta una instancia APARTE y desechable con la copia base más reciente y todo el WAL (scripts/restaurar_postgres.sh instancia: nunca toca el contenedor ni el volumen de producción), compara el
número de filas de las tablas clave con las de producción y la borra. Deja el resultado en data/backups/pg_estado_restauracion.json (lo lee el panel Salud) y sale con error si algo falla.
Como la instancia restaurada llega hasta el último WAL archivado, puede ir unos minutos por detrás de producción: se acepta hasta un 2 % (o 25 filas) menos, nunca más filas que producción
ni una tabla vacía donde producción tiene datos.

  scripts/ensayo_restauracion_pg.py [--nombre guilda-pg-ensayo-restauracion] [--puerto 55442] [--estado RUTA.json] [--produccion guilda-work-postgres-app] [--conservar]
Variables: GUILDA_PG_BACKUPS (carpeta de las copias), GUILDA_BACKUPS_DIR (dónde dejar el estado; por defecto data/backups)."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TABLAS = ("tenants", "usuarios", "clientes_fiscales", "expedientes", "tareas", "notas", "facturas_contables", "portal_peticiones")
TOLERANCIA_PCT = 2
TOLERANCIA_FILAS = 25
BASE_DATOS = "guilda"
USUARIO = "guilda"


def comparar(produccion: dict[str, int], restaurada: dict[str, int]) -> dict[str, str]:
    """{tabla: "ok" | motivo}. Una tabla que falta en la restaurada, con más filas que producción o muy por debajo, es un fallo."""
    res = {}
    for t, p in produccion.items():
        r = restaurada.get(t)
        if r is None:
            res[t] = "falta en la copia restaurada"
        elif r > p:
            res[t] = f"la copia tiene más filas que producción ({r} > {p})"
        elif p and not r:
            res[t] = f"vacía en la copia (producción {p})"
        elif p - r > max(TOLERANCIA_FILAS, p * TOLERANCIA_PCT / 100):
            res[t] = f"le faltan {p - r} filas (copia {r}, producción {p})"
        else:
            res[t] = "ok"
    return res


def _contar(contenedor: str) -> dict[str, int]:
    existentes = _psql(contenedor, "select tablename from pg_tables where schemaname = 'public'").split()
    usar = [t for t in TABLAS if t in existentes]
    if not usar:
        return {}
    consulta = " union all ".join(f"select '{t}', count(*) from {t}" for t in usar)
    salida = _psql(contenedor, consulta)
    return {linea.split("|")[0]: int(linea.split("|")[1]) for linea in salida.splitlines() if "|" in linea}


def _psql(contenedor: str, sql: str) -> str:
    r = subprocess.run(["docker", "exec", contenedor, "psql", "-X", "-U", USUARIO, "-d", BASE_DATOS, "-At", "-c", sql], capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise RuntimeError(f"psql en {contenedor}: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def _estado_previo(ruta: Path) -> dict:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def ensayar(nombre: str, puerto: int, produccion: str, conservar: bool = False) -> dict:
    inicio = time.time()
    resultado: dict = {"ok": False, "fecha": datetime.now().isoformat(timespec="seconds"), "comprobaciones": {}, "contenedor": nombre}
    restaurar = str(RAIZ / "scripts" / "restaurar_postgres.sh")
    try:
        r = subprocess.run([restaurar, "instancia", "--nombre", nombre, "--puerto", str(puerto)], capture_output=True, text=True, timeout=45 * 60)
        salida = r.stdout + r.stderr
        m = re.search(r"Copia base: (\S+)", salida)
        resultado["base"] = m.group(1) if m else None
        m = re.search(r"Instancia lista en (\d+) s", salida)
        resultado["segundos_restauracion"] = int(m.group(1)) if m else None
        m = re.search(r"recuperada hasta: (.+)", salida)
        resultado["recuperada_hasta"] = m.group(1).strip() if m else None
        if r.returncode:
            resultado["error"] = "No se pudo restaurar: " + (salida.strip().splitlines() or ["sin salida"])[-1][:300]
            resultado["comprobaciones"] = {"restauracion": "fallo"}
            return resultado
        resultado["comprobaciones"] = {"restauracion": "ok", **comparar(_contar(produccion), _contar(nombre))}
        resultado["ok"] = all(v == "ok" for v in resultado["comprobaciones"].values())
    except Exception as e:  # noqa: BLE001
        resultado["error"] = f"{type(e).__name__}: {e}"[:300]
        resultado["comprobaciones"].setdefault("restauracion", "fallo")
    finally:
        resultado["segundos"] = int(time.time() - inicio)
        if not conservar:
            subprocess.run([str(RAIZ / "scripts" / "restaurar_postgres.sh"), "quitar", "--nombre", nombre], capture_output=True, text=True, timeout=300)
    return resultado


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--nombre", default="guilda-pg-ensayo-restauracion")
    p.add_argument("--puerto", type=int, default=55442)
    p.add_argument("--produccion", default="guilda-work-postgres-app")
    p.add_argument("--estado", default=str(Path(os.environ.get("GUILDA_BACKUPS_DIR") or RAIZ / "data" / "backups") / "pg_estado_restauracion.json"))
    p.add_argument("--conservar", action="store_true", help="no borrar la instancia restaurada (para inspeccionarla)")
    a = p.parse_args()
    estado = Path(a.estado)
    previo = _estado_previo(estado)
    resultado = ensayar(a.nombre, a.puerto, a.produccion, a.conservar)
    resultado["ultimo_ok"] = resultado["fecha"] if resultado["ok"] else previo.get("ultimo_ok")
    estado.parent.mkdir(parents=True, exist_ok=True)
    estado.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        ref = estado.parent.parent if estado.parent.name == "backups" else estado.parent
        st = ref.stat()
        os.chown(estado, st.st_uid, st.st_gid)
    except Exception:  # noqa: BLE001
        pass
    print(json.dumps(resultado, ensure_ascii=False, indent=1))
    return 0 if resultado["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
