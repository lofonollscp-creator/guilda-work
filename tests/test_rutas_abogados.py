"""Pantallas del módulo Gabinete de abogados y la página pública de solo lectura del cliente."""
import io
import re
from datetime import date, datetime, timedelta

import pytest

from app import abogados as ab
from app import almacen_documentos as alm
from app import db, nucleo, verticales
from tests.conftest import iniciar_sesion_de_prueba


def _con_bufete(cliente, email="abogada@ejemplo.com", modulo=True, supervisor=False):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant(f"Bufete {email}")
    db.asignar_tenant(uid, t)
    if modulo:
        verticales.fijar_activo(t, "abogados", True)
    if supervisor:
        conn = db.get_connection(); conn.execute("UPDATE usuarios SET supervisor_tenant = 1 WHERE id = ?", (uid,)); conn.commit(); conn.close()
    return uid, t


def _asunto(t, uid, titulo="Reclamación a Delta", tipo="procedimiento_judicial"):
    c = nucleo.crear_cliente(t, "Cliente Uno S.L.", nif="B12345678")
    return c, nucleo.crear_expediente(t, uid, c, titulo, tipo=tipo)


def test_sin_el_modulo_todo_da_404_y_el_menu_no_lo_ofrece(cliente):
    uid, t = _con_bufete(cliente, modulo=False)
    for ruta in ("/abogados/", "/abogados/ajustes", "/abogados/conflictos", "/abogados/vistas", "/abogados/vistas.ics", "/abogados/minutas"):
        assert cliente.get(ruta).status_code == 404, ruta
    assert 'title="Gabinete"' not in cliente.get("/clientes/").get_data(as_text=True)
    verticales.fijar_activo(t, "abogados", True)
    assert cliente.get("/abogados/").status_code == 200 and 'title="Gabinete"' in cliente.get("/clientes/").get_data(as_text=True)


def test_las_pantallas_del_modulo_cargan(cliente):
    uid, t = _con_bufete(cliente)
    c, x = _asunto(t, uid)
    nucleo.crear_plazo(t, uid, "Contestar", (date.today() + timedelta(days=4)).isoformat(), expediente_id=x, critico=True)
    ab.crear_vista(t, uid, x, (datetime.now() + timedelta(days=3)).isoformat(timespec="minutes"), "juicio", "Sala 1")
    for ruta in ("/abogados/", "/abogados/ajustes", "/abogados/conflictos", "/abogados/conflictos?nombre=Delta&como=contraparte", "/abogados/vistas", "/abogados/minutas", f"/abogados/expedientes/{x}/notificacion", f"/expedientes/{x}"):
        r = cliente.get(ruta)
        assert r.status_code == 200, ruta
    html = cliente.get("/abogados/").get_data(as_text=True)
    assert "Contestar" in html and "Sala 1" in html and "Fatal" in html
    ficha = cliente.get(f"/expedientes/{x}").get_data(as_text=True)
    assert 'id="panel-abogados"' in ficha and "Registrar notificación" in ficha and "Provisión de fondos" in ficha and "Enlace para el cliente" in ficha
    _, general = _asunto(t, uid, "Otro", tipo="general")
    assert 'id="panel-abogados"' not in cliente.get(f"/expedientes/{general}").get_data(as_text=True), "los expedientes generales no llevan el panel"


def test_flujo_de_un_asunto_judicial_en_la_web(cliente):
    uid, t = _con_bufete(cliente)
    c = nucleo.crear_cliente(t, "Cliente Uno S.L.", nif="B12345678")
    r = cliente.post("/expedientes/nuevo", data={"cliente_id": c, "titulo": "Demanda de reclamación", "tipo": "procedimiento_judicial"})
    x = int(r.headers["Location"].rsplit("/", 1)[1])
    assert nucleo.obtener_expediente(t, x, uid)["tipo"] == "procedimiento_judicial"
    assert 'value="procedimiento_judicial"' in cliente.get("/expedientes/nuevo").get_data(as_text=True)
    assert cliente.post(f"/abogados/expedientes/{x}/datos", data={"numero_procedimiento": "45/2026", "juzgado": "Juzgado nº 4", "jurisdiccion": "civil", "cuantia": "3.000,00", "resumen_cliente": "Presentada la demanda."}).status_code == 302
    d = ab.datos_de(nucleo.obtener_expediente(t, x, uid))
    assert d["numero_procedimiento"] == "45/2026" and d["cuantia_centimos"] == 300000
    html = cliente.get(f"/expedientes/{x}").get_data(as_text=True)
    assert "45/2026" in html and "Presentada la demanda." in html and "Juzgado nº 4" in html
    r = cliente.post(f"/abogados/expedientes/{x}/datos", data={"jurisdiccion": "marciana"}, follow_redirects=True)
    assert "Jurisdicción no válida" in r.get_data(as_text=True)
    # vista
    cliente.post(f"/abogados/expedientes/{x}/vistas", data={"fecha_hora": "2030-05-14T10:30", "tipo": "juicio", "lugar": "Sala 3"})
    v = ab.listar_vistas(t, uid)[0]
    assert v["lugar"] == "Sala 3"
    cliente.post(f"/abogados/expedientes/{x}/vistas/{v['id']}/estado", data={"estado": "celebrada"})
    assert ab.listar_vistas(t, uid)[0]["estado"] == "celebrada"
    r = cliente.get("/abogados/vistas.ics")
    assert r.status_code == 200 and r.mimetype == "text/calendar" and r.data.startswith(b"BEGIN:VCALENDAR")
    cliente.post(f"/abogados/expedientes/{x}/vistas/{v['id']}/eliminar")
    assert ab.listar_vistas(t, uid) == []
    # fondos
    cliente.post(f"/abogados/expedientes/{x}/fondos", data={"tipo": "provision", "importe": "500,00", "concepto": "Provisión inicial", "fecha": date.today().isoformat()})
    assert ab.saldo(t, x)["saldo"] == 50000 and "500,00 €" in cliente.get(f"/expedientes/{x}").get_data(as_text=True)
    r = cliente.post(f"/abogados/expedientes/{x}/fondos", data={"tipo": "provision", "importe": "0", "concepto": "x"}, follow_redirects=True)
    assert "mayor que cero" in r.get_data(as_text=True)


def test_notificacion_calcula_vista_previa_y_crea_el_plazo(cliente):
    uid, t = _con_bufete(cliente)
    c, x = _asunto(t, uid)
    url = f"/abogados/expedientes/{x}/notificacion"
    previo = cliente.get(url + "?resolucion=auto&fecha_notificacion=2026-07-29&plazo=5&unidad=habiles").get_data(as_text=True)
    assert "2026-09-03" in previo and "Confirmar y crear el plazo" in previo and nucleo.listar_plazos(t, uid) == [], "calcular no crea nada"
    hace = (date.today() - timedelta(days=1)).isoformat()
    r = cliente.post(url, data={"resolucion": "sentencia", "fecha_notificacion": hace, "plazo": "20", "unidad": "habiles", "critico": "1", "crear_tarea": "1"})
    assert r.status_code == 302
    p = nucleo.listar_plazos(t, uid)[0]
    assert p["critico"] == 1 and p["origen"] == "notificacion" and "Sentencia" in p["titulo"]
    r = cliente.post(url, data={"resolucion": "carta", "fecha_notificacion": hace, "plazo": "5"})
    assert r.status_code == 200 and "resolución" in r.get_data(as_text=True).lower()
    assert len(nucleo.listar_plazos(t, uid)) == 1
    r = cliente.get(url + "?fecha_notificacion=ayer&plazo=5")
    assert r.status_code == 200 and "no es válida" in r.get_data(as_text=True)


def test_conflicto_al_anadir_una_parte_enseña_la_coincidencia(cliente):
    uid, t = _con_bufete(cliente)
    c, x1 = _asunto(t, uid, "Caso A")
    ab.anadir_parte(t, uid, x1, "contraparte", "Constructora Delta S.L.", "B99999999")
    c2 = nucleo.crear_cliente(t, "Constructora Delta S.L.", nif="B99999999")
    x2 = nucleo.crear_expediente(t, uid, c2, "Caso B", tipo="asunto_extrajudicial")
    r = cliente.post(f"/abogados/expedientes/{x2}/partes", data={"rol": "cliente", "nombre": "Constructora Delta S.L.", "nif": "B99999999"}, follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "posible conflicto" in html.lower() and "Caso A" in html, "se le enseña el conflicto antes de seguir"
    r = cliente.post(f"/abogados/expedientes/{x1}/partes", data={"rol": "tercero", "nombre": "Un testigo cualquiera"})
    assert r.status_code == 302 and f"/expedientes/{x1}" in r.headers["Location"], "sin coincidencias, vuelve al asunto"


def test_minutas_en_la_web(cliente):
    uid, t = _con_bufete(cliente, supervisor=True)
    c, x = _asunto(t, uid)
    nucleo.fijar_tarifa_usuario(t, uid, 15000)
    r = cliente.post(f"/abogados/expedientes/{x}/minutas", follow_redirects=True)
    assert "No hay horas" in r.get_data(as_text=True)
    nucleo.registrar_parte(t, uid, "Estudio del caso", minutos=60, expediente_id=x)
    r = cliente.post(f"/abogados/expedientes/{x}/minutas")
    assert r.status_code == 302
    mid = int(re.search(r"/minutas/(\d+)", r.headers["Location"]).group(1))
    html = cliente.get(f"/abogados/minutas/{mid}").get_data(as_text=True)
    assert "Estudio del caso" in html and "150,00 €" in html and "Emitir minuta" in html
    cliente.post(f"/abogados/minutas/{mid}/lineas", data={"concepto": "Escrito", "importe": "50,00", "tipo": "honorarios"})
    cliente.post(f"/abogados/minutas/{mid}/impuestos", data={"iva_pct": "21", "irpf_pct": "15", "notas": "Gracias"})
    m, _l = ab.obtener_minuta(t, mid)
    assert m["base_centimos"] == 20000 and m["irpf_pct"] == 15 and m["total_centimos"] == 20000 + 4200 - 3000
    cliente.post(f"/abogados/minutas/{mid}/emitir", data={"cargar_a_provision": "1"})
    m, _l = ab.obtener_minuta(t, mid)
    assert m["estado"] == "emitida" and m["numero"] == f"M-{date.today().year}-001"
    r = cliente.get(f"/abogados/minutas/{mid}.pdf")
    assert r.status_code == 200 and r.data.startswith(b"%PDF") and "minuta_M-" in r.headers["Content-Disposition"]
    r = cliente.post(f"/abogados/minutas/{mid}/lineas", data={"concepto": "tarde", "importe": "1"}, follow_redirects=True)
    assert "ya está emitida" in r.get_data(as_text=True)
    assert "M-" in cliente.get("/abogados/minutas").get_data(as_text=True) and "Emitidas" in cliente.get("/abogados/minutas?estado=emitida").get_data(as_text=True)
    cliente.post(f"/abogados/minutas/{mid}/estado", data={"estado": "pagada"})
    assert ab.obtener_minuta(t, mid)[0]["estado"] == "pagada"
    assert cliente.get("/abogados/minutas/99999").status_code == 404


def test_ajustes_solo_los_cambia_un_responsable(cliente):
    uid, t = _con_bufete(cliente)
    datos = {"serie": "AB", "iva_pct": "21", "irpf_pct": "7", "bloque_minutos": "15", "provision_minima": "300,00", "plantilla_encargo": "Hola {cliente}"}
    assert cliente.post("/abogados/ajustes", data=datos).status_code == 403
    conn = db.get_connection(); conn.execute("UPDATE usuarios SET supervisor_tenant = 1 WHERE id = ?", (uid,)); conn.commit(); conn.close()
    cliente.get("/clientes/")
    assert cliente.post("/abogados/ajustes", data=datos).status_code == 302
    a = ab.obtener_ajustes(t)
    assert (a["serie"], a["irpf_pct"], a["provision_minima_centimos"], a["plantilla_encargo"]) == ("AB", 7, 30000, "Hola {cliente}")
    r = cliente.post("/abogados/ajustes", data={**datos, "iva_pct": "99"}, follow_redirects=True)
    assert "fuera de rango" in r.get_data(as_text=True)


def test_hoja_de_encargo_y_envio_a_firma_en_la_web(cliente, monkeypatch):
    from app import documenso

    uid, t = _con_bufete(cliente)
    c, x = _asunto(t, uid)
    cliente.post(f"/abogados/expedientes/{x}/hoja-de-encargo")
    docs = alm.listar(t, uid, expediente_id=x)
    assert len(docs) == 1 and docs[0]["categoria"] == "Hoja de encargo"
    html = cliente.get(f"/expedientes/{x}").get_data(as_text=True)
    assert "Enviar a firma" in html and f"/abogados/expedientes/{x}/firma/{docs[0]['id']}" in html
    monkeypatch.setattr(documenso, "crear_documento", lambda *a: {"id": "env_9"})
    monkeypatch.setattr(documenso, "enviar_a_firma", lambda *a: None)
    r = cliente.post(f"/abogados/expedientes/{x}/firma/{docs[0]['id']}", data={"email": "cliente@ejemplo.com", "nombre": "Cliente"})
    assert r.status_code == 302
    r = cliente.post(f"/abogados/expedientes/{x}/firma/{docs[0]['id']}", data={"email": "sin-arroba"}, follow_redirects=True)
    assert "email" in r.get_data(as_text=True).lower()


def test_enlace_publico_del_cliente_de_extremo_a_extremo(cliente):
    uid, t = _con_bufete(cliente)
    c, x = _asunto(t, uid, "Reclamación a Delta")
    ab.fijar_datos(t, uid, x, resumen_cliente="Hemos presentado la demanda.")
    nucleo.cambiar_estado_expediente(t, uid, x, "pendiente_vista")
    _, d1 = alm.guardar(uid, "demanda.pdf", "application/pdf", b"%PDF demanda", expediente_id=x)
    _, d2 = alm.guardar(uid, "interno.pdf", "application/pdf", b"%PDF interno", expediente_id=x)
    nucleo.registrar_parte(t, uid, "Horas internas confidenciales", minutos=30, expediente_id=x)
    assert cliente.post(f"/abogados/expedientes/{x}/documentos/{d1}/compartir", data={"compartido": "1"}).status_code == 302
    r = cliente.post(f"/abogados/expedientes/{x}/enlaces", data={"dias": "10"})
    assert r.status_code == 200 and r.headers["Cache-Control"] == "no-store"
    url = re.search(r'id="enlace-cliente">([^<]+)<', r.get_data(as_text=True)).group(1)
    token = url.rsplit("/", 1)[1]
    assert "/asunto/" in url and len(token) >= 40
    # una persona sin sesión ve la página
    from app.main import app
    anonimo = app.test_client()
    r = anonimo.get(f"/asunto/{token}")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Reclamación a Delta" in html and "Hemos presentado la demanda." in html and "demanda.pdf" in html
    assert "interno.pdf" not in html and "Horas internas" not in html and "noindex" in html
    assert r.headers["Cache-Control"] == "no-store" and "noindex" in r.headers["X-Robots-Tag"] and r.headers["Referrer-Policy"] == "no-referrer"
    r = anonimo.get(f"/asunto/{token}/documentos/{d1}")
    assert r.status_code == 200 and r.data == b"%PDF demanda" and "attachment" in r.headers["Content-Disposition"]
    assert anonimo.get(f"/asunto/{token}/documentos/{d2}").status_code == 404, "un documento no compartido no se baja"
    r = anonimo.get("/asunto/token-inventado")
    assert r.status_code == 404 and "noindex" in r.get_data(as_text=True)
    # revocar
    enlace = ab.listar_enlaces(t, x)[0]["id"]
    cliente.post(f"/abogados/expedientes/{x}/enlaces/{enlace}/revocar")
    assert anonimo.get(f"/asunto/{token}").status_code == 404 and anonimo.get(f"/asunto/{token}/documentos/{d1}").status_code == 404
    assert "Revocado" in cliente.get(f"/expedientes/{x}").get_data(as_text=True)


def test_otro_bufete_no_toca_los_asuntos_ajenos(cliente):
    uid, t = _con_bufete(cliente, "dueña@ejemplo.com")
    c, x = _asunto(t, uid)
    mid = (nucleo.registrar_parte(t, uid, "h", minutos=60, expediente_id=x, tarifa_hora_centimos=10000), ab.crear_borrador_de_minuta(t, uid, x))[1]
    otro = db.crear_usuario_vinculado_a_kratos("intruso-abogados@ejemplo.com", "kratos-intruso-abogados")
    t2 = db.crear_tenant("Otro bufete")
    db.asignar_tenant(otro, t2)
    verticales.fijar_activo(t2, "abogados", True)
    db.asignar_tenant(uid, t2)           # la persona con sesión pasa al otro despacho
    cliente.get("/clientes/")
    assert cliente.get(f"/abogados/minutas/{mid}").status_code == 404 and cliente.get(f"/abogados/minutas/{mid}.pdf").status_code == 404
    for ruta, datos in ((f"/abogados/expedientes/{x}/datos", {"juzgado": "Robado"}), (f"/abogados/expedientes/{x}/vistas", {"fecha_hora": "2030-01-01T10:00"}),
                        (f"/abogados/expedientes/{x}/fondos", {"tipo": "provision", "importe": "10", "concepto": "x"}), (f"/abogados/minutas/{mid}/emitir", {}), (f"/abogados/expedientes/{x}/enlaces", {})):
        r = cliente.post(ruta, data=datos)
        assert r.status_code in (302, 404, 200), ruta
    assert nucleo.obtener_expediente(t2, x, uid) is None, "el asunto no es visible desde el otro despacho"
    assert ab.listar_vistas(t, otro) == [] and ab.saldo(t, x)["saldo"] == 0 and ab.listar_enlaces(t, x) == []
    assert ab.obtener_minuta(t, mid)[0]["estado"] == "borrador"
