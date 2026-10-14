"""Perfil fiscal de la gestoría (app/perfil_fiscal.py): modelos deducidos, fechas desplazadas y semáforo."""
from datetime import date

from app import calendario_plazos as cp
from app import db, nucleo, perfil_fiscal as pf
from tests.conftest import iniciar_sesion_de_prueba


def test_perfil_limpio_descarta_lo_desconocido():
    assert pf.perfil_limpio("raro", ["iva", "x"]) == {"tipo": "particular", "atributos": ["iva"]}
    assert pf.perfil_limpio("autonomo", ["retenciones", "iva"])["atributos"] == ["iva", "retenciones"]


def test_modelos_de_un_autonomo_y_de_una_sociedad():
    aut = [m["modelo"] for m in pf.modelos_para_perfil(pf.perfil_limpio("autonomo", ["iva", "estimacion_directa", "retenciones", "alquiler_local"]))]
    assert aut == ["303", "390", "130", "111", "115"]
    soc = [m["modelo"] for m in pf.modelos_para_perfil(pf.perfil_limpio("sociedad", ["iva"]))]
    assert soc == ["303", "390", "200"]
    assert pf.modelos_para_perfil(pf.perfil_limpio("particular", [])) == []
    assert pf.modelos_para_perfil(None) == []


def test_estimacion_directa_solo_vale_para_autonomos():
    assert pf.modelos_para_perfil(pf.perfil_limpio("sociedad", ["estimacion_directa"]))[0]["modelo"] == "200"
    assert all(m["motivo"] for m in pf.modelos_para_perfil(pf.perfil_limpio("autonomo", ["iva"])))


def test_fecha_que_cae_en_inhabil_pasa_al_siguiente_habil():
    cal = cp.calendario_general([2026])
    res = pf.ajustar_a_calendario([{"fecha_limite": "2026-04-04"}, {"fecha_limite": "2026-10-20"}], cal)
    assert res[0]["fecha_limite"] == "2026-04-06" and res[0]["fecha_original"] == "2026-04-04"
    assert res[1]["fecha_limite"] == "2026-10-20" and "fecha_original" not in res[1]


def test_semaforo():
    hoy = date(2026, 10, 12)
    assert pf.semaforo([], hoy)["estado"] == "sin_obligaciones"
    assert pf.semaforo([{"estado": "pendiente", "fecha_limite": "2026-10-01"}], hoy)["estado"] == "atrasado"
    assert pf.semaforo([{"estado": "pendiente", "fecha_limite": "2026-10-15"}], hoy)["estado"] == "proximo"
    assert pf.semaforo([{"estado": "pendiente", "fecha_limite": "2026-12-15"}], hoy)["estado"] == "al_dia"
    assert pf.semaforo([{"estado": "presentado", "fecha_limite": "2026-10-01"}], hoy)["estado"] == "al_dia"
    mixto = [{"estado": "presentado", "fecha_limite": "2026-01-01"}, {"estado": "pendiente", "fecha_limite": "2026-10-01"}, {"estado": "pendiente", "fecha_limite": "2026-10-14"}]
    assert pf.semaforo(mixto, hoy) == {"estado": "atrasado", "atrasados": 1, "proximos": 1, "pendientes": 2}


def _despacho(cliente, correo):
    uid = iniciar_sesion_de_prueba(cliente, correo, "contrasena123")
    tid = db.crear_tenant("Gestoría perfil")
    db.asignar_tenant(uid, tid)
    return tid


def test_propuestas_del_despacho_respetan_sus_festivos():
    tid = db.crear_tenant("Festivos propios")
    base = nucleo.propuestas_vencimientos_ajustadas(tid, ["303"], 2026)
    assert [p["fecha_limite"] for p in base][:2] == ["2026-04-20", "2026-07-20"]
    nucleo.anadir_festivo(tid, "2026-04-20", "Patrón local")
    mod = nucleo.propuestas_vencimientos_ajustadas(tid, ["303"], 2026)
    assert mod[0]["fecha_limite"] == "2026-04-21" and mod[0]["fecha_original"] == "2026-04-20"


def test_guardar_perfil_y_aplicarlo_a_los_modelos(cliente):
    tid = _despacho(cliente, "perfil-guardar@ejemplo.com")
    cid = db.crear_cliente_fiscal(tid, "Taller Mecánico SL")
    resp = cliente.post(f"/fiscal/clientes/{cid}/editar", data={
        "nombre": "Taller Mecánico SL", "pais": "ES", "perfil_tipo": "sociedad", "perfil_atributos": ["iva", "retenciones"], "aplicar_perfil": "1",
    })
    assert resp.status_code == 302
    fila = db.obtener_cliente_fiscal(tid, cid)
    assert db.perfil_fiscal_de_cliente(fila) == {"tipo": "sociedad", "atributos": ["iva", "retenciones"]}
    assert db.modelos_fiscales_de_cliente(fila) == ["303", "390", "111", "200"]
    html = cliente.get(f"/fiscal/clientes/{cid}/editar").get_data(as_text=True)
    assert "Sociedad: Impuesto sobre Sociedades anual" in html


def test_sin_aplicar_el_perfil_no_toca_los_modelos(cliente):
    tid = _despacho(cliente, "perfil-sin-aplicar@ejemplo.com")
    cid = db.crear_cliente_fiscal(tid, "Cliente X", modelos_fiscales=["115"])
    cliente.post(f"/fiscal/clientes/{cid}/editar", data={"nombre": "Cliente X", "pais": "ES", "perfil_tipo": "autonomo", "perfil_atributos": ["iva"], "modelos_fiscales": ["115"]})
    assert db.modelos_fiscales_de_cliente(db.obtener_cliente_fiscal(tid, cid)) == ["115"]


def test_generar_parte_del_perfil_si_no_hay_modelos_guardados(cliente):
    tid = _despacho(cliente, "perfil-generar@ejemplo.com")
    cid = db.crear_cliente_fiscal(tid, "Cliente Y")
    cliente.post(f"/fiscal/clientes/{cid}/editar", data={"nombre": "Cliente Y", "pais": "ES", "perfil_tipo": "autonomo", "perfil_atributos": ["estimacion_directa"]})
    html = cliente.get(f"/fiscal/clientes/{cid}/generar-vencimientos?anio=2026").get_data(as_text=True)
    assert "130 — 2026-T1" in html and "303 — 2026-T1" not in html


def test_lista_de_clientes_muestra_y_filtra_el_semaforo(cliente):
    tid = _despacho(cliente, "perfil-semaforo@ejemplo.com")
    atrasado = db.crear_cliente_fiscal(tid, "Cliente Atrasado")
    limpio = db.crear_cliente_fiscal(tid, "Cliente Limpio")
    db.crear_vencimiento_fiscal(tid, atrasado, "303", "2020-T1", "2020-04-20")
    html = cliente.get("/fiscal/clientes").get_data(as_text=True)
    assert "Atrasado · 1" in html
    solo = cliente.get("/fiscal/clientes?estado=atrasado").get_data(as_text=True)
    assert "Cliente Atrasado" in solo and "Cliente Limpio" not in solo
    sin = cliente.get("/fiscal/clientes?estado=sin_obligaciones").get_data(as_text=True)
    assert "Cliente Limpio" in sin and "Cliente Atrasado" not in sin
    assert limpio


# --- Informe mensual y capa común de informes -------------------------------------------------------------------------------------------------------
def test_datos_del_informe_mensual():
    from app import informe_cliente as ic
    hoy = date(2026, 10, 12)
    venc = [
        {"modelo": "303", "periodo": "2026-T3", "fecha_limite": "2026-10-05", "estado": "presentado"},
        {"modelo": "130", "periodo": "2026-T3", "fecha_limite": "2026-09-20", "estado": "presentado"},   # otro mes
        {"modelo": "111", "periodo": "2026-T2", "fecha_limite": "2026-07-20", "estado": "pendiente"},   # atrasado
        {"modelo": "115", "periodo": "2026-T3", "fecha_limite": "2026-10-20", "estado": "pendiente"},   # próximo
        {"modelo": "200", "periodo": "2026-anual", "fecha_limite": "2027-07-25", "estado": "pendiente"},  # lejos
    ]
    d = ic.datos_informe(venc, 2026, 10, hoy)
    assert [v["modelo"] for v in d["presentados"]] == ["303"]
    assert [v["modelo"] for v in d["atrasados"]] == ["111"]
    assert [v["modelo"] for v in d["proximos"]] == ["115"]


def test_capa_comun_de_pdf_cabecera_paginas_y_acentos():
    from app import informes
    pdf = informes.construir_pdf("Informe de prueba", [("seccion", "Dades"), ("parrafo", "l·l ç à è œ — <b>no es negrita</b>"), ("claves", [("Clau", "Valor")]),
                                                      ("tabla", ["A", "B"], [["x" * 400, None]] * 80)], despacho="Gestoria Çà & Co")
    assert pdf.startswith(b"%PDF")
    import re
    paginas = len(re.findall(rb"/Type /Page\b", pdf))
    assert paginas >= 2


def test_pdf_informe_mensual_via_ruta(cliente):
    tid = _despacho(cliente, "perfil-informe@ejemplo.com")
    cid = db.crear_cliente_fiscal(tid, "Cliente Informe")
    db.crear_vencimiento_fiscal(tid, cid, "303", "2020-T1", "2020-04-20")
    resp = cliente.get(f"/fiscal/clientes/{cid}/informe-mensual.pdf?mes=2026-10")
    assert resp.status_code == 200 and resp.mimetype == "application/pdf" and resp.data.startswith(b"%PDF")
    assert cliente.get(f"/fiscal/clientes/{cid}/informe-mensual.pdf?mes=2026-13").status_code == 400
    assert cliente.get("/fiscal/clientes/99999/informe-mensual.pdf").status_code == 404
    assert "Informe mensual (PDF)" in cliente.get(f"/fiscal/clientes/{cid}", follow_redirects=True).get_data(as_text=True)


def test_informe_mensual_de_otro_despacho_da_404(cliente):
    otro = db.crear_tenant("Otro despacho")
    ajeno = db.crear_cliente_fiscal(otro, "Ajeno")
    _despacho(cliente, "perfil-ajeno@ejemplo.com")
    assert cliente.get(f"/fiscal/clientes/{ajeno}/informe-mensual.pdf").status_code == 404
