"""Tests de app/main.py: el hilo de sincronización automática de correo en
segundo plano (Fase 6). No arranca ningún servidor ni hilo real: se llama
directamente a la función del bucle, con time.sleep mockeado para parar
tras la primera vuelta."""
import pytest

from app import db, main as main_module


class _DetenerBucle(Exception):
    pass


def _cuenta(nombre: str) -> int:
    return db.crear_cuenta_correo(
        nombre=nombre, protocolo="imap", host="imap.ejemplo.com", puerto=993, usuario=f"{nombre}@ejemplo.com",
    )


def test_sincronizacion_correo_periodica_sincroniza_todas_las_cuentas(monkeypatch):
    id_a = _cuenta("A")
    id_b = _cuenta("B")

    llamadas = []
    monkeypatch.setattr(main_module.correo, "sincronizar_bandeja", lambda cid: llamadas.append(cid) or {"nuevos": 0})

    vueltas = {"n": 0}

    def sleep_falso(segundos):
        vueltas["n"] += 1
        if vueltas["n"] > 1:
            raise _DetenerBucle

    monkeypatch.setattr(main_module.time, "sleep", sleep_falso)

    with pytest.raises(_DetenerBucle):
        main_module._sincronizacion_correo_periodica()

    assert sorted(llamadas) == sorted([id_a, id_b])


def test_sincronizacion_correo_periodica_una_cuenta_rota_no_bloquea_las_demas(monkeypatch):
    id_a = _cuenta("A")
    id_b = _cuenta("B")

    llamadas = []

    def fake_sincronizar(cuenta_id):
        if cuenta_id == id_a:
            raise RuntimeError("cuenta A sin red")
        llamadas.append(cuenta_id)
        return {"nuevos": 0}

    monkeypatch.setattr(main_module.correo, "sincronizar_bandeja", fake_sincronizar)

    vueltas = {"n": 0}

    def sleep_falso(segundos):
        vueltas["n"] += 1
        if vueltas["n"] > 1:
            raise _DetenerBucle

    monkeypatch.setattr(main_module.time, "sleep", sleep_falso)

    with pytest.raises(_DetenerBucle):
        main_module._sincronizacion_correo_periodica()

    assert llamadas == [id_b]
