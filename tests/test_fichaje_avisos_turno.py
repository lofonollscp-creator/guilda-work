"""Aviso de fin de turno con la jornada abierta (app/fichaje_avisos.py:procesar_avisos_turno)."""
from datetime import date, datetime, timedelta

import pytest

from app import db, fichaje_avisos as fa, turnos as tu

D = date(2026, 3, 17)


@pytest.fixture
def eq(usuario_id):
    t = db.crear_tenant("Despacho avisos turno")
    class E: pass
    e = E(); e.t = t
    e.g = db.crear_usuario_vinculado_a_kratos("g-avt@ejemplo.com", "k-g-avt"); db.asignar_tenant(e.g, t); db.asignar_gestor_fichajes(e.g, True)
    e.ana = db.crear_usuario_vinculado_a_kratos("ana-avt@ejemplo.com", "k-ana-avt"); db.asignar_tenant(e.ana, t)
    return e


def _turno(eq, usuario, dia, nombre, inicio, fin):
    tipo = next((x["id"] for x in tu.listar_tipos(eq.t) if x["nombre"] == nombre), None) or tu.crear_tipo(eq.t, eq.g, nombre, inicio, fin)
    conn = db.get_connection()
    conn.execute("INSERT INTO turnos_asignados (tenant_id, usuario_id, fecha, turno_id, asignado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?)", (eq.t, usuario, dia.isoformat(), tipo, eq.g, db.now_iso()))
    conn.commit(); conn.close()


def _fichar(eq, usuario, tipo, cuando: datetime):
    conn = db.get_connection()
    conn.execute("INSERT INTO fichajes (usuario_id, tenant_id, tipo, marca_tiempo, origen, creado_por, creado_en) VALUES (?, ?, ?, ?, 'web', ?, ?)",
                 (usuario, eq.t, tipo, cuando.isoformat(timespec="seconds"), usuario, db.now_iso()))
    conn.commit(); conn.close()


def _avisos(usuario):
    return [n["titulo"] for n in db.listar_notificaciones(usuario, 20) if n["titulo"] == "Tu turno ya ha terminado"]


def at(dia, hhmm):
    return datetime.fromisoformat(f"{dia.isoformat()}T{hhmm}:00")


def test_avisa_una_sola_vez_cuando_pasa_el_margen_del_fin_del_turno(eq):
    _turno(eq, eq.ana, D, "Mañana", "08:00", "14:00"); _fichar(eq, eq.ana, "entrada", at(D, "08:05"))
    assert fa.procesar_avisos_turno(at(D, "14:30"), 1.0) == 0 and _avisos(eq.ana) == []                 # dentro del margen
    assert fa.procesar_avisos_turno(at(D, "15:10"), 1.0) == 1 and len(_avisos(eq.ana)) == 1
    assert fa.procesar_avisos_turno(at(D, "16:30"), 1.0) == 0 and len(_avisos(eq.ana)) == 1             # una vez por jornada


def test_el_texto_dice_el_turno_y_la_hora_de_fin(eq):
    _turno(eq, eq.ana, D, "Mañana", "08:00", "14:00"); _fichar(eq, eq.ana, "entrada", at(D, "08:00"))
    fa.procesar_avisos_turno(at(D, "16:00"), 1.0)
    (n,) = [x for x in db.listar_notificaciones(eq.ana, 5) if x["titulo"] == "Tu turno ya ha terminado"]
    assert "«Mañana»" in n["cuerpo"] and "14:00" in n["cuerpo"] and "2.0 h" in n["cuerpo"]


def test_sin_turno_ese_dia_o_con_la_jornada_cerrada_no_avisa(eq):
    _fichar(eq, eq.ana, "entrada", at(D, "08:00"))
    assert fa.procesar_avisos_turno(at(D, "23:00"), 1.0) == 0                                          # sin turno
    _turno(eq, eq.ana, D, "Mañana", "08:00", "14:00"); _fichar(eq, eq.ana, "salida", at(D, "14:02"))
    assert fa.procesar_avisos_turno(at(D, "23:00"), 1.0) == 0 and _avisos(eq.ana) == []


def test_un_turno_de_noche_que_cruza_la_medianoche(eq):
    _turno(eq, eq.ana, D, "Noche", "22:00", "06:00"); _fichar(eq, eq.ana, "entrada", at(D, "22:05"))
    sig = D + timedelta(days=1)
    assert fa.procesar_avisos_turno(at(sig, "06:30"), 1.0) == 0 and fa.procesar_avisos_turno(at(sig, "07:10"), 1.0) == 1


def test_una_entrada_de_madrugada_se_atribuye_al_turno_de_la_noche_anterior_solo_si_aun_no_habia_terminado(eq):
    sig = D + timedelta(days=1)
    _turno(eq, eq.ana, D, "Noche", "22:00", "06:00")
    _fichar(eq, eq.ana, "entrada", at(sig, "00:30"))                                                  # entra tarde a su turno de noche
    assert fa.procesar_avisos_turno(at(sig, "08:00"), 1.0) == 1
    otra = db.crear_usuario_vinculado_a_kratos("otra-avt@ejemplo.com", "k-otra-avt"); db.asignar_tenant(otra, eq.t)
    _turno(eq, otra, D, "Noche", "22:00", "06:00")
    _fichar(eq, otra, "entrada", at(sig, "09:00"))                                                    # el turno de anoche ya había acabado: es otra jornada, sin turno
    assert fa.procesar_avisos_turno(at(sig, "20:00"), 1.0) == 0


def test_un_margen_negativo_lo_desactiva_y_el_margen_por_defecto_es_una_hora(eq, monkeypatch):
    _turno(eq, eq.ana, D, "Mañana", "08:00", "14:00"); _fichar(eq, eq.ana, "entrada", at(D, "08:00"))
    assert fa.procesar_avisos_turno(at(D, "20:00"), -1) == 0
    monkeypatch.delenv("GUILDA_FICHAJE_AVISO_TURNO_MARGEN_HORAS", raising=False)
    assert fa.margen_turno_horas() == 1.0
    monkeypatch.setenv("GUILDA_FICHAJE_AVISO_TURNO_MARGEN_HORAS", "x"); assert fa.margen_turno_horas() == 1.0
    monkeypatch.setenv("GUILDA_FICHAJE_AVISO_TURNO_MARGEN_HORAS", "0.5"); assert fa.margen_turno_horas() == 0.5


def test_el_aviso_por_turno_no_gasta_el_aviso_por_horas(eq):
    _turno(eq, eq.ana, D, "Mañana", "08:00", "14:00"); _fichar(eq, eq.ana, "entrada", at(D, "08:00"))
    assert fa.procesar_avisos_turno(at(D, "15:30"), 1.0) == 1
    assert fa.procesar_avisos(at(D, "20:00"), 10.0) == 1                                              # a las 12 h sigue yendo el aviso de «salida olvidada»


def test_borrar_un_despacho_limpia_los_avisos_de_turno(eq):
    _turno(eq, eq.ana, D, "Mañana", "08:00", "14:00"); _fichar(eq, eq.ana, "entrada", at(D, "08:00"))
    assert fa.procesar_avisos_turno(at(D, "15:30"), 1.0) == 1
    db.borrar_tenant(eq.t, incluir_fichajes=True)
    conn = db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM fichaje_avisos_turno").fetchone()[0] == 0
    conn.close()
