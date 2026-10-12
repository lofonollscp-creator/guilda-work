"""Pantallas del núcleo (app/rutas_nucleo.py): clientes, expedientes, plazos y horas, con sus permisos."""
import io
from datetime import date, timedelta

import pytest

from app import almacen_documentos as alm
from app import db, nucleo, verticales
from tests.conftest import iniciar_sesion_de_prueba


def _con_despacho(cliente, email="nucleo@ejemplo.com", supervisor=False):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant(f"Despacho {email}")
    db.asignar_tenant(uid, t)
    if supervisor:
        conn = db.get_connection(); conn.execute("UPDATE usuarios SET supervisor_tenant = 1 WHERE id = ?", (uid,)); conn.commit(); conn.close()
    return uid, t


def test_las_pantallas_cargan_vacias_y_con_datos(cliente):
    uid, t = _con_despacho(cliente)
    for ruta in ("/clientes/", "/clientes/nuevo", "/expedientes/", "/expedientes/nuevo", "/plazos/", "/plazos/festivos", "/tiempo/"):
        r = cliente.get(ruta)
        assert r.status_code == 200, ruta
        assert "tareas-subnav" in r.get_data(as_text=True), ruta
    c = nucleo.crear_cliente(t, "Cliente <b>Uno</b>", nif="B12345678", etiquetas=["vip"])
    x = nucleo.crear_expediente(t, uid, c, "Asunto & compañía")
    nucleo.crear_plazo(t, uid, "Contestar", (date.today() + timedelta(days=2)).isoformat(), expediente_id=x)
    nucleo.registrar_parte(t, uid, "Estudio", minutos=75, expediente_id=x)
    for ruta in ("/clientes/", f"/clientes/{c}", "/expedientes/", f"/expedientes/{x}", "/plazos/", "/tiempo/", f"/clientes/?q=uno&etiqueta=vip&tipo=empresa"):
        html = cliente.get(ruta).get_data(as_text=True)
        assert "<b>Uno</b>" not in html, f"{ruta}: el nombre se escapa"
    assert "Asunto &amp; compañía" in cliente.get(f"/expedientes/{x}").get_data(as_text=True)
    assert "1 h 15" in cliente.get("/tiempo/").get_data(as_text=True).replace("\xa0", " ") or "1:15" in cliente.get("/tiempo/").get_data(as_text=True)


def test_crear_cliente_avisa_de_duplicados_y_deja_crear_igualmente(cliente):
    uid, t = _con_despacho(cliente)
    r = cliente.post("/clientes/nuevo", data={"nombre": "Ana Ruiz", "nif": "12345678Z", "etiquetas": "vip, renta"})
    assert r.status_code == 302
    cid = int(r.headers["Location"].rsplit("/", 1)[1])
    assert nucleo.etiquetas_de(cid) == ["renta", "vip"]
    r = cliente.post("/clientes/nuevo", data={"nombre": "Ana Ruiz", "nif": "12345678z"})
    assert r.status_code == 200 and "Ya hay clientes parecidos" in r.get_data(as_text=True) and nucleo.listar_clientes(t)[1] == 1
    r = cliente.post("/clientes/nuevo", data={"nombre": "Ana Ruiz", "nif": "12345678Z", "crear_igualmente": "1"})
    assert r.status_code == 302 and nucleo.listar_clientes(t)[1] == 2
    r = cliente.post("/clientes/nuevo", data={"nombre": " "})
    assert r.status_code == 400 and "nombre" in r.get_data(as_text=True).lower()


def test_ficha_de_cliente_editar_contactos_fusion_y_papelera(cliente):
    uid, t = _con_despacho(cliente)
    a, b = nucleo.crear_cliente(t, "Cliente A"), nucleo.crear_cliente(t, "Cliente B")
    assert cliente.post(f"/clientes/{a}/editar", data={"nombre": "Cliente A2", "email": "a@ejemplo.com", "etiquetas": "x, y", "idioma": "fr"}).status_code == 302
    assert nucleo.obtener_cliente(t, a)["nombre"] == "Cliente A2" and nucleo.etiquetas_de(a) == ["x", "y"] and nucleo.obtener_cliente(t, a)["idioma"] == "fr"
    r = cliente.post(f"/clientes/{a}/editar", data={"nombre": " "}, follow_redirects=True)
    assert "no puede quedar vacío" in r.get_data(as_text=True)
    cliente.post(f"/clientes/{a}/contactos", data={"nombre": "Contacto 1", "email": "k@ejemplo.com", "principal": "1"})
    k = nucleo.listar_contactos(t, a)[0]["id"]
    assert "Contacto 1" in cliente.get(f"/clientes/{a}").get_data(as_text=True)
    cliente.post(f"/clientes/{a}/contactos/{k}/eliminar")
    assert nucleo.listar_contactos(t, a) == []
    cliente.post(f"/clientes/{b}/fusionar", data={"destino_id": a})
    assert nucleo.obtener_cliente(t, b)["papelera_en"] and nucleo.listar_clientes(t)[1] == 1
    cliente.post(f"/clientes/{a}/papelera")
    assert nucleo.listar_clientes(t)[1] == 0
    cliente.post(f"/clientes/{a}/papelera", data={"restaurar": "1"})
    assert nucleo.listar_clientes(t)[1] == 1


def test_flujo_de_un_expediente_en_la_web(cliente):
    uid, t = _con_despacho(cliente)
    c = nucleo.crear_cliente(t, "Cliente")
    r = cliente.post("/expedientes/nuevo", data={"cliente_id": c, "titulo": "Constitución", "referencia": "E-1", "descripcion": "x"})
    assert r.status_code == 302
    x = int(r.headers["Location"].rsplit("/", 1)[1])
    assert cliente.post("/expedientes/nuevo", data={"cliente_id": c, "titulo": ""}).status_code == 200
    assert cliente.post(f"/expedientes/{x}/estado", data={"estado": "en_curso"}).status_code == 302
    assert nucleo.obtener_expediente(t, x, uid)["estado"] == "en_curso"
    cliente.post(f"/expedientes/{x}/estado", data={"estado": "inventado"})
    assert nucleo.obtener_expediente(t, x, uid)["estado"] == "en_curso"
    cliente.post(f"/expedientes/{x}/nota", data={"texto": "Llamar mañana"})
    cliente.post(f"/expedientes/{x}/plazos", data={"titulo": "Presentar", "fecha_limite": "2030-01-15", "critico": "1"})
    cliente.post(f"/expedientes/{x}/horas", data={"descripcion": "Estudio", "horas": "1", "minutos": "30", "fecha": date.today().isoformat(), "facturable": "1"})
    html = cliente.get(f"/expedientes/{x}").get_data(as_text=True)
    for texto in ("Llamar mañana", "Presentar", "Estudio", "Fatal"):
        assert texto in html, texto
    assert len(nucleo.listar_partes(t, uid)) == 1 and nucleo.listar_partes(t, uid)[0]["segundos"] == 5400
    cliente.post(f"/expedientes/{x}/editar", data={"titulo": "Constitución S.L.", "confidencial_presente": "1", "confidencial": "1"})
    e = nucleo.obtener_expediente(t, x, uid)
    assert e["titulo"] == "Constitución S.L." and e["confidencial"] == 1
    cliente.post(f"/expedientes/{x}/papelera")
    assert nucleo.listar_expedientes(t, uid)[1] == 0 and nucleo.listar_expedientes(t, uid, papelera=True)[1] == 1


def test_documentos_de_cliente_y_expediente_subir_bajar_borrar(cliente):
    uid, t = _con_despacho(cliente)
    c = nucleo.crear_cliente(t, "Cliente")
    x = nucleo.crear_expediente(t, uid, c, "Asunto")
    for base, ident in ((f"/clientes/{c}", "cliente_id"), (f"/expedientes/{x}", "expediente_id")):
        r = cliente.post(f"{base}/documentos", data={"archivo": (io.BytesIO(b"%PDF-1.4 hola"), 'ficha "rara".pdf'), "categoria": "Contratos"}, content_type="multipart/form-data")
        assert r.status_code == 302, base
    docs_c, docs_x = alm.listar(t, uid, cliente_id=c), alm.listar(t, uid, expediente_id=x)
    assert len(docs_x) == 1 and docs_x[0]["categoria"] == "Contratos"
    d = docs_x[0]["id"]
    r = cliente.get(f"/expedientes/{x}/documentos/{d}")
    assert r.status_code == 200 and r.data == b"%PDF-1.4 hola" and "attachment" in r.headers["Content-Disposition"] and r.headers["X-Content-Type-Options"] == "nosniff"
    assert '"' not in r.headers["Content-Disposition"].split("filename=", 1)[1].strip('"')
    assert cliente.get(f"/clientes/{c}/documentos/{d}").status_code == 200, "el documento de un expediente también es del cliente"
    otro = nucleo.crear_cliente(t, "Otro cliente")
    assert cliente.get(f"/clientes/{otro}/documentos/{d}").status_code == 404, "pero no se baja por la ficha de otro cliente"
    assert cliente.get(f"/expedientes/{x + 99}/documentos/{d}").status_code == 404
    assert cliente.get(f"/expedientes/{x}/documentos/999999").status_code == 404
    assert cliente.post(f"/clientes/{c}/documentos", data={}, content_type="multipart/form-data").status_code == 302
    cliente.post(f"/expedientes/{x}/documentos/{d}/eliminar")
    assert alm.listar(t, uid, expediente_id=x) == [] and docs_c


def test_plazos_en_la_web(cliente):
    uid, t = _con_despacho(cliente)
    c = nucleo.crear_cliente(t, "Cliente")
    cliente.post("/plazos/", data={"titulo": "Presentar escrito", "fecha_limite": (date.today() + timedelta(days=3)).isoformat(), "cliente_id": c, "avisos": "5,1"})
    p = nucleo.listar_plazos(t, uid)[0]
    assert p["avisos"] == "5,1" and p["cliente_id"] == c
    assert "Presentar escrito" in cliente.get("/plazos/").get_data(as_text=True)
    r = cliente.post("/plazos/", data={"titulo": "Mal", "fecha_limite": "ayer"}, follow_redirects=True)
    assert "no es válida" in r.get_data(as_text=True)
    cliente.post(f"/plazos/{p['id']}/cumplido")
    assert nucleo.listar_plazos(t, uid)[0]["estado"] == "cumplido" and "Presentar escrito" not in cliente.get("/plazos/").get_data(as_text=True)
    assert "Presentar escrito" in cliente.get("/plazos/?estado=cumplido").get_data(as_text=True)
    cliente.post(f"/plazos/{p['id']}/cumplido", data={"reabrir": "1"})
    cliente.post(f"/plazos/{p['id']}/mover", data={"fecha_limite": "2031-05-05"})
    assert nucleo.listar_plazos(t, uid)[0]["fecha_limite"] == "2031-05-05"
    r = cliente.post(f"/plazos/{p['id']}/revisar", follow_redirects=True)
    assert "otra persona" in r.get_data(as_text=True)
    cliente.post(f"/plazos/{p['id']}/eliminar")
    assert nucleo.listar_plazos(t, uid) == []


def test_festivos_solo_los_edita_un_responsable(cliente):
    uid, t = _con_despacho(cliente)
    assert cliente.post("/plazos/festivos", data={"fecha": "2026-11-09", "nombre": "La Almudena"}).status_code == 403
    conn = db.get_connection(); conn.execute("UPDATE usuarios SET supervisor_tenant = 1 WHERE id = ?", (uid,)); conn.commit(); conn.close()
    cliente.get("/clientes/")      # nueva petición: lee la fila actualizada
    assert cliente.post("/plazos/festivos", data={"fecha": "2026-11-09", "nombre": "La Almudena"}).status_code == 302
    assert "La Almudena" in cliente.get("/plazos/festivos?anio=2026").get_data(as_text=True)
    f = nucleo.listar_festivos(t)[0]["id"]
    cliente.post("/plazos/festivos", data={"eliminar": f})
    assert nucleo.listar_festivos(t) == []


def test_horas_resumen_exportaciones_y_facturacion(cliente):
    uid, t = _con_despacho(cliente, supervisor=True)
    c = nucleo.crear_cliente(t, "Cliente Horas")
    cliente.post("/tiempo/tarifa", data={"tarifa": "120,50"})
    assert nucleo.tarifa_de(uid) == 12050
    assert cliente.post("/tiempo/tarifa", data={"tarifa": "mucho"}, follow_redirects=True).status_code == 200
    cliente.post("/tiempo/", data={"descripcion": "=HYPERLINK(\"x\")", "horas": "2", "minutos": "0", "cliente_id": c, "facturable": "1", "fecha": date.today().isoformat()})
    html = cliente.get("/tiempo/").get_data(as_text=True)
    assert "Cliente Horas" in html and "241,00" in html
    r = cliente.get("/tiempo/hoja.csv")
    assert r.status_code == 200 and r.mimetype == "text/csv" and "'=HYPERLINK" in r.get_data(as_text=True), "una fórmula no llega a Excel como fórmula"
    r = cliente.get("/tiempo/hoja.pdf")
    assert r.status_code == 200 and r.data.startswith(b"%PDF")
    p = nucleo.listar_partes(t, uid)[0]["id"]
    cliente.post("/tiempo/facturar", data={"parte_id": p})
    assert nucleo.listar_partes(t, uid)[0]["facturado_en"]
    cliente.post(f"/tiempo/{p}/eliminar")
    assert len(nucleo.listar_partes(t, uid)) == 1, "un parte facturado no se borra"
    assert "Todo el equipo" in cliente.get("/tiempo/").get_data(as_text=True)


def test_facturar_horas_es_cosa_de_responsables(cliente):
    uid, t = _con_despacho(cliente)
    assert cliente.post("/tiempo/facturar", data={"parte_id": 1}).status_code == 403
    assert "Todo el equipo" not in cliente.get("/tiempo/").get_data(as_text=True)


def test_sin_despacho_no_hay_nada_que_ver(cliente):
    iniciar_sesion_de_prueba(cliente, "sindespacho@ejemplo.com", "contrasena123")
    for ruta in ("/clientes/", "/expedientes/", "/plazos/", "/tiempo/", "/clientes/nuevo"):
        assert cliente.get(ruta).status_code == 404, ruta


def test_otro_despacho_recibe_404_en_todo(cliente):
    uid, t = _con_despacho(cliente, "dueno@ejemplo.com")
    c = nucleo.crear_cliente(t, "Cliente ajeno")
    x = nucleo.crear_expediente(t, uid, c, "Expediente ajeno")
    z = nucleo.crear_plazo(t, uid, "Plazo ajeno", "2030-01-01", expediente_id=x)
    _, d = alm.guardar(uid, "a.txt", "text/plain", b"x", expediente_id=x)
    # segunda persona, de otro despacho, en el mismo cliente de pruebas
    otro = db.crear_usuario_vinculado_a_kratos("intruso@ejemplo.com", "kratos-intruso")
    t2 = db.crear_tenant("Despacho intruso")
    db.asignar_tenant(otro, t2)
    db.asignar_tenant(uid, t2)          # el usuario con sesión pasa al otro despacho
    cliente.get("/clientes/")
    for ruta in (f"/clientes/{c}", f"/expedientes/{x}", f"/expedientes/{x}/documentos/{d}", f"/clientes/{c}/documentos/{d}"):
        assert cliente.get(ruta).status_code == 404, ruta
    for ruta in (f"/clientes/{c}/editar", f"/expedientes/{x}/nota", f"/plazos/{z}/cumplido", f"/clientes/{c}/papelera"):
        r = cliente.post(ruta, data={"texto": "x", "nombre": "Robado"})
        assert r.status_code in (302, 404), ruta
    assert nucleo.obtener_cliente(t, c)["nombre"] == "Cliente ajeno" and nucleo.listar_plazos(t, uid)[0]["estado"] == "pendiente"
    assert nucleo.listar_expedientes(t2, uid)[1] == 0


def test_un_expediente_confidencial_da_404_a_quien_no_es_suyo(cliente):
    uid, t = _con_despacho(cliente)
    jefe = db.crear_usuario_vinculado_a_kratos("jefa@ejemplo.com", "kratos-jefa")
    db.asignar_tenant(jefe, t)
    c = nucleo.crear_cliente(t, "Cliente")
    x = nucleo.crear_expediente(t, jefe, c, "Reservado", confidencial=True)
    assert cliente.get(f"/expedientes/{x}").status_code == 404 and "Reservado" not in cliente.get("/expedientes/").get_data(as_text=True)
    assert cliente.post(f"/expedientes/{x}/nota", data={"texto": "hola"}).status_code in (302, 404)
    assert not any(e["tipo"] == "nota" for e in nucleo.linea_de_tiempo(t, jefe, x))


def test_el_menu_tiene_clientes_y_oculta_fiscal_si_el_modulo_no_esta(cliente):
    uid, t = _con_despacho(cliente)
    html = cliente.get("/clientes/").get_data(as_text=True)
    assert 'title="Clientes"' in html and "Calendario fiscal" in html and "Videollamadas" in html
    verticales.fijar_activo(t, "gestoria", False)
    html = cliente.get("/clientes/").get_data(as_text=True)
    assert "Calendario fiscal" not in html and "Videollamadas" in html and 'title="Clientes"' in html
    verticales.quitar_ajuste_manual(t, "gestoria")


def test_el_decorador_de_vertical_da_404_si_no_esta_activo(cliente):
    from flask import g
    from werkzeug.exceptions import NotFound
    from app.main import app

    uid, t = _con_despacho(cliente)

    @verticales.requiere_vertical("abogados")
    def vista():
        return "dentro"

    with app.test_request_context("/"):
        g.tenant_id = t
        with pytest.raises(NotFound):
            vista()
        verticales.fijar_activo(t, "abogados", True)
        assert vista() == "dentro"
        g.tenant_id = None
        with pytest.raises(NotFound):
            vista()


def test_sin_el_modulo_de_gestoria_las_pantallas_fiscales_no_existen(cliente):
    uid, t = _con_despacho(cliente)
    assert cliente.get("/fiscal/vencimientos").status_code == 200 and cliente.get("/fiscal/clientes").status_code == 200
    verticales.fijar_activo(t, "gestoria", False)
    for ruta in ("/fiscal/vencimientos", "/fiscal/clientes", "/fiscal/papelera"):
        assert cliente.get(ruta).status_code == 404, ruta
    assert cliente.get("/clientes/").status_code == 200 and cliente.get("/tareas/").status_code in (200, 302), "el núcleo y el resto siguen"
    verticales.quitar_ajuste_manual(t, "gestoria")
    assert cliente.get("/fiscal/vencimientos").status_code == 200
