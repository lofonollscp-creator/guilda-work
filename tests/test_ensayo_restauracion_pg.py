"""Ensayo mensual de restauración de la base de datos (M5): la comparación de filas, el flujo del script con Docker simulado y el punto del panel Salud."""
import importlib.util
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import db, salud

RUTA = Path(__file__).resolve().parent.parent / "scripts" / "ensayo_restauracion_pg.py"
AHORA = datetime(2026, 11, 20, 9, 0)


@pytest.fixture(scope="module")
def ens():
    spec = importlib.util.spec_from_file_location("ensayo_restauracion_pg", RUTA)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_comparar_acepta_un_poco_de_retraso_y_rechaza_lo_demas(ens):
    prod = {"tenants": 2, "usuarios": 400, "tareas": 5000, "notas": 10, "expedientes": 7}
    rest = {"tenants": 2, "usuarios": 395, "tareas": 4700, "notas": 11, "expedientes": 0}
    r = ens.comparar(prod, rest)
    assert r["tenants"] == "ok" and r["usuarios"] == "ok"                     # 5 filas de retraso: dentro de la tolerancia
    assert "faltan 300" in r["tareas"]                                          # 6 % por debajo
    assert "más filas" in r["notas"]                                            # la copia nunca puede tener más que producción
    assert "vacía" in r["expedientes"]
    assert ens.comparar({"x": 1}, {})["x"] == "falta en la copia restaurada"


def _falso_docker(salida_restaurar, codigo=0, filas_prod=None, filas_rest=None):
    filas_prod = filas_prod or {"tenants": 2, "usuarios": 4}
    filas_rest = filas_rest if filas_rest is not None else dict(filas_prod)
    llamadas = []

    def run(cmd, **kw):
        llamadas.append(cmd)
        if cmd[0].endswith("restaurar_postgres.sh") and cmd[1] == "instancia":
            return subprocess.CompletedProcess(cmd, codigo, salida_restaurar, "")
        if cmd[0].endswith("restaurar_postgres.sh"):
            return subprocess.CompletedProcess(cmd, 0, "retirada", "")
        sql = cmd[-1]
        contenedor = cmd[2]
        if sql.startswith("select tablename"):
            return subprocess.CompletedProcess(cmd, 0, "\n".join(filas_prod), "")
        datos = filas_prod if contenedor == "prod" else filas_rest
        return subprocess.CompletedProcess(cmd, 0, "\n".join(f"{t}|{n}" for t, n in datos.items()), "")
    return run, llamadas


def test_flujo_correcto_compara_y_retira_la_instancia(ens, monkeypatch):
    run, llamadas = _falso_docker("Copia base: base-20261106-021858.tar.gz\nInstancia lista en 31 s: postgresql://x\nrecuperada hasta: 2026-11-06 03:00:00+00")
    monkeypatch.setattr(ens.subprocess, "run", run)
    r = ens.ensayar("ensayo", 55442, "prod")
    assert r["ok"] and r["base"] == "base-20261106-021858.tar.gz" and r["segundos_restauracion"] == 31 and r["recuperada_hasta"].startswith("2026-11-06")
    assert r["comprobaciones"] == {"restauracion": "ok", "tenants": "ok", "usuarios": "ok"}
    quitar = [c for c in llamadas if c[0].endswith("restaurar_postgres.sh") and c[1] == "quitar"]
    assert quitar and quitar[0][2:] == ["--nombre", "ensayo"]                                        # la instancia no se queda (y el nombre va como opción: el script rechaza argumentos sueltos)


def test_si_faltan_filas_el_ensayo_falla(ens, monkeypatch):
    run, _ = _falso_docker("Instancia lista en 10 s", filas_prod={"tenants": 2, "usuarios": 400}, filas_rest={"tenants": 2, "usuarios": 100})
    monkeypatch.setattr(ens.subprocess, "run", run)
    r = ens.ensayar("ensayo", 55442, "prod")
    assert not r["ok"] and "faltan 300" in r["comprobaciones"]["usuarios"]


def test_si_no_se_puede_restaurar_falla_y_aun_asi_retira(ens, monkeypatch):
    run, llamadas = _falso_docker("No hay una copia base adecuada en /x/base.", codigo=1)
    monkeypatch.setattr(ens.subprocess, "run", run)
    r = ens.ensayar("ensayo", 55442, "prod")
    assert not r["ok"] and r["comprobaciones"] == {"restauracion": "fallo"} and "copia base" in r["error"]
    assert any(len(c) > 1 and c[1] == "quitar" for c in llamadas)


def test_main_guarda_el_estado_y_conserva_el_ultimo_ok(ens, monkeypatch, tmp_path):
    estado = tmp_path / "backups" / "pg_estado_restauracion.json"
    estado.parent.mkdir()
    estado.write_text(json.dumps({"ok": True, "ultimo_ok": "2026-10-02T04:40:00"}))
    run, _ = _falso_docker("Instancia lista en 5 s", codigo=1)
    monkeypatch.setattr(ens.subprocess, "run", run)
    monkeypatch.setattr("sys.argv", ["x", "--estado", str(estado), "--produccion", "prod"])
    assert ens.main() == 1
    guardado = json.loads(estado.read_text())
    assert guardado["ok"] is False and guardado["ultimo_ok"] == "2026-10-02T04:40:00"          # el último correcto no se pierde


def _estado_en(monkeypatch, tmp_path, **datos):
    monkeypatch.setattr(db, "BACKUPS_DIR", tmp_path)
    (tmp_path / "pg_estado_restauracion.json").write_text(json.dumps(datos))


def test_panel_sin_ensayo_gris_correcto_verde_viejo_ambar_y_fallo_rojo(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "BACKUPS_DIR", tmp_path)
    assert salud._estado_ensayo_restauracion_pg(AHORA)["estado"] == salud.GRIS
    _estado_en(monkeypatch, tmp_path, ok=True, ultimo_ok=(AHORA - timedelta(days=5)).isoformat(), segundos_restauracion=31, comprobaciones={"tenants": "ok"})
    i = salud._estado_ensayo_restauracion_pg(AHORA)
    assert i["estado"] == salud.VERDE and i["valor"] == 31 and "31 s" in i["detalle"]
    _estado_en(monkeypatch, tmp_path, ok=True, ultimo_ok=(AHORA - timedelta(days=60)).isoformat(), comprobaciones={})
    assert salud._estado_ensayo_restauracion_pg(AHORA)["estado"] == salud.AMBAR
    _estado_en(monkeypatch, tmp_path, ok=False, comprobaciones={"restauracion": "ok", "usuarios": "le faltan 300 filas"})
    i = salud._estado_ensayo_restauracion_pg(AHORA)
    assert i["estado"] == salud.ROJO and "usuarios" in i["detalle"]
