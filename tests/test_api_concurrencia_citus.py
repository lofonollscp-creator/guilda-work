"""La API aguanta peticiones simultáneas sobre PostgreSQL + Citus REAL (tablas de referencia incluidas).

La suite normal usa el esquema `multitenant` (sin tablas de referencia): allí no existe el `DeadlockDetected` distribuido que producían las escrituras de uso de cada petición
(`tokens_api`, `tokens_api_uso`, `api_idempotencia`, `mcp_uso`). Esta prueba lanza `scripts/prueba_concurrencia_api.py` en un proceso aparte (no toca el motor global de la suite) contra
un PostgreSQL con Citus (`GUILDA_TEST_PG_URL`, superusuario) y exige 0 respuestas 5xx. Se salta si no hay Citus disponible."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
URL = os.environ.get("GUILDA_TEST_PG_URL")


def _hay_citus() -> bool:
    if not URL:
        return False
    try:
        import psycopg
        with psycopg.connect(URL, autocommit=True, connect_timeout=5) as c:
            return c.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'citus'").fetchone() is not None
    except Exception:                                                                    # noqa: BLE001
        return False


@pytest.mark.skipif(not _hay_citus(), reason="necesita GUILDA_TEST_PG_URL apuntando a un PostgreSQL con la extensión Citus")
def test_la_api_no_da_500_con_clientes_simultaneos_sobre_citus():
    r = subprocess.run([sys.executable, str(RAIZ / "scripts" / "prueba_concurrencia_api.py"), "--url", URL, "--hilos", "4,8", "--peticiones", "24"],
                       capture_output=True, text=True, timeout=280, cwd=str(RAIZ), env={**os.environ, "GUILDA_TEST_MOTOR": "sqlite"})
    assert r.returncode == 0, (r.stdout[-1500:] + r.stderr[-1500:])
    assert "0 errores 5xx" in r.stdout
