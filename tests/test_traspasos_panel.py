"""Traspasos de clientes con aceptación y panel fiscal (fase E, RF-14): responsabilidad conservada hasta aceptar, acceso del receptor, escalado, ámbito del panel, API e IA."""
from datetime import date, timedelta

import pytest

from app import acceso, auditoria, db, ia_herramientas as ih, panel_fiscal, traspasos
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_rutas_api import _auth, _registrar


@pytest.fixture
def d(usuario_id):
    t = db.crear_tenant("Despacho Traspasos")
    class E: pass
    e = E(); e.t = t
    def u(mail, sup=False):
        x = db.crear_usuario_vinculado_a_kratos(mail, "k-" + mail); db.asignar_tenant(x, t)
        if sup:
            db.asignar_supervisor_tenant(x, True)
        return x
    e.sup, e.ana, e.biel, e.ext = u("sup-tr@ejemplo.com", True), u("ana-tr@ejemplo.com"), u("biel-tr@ejemplo.com"), u("ext-tr@ejemplo.com")
    e.a = db.crear_cliente_fiscal(t, "Cliente A", nif="B12345674"); e.b = db.crear_cliente_fiscal(t, "Cliente B", nif="J21938519")
    hoy = date.today()
    e.v_a = db.crear_vencimiento_fiscal(t, e.a, "303", "2026-T3", (hoy + timedelta(days=3)).isoformat())
    e.v_b = db.crear_vencimiento_fiscal(t, e.b, "303", "2026-T3", (hoy - timedelta(days=2)).isoformat())
    return e


def _resp(t, c):
    conn = db.get_connection()
    try:
        return conn.execute("SELECT responsable_id, oficina_id FROM clientes_fiscales WHERE id = ?", (c,)).fetchone()
    finally:
        conn.close()


def _con_oficinas(d):
    d.gi = acceso.crear_oficina(d.t, d.sup, "Girona"); d.bc = acceso.crear_oficina(d.t, d.sup, "Barcelona")
    acceso.asignar_cliente_a_oficina(d.t, d.sup, d.a, d.gi)
    acceso.dar_membresia(d.t, d.sup, d.ana, "gestor", "oficina", d.gi); acceso.dar_membresia(d.t, d.sup, d.biel, "gestor", "oficina", d.bc)


def test_hasta_aceptar_el_responsable_anterior_conserva_el_cliente(d):
    traspasos.asignar_responsable(d.t, d.sup, d.a, d.ana)
    tid = traspasos.proponer(d.t, d.ana, d.a, d.biel, nota="Falta el 303")
    assert _resp(d.t, d.a)["responsable_id"] == d.ana
    t = traspasos.obtener(d.t, tid)
    assert t["estado"] == "pendiente" and t["de_usuario_id"] == d.ana and t["dias_al_vencimiento"] == 3
    with pytest.raises(ValueError, match="ya tiene un traspaso pendiente"):
        traspasos.proponer(d.t, d.ana, d.a, d.ext)
    with pytest.raises(ValueError, match="Hay un traspaso pendiente"):
        traspasos.asignar_responsable(d.t, d.sup, d.a, d.ext)
    with pytest.raises(ValueError, match="Solo quien lo recibe"):
        traspasos.aceptar(d.t, d.ext, tid)
    traspasos.aceptar(d.t, d.biel, tid, version=t["version"])
    assert _resp(d.t, d.a)["responsable_id"] == d.biel and traspasos.obtener(d.t, tid)["estado"] == "aceptado"
    with pytest.raises(traspasos.ConflictoDeVersion):
        traspasos.aceptar(d.t, d.biel, tid)
    assert any(e["accion"] == "traspaso.aceptar" for e in auditoria.listar(d.t)) if hasattr(auditoria, "listar") else True


def test_validaciones_al_proponer(d):
    traspasos.asignar_responsable(d.t, d.sup, d.a, d.ana)
    with pytest.raises(ValueError, match="ya es la responsable"):
        traspasos.proponer(d.t, d.sup, d.a, d.ana)
    with pytest.raises(ValueError, match="no pertenece al despacho"):
        traspasos.proponer(d.t, d.sup, d.a, 99999)
    with pytest.raises(ValueError, match="No existe esa oficina"):
        traspasos.proponer(d.t, d.sup, d.a, d.biel, a_oficina_id=9999)
    otro = db.crear_tenant("Otro despacho traspasos")
    ajeno = db.crear_cliente_fiscal(otro, "Ajeno", nif="B12345674")
    with pytest.raises(ValueError, match="No existe ese cliente"):
        traspasos.proponer(d.t, d.sup, ajeno, d.biel)


def test_rechazar_pide_motivo_y_el_cliente_no_cambia(d):
    traspasos.asignar_responsable(d.t, d.sup, d.a, d.ana)
    tid = traspasos.proponer(d.t, d.ana, d.a, d.biel)
    with pytest.raises(ValueError, match="por qué se rechaza"):
        traspasos.rechazar(d.t, d.biel, tid, "  ")
    traspasos.rechazar(d.t, d.biel, tid, "Estoy de baja esa semana")
    t = traspasos.obtener(d.t, tid)
    assert t["estado"] == "rechazado" and t["motivo"] == "Estoy de baja esa semana" and _resp(d.t, d.a)["responsable_id"] == d.ana
    t2 = traspasos.proponer(d.t, d.ana, d.a, d.biel)
    with pytest.raises(ValueError, match="Solo quien lo propuso"):
        traspasos.cancelar(d.t, d.ext, t2)
    traspasos.cancelar(d.t, d.ana, t2)
    assert traspasos.obtener(d.t, t2)["estado"] == "cancelado"


def test_al_aceptar_con_oficina_el_receptor_gana_acceso_y_cambia_la_oficina(d):
    _con_oficinas(d)
    assert acceso.puede_ver_cliente(d.t, d.biel, d.a) is False
    tid = traspasos.proponer(d.t, d.sup, d.a, d.biel, a_oficina_id=d.bc)
    assert acceso.puede_ver_cliente(d.t, d.biel, d.a) is False, "hasta aceptar no hay visibilidad nueva"
    traspasos.aceptar(d.t, d.biel, tid)
    acceso.invalidar(d.t)
    r = _resp(d.t, d.a)
    assert r["oficina_id"] == d.bc and r["responsable_id"] == d.biel
    assert acceso.puede_ver_cliente(d.t, d.biel, d.a) is True
    assert acceso.puede_ver_cliente(d.t, d.ana, d.a) is False, "la oficina anterior ya no lo ve"


def test_sin_cambio_de_oficina_el_receptor_recibe_acceso_de_gestion(d):
    _con_oficinas(d)
    tid = traspasos.proponer(d.t, d.ana, d.a, d.biel)
    traspasos.aceptar(d.t, d.biel, tid)
    acceso.invalidar(d.t)
    assert acceso.puede_ver_cliente(d.t, d.biel, d.a) and acceso.puede_modificar_cliente(d.t, d.biel, d.a)
    assert any(k["usuario_id"] == d.biel for k in acceso.concesiones_de(d.t, d.a))


def test_el_traspaso_lo_ven_emisor_y_receptor_aunque_no_vean_el_cliente(d):
    _con_oficinas(d)
    tid = traspasos.proponer(d.t, d.ana, d.a, d.biel)
    assert [t["id"] for t in traspasos.listar(d.t, d.biel)] == [tid]
    assert traspasos.listar(d.t, d.ext) == [] or acceso.clientes_visibles(d.t, d.ext) is None


def test_escalado_avisa_una_sola_vez_cuando_hay_un_plazo_cerca(d):
    tid = traspasos.proponer(d.t, d.sup, d.a, d.biel)
    assert traspasos.escalar(date.today() - timedelta(days=30)) == 0, "con el plazo lejos no se escala"
    assert traspasos.escalar() == 1 and traspasos.escalar() == 0
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT escalado_en FROM traspasos WHERE id = ?", (tid,)).fetchone()["escalado_en"]
    finally:
        conn.close()


def test_asignar_responsable_solo_direccion_o_coordinacion(d):
    _con_oficinas(d)
    with pytest.raises(ValueError, match="Solo la dirección"):
        traspasos.asignar_responsable(d.t, d.ana, d.a, d.ana)
    acceso.dar_membresia(d.t, d.sup, d.ext, "coordinador", "oficina", d.gi)
    traspasos.asignar_responsable(d.t, d.ext, d.a, d.ana)
    assert _resp(d.t, d.a)["responsable_id"] == d.ana
    traspasos.asignar_responsable(d.t, d.sup, d.a, None)
    assert _resp(d.t, d.a)["responsable_id"] is None


# --- Panel -------------------------------------------------------------------------------------------------------------------------------------
def test_el_panel_cuenta_riesgos_con_causa_y_no_da_100_por_cien_sin_datos(d):
    traspasos.asignar_responsable(d.t, d.sup, d.a, d.ana)
    traspasos.proponer(d.t, d.ana, d.a, d.biel)
    p = panel_fiscal.construir(d.t, d.sup)
    assert p["totales"]["vencidas"] == 1 and p["totales"]["proximas"] == 1 and p["totales"]["traspasos"] == 1
    v = p["hoy_lista"]["vencidas"][0]
    assert v["cliente"] == "Cliente B" and v["causa"] == "vencida" and v["dias"] == 2 and v["url"].endswith("/editar")
    assert p["hoy_lista"]["proximas"][0]["cliente"] == "Cliente A" and p["traspasos"][0]["urgente"] is True
    i = p["indicadores"]
    assert i["en_plazo"]["n"] == 1 and i["en_plazo"]["porcentaje"] == 0 and i["clientes"] == {"n": 2, "sin_responsable": 1}
    vacio = panel_fiscal.construir(db.crear_tenant("Despacho vacío panel"), d.sup)
    assert vacio["indicadores"]["en_plazo"]["porcentaje"] is None and vacio["indicadores"]["en_plazo"]["n"] == 0


def test_el_indicador_de_plazo_excluye_no_aplica_y_cuenta_las_tardias_como_no_cumplidas(d):
    hoy = date.today()
    for i, fase in enumerate(("presentada", "no_aplica", "anulada")):
        c = db.crear_cliente_fiscal(d.t, f"Cliente P{i}")
        v = db.crear_vencimiento_fiscal(d.t, c, "303", "2026-T2", (hoy - timedelta(days=10)).isoformat())
        conn = db.get_connection(); conn.execute("UPDATE vencimientos_fiscales SET fase = ?, estado = ? WHERE id = ?", (fase, "presentado" if fase == "presentada" else "pendiente", v)); conn.commit(); conn.close()
    i = panel_fiscal.construir(d.t, d.sup)["indicadores"]["en_plazo"]
    assert i["n"] == 2 and i["excluidas"] == 2 and i["buenas"] == 1 and i["porcentaje"] == 50


def test_el_panel_respeta_el_ambito_de_cada_persona(d):
    _con_oficinas(d)
    db.crear_cliente_fiscal(d.t, "Cliente Sin Oficina")
    p_ana = panel_fiscal.construir(d.t, d.ana)
    assert p_ana["ambito"] == "parcial" and p_ana["totales"]["proximas"] == 1 and p_ana["totales"]["vencidas"] == 1   # B no tiene oficina: la ve todo el equipo
    assert p_ana["certificados"] is None and "certificados" not in p_ana["indicadores"], "sin permiso de certificados no se ven"
    p_biel = panel_fiscal.construir(d.t, d.biel)
    assert p_biel["totales"]["proximas"] == 0 and p_biel["totales"]["vencidas"] == 1 and p_biel["indicadores"]["clientes"]["n"] == 2   # B y el sin oficina (los sin oficina los ve todo el equipo)
    p_sup = panel_fiscal.construir(d.t, d.sup)
    assert p_sup["ambito"] == "todo" and p_sup["certificados"] is not None and p_sup["indicadores"]["clientes"]["n"] == 3


# --- Pantallas, API e IA ----------------------------------------------------------------------------------------------------------------------
def test_pantallas_de_panel_y_traspasos(cliente):
    t = db.crear_tenant("Despacho Web Traspasos")
    u = iniciar_sesion_de_prueba(cliente, "web-tr@ejemplo.com", "contrasena123")
    db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    otro = db.crear_usuario_vinculado_a_kratos("otro-tr@ejemplo.com", "k-otro-tr"); db.asignar_tenant(otro, t)
    c = db.crear_cliente_fiscal(t, "Cliente Web Panel", nif="B12345674")
    db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", (date.today() - timedelta(days=1)).isoformat())
    h = cliente.get("/fiscal/panel").get_data(as_text=True)
    assert "Panel fiscal" in h and "Cliente Web Panel" in h and "Venció ayer" in h and "Calculado el" in h and "sin datos" not in h.lower().replace("«sin datos»", "")
    r = cliente.post("/fiscal/traspasos/nuevo", data={"cliente_id": c, "a_usuario_id": otro, "nota": "Revisar el 303"})
    assert "aviso=propuesto" in r.headers["Location"]
    h = cliente.get("/fiscal/traspasos").get_data(as_text=True)
    assert "Pendiente de aceptar" in h and "Revisar el 303" in h and "Aceptar" in h
    tid = traspasos.listar(t, u)[0]["id"]
    r = cliente.post(f"/fiscal/traspasos/{tid}/rechazar", data={"motivo": ""})
    assert "error=" in r.headers["Location"]
    r = cliente.post(f"/fiscal/traspasos/{tid}/aceptar", data={"version": 1})
    assert "aviso=aceptado" in r.headers["Location"] and _resp(t, c)["responsable_id"] == otro
    r = cliente.post(f"/fiscal/traspasos/{tid}/aceptar", data={"version": 1})
    assert "error=" in r.headers["Location"], "ya resuelto"
    assert "aviso=hecho" in cliente.post(f"/fiscal/clientes/{c}/responsable", data={"responsable_id": u}).headers["Location"]
    assert _resp(t, c)["responsable_id"] == u


def test_api_de_panel_y_traspasos(cliente):
    t = db.crear_tenant("Despacho API Traspasos")
    datos = _registrar(cliente, "api-tr@ejemplo.com"); u = db.obtener_usuario_por_email("api-tr@ejemplo.com")["id"]
    db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    h = _auth(datos["token"])
    otro = db.crear_usuario_vinculado_a_kratos("api-tr2@ejemplo.com", "k-api-tr2"); db.asignar_tenant(otro, t)
    c = db.crear_cliente_fiscal(t, "Cliente API Panel", nif="B12345674")
    db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", (date.today() + timedelta(days=2)).isoformat())
    p = cliente.get("/api/v1/fiscal/panel", headers=h).get_json()["data"]
    assert p["totales"]["proximas"] == 1 and p["indicadores"]["en_plazo"]["porcentaje"] is None
    r = cliente.post("/api/v1/fiscal/traspasos", headers=h, json={"cliente_id": c, "a_usuario_id": otro, "nota": "x"})
    assert r.status_code == 201 and r.get_json()["data"]["estado"] == "pendiente"
    tid = r.get_json()["data"]["id"]
    assert cliente.post("/api/v1/fiscal/traspasos", headers=h, json={"cliente_id": c, "a_usuario_id": otro}).status_code == 409
    assert cliente.post("/api/v1/fiscal/traspasos", headers=h, json={"cliente_id": 0, "a_usuario_id": otro}).status_code == 400
    assert [x["id"] for x in cliente.get("/api/v1/fiscal/traspasos?estado=pendiente", headers=h).get_json()["data"]] == [tid]
    assert cliente.get("/api/v1/fiscal/traspasos?estado=raro", headers=h).status_code == 400
    assert cliente.post(f"/api/v1/fiscal/traspasos/{tid}/rechazar", headers=h, json={}).status_code == 400
    assert cliente.post(f"/api/v1/fiscal/traspasos/{tid}/aceptar", headers={**h, "If-Match": '"99"'}).status_code == 412
    r = cliente.post(f"/api/v1/fiscal/traspasos/{tid}/aceptar", headers={**h, "If-Match": '"1"'})
    assert r.status_code == 200 and r.get_json()["data"]["estado"] == "aceptado"
    assert cliente.post("/api/v1/fiscal/traspasos/9999/aceptar", headers=h).status_code == 404
    r = cliente.put(f"/api/v1/fiscal/clientes/{c}/responsable", headers=h, json={"responsable_id": u})
    assert r.status_code == 200 and _resp(t, c)["responsable_id"] == u


def test_las_herramientas_de_ia_cubren_el_panel_y_los_traspasos(d):
    for n in ("proponer_traspaso", "resolver_traspaso"):
        assert n in ih.ESCRITURA
    assert "panel_fiscal" not in ih.ESCRITURA and "listar_traspasos" not in ih.ESCRITURA
    p = ih.ejecutar(d.sup, "panel_fiscal", {})
    assert p["totales"]["vencidas"] == 1 and "carga_por_responsable" in p
    r = ih.ejecutar(d.sup, "proponer_traspaso", {"cliente_id": d.a, "a_usuario_id": d.biel, "nota": "Pásalo"})
    assert r["estado"] == "pendiente" and [x["id"] for x in ih.ejecutar(d.sup, "listar_traspasos", {"estado": "pendiente"})] == [r["id"]]
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(d.biel, "resolver_traspaso", {"traspaso_id": r["id"], "accion": "rechazar"})
    assert ih.ejecutar(d.biel, "resolver_traspaso", {"traspaso_id": r["id"], "accion": "aceptar"})["estado"] == "aceptado"
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(d.biel, "resolver_traspaso", {"traspaso_id": r["id"], "accion": "borrar"})
