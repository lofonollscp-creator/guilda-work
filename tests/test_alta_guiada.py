"""Alta guiada (C1): documentos que se piden solos al dar de alta con una plantilla, invitación al portal escalonada y su importación masiva."""
from datetime import datetime, timedelta

import pytest

from app import alta_cliente, db, plantillas_cliente as pc, portal_invitaciones as pi, portal_peticiones, verticales
from tests.test_plantillas_cliente import _despacho


def _alta(t, u, nombre, email="x@ejemplo.com", plantilla="serie:autonomo", **kw):
    verticales.fijar_activo(t, "gestoria", True)
    return alta_cliente.crear_cliente_completo(t, nombre, gestion_fiscal=True, email=email, plantilla_id=plantilla, usuario_id=u, nif=kw.pop("nif", None), **kw)


def test_las_plantillas_de_serie_traen_su_lista_de_documentos_y_las_propias_la_guardan():
    t, u = _despacho("Guiada plantillas")
    series = {p["id"]: p for p in pc.listar(t)}
    assert "DNI o NIE (por las dos caras)" in series["serie:autonomo"]["peticiones"] and "Escritura de constitución y estatutos" in series["serie:sociedad"]["peticiones"]
    pid = pc.crear(t, u, "Con empleados", perfil_tipo="sociedad", peticiones="Contrato tipo\n\nContrato tipo\n  Alta de trabajadores  ", invitar_portal=True)
    p = pc.obtener(t, pid)
    assert p["peticiones"] == ["Contrato tipo", "Alta de trabajadores"] and p["invitar_portal"] is True
    assert pc.peticiones_limpias(["a"] * 40) == ["a"] and len(pc.peticiones_limpias("\n".join(f"p{i}" for i in range(40)))) == pc.MAX_PETICIONES


def test_dar_de_alta_con_plantilla_abre_una_peticion_por_documento_y_apunta_la_invitacion():
    t, u = _despacho("Guiada alta")
    pid = pc.crear(t, u, "Autónomo guiado", perfil_tipo="autonomo", peticiones="DNI\nCertificado digital", invitar_portal=True)
    r = _alta(t, u, "Cliente Guiado", "guiado@ejemplo.com", pid, nif="B12345678")
    ficha = db.obtener_cliente_fiscal(t, r["cliente_fiscal_id"])
    titulos = [p["titulo"] for p in portal_peticiones.listar(ficha)]
    assert sorted(titulos) == ["Certificado digital", "DNI"] and r["peticiones"] == 2 and r["invitada"] is True and pi.pendientes(t) == 1


def test_sin_correo_o_sin_invitar_no_se_apunta_nada_y_la_invitacion_no_se_duplica():
    t, u = _despacho("Guiada sin")
    r = _alta(t, u, "Sin correo", email=None, plantilla=pc.crear(t, u, "Invita", perfil_tipo="autonomo", invitar_portal=True))
    assert r["invitada"] is False and pi.pendientes(t) == 0
    r2 = _alta(t, u, "Sin invitar", "si@ejemplo.com", plantilla="serie:autonomo", nif="A11111119")
    assert r2["invitada"] is False and r2["peticiones"] == 4
    assert pi.encolar(t, r2["cliente_fiscal_id"]) is True and pi.encolar(t, r2["cliente_fiscal_id"]) is False                # una pendiente por cliente


def test_las_invitaciones_salen_escalonadas_con_tope_por_hora_y_despacho():
    t, u = _despacho("Guiada cola")
    ids = [_alta(t, u, f"Cliente {i}", f"c{i}@ejemplo.com", "serie:autonomo", nif=None, invitar_portal=True)["cliente_fiscal_id"] for i in range(25)]
    enviadas = []
    def falso(cliente, base, ip):
        enviadas.append(cliente["email"])
        return True
    ahora = datetime.now()
    assert pi.procesar(ahora, base_url="https://work.ejemplo.com", enviar=falso)["enviadas"] == pi.MAX_POR_PASADA == 20 and pi.pendientes(t) == 5
    r = pi.procesar(ahora + timedelta(minutes=5), base_url="https://work.ejemplo.com", enviar=falso)
    assert r["enviadas"] == 5 and pi.pendientes(t) == 0 and len(enviadas) == 25 and len(set(enviadas)) == 25


def test_el_tope_por_hora_aplaza_y_un_fallo_se_reintenta_hasta_agotarse():
    t, u = _despacho("Guiada tope")
    ids = [_alta(t, u, f"C{i}", f"t{i}@ejemplo.com", "serie:autonomo", nif=None, invitar_portal=True)["cliente_fiscal_id"] for i in range(3)]
    ahora = datetime.now()
    assert pi.procesar(ahora, base_url="https://w.ejemplo.com", enviar=lambda c, b, ip: False)["fallidas"] == 3
    for _ in range(pi.MAX_INTENTOS - 1):
        pi.procesar(ahora, base_url="https://w.ejemplo.com", enviar=lambda c, b, ip: False)
    assert pi.pendientes(t) == 0                                                                                   # agotados los intentos, deja de insistir
    assert pi.procesar(ahora, base_url="")["enviadas"] == 0                                                         # sin dirección pública no se manda nada


def test_el_panel_pone_en_cola_a_los_pendientes_y_cuenta_lo_que_queda(cliente):
    from tests.test_facturas_contables import _web
    from app.db_fiscal import crear_cliente_fiscal
    uid, t, c = _web(cliente, email="guiada-panel@ejemplo.com")
    for i in range(3):
        crear_cliente_fiscal(t, f"Pendiente {i}", nif=None, email=f"p{i}@ejemplo.com")
    r = cliente.post("/fiscal/portal-adopcion/invitar-pendientes")
    assert r.status_code == 302 and "en_cola=" in r.headers["Location"] and pi.pendientes(t) >= 3
    html = cliente.get("/fiscal/portal-adopcion").get_data(as_text=True)
    assert "invitaciones por enviar" in html or "invitación por enviar" in html


def test_la_importacion_aplica_la_plantilla_y_encola_las_invitaciones(cliente):
    import io
    from tests.test_facturas_contables import _web
    uid, t, c = _web(cliente, email="guiada-import@ejemplo.com")
    verticales.fijar_activo(t, "gestoria", True)
    csv = "nombre,nif,email\nImportada Uno,B87654323,uno@ejemplo.com\nImportada Dos,A11111119,dos@ejemplo.com\n".encode()
    r = cliente.post("/clientes/importar/", data={"archivo": (io.BytesIO(csv), "clientes.csv")}, content_type="multipart/form-data")
    ident = r.headers["Location"].rstrip("/").split("/")[-1].split("?")[0]
    pid = pc.crear(t, uid, "Importados", perfil_tipo="autonomo", peticiones="DNI", invitar_portal=False)
    r = cliente.post(f"/clientes/importar/{ident}", data={"gestion_fiscal": "1", "omitir_duplicados": "1", "plantilla_id": pid, "invitar_portal": "1", "perfil_tipo": "autonomo"})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "2 invitaciones al portal en cola" in html and "2 peticiones de documentos abiertas" in html and pi.pendientes(t) == 2
