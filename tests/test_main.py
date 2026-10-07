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
    """Bug encontrado en la auditoría de 2026-10-01: la llamada real
    (app/main.py) mandaba un solo argumento a sincronizar_bandeja(), que
    necesita usuario_id Y cuenta_id -- TypeError silenciado en cada vuelta
    desde siempre. El mock de este test, con la misma firma de un solo
    argumento que la llamada rota, nunca pudo detectarlo -- ahora exige
    los dos para no repetir el mismo punto ciego."""
    id_a = _cuenta(usuario_id, "A")
    id_b = _cuenta(usuario_id, "B")

    llamadas = []
    monkeypatch.setattr(
        main_module.correo, "sincronizar_bandeja",
        lambda uid, cid: llamadas.append((uid, cid)) or {"nuevos": 0},
    )

    vueltas = {"n": 0}

    def sleep_falso(segundos):
        vueltas["n"] += 1
        if vueltas["n"] > 1:
            raise _DetenerBucle

    monkeypatch.setattr(main_module.time, "sleep", sleep_falso)

    with pytest.raises(_DetenerBucle):
        main_module._sincronizacion_correo_periodica()

    assert sorted(llamadas) == sorted([(usuario_id, id_a), (usuario_id, id_b)])


def test_sincronizacion_correo_periodica_una_cuenta_rota_no_bloquea_las_demas(monkeypatch, usuario_id):
    id_a = _cuenta(usuario_id, "A")
    id_b = _cuenta(usuario_id, "B")

    llamadas = []

    def fake_sincronizar(uid, cuenta_id):
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
    assert "<h3>Equipo</h3>" not in resp.get_data(as_text=True)


def test_estadisticas_con_tenant_muestra_la_seccion_de_equipo(cliente):
    from tests.conftest import iniciar_sesion_de_prueba

    usuario_id = iniciar_sesion_de_prueba(cliente, "stats-con-tenant@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Stats")
    db.asignar_tenant(usuario_id, tenant_id)

    resp = cliente.get("/estadisticas")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "<h3>Equipo</h3>" in html
    assert "stats-con-tenant@ejemplo.com" in html


# --- Recordatorio de vencimientos fiscales respeta la preferencia ----------

def test_recordatorio_vencimientos_respeta_la_preferencia_desactivada(monkeypatch, usuario_id):
    from datetime import date, timedelta as _td

    tenant_id = db.crear_tenant("Gestoria Recordatorio Pref")
    db.asignar_tenant(usuario_id, tenant_id)
    cliente_id = db.crear_cliente_fiscal(tenant_id, "Cliente Recordatorio")
    fecha = (date.today() + _td(days=3)).isoformat()
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", fecha, usuario_id=usuario_id)
    db.guardar_perfil_usuario(usuario_id, notificar_push_vencimientos=False)

    llamadas = []
    monkeypatch.setattr(main_module.notificaciones, "crear_y_enviar", lambda *a, **k: llamadas.append(a))

    vueltas = {"n": 0}

    def sleep_falso(segundos):
        vueltas["n"] += 1
        if vueltas["n"] > 1:
            raise _DetenerBucle
    monkeypatch.setattr(main_module.time, "sleep", sleep_falso)

    with pytest.raises(_DetenerBucle):
        main_module._recordatorio_vencimientos_fiscales()

    assert not llamadas
    # Se marca como enviado igualmente -- si no, el hilo lo reintentaría
    # cada vuelta aunque el usuario nunca vaya a recibir el aviso.
    assert db.obtener_vencimiento_fiscal(tenant_id, v_id)["recordatorio_enviado_en"] is not None


def test_recordatorio_vencimientos_avisa_si_la_preferencia_esta_activa(monkeypatch, usuario_id):
    from datetime import date, timedelta as _td

    tenant_id = db.crear_tenant("Gestoria Recordatorio Activo")
    db.asignar_tenant(usuario_id, tenant_id)
    cliente_id = db.crear_cliente_fiscal(tenant_id, "Cliente Recordatorio Activo")
    fecha = (date.today() + _td(days=3)).isoformat()
    db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", fecha, usuario_id=usuario_id)

    llamadas = []
    monkeypatch.setattr(main_module.notificaciones, "crear_y_enviar", lambda *a, **k: llamadas.append(a))

    vueltas = {"n": 0}

    def sleep_falso(segundos):
        vueltas["n"] += 1
        if vueltas["n"] > 1:
            raise _DetenerBucle
    monkeypatch.setattr(main_module.time, "sleep", sleep_falso)

    with pytest.raises(_DetenerBucle):
        main_module._recordatorio_vencimientos_fiscales()

    assert len(llamadas) == 1


# --- Límite global de tamaño de petición (bug encontrado en la auditoría de 2026-10-01) ---

def test_max_content_length_rechaza_peticion_demasiado_grande(cliente):
    """Sin MAX_CONTENT_LENGTH, un endpoint sin su propio chequeo explícito
    de tamaño podía agotar memoria con peticiones grandes repetidas --
    /webhooks/stripe no requiere login y lee el cuerpo entero con
    request.get_data() antes de nada, así que sirve para probar el límite
    sin depender de autenticación."""
    limite = main_module.app.config["MAX_CONTENT_LENGTH"]
    cuerpo_grande = b"x" * (limite + 1)
    resp = cliente.post("/webhooks/stripe", data=cuerpo_grande, headers={"Stripe-Signature": "x"})
    assert resp.status_code == 413
