"""Pantallas del Marketing del Comercial (app/rutas_marketing.py) y la baja de un clic. Con Kratos real."""
from app import db, marketing as mk, nucleo, verticales
from tests.conftest import iniciar_sesion_de_prueba


def _web(cliente, email="mkweb@ejemplo.com", director=True, activo=True):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant("Despacho " + email)
    db.asignar_tenant(uid, t)
    if director:
        db.asignar_supervisor_tenant(uid, True)
    if activo:
        verticales.fijar_activo(t, "comercial", True)
    db.guardar_datos_tenant(t, "B12345678", "Calle Mayor 1, Barcelona")
    return uid, t


def test_las_pantallas_responden_y_el_flujo_completo_funciona(cliente, monkeypatch):
    for v, x in (("MARKETING_SMTP_HOST", "h"), ("MARKETING_SMTP_USUARIO", "u"), ("MARKETING_SMTP_CONTRASENA", "p"), ("MARKETING_SMTP_REMITENTE", "r@x")):
        monkeypatch.setenv(v, x)
    uid, t = _web(cliente)
    for ruta in ("/", "/consentimientos", "/grupos", "/plantillas", "/plantillas/nueva", "/envios", "/envios/nuevo"):
        r = cliente.get("/comercial/marketing" + ruta)
        assert r.status_code == 200, ruta
    assert "Marketing" in cliente.get("/comercial/").get_data(as_text=True)

    for i in range(2):
        nucleo.crear_cliente(t, f"Cliente {i}", email=f"c{i}@x.example", etiquetas=["vip"])
    r = cliente.post("/comercial/marketing/consentimientos", data={"email": "c0@x.example", "origen": "formulario", "evidencia": "Casilla web 12/10/2026"})
    assert r.status_code == 302
    assert cliente.post("/comercial/marketing/consentimientos", data={"email": "c1@x.example", "origen": "verbal", "evidencia": ""}, follow_redirects=True).get_data(as_text=True).count("prueba") >= 1
    assert "c0@x.example" in cliente.get("/comercial/marketing/consentimientos").get_data(as_text=True)

    assert cliente.post("/comercial/marketing/grupos", data={"nombre": "VIP", "fuente": "clientes", "etiquetas": "vip"}).status_code == 302
    gh = cliente.get("/comercial/marketing/grupos").get_data(as_text=True)
    assert "VIP" in gh and "1 destinatarios" in gh and "sin consentimiento 1" in gh
    gid = mk.listar_grupos(t)[0]["id"]
    csv = cliente.get(f"/comercial/marketing/grupos/{gid}/audiencia.csv")
    assert csv.mimetype == "text/csv" and b"c0@x.example" in csv.data and b"c1@x.example" not in csv.data

    r = cliente.post("/comercial/marketing/plantillas/nueva", data={"nombre": "Novedades", "asunto": "Hola {{nombre}}", "tipo": ["titulo", "texto", "boton"],
                                                                     "texto": ["Novedad", "Hola {{nombre}}", "Ver"], "url": ["", "", "https://ejemplo.com"]})
    assert r.status_code == 302
    pid = mk.listar_plantillas(t)[0]["id"]
    prev = cliente.post(f"/comercial/marketing/plantillas/{pid}", data={"nombre": "Novedades", "asunto": "x", "accion": "previsualizar", "tipo": ["texto"], "texto": ["<b>Hola</b>"], "url": [""]}).get_data(as_text=True)
    assert "srcdoc" in prev and "Darme de baja" in prev
    mal = cliente.post("/comercial/marketing/plantillas/nueva", data={"nombre": "X", "asunto": "Y", "tipo": ["boton"], "texto": ["Ir"], "url": ["javascript:alert(1)"]})
    assert mal.status_code == 200 and "https://" in mal.get_data(as_text=True)

    r = cliente.post("/comercial/marketing/envios/nuevo", data={"nombre": "Octubre", "grupo_id": gid, "plantilla_id": pid})
    assert r.status_code == 302
    url = r.headers["Location"]
    ver = cliente.get(url).get_data(as_text=True)
    assert "1 destinatarios con consentimiento" in ver and "Programar el envío" in ver
    mal = cliente.post(url + "/programar", data={"confirmacion": "5"}, follow_redirects=True).get_data(as_text=True)
    assert "Escribe 1" in mal
    prueba = []
    monkeypatch.setattr(mk, "_enviar_smtp", lambda *a: prueba.append(a))
    assert cliente.post(url + "/prueba", data={"email": "yo@despacho.example"}).status_code == 302 and prueba and prueba[0][1].startswith("[PRUEBA]")
    assert cliente.post(url + "/programar", data={"confirmacion": "1"}).status_code == 302
    assert "Programado" in cliente.get(url).get_data(as_text=True) or "programado" in cliente.get(url).get_data(as_text=True)
    assert mk.obtener_envio(t, mk.listar_envios(t)[0]["id"])["estado"] == "programado"


def test_solo_la_direccion_programa_y_sin_el_modulo_no_existe(cliente):
    uid, t = _web(cliente, director=False)
    nucleo.crear_cliente(t, "C", email="c@x.example")
    mk.registrar_consentimiento(t, uid, "c@x.example", origen="formulario", evidencia="x")
    g = mk.crear_grupo(t, uid, "Todos", {})
    eid = mk.crear_envio(t, uid, "E", g, "Hola", [{"tipo": "texto", "texto": "Hola"}])
    r = cliente.post(f"/comercial/marketing/envios/{eid}/programar", data={"confirmacion": "1"}, follow_redirects=True)
    assert "dirección" in r.get_data(as_text=True)
    verticales.fijar_activo(t, "comercial", False)
    assert cliente.get("/comercial/marketing/").status_code == 404


def test_la_baja_de_un_clic_es_publica_firmada_y_definitiva(cliente):
    uid, t = _web(cliente)
    mk.registrar_consentimiento(t, uid, "ana@x.example", origen="formulario", evidencia="x")
    tok = mk.token_baja(t, "ana@x.example")
    assert "Darme de baja" in cliente.get(f"/baja/{tok}").get_data(as_text=True) and mk.obtener_contacto(t, "ana@x.example")["estado"] == "consentido"
    assert "te hemos dado de baja" in cliente.post(f"/baja/{tok}").get_data(as_text=True)
    assert mk.obtener_contacto(t, "ana@x.example")["estado"] == "baja"
    assert cliente.get("/baja/manipulado").status_code == 404 and cliente.post(f"/baja/{tok[:-2]}00").status_code == 404
