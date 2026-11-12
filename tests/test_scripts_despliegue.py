"""Los scripts de despliegue y verificación tienen la sintaxis bien y no hacen nada raro al pedir ayuda (no se ejecutan contra el servidor)."""
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SCRIPTS = ("scripts/desplegar.sh", "scripts/verificar_despliegue.sh", "scripts/auditar_dependencias.sh")


def test_sintaxis_de_bash():
    for s in SCRIPTS:
        r = subprocess.run(["bash", "-n", str(RAIZ / s)], capture_output=True, text=True)
        assert r.returncode == 0, f"{s}: {r.stderr}"


def test_desplegar_pide_ayuda_sin_tocar_nada_y_rechaza_opciones_raras():
    r = subprocess.run([str(RAIZ / "scripts/desplegar.sh"), "--ayuda"], capture_output=True, text=True)
    assert r.returncode == 0 and "--simular" in r.stdout
    r = subprocess.run([str(RAIZ / "scripts/desplegar.sh"), "--borra-todo"], capture_output=True, text=True)
    assert r.returncode == 2 and "desconocida" in r.stderr


def test_los_scripts_son_ejecutables():
    for s in SCRIPTS:
        assert (RAIZ / s).stat().st_mode & 0o111, s
