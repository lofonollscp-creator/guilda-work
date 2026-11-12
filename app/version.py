"""Qué versión del código está corriendo (AA12): el último commit en disco y desde cuándo corre este proceso. Si hay un commit POSTERIOR al arranque, es que hay código
commiteado sin desplegar (falta reiniciar). Lo muestra el panel Salud; no necesita ningún registro de despliegues."""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARRANCADO = datetime.now()


def ultimo_commit() -> dict | None:
    """{hash, asunto, fecha (datetime local sin zona)} del HEAD, o None si no hay Git (instalación sin repositorio)."""
    try:
        r = subprocess.run(["git", "-c", f"safe.directory={RAIZ}", "-C", str(RAIZ), "log", "-1", "--format=%h%x1f%s%x1f%cI"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    partes = r.stdout.strip().split("\x1f")
    if r.returncode != 0 or len(partes) != 3:
        return None
    return {"hash": partes[0], "asunto": partes[1], "fecha": datetime.fromisoformat(partes[2]).astimezone().replace(tzinfo=None)}


def estado(ahora: datetime | None = None, arrancado: datetime | None = None, commit: dict | None = None) -> dict | None:
    """{hash, asunto, commit_hace_s, corriendo_desde_s, pendiente}: `pendiente` si el commit es posterior al arranque (con un minuto de margen)."""
    commit = commit if commit is not None else ultimo_commit()
    if commit is None:
        return None
    ahora, arrancado = ahora or datetime.now(), arrancado or ARRANCADO
    return {"hash": commit["hash"], "asunto": commit["asunto"], "commit_hace_s": (ahora - commit["fecha"]).total_seconds(),
            "corriendo_desde_s": (ahora - arrancado).total_seconds(), "pendiente": (commit["fecha"] - arrancado).total_seconds() > 60}
