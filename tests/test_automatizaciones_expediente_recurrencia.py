"""Disparadores «Se genera una tarea recurrente», «Se abre un expediente» y «Un expediente cambia de estado» (app/automatizaciones.py)."""
from datetime import datetime, timezone

import pytest

from app import automatizaciones as au, db, nucleo
from tests.test_automatizaciones import AHORA, _avisos_de_automatizacion, d  # noqa: F401  (la fixture del despacho de pruebas)


def _expediente(d, titulo="Constitución de la sociedad", responsable=None, **kw):
    cliente_nucleo = db.get_connection().execute("SELECT cliente_id FROM clientes_fiscales WHERE id = ?", (d.cliente,)).fetchone()["cliente_id"]
    return nucleo.crear_expediente(d.t, responsable or d.cus, cliente_nucleo, titulo, tipo=kw.pop("tipo", "general"), **kw)


def _tareas_de_auto(t):
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT t.* FROM tareas_outlook t JOIN usuarios u ON u.id = t.usuario_id WHERE u.tenant_id = ? AND t.referencia_externa LIKE 'auto:%' ORDER BY t.id", (t,))]
    finally:
        conn.close()


# --- Recurrencia ------------------------------------------------------------------------------------------------------------

def test_validacion_de_los_disparadores_nuevos(d):
    assert au.validar_condiciones("recurrencia.generada", {"periodicidades": ["mensual", "rara"]}) == {"periodicidades": ["mensual"]}
    assert au.validar_condiciones("recurrencia.generada", {}) == {}
    assert au.validar_condiciones("expediente.creado", {"tipo": "general"}) == {"tipo": "general"}
    assert au.validar_condiciones("expediente.creado", {}) == {}
    assert au.validar_condiciones("expediente.estado", {"estado": "cerrado", "tipo": ""}) == {"estado": "cerrado"}
    for malo in ({}, {"estado": ""}, {"estado": "Con Espacios; DROP"}):
        with pytest.raises(ValueError):
            au.validar_condiciones("expediente.estado", malo)
    with pytest.raises(ValueError):
        au.validar_condiciones("expediente.creado", {"tipo": "../x"})
    # las variables son las de cada disparador
    au.validar_acciones("expediente.estado", [{"tipo": "notificar", "titulo": "{expediente} pasa de {anterior} a {estado}"}])
    with pytest.raises(ValueError, match="no existe"):
        au.validar_acciones("expediente.creado", [{"tipo": "notificar", "titulo": "{anterior}"}])
    with pytest.raises(ValueError, match="no existe"):
        au.validar_acciones("recurrencia.generada", [{"tipo": "notificar", "titulo": "{estado}"}])
    # un expediente no es una tarea: las acciones sobre la tarea no valen
    for accion in ({"tipo": "comentar", "texto": "x"}, {"tipo": "fijar_fecha"}, {"tipo": "asignar", "a": 1}):
        with pytest.raises(ValueError, match="solo vale cuando el disparador es una tarea"):
            au.validar_acciones("expediente.estado", [accion])
    au.validar_acciones("recurrencia.generada", [{"tipo": "fijar_fecha", "dias_plazo": 3}])           # la recurrente SÍ es una tarea


def test_tipo_y_estado_tienen_que_existir_para_el_despacho(d):
    nota = [{"tipo": "notificar", "titulo": "x", "a": "direccion"}]
    with pytest.raises(ValueError, match="tipo de expediente"):
        au.crear_regla(d.t, d.sup, "x", "expediente.creado", {"tipo": "inventado"}, nota)
    with pytest.raises(ValueError, match="estado no existe"):
        au.crear_regla(d.t, d.sup, "x", "expediente.estado", {"estado": "inventado"}, nota)
    with pytest.raises(ValueError, match="estado no existe"):
        au.crear_regla(d.t, d.sup, "x", "expediente.estado", {"estado": "en_revision", "tipo": "general"}, nota)          # ese estado no es de ese tipo
    assert au.crear_regla(d.t, d.sup, "ok", "expediente.estado", {"estado": "cerrado", "tipo": "general"}, nota)


def test_generar_una_recurrente_dispara_la_regla_y_ponerle_fecha(d):
    au.crear_regla(d.t, d.sup, "Fecha a las recurrentes", "recurrencia.generada", {"periodicidades": ["diaria"]},
                   [{"tipo": "fijar_fecha", "dias_plazo": 7}, {"tipo": "notificar", "titulo": "Nueva recurrente: {asunto} ({periodicidad})", "a": "direccion"}])
    au.crear_regla(d.t, d.sup, "Solo mensuales", "recurrencia.generada", {"periodicidades": ["mensual"]}, [{"tipo": "notificar", "titulo": "Mensual: {asunto}", "a": "direccion"}])
    db.crear_tarea_recurrente(d.cus, "Cerrar la caja", "diaria", 0)
    assert db.generar_tareas_recurrentes() == 1
    r = au.procesar_eventos(AHORA)
    assert r["eventos"] == 1 and r["ejecuciones"] == 1 and r["fallidas"] == 0                         # la «mensual» no cumple
    tarea = [t for t in db.listar_tareas_outlook(d.cus) if t["asunto"] == "Cerrar la caja"][0]
    assert tarea["fecha_vencimiento"]                                                                  # las recurrentes nacen sin fecha: la regla se la pone
    assert [a["titulo"] for a in _avisos_de_automatizacion(d.sup)] == ["Nueva recurrente: Cerrar la caja (diaria)"]
    assert db.generar_tareas_recurrentes() == 0 and au.procesar_eventos(AHORA)["eventos"] == 0       # idempotente: no se genera ni se dispara otra vez


def test_la_tarea_recurrente_no_dispara_la_regla_de_tarea_creada_y_es_un_hecho_documentado(d):
    au.crear_regla(d.t, d.sup, "Toda tarea nueva", "tarea.creada", {}, [{"tipo": "notificar", "titulo": "Nueva {asunto}", "a": "direccion"}])
    db.crear_tarea_recurrente(d.cus, "Recurrente", "diaria", 0)
    db.generar_tareas_recurrentes()
    assert au.procesar_eventos(AHORA)["eventos"] == 0 and _avisos_de_automatizacion(d.sup) == []


def test_una_regla_de_recurrencia_no_se_dispara_a_si_misma(d):
    au.crear_regla(d.t, d.sup, "Crea otra", "recurrencia.generada", {}, [{"tipo": "crear_tarea", "asunto": "Seguimiento de {asunto}", "dias_plazo": 2, "asignar_a": d.cus}])
    db.crear_tarea_recurrente(d.cus, "Base", "diaria", 0)
    db.generar_tareas_recurrentes()
    au.procesar_eventos(AHORA)
    au.procesar_eventos(AHORA)
    assert [t["asunto"] for t in _tareas_de_auto(d.t)] == ["Seguimiento de Base"]


def test_simular_la_regla_de_recurrencia(d):
    rid = au.crear_regla(d.t, d.sup, "Sim", "recurrencia.generada", {}, [{"tipo": "notificar", "titulo": "{asunto}", "a": "direccion"}])
    db.crear_tarea_recurrente(d.cus, "Hecha hoy", "diaria", 0)
    db.generar_tareas_recurrentes()
    r = au.simular(d.t, rid, datetime.now(timezone.utc))
    assert r["reciente"] is True and [e["datos"]["asunto"] for e in r["ejemplos"]] == ["Hecha hoy"]


# --- Expedientes ------------------------------------------------------------------------------------------------------------

def test_abrir_un_expediente_dispara_la_regla_con_sus_variables(d):
    au.crear_regla(d.t, d.sup, "Al abrir", "expediente.creado", {}, [{"tipo": "notificar", "titulo": "Nuevo: {expediente} de {cliente} ({tipo}, {estado})", "a": "direccion"},
                                                                  {"tipo": "crear_tarea", "asunto": "Preparar {expediente}", "dias_plazo": 3, "asignar_a": "responsable"}])
    x = _expediente(d, "Constitución")
    r = au.procesar_eventos(AHORA)
    assert r["eventos"] == 1 and r["ejecuciones"] == 1 and r["errores"] == 0
    assert [a["titulo"] for a in _avisos_de_automatizacion(d.sup)] == ["Nuevo: Constitución de Marta Puig (Expediente, Abierto)"]
    tareas = _tareas_de_auto(d.t)
    assert [t["asunto"] for t in tareas] == ["Preparar Constitución"] and tareas[0]["usuario_id"] == d.cus and tareas[0]["cliente_fiscal_id"] == d.cliente and x
    assert au.procesar_eventos(AHORA)["eventos"] == 0                                                  # no se repite


def test_cambiar_de_estado_solo_dispara_al_estado_elegido_y_al_tipo_elegido(d):
    au.crear_regla(d.t, d.sup, "Al cerrar", "expediente.estado", {"estado": "cerrado", "tipo": "general"},
                   [{"tipo": "notificar", "titulo": "{expediente}: de {anterior} a {estado}", "a": "direccion"}])
    x = _expediente(d, "Se cierra")
    nucleo.cambiar_estado_expediente(d.t, d.cus, x, "en_curso")
    nucleo.cambiar_estado_expediente(d.t, d.cus, x, "en_curso")                                        # sin cambio real: no hay evento
    nucleo.cambiar_estado_expediente(d.t, d.cus, x, "cerrado")
    r = au.procesar_eventos(AHORA)
    assert r["eventos"] == 2 and r["ejecuciones"] == 1                                                 # creado (nadie lo escucha) + dos estados (uno cumple)... el creado no se encola sin regla
    assert [a["titulo"] for a in _avisos_de_automatizacion(d.sup)] == ["Se cierra: de En curso a Cerrado"]


def test_el_expediente_confidencial_solo_avisa_a_quien_puede_verlo(d):
    au.crear_regla(d.t, d.sup, "Aviso", "expediente.creado", {}, [{"tipo": "notificar", "titulo": "Nuevo: {expediente}", "a": d.otro},
                                                                {"tipo": "notificar", "titulo": "Nuevo (dirección): {expediente}", "a": "direccion"}])
    _expediente(d, "Reservado", confidencial=True)                                                      # lo abre y lo lleva «cus»; «otro» no es miembro; la dirección sí lo ve
    au.procesar_eventos(AHORA)
    assert _avisos_de_automatizacion(d.otro) == []                                                      # ni el título le llega
    assert [a["titulo"] for a in _avisos_de_automatizacion(d.sup)] == ["Nuevo (dirección): Reservado"]


def test_una_tarea_para_quien_no_ve_el_expediente_falla_sin_filtrar_nada(d):
    au.crear_regla(d.t, d.sup, "Tarea", "expediente.creado", {}, [{"tipo": "crear_tarea", "asunto": "Mirar {expediente}", "asignar_a": d.otro}])
    _expediente(d, "Reservado", confidencial=True)
    r = au.procesar_eventos(AHORA)
    assert r["errores"] == 1 and _tareas_de_auto(d.t) == []


def test_las_reglas_de_expediente_no_ven_los_de_otro_despacho(d):
    au.crear_regla(d.t, d.sup, "Mi despacho", "expediente.creado", {}, [{"tipo": "notificar", "titulo": "Nuevo {expediente}", "a": "direccion"}])
    otro = db.crear_tenant("Otro despacho expedientes")
    uo = db.crear_usuario_vinculado_a_kratos("otro-exp@ejemplo.com", "k-otro-exp"); db.asignar_tenant(uo, otro)
    co = db.crear_cliente_fiscal(otro, "Cliente ajeno")
    cn = db.get_connection().execute("SELECT cliente_id FROM clientes_fiscales WHERE id = ?", (co,)).fetchone()["cliente_id"]
    nucleo.crear_expediente(otro, uo, cn, "Ajeno")
    assert au.procesar_eventos(AHORA)["ejecuciones"] == 0 and _avisos_de_automatizacion(d.sup) == []


def test_simular_las_reglas_de_expediente(d):
    r1 = au.crear_regla(d.t, d.sup, "Sim creado", "expediente.creado", {}, [{"tipo": "notificar", "titulo": "{expediente}", "a": "direccion"}])
    r2 = au.crear_regla(d.t, d.sup, "Sim estado", "expediente.estado", {"estado": "en_espera"}, [{"tipo": "notificar", "titulo": "{expediente}", "a": "direccion"}])
    x = _expediente(d, "Simulado")
    nucleo.cambiar_estado_expediente(d.t, d.cus, x, "en_espera")
    ahora = datetime.now(timezone.utc)
    assert [e["datos"]["expediente"] for e in au.simular(d.t, r1, ahora)["ejemplos"]] == ["Simulado"]
    s2 = au.simular(d.t, r2, ahora)
    assert s2["reciente"] is True and [e["datos"]["estado"] for e in s2["ejemplos"]] == ["En espera"]


def test_plantillas_nuevas_y_pantalla_del_constructor(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    uid = iniciar_sesion_de_prueba(cliente, "exp-pantalla@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho pantalla expedientes")
    db.asignar_tenant(uid, t)
    db.asignar_supervisor_tenant(uid, True)
    html = cliente.get("/tareas/automatizaciones/regla").get_data(as_text=True)
    for clave in ("recurrencia.generada", "expediente.creado", "expediente.estado"):
        assert f'value="{clave}"' in html
    assert 'name="c_estado_x"' in html and 'name="c_tipo_x"' in html and 'name="c_periodicidades_r"' in html and 'value="cerrado"' in html
    r = cliente.post("/tareas/automatizaciones/regla", data={"nombre": "Cierres", "disparador": "expediente.estado", "c_estado_x": "cerrado", "c_tipo_x": "general", "activa": "1",
                                                           "a0_tipo": "notificar", "a0_titulo": "Cerrado {expediente}", "a0_dest_aviso": "direccion"})
    assert r.status_code == 302
    regla = au.listar_reglas(t)[0]
    assert regla["disparador"] == "expediente.estado" and regla["condiciones"] == {"estado": "cerrado", "tipo": "general"}
    malo = cliente.post("/tareas/automatizaciones/regla", data={"nombre": "Mala", "disparador": "expediente.estado", "c_estado_x": "inventado", "a0_tipo": "comentar", "a0_texto": "x"})
    assert malo.status_code == 422
    for plantilla in ("recurrente_con_fecha", "expediente_cerrado"):
        assert cliente.post("/tareas/automatizaciones/nueva", data={"plantilla": plantilla}).status_code == 302
    assert {r["disparador"] for r in au.listar_reglas(t)} == {"expediente.estado", "recurrencia.generada"}
    pagina = cliente.get("/tareas/automatizaciones").get_data(as_text=True)
    assert "Poner fecha límite a las tareas recurrentes" in pagina and "Avisar cuando se cierre un expediente" in pagina


def test_las_tareas_por_vencimiento_si_disparan_tarea_creada(d):
    """Comprobado a propósito: las tareas «por vencimiento fiscal» pasan por crear_tarea_outlook, así que ya tienen disparador («Se crea una tarea»), a diferencia de las recurrentes."""
    from datetime import date, timedelta
    au.crear_regla(d.t, d.sup, "Toda tarea nueva", "tarea.creada", {}, [{"tipo": "notificar", "titulo": "Nueva {asunto}", "a": "direccion"}])
    hoy = date.today()
    db.crear_vencimiento_fiscal(d.t, d.cliente, "303", "2026-T4", (hoy + timedelta(days=5)).isoformat())
    db.crear_regla_por_vencimiento(d.sup, "303", "Preparar el {modelo} de {cliente}", crear_dias_antes=10, vence_dias_antes=2)
    assert db.generar_tareas_por_vencimiento(hoy) == 1
    r = au.procesar_eventos(AHORA)
    assert r["eventos"] == 1 and r["ejecuciones"] == 1
    assert [a["titulo"] for a in _avisos_de_automatizacion(d.sup)] == ["Nueva Preparar el 303 de Marta Puig"]


# --- «Se crea una tarea»: filtro por vencimiento fiscal y variables {modelo}/{periodo} --------------------------------------

def test_validacion_del_filtro_de_vencimiento_en_tarea_creada(d):
    assert au.validar_condiciones("tarea.creada", {}) == {}
    assert au.validar_condiciones("tarea.creada", {"desde_vencimiento": "1"}) == {"desde_vencimiento": True}
    assert au.validar_condiciones("tarea.creada", {"modelo": " 303 "}) == {"modelo": "303", "desde_vencimiento": True}        # pedir un modelo implica la opción
    assert au.validar_condiciones("tarea.creada", {"desde_vencimiento": ""}) == {}
    assert au.validar_condiciones("tarea.estado", {"estado": "esperando", "modelo": "303"}) == {"estado": "esperando"}          # en los demás disparadores no existe
    au.validar_acciones("tarea.creada", [{"tipo": "notificar", "titulo": "{modelo} {periodo}: {asunto}"}])
    with pytest.raises(ValueError, match="no existe"):
        au.validar_acciones("tarea.estado", [{"tipo": "notificar", "titulo": "{modelo}"}])


def _vencimientos(d):
    from datetime import date, timedelta
    hoy = date.today()
    for modelo, periodo in (("303", "2026-T4"), ("111", "2026-T4")):
        db.crear_vencimiento_fiscal(d.t, d.cliente, modelo, periodo, (hoy + timedelta(days=5)).isoformat())
    db.crear_regla_por_vencimiento(d.sup, "303", "Preparar el {modelo} de {cliente}", crear_dias_antes=10, vence_dias_antes=2)
    db.crear_regla_por_vencimiento(d.sup, "111", "Preparar el {modelo} de {cliente}", crear_dias_antes=10, vence_dias_antes=2)
    return hoy


def test_solo_las_tareas_de_un_vencimiento_y_las_variables_modelo_y_periodo(d):
    au.crear_regla(d.t, d.sup, "De vencimiento", "tarea.creada", {"desde_vencimiento": True},
                   [{"tipo": "notificar", "titulo": "Generada {modelo} {periodo}: {asunto}", "a": "direccion"}])
    hoy = _vencimientos(d)
    db.crear_tarea_outlook(d.cus, asunto="Tarea cualquiera")                                          # no viene de un vencimiento
    assert db.generar_tareas_por_vencimiento(hoy) == 2
    r = au.procesar_eventos(AHORA)
    assert r["eventos"] == 3 and r["ejecuciones"] == 2
    assert sorted(a["titulo"] for a in _avisos_de_automatizacion(d.sup)) == ["Generada 111 2026-T4: Preparar el 111 de Marta Puig", "Generada 303 2026-T4: Preparar el 303 de Marta Puig"]


def test_filtro_por_modelo_y_variables_vacias_en_las_demas(d):
    au.crear_regla(d.t, d.sup, "Solo 303", "tarea.creada", {"modelo": "303"}, [{"tipo": "notificar", "titulo": "Solo {modelo}", "a": "direccion"}])
    au.crear_regla(d.t, d.sup, "Todas", "tarea.creada", {}, [{"tipo": "notificar", "titulo": "Todas [{modelo}|{periodo}]: {asunto}", "a": "direccion"}])
    hoy = _vencimientos(d)
    db.crear_tarea_outlook(d.cus, asunto="Suelta")
    db.generar_tareas_por_vencimiento(hoy)
    au.procesar_eventos(AHORA)
    titulos = sorted(a["titulo"] for a in _avisos_de_automatizacion(d.sup))
    assert titulos == ["Solo 303", "Todas [111|2026-T4]: Preparar el 111 de Marta Puig", "Todas [303|2026-T4]: Preparar el 303 de Marta Puig", "Todas [|]: Suelta"]


def test_el_modelo_no_distingue_mayusculas_y_la_simulacion_lo_respeta(d):
    rid = au.crear_regla(d.t, d.sup, "Modelo", "tarea.creada", {"modelo": "190"}, [{"tipo": "notificar", "titulo": "{modelo}", "a": "direccion"}])
    from datetime import date, timedelta
    db.crear_vencimiento_fiscal(d.t, d.cliente, "190", "2026", (date.today() + timedelta(days=3)).isoformat())
    db.crear_regla_por_vencimiento(d.sup, "190", "Resumen {modelo}", crear_dias_antes=10, vence_dias_antes=1)
    db.generar_tareas_por_vencimiento(date.today())
    db.crear_tarea_outlook(d.cus, asunto="Otra")
    from datetime import datetime, timezone
    s = au.simular(d.t, rid, datetime.now(timezone.utc))
    assert [e["datos"]["modelo"] for e in s["ejemplos"]] == ["190"]


def test_pantalla_del_filtro_de_vencimiento(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    uid = iniciar_sesion_de_prueba(cliente, "venc-pantalla@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho pantalla vencimiento")
    db.asignar_tenant(uid, t)
    db.asignar_supervisor_tenant(uid, True)
    html = cliente.get("/tareas/automatizaciones/regla").get_data(as_text=True)
    assert 'name="c_venc_c"' in html and 'name="c_modelo_c"' in html and "{modelo}" in html
    r = cliente.post("/tareas/automatizaciones/regla", data={"nombre": "303 nuevos", "disparador": "tarea.creada", "c_modelo_c": "303", "activa": "1",
                                                           "a0_tipo": "notificar", "a0_titulo": "Nuevo {modelo} de {cliente}", "a0_dest_aviso": "direccion"})
    assert r.status_code == 302
    assert au.listar_reglas(t)[0]["condiciones"] == {"modelo": "303", "desde_vencimiento": True}
    editar = cliente.get(f"/tareas/automatizaciones/regla/{au.listar_reglas(t)[0]['id']}").get_data(as_text=True)
    assert 'value="303"' in editar and 'name="c_venc_c" value="1" checked' in editar


# --- «Una tarea queda libre» ----------------------------------------------------------------------------------------------

def test_completar_lo_que_esperaba_dispara_la_regla_de_tarea_liberada(d):
    au.crear_regla(d.t, d.sup, "Libre", "tarea.liberada", {"prioridades": ["alta"]},
                   [{"tipo": "notificar", "titulo": "Libre: {asunto} (tras «{previa}»)", "a": "direccion"}, {"tipo": "fijar_fecha", "dias_plazo": 4}])
    previa = db.crear_tarea_outlook(d.cus, asunto="Recoger documentación")
    otra_previa = db.crear_tarea_outlook(d.cus, asunto="Pedir certificado")
    siguiente = db.crear_tarea_outlook(d.cus, asunto="Preparar la declaración", prioridad="alta")
    normal = db.crear_tarea_outlook(d.cus, asunto="Archivar", prioridad="normal")
    for previa_id in (previa, otra_previa):
        assert db.anadir_dependencia_tarea(d.cus, siguiente, previa_id)
    assert db.anadir_dependencia_tarea(d.cus, normal, previa)
    db.completar_tarea_outlook(d.cus, previa)
    assert au.procesar_eventos(AHORA)["ejecuciones"] == 0                                              # «siguiente» aún espera a la otra; «normal» no cumple la prioridad
    db.completar_tarea_outlook(d.cus, otra_previa)
    r = au.procesar_eventos(AHORA)
    assert r["ejecuciones"] == 1 and r["fallidas"] == 0
    assert [a["titulo"] for a in _avisos_de_automatizacion(d.sup)] == ["Libre: Preparar la declaración (tras «Pedir certificado»)"]
    assert [t for t in db.listar_tareas_outlook(d.cus) if t["id"] == siguiente][0]["fecha_vencimiento"]


def test_validacion_y_pantalla_de_tarea_liberada(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    assert au.validar_condiciones("tarea.liberada", {"prioridades": ["alta", "x"]}) == {"prioridades": ["alta"]}
    assert au.validar_condiciones("tarea.liberada", {"modelo": "303"}) == {}                              # el filtro de vencimiento es solo de «Se crea una tarea»
    au.validar_acciones("tarea.liberada", [{"tipo": "asignar", "a": 1}, {"tipo": "notificar", "titulo": "{previa}"}])
    with pytest.raises(ValueError, match="no existe"):
        au.validar_acciones("tarea.liberada", [{"tipo": "notificar", "titulo": "{modelo}"}])
    uid = iniciar_sesion_de_prueba(cliente, "liberada-pantalla@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho pantalla liberada")
    db.asignar_tenant(uid, t)
    db.asignar_supervisor_tenant(uid, True)
    assert 'name="c_prioridades_l"' in cliente.get("/tareas/automatizaciones/regla").get_data(as_text=True)
    r = cliente.post("/tareas/automatizaciones/regla", data={"nombre": "Libres", "disparador": "tarea.liberada", "c_prioridades_l": ["alta"], "activa": "1",
                                                           "a0_tipo": "notificar", "a0_titulo": "Libre {asunto}", "a0_dest_aviso": "responsable"})
    assert r.status_code == 302 and au.listar_reglas(t)[0]["condiciones"] == {"prioridades": ["alta"]}


# --- «En revisión» como estado: las reglas lo ven ---------------------------------------------------------------------------

def test_pedir_la_revision_es_un_cambio_de_estado_que_las_reglas_ven(d):
    from app import tareas_trabajo as tt
    au.crear_regla(d.t, d.sup, "A revisión", "tarea.estado", {"estado": "en_revision"}, [{"tipo": "notificar", "titulo": "{asunto}: de {anterior} a {estado}", "a": "direccion"}])
    t = db.crear_tarea_outlook(d.cus, asunto="Para revisar")
    db.cambiar_estado_tarea_outlook(d.cus, t, "en_progreso")
    au.procesar_eventos(AHORA)
    tt.solicitar_revision(d.cus, t, d.otro)
    assert au.procesar_eventos(AHORA)["ejecuciones"] == 1
    assert [a["titulo"] for a in _avisos_de_automatizacion(d.sup)] == ["Para revisar: de En progreso a En revisión"]
    with pytest.raises(ValueError, match="ya está en revisión"):
        au.crear_regla(d.t, d.sup, "Absurda", "tarea.estado", {"estado": "en_revision"}, [{"tipo": "pedir_revision", "revisor": d.otro}])


def test_el_cliente_no_ve_la_revision_interna_y_el_calendario_externo_la_exporta_como_en_curso(d):
    from app import outlook_ics, tareas_trabajo as tt
    t = db.crear_tarea_outlook(d.cus, asunto="Con cliente", cliente_fiscal_id=d.cliente)
    tt.fijar_visible_cliente(d.cus, t, True)
    tt.solicitar_revision(d.cus, t, d.otro)
    cliente_nucleo = tt.tareas_para_cliente(d.t, d.cliente)
    assert cliente_nucleo[0]["estado_texto"] == "En curso" and "revisi" not in cliente_nucleo[0]["estado_texto"].lower()
    assert outlook_ics.ESTADO_A_ICS["en_revision"] == "IN-PROCESS" and outlook_ics.ESTADO_A_CSV_EXPORTAR["en_revision"] == "In Progress"
    assert "en_revision" not in outlook_ics.CSV_A_ESTADO.values()
