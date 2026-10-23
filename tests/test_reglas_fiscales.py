"""Catálogo global de reglas fiscales (app/reglas_fiscales.py, backoffice/rutas_reglas.py): sembrado desde el código, versiones y aprobación por el propietario."""
import pytest

from app import db, nucleo, reglas_fiscales as rf, vencimientos_fiscales as vf
from tests.test_backoffice_app import bo, entrar, post          # noqa: F401  (fixture y ayudas del backoffice)


def _propuestas(modelos, anio=2027):
    return vf.generar_vencimientos_propuestos(modelos, anio)


def test_el_sembrado_reproduce_exactamente_el_calendario_del_codigo():
    cat = rf.catalogo("ES")
    assert cat == vf.MODELOS_POR_PAIS["ES"]
    todos = list(vf.modelos_disponibles("ES"))
    assert set(todos) == {"303", "130", "111", "115", "390", "200"} and len(_propuestas(todos)) == 4 * 4 + 2
    conn = db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM reglas_fiscales WHERE aprobada = 1 AND origen = 'codigo' AND aprobada_por = ?", (rf.SEMBRADO_POR,)).fetchone()[0] == 6
    conn.close()


def test_el_sembrado_es_idempotente_y_no_pisa_lo_que_cambia_el_propietario():
    rf.guardar_borrador("ES", "303", "trimestral", "jorge", nombre="IVA", m1=4, d1=25, m2=7, d2=20, m3=10, d3=20, m4=1, d4=30)
    rf.aprobar("ES", "303", 2, "jorge")
    conn = db.get_connection(); rf._sembrar(conn); rf._sembrar(conn); conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM reglas_fiscales WHERE modelo = '303'").fetchone()[0] == 2
    conn.close()
    assert rf.catalogo("ES")["trimestrales"]["303"]["trimestres"][1] == (4, 25)


def test_un_borrador_no_se_aplica_hasta_aprobarlo_y_solo_cambia_lo_que_se_genera_despues():
    antes = {p["periodo"]: p["fecha_limite"] for p in _propuestas(["303"])}
    assert antes["2027-T1"] == "2027-04-20"
    v = rf.guardar_borrador("ES", "303", "trimestral", "jorge", nombre="IVA", m1=4, d1=22, m2=7, d2=20, m3=10, d3=20, m4=1, d4=30, nota="prueba")
    assert v == 2 and {p["periodo"]: p["fecha_limite"] for p in _propuestas(["303"])} == antes
    rf.aprobar("ES", "303", 2, "jorge")
    despues = {p["periodo"]: p["fecha_limite"] for p in _propuestas(["303"])}
    assert despues["2027-T1"] == "2027-04-22" and despues["2027-T4"] == "2028-01-30" and despues["2027-T2"] == antes["2027-T2"]


def test_reescribir_un_borrador_no_crea_versiones_y_no_se_aprueba_una_vieja():
    d = dict(nombre="IVA", m1=4, d1=21, m2=7, d2=20, m3=10, d3=20, m4=1, d4=30)
    assert rf.guardar_borrador("ES", "303", "trimestral", "a", **d) == 2 and rf.guardar_borrador("ES", "303", "trimestral", "a", **{**d, "d1": 23}) == 2
    rf.aprobar("ES", "303", 2, "a"); rf.aprobar("ES", "303", 2, "otro")
    conn = db.get_connection()
    assert conn.execute("SELECT aprobada_por FROM reglas_fiscales WHERE modelo = '303' AND version = 2").fetchone()[0] == "a"
    conn.execute("INSERT INTO reglas_fiscales (pais, modelo, version, nombre, tipo, fechas, aprobada, creada_en) VALUES ('ES', '303', 0, 'x', 'trimestral', '{}', 0, '2026-01-01')"); conn.commit(); conn.close()
    with pytest.raises(ValueError, match="más reciente"):
        rf.aprobar("ES", "303", 0, "a")
    with pytest.raises(ValueError, match="no existe"):
        rf.aprobar("ES", "303", 9, "a")


def test_un_modelo_nuevo_anual_aparece_al_aprobarlo_y_genera_su_fecha():
    assert "349" not in vf.modelos_disponibles("ES")
    rf.guardar_borrador("ES", "349", "anual", "jorge", nombre="Operaciones intracomunitarias", mes=1, dia=30, anio_siguiente="1")
    assert "349" not in vf.modelos_disponibles("ES")
    rf.aprobar("ES", "349", 1, "jorge")
    assert vf.modelos_disponibles("ES")["349"]["nombre"] == "Operaciones intracomunitarias"
    assert _propuestas(["349"]) == [{"modelo": "349", "periodo": "2027-anual", "fecha_limite": "2028-01-30"}]


def test_retirar_un_modelo_lo_quita_del_catalogo_sin_tocar_lo_ya_creado():
    t = db.crear_tenant("Despacho retirar"); c = db.crear_cliente_fiscal(t, "Cliente SL")
    existente = db.crear_vencimiento_fiscal(t, c, "115", "2026-T1", "2026-04-20")
    rf.guardar_borrador("ES", "115", "trimestral", "jorge", activa=False, nombre="Retenciones alquileres", m1=4, d1=20, m2=7, d2=20, m3=10, d3=20, m4=1, d4=20)
    assert "115" in vf.modelos_disponibles("ES")                 # el borrador no cuenta
    rf.aprobar("ES", "115", 2, "jorge")
    assert "115" not in vf.modelos_disponibles("ES") and _propuestas(["115"]) == [] and "111" in vf.modelos_disponibles("ES")
    assert db.obtener_vencimiento_fiscal(t, existente)["fecha_limite"].startswith("2026-04-20")


def test_la_generacion_de_un_cliente_usa_el_catalogo_aprobado():
    rf.guardar_borrador("ES", "303", "trimestral", "jorge", nombre="IVA", m1=4, d1=24, m2=7, d2=24, m3=10, d3=24, m4=1, d4=24)
    rf.aprobar("ES", "303", 2, "jorge")
    t = db.crear_tenant("Despacho cat"); c = db.crear_cliente_fiscal(t, "Cliente SL", modelos_fiscales=["303"])
    propuestas = nucleo.propuestas_vencimientos_ajustadas(t, ["303"], 2027)
    # el 24 cae en sábado (abril y julio), domingo (octubre) y lunes (enero): se pasa al siguiente día hábil
    assert [(p["periodo"], p["fecha_limite"]) for p in propuestas] == [("2027-T1", "2027-04-26"), ("2027-T2", "2027-07-26"), ("2027-T3", "2027-10-25"), ("2027-T4", "2028-01-24")]


@pytest.mark.parametrize("tipo,datos,fragmento", [
    ("trimestral", {"nombre": "x", "m1": 13, "d1": 1, "m2": 7, "d2": 1, "m3": 10, "d3": 1, "m4": 1, "d4": 1}, "Trimestre 1"),
    ("trimestral", {"nombre": "x", "m1": 4, "d1": 31, "m2": 7, "d2": 1, "m3": 10, "d3": 1, "m4": 1, "d4": 1}, "Trimestre 1"),
    ("trimestral", {"nombre": "x", "m1": 4, "d1": 1, "m2": 7, "d2": 1, "m3": 10, "d3": 1, "m4": 1}, "Trimestre 4"),
    ("anual", {"nombre": "x", "mes": 2, "dia": 29}, "Fecha límite"), ("anual", {"nombre": "x", "mes": "abc", "dia": 1}, "Fecha límite"),
    ("anual", {"nombre": " ", "mes": 1, "dia": 1}, "nombre"), ("mensual", {"nombre": "x"}, "Tipo")])
def test_validacion_de_fechas_y_nombres(tipo, datos, fragmento):
    with pytest.raises(ValueError, match=fragmento):
        rf.validar(tipo, datos)


@pytest.mark.parametrize("pais,modelo,fragmento", [("", "349", "país"), ("ESPAÑA", "349", "país"), ("ES", "", "código"), ("ES", "a b", "código"), ("ES", "x" * 13, "código")])
def test_pais_y_codigo_del_modelo_validos(pais, modelo, fragmento):
    with pytest.raises(ValueError, match=fragmento):
        rf.guardar_borrador(pais, modelo, "anual", "jorge", nombre="x", mes=1, dia=1)


def test_si_la_base_falla_el_calendario_sigue_con_los_valores_del_codigo(monkeypatch):
    monkeypatch.setattr(rf, "catalogo", lambda pais: (_ for _ in ()).throw(RuntimeError("tabla rota")))
    assert vf.modelos_disponibles("ES") == {**vf.MODELOS_POR_PAIS["ES"]["trimestrales"], **vf.MODELOS_POR_PAIS["ES"]["anuales"]}
    assert vf.modelos_disponibles("XX") == {} and vf.generar_vencimientos_propuestos(["303"], 2027, pais="XX") == []


def test_cada_cambio_queda_en_la_auditoria():
    rf.guardar_borrador("ES", "130", "trimestral", "jorge", nombre="IRPF", m1=4, d1=21, m2=7, d2=20, m3=10, d3=20, m4=1, d4=30)
    rf.aprobar("ES", "130", 2, "jorge")
    conn = db.get_connection()
    filas = conn.execute("SELECT accion, entidad_id, tenant_id FROM auditoria_eventos WHERE entidad = 'regla_fiscal' ORDER BY id").fetchall()
    conn.close()
    assert [(f["accion"], f["entidad_id"]) for f in filas] == [("regla_fiscal.borrador", "ES:130:2"), ("regla_fiscal.aprobada", "ES:130:2")] and all(not f["tenant_id"] for f in filas)


# --- Backoffice ----------------------------------------------------------------------------------------------------------------------------------

def test_la_pantalla_exige_sesion_y_lista_los_modelos_sembrados(bo):
    assert bo.get("/reglas-fiscales").status_code == 302
    entrar(bo)
    html = bo.get("/reglas-fiscales").get_data(as_text=True)
    assert html.count('class="tarjeta"') >= 7 and "ES · 303" in html and "Retenciones IRPF" in html and "nada cambia hasta que edites algo" in html


def test_guardar_y_aprobar_desde_el_backoffice_cambia_el_calendario(bo):
    entrar(bo)
    r = post(bo, "/reglas-fiscales/guardar", pais="ES", modelo="303", tipo="trimestral", nombre="IVA - Declaración trimestral", m1="4", d1="27", m2="7", d2="20", m3="10", d3="20", m4="1", d4="30", activa="1", nota="prueba")
    assert r.status_code == 302 and "error" not in r.headers["Location"]
    assert _propuestas(["303"])[0]["fecha_limite"] == "2027-04-20"
    html = bo.get("/reglas-fiscales").get_data(as_text=True)
    assert "Borrador v2 pendiente" in html and "T1: 27/4" in html
    assert post(bo, "/reglas-fiscales/ES/303/2/aprobar").status_code == 302
    assert _propuestas(["303"])[0]["fecha_limite"] == "2027-04-27" and "Vigente · v2" in bo.get("/reglas-fiscales").get_data(as_text=True)


def test_el_backoffice_muestra_los_errores_y_crea_modelos_nuevos(bo):
    entrar(bo)
    r = post(bo, "/reglas-fiscales/guardar", pais="ES", modelo="349", tipo="anual", nombre="Intracomunitarias", mes="2", dia="30", activa="1")
    assert "error=" in r.headers["Location"] and "existan en ese mes" in bo.get(r.headers["Location"]).get_data(as_text=True)
    post(bo, "/reglas-fiscales/guardar", pais="ES", modelo="349", tipo="anual", nombre="Intracomunitarias", mes="1", dia="30", anio_siguiente="1", activa="1")
    post(bo, "/reglas-fiscales/ES/349/1/aprobar")
    assert "349" in vf.modelos_disponibles("ES")
    assert "error=" in post(bo, "/reglas-fiscales/ES/349/7/aprobar").headers["Location"]


def test_sin_token_csrf_no_se_puede_guardar(bo):
    entrar(bo)
    assert bo.post("/reglas-fiscales/guardar", data={"pais": "ES", "modelo": "349", "tipo": "anual"}).status_code in (400, 403)
