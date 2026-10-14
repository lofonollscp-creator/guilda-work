"""Plantillas de cliente (app/plantillas_cliente.py) y su uso en el alta (app/alta_cliente.py, /clientes/nuevo, /clientes/plantillas)."""
import json

import pytest

from app import alta_cliente, db, nucleo, plantillas_cliente, verticales
from tests.conftest import iniciar_sesion_de_prueba


def _despacho(nombre="Despacho plantillas"):
    t = db.crear_tenant(nombre)
    u = db.crear_usuario_vinculado_a_kratos(f"u-{nombre.replace(' ', '')}@ejemplo.com", f"k-{nombre}")
    db.asignar_tenant(u, t)
    return t, u


def _tareas_de(uid, fiscal_id):
    return [x for x in db.listar_tareas_outlook(uid) if x["cliente_fiscal_id"] == fiscal_id]


def test_hay_tres_de_serie_y_van_primero():
    t, _ = _despacho()
    plantillas_cliente.crear(t, _, "Comunidad de bienes", perfil_tipo="sociedad")
    ids = [p["id"] for p in plantillas_cliente.listar(t)]
    assert ids[:3] == ["serie:autonomo", "serie:sociedad", "serie:particular"] and len(ids) == 4


def test_crear_valida_y_no_admite_duplicados():
    t, u = _despacho()
    with pytest.raises(ValueError):
        plantillas_cliente.crear(t, u, "  ")
    with pytest.raises(ValueError):
        plantillas_cliente.crear(t, u, "x" * 81)
    with pytest.raises(ValueError):
        plantillas_cliente.crear(t, u, "Mala", perfil_tipo="inventado")
    plantillas_cliente.crear(t, u, "Pyme")
    with pytest.raises(ValueError):
        plantillas_cliente.crear(t, u, "pyme")          # mismo nombre sin distinguir mayúsculas
    t2, u2 = _despacho("Otro despacho plantillas")
    plantillas_cliente.crear(t2, u2, "Pyme")             # otro despacho sí puede


def test_la_plantilla_de_tareas_debe_existir_y_estar_compartida():
    t, u = _despacho()
    propia = db.crear_plantilla_tareas(u, "Solo mía", None, "Una tarea", compartida=False)
    with pytest.raises(ValueError):
        plantillas_cliente.crear(t, u, "A", plantilla_tareas_id=propia)
    with pytest.raises(ValueError):
        plantillas_cliente.crear(t, u, "B", plantilla_tareas_id=999999)
    compartida = db.crear_plantilla_tareas(u, "Para todos", None, "Una tarea", compartida=True)
    assert plantillas_cliente.crear(t, u, "C", plantilla_tareas_id=compartida)


def test_una_plantilla_de_otro_despacho_no_existe_y_las_de_serie_no_se_borran():
    t1, u1 = _despacho("Despacho uno plantillas")
    t2, _ = _despacho("Despacho dos plantillas")
    pid = plantillas_cliente.crear(t1, u1, "Mía")
    assert plantillas_cliente.obtener(t2, pid) is None and plantillas_cliente.obtener(t1, pid)["nombre"] == "Mía"
    assert plantillas_cliente.eliminar(t2, pid) is False
    assert plantillas_cliente.eliminar(t1, "serie:autonomo") is False and plantillas_cliente.obtener(t1, "serie:autonomo") is not None
    assert plantillas_cliente.eliminar(t1, pid) is True and plantillas_cliente.obtener(t1, pid) is None


def test_alta_con_plantilla_de_serie_pone_el_perfil_y_los_modelos():
    t, u = _despacho()
    res = alta_cliente.crear_cliente_completo(t, "Sociedad Uno SL", gestion_fiscal=True, plantilla_id="serie:sociedad", usuario_id=u)
    f = db.obtener_cliente_fiscal(t, res["cliente_fiscal_id"])
    assert json.loads(f["perfil_fiscal"]) == {"tipo": "sociedad", "atributos": ["iva"]}
    assert db.modelos_fiscales_de_cliente(f) == ["303", "390", "200"]


def test_lo_que_se_marca_a_mano_manda_sobre_la_plantilla():
    t, u = _despacho()
    res = alta_cliente.crear_cliente_completo(t, "A mano", gestion_fiscal=True, plantilla_id="serie:autonomo", perfil_tipo="sociedad", usuario_id=u)
    f = db.obtener_cliente_fiscal(t, res["cliente_fiscal_id"])
    assert json.loads(f["perfil_fiscal"]) == {"tipo": "sociedad", "atributos": []}, "el perfil del formulario sustituye al de la plantilla, no se mezclan"


def test_las_etiquetas_de_la_plantilla_se_suman_a_las_del_alta():
    t, u = _despacho()
    pid = plantillas_cliente.crear(t, u, "Con etiquetas", etiquetas="Renta, vip")
    res = alta_cliente.crear_cliente_completo(t, "Etiquetado", gestion_fiscal=True, etiquetas=["nuevo"], plantilla_id=pid, usuario_id=u)
    assert nucleo.etiquetas_de(res["cliente_id"]) == ["nuevo", "renta", "vip"]


def test_con_generacion_automatica_los_vencimientos_aparecen_en_el_alta():
    t, u = _despacho()
    pid = plantillas_cliente.crear(t, u, "Automática", perfil_tipo="sociedad", perfil_atributos=["iva"], generacion_automatica=True)
    res = alta_cliente.crear_cliente_completo(t, "Con vencimientos", gestion_fiscal=True, plantilla_id=pid, usuario_id=u)
    f = db.obtener_cliente_fiscal(t, res["cliente_fiscal_id"])
    assert f["generacion_automatica"] == 1 and res["vencimientos"] > 0
    assert len(db.listar_vencimientos_fiscales(t, cliente_fiscal_id=f["id"])) == res["vencimientos"]
    assert db.generar_vencimientos_automaticos() == 0, "el cron diario no duplica lo ya creado"


def test_las_tareas_iniciales_se_crean_a_nombre_de_quien_da_de_alta_y_ligadas_al_cliente():
    t, u = _despacho()
    tp = db.crear_plantilla_tareas(u, "Alta de cliente", None, "Pedir certificado | 0 | alta\nRevisar IVA | 7", compartida=True)
    pid = plantillas_cliente.crear(t, u, "Con tareas", perfil_tipo="autonomo", plantilla_tareas_id=tp)
    res = alta_cliente.crear_cliente_completo(t, "Con tareas SL", gestion_fiscal=True, plantilla_id=pid, usuario_id=u)
    assert res["tareas"] == 2
    assert sorted(x["asunto"] for x in _tareas_de(u, res["cliente_fiscal_id"])) == ["Pedir certificado", "Revisar IVA"]


def test_una_plantilla_que_no_existe_no_crea_nada():
    t, u = _despacho()
    with pytest.raises(ValueError):
        alta_cliente.crear_cliente_completo(t, "Fantasma", gestion_fiscal=True, plantilla_id="999999", usuario_id=u)
    assert nucleo.listar_clientes(t)[1] == 0


def test_si_fallan_los_pasos_posteriores_el_cliente_se_queda_creado(monkeypatch):
    t, u = _despacho()
    pid = plantillas_cliente.crear(t, u, "Frágil", perfil_tipo="sociedad", perfil_atributos=["iva"], generacion_automatica=True)

    def falla(*a, **k):
        raise RuntimeError("fallo de prueba")

    monkeypatch.setattr(db, "generar_vencimientos_de_cliente", falla)
    res = alta_cliente.crear_cliente_completo(t, "Sigue creado", gestion_fiscal=True, plantilla_id=pid, usuario_id=u)
    assert nucleo.listar_clientes(t)[1] == 1 and res["vencimientos"] == 0


def test_activar_gestion_fiscal_con_plantilla_aplica_perfil_y_etiquetas():
    t, u = _despacho()
    pid = plantillas_cliente.crear(t, u, "Para activar", perfil_tipo="autonomo", perfil_atributos=["iva"], etiquetas="renta")
    cid = nucleo.crear_cliente(t, "Cliente núcleo", etiquetas=["previa"])
    fid = alta_cliente.activar_gestion_fiscal(t, cid, plantilla_id=pid, usuario_id=u)
    assert json.loads(db.obtener_cliente_fiscal(t, fid)["perfil_fiscal"])["tipo"] == "autonomo"
    assert nucleo.etiquetas_de(cid) == ["previa", "renta"]


# --- Pantallas ------------------------------------------------------------------------------------------------------------------------------

def _con_despacho(cliente, email, supervisor=False):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant(f"Despacho {email}")
    db.asignar_tenant(uid, t)
    if supervisor:
        db.asignar_supervisor_tenant(uid, True)
    return uid, t


def test_la_dirección_crea_y_borra_plantillas_desde_la_web(cliente):
    uid, t = _con_despacho(cliente, "pl-sup@ejemplo.com", supervisor=True)
    assert "Autónomo" in cliente.get("/clientes/plantillas").get_data(as_text=True)
    r = cliente.post("/clientes/plantillas", data={"nombre": "Comunidad de bienes", "perfil_tipo": "sociedad", "perfil_atributos": ["iva"], "etiquetas": "cb"})
    assert r.status_code == 302 and "error" not in r.headers["Location"]
    pid = [p for p in plantillas_cliente.listar(t) if not p["de_serie"]][0]["id"]
    assert "Comunidad de bienes" in cliente.get("/clientes/plantillas").get_data(as_text=True)
    assert cliente.post(f"/clientes/plantillas/{pid}/eliminar").status_code == 302
    assert [p for p in plantillas_cliente.listar(t) if not p["de_serie"]] == []


def test_un_nombre_repetido_se_explica_en_pantalla(cliente):
    uid, t = _con_despacho(cliente, "pl-dup@ejemplo.com", supervisor=True)
    cliente.post("/clientes/plantillas", data={"nombre": "Pyme"})
    r = cliente.post("/clientes/plantillas", data={"nombre": "Pyme"}, follow_redirects=True)
    assert "Ya hay una plantilla con ese nombre" in r.get_data(as_text=True)


def test_quien_no_es_direccion_las_ve_y_las_usa_pero_no_las_gestiona(cliente):
    uid, t = _con_despacho(cliente, "pl-eq@ejemplo.com")
    html = cliente.get("/clientes/plantillas").get_data(as_text=True)
    assert "Autónomo" in html and "Crear plantilla" not in html
    assert cliente.post("/clientes/plantillas", data={"nombre": "Intento"}).status_code == 403
    assert cliente.post("/clientes/plantillas/serie:autonomo/eliminar").status_code == 403


def test_las_plantillas_no_existen_sin_el_modulo_de_gestoria(cliente):
    uid, t = _con_despacho(cliente, "pl-sin@ejemplo.com", supervisor=True)
    verticales.fijar_activo(t, "gestoria", False)
    try:
        assert cliente.get("/clientes/plantillas").status_code == 404
    finally:
        verticales.quitar_ajuste_manual(t, "gestoria")


def test_el_alta_web_aplica_la_plantilla_elegida(cliente):
    uid, t = _con_despacho(cliente, "pl-alta@ejemplo.com")
    assert 'name="plantilla_id"' in cliente.get("/clientes/nuevo").get_data(as_text=True)
    r = cliente.post("/clientes/nuevo", data={"nombre": "Alta con plantilla", "gestion_fiscal": "1", "plantilla_id": "serie:sociedad"})
    assert r.status_code == 302
    c = nucleo.obtener_cliente(t, int(r.headers["Location"].rsplit("/", 1)[1]))
    assert json.loads(db.obtener_cliente_fiscal(t, c["cliente_fiscal_id"])["perfil_fiscal"])["tipo"] == "sociedad"


def test_la_ficha_ofrece_las_plantillas_al_activar_la_gestion_fiscal(cliente):
    uid, t = _con_despacho(cliente, "pl-ficha@ejemplo.com")
    cid = nucleo.crear_cliente(t, "Cliente núcleo")
    assert 'name="plantilla_id"' in cliente.get(f"/clientes/{cid}").get_data(as_text=True)
    assert cliente.post(f"/clientes/{cid}/gestion-fiscal", data={"plantilla_id": "serie:autonomo"}).status_code == 302
    assert nucleo.obtener_cliente(t, cid)["cliente_fiscal_id"] is not None
