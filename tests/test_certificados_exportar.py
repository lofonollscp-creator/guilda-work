"""Calendario .ics e informe para auditoría de los certificados (K2 y K6)."""
from datetime import datetime, timedelta, timezone

import pytest

from app import certificados as ce
from app import certificados_exportar as ex
from app import db, verticales
from tests.conftest import iniciar_sesion_de_prueba

AHORA = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def despacho(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "cert-exp@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho certificados exportar")
    db.asignar_tenant(uid, t)
    db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "gestoria", True)
    cf = db.crear_cliente_fiscal(t, "Panadería Marta, S.L.", nif="B12345674")
    return cliente, uid, t, cf


def _alta(t, uid, cf, dias, titular):
    caduca = (datetime.now(timezone.utc) + timedelta(days=dias)).date().isoformat()
    cid = ce.alta_rapida(t, uid, tipo="fnmt_persona_fisica", caduca=caduca, cliente_fiscal_id=cf, titular=titular)["id"]
    return cid, caduca


def test_el_ics_trae_un_evento_por_certificado_con_avisos_y_sin_los_caducados_hace_mucho(despacho):
    _c, uid, t, cf = despacho
    cid, caduca = _alta(t, uid, cf, 20, "Marta Puig; con, comas")
    _alta(t, uid, cf, -200, "Muy antiguo")
    ce.vincular(t, uid, cid, cliente_fiscal_id=cf, servicio="presentacion", autorizacion="Mandato")
    texto = ex.ics(t)
    assert texto.startswith("BEGIN:VCALENDAR\r\n") and texto.endswith("END:VCALENDAR\r\n") and texto.count("BEGIN:VEVENT") == 1
    assert f"DTSTART;VALUE=DATE:{caduca.replace('-', '')}" in texto and f"UID:certificado-{cid}-{t}@guilda.work" in texto
    assert texto.count("BEGIN:VALARM") == 2 and "TRIGGER:-P30D" in texto and "TRIGGER:-P7D" in texto
    assert "Presentación de impuestos" in texto.replace("\r\n ", "") and "Muy antiguo" not in texto
    assert all(len(linea.encode("utf-8")) <= 75 for linea in texto.split("\r\n"))                 # líneas plegadas como exige RFC 5545
    assert "\\," in texto.replace("\r\n ", "") or "Panadería Marta\\, S.L." in texto.replace("\r\n ", "")


def test_el_informe_csv_neutraliza_formulas_y_lleva_servicios_y_dias(despacho):
    _c, uid, t, cf = despacho
    cid, _caduca = _alta(t, uid, cf, 10, "=SUMA(1+1)")
    ce.vincular(t, uid, cid, cliente_fiscal_id=cf, servicio="firma", autorizacion="Mandato")
    texto = ex.csv_auditoria(t)
    cabecera, fila = texto.lstrip("﻿").splitlines()[:2]
    assert cabecera.split(",")[0] == "Titular" and "Servicios que cubre" in cabecera
    dias = ce.obtener(t, cid)["dias_restantes"]
    assert fila.startswith("'=SUMA(1+1)") and "Firma" in fila and f",{dias}," in fila                      # la fórmula queda como texto
    assert ex._seguro("+34 600 000 000").startswith("'") and ex._seguro("Normal") == "Normal"


def test_las_pantallas_descargan_el_calendario_y_los_informes_solo_la_gestion(despacho):
    cliente, uid, t, cf = despacho
    _alta(t, uid, cf, 15, "Marta Puig")
    ics = cliente.get("/certificados/caducidades.ics")
    assert ics.status_code == 200 and ics.mimetype == "text/calendar" and b"BEGIN:VEVENT" in ics.data
    csv = cliente.get("/certificados/informe.csv")
    assert csv.status_code == 200 and csv.mimetype == "text/csv" and "certificados-" in csv.headers["Content-Disposition"]
    pdf = cliente.get("/certificados/informe.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    html = cliente.get("/certificados/").get_data(as_text=True)
    assert "caducidades.ics" in html and "informe.csv" in html and "informe.pdf" in html
    db.asignar_supervisor_tenant(uid, False)
    assert cliente.get("/certificados/caducidades.ics").status_code == 403
