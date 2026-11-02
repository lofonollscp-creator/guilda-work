"""Pantallas de los documentos para firmar desde la ficha del cliente (app/rutas_documentos_firma.py). Con Kratos real."""
from app import db, documentos_firma as df, documenso, nucleo
from tests.conftest import iniciar_sesion_de_prueba


def _web(cliente, email="firmasweb@ejemplo.com", director=True):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant("Despacho " + email)
    db.asignar_tenant(uid, t)
    if director:
        db.asignar_supervisor_tenant(uid, True)
    db.guardar_datos_tenant(t, "B12345678", "Calle Mayor 1, Barcelona")
    db.guardar_documenso_api_key(t, "clave")
    c = nucleo.crear_cliente(t, "Cliente Web SL", nif="B87654321", email="cliente@web.example", direccion="Av. Diagonal 100")
    return uid, t, c


def test_la_ficha_ofrece_los_documentos_y_el_flujo_completo(cliente, monkeypatch):
    uid, t, c = _web(cliente)
    r = cliente.get(f"/clientes/{c}?pestana=documentos")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Documentos para firmar" in html and "Hoja de encargo profesional" in html and "Orden de domiciliación SEPA" in html

    r = cliente.get(f"/documentos-firma/clientes/{c}/nuevo/mandato_sepa")
    assert r.status_code == 200 and "IBAN" in r.get_data(as_text=True) and "cliente@web.example" in r.get_data(as_text=True)
    mal = cliente.post(f"/documentos-firma/clientes/{c}/crear/mandato_sepa", data={"iban": "ES00 1234", "acreedor_sepa": "ES12ZZZ1"})
    assert mal.status_code == 400 and "IBAN" in mal.get_data(as_text=True)

    r = cliente.post(f"/documentos-firma/clientes/{c}/crear/mandato_sepa", data={"iban": "ES91 2100 0418 4502 0005 1332", "acreedor_sepa": "ES12ZZZ12345678", "lugar": "Barcelona",
                                                                                  "firmante_email": "cliente@web.example"})
    assert r.status_code == 302
    did = int(r.headers["Location"].rstrip("/").split("/")[-1])
    ver = cliente.get(f"/documentos-firma/clientes/{c}/{did}").get_data(as_text=True)
    assert "ES9121000418450200051332" in ver and "Enviar a firmar" in ver
    pdf = cliente.get(f"/documentos-firma/clientes/{c}/{did}/pdf")
    assert pdf.status_code == 200 and pdf.mimetype == "application/pdf" and pdf.data.startswith(b"%PDF")

    monkeypatch.setattr(documenso, "crear_documento", lambda *a, **k: {"id": "env_web"})
    monkeypatch.setattr(documenso, "enviar_a_firma", lambda *a: {})
    r = cliente.post(f"/documentos-firma/clientes/{c}/{did}/enviar")
    assert r.status_code == 302 and "aviso=enviado" in r.headers["Location"]
    assert "Pendiente de firma" in cliente.get(f"/documentos-firma/clientes/{c}/{did}").get_data(as_text=True)
    assert "ya se envió" in cliente.post(f"/documentos-firma/clientes/{c}/{did}/enviar", follow_redirects=True).get_data(as_text=True)
    assert df.obtener(t, c, did)["estado"] == "enviado"


def test_otro_despacho_recibe_404(cliente):
    ajeno = db.crear_tenant("Despacho ajeno")
    u_ajeno = db.crear_usuario_vinculado_a_kratos("ajeno@ejemplo.com", "k-ajeno")
    db.asignar_tenant(u_ajeno, ajeno)
    db.guardar_datos_tenant(ajeno, "B11111111", "Calle Ajena 1")
    c_ajeno = nucleo.crear_cliente(ajeno, "Cliente ajeno", nif="B22222222", direccion="X 1", email="ajeno@cliente.example")
    did = df.crear_borrador(ajeno, u_ajeno, c_ajeno, "hoja_encargo", {"servicios": "x", "honorarios": "y"})
    uid, t, c = _web(cliente)
    assert cliente.get(f"/documentos-firma/clientes/{c_ajeno}/{did}").status_code == 404
    assert cliente.get(f"/documentos-firma/clientes/{c}/{did}").status_code == 404
    assert cliente.get(f"/documentos-firma/clientes/{c_ajeno}/nuevo/hoja_encargo").status_code == 404
    assert cliente.get(f"/documentos-firma/clientes/{c}/nuevo/no_existe").status_code == 404


def test_la_direccion_edita_los_textos_y_los_demas_solo_los_ven(cliente):
    uid, t, c = _web(cliente)
    assert "Textos" in cliente.get("/documentos-firma/plantillas").get_data(as_text=True)
    r = cliente.post("/documentos-firma/plantillas/hoja_encargo", data={"texto": "# Mía\nPara {{cliente.nombre}}"})
    assert "Texto guardado" in r.get_data(as_text=True) and df.texto_de(t, "hoja_encargo")[1]
    r = cliente.post("/documentos-firma/plantillas/hoja_encargo", data={"texto": "Hola {{inventada}}"})
    assert "inventada" in r.get_data(as_text=True)
    assert cliente.get("/documentos-firma/plantillas/no_existe").status_code == 404
    cliente.post("/documentos-firma/plantillas/hoja_encargo", data={"accion": "restaurar"})
    assert not df.texto_de(t, "hoja_encargo")[1]


def test_recordar_la_firma_y_los_dias_del_aviso_automatico(cliente, monkeypatch):
    uid, t, c = _web(cliente, "recordarweb@ejemplo.com")
    monkeypatch.setattr(documenso, "crear_documento", lambda *a, **k: {"id": "env_rw"})
    monkeypatch.setattr(documenso, "enviar_a_firma", lambda *a: {})
    monkeypatch.setattr(documenso, "estado_documento", lambda *a: "PENDING")
    monkeypatch.setattr(documenso, "reenviar_a_firma", lambda *a: 1)
    did = df.crear_borrador(t, uid, c, "consentimiento_comercial", {"contacto_rgpd": "datos@despacho.example"}, lugar="Barcelona")
    df.enviar(t, uid, c, did)
    ver = cliente.get(f"/documentos-firma/clientes/{c}/{did}").get_data(as_text=True)
    assert "Recordar la firma" in ver
    assert cliente.post(f"/documentos-firma/clientes/{c}/{did}/recordar").status_code == 302
    assert df.obtener(t, c, did)["recordatorios"] == 1
    assert "recordado 1" in cliente.get(f"/documentos-firma/clientes/{c}/{did}").get_data(as_text=True)
    assert "Recordar a quien no firma" in cliente.get("/documentos-firma/plantillas").get_data(as_text=True)
    assert cliente.post("/documentos-firma/plantillas/recordatorio", data={"dias": "5"}).status_code == 302
    assert df.recordatorio_dias(t) == 5
    r = cliente.post("/documentos-firma/plantillas/recordatorio", data={"dias": "99"})
    assert "error=" in r.headers["Location"] and df.recordatorio_dias(t) == 5


def test_el_panel_de_firmas_pendientes_y_su_boton_de_recordar(cliente, monkeypatch):
    uid, t, c = _web(cliente, "pendientesweb@ejemplo.com")
    monkeypatch.setattr(documenso, "crear_documento", lambda *a, **k: {"id": "env_pw"})
    monkeypatch.setattr(documenso, "enviar_a_firma", lambda *a: {})
    monkeypatch.setattr(documenso, "estado_documento", lambda *a: "PENDING")
    monkeypatch.setattr(documenso, "reenviar_a_firma", lambda *a: 1)
    assert "No hay firmas pendientes" in cliente.get("/documentos-firma/pendientes").get_data(as_text=True)
    did = df.crear_borrador(t, uid, c, "consentimiento_comercial", {"contacto_rgpd": "datos@despacho.example"}, lugar="Barcelona")
    df.enviar(t, uid, c, did)
    html = cliente.get("/documentos-firma/pendientes").get_data(as_text=True)
    assert "Cliente Web SL" in html and "Recordar la firma" in html and "0/3" in html
    r = cliente.post(f"/documentos-firma/pendientes/{c}/{did}/recordar")
    assert r.status_code == 302 and "aviso=recordado" in r.headers["Location"]
    assert "1/3" in cliente.get("/documentos-firma/pendientes").get_data(as_text=True) and "Firmas pendientes" in cliente.get("/documentos-firma/plantillas").get_data(as_text=True)
