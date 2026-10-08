"""Auditoría de dependencias: paquetes de Python instalados con vulnerabilidades
conocidas (base pública OSV, osv.dev) e imágenes de Docker sin versión fijada.

Solo se envía a OSV el NOMBRE y la VERSIÓN de cada paquete público, nada más. Se
puede desactivar con BACKOFFICE_AUDITORIA_DEPENDENCIAS=0. Un fallo de red no rompe
nada: queda anotado en el resultado."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from importlib import metadata
from pathlib import Path

from app import db as plataforma

from . import auth

URL_OSV = "https://api.osv.dev/v1"
RAIZ = Path(plataforma.RAIZ_PROYECTO)
MAX_DETALLES = 25


def activa() -> bool:
    return os.environ.get("BACKOFFICE_AUDITORIA_DEPENDENCIAS", "1") != "0"


def paquetes_instalados() -> list[tuple[str, str]]:
    vistos = {}
    for d in metadata.distributions():
        nombre = (d.metadata["Name"] or "").strip()
        if nombre:
            vistos[nombre.lower()] = (nombre, d.version)
    return sorted(vistos.values(), key=lambda p: p[0].lower())


def imagenes_sin_fijar(raiz: Path | None = None) -> list[dict]:
    """`image:` de los docker-compose cuya etiqueta es `latest`/`unstable`/inexistente: cada
    reinicio o `pull` puede traer una versión distinta sin que nadie la haya revisado."""
    encontradas = []
    for fichero in sorted((raiz or RAIZ).glob("docker-compose*.yml")):
        if fichero.name.startswith(("docker-compose.test", "docker-compose.synapse")):
            continue
        for linea in fichero.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(r"\s*image:\s*['\"]?([^'\"\s#]+)", linea)
            if not m:
                continue
            imagen = m.group(1)
            if "${" in imagen or "@sha256:" in imagen:
                continue  # parametrizada por variable de entorno, o fijada por digest
            nombre, _, etiqueta = imagen.rpartition(":") if ":" in imagen.split("/")[-1] else (imagen, "", "")
            if etiqueta in ("", "latest", "unstable") or etiqueta.endswith("-latest"):
                encontradas.append({"imagen": imagen, "fichero": fichero.name, "etiqueta": etiqueta or "(sin etiqueta)"})
    return encontradas


def _post(ruta: str, cuerpo: dict, timeout: int = 20) -> dict:
    peticion = urllib.request.Request(
        URL_OSV + ruta, data=json.dumps(cuerpo).encode(), headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(peticion, timeout=timeout) as r:
        return json.loads(r.read())


def _get(ruta: str, timeout: int = 20) -> dict:
    with urllib.request.urlopen(URL_OSV + ruta, timeout=timeout) as r:
        return json.loads(r.read())


def consultar_vulnerabilidades(paquetes: list[tuple[str, str]], post=_post, get=_get) -> tuple[list[dict], str | None]:
    """[{paquete, version, ids:[…], resumen}] para los paquetes afectados, y un error legible si OSV no responde."""
    try:
        consultas = [{"package": {"name": n, "ecosystem": "PyPI"}, "version": v} for n, v in paquetes]
        afectados = []
        for inicio in range(0, len(consultas), 500):
            lote = consultas[inicio:inicio + 500]
            respuesta = post("/querybatch", {"queries": lote})
            for consulta, resultado in zip(lote, respuesta.get("results", [])):
                ids = [v["id"] for v in resultado.get("vulns", [])]
                if ids:
                    afectados.append({"paquete": consulta["package"]["name"], "version": consulta["version"], "ids": ids, "resumen": ""})
        for a in afectados[:MAX_DETALLES]:
            try:
                detalle = get(f"/vulns/{a['ids'][0]}")
                a["resumen"] = (detalle.get("summary") or detalle.get("details") or "")[:200]
                arreglos = [
                    ev["fixed"] for af in detalle.get("affected", []) for rg in af.get("ranges", []) for ev in rg.get("events", []) if "fixed" in ev
                ]
                a["arreglado_en"] = arreglos[0] if arreglos else None
            except (urllib.error.URLError, OSError, ValueError):
                continue
        return afectados, None
    except (urllib.error.URLError, OSError, ValueError) as e:
        return [], f"No se pudo consultar osv.dev: {e}"


def auditar(post=_post, get=_get, raiz: Path | None = None) -> dict:
    paquetes = paquetes_instalados()
    vulnerables, error = consultar_vulnerabilidades(paquetes, post, get)
    resultado = {
        "fecha": auth._ahora(), "n_paquetes": len(paquetes), "vulnerables": vulnerables, "error": error,
        "imagenes": imagenes_sin_fijar(raiz),
    }
    conn = auth.conectar()
    try:
        conn.execute("INSERT INTO auditorias_dependencias (fecha, resultado) VALUES (?, ?)", (resultado["fecha"], json.dumps(resultado)))
        conn.execute("DELETE FROM auditorias_dependencias WHERE id NOT IN (SELECT id FROM auditorias_dependencias ORDER BY id DESC LIMIT 20)")
        conn.commit()
    finally:
        conn.close()
    return resultado


def ultima() -> dict | None:
    conn = auth.conectar()
    try:
        fila = conn.execute("SELECT resultado FROM auditorias_dependencias ORDER BY id DESC LIMIT 1").fetchone()
        return json.loads(fila["resultado"]) if fila else None
    finally:
        conn.close()


def auditar_si_toca(ahora: datetime | None = None, **kw) -> bool:
    """Una vez por semana ISO, aunque el servicio se reinicie."""
    if not activa():
        return False
    ahora = ahora or datetime.now()
    anterior = ultima()
    if anterior:
        try:
            if datetime.fromisoformat(anterior["fecha"]).isocalendar()[:2] == ahora.isocalendar()[:2]:
                return False
        except (ValueError, KeyError):
            pass
    auditar(**kw)
    return True
