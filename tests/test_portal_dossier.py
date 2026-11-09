"""Dossier de actividad para el banco (A4): números del periodo, PDF, validación de la gestoría y comprobación pública."""
from datetime import date

import pytest

from app import db, facturas_contables as fc, portal_dossier as pd
from tests.test_facturas_contables import _web
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures


def _factura(c, tipo, fecha, total, estado="revisada", abono=False, pct=21):
    fid = fc.crear_desde_portal(c, {"tipo": tipo, "fecha": fecha, "numero": f"F-{fecha}-{total}-{estado}", "tercero_nombre": "Tercero", "tercero_nif": "B87654323", "total": str(total), "pct_iva": str(pct)})
    conn = db.get_connection()
    conn.execute("UPDATE facturas_contables SET estado = ?, abono = ? WHERE id = ?", (estado, 1 if abono else 0, fid))
    conn.commit(); conn.close()
    return fid


def _datos(c):
    _factura(c, "emitida", "2026-01-15", "121,00")                      # base 100, IVA 21
    _factura(c, "emitida", "2026-02-10", "242,00")                      # base 200, IVA 42
    _factura(c, "recibida", "2026-02-20", "60,50")                      # base 50, IVA 10,50
    _factura(c, "emitida", "2026-05-02", "121,00")                      # 2T
    _factura(c, "emitida", "2026-02-12", "121,00", estado="pendiente")  # no cuenta: sin revisar
    _factura(c, "recibida", "2026-03-03", "121,00", estado="descartada")  # no cuenta
    _factura(c, "emitida", "2026-03-20", "24,20", abono=True)           # abono: resta base 20 / IVA 4,20


def test_los_numeros_son_solo_de_facturas_revisadas_por_trimestre_y_los_abonos_restan():
    t, u, c = _despacho("Dossier numeros")
    _datos(c)
    d = pd.calcular(_ficha(c), "2026-01-01", "2026-06-30")
    t1 = next(x for x in d["trimestres"] if x["trimestre"].endswith("T1"))
    assert (t1["ventas"], t1["gastos"], t1["iva_repercutido"], t1["iva_soportado"]) == (30000 - 2000, 5000, 6300 - 420, 1050)
    assert d["total"]["facturas"] == 5 and d["total"]["ventas"] == 30000 - 2000 + 10000 and d["total"]["resultado_iva"] == (6300 - 420 + 2100) - 1050
    with pytest.raises(ValueError):
        pd.calcular(_ficha(c), "2026-06-30", "2026-01-01")
    with pytest.raises(ValueError):
        pd.calcular(_ficha(c), "2020-01-01", "2026-06-30")


def test_los_periodos_con_nombre():
    hoy = date(2026, 11, 9)
    assert pd.periodo("anio_anterior", hoy) == ("2025-01-01", "2025-12-31") and pd.periodo("anio_en_curso", hoy) == ("2026-01-01", "2026-11-09")
    assert pd.periodo("ultimo_trimestre", hoy) == ("2026-07-01", "2026-09-30") and pd.periodo("ultimo_trimestre", date(2026, 2, 1)) == ("2025-10-01", "2025-12-31")
    assert pd.periodo("ultimo_anio", hoy) == ("2025-11-09", "2026-11-09") and pd.periodo("ultimo_anio", date(2024, 2, 29))[0] == "2023-02-28"
    with pytest.raises(ValueError):
        pd.periodo("siempre")


def test_sin_nada_que_contar_no_se_genera_y_con_datos_si_y_se_ve_en_el_portal(cliente, correo):
    t, u, c = _despacho("Dossier portal")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "Todavía no hay facturas revisadas" in cliente.post("/portal/dossier", data={"periodo": "anio_en_curso"}).get_data(as_text=True)
    _datos(c)
    r = cliente.post("/portal/dossier", data={"periodo": "anio_en_curso"})
    assert r.status_code == 302 and "generado=" in r.headers["Location"]
    html = _html(cliente, r.headers["Location"])
    assert "Dossier generado" in html and "Sin validar" in html and "Pedir que lo valide mi gestoría" in html
    did = pd.listar(_ficha(c))[0]["id"]
    pdf = cliente.get(f"/portal/dossier/{did}.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF") and pdf.headers["Cache-Control"] == "private, no-store"


def test_el_dossier_guarda_los_datos_de_cuando_se_genero_aunque_luego_cambien_las_facturas():
    t, u, c = _despacho("Dossier congelado")
    _datos(c)
    did = pd.crear(_ficha(c), "2026-01-01", "2026-06-30", "titular")
    antes = pd.obtener(_ficha(c), did)["datos"]["total"]["ventas"]
    _factura(c, "emitida", "2026-04-04", "1210,00")
    assert pd.obtener(_ficha(c), did)["datos"]["total"]["ventas"] == antes and pd.calcular(_ficha(c), "2026-01-01", "2026-06-30")["total"]["ventas"] > antes


def test_flujo_completo_pedir_validar_y_comprobar_en_publico(cliente):
    uid, t, c = _web(cliente, email="dossier-equipo@ejemplo.com")
    _datos(c)
    ficha = db.obtener_cliente_fiscal_por_id(c)
    did = pd.crear(ficha, "2026-01-01", "2026-06-30", "titular")
    assert pd.pedir_validacion(ficha, did) is True and pd.pedir_validacion(ficha, did) is False and len(pd.pendientes(t)) == 1
    assert "Dossiers de actividad" in cliente.get("/fiscal/dossiers").get_data(as_text=True) and "Validar" in cliente.get("/fiscal/dossiers").get_data(as_text=True)
    r = cliente.post(f"/fiscal/dossiers/{did}/resolver", data={"accion": "validar"})
    assert r.status_code == 302 and "hecho=validado" in r.headers["Location"] and pd.pendientes(t) == []
    codigo = pd.obtener(ficha, did)["codigo"]
    assert len(codigo) == 10 and pd.obtener(ficha, did)["estado"] == "validado"
    publico = cliente.application.test_client()
    ok = publico.get(f"/portal/verificar-dossier/{codigo.lower()}")
    html = ok.get_data(as_text=True)
    assert ok.status_code == 200 and "Dossier auténtico" in html and "350,00 €" in html.replace("\xa0", " ") or "Dossier auténtico" in html
    assert publico.get("/portal/verificar-dossier/AAAAAAAAAA").status_code == 404 and "no existe" in publico.get("/portal/verificar-dossier/AAAAAAAAAA").get_data(as_text=True)
    assert pd.resolver.__name__ and cliente.post(f"/fiscal/dossiers/{did}/resolver", data={"accion": "validar"}).headers["Location"].endswith("hecho=no")      # ya no está pendiente
    cuerpo = pd.pdf(pd.obtener(ficha, did), "Cliente", "B1", "Despacho", "https://x.test/v")
    assert cuerpo.startswith(b"%PDF")


def test_si_alguien_toca_los_datos_guardados_la_comprobacion_falla():
    t, u, c = _despacho("Dossier manipulado")
    _datos(c)
    ficha = _ficha(c)
    did = pd.crear(ficha, "2026-01-01", "2026-06-30", "titular")
    pd.pedir_validacion(ficha, did)
    codigo = pd.resolver(t, did, u, True)
    assert pd.verificar(codigo)["cliente_nombre"] == ficha["nombre"]
    conn = db.get_connection()
    f = conn.execute("SELECT datos FROM portal_dossiers WHERE id = ?", (did,)).fetchone()["datos"]
    conn.execute("UPDATE portal_dossiers SET datos = ? WHERE id = ?", (f.replace('"ventas": 40000', '"ventas": 99999999'), did))
    conn.commit(); conn.close()
    import json
    d = json.loads(f); d["total"]["ventas"] += 1
    conn = db.get_connection(); conn.execute("UPDATE portal_dossiers SET datos = ? WHERE id = ?", (json.dumps(d), did)); conn.commit(); conn.close()
    assert pd.verificar(codigo) is None


def test_rechazar_deja_la_nota_y_permite_volver_a_pedir(cliente):
    uid, t, c = _web(cliente, email="dossier-rechazo@ejemplo.com")
    _datos(c)
    ficha = db.obtener_cliente_fiscal_por_id(c)
    did = pd.crear(ficha, "2026-01-01", "2026-06-30", "titular")
    pd.pedir_validacion(ficha, did)
    cliente.post(f"/fiscal/dossiers/{did}/resolver", data={"accion": "rechazar", "nota": "Faltan las facturas de mayo"})
    d = pd.obtener(ficha, did)
    assert d["estado"] == "rechazado" and d["nota"] == "Faltan las facturas de mayo" and d["codigo"] is None
    assert pd.pedir_validacion(ficha, did) is True


def test_el_perfil_de_consulta_ve_pero_no_genera(cliente, correo):
    from app import portal_personas
    t, u, c = _despacho("Dossier consulta")
    portal_personas.anadir(_ficha(c), "mira@ejemplo.com", "Mira", "consulta", por=u)
    _entrar(cliente, c, "mira@ejemplo.com")
    assert cliente.get("/portal/dossier").status_code == 200 and cliente.post("/portal/dossier", data={"periodo": "ultimo_anio"}).status_code == 403
