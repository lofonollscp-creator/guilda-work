"""Tareas ↔ vencimientos fiscales en los dos sentidos: la tarea sabe de qué vencimiento sale (`tareas_outlook.vencimiento_id`), presentar el vencimiento cierra las que generó una
regla (nunca las creadas a mano), y la ficha del vencimiento lista sus tareas, avisa cuando están todas hechas y crea nuevas."""
import itertools
from datetime import date, timedelta

import pytest

from app import db, obligaciones
from tests.conftest import iniciar_sesion_de_prueba

HOY = date(2026, 10, 7)
_n = itertools.count()


def _d(n):
    return (HOY + timedelta(days=n)).isoformat()


def _despacho(nombre="Despacho tareas-vencimiento"):
    tenant = db.crear_tenant(nombre)
    k = next(_n)
    ana, luis = (db.crear_usuario(f"tv-{k}-{n}@x.com", "contrasena123") for n in ("a", "l"))
    for u in (ana, luis):
        db.asignar_tenant(u, tenant)
    cliente = db.crear_cliente_fiscal(tenant, "Panadería")
    return tenant, ana, luis, cliente


def _estado(tarea_id):
    conn = db.get_connection()
    try:
        return conn.execute("SELECT estado, vencimiento_id FROM tareas_outlook WHERE id = ?", (tarea_id,)).fetchone()
    finally:
        conn.close()


def _por_regla(tenant, ana, cliente, vencimiento_dias=10):
    v = db.crear_vencimiento_fiscal(tenant, cliente, "303", "3T", _d(vencimiento_dias))
    db.crear_regla_por_vencimiento(ana, "303", "Preparar el {modelo}", 14, 2)
    assert db.generar_tareas_por_vencimiento(HOY) == 1
    tarea = [t for t in db.listar_tareas_outlook(ana) if t["asunto"] == "Preparar el 303"][0]["id"]
    return v, tarea


def test_la_tarea_generada_por_una_regla_guarda_su_vencimiento():
    tenant, ana, _, cliente = _despacho()
    v, tarea = _por_regla(tenant, ana, cliente)
    assert _estado(tarea)["vencimiento_id"] == v


@pytest.mark.solo_sqlite
def test_las_tareas_ya_generadas_antes_de_existir_la_columna_se_enlazan_al_arrancar():
    tenant, ana, _, cliente = _despacho()
    v, tarea = _por_regla(tenant, ana, cliente)
    conn = db.get_connection(); conn.execute("UPDATE tareas_outlook SET vencimiento_id = NULL"); conn.commit(); conn.close()
    db.init_db()
    assert _estado(tarea)["vencimiento_id"] == v


def test_solo_se_enlaza_un_vencimiento_del_propio_despacho():
    tenant, ana, _, cliente = _despacho()
    otro, _, _, otro_cliente = _despacho("Otro despacho tareas-vencimiento")
    ajeno = db.crear_vencimiento_fiscal(otro, otro_cliente, "303", "3T", _d(5))
    propio = db.crear_vencimiento_fiscal(tenant, cliente, "303", "3T", _d(5))
    assert _estado(db.crear_tarea_outlook(ana, "Con vencimiento ajeno", vencimiento_id=ajeno))["vencimiento_id"] is None
    assert _estado(db.crear_tarea_outlook(ana, "Con vencimiento propio", vencimiento_id=propio))["vencimiento_id"] == propio


@pytest.mark.parametrize("via", ["atajo", "editar", "flujo"])
def test_presentar_el_vencimiento_completa_las_tareas_de_la_regla_y_no_las_manuales(via):
    tenant, ana, _, cliente = _despacho()
    v, de_regla = _por_regla(tenant, ana, cliente)
    manual = db.crear_tarea_outlook(ana, "Revisar a mano", vencimiento_id=v)
    sin_vinculo = db.crear_tarea_outlook(ana, "Otra cosa")
    otro_v = db.crear_vencimiento_fiscal(tenant, cliente, "130", "3T", _d(10))
    de_otro = db.crear_tarea_outlook(ana, "De otro vencimiento", vencimiento_id=otro_v)
    if via == "atajo":
        db.marcar_presentado_vencimiento_fiscal(tenant, v, ana)
    elif via == "editar":
        db.editar_vencimiento_fiscal(tenant, v, estado="presentado")
    else:
        obligaciones.transicionar(tenant, ana, v, "presentada", presentacion={"referencia": "CSV-1", "organismo": "AEAT"})
    assert _estado(de_regla)["estado"] == "completada"
    assert [_estado(t)["estado"] for t in (manual, sin_vinculo, de_otro)] == ["no_iniciada"] * 3


def test_cerrar_las_tareas_es_idempotente_y_no_afecta_a_otro_despacho():
    tenant, ana, _, cliente = _despacho()
    v, tarea = _por_regla(tenant, ana, cliente)
    otro, _, _, _ = _despacho("Otro despacho tareas-vencimiento")
    assert db.completar_tareas_de_vencimiento(otro, v) == 0 and _estado(tarea)["estado"] == "no_iniciada"
    assert db.completar_tareas_de_vencimiento(tenant, v) == 1
    assert db.completar_tareas_de_vencimiento(tenant, v) == 0


def test_si_falla_cerrar_las_tareas_el_vencimiento_se_queda_presentado(monkeypatch):
    tenant, ana, _, cliente = _despacho()
    v, tarea = _por_regla(tenant, ana, cliente)

    def falla(*a, **k):
        raise RuntimeError("fallo de prueba")

    monkeypatch.setattr(db, "completar_tareas_de_vencimiento", falla)
    db.marcar_presentado_vencimiento_fiscal(tenant, v, ana)
    assert db.obtener_vencimiento_fiscal(tenant, v)["estado"] == "presentado" and _estado(tarea)["estado"] == "no_iniciada"


def test_cada_persona_ve_sus_tareas_del_vencimiento_y_el_resumen_cuenta_todas():
    tenant, ana, luis, cliente = _despacho()
    v, de_regla = _por_regla(tenant, ana, cliente)
    de_luis = db.crear_tarea_outlook(luis, "Tarea de Luis", vencimiento_id=v)
    asignada = db.crear_tarea_outlook(ana, "Asignada a Luis", vencimiento_id=v, asignada_a=luis)
    assert sorted(t["id"] for t in db.tareas_de_vencimiento(tenant, v, ana)) == sorted([de_regla, asignada])
    assert sorted(t["id"] for t in db.tareas_de_vencimiento(tenant, v, luis)) == sorted([de_luis, asignada])
    assert db.resumen_tareas_de_vencimiento(tenant, v) == {"total": 3, "abiertas": 3}
    assert [t["generada"] for t in db.tareas_de_vencimiento(tenant, v, ana) if t["id"] == de_regla] == [1]
    db.completar_tarea_outlook(ana, de_regla)
    assert db.resumen_tareas_de_vencimiento(tenant, v) == {"total": 3, "abiertas": 2}


# --- Ficha del vencimiento -----------------------------------------------------------------------------------------------------------------------

def _con_vencimiento(cliente_http, email):
    uid = iniciar_sesion_de_prueba(cliente_http, email, "contrasena123")
    t = db.crear_tenant(f"Despacho {email}")
    db.asignar_tenant(uid, t)
    c = db.crear_cliente_fiscal(t, "Cliente Ficha")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20")
    return uid, t, c, v


def test_la_ficha_lista_las_tareas_y_las_crea_ligadas_al_vencimiento(cliente):
    uid, t, c, v = _con_vencimiento(cliente, "tv-ficha@ejemplo.com")
    assert "Todavía no hay tareas ligadas" in cliente.get(f"/fiscal/vencimientos/{v}/editar").get_data(as_text=True)
    r = cliente.post(f"/fiscal/vencimientos/{v}/tarea", data={"asunto": "Pedir las facturas"})
    assert r.status_code == 302
    (tarea,) = db.tareas_de_vencimiento(t, v, uid)
    assert tarea["asunto"] == "Pedir las facturas" and tarea["fecha_vencimiento"][:10] == "2026-10-20" and not tarea["generada"]
    assert db.listar_tareas_outlook(uid)[0]["cliente_fiscal_id"] == c
    assert "Pedir las facturas" in cliente.get(f"/fiscal/vencimientos/{v}/editar").get_data(as_text=True)


def test_sin_asunto_la_tarea_lleva_modelo_periodo_y_cliente_y_se_puede_asignar(cliente):
    uid, t, c, v = _con_vencimiento(cliente, "tv-asig@ejemplo.com")
    otra = db.crear_usuario("tv-otra@x.com", "contrasena123"); db.asignar_tenant(otra, t)
    cliente.post(f"/fiscal/vencimientos/{v}/tarea", data={"asunto": "", "asignada_a": str(otra)})
    tarea = db.listar_tareas_outlook(uid)[0]
    assert tarea["asunto"] == "303 2026-T3 · Cliente Ficha" and tarea["asignada_a"] == otra


def test_la_ficha_avisa_cuando_todas_las_tareas_estan_completadas_y_el_vencimiento_sigue_pendiente(cliente):
    uid, t, c, v = _con_vencimiento(cliente, "tv-aviso@ejemplo.com")
    aviso = "Todas las tareas de este vencimiento están completadas"
    cliente.post(f"/fiscal/vencimientos/{v}/tarea", data={"asunto": "Única"})
    assert aviso not in cliente.get(f"/fiscal/vencimientos/{v}/editar").get_data(as_text=True)
    db.completar_tarea_outlook(uid, db.tareas_de_vencimiento(t, v, uid)[0]["id"])
    assert aviso in cliente.get(f"/fiscal/vencimientos/{v}/editar").get_data(as_text=True)
    db.marcar_presentado_vencimiento_fiscal(t, v, uid)
    assert aviso not in cliente.get(f"/fiscal/vencimientos/{v}/editar").get_data(as_text=True)


def test_crear_tarea_de_un_vencimiento_de_otro_despacho_da_404(cliente):
    uid, t, c, v = _con_vencimiento(cliente, "tv-404@ejemplo.com")
    otro = db.crear_tenant("Despacho ajeno tv")
    ajeno = db.crear_vencimiento_fiscal(otro, db.crear_cliente_fiscal(otro, "Ajeno"), "303", "2026-T3", "2026-10-20")
    assert cliente.post(f"/fiscal/vencimientos/{ajeno}/tarea", data={"asunto": "x"}).status_code == 404
