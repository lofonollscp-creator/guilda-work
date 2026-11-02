"""Pantallas de los cambios en lote del Comercial (app/rutas_comercial.py). Con Kratos real."""
from app import comercial as co, db, verticales
from tests.conftest import iniciar_sesion_de_prueba


def _web(cliente, email="masivoweb@ejemplo.com", activo=True):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant("Despacho " + email)
    db.asignar_tenant(uid, t)
    if activo:
        verticales.fijar_activo(t, "comercial", True)
    return uid, t


def test_flujo_completo_desde_la_lista(cliente):
    uid, t = _web(cliente)
    ids = [co.crear_oportunidad(t, uid, f"Op {i}", contacto_nombre="P") for i in range(3)]
    html = cliente.get("/comercial/?vista=lista").get_data(as_text=True)
    assert 'name="ids"' in html and "Cambiar varias a la vez" in html

    r = cliente.post("/comercial/masivo/proponer", data={"ids": [str(i) for i in ids], "tipo": "mover_etapa", "etapa": "reunion"})
    assert r.status_code == 302
    url = r.headers["Location"]
    ver = cliente.get(url).get_data(as_text=True)
    assert "¿Aplicar este cambio?" in ver and "Aplicar a 3 oportunidades" in ver
    assert all(co.obtener_oportunidad(t, uid, i)["etapa"] == "nuevo" for i in ids)                  # proponer no cambia nada

    r = cliente.post(url + "/aplicar")
    assert r.status_code == 302
    assert "Cambio aplicado" in cliente.get(url).get_data(as_text=True) and all(co.obtener_oportunidad(t, uid, i)["etapa"] == "reunion" for i in ids)
    assert "Cambio aplicado" in cliente.get("/comercial/masivo").get_data(as_text=True) or "se puede deshacer" in cliente.get("/comercial/masivo").get_data(as_text=True)

    cliente.post(url + "/deshacer")
    assert "Cambio deshecho" in cliente.get(url).get_data(as_text=True) and all(co.obtener_oportunidad(t, uid, i)["etapa"] == "nuevo" for i in ids)


def test_la_papelera_exige_escribir_el_recuento(cliente):
    uid, t = _web(cliente)
    ids = [co.crear_oportunidad(t, uid, f"Op {i}", contacto_nombre="P") for i in range(2)]
    url = cliente.post("/comercial/masivo/proponer", data={"ids": [str(i) for i in ids], "tipo": "papelera"}).headers["Location"]
    assert "2 oportunidades" in cliente.get(url).get_data(as_text=True)
    mal = cliente.post(url + "/aplicar", data={"confirmacion": "no"}, follow_redirects=True).get_data(as_text=True)
    assert "para confirmar" in mal and len(co.listar_oportunidades(t, uid)) == 2
    cliente.post(url + "/aplicar", data={"confirmacion": "2 oportunidades"})
    assert co.listar_oportunidades(t, uid) == []


def test_sin_seleccion_vuelve_a_la_lista_con_el_error_y_sin_el_modulo_no_existe(cliente):
    uid, t = _web(cliente)
    r = cliente.post("/comercial/masivo/proponer", data={"tipo": "mover_etapa", "etapa": "reunion"})
    assert r.status_code == 302 and "error=" in r.headers["Location"]
    assert cliente.get("/comercial/masivo/9999").status_code == 404
    verticales.fijar_activo(t, "comercial", False)
    assert cliente.get("/comercial/masivo").status_code == 404
