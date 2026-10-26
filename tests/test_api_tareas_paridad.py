"""Tareas en la API como las ve la web (Fase 1 del plan de paridad con la app): `completadas`, indicadores por fila y alta con texto libre."""
from datetime import date, timedelta

from app import db
from tests.test_api_fiscal import _cliente_fiscal, _despacho


def _crear(cliente, h, **datos):
    r = cliente.post("/api/v1/tareas-outlook", json=datos, headers=h)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["data"]


def test_completadas_0_oculta_las_hechas_igual_que_la_web(cliente):
    h, uid, _ = _despacho(cliente, "paridad1@ejemplo.com")
    a = _crear(cliente, h, asunto="Pendiente")["id"]
    b = _crear(cliente, h, asunto="Hecha")["id"]
    assert cliente.post(f"/api/v1/tareas-outlook/{b}/completar", headers=h).status_code == 200
    ids = lambda **q: {t["id"] for t in cliente.get("/api/v1/tareas-outlook", query_string=q, headers=h).get_json()["data"]}
    assert ids() == {a, b}                                  # sin parámetro: como siempre
    assert ids(completadas="0") == {a}
    assert ids(completadas="1") == {a, b}
    assert ids(completadas="0", estado="completada") == {b}  # pedir un estado manda, como en la web


def test_cada_fila_trae_sus_indicadores(cliente):
    h, uid, _ = _despacho(cliente, "paridad2@ejemplo.com")
    t = _crear(cliente, h, asunto="Con cosas")["id"]
    previa = _crear(cliente, h, asunto="Previa")["id"]
    cliente.post(f"/api/v1/tareas-outlook/{t}/comentarios", json={"texto": "uno"}, headers=h)
    cliente.post(f"/api/v1/tareas-outlook/{t}/checklist", json={"texto": "paso 1"}, headers=h)
    cliente.post(f"/api/v1/tareas-outlook/{t}/dependencias", json={"depende_de_id": previa}, headers=h)
    fila = next(f for f in cliente.get("/api/v1/tareas-outlook", headers=h).get_json()["data"] if f["id"] == t)
    assert (fila["n_comentarios"], fila["checklist_total"], fila["checklist_hechas"], fila["bloqueos"]) == (1, 1, 0, 1)
    sola = next(f for f in cliente.get("/api/v1/tareas-outlook", headers=h).get_json()["data"] if f["id"] == previa)
    assert (sola["n_comentarios"], sola["checklist_total"], sola["bloqueos"]) == (0, 0, 0)


def test_alta_con_texto_libre_entiende_fecha_prioridad_persona_y_proyecto(cliente):
    h, uid, t = _despacho(cliente, "paridad3@ejemplo.com")
    h2, luis, _ = _despacho(cliente, "luis.paridad@ejemplo.com", tenant_id=t)
    db.crear_categoria(uid, "IVA")
    r = _crear(cliente, h, asunto="mañana pedir extractos a Sol @luis !alta #IVA", texto_libre=True)
    assert r["asunto"] == "pedir extractos a Sol"
    assert r["prioridad"] == "alta" and r["asignada_a"] == luis and r["categoria_id"]
    assert r["fecha_vencimiento"].startswith((date.today() + timedelta(days=1)).isoformat())
    assert r["sin_resolver"] == []


def test_texto_libre_no_adivina_lo_que_no_encuentra_y_sin_la_marca_el_texto_va_tal_cual(cliente):
    h, uid, _ = _despacho(cliente, "paridad4@ejemplo.com")
    r = _crear(cliente, h, asunto="llamar @fantasma #nada", texto_libre=True)
    assert r["asignada_a"] is None and r["sin_resolver"]
    literal = _crear(cliente, h, asunto="llamar @luis !alta mañana")
    assert literal["asunto"] == "llamar @luis !alta mañana" and literal["prioridad"] == "normal"


def test_alta_con_campos_explicitos_valida_persona_proyecto_y_cliente(cliente):
    h, uid, t = _despacho(cliente, "paridad5@ejemplo.com")
    _, otro_despacho, _ = _despacho(cliente, "ajeno.paridad@ejemplo.com")
    r = cliente.post("/api/v1/tareas-outlook", json={"asunto": "x", "asignada_a": otro_despacho}, headers=h)
    assert r.status_code == 400 and r.get_json()["codigo"] == "asignada_invalida"
    r = cliente.post("/api/v1/tareas-outlook", json={"asunto": "x", "categoria_id": 99999}, headers=h)
    assert r.status_code == 400 and r.get_json()["codigo"] == "proyecto_invalido"
    cid = _cliente_fiscal(cliente, h)
    assert _crear(cliente, h, asunto="de cliente", cliente_fiscal_id=cid)["cliente_fiscal_id"] == cid


def test_categorias_outlook_para_el_filtro(cliente):
    h, uid, _ = _despacho(cliente, "paridad6@ejemplo.com")
    _crear(cliente, h, asunto="a", categoria_outlook="Fiscal")
    _crear(cliente, h, asunto="b", categoria_outlook="Laboral")
    _crear(cliente, h, asunto="c", categoria_outlook="Fiscal")
    r = cliente.get("/api/v1/tareas-outlook/categorias-outlook", headers=h)
    assert r.status_code == 200 and r.get_json()["data"] == ["Fiscal", "Laboral"]


def test_la_estimacion_se_escribe_como_en_la_web_y_la_interpreta_el_servidor(cliente):
    h, uid, _ = _despacho(cliente, "paridad7@ejemplo.com")
    t = _crear(cliente, h, asunto="estimar")["id"]
    put = lambda texto: cliente.put(f"/api/v1/tareas-outlook/{t}", json={"estimacion": texto}, headers=h)
    assert put("1h30").get_json()["data"]["estimacion_min"] == 90
    assert put("2").get_json()["data"]["estimacion_min"] == 120      # un número solo son horas
    assert put("45 min").get_json()["data"]["estimacion_min"] == 45
    r = put("mucho")
    assert r.status_code == 400 and r.get_json()["codigo"] == "estimacion_invalida"
    assert put("").get_json()["data"]["estimacion_min"] is None      # vacío la quita


def test_el_tiempo_de_una_tarea_trae_mi_cronometro_y_la_hora_del_servidor(cliente):
    h, uid, _ = _despacho(cliente, "paridad8@ejemplo.com")
    t = _crear(cliente, h, asunto="con reloj")["id"]
    d = cliente.get(f"/api/v1/tareas-outlook/{t}/tiempo", headers=h).get_json()["data"]
    assert d["cronometro"] is None and d["mio_segundos"] == 0 and d["ahora"] and d["personas"] == []
    proyecto = db.crear_categoria(uid, "Gestión")
    r = cliente.post(f"/api/v1/tareas-outlook/{t}/cronometro/iniciar", json={"proyecto_id": proyecto}, headers=h)
    assert r.status_code == 201
    cron = cliente.get(f"/api/v1/tareas-outlook/{t}/tiempo", headers=h).get_json()["data"]["cronometro"]
    assert cron["estado"] == "en_curso" and cron["id"] == r.get_json()["data"]["tarea_cronometro_id"]
    assert cliente.post(f"/api/v1/tareas/{cron['id']}/pausar", headers=h).status_code == 200
    pausado = cliente.get(f"/api/v1/tareas-outlook/{t}/tiempo", headers=h).get_json()["data"]["cronometro"]
    assert pausado["estado"] == "pausada" and pausado["segundos_trabajados_congelado"] is not None
    assert cliente.post(f"/api/v1/tareas/{cron['id']}/finalizar", headers=h).status_code == 200
    final = cliente.get(f"/api/v1/tareas-outlook/{t}/tiempo", headers=h).get_json()["data"]
    assert final["cronometro"] is None          # ya finalizado (sin segundos no hay persona en la lista)


def test_el_calendario_de_la_api_trae_lo_mismo_que_el_de_la_web(cliente):
    """Mismo día, mismas tareas: la web (vista día) y la API salen de la misma función."""
    import re
    from datetime import date, timedelta
    from tests.conftest import iniciar_sesion_de_prueba
    web_uid = iniciar_sesion_de_prueba(cliente, "cal-web@ejemplo.com", "contrasena123")
    h, api_uid, _ = _despacho(cliente, "cal-api@ejemplo.com")
    hoy = date.today()
    for uid in (web_uid, api_uid):
        db.crear_tarea_outlook(uid, asunto="C1 vence hoy", fecha_vencimiento=hoy.isoformat())
        db.crear_tarea_outlook(uid, asunto="C2 empieza hoy", fecha_inicio=hoy.isoformat())
        db.crear_tarea_outlook(uid, asunto="C3 mañana", fecha_vencimiento=(hoy + timedelta(days=1)).isoformat())
        db.crear_tarea_outlook(uid, asunto="C4 sin fecha")
    api = cliente.application.test_client()
    for vista in ("dia", "semana", "semana_laboral", "mes"):
        r = api.get("/api/v1/tareas-outlook/calendario", query_string={"vista": vista, "fecha": hoy.isoformat()}, headers=h)
        assert r.status_code == 200, r.get_json()
        d = r.get_json()["data"]
        por_dia = {x["fecha"]: [t["asunto"] for t in x["tareas"]] for x in d["dias"] if x["tareas"]}
        assert "C4 sin fecha" not in str(por_dia)
        assert sorted(por_dia.get(hoy.isoformat(), [])) == ["C1 vence hoy", "C2 empieza hoy"]
        assert "C3 mañana" in por_dia.get((hoy + timedelta(days=1)).isoformat(), []) or vista in ("dia",) or hoy.weekday() == 6 and vista == "semana_laboral"
        html = cliente.get("/tareas/calendario", query_string={"vista": vista, "fecha": hoy.isoformat()}).get_data(as_text=True)
        web = sorted(set(re.findall(r'href="/tareas/\d+(?:/editar)?"[^>]*>\s*(C\d [^<]*?)\s*</a>', html)))
        api_todas = sorted({t["asunto"] for x in d["dias"] for t in x["tareas"] if t["asunto"].startswith("C")})
        assert api_todas == web, (vista, api_todas, web)
    assert api.get("/api/v1/tareas-outlook/calendario", query_string={"vista": "año"}, headers=h).status_code == 400
    assert api.get("/api/v1/tareas-outlook/calendario", query_string={"fecha": "ayer"}, headers=h).status_code == 400


def test_la_carga_de_la_api_trae_fechas_iso_y_los_mismos_numeros_que_la_web(cliente):
    from datetime import date, timedelta
    h, uid, _ = _despacho(cliente, "carga-api@ejemplo.com")
    lunes = date.today() - timedelta(days=date.today().weekday())
    db.crear_tarea_outlook(uid, asunto="Con horas", fecha_vencimiento=(lunes + timedelta(days=1)).isoformat(), estimacion_min=90)
    db.crear_tarea_outlook(uid, asunto="Sin horas", fecha_vencimiento=(lunes + timedelta(days=1)).isoformat())
    db.crear_tarea_outlook(uid, asunto="Atrasada", fecha_vencimiento=(lunes - timedelta(days=2)).isoformat(), estimacion_min=30)
    d = cliente.get("/api/v1/tareas-outlook/carga", query_string={"semana": date.today().isoformat()}, headers=h).get_json()["data"]
    assert d["lunes"] == lunes.isoformat()
    assert [x[:10] for x in d["dias"]] == [(lunes + timedelta(days=i)).isoformat() for i in range(7)]
    yo = next(p for p in d["personas"] if p["yo"])
    martes = yo["dias"][(lunes + timedelta(days=1)).isoformat()]
    assert (martes["min"], martes["n"], martes["sin_estimar"]) == (90, 2, 1)
    assert yo["atrasadas"]["min"] == 30 and yo["capacidad_semana_min"] == yo["capacidad_dia_min"] * 5
