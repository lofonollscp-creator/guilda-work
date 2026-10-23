"""Reglas laborales de la plataforma (app/reglas_laborales.py y backoffice/rutas_reglas.py): ninguna fecha en el código, versiones y aprobación por el propietario.
Todos los valores de estos tests son ficticios: no reflejan ninguna obligación real."""
import pytest

from app import db, reglas_laborales as rl
from tests.test_backoffice_app import bo, entrar, post          # noqa: F401  (fixture y ayudas del backoffice)


# --- Cálculo puro ---------------------------------------------------------------------------------------------------------------------------------

def test_periodos_mensuales_en_el_mismo_mes():
    p = rl.periodos_mensuales({"dia": 12, "mes_siguiente": 0}, 2027)
    assert len(p) == 12 and p[0] == {"periodo": "2027-01", "fecha_limite": "2027-01-12"} and p[11] == {"periodo": "2027-12", "fecha_limite": "2027-12-12"}


def test_periodos_mensuales_el_mes_siguiente_salta_de_diciembre_a_enero():
    p = {x["periodo"]: x["fecha_limite"] for x in rl.periodos_mensuales({"dia": 5, "mes_siguiente": 1}, 2027)}
    assert p["2027-03"] == "2027-04-05" and p["2027-12"] == "2028-01-05"


def test_un_dia_que_el_mes_no_tiene_cae_en_su_ultimo_dia():
    p = {x["periodo"]: x["fecha_limite"] for x in rl.periodos_mensuales({"dia": 31, "mes_siguiente": 0}, 2028)}      # 2028 es bisiesto
    assert p["2028-02"] == "2028-02-29" and p["2028-04"] == "2028-04-30" and p["2028-01"] == "2028-01-31"
    assert {x["periodo"]: x["fecha_limite"] for x in rl.periodos_mensuales({"dia": 30, "mes_siguiente": 1}, 2027)}["2027-01"] == "2027-02-28"


def test_periodo_anual_en_el_mismo_anio_o_en_el_siguiente():
    assert rl.periodo_anual({"dia": 15, "mes": 3, "anio_siguiente": 1}, 2026) == {"periodo": "2026-anual", "fecha_limite": "2027-03-15"}
    assert rl.periodo_anual({"dia": 15, "mes": 3, "anio_siguiente": 0}, 2026) == {"periodo": "2026-anual", "fecha_limite": "2026-03-15"}
    assert rl.periodo_anual({"dia": 31, "mes": 2, "anio_siguiente": 0}, 2027)["fecha_limite"] == "2027-02-28"


@pytest.mark.parametrize("clave,datos,fragmento", [
    ("tc", {"dia": "0"}, "Día"), ("tc", {"dia": "32"}, "Día"), ("tc", {"dia": "abc"}, "número"),
    ("m190", {"dia": "5", "mes": "13"}, "Mes"), ("m190", {"dia": "5"}, "Mes"),
    ("alta_ss", {"plazo": "5", "unidad": "lustros"}, "Unidad"), ("alta_ss", {"plazo": "mucho", "unidad": "habiles"}, "Plazo"),
    ("inventada", {"dia": "5"}, "desconocida"),
])
def test_los_parametros_no_validos_se_rechazan(clave, datos, fragmento):
    with pytest.raises(ValueError, match=fragmento):
        rl.validar(clave, datos)


def test_validar_conserva_solo_lo_que_usa_cada_tipo_y_admite_plazos_negativos():
    assert rl.validar("tc", {"dia": "7", "mes_siguiente": "1", "plazo": "9", "mes": "3"}) == {"dia": 7, "mes_siguiente": 1}
    assert rl.validar("m190", {"dia": "31", "mes": "1", "anio_siguiente": "1"}) == {"dia": 31, "mes": 1, "anio_siguiente": 1}
    assert rl.validar("alta_ss", {"plazo": "-1", "unidad": "naturales", "dia": "9"}) == {"plazo": -1, "unidad": "naturales"}


# --- Versiones y aprobación -----------------------------------------------------------------------------------------------------------------------

def test_al_instalar_no_hay_ninguna_regla_aprobada():
    assert rl.vigentes() == {} and rl.vigente("tc") is None
    todas = rl.estado_de_todas()
    assert [r["clave"] for r in todas] == ["tc", "m190", "alta_ss", "baja_ss", "contrato"] and all(r["vigente"] is None and r["borrador"] is None for r in todas)


def test_un_borrador_no_se_aplica_hasta_que_se_aprueba():
    assert rl.guardar_borrador("tc", "jorge", dia="9", mes_siguiente="1") == 1
    assert rl.vigente("tc") is None
    assert rl.estado_de_todas()[0]["borrador"]["dia"] == 9
    rl.aprobar("tc", 1, "jorge")
    v = rl.vigente("tc")
    assert v["version"] == 1 and v["dia"] == 9 and v["mes_siguiente"] == 1 and v["aprobada_por"] == "jorge" and v["aprobada_en"]


def test_reescribir_un_borrador_no_crea_versiones_pero_cambiar_lo_aprobado_si():
    assert rl.guardar_borrador("tc", "jorge", dia="9") == 1 and rl.guardar_borrador("tc", "jorge", dia="10") == 1
    rl.aprobar("tc", 1, "jorge")
    assert rl.guardar_borrador("tc", "jorge", dia="11") == 2
    assert rl.vigente("tc")["dia"] == 10, "la vigente no cambia hasta aprobar la nueva"
    e = rl.estado_de_todas()[0]
    assert e["vigente"]["version"] == 1 and e["borrador"]["version"] == 2
    rl.aprobar("tc", 2, "jorge")
    assert rl.vigente("tc")["dia"] == 11 and rl.estado_de_todas()[0]["borrador"] is None and [h["version"] for h in rl.estado_de_todas()[0]["historial"]] == [1]


def test_no_se_aprueba_una_version_anterior_a_la_vigente_ni_una_que_no_existe():
    rl.guardar_borrador("m190", "jorge", dia="20", mes="1", anio_siguiente="1"); rl.aprobar("m190", 1, "jorge")
    rl.guardar_borrador("m190", "jorge", dia="25", mes="1", anio_siguiente="1"); rl.aprobar("m190", 2, "jorge")
    rl.aprobar("m190", 2, "otro")                                       # aprobar lo ya aprobado no cambia nada
    assert rl.vigente("m190")["aprobada_por"] == "jorge"
    # Una versión vieja sin aprobar (no sale del flujo normal; se fabrica a mano) no puede pasar por encima de la vigente.
    conn = db.get_connection()
    conn.execute("INSERT INTO reglas_laborales (clave, version, tipo, dia, mes, aprobada, creada_en) VALUES ('m190', 0, 'anual', 1, 1, 0, '2026-01-01')")
    conn.commit(); conn.close()
    with pytest.raises(ValueError, match="más reciente"):
        rl.aprobar("m190", 0, "jorge")
    with pytest.raises(ValueError, match="no existe"):
        rl.aprobar("m190", 9, "jorge")


def test_cada_borrador_y_cada_aprobacion_quedan_en_la_auditoria():
    rl.guardar_borrador("alta_ss", "jorge", plazo="-1", unidad="habiles")
    rl.aprobar("alta_ss", 1, "jorge")
    conn = db.get_connection()
    filas = conn.execute("SELECT accion, entidad_id, detalle, tenant_id FROM auditoria_eventos WHERE entidad = 'regla_laboral' ORDER BY id").fetchall()
    conn.close()
    assert [f["accion"] for f in filas] == ["regla_laboral.borrador", "regla_laboral.aprobada"] and all(f["entidad_id"] == "alta_ss:1" and not f["tenant_id"] for f in filas)
    assert '"por": "jorge"' in filas[1]["detalle"]


# --- Backoffice -----------------------------------------------------------------------------------------------------------------------------------

def test_la_pantalla_exige_sesion_y_empieza_sin_nada_aprobado(bo):
    assert bo.get("/reglas-laborales").status_code == 302
    entrar(bo)
    html = bo.get("/reglas-laborales").get_data(as_text=True)
    assert "Sin aprobar: no se genera nada" in html and html.count('class="tarjeta"') == 5 and "Cotizaciones a la Seguridad Social (TC)" in html


def test_guardar_y_aprobar_desde_la_pantalla(bo):
    entrar(bo)
    r = post(bo, "/reglas-laborales/tc", dia="9", mes_siguiente="1", nota="valor de prueba")
    assert r.status_code == 302 and rl.vigente("tc") is None
    html = bo.get("/reglas-laborales").get_data(as_text=True)
    assert "Borrador v1 pendiente" in html and "día 9 del mes siguiente al periodo" in html and "valor de prueba" in html
    assert post(bo, "/reglas-laborales/tc/1/aprobar").status_code == 302
    assert rl.vigente("tc")["aprobada_por"] == "jorge"
    assert "Vigente · v1" in bo.get("/reglas-laborales").get_data(as_text=True)


def test_un_error_de_validacion_se_muestra_y_no_guarda_nada(bo):
    entrar(bo)
    r = post(bo, "/reglas-laborales/tc", dia="99")
    assert r.status_code == 302 and "error=" in r.headers["Location"]
    assert "debe estar entre 1 y 31" in bo.get(r.headers["Location"]).get_data(as_text=True)
    assert rl.estado_de_todas()[0]["borrador"] is None


def test_sin_token_csrf_no_se_puede_guardar(bo):
    entrar(bo)
    assert bo.post("/reglas-laborales/tc", data={"dia": "9"}).status_code in (400, 403)
    assert rl.estado_de_todas()[0]["borrador"] is None


# --- Propuesta inicial como borrador -----------------------------------------------------------------------------------------------------------------

def test_las_propuestas_son_validas_y_cubren_todas_las_reglas():
    assert set(rl.PROPUESTAS) == set(rl.CLAVES)
    for clave, p in rl.PROPUESTAS.items():
        rl.validar(clave, p)
        assert p["nota"].startswith("Propuesta a verificar")


def test_cargar_las_propuestas_crea_borradores_y_no_aprueba_nada():
    assert sorted(rl.cargar_propuestas("jorge")) == sorted(rl.CLAVES)
    assert rl.vigentes() == {}, "ninguna regla queda aprobada: no se genera nada hasta que el propietario las apruebe"
    for r in rl.estado_de_todas():
        assert r["vigente"] is None and r["borrador"] is not None and r["borrador"]["version"] == 1 and r["borrador"]["nota"].startswith("Propuesta a verificar")
    tc = next(r for r in rl.estado_de_todas() if r["clave"] == "tc")["borrador"]
    assert (tc["dia"], tc["mes_siguiente"]) == (31, 1)


def test_cargar_de_nuevo_no_pisa_nada():
    rl.cargar_propuestas("jorge")
    rl.guardar_borrador("tc", "jorge", dia=9, mes_siguiente=1, nota="mi valor")
    rl.aprobar("m190", 1, "jorge")
    assert rl.cargar_propuestas("jorge") == []
    assert next(r for r in rl.estado_de_todas() if r["clave"] == "tc")["borrador"]["dia"] == 9
    assert rl.vigente("m190")["version"] == 1


def test_solo_se_cargan_las_que_no_tienen_ninguna_version():
    rl.guardar_borrador("baja_ss", "jorge", plazo=5, unidad="habiles")
    assert sorted(rl.cargar_propuestas("jorge")) == sorted(set(rl.CLAVES) - {"baja_ss"})
    assert next(r for r in rl.estado_de_todas() if r["clave"] == "baja_ss")["borrador"]["plazo"] == 5


def test_el_boton_de_la_pantalla_carga_borradores_sin_aprobar_y_luego_desaparece(bo):
    entrar(bo)
    assert "Cargar valores habituales como borrador" in bo.get("/reglas-laborales").get_data(as_text=True)
    assert post(bo, "/reglas-laborales/cargar-propuestas").status_code == 302
    html = bo.get("/reglas-laborales").get_data(as_text=True)
    assert rl.vigentes() == {} and html.count("Borrador v1 pendiente") == 5 and "Cargar valores habituales como borrador" not in html
    assert "día 31 del mes siguiente al periodo" in html and "31/1 del año siguiente al periodo" in html and "3 días naturales después del hecho" in html
    assert "1 día natural antes del hecho" in html and "10 días hábiles después del hecho" in html


def test_sin_token_csrf_no_se_cargan_las_propuestas(bo):
    entrar(bo)
    assert bo.post("/reglas-laborales/cargar-propuestas").status_code in (400, 403)
    assert rl.vigentes() == {} and all(r["borrador"] is None for r in rl.estado_de_todas())
