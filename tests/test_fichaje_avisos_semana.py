"""Bloque 6: aviso de salida olvidada y horas de la semana frente a la jornada contratada."""
from datetime import datetime, timedelta

from app import db, fichaje_avisos, fichaje_export, notificaciones
from tests.conftest import iniciar_sesion_de_prueba

# Miércoles fijo para que los tests no dependan del día en que se ejecutan.
AHORA = datetime(2026, 3, 11, 12, 0)


def _trabajador(email, jornada=None):
    tenant = db.crear_tenant("Gestoria " + email)
    uid = db.crear_usuario_vinculado_a_kratos(email, "kratos-" + email)
    db.asignar_tenant(uid, tenant)
    if jornada is not None:
        db.guardar_fichaje_datos(uid, nombre_completo="Ana Pérez", dni_nie="12345678Z", jornada_semanal_horas=jornada)
    return uid, tenant


def _f(uid, tenant, tipo, cuando):
    """Inserta el evento con una hora fija (db.fichar solo admite horas de los
    últimos 7 días, y estos tests usan una semana fija)."""
    conn = db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO fichajes (usuario_id, tenant_id, tipo, marca_tiempo, origen, creado_por, creado_en) "
            "VALUES (?, ?, ?, ?, 'web', ?, ?)",
            (uid, tenant, tipo, cuando.strftime("%Y-%m-%dT%H:%M:%S"), uid, db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# --- aviso de salida olvidada -----------------------------------------------

def test_aviso_una_sola_vez_por_jornada_y_solo_si_supera_el_limite(monkeypatch):
    avisos = []
    monkeypatch.setattr(notificaciones, "crear_y_enviar", lambda uid, tipo, *a, **k: avisos.append((uid, tipo)))
    uid, tenant = _trabajador("b6-aviso@ejemplo.com")
    _f(uid, tenant, "entrada", AHORA - timedelta(hours=9))
    assert fichaje_avisos.procesar_avisos(AHORA, horas=10) == 0  # 9 h: todavía no
    assert fichaje_avisos.procesar_avisos(AHORA + timedelta(hours=2), horas=10) == 1
    assert fichaje_avisos.procesar_avisos(AHORA + timedelta(hours=3), horas=10) == 0  # ya avisado
    assert avisos == [(uid, "fichaje_salida_olvidada")]


def test_jornada_cerrada_o_pausa_y_nueva_jornada(monkeypatch):
    avisos = []
    monkeypatch.setattr(notificaciones, "crear_y_enviar", lambda uid, tipo, *a, **k: avisos.append(uid))
    cerrado, t1 = _trabajador("b6-cerrado@ejemplo.com")
    _f(cerrado, t1, "entrada", AHORA - timedelta(hours=14))
    _f(cerrado, t1, "salida", AHORA - timedelta(hours=6))
    pausa, t2 = _trabajador("b6-pausa@ejemplo.com")
    _f(pausa, t2, "entrada", AHORA - timedelta(hours=12))
    _f(pausa, t2, "pausa_inicio", AHORA - timedelta(hours=5))  # sigue siendo jornada abierta
    assert fichaje_avisos.procesar_avisos(AHORA, horas=10) == 1 and avisos == [pausa]
    # otra jornada (nueva entrada) vuelve a poder avisar
    _f(pausa, t2, "pausa_fin", AHORA - timedelta(hours=4))
    _f(pausa, t2, "salida", AHORA - timedelta(hours=3))
    _f(pausa, t2, "entrada", AHORA - timedelta(hours=2))
    assert fichaje_avisos.procesar_avisos(AHORA + timedelta(hours=9), horas=10) == 1


def test_desactivado_con_cero_y_variable_de_entorno(monkeypatch):
    avisos = []
    monkeypatch.setattr(notificaciones, "crear_y_enviar", lambda *a, **k: avisos.append(1))
    uid, tenant = _trabajador("b6-off@ejemplo.com")
    _f(uid, tenant, "entrada", AHORA - timedelta(days=2))
    monkeypatch.setenv("GUILDA_FICHAJE_AVISO_HORAS", "0")
    assert fichaje_avisos.procesar_avisos(AHORA) == 0 and avisos == []
    monkeypatch.setenv("GUILDA_FICHAJE_AVISO_HORAS", "basura")
    assert fichaje_avisos.horas_aviso() == 10.0
    monkeypatch.setenv("GUILDA_FICHAJE_AVISO_HORAS", "24")
    assert fichaje_avisos.procesar_avisos(AHORA) == 1  # 48 h > 24 h


def test_un_fallo_del_push_no_repite_el_aviso(monkeypatch):
    llamadas = []

    def roto(*a, **k):
        llamadas.append(1)
        raise RuntimeError("push caído")

    monkeypatch.setattr(notificaciones, "crear_y_enviar", roto)
    uid, tenant = _trabajador("b6-roto@ejemplo.com")
    _f(uid, tenant, "entrada", AHORA - timedelta(hours=20))
    assert fichaje_avisos.procesar_avisos(AHORA, horas=10) == 0
    fichaje_avisos.procesar_avisos(AHORA + timedelta(minutes=15), horas=10)
    assert len(llamadas) == 1  # registrado antes de notificar: no insiste


# --- horas de la semana -----------------------------------------------------

def test_semana_suma_solo_la_semana_actual_y_compara_con_la_jornada():
    uid, tenant = _trabajador("b6-semana@ejemplo.com", jornada=40)
    lunes = datetime(2026, 3, 9, 9, 0)
    _f(uid, tenant, "entrada", lunes - timedelta(days=3))          # semana anterior: no cuenta
    _f(uid, tenant, "salida", lunes - timedelta(days=3) + timedelta(hours=8))
    _f(uid, tenant, "entrada", lunes)
    _f(uid, tenant, "salida", lunes + timedelta(hours=8))           # lunes 8 h
    _f(uid, tenant, "entrada", lunes + timedelta(days=1))
    _f(uid, tenant, "salida", lunes + timedelta(days=1, hours=6, minutes=30))  # martes 6 h 30
    r = fichaje_export.resumen_semana(tenant, uid, AHORA)
    assert r["segundos"] == 14.5 * 3600 and r["contratados"] == 40 * 3600
    assert r["diferencia"] == (14.5 - 40) * 3600 and r["porcentaje"] == 36 and r["en_curso"] is False


def test_semana_incluye_la_jornada_abierta_y_el_turno_nocturno_del_domingo():
    uid, tenant = _trabajador("b6-noche@ejemplo.com", jornada=20)
    # turno que empieza el domingo 8 por la noche y acaba el lunes 9: solo 6 h son de esta semana
    _f(uid, tenant, "entrada", datetime(2026, 3, 8, 22, 0))
    _f(uid, tenant, "salida", datetime(2026, 3, 9, 6, 0))
    _f(uid, tenant, "entrada", datetime(2026, 3, 11, 9, 0))        # abierta: 3 h hasta AHORA
    r = fichaje_export.resumen_semana(tenant, uid, AHORA)
    assert r["segundos"] == 6 * 3600 + 3 * 3600 and r["en_curso"] is True


def test_semana_sin_jornada_contratada_y_sin_fichajes():
    uid, tenant = _trabajador("b6-sinjornada@ejemplo.com")
    r = fichaje_export.resumen_semana(tenant, uid, AHORA)
    assert r["segundos"] == 0 and r["contratados"] is None and r["diferencia"] is None and r["porcentaje"] is None


def test_formato_horas():
    assert fichaje_export.formato_horas(24.5 * 3600) == "24 h 30 min"
    assert fichaje_export.formato_horas(-90 * 60) == "-1 h 30 min"
    assert fichaje_export.formato_horas(None) == "—"


def test_paginas_muestran_la_barra_semanal_y_el_admin_las_columnas(cliente):
    gestor = iniciar_sesion_de_prueba(cliente, "b6-ui@ejemplo.com", "contrasena123")
    tenant = db.crear_tenant("Gestoria UI Fichaje")
    db.asignar_tenant(gestor, tenant)
    db.asignar_gestor_fichajes(gestor, True)
    db.guardar_fichaje_datos(gestor, nombre_completo="Gestor Uno", dni_nie="11111111H", jornada_semanal_horas=40)
    hoy = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
    if hoy > datetime.now():  # antes de las 8: usa el inicio del día para no fichar en el futuro
        hoy = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    db.fichar(gestor, tenant, "entrada", marca_tiempo=hoy.strftime("%Y-%m-%dT%H:%M:%S"))
    panel = cliente.get("/fichaje/").get_data(as_text=True)
    assert "fichaje-semana" in panel and "Esta semana" in panel and "incluye la jornada en curso" in panel
    assert "fichaje-semana" in cliente.get("/fichaje/historial").get_data(as_text=True)
    admin = cliente.get("/fichaje/admin").get_data(as_text=True)
    assert "Esta semana" in admin and "Diferencia" in admin
