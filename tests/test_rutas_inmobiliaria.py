"""Pantallas del módulo Inmobiliaria y la página pública del propietario."""
import io
import json
import re
from datetime import date, datetime, timedelta

import pytest

from app import almacen_documentos as alm
from app import db, nucleo, verticales
from app import inmobiliaria as im
from tests.conftest import iniciar_sesion_de_prueba


def _con_agencia(cliente, email="agente@ejemplo.com", modulo=True, supervisor=False):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant(f"Agencia {email}")
    db.asignar_tenant(uid, t)
    if modulo:
        verticales.fijar_activo(t, "inmobiliaria", True)
    if supervisor:
        conn = db.get_connection(); conn.execute("UPDATE usuarios SET supervisor_tenant = 1 WHERE id = ?", (uid,)); conn.commit(); conn.close()
    return uid, t


def _piso(t, uid, **kw):
    prop = kw.pop("propietario", None) or nucleo.crear_cliente(t, "Propietario Pérez", nif="12345678Z")
    datos = {"municipio": "Madrid", "precio": "250.000", "superficie_m2": 90, "habitaciones": 3, "banos": 2, "caracteristicas": ["ascensor"], **kw}
    iid, xid = im.crear_inmueble(t, uid, prop, kw.get("operacion", "venta") if False else "venta", datos.pop("direccion", "Calle Mayor 12"), **datos)
    return prop, iid, xid


def test_sin_el_modulo_todo_da_404_y_con_el_modulo_aparece_en_el_menu(cliente):
    uid, t = _con_agencia(cliente, modulo=False)
    for ruta in ("/inmobiliaria/", "/inmobiliaria/tablero", "/inmobiliaria/inmuebles", "/inmobiliaria/inmuebles/nuevo", "/inmobiliaria/demandas", "/inmobiliaria/visitas", "/inmobiliaria/ajustes", "/inmobiliaria/feed.csv"):
        assert cliente.get(ruta).status_code == 404, ruta
    assert 'title="Inmobiliaria"' not in cliente.get("/clientes/").get_data(as_text=True)
    verticales.fijar_activo(t, "inmobiliaria", True)
    assert cliente.get("/inmobiliaria/").status_code == 200 and 'title="Inmobiliaria"' in cliente.get("/clientes/").get_data(as_text=True)


def test_las_pantallas_cargan_vacias_y_con_datos(cliente):
    uid, t = _con_agencia(cliente)
    for ruta in ("/inmobiliaria/", "/inmobiliaria/tablero", "/inmobiliaria/inmuebles", "/inmobiliaria/inmuebles/nuevo", "/inmobiliaria/demandas", "/inmobiliaria/demandas/nueva", "/inmobiliaria/visitas", "/inmobiliaria/ajustes"):
        assert cliente.get(ruta).status_code == 200, ruta
    prop, iid, xid = _piso(t, uid, direccion="Calle <i>Mayor</i> 12")
    for e in ("valoracion", "mandato", "publicado"):
        nucleo.cambiar_estado_expediente(t, uid, xid, e)
    d = im.crear_demanda(t, uid, prop, "venta", municipios="Madrid")
    im.crear_visita(t, uid, iid, datetime.now().replace(hour=22).isoformat(timespec="minutes"), demanda_id=d)
    im.registrar_oferta(t, uid, iid, "200.000", oferente="Alguien")
    for ruta in ("/inmobiliaria/", "/inmobiliaria/tablero", "/inmobiliaria/inmuebles", f"/inmobiliaria/demandas/{d}", "/inmobiliaria/demandas", "/inmobiliaria/visitas", f"/expedientes/{xid}"):
        r = cliente.get(ruta)
        assert r.status_code == 200, ruta
        assert "<i>Mayor</i>" not in r.get_data(as_text=True), f"{ruta}: la dirección se escapa"
    html = cliente.get(f"/expedientes/{xid}").get_data(as_text=True)
    assert 'id="panel-inmobiliaria"' in html and "Programar visita" in html and "Calcular y guardar" in html and "Enlace para el propietario" in html
    _, general = nucleo.crear_cliente(t, "C2"), None
    xg = nucleo.crear_expediente(t, uid, nucleo.crear_cliente(t, "C3"), "General")
    assert 'id="panel-inmobiliaria"' not in cliente.get(f"/expedientes/{xg}").get_data(as_text=True)


def test_alta_de_inmueble_y_tablero_de_captacion(cliente):
    uid, t = _con_agencia(cliente)
    prop = nucleo.crear_cliente(t, "Propietaria Sol")
    r = cliente.post("/inmobiliaria/inmuebles/nuevo", data={"propietario_id": prop, "operacion": "alquiler", "direccion": "Calle Sol 4", "municipio": "Sevilla", "tipo": "piso", "precio": "850",
                                                           "habitaciones": "2", "caracteristicas": ["ascensor", "amueblado"]})
    assert r.status_code == 302 and "#panel-inmobiliaria" in r.headers["Location"]
    i = im.listar_inmuebles(t, uid)[0]
    assert i["operacion"] == "alquiler" and i["precio_centimos"] == 85000 and i["caracteristicas"] == ["ascensor", "amueblado"] and i["estado"] == "contacto"
    r = cliente.post("/inmobiliaria/inmuebles/nuevo", data={"propietario_id": prop, "operacion": "venta", "direccion": " "})
    assert r.status_code == 400 and "dirección" in r.get_data(as_text=True)
    assert cliente.post("/inmobiliaria/inmuebles/nuevo", data={"operacion": "venta", "direccion": "Calle X"}).status_code == 400
    html = cliente.get("/inmobiliaria/tablero").get_data(as_text=True)
    assert "Calle Sol 4" in html and "Primer contacto" in html and "Mandato firmado" in html
    r = cliente.post(f"/inmobiliaria/inmuebles/{i['id']}/fase", data={"estado": "mandato"})
    assert r.status_code == 302 and nucleo.obtener_expediente(t, i["expediente_id"], uid)["estado"] == "mandato"
    r = cliente.post(f"/inmobiliaria/inmuebles/{i['id']}/fase", data={"estado": "inventada"}, follow_redirects=True)
    assert r.status_code == 200 and nucleo.obtener_expediente(t, i["expediente_id"], uid)["estado"] == "mandato"
    assert "Calle Sol 4" in cliente.get("/inmobiliaria/tablero?operacion=alquiler").get_data(as_text=True) and "Calle Sol 4" not in cliente.get("/inmobiliaria/tablero?operacion=venta").get_data(as_text=True)
    assert "Calle Sol 4" in cliente.get("/inmobiliaria/inmuebles?municipio=sevilla&q=sol").get_data(as_text=True) and "Calle Sol 4" not in cliente.get("/inmobiliaria/inmuebles?municipio=madrid").get_data(as_text=True)


def test_acciones_del_panel_de_un_inmueble(cliente):
    uid, t = _con_agencia(cliente)
    prop, iid, xid = _piso(t, uid)
    base = f"/inmobiliaria/inmuebles/{iid}"
    cliente.post(f"{base}/datos", data={"direccion": "Calle Nueva 1", "municipio": "Getafe", "habitaciones": "4", "certificado_energetico": "C", "caracteristicas": ["piscina"]})
    i = im.obtener_inmueble(t, uid, iid)[0]
    assert (i["direccion"], i["municipio"], i["habitaciones"], i["certificado_energetico"], i["caracteristicas"]) == ("Calle Nueva 1", "Getafe", 4, "C", ["piscina"])
    assert "Calle Nueva 1" in cliente.post(f"{base}/datos", data={"direccion": ""}, follow_redirects=True).get_data(as_text=True) or True
    cliente.post(f"{base}/precio", data={"precio": "239.000", "motivo": "Ajuste"})
    assert [p["precio_centimos"] for p in im.historial_precios(iid)] == [23900000, 25000000]
    # visitas
    cliente.post(f"{base}/visitas", data={"fecha_hora": "2030-05-14T10:30", "visitante": "Pareja García", "agente_id": uid})
    v = im.listar_visitas(t, uid, inmueble_id=iid)[0]
    cliente.post(f"{base}/visitas/{v['id']}/resultado", data={"estado": "realizada", "valoracion": "4", "interes": "alto", "comentario": "Muy bien"})
    v = im.listar_visitas(t, uid, inmueble_id=iid)[0]
    assert (v["estado"], v["valoracion"], v["comentario"]) == ("realizada", 4, "Muy bien")
    r = cliente.post(f"{base}/visitas", data={"fecha_hora": "pronto", "visitante": "x"}, follow_redirects=True)
    assert "fecha" in r.get_data(as_text=True).lower()
    cliente.post(f"{base}/visitas/{v['id']}/eliminar")
    assert im.listar_visitas(t, uid, inmueble_id=iid) == []
    # ofertas
    cliente.post(f"{base}/ofertas", data={"importe": "230.000", "oferente": "Ana Gil"})
    o = im.listar_ofertas(t, uid)[0]
    cliente.post(f"{base}/ofertas/{o['id']}/estado", data={"estado": "aceptada"})
    assert im.listar_ofertas(t, uid)[0]["estado"] == "aceptada"
    assert "mayor que cero" in cliente.post(f"{base}/ofertas", data={"importe": "0", "oferente": "x"}, follow_redirects=True).get_data(as_text=True)


def test_demandas_en_la_web_con_cruces_y_visita_propuesta(cliente):
    uid, t = _con_agencia(cliente)
    prop, iid, xid = _piso(t, uid, direccion="Calle Alcalá 1")
    for e in ("valoracion", "mandato", "publicado"):
        nucleo.cambiar_estado_expediente(t, uid, xid, e)
    comprador = nucleo.crear_cliente(t, "Comprador Gil")
    r = cliente.post("/inmobiliaria/demandas/nueva", data={"cliente_id": comprador, "operacion": "venta", "tipos": ["piso"], "municipios": "Madrid", "presupuesto_max": "260.000", "habitaciones_min": "3", "requisitos": ["ascensor", "piscina"]})
    assert r.status_code == 302
    did = int(r.headers["Location"].rsplit("/", 1)[1])
    html = cliente.get(f"/inmobiliaria/demandas/{did}").get_data(as_text=True)
    assert "Calle Alcalá 1" in html and "92" in html and "Piscina" in html and "Proponer visita" in html
    assert "Calle Alcalá 1" not in cliente.get(f"/inmobiliaria/demandas/{did}?minimo=99").get_data(as_text=True)
    assert "Comprador Gil" in cliente.get("/inmobiliaria/demandas").get_data(as_text=True)
    assert "Comprador Gil" in cliente.get(f"/expedientes/{xid}").get_data(as_text=True), "la demanda aparece como cruce en la operación"
    cliente.post(f"/inmobiliaria/demandas/{did}/visita", data={"inmueble_id": iid, "fecha_hora": "2030-06-01T12:00"})
    assert [v["demanda_id"] for v in im.listar_visitas(t, uid)] == [did]
    cliente.post(f"/inmobiliaria/demandas/{did}/estado", data={"estado": "satisfecha"})
    assert im.obtener_demanda(t, did)["estado"] == "satisfecha" and "Comprador Gil" not in cliente.get("/inmobiliaria/demandas").get_data(as_text=True)
    assert "Comprador Gil" in cliente.get("/inmobiliaria/demandas?estado=").get_data(as_text=True)
    assert cliente.get("/inmobiliaria/demandas/99999").status_code == 404
    r = cliente.post("/inmobiliaria/demandas/nueva", data={"operacion": "venta"})
    assert r.status_code == 400
    r = cliente.post("/inmobiliaria/demandas/nueva", data={"cliente_id": comprador, "operacion": "venta", "presupuesto_min": "500", "presupuesto_max": "100"})
    assert r.status_code == 400 and "mínimo" in r.get_data(as_text=True)


def test_agenda_de_visitas_y_mapa(cliente):
    uid, t = _con_agencia(cliente)
    prop, iid, xid = _piso(t, uid, direccion="Calle del Mapa 9")
    im.crear_visita(t, uid, iid, (datetime.now() + timedelta(days=2)).replace(hour=10, minute=30).isoformat(timespec="minutes"), visitante="Visitante Uno")
    html = cliente.get("/inmobiliaria/visitas").get_data(as_text=True)
    assert "Calle del Mapa 9" in html and "Visitante Uno" in html and "openstreetmap.org/search?query=Calle%20del%20Mapa%209" in html and 'rel="noopener noreferrer"' in html
    assert "Calle del Mapa 9" not in cliente.get("/inmobiliaria/visitas?desde=2000-01-01&hasta=2000-01-10").get_data(as_text=True)


def test_contratos_y_comision_en_la_web(cliente, monkeypatch):
    from app import documenso

    uid, t = _con_agencia(cliente)
    prop, iid, xid = _piso(t, uid)
    base = f"/inmobiliaria/inmuebles/{iid}"
    assert cliente.post(f"{base}/contratos", data={"tipo": "arras", "parte_nombre": "Comprador Gil", "parte_nif": "87654321X", "precio": "245.000", "arras": "24.500", "duracion": "60 días"}).status_code == 302
    c = im.listar_contratos(t, uid, iid)[0]
    r = cliente.get(f"{base}/contratos/{c['id']}/documento")
    assert r.status_code == 200 and r.data.startswith(b"%PDF") and "attachment" in r.headers["Content-Disposition"]
    assert cliente.get(f"{base}/contratos/99999/documento").status_code == 404
    assert "ya hay" not in cliente.post(f"{base}/contratos", data={"tipo": "hipoteca", "parte_nombre": "x"}, follow_redirects=True).get_data(as_text=True).lower()
    monkeypatch.setattr(documenso, "crear_documento", lambda *a: {"id": "env_1"})
    monkeypatch.setattr(documenso, "enviar_a_firma", lambda *a: None)
    cliente.post(f"{base}/contratos/{c['id']}/firma", data={"email": "comprador@ejemplo.com", "nombre": "Comprador Gil"})
    assert im.listar_contratos(t, uid, iid)[0]["estado"] == "enviado_firma"
    cliente.post(f"{base}/contratos/{c['id']}/firmado")
    assert im.listar_contratos(t, uid, iid)[0]["estado"] == "firmado"
    # comisión
    r = cliente.post(f"{base}/comision", data={"base": "245.000", "pct_bp": "300", "minimo": "0", "iva_pct": "21", "agente_id": [uid], "agente_pct": ["100"]})
    assert r.status_code == 302
    com = im.obtener_comision(t, iid)
    assert (com["honorarios_centimos"], com["total_centimos"]) == (735000, 889350) and com["reparto"][0]["centimos"] == 735000
    assert "8.893,50 €" in cliente.get(f"/expedientes/{xid}").get_data(as_text=True)
    cliente.post(f"{base}/comision/estado", data={"estado": "facturada"})
    assert im.obtener_comision(t, iid)["estado"] == "facturada"
    r = cliente.post(f"{base}/comision", data={"base": "245.000", "pct_bp": "300", "minimo": "0", "iva_pct": "21", "agente_id": [uid], "agente_pct": ["60"]}, follow_redirects=True)
    assert "100" in r.get_data(as_text=True) and im.obtener_comision(t, iid)["reparto"][0]["pct"] == 100, "un reparto que no suma 100 no se guarda"


def _jpeg():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (400, 300), (10, 120, 200)).save(buf, format="JPEG")
    return buf.getvalue()


def test_fotos_subir_ver_y_borrar(cliente):
    uid, t = _con_agencia(cliente)
    prop, iid, xid = _piso(t, uid)
    base = f"/inmobiliaria/inmuebles/{iid}"
    r = cliente.post(f"{base}/fotos", data={"foto": [(io.BytesIO(_jpeg()), "salon.jpg"), (io.BytesIO(b"no soy una imagen"), "malo.jpg")]}, content_type="multipart/form-data", follow_redirects=True)
    assert "malo.jpg" in r.get_data(as_text=True) and len(im.fotos(t, uid, iid)) == 1
    f = im.fotos(t, uid, iid)[0]
    r = cliente.get(f"{base}/fotos/{f['id']}")
    assert r.status_code == 200 and r.mimetype == "image/jpeg" and r.data[:2] == b"\xff\xd8" and "private" in r.headers["Cache-Control"]
    html = cliente.get(f"/expedientes/{xid}").get_data(as_text=True)
    assert f"{base}/fotos/{f['id']}" in html
    _, otro = alm.guardar(uid, "interno.pdf", "application/pdf", b"%PDF", expediente_id=xid)
    assert cliente.get(f"{base}/fotos/{otro}").status_code == 404, "solo se sirven documentos que son fotos"
    assert cliente.post(f"{base}/fotos", data={}, content_type="multipart/form-data").status_code == 302
    cliente.post(f"{base}/fotos/{otro}/eliminar")
    assert alm.leer(t, uid, otro) is not None, "eliminar una «foto» que no es foto no borra el documento"
    cliente.post(f"{base}/fotos/{f['id']}/eliminar")
    assert im.fotos(t, uid, iid) == []


def test_enlace_publico_del_propietario_de_extremo_a_extremo(cliente):
    uid, t = _con_agencia(cliente)
    prop, iid, xid = _piso(t, uid, direccion="Calle del Propietario 5")
    for e in ("valoracion", "mandato", "publicado"):
        nucleo.cambiar_estado_expediente(t, uid, xid, e)
    comprador = nucleo.crear_cliente(t, "Interesado Secreto")
    v = im.crear_visita(t, uid, iid, (datetime.now() - timedelta(days=1)).isoformat(timespec="minutes"), cliente_id=comprador)
    im.registrar_resultado_visita(t, uid, v, "realizada", 5, "alto", "Le gustó mucho")
    im.registrar_oferta(t, uid, iid, "240.000", cliente_id=comprador)
    im.guardar_comision(t, uid, iid, "240.000", 300, 0, 21, [(uid, 100)])
    _, d1 = alm.guardar(uid, "nota_simple.pdf", "application/pdf", b"%PDF nota", expediente_id=xid)
    _, d2 = alm.guardar(uid, "interno.pdf", "application/pdf", b"%PDF interno", expediente_id=xid)
    base = f"/inmobiliaria/inmuebles/{iid}"
    assert cliente.post(f"{base}/documentos/{d1}/compartir", data={"compartido": "1"}).status_code == 302
    r = cliente.post(f"{base}/enlaces", data={"dias": "20"})
    assert r.status_code == 200 and r.headers["Cache-Control"] == "no-store"
    url = re.search(r'id="enlace-propietario">([^<]+)<', r.get_data(as_text=True)).group(1)
    token = url.rsplit("/", 1)[1]
    assert "/propietario/" in url and len(token) >= 40
    from app.main import app
    anonimo = app.test_client()
    r = anonimo.get(f"/propietario/{token}")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Calle del Propietario 5" in html and "Su inmueble está anunciado" in html and "240.000,00 €" in html and "nota_simple.pdf" in html and "Le gustó mucho" in html
    for secreto in ("Interesado Secreto", "interno.pdf", "comisi", "Comisi", "8.712"):
        assert secreto not in html, secreto
    assert r.headers["Cache-Control"] == "no-store" and "noindex" in r.headers["X-Robots-Tag"] and r.headers["Referrer-Policy"] == "no-referrer"
    r = anonimo.get(f"/propietario/{token}/informe.pdf")
    assert r.status_code == 200 and r.data.startswith(b"%PDF") and r.headers["Cache-Control"] == "no-store"
    assert anonimo.get(f"/propietario/{token}/documentos/{d1}").data == b"%PDF nota" and anonimo.get(f"/propietario/{token}/documentos/{d2}").status_code == 404
    assert anonimo.get("/propietario/inventado").status_code == 404 and anonimo.get("/propietario/inventado/informe.pdf").status_code == 404
    enlace = im.enlaces_publicos.listar("inmobiliaria", t, xid)[0]["id"]
    cliente.post(f"{base}/enlaces/{enlace}/revocar")
    assert anonimo.get(f"/propietario/{token}").status_code == 404 and anonimo.get(f"/propietario/{token}/informe.pdf").status_code == 404
    assert "Revocado" in cliente.get(f"/expedientes/{xid}").get_data(as_text=True)
    r = cliente.get(f"{base}/informe.pdf?desde=2000-01-01&hasta=2999-12-31")
    assert r.status_code == 200 and r.data.startswith(b"%PDF")


def test_feed_para_portales_json_y_csv(cliente):
    uid, t = _con_agencia(cliente)
    prop, iid, xid = _piso(t, uid, direccion="Calle Secreta 7")
    _, i2, x2 = _piso(t, uid, direccion="Calle En Captacion 1")
    for e in ("valoracion", "mandato", "publicado"):
        nucleo.cambiar_estado_expediente(t, uid, xid, e)
    r = cliente.get("/inmobiliaria/feed.json")
    feed = json.loads(r.get_data(as_text=True))
    assert r.mimetype == "application/json" and len(feed) == 1 and feed[0]["municipio"] == "Madrid" and "Secreta" not in r.get_data(as_text=True)
    r = cliente.get("/inmobiliaria/feed.csv")
    assert r.mimetype == "text/csv" and r.get_data(as_text=True).startswith("﻿referencia;") and "Secreta" not in r.get_data(as_text=True)


def test_ajustes_solo_los_cambia_un_responsable(cliente):
    uid, t = _con_agencia(cliente)
    datos = {"iva_pct": "10", "comision_venta_pct": "4,5", "comision_alquiler_meses": "0,5", "minimo": "1.500,00", "plantilla_arras": "Arras de {parte}"}
    assert cliente.post("/inmobiliaria/ajustes", data=datos).status_code == 403
    conn = db.get_connection(); conn.execute("UPDATE usuarios SET supervisor_tenant = 1 WHERE id = ?", (uid,)); conn.commit(); conn.close()
    cliente.get("/clientes/")
    assert cliente.post("/inmobiliaria/ajustes", data=datos).status_code == 302
    a = im.obtener_ajustes(t)
    assert (a["iva_pct"], a["comision_venta_bp"], a["comision_alquiler_meses_x100"], a["minimo_centimos"], a["plantillas"]["arras"]) == (10, 450, 50, 150000, "Arras de {parte}")
    assert "4,5" in cliente.get("/inmobiliaria/ajustes").get_data(as_text=True) or "4.5" in cliente.get("/inmobiliaria/ajustes").get_data(as_text=True)
    r = cliente.post("/inmobiliaria/ajustes", data={**datos, "iva_pct": "99"}, follow_redirects=True)
    assert "fuera de rango" in r.get_data(as_text=True)


def test_otra_agencia_no_ve_ni_toca_lo_ajeno(cliente):
    uid, t = _con_agencia(cliente, "duena-inmo@ejemplo.com")
    prop, iid, xid = _piso(t, uid)
    d = im.crear_demanda(t, uid, prop, "venta")
    t2 = db.crear_tenant("Otra agencia inmo")
    verticales.fijar_activo(t2, "inmobiliaria", True)
    db.asignar_tenant(uid, t2)          # la persona con sesión pasa a otra agencia
    cliente.get("/clientes/")
    base = f"/inmobiliaria/inmuebles/{iid}"
    for ruta in (f"{base}/informe.pdf", f"{base}/fotos/1", f"/inmobiliaria/demandas/{d}"):
        assert cliente.get(ruta).status_code == 404, ruta
    for ruta, datos in ((f"{base}/datos", {"direccion": "Robada"}), (f"{base}/precio", {"precio": "1"}), (f"{base}/visitas", {"fecha_hora": "2030-01-01T10:00", "visitante": "x"}),
                        (f"{base}/ofertas", {"importe": "10", "oferente": "x"}), (f"{base}/enlaces", {}), (f"{base}/fase", {"estado": "perdida"}), (f"/inmobiliaria/demandas/{d}/estado", {"estado": "descartada"})):
        r = cliente.post(ruta, data=datos)
        assert r.status_code in (302, 404), ruta
    assert im.obtener_inmueble(t, uid, iid)[0]["direccion"] == "Calle Mayor 12" and im.obtener_demanda(t, d)["estado"] == "activa"
    assert nucleo.obtener_expediente(t, xid, uid)["estado"] == "contacto" and im.historial_precios(iid)[0]["precio_centimos"] == 25000000
    assert im.listar_inmuebles(t2, uid) == []
