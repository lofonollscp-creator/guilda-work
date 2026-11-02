"""Pantalla de los honorarios por tramos (app/rutas_honorarios.py). Con Kratos real."""
from app import db, honorarios as h, verticales
from app.db_fiscal import crear_cliente_fiscal, crear_vencimiento_fiscal, marcar_presentado_vencimiento_fiscal
from tests.conftest import iniciar_sesion_de_prueba


def _web(cliente, email="honorariosweb@ejemplo.com", activo=True, director=True):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant("Despacho " + email)
    db.asignar_tenant(uid, t)
    if director:
        db.asignar_supervisor_tenant(uid, True)
    if activo:
        verticales.fijar_activo(t, "fiscal", True)
    c = crear_cliente_fiscal(t, "Titular Web SL", nif="A12345674")
    return uid, t, c


def test_sin_el_modulo_no_existe(cliente):
    _web(cliente, activo=False)
    assert cliente.get("/guilda-fiscal/honorarios/").status_code == 404


def test_flujo_completo_de_reglas_propuesta_y_confirmacion(cliente):
    uid, t, c = _web(cliente)
    r = cliente.get("/guilda-fiscal/honorarios/")
    assert r.status_code == 200 and "Aún no hay reglas" in r.get_data(as_text=True)

    mala = cliente.post("/guilda-fiscal/honorarios/reglas", data={"nombre": "Tramos", "calculo": "tramos", "tramos": "diez: 5"})
    assert mala.status_code == 302 and "error=" in mala.headers["Location"]
    ok = cliente.post("/guilda-fiscal/honorarios/reglas", data={"nombre": "303 por tramos", "prioridad": "10", "modelo": "303", "calculo": "tramos", "tramos": "hasta 10: 60,00\nresto: 90,00"})
    assert ok.status_code == 302 and "error" not in ok.headers["Location"]
    pagina = cliente.get("/guilda-fiscal/honorarios/").get_data(as_text=True)
    assert "303 por tramos" in pagina and "60,00 €" in pagina and "90,00 €" in pagina

    editar = cliente.get(f"/guilda-fiscal/honorarios/?editar={h.listar_reglas(t)[0]['id']}").get_data(as_text=True)
    assert "hasta 10: 60,00" in editar and "Editar regla" in editar
    sim = cliente.get("/guilda-fiscal/honorarios/?sim_modelo=303&sim_forma=&sim_apuntes=25").get_data(as_text=True)
    assert "90,00 €" in sim and "regla" in sim

    v = crear_vencimiento_fiscal(t, c, "303", "2T 2026", "2026-07-20", usuario_id=uid)
    marcar_presentado_vencimiento_fiscal(t, v, uid)
    assert "Titular Web SL" in cliente.get("/guilda-fiscal/honorarios/").get_data(as_text=True)
    assert cliente.post(f"/guilda-fiscal/honorarios/vencimientos/{v}/confirmar", data={"importe": "x"}).headers["Location"].find("error=") > 0
    assert cliente.post(f"/guilda-fiscal/honorarios/vencimientos/{v}/confirmar", data={"importe": "75,50"}).status_code == 302
    a = h.aplicado_de(t, v)
    assert a["importe_centimos"] == 7550
    pagina = cliente.get("/guilda-fiscal/honorarios/").get_data(as_text=True)
    assert "Honorarios 303 2T 2026".replace("Honorarios ", "Honorarios modelo ") in pagina and "75,50 €" in pagina
    assert "error=" in cliente.post(f"/guilda-fiscal/honorarios/aplicados/{a['id']}/facturar", data={"referencia": ""}).headers["Location"]
    cliente.post(f"/guilda-fiscal/honorarios/aplicados/{a['id']}/facturar", data={"referencia": "F-1"})
    assert h.aplicado_de(t, v)["estado"] == "facturado"
    cliente.post(f"/guilda-fiscal/honorarios/aplicados/{a['id']}/anular", data={"motivo": "Error de importe"})
    assert h.aplicado_de(t, v) is None
    cliente.post(f"/guilda-fiscal/honorarios/reglas/{h.listar_reglas(t)[0]['id']}/activar")
    assert h.listar_reglas(t)[0]["activa"] == 0
    cliente.post(f"/guilda-fiscal/honorarios/reglas/{h.listar_reglas(t)[0]['id']}/eliminar")
    assert h.listar_reglas(t) == []


def test_quien_no_dirige_ve_pero_no_gestiona(cliente):
    uid, t, c = _web(cliente, "prepara@ejemplo.com", director=False)
    pagina = cliente.get("/guilda-fiscal/honorarios/").get_data(as_text=True)
    assert "Nueva regla" not in pagina
    r = cliente.post("/guilda-fiscal/honorarios/reglas", data={"nombre": "X", "calculo": "fijo", "importe": "5"})
    assert "error=" in r.headers["Location"] and h.listar_reglas(t) == []
