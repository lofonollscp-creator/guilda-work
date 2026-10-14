"""Puesta en marcha guiada del despacho: pasos calculados, tarjeta de la app y aviso desde el backoffice."""
from datetime import datetime

from app import comunicados, db, onboarding_despacho
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_backoffice_app import bo, entrar, post  # noqa: F401 -- fixture


def _ahora():
    return datetime.now().isoformat(timespec="seconds")


def _cliente_fiscal(tenant_id, nombre="Cliente SL"):
    conn = db.get_connection()
    cur = conn.execute("INSERT INTO clientes_fiscales (tenant_id, nombre, creado_en) VALUES (?, ?, ?)", (tenant_id, nombre, _ahora()))
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    return cid


def _vencimiento(tenant_id, cliente_id, estado="pendiente", periodo="1T"):
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO vencimientos_fiscales (tenant_id, cliente_fiscal_id, modelo, periodo, fecha_limite, estado, creado_en) VALUES (?, ?, '303', ?, '2026-04-20', ?, ?)",
        (tenant_id, cliente_id, periodo, estado, _ahora()),
    )
    conn.commit()
    conn.close()


def test_pasos_se_calculan_de_los_datos_y_aislan_por_despacho():
    t, otro = db.crear_tenant("Uno"), db.crear_tenant("Otro")
    r = onboarding_despacho.resumen(t)
    assert (r["hechos"], r["total"], r["pct"], r["completo"]) == (0, 6, 0, False) and r["siguiente"].startswith("Crear el primer cliente")
    c = _cliente_fiscal(t)
    _cliente_fiscal(otro, "Ajeno")
    r = onboarding_despacho.resumen(t)
    assert r["hechos"] == 1 and r["siguiente"] == "Generar los vencimientos fiscales"
    _vencimiento(t, c)
    assert onboarding_despacho.estado(t)["vencimientos"] and not onboarding_despacho.estado(t)["presentado"]
    _vencimiento(t, c, "presentado", periodo="2T")
    assert onboarding_despacho.estado(t)["presentado"] and not onboarding_despacho.estado(otro)["vencimientos"]
    assert not onboarding_despacho.estado(otro)["presentado"]


def test_clientes_en_papelera_no_cuentan():
    t = db.crear_tenant("Papelera")
    c = _cliente_fiscal(t)
    conn = db.get_connection()
    conn.execute("UPDATE clientes_fiscales SET papelera_en = ? WHERE id = ?", (_ahora(), c))
    conn.commit(); conn.close()
    assert not onboarding_despacho.estado(t)["clientes"]


def test_tarjeta_en_el_inicio_de_la_app(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "onb@ejemplo.com", "una-clave-larga-1234")
    t = db.crear_tenant("Despacho onb")
    db.asignar_tenant(uid, t)
    html = cliente.get("/").get_data(as_text=True)
    assert "Puesta en marcha de tu despacho" in html and "Crea tu primer cliente fiscal" in html and "0/6" in html
    _cliente_fiscal(t)
    assert "1/6" in cliente.get("/").get_data(as_text=True)


def test_backoffice_muestra_progreso_y_avisa_sin_duplicar(bo):
    entrar(bo)
    t = db.crear_tenant("Atascado")
    html = bo.get(f"/tenants/{t}").get_data(as_text=True)
    assert "Puesta en marcha" in html and "0 de 6 pasos" in html
    assert "Atascado" in bo.get("/journey").get_data(as_text=True)
    post(bo, f"/tenants/{t}/puesta-en-marcha/avisar")
    avisos = [c for c in comunicados.listar() if c["tenant_id"] == t]
    assert len(avisos) == 1 and "Te faltan" in avisos[0]["texto"] and "cliente fiscal" in avisos[0]["texto"]
    post(bo, f"/tenants/{t}/puesta-en-marcha/avisar")                         # segundo clic: no duplica
    assert len([c for c in comunicados.listar() if c["tenant_id"] == t]) == 1
    assert post(bo, "/tenants/9999/puesta-en-marcha/avisar").status_code == 404
