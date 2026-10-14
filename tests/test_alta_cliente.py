"""Alta única de cliente (app/alta_cliente.py): el cliente del núcleo y su ficha fiscal se crean y se enlazan desde un solo camino."""
import json

import pytest

from app import alta_cliente, db, nucleo, verticales
from tests.conftest import iniciar_sesion_de_prueba


def _despacho(nombre="Despacho alta"):
    return db.crear_tenant(nombre)


def _con_despacho(cliente, email="alta@ejemplo.com"):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant(f"Despacho {email}")
    db.asignar_tenant(uid, t)
    return uid, t


def test_sin_gestion_fiscal_solo_crea_la_ficha_del_nucleo():
    t = _despacho()
    res = alta_cliente.crear_cliente_completo(t, "Ana Ruiz", nif="12345678Z")
    assert res["cliente_fiscal_id"] is None
    assert nucleo.obtener_cliente(t, res["cliente_id"])["cliente_fiscal_id"] is None
    assert db.listar_clientes_fiscales(t) == []


def test_con_gestion_fiscal_crea_las_dos_fichas_enlazadas_con_todos_los_datos():
    t = _despacho()
    res = alta_cliente.crear_cliente_completo(
        t, "Panadería SL", gestion_fiscal=True, nif="B12345678", email="pan@ejemplo.com", telefono="600111222", origen="Recomendación",
        etiquetas=["vip"], idioma="ca", pais="ES", perfil_tipo="sociedad", perfil_atributos=["iva"], generacion_automatica=True,
    )
    c = nucleo.obtener_cliente(t, res["cliente_id"])
    assert c["cliente_fiscal_id"] == res["cliente_fiscal_id"]
    assert (c["telefono"], c["origen"], c["tipo"]) == ("600111222", "Recomendación", "empresa")
    assert nucleo.etiquetas_de(res["cliente_id"]) == ["vip"]
    f = db.obtener_cliente_fiscal(t, res["cliente_fiscal_id"])
    assert f["cliente_id"] == res["cliente_id"] and f["idioma"] == "ca" and f["pais"] == "ES"
    assert json.loads(f["perfil_fiscal"]) == {"tipo": "sociedad", "atributos": ["iva"]}
    # El perfil propone los modelos y la generación automática queda activa porque España tiene calendario.
    assert db.modelos_fiscales_de_cliente(f) == ["303", "390", "200"]
    assert f["generacion_automatica"] == 1
    assert len(nucleo.listar_clientes(t)[0]) == 1  # no se duplica la ficha del núcleo


def test_pais_sin_calendario_no_activa_la_generacion_automatica():
    t = _despacho()
    res = alta_cliente.crear_cliente_completo(
        t, "Cliente Extranjero", gestion_fiscal=True, pais="OTRO", perfil_tipo="autonomo", perfil_atributos=["iva"], generacion_automatica=True,
    )
    f = db.obtener_cliente_fiscal(t, res["cliente_fiscal_id"])
    assert f["pais"] == "OTRO" and f["generacion_automatica"] == 0


def test_un_error_de_validacion_no_crea_nada():
    t = _despacho()
    with pytest.raises(ValueError):
        alta_cliente.crear_cliente_completo(t, "  ", gestion_fiscal=True)
    assert nucleo.listar_clientes(t)[1] == 0 and db.listar_clientes_fiscales(t) == []


def test_si_falla_la_ficha_fiscal_no_queda_un_cliente_huerfano(monkeypatch):
    t = _despacho()

    def falla(*a, **k):
        raise RuntimeError("fallo de prueba")

    monkeypatch.setattr(db, "crear_cliente_fiscal", falla)
    with pytest.raises(RuntimeError):
        alta_cliente.crear_cliente_completo(t, "Huérfano", gestion_fiscal=True, etiquetas=["x"])
    assert nucleo.listar_clientes(t)[1] == 0


def test_activar_gestion_fiscal_enlaza_con_el_cliente_existente_sin_duplicarlo():
    t = _despacho()
    cid = nucleo.crear_cliente(t, "Solo núcleo", nif="12345678Z", email="n@ejemplo.com", notas="nota")
    fid = alta_cliente.activar_gestion_fiscal(t, cid, perfil_tipo="autonomo", perfil_atributos=["iva", "estimacion_directa"])
    f = db.obtener_cliente_fiscal(t, fid)
    assert f["cliente_id"] == cid and f["nombre"] == "Solo núcleo" and f["email"] == "n@ejemplo.com" and f["notas"] == "nota"
    assert db.modelos_fiscales_de_cliente(f) == ["303", "390", "130"]
    assert nucleo.listar_clientes(t)[1] == 1
    with pytest.raises(ValueError):
        alta_cliente.activar_gestion_fiscal(t, cid)


def test_activar_gestion_fiscal_de_otro_despacho_no_existe():
    t1, t2 = _despacho("A"), _despacho("B")
    cid = nucleo.crear_cliente(t1, "De A")
    with pytest.raises(ValueError):
        alta_cliente.activar_gestion_fiscal(t2, cid)


def test_el_alta_rapida_de_fiscal_y_la_api_usan_el_mismo_camino(monkeypatch):
    t = _despacho()
    vinculos = []
    monkeypatch.setattr(alta_cliente, "vincular_espocrm", lambda tenant, fid, nombre: vinculos.append((tenant, fid, nombre)))
    res = alta_cliente.crear_cliente_completo(t, "Con CRM", gestion_fiscal=True)
    assert vinculos == [(t, res["cliente_fiscal_id"], "Con CRM")]


# --- Pantallas ------------------------------------------------------------------------------------------------------------------------------

def test_formulario_de_alta_ofrece_la_gestion_fiscal_si_el_despacho_la_lleva(cliente):
    uid, t = _con_despacho(cliente)
    html = cliente.get("/clientes/nuevo").get_data(as_text=True)
    assert 'name="gestion_fiscal"' in html and 'name="perfil_tipo"' in html and 'name="pais"' in html
    verticales.fijar_activo(t, "gestoria", False)
    try:
        assert 'name="gestion_fiscal"' not in cliente.get("/clientes/nuevo").get_data(as_text=True)
    finally:
        verticales.quitar_ajuste_manual(t, "gestoria")


def test_alta_desde_la_web_con_gestion_fiscal_crea_ambas_fichas(cliente):
    uid, t = _con_despacho(cliente, "alta-web@ejemplo.com")
    r = cliente.post("/clientes/nuevo", data={
        "nombre": "Autónomo Web", "nif": "12345678Z", "email": "web@ejemplo.com", "gestion_fiscal": "1", "pais": "ES", "perfil_tipo": "autonomo",
        "perfil_atributos": ["iva", "estimacion_directa"], "generacion_automatica": "1",
    })
    assert r.status_code == 302
    cid = int(r.headers["Location"].rsplit("/", 1)[1])
    c = nucleo.obtener_cliente(t, cid)
    f = db.obtener_cliente_fiscal(t, c["cliente_fiscal_id"])
    assert db.modelos_fiscales_de_cliente(f) == ["303", "390", "130"] and f["generacion_automatica"] == 1


def test_alta_desde_la_web_sin_marcar_gestion_fiscal_solo_crea_el_nucleo(cliente):
    uid, t = _con_despacho(cliente, "alta-nucleo@ejemplo.com")
    r = cliente.post("/clientes/nuevo", data={"nombre": "Solo Núcleo", "perfil_tipo": "sociedad"})
    cid = int(r.headers["Location"].rsplit("/", 1)[1])
    assert nucleo.obtener_cliente(t, cid)["cliente_fiscal_id"] is None
    assert db.listar_clientes_fiscales(t) == []


def test_la_ficha_ofrece_activar_la_gestion_fiscal_y_deja_de_hacerlo_una_vez_activada(cliente):
    uid, t = _con_despacho(cliente, "activar@ejemplo.com")
    cid = nucleo.crear_cliente(t, "Cliente Núcleo")
    assert "Activar gestión fiscal" in cliente.get(f"/clientes/{cid}").get_data(as_text=True)
    r = cliente.post(f"/clientes/{cid}/gestion-fiscal", data={"perfil_tipo": "sociedad", "perfil_atributos": ["iva"]})
    assert r.status_code == 302
    html = cliente.get(f"/clientes/{cid}").get_data(as_text=True)
    assert "Activar gestión fiscal" not in html and "Ficha fiscal" in html
    assert nucleo.obtener_cliente(t, cid)["cliente_fiscal_id"] is not None


def test_activar_gestion_fiscal_de_otro_despacho_da_404(cliente):
    uid, t = _con_despacho(cliente, "activar-otro@ejemplo.com")
    ajeno = nucleo.crear_cliente(db.crear_tenant("Otro despacho"), "Ajeno")
    assert cliente.post(f"/clientes/{ajeno}/gestion-fiscal").status_code == 404


def test_activar_gestion_fiscal_exige_el_modulo_de_gestoria(cliente):
    uid, t = _con_despacho(cliente, "activar-sin-modulo@ejemplo.com")
    cid = nucleo.crear_cliente(t, "Cliente Núcleo")
    verticales.fijar_activo(t, "gestoria", False)
    try:
        assert cliente.post(f"/clientes/{cid}/gestion-fiscal").status_code == 404
        assert "Activar gestión fiscal" not in cliente.get(f"/clientes/{cid}").get_data(as_text=True)
    finally:
        verticales.quitar_ajuste_manual(t, "gestoria")


def test_alta_rapida_de_fiscal_crea_tambien_la_ficha_del_nucleo(cliente):
    uid, t = _con_despacho(cliente, "rapida@ejemplo.com")
    assert cliente.post("/fiscal/clientes", data={"nombre": "Rápido SL", "nif": "B12345678"}).status_code == 302
    f = db.listar_clientes_fiscales(t)[0]
    assert f["cliente_id"] is not None and nucleo.obtener_cliente(t, f["cliente_id"])["nombre"] == "Rápido SL"
