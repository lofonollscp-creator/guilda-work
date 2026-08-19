"""Tests de app/main.py: el hilo de sincronización automática de correo en
segundo plano (Fase 6). No arranca ningún servidor ni hilo real: se llama
directamente a la función del bucle, con time.sleep mockeado para parar
tras la primera vuelta."""
import pytest

from app import db, main as main_module


class _DetenerBucle(Exception):
    pass


def _cuenta(usuario_id: int, nombre: str) -> int:
    return db.crear_cuenta_correo(
        usuario_id,
        nombre=nombre, protocolo="imap", host="imap.ejemplo.com", puerto=993, usuario=f"{nombre}@ejemplo.com",
    )


def test_sincronizacion_correo_periodica_sincroniza_todas_las_cuentas(monkeypatch, usuario_id):
    id_a = _cuenta(usuario_id, "A")
    id_b = _cuenta(usuario_id, "B")

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


def test_sincronizacion_correo_periodica_una_cuenta_rota_no_bloquea_las_demas(monkeypatch, usuario_id):
    id_a = _cuenta(usuario_id, "A")
    id_b = _cuenta(usuario_id, "B")

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


# --- Estadísticas de equipo (app/main.py:estadisticas) ---------------------

def test_estadisticas_sin_tenant_no_muestra_la_seccion_de_equipo(cliente):
    from tests.conftest import iniciar_sesion_de_prueba

    iniciar_sesion_de_prueba(cliente, "stats-sin-tenant@ejemplo.com", "contrasena123")
    resp = cliente.get("/estadisticas")
    assert resp.status_code == 200
    assert "Equipo" not in resp.get_data(as_text=True)


def test_estadisticas_con_tenant_muestra_la_seccion_de_equipo(cliente):
    from tests.conftest import iniciar_sesion_de_prueba

    usuario_id = iniciar_sesion_de_prueba(cliente, "stats-con-tenant@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Stats")
    db.asignar_tenant(usuario_id, tenant_id)

    resp = cliente.get("/estadisticas")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Equipo" in html
    assert "stats-con-tenant@ejemplo.com" in html
