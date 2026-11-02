"""Pantallas de los cambios en lote de los vencimientos fiscales (app/rutas_fiscal_masivo.py). Con Kratos real."""
from app import db, fiscal_masivo as fm, verticales
from app.db_fiscal import crear_cliente_fiscal, crear_vencimiento_fiscal, obtener_vencimiento_fiscal
from tests.conftest import iniciar_sesion_de_prueba


def _web(cliente, email="masivofiscal@ejemplo.com", activo=True):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant("Despacho " + email)
    db.asignar_tenant(uid, t)
    db.asignar_supervisor_tenant(uid, True)
    if activo:
        verticales.fijar_activo(t, "fiscal", True)
    otra = db.crear_usuario_vinculado_a_kratos("otra-" + email, "k-otra-" + email); db.asignar_tenant(otra, t)
    c = crear_cliente_fiscal(t, "Titular Lote Web SL", nif=None)
    vs = [crear_vencimiento_fiscal(t, c, "303", f"{i}T 2026", f"2027-0{i}-20", usuario_id=uid) for i in (1, 2)]
    return uid, otra, t, vs


def test_sin_el_modulo_no_existe(cliente):
    _web(cliente, activo=False)
    assert cliente.get("/guilda-fiscal/masivo/").status_code == 404


def test_el_panel_ofrece_el_lote_y_el_flujo_completo(cliente):
    uid, otra, t, vs = _web(cliente)
    panel = cliente.get("/guilda-fiscal/vencimientos?dias=180").get_data(as_text=True)
    assert 'name="ids"' in panel and "Cambiar varios a la vez" in panel
    r = cliente.post("/guilda-fiscal/masivo/proponer", data={"tipo": "reasignar", "usuario_id": str(otra), "ids": [str(v) for v in vs]})
    assert r.status_code == 302
    aid = int(r.headers["Location"].rstrip("/").split("/")[-1].split("?")[0])
    ver = cliente.get(f"/guilda-fiscal/masivo/{aid}").get_data(as_text=True)
    assert "¿Aplicar este cambio?" in ver and "Titular Lote Web SL" in ver
    assert dict(obtener_vencimiento_fiscal(t, vs[0]))["usuario_id"] == uid                 # proponer no cambia nada
    assert cliente.post(f"/guilda-fiscal/masivo/{aid}/aplicar").status_code == 302
    assert dict(obtener_vencimiento_fiscal(t, vs[0]))["usuario_id"] == otra
    assert "Cambio aplicado" in cliente.get(f"/guilda-fiscal/masivo/{aid}").get_data(as_text=True)
    assert "Reasignar" in cliente.get("/guilda-fiscal/masivo/").get_data(as_text=True) or "responsable" in cliente.get("/guilda-fiscal/masivo/").get_data(as_text=True)
    assert cliente.post(f"/guilda-fiscal/masivo/{aid}/deshacer").status_code == 302
    assert dict(obtener_vencimiento_fiscal(t, vs[0]))["usuario_id"] == uid
    mal = cliente.post("/guilda-fiscal/masivo/proponer", data={"tipo": "posponer", "dias": "5", "ids": [str(vs[0])]})
    assert mal.status_code == 302 and "error=" in mal.headers["Location"]                  # sin motivo
    assert fm.historial(t, uid)[0]["estado"] == "deshecha"
