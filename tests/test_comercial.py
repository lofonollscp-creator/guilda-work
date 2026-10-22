"""Comercial (app/comercial.py): embudo de oportunidades, etapas, actividades con próxima acción, conversión en cliente, visibilidad por oficinas, informes y pantallas."""
from datetime import date, timedelta

import pytest

from app import acceso, comercial as co, db, verticales
from app.comercial import ErrorComercial
from tests.conftest import iniciar_sesion_de_prueba


@pytest.fixture
def d(base_de_datos_temporal):
    t = db.crear_tenant("Despacho comercial")
    verticales.fijar_activo(t, "comercial", True)
    class E: pass
    e = E(); e.t = t
    def u(mail, sup=False):
        x = db.crear_usuario_vinculado_a_kratos(mail, "k-" + mail); db.asignar_tenant(x, t)
        if sup:
            db.asignar_supervisor_tenant(x, True)
        return x
    e.sup, e.ana, e.beto, e.aud = u("sup-co@ejemplo.com", True), u("ana-co@ejemplo.com"), u("beto-co@ejemplo.com"), u("aud-co@ejemplo.com")
    acceso.dar_membresia(t, e.sup, e.aud, "auditor", "organizacion")
    return e


def _op(d, **kw):
    return co.crear_oportunidad(d.t, kw.pop("quien", d.ana), kw.pop("titulo", "Llevanza contable"), contacto_nombre=kw.pop("contacto_nombre", "Marta Puig"), **kw)


def test_las_etapas_se_crean_la_primera_vez_con_una_ganada_y_una_perdida(d):
    etapas = co.listar_etapas(d.t)
    assert [e["clave"] for e in etapas] == ["nuevo", "contactado", "reunion", "propuesta", "negociacion", "ganada", "perdida"]
    assert [e["tipo"] for e in etapas].count("ganada") == 1 and [e["tipo"] for e in etapas].count("perdida") == 1
    assert co.listar_etapas(d.t) == etapas                                                           # idempotente


def test_crear_y_validar_una_oportunidad(d):
    oid = _op(d, importe="1.200,50", cierre_previsto="2026-12-31", origen="Recomendación")
    o = co.obtener_oportunidad(d.t, d.ana, oid)
    assert (o["etapa"], o["estado"], o["importe_centimos"], o["probabilidad"], o["responsable_id"]) == ("nuevo", "abierta", 120050, 10, d.ana)
    for malo, texto in (({"titulo": " "}, "de qué"), ({"importe": "mucho"}, "importe"), ({"cierre_previsto": "ayer"}, "AAAA-MM-DD"), ({"contacto_nombre": None, "empresa": None}, "prospecto"),
                        ({"etapa": "ganada"}, "etapa"), ({"responsable_id": 999999}, "despacho")):
        with pytest.raises(ErrorComercial, match=texto):
            co.crear_oportunidad(d.t, d.ana, **{"titulo": "X", "contacto_nombre": "Y", **malo})


def test_mover_de_etapa_probabilidad_cierre_motivo_y_cronologia(d):
    oid = _op(d, importe="1000")
    o = co.mover_oportunidad(d.t, d.ana, oid, "propuesta")
    assert (o["etapa"], o["probabilidad"], o["estado"]) == ("propuesta", 60, "abierta") and ((o["importe_centimos"] * o["probabilidad"]) // 100) == 60000
    with pytest.raises(ErrorComercial, match="por qué"):
        co.mover_oportunidad(d.t, d.ana, oid, "perdida")
    o = co.mover_oportunidad(d.t, d.ana, oid, "perdida", "Se fue con otra gestoría")
    assert (o["estado"], o["probabilidad"], o["motivo_perdida"]) == ("perdida", 0, "Se fue con otra gestoría") and o["cerrada_en"]
    o = co.mover_oportunidad(d.t, d.ana, oid, "negociacion")                                         # se puede reabrir
    assert (o["estado"], o["cerrada_en"], o["motivo_perdida"]) == ("abierta", None, None)
    textos = [a["asunto"] for a in co.cronologia(d.t, d.ana, oportunidad_id=oid)]
    assert any("Propuesta enviada → Perdida" in t for t in textos) and any("Perdida → Negociación" in t for t in textos)
    with pytest.raises(ErrorComercial, match="no existe"):
        co.mover_oportunidad(d.t, d.ana, oid, "inventada")


def test_las_etapas_se_editan_solo_por_la_direccion(d):
    co.listar_etapas(d.t)
    with pytest.raises(ErrorComercial, match="dirección"):
        co.renombrar_etapa(d.t, d.ana, "nuevo", "Prospecto")
    co.renombrar_etapa(d.t, d.sup, "nuevo", "Prospecto", 15)
    oid = _op(d)
    assert co.obtener_oportunidad(d.t, d.ana, oid)["probabilidad"] == 15 and co.obtener_oportunidad(d.t, d.ana, oid)["etapa_nombre"] == "Prospecto"
    clave = co.crear_etapa(d.t, d.sup, "Demo", 50)
    co.mover_etapa(d.t, d.sup, clave, -1)
    abiertas = [e["clave"] for e in co.listar_etapas(d.t) if e["tipo"] == "abierta"]
    assert abiertas.index(clave) == abiertas.index("negociacion") - 1 or abiertas.index(clave) < len(abiertas) - 1
    for malo, texto in ((lambda: co.renombrar_etapa(d.t, d.sup, "contactado", "prospecto"), "otra etapa"), (lambda: co.renombrar_etapa(d.t, d.sup, "nuevo", "X", 150), "entre 0 y 100"),
                        (lambda: co.borrar_etapa(d.t, d.sup, "ganada"), "ganada"), (lambda: co.borrar_etapa(d.t, d.sup, "nuevo"), "oportunidades")):
        with pytest.raises(ErrorComercial, match=texto):
            malo()
    co.borrar_etapa(d.t, d.sup, clave)
    assert clave not in [e["clave"] for e in co.listar_etapas(d.t)]


def test_actividad_con_proxima_accion_crea_una_tarea_para_quien_lleva_la_oportunidad(d):
    oid = co.crear_oportunidad(d.t, d.ana, "Renta", contacto_nombre="Luis", responsable_id=d.beto)
    aid = co.registrar_actividad(d.t, d.ana, tipo="llamada", asunto="Primera llamada", oportunidad_id=oid, texto="Le interesa", proxima_accion="Mandar propuesta", proxima_fecha="2026-11-05")
    a = [x for x in co.cronologia(d.t, d.ana, oportunidad_id=oid) if x["id"] == aid][0]
    assert a["tipo_texto"] == "Llamada" and a["tarea_id"]
    tarea = db.obtener_tarea_outlook_visible(d.beto, a["tarea_id"])
    assert tarea["asunto"] == "Mandar propuesta" and tarea["fecha_vencimiento"][:10] == "2026-11-05" and tarea["asignada_a"] == d.beto
    with pytest.raises(ErrorComercial, match="cuándo"):
        co.registrar_actividad(d.t, d.ana, tipo="nota", asunto="x", oportunidad_id=oid, proxima_accion="Algo")
    with pytest.raises(ErrorComercial, match="tipo"):
        co.registrar_actividad(d.t, d.ana, tipo="etapa", asunto="x", oportunidad_id=oid)


def test_convertir_en_cliente_crea_la_ficha_la_enlaza_y_da_por_ganada(d):
    oid = _op(d, titulo="Sociedad nueva", contacto_nombre="Marta Puig", contacto_email="marta@ejemplo.com", contacto_telefono="600111222", empresa="Panadería Sol SL")
    co.registrar_actividad(d.t, d.ana, tipo="reunion", asunto="Reunión inicial", oportunidad_id=oid)
    res = co.convertir_en_cliente(d.t, d.ana, oid, nif="B12345674")
    o = co.obtener_oportunidad(d.t, d.ana, oid)
    assert o["cliente_id"] == res["cliente_id"] and o["estado"] == "ganada" and o["cliente_nombre"] == "Panadería Sol SL" and res["cliente_fiscal_id"] is None
    assert [a["asunto"] for a in co.cronologia(d.t, d.ana, cliente_id=res["cliente_id"]) if a["tipo"] == "reunion"] == ["Reunión inicial"]      # la cronología pasa al cliente
    with pytest.raises(ErrorComercial, match="ya es de un cliente"):
        co.convertir_en_cliente(d.t, d.ana, oid)
    otro = _op(d, titulo="Otra")
    fiscal = co.convertir_en_cliente(d.t, d.ana, otro, gestion_fiscal=True, ganar=False)
    assert fiscal["cliente_fiscal_id"] and co.obtener_oportunidad(d.t, d.ana, otro)["estado"] == "abierta"


def test_solo_el_auditor_no_escribe_y_los_despachos_no_se_ven(d):
    oid = _op(d)
    assert co.obtener_oportunidad(d.t, d.aud, oid) is not None                                       # puede mirar
    for f in (lambda: co.crear_oportunidad(d.t, d.aud, "X", contacto_nombre="Y"), lambda: co.mover_oportunidad(d.t, d.aud, oid, "contactado"),
              lambda: co.registrar_actividad(d.t, d.aud, tipo="nota", asunto="x", oportunidad_id=oid)):
        with pytest.raises(ErrorComercial, match="solo permite consultar"):
            f()
    otro = db.crear_tenant("Otro despacho comercial")
    ajeno = db.crear_usuario_vinculado_a_kratos("ajeno-co@ejemplo.com", "k-ajeno-co"); db.asignar_tenant(ajeno, otro)
    assert co.obtener_oportunidad(otro, ajeno, oid) is None and co.listar_oportunidades(otro, ajeno) == []


def test_una_oportunidad_de_un_cliente_solo_la_ven_quienes_ven_a_ese_cliente(d):
    girona, bcn = acceso.crear_oficina(d.t, d.sup, "Girona"), acceso.crear_oficina(d.t, d.sup, "Barcelona")
    ca, cb = db.crear_cliente_fiscal(d.t, "Cliente A", nif="B12345674"), db.crear_cliente_fiscal(d.t, "Cliente B", nif="J21938519")
    acceso.asignar_cliente_a_oficina(d.t, d.sup, ca, girona); acceso.asignar_cliente_a_oficina(d.t, d.sup, cb, bcn)
    acceso.dar_membresia(d.t, d.sup, d.ana, "gestor", "oficina", girona); acceso.dar_membresia(d.t, d.sup, d.beto, "gestor", "oficina", bcn)
    nucleo_a = db.get_connection().execute("SELECT cliente_id FROM clientes_fiscales WHERE id = ?", (ca,)).fetchone()[0]
    nucleo_b = db.get_connection().execute("SELECT cliente_id FROM clientes_fiscales WHERE id = ?", (cb,)).fetchone()[0]
    oa = co.crear_oportunidad(d.t, d.sup, "Ampliar A", cliente_id=nucleo_a)
    ob = co.crear_oportunidad(d.t, d.sup, "Ampliar B", cliente_id=nucleo_b)
    libre = co.crear_oportunidad(d.t, d.sup, "Prospecto", contacto_nombre="Sin cliente")
    assert {o["id"] for o in co.listar_oportunidades(d.t, d.ana)} == {oa, libre} and {o["id"] for o in co.listar_oportunidades(d.t, d.beto)} == {ob, libre}
    assert co.obtener_oportunidad(d.t, d.ana, ob) is None
    with pytest.raises(ErrorComercial, match="no existe o no lo puedes ver"):
        co.crear_oportunidad(d.t, d.ana, "Colada", cliente_id=nucleo_b)


def test_embudo_importes_ponderados_tasa_de_exito_y_sin_datos_no_inventa(d):
    vacio = co.embudo(d.t, d.ana)
    assert vacio["tasa_exito"] is None and vacio["ciclo_medio_dias"] is None and vacio["abiertas"]["n"] == 0
    a, b, c, e = _op(d, importe="1000"), _op(d, importe="2000"), _op(d, importe="500"), _op(d, importe="300")
    co.mover_oportunidad(d.t, d.ana, b, "propuesta")                                                 # 60 %
    co.mover_oportunidad(d.t, d.ana, c, "ganada")
    co.mover_oportunidad(d.t, d.ana, e, "perdida", "Precio")
    r = co.embudo(d.t, d.ana)
    por = {x["clave"]: x for x in r["etapas"]}
    assert por["nuevo"]["n"] == 1 and por["propuesta"]["n"] == 1 and por["propuesta"]["ponderado"] == 1200.0 and por["nuevo"]["ponderado"] == 100.0
    assert r["abiertas"]["n"] == 2 and r["abiertas"]["importe"] == 3000.0 and r["abiertas"]["ponderado"] == 1300.0
    assert (r["ganadas"]["n"], r["perdidas"]["n"], r["tasa_exito"]) == (1, 1, 50.0) and r["motivos_perdida"] == [{"motivo": "precio", "n": 1}] and r["ciclo_medio_dias"] == 0.0
    assert a and r["por_responsable"][0]["ganadas"] == 1
    with pytest.raises(ErrorComercial, match="posterior"):
        co.embudo(d.t, d.ana, "2026-12-31", "2026-01-01")


def test_estancadas(d):
    oid = _op(d)
    conn = db.get_connection()
    try:
        conn.execute("UPDATE crm_oportunidades SET ultima_actividad_en = ? WHERE id = ?", ((date.today() - timedelta(days=30)).isoformat() + "T10:00:00", oid))
        conn.commit()
    finally:
        conn.close()
    assert [o["id"] for o in co.estancadas(d.t, d.ana)] == [oid]
    co.registrar_actividad(d.t, d.ana, tipo="llamada", asunto="Reactivada", oportunidad_id=oid)
    assert co.estancadas(d.t, d.ana) == []


def test_la_papelera_y_el_borrado_del_despacho_no_se_atascan(d):
    oid = _op(d)
    co.registrar_actividad(d.t, d.ana, tipo="nota", asunto="x", oportunidad_id=oid)
    co.papelera_oportunidad(d.t, d.ana, oid)
    assert co.obtener_oportunidad(d.t, d.ana, oid) is None and co.listar_oportunidades(d.t, d.ana) == []
    db.borrar_tenant(d.t)
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM crm_oportunidades WHERE tenant_id = ?", (d.t,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_si_se_borra_el_cliente_la_oportunidad_conserva_sus_datos(d):
    oid = _op(d, empresa="Panadería Sol SL")
    res = co.convertir_en_cliente(d.t, d.ana, oid)
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM clientes WHERE id = ?", (res["cliente_id"],))
        conn.commit()
    finally:
        conn.close()
    o = co.obtener_oportunidad(d.t, d.ana, oid)
    assert o is not None and o["cliente_id"] is None and o["empresa"] == "Panadería Sol SL"


# --- Pantallas -----------------------------------------------------------------------------------------------------------------

def test_el_modulo_no_existe_si_el_despacho_no_lo_tiene(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "sin-modulo-co@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, db.crear_tenant("Despacho sin comercial"))
    assert cliente.get("/comercial/").status_code == 404 and cliente.get("/comercial/reuniones").status_code == 404


def test_pantallas_del_embudo_de_principio_a_fin(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "pantallas-co@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho pantallas comercial")
    db.asignar_tenant(uid, t)
    db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "comercial", True)
    assert "Todavía no hay oportunidades" in cliente.get("/comercial/").get_data(as_text=True)
    r = cliente.post("/comercial/nueva", data={"titulo": "Llevanza de Panadería Sol", "empresa": "Panadería Sol SL", "importe": "2.400,00", "etapa": "contactado"})
    assert r.status_code == 302
    oid = co.listar_oportunidades(t, uid)[0]["id"]
    html = cliente.get("/comercial/").get_data(as_text=True)
    assert "Llevanza de Panadería Sol" in html and "Contactado" in html and "2.400" in html
    assert "Llevanza de Panadería Sol" in cliente.get("/comercial/?vista=lista").get_data(as_text=True)
    assert cliente.post("/comercial/nueva", data={"titulo": " "}).status_code == 422
    ficha = cliente.get(f"/comercial/{oid}").get_data(as_text=True)
    assert "Anotar una actividad" in ficha and "Convertir en cliente" in ficha
    assert cliente.post(f"/comercial/{oid}/actividad", data={"tipo": "llamada", "asunto": "Llamada de presentación", "proxima_accion": "Enviar propuesta", "proxima_fecha": "2026-11-10"}).status_code == 302
    assert "Llamada de presentación" in cliente.get(f"/comercial/{oid}").get_data(as_text=True)
    r = cliente.post(f"/comercial/{oid}/etapa", data={"etapa": "perdida"})
    assert r.status_code == 302 and "error=" in r.headers["Location"]                                  # sin motivo no se pierde
    cliente.post(f"/comercial/{oid}/etapa", data={"etapa": "propuesta", "volver_a": "/comercial/"})
    assert co.obtener_oportunidad(t, uid, oid)["etapa"] == "propuesta"
    assert cliente.post(f"/comercial/{oid}/convertir", data={"nif": "B12345674"}).status_code == 302
    assert co.obtener_oportunidad(t, uid, oid)["estado"] == "ganada"
    assert "Panadería Sol SL" in cliente.get(f"/comercial/{oid}").get_data(as_text=True)
    assert "Embudo abierto" in cliente.get("/comercial/informes").get_data(as_text=True)
    assert "Etapas del embudo" in cliente.get("/comercial/etapas").get_data(as_text=True)
    assert cliente.post("/comercial/etapas", data={"accion": "crear", "nombre": "Demo", "probabilidad": "55"}).status_code == 302
    assert "Demo" in cliente.get("/comercial/etapas").get_data(as_text=True)
    assert cliente.post(f"/comercial/{oid}/papelera").status_code == 302 and cliente.get(f"/comercial/{oid}").status_code == 404
    assert "Comercial" in cliente.get("/").get_data(as_text=True)                                       # entrada en el menú lateral


def test_la_ficha_del_cliente_enseña_su_panel_comercial_solo_con_el_modulo(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "ficha-co@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho ficha comercial")
    db.asignar_tenant(uid, t)
    from app import nucleo
    cid = nucleo.crear_cliente(t, "Cliente con oportunidad")
    assert "Últimas reuniones" not in cliente.get(f"/clientes/{cid}").get_data(as_text=True) and "Sin oportunidades" not in cliente.get(f"/clientes/{cid}").get_data(as_text=True)
    verticales.fijar_activo(t, "comercial", True)
    co.crear_oportunidad(t, uid, "Ampliación de servicios", cliente_id=cid, importe="900")
    html = cliente.get(f"/clientes/{cid}").get_data(as_text=True)
    assert "Ampliación de servicios" in html and "+ Oportunidad" in html


# --- Automatizaciones: «Una oportunidad cambia de etapa» ----------------------------------------------------------------------

def test_la_regla_de_oportunidad_avisa_solo_a_quien_puede_verla(d):
    from datetime import datetime, timezone
    from app import automatizaciones as au
    girona = acceso.crear_oficina(d.t, d.sup, "Girona"); bcn = acceso.crear_oficina(d.t, d.sup, "Barcelona")
    ca = db.crear_cliente_fiscal(d.t, "Cliente A", nif="B12345674")
    acceso.asignar_cliente_a_oficina(d.t, d.sup, ca, girona)
    acceso.dar_membresia(d.t, d.sup, d.ana, "gestor", "oficina", girona); acceso.dar_membresia(d.t, d.sup, d.beto, "gestor", "oficina", bcn)
    nucleo_a = db.get_connection().execute("SELECT cliente_id FROM clientes_fiscales WHERE id = ?", (ca,)).fetchone()[0]
    au.crear_regla(d.t, d.sup, "Ganadas", "oportunidad.etapa", {"etapa": "ganada"}, [
        {"tipo": "notificar", "titulo": "Ganada: {oportunidad} ({etapa}, antes {anterior})", "cuerpo": "{contacto} · {importe} · {responsable}", "a": d.beto},
        {"tipo": "notificar", "titulo": "Ganada (dirección): {oportunidad}", "a": "direccion"},
        {"tipo": "crear_tarea", "asunto": "Dar la bienvenida a {contacto}", "asignar_a": d.ana, "dias_plazo": 2}])
    oid = co.crear_oportunidad(d.t, d.sup, "Ampliar A", cliente_id=nucleo_a, importe="1500")
    co.mover_oportunidad(d.t, d.sup, oid, "ganada")
    r = au.procesar_eventos(datetime.now(timezone.utc))
    assert r["eventos"] == 1 and r["ejecuciones"] == 1 and r["errores"] == 0
    conn = db.get_connection()
    try:
        avisos = lambda u: [dict(f)["titulo"] for f in conn.execute("SELECT titulo FROM notificaciones WHERE usuario_id = ? AND tipo = 'automatizacion'", (u,))]    # noqa: E731
        assert avisos(d.beto) == []                                                                # Beto es de Barcelona: no ve esa oportunidad, ni su título le llega
        assert avisos(d.sup) == ["Ganada (dirección): Ampliar A"]
    finally:
        conn.close()
    tareas = [t for t in db.listar_tareas_outlook(d.ana, incluir_asignadas=True) if t["asunto"].startswith("Dar la bienvenida")]
    assert [t["asunto"] for t in tareas] == ["Dar la bienvenida a Cliente A"]


def test_validacion_de_la_regla_de_oportunidad(d):
    from app import automatizaciones as au
    co.listar_etapas(d.t)
    assert au.validar_condiciones("oportunidad.etapa", {"etapa": "propuesta"}) == {"etapa": "propuesta"}
    for malo in ({}, {"etapa": ""}, {"etapa": "Con Espacios"}):
        with pytest.raises(ValueError):
            au.validar_condiciones("oportunidad.etapa", malo)
    nota = [{"tipo": "notificar", "titulo": "{oportunidad} → {etapa}", "a": "direccion"}]
    with pytest.raises(ValueError, match="no existe en tu embudo"):
        au.crear_regla(d.t, d.sup, "x", "oportunidad.etapa", {"etapa": "inventada"}, nota)
    for accion in ({"tipo": "comentar", "texto": "x"}, {"tipo": "asignar", "a": d.ana}):
        with pytest.raises(ValueError, match="solo vale cuando el disparador es una tarea"):
            au.validar_acciones("oportunidad.etapa", [accion])
    with pytest.raises(ValueError, match="no existe"):
        au.validar_acciones("oportunidad.etapa", [{"tipo": "notificar", "titulo": "{asunto}"}])
    sin_modulo = db.crear_tenant("Despacho sin comercial 2")
    jefe = db.crear_usuario_vinculado_a_kratos("jefe-sc@ejemplo.com", "k-jefe-sc"); db.asignar_tenant(jefe, sin_modulo); db.asignar_supervisor_tenant(jefe, True)
    with pytest.raises(ValueError, match="módulo Comercial"):
        au.crear_regla(sin_modulo, jefe, "x", "oportunidad.etapa", {"etapa": "ganada"}, nota)
    assert au.crear_regla(d.t, d.sup, "ok", "oportunidad.etapa", {"etapa": "propuesta"}, nota)


def test_pantalla_y_plantilla_de_la_regla_de_oportunidad(cliente):
    from app import automatizaciones as au
    uid = iniciar_sesion_de_prueba(cliente, "regla-co@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho regla comercial")
    db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    assert 'value="oportunidad.etapa"' not in cliente.get("/tareas/automatizaciones/regla").get_data(as_text=True)         # sin el módulo no se ofrece
    verticales.fijar_activo(t, "comercial", True)
    html = cliente.get("/tareas/automatizaciones/regla").get_data(as_text=True)
    assert 'value="oportunidad.etapa"' in html and 'name="c_etapa_o"' in html and 'value="negociacion"' in html
    r = cliente.post("/tareas/automatizaciones/regla", data={"nombre": "Propuestas", "disparador": "oportunidad.etapa", "c_etapa_o": "propuesta", "activa": "1",
                                                           "a0_tipo": "notificar", "a0_titulo": "Propuesta: {oportunidad}", "a0_dest_aviso": "direccion"})
    assert r.status_code == 302 and au.listar_reglas(t)[0]["condiciones"] == {"etapa": "propuesta"}
    assert cliente.post("/tareas/automatizaciones/nueva", data={"plantilla": "oportunidad_ganada"}).status_code == 302
    assert "Avisar cuando se gane una oportunidad" in cliente.get("/tareas/automatizaciones").get_data(as_text=True)


# --- Herramientas MCP / asistente de IA --------------------------------------------------------------------------------------------

def test_herramientas_del_asistente_para_el_embudo_y_las_reuniones(d, monkeypatch):
    import json
    import mcp_tools  # noqa: F401
    from app import herramientas_grupos as hg, ia_asistente, ia_herramientas as ih, reuniones as ru
    for n in ("comercial_listar_oportunidades", "comercial_ver_oportunidad", "comercial_embudo", "comercial_ver_reunion"):
        assert n in ih.LECTURA and not ih.necesita_confirmacion(n, modo_autonomo=False) and hg.grupo_de(n) == "comercial"
    for n in ("comercial_crear_oportunidad", "comercial_mover_oportunidad", "comercial_anotar_actividad", "comercial_crear_reunion", "comercial_generar_acta"):
        assert n in ih.ESCRITURA and ih.necesita_confirmacion(n, modo_autonomo=False) and hg.grupo_de(n) == "comercial"
    o = ih.ejecutar(d.ana, "comercial_crear_oportunidad", {"titulo": "Renta 2025", "contacto_nombre": "Luis Pérez", "importe": "300"})
    assert o["etapa"] == "nuevo" and o["importe"] == 300.0
    assert [x["id"] for x in ih.ejecutar(d.ana, "comercial_listar_oportunidades", {"texto": "renta"})] == [o["id"]]
    assert ih.ejecutar(d.ana, "comercial_mover_oportunidad", {"oportunidad_id": o["id"], "etapa": "propuesta"})["probabilidad"] == 60
    with pytest.raises(ih.ErrorHerramientaIA, match="por qué"):
        ih.ejecutar(d.ana, "comercial_mover_oportunidad", {"oportunidad_id": o["id"], "etapa": "perdida"})
    ih.ejecutar(d.ana, "comercial_anotar_actividad", {"oportunidad_id": o["id"], "tipo": "llamada", "asunto": "Llamada", "proxima_accion": "Mandar presupuesto", "proxima_fecha": "2026-11-20"})
    ver = ih.ejecutar(d.ana, "comercial_ver_oportunidad", {"oportunidad_id": o["id"]})
    assert {a["asunto"] for a in ver["cronologia"]} >= {"Llamada"}
    assert ih.ejecutar(d.ana, "comercial_embudo", {})["abiertas"]["n"] == 1
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda u, s, c: json.dumps({"resumen": "Todo claro.", "tareas": [], "decisiones": ["Seguir"]}))
    monkeypatch.setattr(ru, "configurada", lambda u: True)
    rid = ih.ejecutar(d.ana, "comercial_crear_reunion", {"titulo": "Llamada", "notas": "Quiere presupuesto", "oportunidad_id": o["id"], "plantilla": "comercial"})["reunion_id"]
    assert ih.ejecutar(d.ana, "comercial_generar_acta", {"reunion_id": rid})["acta"]["resumen"] == "Todo claro."
    ver = ih.ejecutar(d.ana, "comercial_ver_reunion", {"reunion_id": rid})
    assert ver["acta"]["decisiones"] == ["Seguir"] and ver["tiene_transcripcion"] is False and "transcripcion" not in ver
    with pytest.raises(ih.ErrorHerramientaIA, match="no puedes verla"):
        ih.ejecutar(d.beto, "comercial_ver_oportunidad", {"oportunidad_id": 999999})


def test_las_herramientas_exigen_el_modulo_y_respetan_al_auditor(d):
    import mcp_tools  # noqa: F401
    from app import ia_herramientas as ih
    sin = db.crear_tenant("Despacho sin comercial 3")
    uno = db.crear_usuario_vinculado_a_kratos("uno-sc@ejemplo.com", "k-uno-sc"); db.asignar_tenant(uno, sin)
    with pytest.raises(ih.ErrorHerramientaIA, match="no tiene el módulo Comercial"):
        ih.ejecutar(uno, "comercial_listar_oportunidades", {})
    with pytest.raises(ih.ErrorHerramientaIA, match="solo permite consultar"):
        ih.ejecutar(d.aud, "comercial_crear_oportunidad", {"titulo": "X", "contacto_nombre": "Y"})
    assert ih.ejecutar(d.aud, "comercial_listar_oportunidades", {}) == []


NUEVAS_HERRAMIENTAS = {
    "lectura": ("comercial_listar_etapas", "comercial_listar_reuniones"),
    "escritura": ("comercial_editar_oportunidad", "comercial_convertir_en_cliente", "comercial_eliminar_oportunidad", "comercial_editar_reunion", "comercial_borrar_transcripcion",
                  "comercial_guardar_acta", "comercial_crear_tareas_de_acta", "comercial_eliminar_reunion"),
}


def test_las_herramientas_nuevas_estan_en_el_mcp_el_asistente_y_su_grupo():
    import mcp_tools
    from app import herramientas_grupos as hg, ia_herramientas as ih
    todas = [n for lote in NUEVAS_HERRAMIENTAS.values() for n in lote] + ["comercial_guardar_transcripcion"]
    en_mcp = {t.__name__ for t in mcp_tools.TOOLS}
    definidas = {t["function"]["name"] for t in ih.HERRAMIENTAS}
    for n in todas:
        assert n in en_mcp and n in definidas and hg.grupo_de(n) == "comercial", n
    for n in NUEVAS_HERRAMIENTAS["lectura"]:
        assert n in ih.LECTURA and not ih.necesita_confirmacion(n, modo_autonomo=False)
    for n in NUEVAS_HERRAMIENTAS["escritura"]:
        assert n in ih.ESCRITURA and ih.necesita_confirmacion(n, modo_autonomo=False)
    assert "comercial_guardar_transcripcion" in ih.SIEMPRE_CONFIRMAR and ih.necesita_confirmacion("comercial_guardar_transcripcion", modo_autonomo=True), "el aviso de grabación lo confirma siempre la persona"


def test_herramientas_de_gestion_de_oportunidades_y_reuniones(d, monkeypatch):
    import json
    import mcp_tools  # noqa: F401
    from app import ia_asistente, ia_herramientas as ih, reuniones as ru
    etapas = ih.ejecutar(d.ana, "comercial_listar_etapas", {})
    assert [e["clave"] for e in etapas][:2] == ["nuevo", "contactado"] and {"clave", "nombre", "probabilidad", "tipo"} == set(etapas[0])
    o = ih.ejecutar(d.ana, "comercial_crear_oportunidad", {"titulo": "Autónomo", "contacto_nombre": "Rosa", "empresa": "Floristería Rosa"})
    e = ih.ejecutar(d.ana, "comercial_editar_oportunidad", {"oportunidad_id": o["id"], "importe": "450", "email": "rosa@ejemplo.com", "cierre_previsto": "2026-12-01"})
    assert e["importe"] == 450.0 and e["contacto_email"] == "rosa@ejemplo.com" and e["titulo"] == "Autónomo" and e["cierre_previsto"] == "2026-12-01"
    with pytest.raises(ih.ErrorHerramientaIA, match="AAAA-MM-DD"):
        ih.ejecutar(d.ana, "comercial_editar_oportunidad", {"oportunidad_id": o["id"], "cierre_previsto": "ayer"})
    with pytest.raises(ih.ErrorHerramientaIA, match="no puedes verla"):
        ih.ejecutar(d.ana, "comercial_editar_oportunidad", {"oportunidad_id": 999999, "titulo": "x"})
    c = ih.ejecutar(d.ana, "comercial_convertir_en_cliente", {"oportunidad_id": o["id"], "nif": "B12345678"})
    assert c["cliente_id"] and co.obtener_oportunidad(d.t, d.ana, o["id"])["estado"] == "ganada"
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(d.ana, "comercial_convertir_en_cliente", {"oportunidad_id": o["id"]})
    assert ih.ejecutar(d.ana, "comercial_eliminar_oportunidad", {"oportunidad_id": o["id"]})["en_papelera"] is True
    assert ih.ejecutar(d.ana, "comercial_listar_oportunidades", {"estado": "todas"}) == []
    # reuniones
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda u, s, c: json.dumps({"resumen": "Hecho.", "decisiones": [], "proximos_pasos": [],
                                                                                    "tareas": [{"texto": "Enviar presupuesto", "responsable": "", "fecha": ""}, {"texto": "Llamar", "responsable": "", "fecha": ""}]}))
    monkeypatch.setattr(ru, "configurada", lambda u: True)
    rid = ih.ejecutar(d.ana, "comercial_crear_reunion", {"titulo": "Seguimiento", "notas": "n", "plantilla": "comercial"})["reunion_id"]
    otra = ih.ejecutar(d.ana, "comercial_crear_reunion", {"titulo": "Otra", "cliente_id": c["cliente_id"]})["reunion_id"]
    lista = ih.ejecutar(d.ana, "comercial_listar_reuniones", {})
    assert {r["id"] for r in lista} == {rid, otra} and all("notas" not in r and "transcripcion" not in r for r in lista)
    assert [r["id"] for r in ih.ejecutar(d.ana, "comercial_listar_reuniones", {"cliente_id": c["cliente_id"]})] == [otra]
    assert ih.ejecutar(d.ana, "comercial_editar_reunion", {"reunion_id": rid, "titulo": "Seguimiento 2", "participantes": "Rosa"})["titulo"] == "Seguimiento 2"
    with pytest.raises(ih.ErrorHerramientaIA, match="plantilla"):
        ih.ejecutar(d.ana, "comercial_editar_reunion", {"reunion_id": rid, "plantilla": "rara"})
    with pytest.raises(ih.ErrorHerramientaIA, match="avisó|Confirma"):
        ih.ejecutar(d.ana, "comercial_guardar_transcripcion", {"reunion_id": rid, "texto": "SECRETO", "aviso_grabacion": False})
    assert ih.ejecutar(d.ana, "comercial_guardar_transcripcion", {"reunion_id": rid, "texto": "SECRETO", "aviso_grabacion": True}) == {"reunion_id": rid, "tiene_transcripcion": True}
    assert "SECRETO" not in json.dumps(ih.ejecutar(d.ana, "comercial_ver_reunion", {"reunion_id": rid}))
    with pytest.raises(ih.ErrorHerramientaIA, match="todavía no tiene acta"):
        ih.ejecutar(d.ana, "comercial_crear_tareas_de_acta", {"reunion_id": rid, "indices": [0]})
    ih.ejecutar(d.ana, "comercial_generar_acta", {"reunion_id": rid})
    assert ih.ejecutar(d.ana, "comercial_borrar_transcripcion", {"reunion_id": rid})["tiene_transcripcion"] is False
    with pytest.raises(ih.ErrorHerramientaIA, match="Indica qué tareas"):
        ih.ejecutar(d.ana, "comercial_crear_tareas_de_acta", {"reunion_id": rid, "indices": []})
    with pytest.raises(ih.ErrorHerramientaIA, match="no existe"):
        ih.ejecutar(d.ana, "comercial_crear_tareas_de_acta", {"reunion_id": rid, "indices": [7]})
    with pytest.raises(ih.ErrorHerramientaIA, match="no es de tu despacho"):
        ih.ejecutar(d.ana, "comercial_crear_tareas_de_acta", {"reunion_id": rid, "indices": [0], "responsable_id": 999999})
    r1 = ih.ejecutar(d.ana, "comercial_crear_tareas_de_acta", {"reunion_id": rid, "indices": [0], "responsable_id": d.beto, "fecha": "2026-11-30"})
    assert len(r1["tarea_ids"]) == 1
    assert ih.ejecutar(d.ana, "comercial_crear_tareas_de_acta", {"reunion_id": rid, "indices": [0, 1]})["tarea_ids"].__len__() == 1, "la ya creada no se duplica"
    g = ih.ejecutar(d.ana, "comercial_guardar_acta", {"reunion_id": rid, "resumen": "Corregido", "decisiones": ["Una"], "tareas": [{"texto": "Enviar presupuesto"}]})
    assert g["acta"]["resumen"] == "Corregido" and g["acta"]["tareas"][0]["tarea_id"] == r1["tarea_ids"][0], "conserva el enlace de la tarea ya creada"
    assert ih.ejecutar(d.ana, "comercial_eliminar_reunion", {"reunion_id": rid})["en_papelera"] is True
    with pytest.raises(ih.ErrorHerramientaIA, match="no puedes verla"):
        ih.ejecutar(d.ana, "comercial_ver_reunion", {"reunion_id": rid})


def test_el_auditor_no_escribe_con_las_herramientas_nuevas(d):
    import mcp_tools  # noqa: F401
    from app import ia_herramientas as ih, reuniones as ru
    o = _op(d)
    rid = ru.crear(d.t, d.ana, "Reunión", plantilla="comercial", oportunidad_id=o)
    assert [e["clave"] for e in ih.ejecutar(d.aud, "comercial_listar_etapas", {})][0] == "nuevo"
    for nombre, args in (("comercial_editar_oportunidad", {"oportunidad_id": o, "titulo": "x"}), ("comercial_convertir_en_cliente", {"oportunidad_id": o}), ("comercial_eliminar_oportunidad", {"oportunidad_id": o}),
                         ("comercial_editar_reunion", {"reunion_id": rid, "titulo": "x"}), ("comercial_guardar_transcripcion", {"reunion_id": rid, "texto": "x", "aviso_grabacion": True}),
                         ("comercial_guardar_acta", {"reunion_id": rid, "resumen": "x"}), ("comercial_eliminar_reunion", {"reunion_id": rid})):
        with pytest.raises(ih.ErrorHerramientaIA, match="solo permite consultar"):
            ih.ejecutar(d.aud, nombre, args)
