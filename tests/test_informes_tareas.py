"""Informes de tareas (app/informes_tareas.py): cifras con denominadores explícitos, alcance (solo lo visible), ventana, CSV y PDF."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app import certificados as ce, db, informes_tareas as it, tareas_trabajo as tt
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_api_tareas import _tarea, _usuario

HOY = date(2026, 10, 20)
DESDE, HASTA = date(2026, 10, 1), date(2026, 10, 20)


def _t(id, estado="no_iniciada", creada="2026-09-01", vence=None, completada=None, resp=1, clientes=(), **kw):
    return {"id": id, "asunto": f"T{id}", "estado": estado, "prioridad": "normal", "fecha_vencimiento": vence, "creada_en": creada + "T09:00:00", "fecha_completada": completada and completada + "T10:00:00",
            "usuario_id": resp, "asignada_a": None, "cliente_fiscal_id": clientes[0] if clientes else None, "motivo_bloqueo": kw.get("motivo"), "actualizada_en": kw.get("act"), "clientes": list(clientes)}


def _caso():
    return [
        _t(1, "completada", creada="2026-09-30", vence="2026-10-10", completada="2026-10-05"),       # en plazo, cierre 5 días
        _t(2, "completada", creada="2026-10-02", vence="2026-10-10", completada="2026-10-12"),       # tarde, cierre 10
        _t(3, "completada", creada="2026-10-08", completada="2026-10-08"),                           # sin fecha límite, cierre 0
        _t(4, "completada", creada="2026-08-01", vence="2026-09-20", completada="2026-09-15"),       # fuera de la ventana
        _t(5, vence="2026-10-15"),                                                                   # vencida
        _t(6, vence="2026-10-25"),                                                                   # al día
        _t(7),                                                                                       # sin fecha
        _t(8, "esperando", motivo="Falta el certificado"),
    ]


def test_ventana_valida_y_por_defecto():
    assert it.ventana(None, None, HOY) == (date(2026, 9, 21), HOY)
    assert it.ventana("2026-01-01", "2026-12-31", HOY)[1] == date(2026, 12, 31)
    for malo in (("2026-10-20", "2026-10-01"), ("2025-01-01", "2026-10-20"), ("hoy", None), ("2026-13-01", None)):
        with pytest.raises(ValueError):
            it.ventana(*malo, HOY)


def test_cifras_con_denominadores_explicitos():
    r = it.calcular(_caso(), DESDE, HASTA, HOY, {8: "2026-10-10T08:00:00"})
    assert r["creadas"] == 2                                                                         # solo las creadas dentro de la ventana (2 y 3)
    assert r["ahora"] == {"abiertas": 4, "vencidas": 1, "bloqueadas": 1}
    h = r["en_ventana"]
    assert (h["completadas"], h["con_fecha"], h["en_plazo"], h["tasa_en_plazo"]) == (3, 2, 1, 50.0)   # la tarea sin fecha no entra en el denominador
    assert (h["tiempo_medio_cierre_dias"], h["tiempo_medio_n"]) == (5.0, 3)
    assert r["bloqueadas"] == [{"id": 8, "asunto": "T8", "motivo": "Falta el certificado", "desde": "2026-10-10", "dias": 10}]


def test_sin_tareas_con_fecha_no_hay_tasa_inventada():
    r = it.calcular([_t(1, "completada", completada="2026-10-05")], DESDE, HASTA, HOY)
    assert r["en_ventana"]["tasa_en_plazo"] is None and r["en_ventana"]["con_fecha"] == 0
    vacio = it.calcular([], DESDE, HASTA, HOY)
    assert vacio["en_ventana"]["tiempo_medio_cierre_dias"] is None and vacio["ahora"] == {"abiertas": 0, "vencidas": 0, "bloqueadas": 0}


def test_una_tarea_de_dos_clientes_cuenta_en_cada_uno_pero_una_vez_en_el_total():
    r = it.calcular([_t(1, vence="2026-10-01", clientes=(10, 11)), _t(2)], DESDE, HASTA, HOY)
    assert r["ahora"]["abiertas"] == 2 and r["ahora"]["vencidas"] == 1
    assert r["por_cliente"][10]["vencidas"] == 1 and r["por_cliente"][11]["vencidas"] == 1 and r["por_cliente"][None]["abiertas"] == 1


def test_el_dia_de_vencimiento_no_es_tarde_y_los_limites_de_la_ventana_incluyen():
    t = [_t(1, "completada", creada="2026-10-01", vence="2026-10-20", completada="2026-10-20"), _t(2, "completada", creada="2026-10-01", vence="2026-10-01", completada="2026-10-01")]
    r = it.calcular(t, DESDE, HASTA, HOY)
    assert r["en_ventana"]["completadas"] == 2 and r["en_ventana"]["en_plazo"] == 2 and r["creadas"] == 2


# --- Con base de datos --------------------------------------------------------------------------------------------------------------

@pytest.fixture
def d(usuario_id):
    t = db.crear_tenant("Despacho Informes")
    class E: pass
    e = E(); e.t = t
    def u(mail, sup=False):
        x = db.crear_usuario_vinculado_a_kratos(mail, "k-" + mail); db.asignar_tenant(x, t)
        if sup:
            db.asignar_supervisor_tenant(x, True)
        return x
    e.sup, e.ana, e.beto = u("sup-in@ejemplo.com", True), u("ana-in@ejemplo.com"), u("beto-in@ejemplo.com")
    e.c1, e.c2 = db.crear_cliente_fiscal(t, "Alfa SL"), db.crear_cliente_fiscal(t, "Beta SL")
    return e


def _fijar(tid, **cols):
    conn = db.get_connection()
    try:
        conn.execute(f"UPDATE tareas_outlook SET {', '.join(k + ' = ?' for k in cols)} WHERE id = ?", (*cols.values(), tid))
        conn.commit()
    finally:
        conn.close()


def test_el_informe_solo_cuenta_lo_que_la_persona_ve_tambien_para_la_direccion(d):
    privada_beto = db.crear_tarea_outlook(d.beto, asunto="Privada de Beto", fecha_vencimiento="2026-10-01", cliente_fiscal_id=d.c1)
    de_ana = db.crear_tarea_outlook(d.ana, asunto="De Ana", fecha_vencimiento="2026-10-01", cliente_fiscal_id=d.c1)
    compartida = db.crear_tarea_outlook(d.beto, asunto="Compartida", cliente_fiscal_id=d.c2)
    assert db.compartir_tarea_outlook(d.beto, compartida, d.ana, "observa")
    r_ana = it.informe(d.t, d.ana, "2026-10-01", "2026-10-20", hoy=HOY)
    assert r_ana["ahora"]["abiertas"] == 2 and {b["nombre"] for b in r_ana["por_cliente"]} == {"Alfa SL", "Beta SL"}
    r_sup = it.informe(d.t, d.sup, "2026-10-01", "2026-10-20", hoy=HOY)
    assert r_sup["ahora"]["abiertas"] == 0 and r_sup["por_cliente"] == [] and privada_beto and de_ana     # la dirección tampoco ve las privadas de otros


def test_desglose_por_persona_y_cliente_y_bloqueo_con_antiguedad(d):
    a = db.crear_tarea_outlook(d.ana, asunto="Vencida de Ana", fecha_vencimiento="2026-10-01", cliente_fiscal_id=d.c1)
    b = db.crear_tarea_outlook(d.ana, asunto="Hecha a tiempo", fecha_vencimiento="2026-10-18", cliente_fiscal_id=d.c1)
    db.completar_tarea_outlook(d.ana, b)
    _fijar(b, creada_en="2026-10-10T09:00:00", fecha_completada="2026-10-15T09:00:00")
    c = db.crear_tarea_outlook(d.ana, asunto="Bloqueada", cliente_fiscal_id=d.c2)
    tt.transicionar(d.ana, c, "esperando", "Falta el modelo")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE tarea_actividad SET creado_en = '2026-10-12T09:00:00' WHERE tarea_id = ? AND tipo IN ('bloqueada', 'estado')", (c,))
        conn.commit()
    finally:
        conn.close()
    r = it.informe(d.t, d.ana, "2026-10-01", "2026-10-20", hoy=HOY)
    assert r["ahora"] == {"abiertas": 2, "vencidas": 1, "bloqueadas": 1}
    ana = r["por_responsable"][0]
    assert (ana["abiertas"], ana["vencidas"], ana["completadas"], ana["tasa_en_plazo"]) == (2, 1, 1, 100.0)
    por_cli = {f["nombre"]: f for f in r["por_cliente"]}
    assert por_cli["Alfa SL"]["vencidas"] == 1 and por_cli["Beta SL"]["abiertas"] == 1
    assert r["bloqueadas"][0]["motivo"] == "Falta el modelo" and r["bloqueadas"][0]["dias"] == 8 and a
    assert r["en_ventana"]["tiempo_medio_cierre_dias"] == 5.0


def test_proximas_incluye_tareas_vencimientos_y_certificados_solo_a_la_direccion(d):
    ce.fijar_custodio_flag(d.t, d.sup, d.ana, True)
    db.crear_tarea_outlook(d.ana, asunto="Pronto", fecha_vencimiento="2026-10-25")
    db.crear_tarea_outlook(d.ana, asunto="Lejos", fecha_vencimiento="2026-12-25")
    db.crear_vencimiento_fiscal(d.t, d.c1, "303", "2026-T3", "2026-10-27")
    db.crear_vencimiento_fiscal(d.t, d.c1, "303", "2026-T4", "2026-12-27")
    ce.alta_rapida(d.t, d.sup, tipo="otro", caduca="2026-10-30", titular="Ana Pérez", custodio_id=d.ana)
    ce.alta_rapida(d.t, d.sup, tipo="otro", caduca="2027-10-30", titular="Lejana SL", custodio_id=d.ana)
    ahora = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
    ant = ce._ahora
    ce._ahora = lambda: ahora
    try:
        p_ana = it.informe(d.t, d.ana, hoy=HOY, dias_proximos=14)["proximas"]
        p_sup = it.informe(d.t, d.sup, hoy=HOY, dias_proximos=14)["proximas"]
    finally:
        ce._ahora = ant
    assert [t["asunto"] for t in p_ana["tareas"]] == ["Pronto"] and [v["fecha_limite"] for v in p_ana["vencimientos_fiscales"]] == ["2026-10-27"]
    assert p_ana["certificados"] == []                                                              # no es dirección
    assert [c["titular"] for c in p_sup["certificados"]] == ["Ana Pérez"] and p_sup["tareas"] == []


# --- API y pantalla ---------------------------------------------------------------------------------------------------------------------

def test_api_del_informe(cliente):
    t = db.crear_tenant("Despacho API informe")
    h, uid = _usuario(cliente, "ai1@ejemplo.com", t)
    tid = _tarea(cliente, h, "Con fecha", fecha_vencimiento="2026-01-01")
    r = cliente.get("/api/v1/tareas-outlook/informe", headers=h)
    assert r.status_code == 200
    datos = r.get_json()["data"]
    assert datos["ahora"]["vencidas"] == 1 and datos["ventana"]["dias"] == 30 and datos["alcance"] == "tareas que la persona puede ver" and tid
    assert cliente.get("/api/v1/tareas-outlook/informe?desde=2026-02-01&hasta=2026-01-01", headers=h).get_json()["codigo"] == "ventana_invalida"
    assert cliente.get("/api/v1/tareas-outlook/informe?desde=2020-01-01&hasta=2026-01-01", headers=h).status_code == 400
    otro = _usuario(cliente, "ai2@ejemplo.com", db.crear_tenant("Otro despacho informe"))[0]
    assert cliente.get("/api/v1/tareas-outlook/informe", headers=otro).get_json()["data"]["ahora"]["abiertas"] == 0       # nada del despacho ajeno


def test_pantalla_csv_y_pdf(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "wi1@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho pantalla informe")
    db.asignar_tenant(uid, t)
    c = db.crear_cliente_fiscal(t, "=HYPERLINK(\"http://malo\")")
    db.crear_tarea_outlook(uid, asunto="Una", fecha_vencimiento="2026-01-01", cliente_fiscal_id=c)
    html = cliente.get("/tareas/informes?desde=2026-01-01&hasta=2026-12-31").get_data(as_text=True)
    assert "Por persona" in html and "Por cliente" in html and "2026-01-01" in html and "Informes" in html
    assert "no puede ser posterior" in cliente.get("/tareas/informes?desde=2026-12-01&hasta=2026-01-01").get_data(as_text=True)
    csv = cliente.get("/tareas/informes.csv?desde=2026-01-01&hasta=2026-12-31")
    cuerpo = csv.get_data(as_text=True)
    assert csv.mimetype == "text/csv" and "Sección" in cuerpo and "attachment" in csv.headers["Content-Disposition"]
    assert "=HYPERLINK" not in cuerpo.replace("'=HYPERLINK", "")                                      # la fórmula del cliente no se ejecuta en Excel
    pdf = cliente.get("/tareas/informes.pdf?desde=2026-01-01&hasta=2026-12-31")
    assert pdf.mimetype == "application/pdf" and pdf.data[:4] == b"%PDF"
    assert cliente.get("/tareas/informes.csv?desde=malo").status_code == 302
