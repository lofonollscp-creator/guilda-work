"""Solicitudes RGPD en el backoffice (K10): plazo de un mes, anotar, atender y resumen semanal."""
from datetime import datetime, timedelta

import pytest

from app import db, rgpd_persona
from backoffice import cartera, rgpd as r
from tests.test_backoffice_app import bo, entrar, post  # noqa: F401 -- fixture

AHORA = datetime(2026, 11, 20, 10, 0)


def _tenant(nombre="Despacho RGPD"):
    t = db.crear_tenant(nombre)
    u = db.crear_usuario_vinculado_a_kratos(f"{nombre.replace(' ', '').lower()}@ejemplo.com", "k-" + nombre.replace(" ", ""))
    db.asignar_tenant(u, t)
    return t, u


def _fechar(solicitud_id, cuando):
    conn = db.get_connection(); conn.execute("UPDATE registro_rgpd SET creado_en = ? WHERE id = ?", (cuando.isoformat(timespec="seconds"), solicitud_id)); conn.commit(); conn.close()


def test_la_baja_de_una_cuenta_aparece_como_solicitud_con_su_plazo():
    t, u = _tenant()
    assert rgpd_persona.solicitar_baja(u)
    s = r.solicitudes()["abiertas"][0]
    assert s["despacho"] == "Despacho RGPD" and s["persona"] == "despachorgpd@ejemplo.com" and s["tipo"] == "solicitud_baja" and s["etiqueta"] == "Baja de cuenta" and s["nivel"] == "ok"
    assert s["dias_restantes"] in (29, 30)


@pytest.mark.parametrize("dias, nivel", [(3, "ok"), (25, "aviso"), (30, "aviso"), (31, "vencida"), (60, "vencida")])
def test_los_niveles_segun_los_dias_desde_que_llego(dias, nivel):
    t, u = _tenant()
    sid = r.registrar(t, "solicitud_acceso", "ana@ejemplo.com", "quiere copia de sus datos")
    _fechar(sid, AHORA - timedelta(days=dias))
    assert r.solicitudes(AHORA)["abiertas"][0]["nivel"] == nivel


def test_registrar_valida_tipo_despacho_y_descripcion():
    t, u = _tenant()
    with pytest.raises(ValueError, match="tipo"):
        r.registrar(t, "otra_cosa", "x", "descripción larga")
    with pytest.raises(ValueError, match="Describe"):
        r.registrar(t, "solicitud_supresion", "", "ya")
    with pytest.raises(ValueError, match="no existe"):
        r.registrar(9999, "solicitud_supresion", "ana", "borrar todo lo mío")
    with pytest.raises(ValueError, match="no existe"):
        r.registrar(0, "solicitud_supresion", "ana", "borrar todo lo mío")


def test_atender_cierra_la_solicitud_y_queda_en_las_atendidas():
    t, u = _tenant()
    sid = r.registrar(t, "solicitud_rectificacion", "Luis", "cambiar su dirección")
    with pytest.raises(ValueError, match="mínimo"):
        r.atender(sid, "ok", "jorge")
    r.atender(sid, "Corregida por el despacho el mismo día", "jorge")
    estado = r.solicitudes()
    assert estado["abiertas"] == [] and estado["atendidas"][0]["id"] == sid and "Corregida" in estado["atendidas"][0]["nota"]
    with pytest.raises(ValueError, match="ya está atendida"):
        r.atender(sid, "otra vez, por si acaso", "jorge")
    with pytest.raises(ValueError, match="no existe"):
        r.atender(99999, "no existe esa solicitud", "jorge")


def test_otras_anotaciones_del_registro_no_cuentan_como_solicitudes():
    t, u = _tenant()
    conn = db.get_connection()
    conn.execute("INSERT INTO registro_rgpd (tenant_id, usuario_id, tipo, detalle, creado_en) VALUES (?, ?, 'exportacion_propia', 'descarga', ?)", (t, u, db.now_iso())); conn.commit(); conn.close()
    assert r.solicitudes()["abiertas"] == []


def test_el_resumen_semanal_avisa_de_las_que_vencen_o_vencieron():
    t, u = _tenant()
    ok = r.registrar(t, "solicitud_acceso", "ana", "copia de datos")
    tarde = r.registrar(t, "solicitud_supresion", "luis", "borrar mis datos")
    _fechar(tarde, datetime.now() - timedelta(days=40))
    texto = cartera.texto_resumen(cartera.construir_resumen())
    assert "RGPD" in texto and "VENCIDA hace 10 día(s)" in texto and texto.count("Despacho RGPD") >= 1
    assert [q["id"] for q in cartera.construir_resumen()["rgpd"]] == [tarde]


def test_pantalla_registrar_y_atender(bo):
    t, u = _tenant("Despacho pantalla rgpd")
    entrar(bo)
    assert "No hay solicitudes abiertas" in bo.get("/rgpd").get_data(as_text=True)
    post(bo, "/rgpd/registrar", tenant_id=str(t), tipo="solicitud_oposicion", quien="Marta", detalle="se opone al tratamiento")
    html = bo.get("/rgpd").get_data(as_text=True)
    assert "Oposición" in html and "Marta: se opone" in html and "Despacho pantalla rgpd" in html
    post(bo, "/rgpd/registrar", tenant_id=str(t), tipo="solicitud_oposicion", quien="", detalle="")
    sid = r.solicitudes()["abiertas"][0]["id"]
    post(bo, f"/rgpd/{sid}/atender", nota="Hablado con el despacho, ya cesó el tratamiento")
    html = bo.get("/rgpd").get_data(as_text=True)
    assert "No hay solicitudes abiertas" in html and "ya cesó el tratamiento" in html
