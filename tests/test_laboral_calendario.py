"""Calendario laboral por cliente (app/laboral.py:propuestas_laborales/generar_laborales): TC y 190 solo con reglas aprobadas y trabajadores de alta. Reglas ficticias."""
from datetime import date

from app import db, laboral, reglas_laborales as rl
from tests.test_laboral import _con_cliente, _despacho


def _aprobar_tc(dia=9, mes_siguiente=1):
    rl.guardar_borrador("tc", "jorge", dia=str(dia), mes_siguiente=str(mes_siguiente))
    rl.aprobar("tc", 1, "jorge")


def _modelos(t, c):
    conn = db.get_connection()
    filas = conn.execute("SELECT modelo, periodo, fecha_limite FROM vencimientos_fiscales WHERE tenant_id = ? AND cliente_fiscal_id = ? AND papelera_en IS NULL", (t, c)).fetchall()
    conn.close()
    return filas


def test_sin_reglas_aprobadas_no_se_genera_nada_aunque_haya_trabajadores():
    t, u, c = _despacho()
    laboral.crear(t, u, c, "Ana")
    assert laboral.propuestas_laborales(t, c, 2027) == [] and laboral.generar_laborales(t, c) == 0 and _modelos(t, c) == []


def test_una_regla_sin_aprobar_tampoco_genera():
    t, u, c = _despacho()
    laboral.crear(t, u, c, "Ana")
    rl.guardar_borrador("tc", "jorge", dia="9")
    assert laboral.propuestas_laborales(t, c, 2027) == []


def test_sin_trabajadores_de_alta_no_se_genera_nada():
    t, u, c = _despacho()
    _aprobar_tc()
    assert laboral.generar_laborales(t, c) == 0
    laboral.crear(t, u, c, "Ana", fecha_alta="2020-01-01", fecha_baja="2021-01-01")
    assert laboral.generar_laborales(t, c) == 0 and _modelos(t, c) == []


def test_con_regla_aprobada_y_trabajador_de_alta_se_crean_los_tc_y_es_idempotente():
    t, u, c = _despacho()
    _aprobar_tc()
    laboral.crear(t, u, c, "Ana")
    n = laboral.generar_laborales(t, c)
    filas = _modelos(t, c)
    assert n == 24 and len(filas) == 24 and {f["modelo"] for f in filas} == {"TC"}
    assert laboral.generar_laborales(t, c) == 0 and len(_modelos(t, c)) == 24
    anio = date.today().year
    assert any(f["periodo"] == f"{anio}-03" for f in filas)


def test_el_190_se_genera_con_su_regla_y_las_fechas_caen_en_dia_habil():
    t, u, c = _despacho()
    rl.guardar_borrador("m190", "jorge", dia="31", mes="1", anio_siguiente="1"); rl.aprobar("m190", 1, "jorge")
    laboral.crear(t, u, c, "Ana")
    laboral.generar_laborales(t, c)
    filas = _modelos(t, c)
    assert {f["modelo"] for f in filas} == {"190"} and len(filas) == 2
    assert all(date.fromisoformat(f["fecha_limite"]).weekday() < 5 for f in filas)


def test_la_generacion_del_cliente_incluye_lo_laboral_aunque_no_tenga_modelos_fiscales():
    t, u, c = _despacho()
    _aprobar_tc()
    laboral.crear(t, u, c, "Ana")
    conn = db.get_connection()
    fila = conn.execute("SELECT * FROM clientes_fiscales WHERE id = ?", (c,)).fetchone()
    conn.close()
    assert db.generar_vencimientos_de_cliente(fila) == 24 and db.generar_vencimientos_de_cliente(fila) == 0


def test_el_boton_de_la_pestana_solo_aparece_con_reglas_y_trabajadores_y_crea_lo_laboral(cliente):
    uid, t, fid, cid = _con_cliente(cliente, "lab-cal@ejemplo.com")
    url = f"/clientes/{cid}?pestana=laboral"
    laboral.crear(t, uid, fid, "Ana")
    assert "Añadir los vencimientos laborales" not in cliente.get(url).get_data(as_text=True)
    _aprobar_tc()
    assert "Añadir los vencimientos laborales" in cliente.get(url).get_data(as_text=True)
    assert cliente.post(f"/fiscal/clientes/{fid}/laboral/vencimientos").status_code == 302 and len(_modelos(t, fid)) == 24


# --- Plazos que nacen de un hecho del trabajador (7d) -----------------------------------------------------------------------------------------

def _regla_hecho(clave, plazo, unidad):
    rl.guardar_borrador(clave, "jorge", plazo=str(plazo), unidad=unidad)
    rl.aprobar(clave, 1, "jorge")


def _de(t, c, modelo):
    return [f for f in _modelos(t, c) if f["modelo"] == modelo]


def _futuro(dias):
    from datetime import timedelta
    return (date.today() + timedelta(days=dias)).isoformat()


def test_sin_regla_aprobada_un_alta_no_crea_plazo():
    t, u, c = _despacho()
    laboral.crear(t, u, c, "Ana", fecha_alta=_futuro(10))
    assert _modelos(t, c) == []


def test_con_regla_aprobada_el_alta_crea_su_plazo_sin_nombre_y_enlazado_al_trabajador():
    t, u, c = _despacho()
    _regla_hecho("alta_ss", 30, "naturales")
    w = laboral.crear(t, u, c, "Ana Ruiz", fecha_alta=_futuro(10))
    (v,) = _de(t, c, "ALTA-SS")
    assert v["periodo"] == f"T{w}-alta" and "Ana" not in str(dict(v))
    conn = db.get_connection()
    assert conn.execute("SELECT trabajador_id FROM vencimientos_fiscales WHERE modelo = 'ALTA-SS'").fetchone()[0] == w
    conn.close()
    assert date.fromisoformat(v["fecha_limite"]).weekday() < 5
    assert [p["modelo"] for p in laboral.listar(t, c)[0]["plazos"]] == ["ALTA-SS"]


def test_el_plazo_antes_del_hecho_retrocede_al_dia_habil_anterior():
    from app import calendario_plazos as cp
    cal = cp.calendario_general((2027,))
    # 2027-03-09 es martes; 2 días naturales antes = domingo 7 → viernes 5
    assert laboral.plazo_desde_hecho({"plazo": -2, "unidad": "naturales"}, date(2027, 3, 9), cal) == date(2027, 3, 5)
    assert laboral.plazo_desde_hecho({"plazo": 2, "unidad": "naturales"}, date(2027, 3, 5), cal) == date(2027, 3, 8)       # sábado 7 → lunes 8
    assert laboral.plazo_desde_hecho({"plazo": 3, "unidad": "habiles"}, date(2027, 3, 5), cal) == date(2027, 3, 10)
    assert laboral.plazo_desde_hecho({"plazo": -1, "unidad": "habiles"}, date(2027, 3, 8), cal) == date(2027, 3, 5)


def test_cambiar_la_fecha_actualiza_el_plazo_pendiente_pero_no_el_presentado():
    t, u, c = _despacho()
    _regla_hecho("alta_ss", 5, "naturales")
    w = laboral.crear(t, u, c, "Ana", fecha_alta=_futuro(10))
    antes = _de(t, c, "ALTA-SS")[0]["fecha_limite"]
    laboral.editar(t, w, fecha_alta=_futuro(40))
    despues = _de(t, c, "ALTA-SS")
    assert len(despues) == 1 and despues[0]["fecha_limite"] > antes
    conn = db.get_connection()
    conn.execute("UPDATE vencimientos_fiscales SET estado = 'presentado' WHERE modelo = 'ALTA-SS'"); conn.commit(); conn.close()
    fijada = _de(t, c, "ALTA-SS")[0]["fecha_limite"]
    laboral.editar(t, w, fecha_alta=_futuro(80))
    assert _de(t, c, "ALTA-SS")[0]["fecha_limite"] == fijada


def test_borrar_la_fecha_o_al_trabajador_manda_el_plazo_pendiente_a_la_papelera():
    t, u, c = _despacho()
    _regla_hecho("baja_ss", 3, "habiles")
    w = laboral.crear(t, u, c, "Ana", fecha_baja=_futuro(10))
    assert len(_de(t, c, "BAJA-SS")) == 1
    laboral.editar(t, w, fecha_baja="")
    assert _de(t, c, "BAJA-SS") == []
    laboral.editar(t, w, fecha_baja=_futuro(10))
    assert len(_de(t, c, "BAJA-SS")) == 1
    laboral.eliminar(t, w)
    assert _de(t, c, "BAJA-SS") == []


def test_un_hecho_antiguo_no_crea_plazos_ya_vencidos_y_el_contrato_sale_de_la_fecha_de_alta():
    t, u, c = _despacho()
    _regla_hecho("alta_ss", 5, "naturales"); _regla_hecho("contrato", 10, "naturales")
    laboral.crear(t, u, c, "Antigua", fecha_alta="2019-01-10")
    assert _modelos(t, c) == []
    w = laboral.crear(t, u, c, "Nueva", fecha_alta=_futuro(20))
    assert {f["modelo"] for f in _modelos(t, c)} == {"ALTA-SS", "CONTRATO"} and {f["periodo"] for f in _modelos(t, c)} == {f"T{w}-alta", f"T{w}-contrato"}


def test_el_boton_tambien_pone_al_dia_los_plazos_de_los_trabajadores_existentes():
    t, u, c = _despacho()
    w = laboral.crear(t, u, c, "Ana", fecha_alta=_futuro(10))
    assert _modelos(t, c) == []
    _regla_hecho("alta_ss", 5, "naturales")
    assert laboral.generar_laborales(t, c) == 1 and laboral.generar_laborales(t, c) == 0
    assert _de(t, c, "ALTA-SS")[0]["periodo"] == f"T{w}-alta"


# --- Nóminas: recordatorio mensual y seguimiento (7e) -----------------------------------------------------------------------------------------



def test_el_recordatorio_de_nominas_empieza_desactivado_y_no_genera_nada():
    t, u, c = _despacho()
    laboral.crear(t, u, c, "Ana")
    assert laboral.config(t) == {"dia": None, "activo": False} and laboral.generar_laborales(t, c) == 0 and _modelos(t, c) == []


def test_con_el_recordatorio_activado_se_crea_un_vencimiento_nominas_al_mes_sin_reglas_legales(monkeypatch):
    t, u, c = _despacho()
    monkeypatch.setattr("app.acceso.es_directivo", lambda uid: True)
    laboral.guardar_config(t, u, dia="25", activo=True)
    assert laboral.config(t) == {"dia": 25, "activo": True}
    assert laboral.generar_laborales(t, c) == 0                                   # sin trabajadores de alta no hay nada que recordar
    laboral.crear(t, u, c, "Ana")
    assert laboral.generar_laborales(t, c) == 24 and {f["modelo"] for f in _modelos(t, c)} == {"NOMINAS"}
    assert laboral.generar_laborales(t, c) == 0


def test_la_configuracion_se_valida_y_solo_la_cambia_la_direccion(monkeypatch):
    import pytest
    t, u, c = _despacho()
    with pytest.raises(ValueError, match="dirección"):
        laboral.guardar_config(t, u, dia="5", activo=True)
    monkeypatch.setattr("app.acceso.es_directivo", lambda uid: True)
    for dia, fragmento in (("0", "entre 1 y 31"), ("32", "entre 1 y 31"), ("x", "número"), ("", "indica el día")):
        with pytest.raises(ValueError, match=fragmento):
            laboral.guardar_config(t, u, dia=dia, activo=True)
    laboral.guardar_config(t, u, dia="", activo=False)                            # desactivar sin día es válido
    assert laboral.config(t)["activo"] is False


def test_el_seguimiento_de_nominas_avanza_por_estados_y_sugiere_presentar_al_enviar_todas():
    import pytest
    t, u, c = _despacho()
    a = laboral.crear(t, u, c, "Ana"); b = laboral.crear(t, u, c, "Berta")
    laboral.crear(t, u, c, "Baja", fecha_alta="2020-01-01", fecha_baja="2021-01-01")
    p = laboral.periodo_actual()
    m = laboral.seguimiento_nominas(t, c, p)
    assert [f["estado"] for f in m["filas"]] == ["pendiente", "pendiente"] and m["filas"][0]["siguiente"] == "generada" and m["filas"][0]["anterior"] is None
    laboral.fijar_estado_nomina(t, u, a, p, "enviada")
    assert laboral.seguimiento_nominas(t, c, p)["todas_enviadas"] is False
    laboral.fijar_estado_nomina(t, u, b, p, "firmada")
    laboral.fijar_estado_nomina(t, u, a, p, "firmada"); laboral.fijar_estado_nomina(t, u, a, p, "enviada")       # reescribir no duplica
    m = laboral.seguimiento_nominas(t, c, p)
    assert m["todas_enviadas"] is True and m["sugerir_presentado"] is False            # sin vencimiento NOMINAS del mes no hay nada que presentar
    db.crear_vencimiento_fiscal(t, c, "NOMINAS", p, _futuro(5))
    assert laboral.seguimiento_nominas(t, c, p)["sugerir_presentado"] is True
    for malo in ("inventado", ""):
        with pytest.raises(ValueError, match="Estado"):
            laboral.fijar_estado_nomina(t, u, a, p, malo)
    with pytest.raises(ValueError, match="Periodo"):
        laboral.fijar_estado_nomina(t, u, a, "2027-13", "generada")
    with pytest.raises(ValueError, match="no encontrado"):
        laboral.fijar_estado_nomina(t, u, 99999, p, "generada")


def test_las_nominas_se_siguen_desde_la_pestana_y_no_se_guarda_ningun_importe(cliente):
    uid, t, fid, cid = _con_cliente(cliente, "lab-nom@ejemplo.com")
    w = laboral.crear(t, uid, fid, "Ana")
    html = cliente.get(f"/clientes/{cid}?pestana=laboral").get_data(as_text=True)
    assert "Nóminas de" in html and "Solo seguimiento" in html
    r = cliente.post(f"/fiscal/clientes/{fid}/laboral/nominas/{w}", data={"periodo": laboral.periodo_actual(), "estado": "generada"})
    assert r.status_code == 302 and laboral.seguimiento_nominas(t, fid, laboral.periodo_actual())["filas"][0]["estado"] == "generada"
    r = cliente.post(f"/fiscal/clientes/{fid}/laboral/nominas/{w}", data={"periodo": laboral.periodo_actual(), "estado": "inventado"})
    assert "error=" in r.headers["Location"]
    conn = db.get_connection()
    columnas = {f["name"] for f in conn.execute("PRAGMA table_info(nominas_seguimiento)")}
    conn.close()
    assert not columnas & {"importe", "salario", "bruto", "neto"}


def test_las_nominas_se_borran_con_el_trabajador():
    t, u, c = _despacho()
    w = laboral.crear(t, u, c, "Ana")
    laboral.fijar_estado_nomina(t, u, w, laboral.periodo_actual(), "generada")
    conn = db.get_connection()
    conn.execute("DELETE FROM trabajadores_cliente WHERE id = ?", (w,)); conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM nominas_seguimiento").fetchone()[0] == 0
    conn.close()
