"""Cierre de periodos (facturas_contables.periodos_cerrados / cerrar_periodo / exportar con confirmación, /contabilidad/periodo)."""
import pytest

from app import db, facturas_contables as fc, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_facturas_contables import LINEA, _datos


def _despacho():
    t = db.crear_tenant("Despacho cierres")
    u = db.crear_usuario_vinculado_a_kratos("cierres1@ejemplo.com", "k-cierres1"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Cierres SL", nif="B12345678")
    fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8"})
    return t, u, c


def _vencimiento(t, c, modelo, periodo, estado, papelera=None):
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO vencimientos_fiscales (tenant_id, cliente_fiscal_id, modelo, periodo, fecha_limite, estado, creado_en, papelera_en) VALUES (?, ?, ?, ?, '2026-10-20', ?, '2026-01-01T00:00:00', ?)",
                     (t, c, modelo, periodo, estado, papelera))
        conn.commit()
    finally:
        conn.close()


def _revisada(t, u, c, **kw):
    fid = fc.crear(t, u, c, _datos(**kw), [LINEA]); fc.cambiar_estado(t, u, fid, "revisada")
    return fid


# --- Qué está cerrado --------------------------------------------------------------------------------------------------------------------------

def test_por_defecto_no_hay_nada_cerrado():
    t, u, c = _despacho()
    assert fc.periodos_cerrados(t, c, ["2026-T1", "2026-T3"]) == {} and fc.periodos_cerrados(t, c, []) == {}


def test_el_303_presentado_cierra_su_trimestre_y_solo_ese():
    t, u, c = _despacho()
    _vencimiento(t, c, "303", "2026-T2", "presentado")
    _vencimiento(t, c, "303", "2026-T3", "pendiente")
    _vencimiento(t, c, "130", "2026-T1", "presentado")            # otro modelo: no cierra el IVA
    cerrados = fc.periodos_cerrados(t, c, ["2026-T1", "2026-T2", "2026-T3"])
    assert list(cerrados) == ["2026-T2"] and cerrados["2026-T2"]["motivo"] == "303"


def test_un_303_en_la_papelera_o_de_otro_cliente_no_cuenta():
    t, u, c = _despacho()
    otro = crear_cliente_fiscal(t, "Otro SL", nif="B87654321")
    _vencimiento(t, c, "303", "2026-T2", "presentado", papelera="2026-08-01T00:00:00")
    _vencimiento(t, otro, "303", "2026-T3", "presentado")
    assert fc.periodos_cerrados(t, c, ["2026-T2", "2026-T3"]) == {}


def test_el_390_presentado_cierra_los_cuatro_trimestres_del_ano():
    t, u, c = _despacho()
    _vencimiento(t, c, "390", "2025-anual", "presentado")
    cerrados = fc.periodos_cerrados(t, c, ["2025-T1", "2025-T4", "2026-T1"])
    assert set(cerrados) == {"2025-T1", "2025-T4"} and cerrados["2025-T1"]["motivo"] == "390"


def test_cerrar_a_mano_y_reabrir():
    t, u, c = _despacho()
    fc.cerrar_periodo(t, u, c, "2026-T3")
    fc.cerrar_periodo(t, u, c, "2026-T3")                          # repetir no duplica
    assert fc.periodos_cerrados(t, c, ["2026-T3"])["2026-T3"]["motivo"] == "manual"
    fc.reabrir_periodo(t, u, c, "2026-T3")
    assert fc.periodos_cerrados(t, c, ["2026-T3"]) == {}
    fc.reabrir_periodo(t, u, c, "2026-T3")                          # reabrir lo ya abierto no falla


def test_lo_cerrado_por_un_modelo_presentado_no_se_reabre_desde_aqui():
    t, u, c = _despacho()
    _vencimiento(t, c, "303", "2026-T2", "presentado")
    with pytest.raises(ValueError, match="calendario fiscal"):
        fc.reabrir_periodo(t, u, c, "2026-T2")
    assert "2026-T2" in fc.periodos_cerrados(t, c, ["2026-T2"])


def test_trimestre_mal_escrito_o_cliente_ajeno():
    t, u, c = _despacho()
    with pytest.raises(ValueError):
        fc.cerrar_periodo(t, u, c, "ayer")
    ajeno = crear_cliente_fiscal(db.crear_tenant("Ajeno cierres"), "Ajeno", nif="B99999999")
    with pytest.raises(ValueError, match="no encontrado"):
        fc.cerrar_periodo(t, u, ajeno, "2026-T3")


# --- Exportar ---------------------------------------------------------------------------------------------------------------------------------------

def test_exportar_facturas_de_un_periodo_cerrado_pide_confirmacion():
    t, u, c = _despacho()
    _vencimiento(t, c, "303", "2026-T3", "presentado")
    fid = _revisada(t, u, c, fecha="2026-08-15")
    with pytest.raises(ValueError, match="periodos ya cerrados: 2026-T3 \\(modelo 303 presentado\\)"):
        fc.exportar(t, u, c)
    assert fc.obtener(t, u, fid)["estado"] == "revisada" and fc.listar_lotes(t, u) == [], "no se marca ni se guarda nada"
    r = fc.exportar(t, u, c, confirmar_cerrado=True)
    assert r["n_facturas"] == 1 and fc.obtener(t, u, fid)["estado"] == "exportada"


def test_solo_cuentan_las_facturas_que_salen_y_los_periodos_abiertos_no_piden_nada():
    t, u, c = _despacho()
    _vencimiento(t, c, "303", "2026-T2", "presentado")
    _revisada(t, u, c, numero="A", fecha="2026-08-15")             # T3, abierto
    assert fc.exportar(t, u, c)["n_facturas"] == 1


def test_el_cierre_manual_tambien_bloquea_y_la_auditoria_recuerda_la_confirmacion():
    t, u, c = _despacho()
    fc.cerrar_periodo(t, u, c, "2026-T3")
    _revisada(t, u, c, fecha="2026-08-15")
    with pytest.raises(ValueError, match="cerrado a mano"):
        fc.exportar(t, u, c)
    fc.exportar(t, u, c, confirmar_cerrado=True)
    conn = db.get_connection()
    try:
        d = conn.execute("SELECT detalle FROM auditoria_eventos WHERE accion = 'contabilidad.exportada' AND tenant_id = ?", (t,)).fetchone()["detalle"]
    finally:
        conn.close()
    assert "2026-T3" in d


def test_el_precheque_avisa_de_los_periodos_cerrados_sin_marcar_nada():
    t, u, c = _despacho()
    _vencimiento(t, c, "303", "2026-T3", "presentado")
    _revisada(t, u, c, fecha="2026-08-15")
    informe = fc.comprobar_exportacion(t, u, c)
    assert [p["trimestre"] for p in informe["periodos_cerrados"]] == ["2026-T3"] and informe["ok"]
    assert "periodos ya cerrados" in informe["avisos"][0]["mensaje"] and fc.listar_lotes(t, u) == []


# --- Web ----------------------------------------------------------------------------------------------------------------------------------------------

def test_web_cerrar_ver_el_aviso_y_exportar_con_confirmacion(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "cierresweb@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho cierres web"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Web", nif="B12345678")
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8"})
    fid = _revisada(t, uid, c, fecha="2026-08-15")
    url = f"/contabilidad/?cliente_id={c}&trimestre=2026-T3"
    html = cliente.get(url).get_data(as_text=True)
    assert "Cerrar el trimestre 2026-T3" in html and "Periodo cerrado" not in html
    assert cliente.post("/contabilidad/periodo", data={"cliente_id": c, "trimestre": "2026-T3", "accion": "cerrar"}).status_code == 302
    html = cliente.get(url).get_data(as_text=True)
    assert "Periodo cerrado" in html and "Reabrir el periodo" in html and "Exportar aunque el periodo esté cerrado" in html
    ver = cliente.get(f"/contabilidad/{fid}").get_data(as_text=True)
    assert "Periodo cerrado" in ver and "confirmar el cierre" in ver
    comprobar = cliente.post("/contabilidad/comprobar", data={"cliente_id": c, "trimestre": "2026-T3"}).get_data(as_text=True)
    assert "periodos ya cerrados" in comprobar and 'name="confirmo_cerrado"' in comprobar
    r = cliente.post("/contabilidad/exportar", data={"cliente_id": c, "trimestre": "2026-T3"})
    assert r.status_code == 302 and "error=" in r.headers["Location"] and fc.obtener(t, uid, fid)["estado"] == "revisada"
    r = cliente.post("/contabilidad/exportar", data={"cliente_id": c, "trimestre": "2026-T3", "confirmo_cerrado": "1"})
    assert r.status_code == 200 and fc.obtener(t, uid, fid)["estado"] == "exportada"
    assert cliente.post("/contabilidad/periodo", data={"cliente_id": c, "trimestre": "2026-T3", "accion": "reabrir"}).status_code == 302
    assert "Periodo cerrado" not in cliente.get(url).get_data(as_text=True)


def test_web_un_trimestre_cerrado_por_el_modelo_no_ofrece_reabrir(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "cierresweb2@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho cierres web 2"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Web", nif="B12345678")
    _vencimiento(t, c, "303", "2026-T3", "presentado")
    html = cliente.get(f"/contabilidad/?cliente_id={c}&trimestre=2026-T3").get_data(as_text=True)
    assert "modelo 303 presentado" in html and "Reabrir el periodo" not in html and "calendario fiscal" in html
    r = cliente.post("/contabilidad/periodo", data={"cliente_id": c, "trimestre": "2026-T3", "accion": "reabrir"})
    assert r.status_code == 302 and "error=" in r.headers["Location"]
