"""«Tus datos» (Q9): copia en ZIP de lo del cliente y solicitud de supresión como conversación con la gestoría."""
import io
import json
import zipfile

from app import db, portal_conversaciones as pc, portal_datos as pd
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_facturas_contables import PDF
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures


def _con_datos(t, u, c):
    from app import facturas_contables as fc, portal_peticiones as pp
    ficha = _ficha(c)
    fc.subir_archivos(t, u, c, "recibida", [("factura-luz.pdf", "application/pdf", PDF + b"1")])
    pp.crear(ficha, "Extracto del 3T", por=u)
    cid = pc.iniciar(ficha, "Una duda", "¿Puedo deducir esto?", "cliente", "titular@ejemplo.com", archivos=[("nomina.pdf", "application/pdf", PDF + b"2")])
    pc.responder(ficha, cid, "Sí.", "despacho", "eq@despacho.com")
    return ficha


def test_el_zip_lleva_datos_conversaciones_facturas_y_documentos_y_nada_interno():
    t, u, c = _despacho("Datos zip")
    ficha = _con_datos(t, u, c)
    z = zipfile.ZipFile(io.BytesIO(pd.zip_de_mis_datos(ficha, "titular@ejemplo.com")))
    nombres = z.namelist()
    assert {"datos.json", "conversaciones.json", "facturas.csv", "LEEME.txt"} <= set(nombres)
    docs = [n for n in nombres if n.startswith("documentos/")]
    assert len(docs) == 2 and any("factura-luz" in n for n in docs) and any("nomina" in n for n in docs)
    datos = json.loads(z.read("datos.json"))
    assert datos["cliente"]["nombre"] == "Cliente P SL" and datos["solicitado_por"] == "titular@ejemplo.com" and datos["peticiones"][0]["titulo"] == "Extracto del 3T"
    conv = json.loads(z.read("conversaciones.json"))
    assert conv[0]["asunto"] == "Una duda" and [m["de"] for m in conv[0]["mensajes"]] == ["yo", "la gestoría"] and conv[0]["mensajes"][0]["adjuntos"] == ["nomina.pdf"]
    lineas_csv = z.read("facturas.csv").decode("utf-8-sig").splitlines()
    assert lineas_csv[0] == "Fecha;Número;Tipo;Proveedor o cliente;NIF;Base imponible;IVA;Total;Estado" and len(lineas_csv) == 2 and lineas_csv[1].endswith(";pendiente")
    crudo = b"".join(z.read(n) for n in nombres if not n.startswith("documentos/")).decode("utf-8", "ignore")
    assert "notas internas" not in crudo.lower() and "cuenta_linea" not in crudo and "responsable_id" not in crudo


def test_los_documentos_que_no_caben_se_listan_como_omitidos(monkeypatch):
    t, u, c = _despacho("Datos tope")
    ficha = _con_datos(t, u, c)
    monkeypatch.setattr(pd, "TOPE_DOCUMENTOS_BYTES", 10)
    z = zipfile.ZipFile(io.BytesIO(pd.zip_de_mis_datos(ficha, "titular@ejemplo.com")))
    assert not [n for n in z.namelist() if n.startswith("documentos/")] and "omitidos.txt" in z.namelist() and "no cabe" in z.read("omitidos.txt").decode()


def test_el_nombre_de_un_documento_no_puede_escapar_del_zip():
    for peligroso in ("../../etc/passwd", "a/b\\c.pdf", "/absoluto/x.pdf", "C:\\windows\\x.pdf"):
        n = pd._nombre_seguro(peligroso, 1)
        assert "/" not in n and "\\" not in n and n.startswith("001-") and not n.startswith("..")
    assert pd._nombre_seguro("", 3).startswith("003-") and len(pd._nombre_seguro("x" * 500, 4)) <= 84


def test_la_descarga_web_es_solo_del_titular_y_queda_en_la_auditoria(cliente, correo):
    t, u, c = _despacho("Datos web")
    _con_datos(t, u, c)
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "Descargar mis datos" in _html(cliente, "/portal/cuenta")
    r = cliente.post("/portal/mis-datos")
    assert r.status_code == 200 and r.mimetype == "application/zip" and "attachment" in r.headers["Content-Disposition"] and zipfile.is_zipfile(io.BytesIO(r.data)) and "no-store" in r.headers["Cache-Control"]
    conn = db.get_connection()
    acciones = [x["accion"] for x in conn.execute("SELECT accion FROM auditoria_eventos WHERE tenant_id = ?", (t,)).fetchall()]
    conn.close()
    assert "portal.datos_descargados" in acciones
    assert cliente.get("/portal/mis-datos").status_code == 405


def test_quien_solo_consulta_no_descarga_ni_pide_la_supresion(cliente, correo):
    from app import portal_personas
    t, u, c = _despacho("Datos consulta")
    portal_personas.anadir(_ficha(c), "lector@ejemplo.com", "Lector", "consulta", por=u)
    _entrar(cliente, c, "lector@ejemplo.com")
    assert "Descargar mis datos" not in _html(cliente, "/portal/cuenta")
    assert cliente.post("/portal/mis-datos").status_code == 403 and cliente.post("/portal/pedir-supresion", data={"confirmo": "1"}).status_code == 403
    assert pc.listar(_ficha(c)) == []


def test_pedir_la_supresion_abre_una_conversacion_y_avisa_al_equipo(cliente, correo):
    t, u, c = _despacho("Datos supresion")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert cliente.post("/portal/pedir-supresion", data={}).status_code == 403                    # hace falta confirmar
    r = cliente.post("/portal/pedir-supresion", data={"confirmo": "1"})
    assert r.status_code == 302 and "/portal/conversaciones/" in r.headers["Location"]
    h = pc.listar(_ficha(c))[0]
    assert h["asunto"].startswith("Solicitud de supresión") and h["iniciada_por"] == "cliente"
    c_ = pc.obtener(_ficha(c), h["id"])
    assert "artículo 17 del RGPD" in c_["mensajes"][0]["texto"]
    notis = db.get_connection().execute("SELECT titulo FROM notificaciones WHERE usuario_id = ?", (u,)).fetchall()
    assert any("supresión" in n["titulo"].lower() for n in notis)
    conn = db.get_connection()
    acciones = [x["accion"] for x in conn.execute("SELECT accion FROM auditoria_eventos WHERE tenant_id = ?", (t,)).fetchall()]
    conn.close()
    assert "portal.supresion_solicitada" in acciones
