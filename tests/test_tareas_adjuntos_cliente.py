"""Archivos del cliente en sus comentarios del portal: solo PDF e imágenes comprobados por contenido, límites, aislamiento y descarga segura."""
import pytest

from app import db, tareas_trabajo as tt
from tests.test_tareas_portal_cliente import _entrar_como_cliente, _guardados, _mundo, _portal, _tarea_comentable

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 40


def _subir(portal, tid, archivos, texto="Os mando los documentos"):
    return portal.post(f"/portal/tareas/{tid}/comentarios", data={"texto": texto, "archivos": [(__import__("io").BytesIO(c), n) for n, c in archivos]}, content_type="multipart/form-data")


def _filas_adjuntos(tid):
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT id, comentario_id, nombre_archivo, tipo_mime, tamano_bytes, cliente_fiscal_id FROM tarea_comentarios_cliente_adjuntos WHERE tarea_id = ? ORDER BY id", (tid,))]
    finally:
        conn.close()


def test_el_cliente_envia_archivos_y_los_ve_y_descarga_el_equipo_tambien(cliente):
    uid, t, c1, c2 = _mundo(cliente, "ad1@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    portal = _portal(cliente, c1)
    assert _subir(portal, tid, [("factura.pdf", PDF), ("foto.png", PNG)]).status_code == 302
    filas = _filas_adjuntos(tid)
    assert [(f["nombre_archivo"], f["tipo_mime"]) for f in filas] == [("factura.pdf", "application/pdf"), ("foto.png", "image/png")]
    html = portal.get("/portal/").get_data(as_text=True)
    assert "factura.pdf" in html and "foto.png" in html
    r = portal.get(f"/portal/tareas/adjuntos/{filas[0]['id']}")
    assert r.status_code == 200 and r.data == PDF and r.mimetype == "application/pdf" and "attachment" in r.headers["Content-Disposition"] and r.headers["X-Content-Type-Options"] == "nosniff"
    ficha = cliente.get(f"/tareas/{tid}").get_data(as_text=True)
    assert "factura.pdf" in ficha and f"/tareas/cliente-adjuntos/{filas[0]['id']}" in ficha
    r = cliente.get(f"/tareas/cliente-adjuntos/{filas[1]['id']}")
    assert r.status_code == 200 and r.data == PNG and "attachment" in r.headers["Content-Disposition"] and "sandbox" in r.headers["Content-Security-Policy"]


@pytest.mark.parametrize("nombre,contenido", [
    ("virus.exe", b"MZ\x90\x00"), ("pagina.html", b"<script>alert(1)</script>"), ("dibujo.svg", b"<svg onload=alert(1)/>"),
    ("falso.pdf", b"<script>alert(1)</script>"), ("falsa.png", PDF), ("vacio.pdf", b""), ("clave.pdf", b"%PDF-1.4\n-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"),
])
def test_lo_que_no_es_pdf_o_imagen_de_verdad_se_rechaza_y_no_se_guarda_ni_el_texto(cliente, nombre, contenido):
    uid, t, c1, c2 = _mundo(cliente, "ad2@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    portal = _portal(cliente, c1)
    r = _subir(portal, tid, [(nombre, contenido)], "Texto que tampoco debe quedar")
    assert r.status_code == 302 and "aviso=" in r.headers["Location"]
    assert _guardados(tid) == [] and _filas_adjuntos(tid) == []                                       # todo o nada


def test_limites_por_comentario_tamano_y_por_tarea(cliente):
    uid, t, c1, c2 = _mundo(cliente, "ad3@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    portal = _portal(cliente, c1)
    cuatro = [(f"f{i}.png", PNG + bytes([i])) for i in range(4)]
    assert "aviso=" in _subir(portal, tid, cuatro).headers["Location"] and _filas_adjuntos(tid) == []
    grande = PDF + b"0" * (tt.MAX_ADJUNTO_CLIENTE_BYTES)
    assert "aviso=" in _subir(portal, tid, [("grande.pdf", grande)]).headers["Location"] and _filas_adjuntos(tid) == []
    for i in range(5):                                                                                 # 5 comentarios x 3 = 15
        _subir(portal, tid, [(f"a{i}{j}.png", PNG + bytes([i, j])) for j in range(3)])
    assert len(_filas_adjuntos(tid)) == tt.MAX_ADJUNTOS_CLIENTE_POR_TAREA
    antes = len(_guardados(tid))
    assert "aviso=" in _subir(portal, tid, [("otro.png", PNG + b"zz")]).headers["Location"] and len(_guardados(tid)) == antes


def test_el_mismo_archivo_dos_veces_en_un_comentario_se_guarda_una_vez(cliente):
    uid, t, c1, c2 = _mundo(cliente, "ad4@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    _subir(_portal(cliente, c1), tid, [("a.pdf", PDF), ("copia.pdf", PDF)])
    assert len(_filas_adjuntos(tid)) == 1


def test_cada_cliente_descarga_solo_los_suyos(cliente):
    uid, t, c1, c2 = _mundo(cliente, "ad5@ejemplo.com")
    tid = db.crear_tarea_outlook(uid, asunto="Compartida", cliente_fiscal_id=c1)
    tt.fijar_clientes(uid, tid, [c1, c2], c1)
    tt.fijar_visible_cliente(uid, tid, True, True)
    p1, p2 = _portal(cliente, c1), _portal(cliente, c2)
    _subir(p1, tid, [("secreto-uno.pdf", PDF)])
    aid = _filas_adjuntos(tid)[0]["id"]
    assert p1.get(f"/portal/tareas/adjuntos/{aid}").status_code == 200
    assert p2.get(f"/portal/tareas/adjuntos/{aid}").status_code == 404                                # otro cliente de la misma tarea
    assert "secreto-uno.pdf" not in p2.get("/portal/").get_data(as_text=True)
    otro_t = db.crear_tenant("Otro despacho adjuntos cliente")
    ajeno = db.crear_cliente_fiscal(otro_t, "Cliente ajeno", email="ajeno-ad5@ejemplo.com")
    assert _portal(cliente, ajeno).get(f"/portal/tareas/adjuntos/{aid}").status_code == 404
    assert cliente.application.test_client().get(f"/portal/tareas/adjuntos/{aid}").status_code in (302, 401, 403, 404)      # sin sesión


def test_al_ocultar_el_comentario_o_dejar_de_ensenar_la_tarea_el_archivo_deja_de_verse(cliente):
    uid, t, c1, c2 = _mundo(cliente, "ad6@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    portal = _portal(cliente, c1)
    _subir(portal, tid, [("oculto.pdf", PDF)])
    aid, cid = _filas_adjuntos(tid)[0]["id"], _guardados(tid)[0]["id"]
    assert cliente.post(f"/tareas/cliente-comentarios/{cid}/ocultar").status_code == 302
    assert portal.get(f"/portal/tareas/adjuntos/{aid}").status_code == 404 and cliente.get(f"/tareas/cliente-adjuntos/{aid}").status_code == 404
    assert "oculto.pdf" not in cliente.get(f"/tareas/{tid}").get_data(as_text=True)
    tid2 = _tarea_comentable(uid, t, c1, asunto="Segunda")
    _subir(portal, tid2, [("visible.pdf", PDF)])
    aid2 = [f for f in _filas_adjuntos(tid2)][0]["id"]
    tt.fijar_visible_cliente(uid, tid2, False)
    assert portal.get(f"/portal/tareas/adjuntos/{aid2}").status_code == 404 and cliente.get(f"/tareas/cliente-adjuntos/{aid2}").status_code == 200       # el equipo conserva lo recibido


def test_el_equipo_de_otro_despacho_no_descarga_y_la_api_solo_da_metadatos(cliente):
    from tests.test_api_tareas import _usuario
    uid, t, c1, c2 = _mundo(cliente, "ad7@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    _subir(_portal(cliente, c1), tid, [("datos.pdf", PDF)])
    aid = _filas_adjuntos(tid)[0]["id"]
    ajeno = cliente.application.test_client()
    from tests.conftest import iniciar_sesion_de_prueba
    iniciar_sesion_de_prueba(ajeno, "ad7-ajeno@ejemplo.com", "contrasena123")
    assert ajeno.get(f"/tareas/cliente-adjuntos/{aid}").status_code == 404
    lista = tt.conversaciones_con_clientes(uid, tid)[0]["mensajes"][0]["adjuntos"]
    assert lista == [{"id": aid, "nombre": "datos.pdf", "tipo": "application/pdf", "tamano": len(PDF)}] and "contenido" not in lista[0]


def test_borrar_cliente_o_despacho_borra_sus_archivos(cliente):
    uid, t, c1, c2 = _mundo(cliente, "ad8@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    _subir(_portal(cliente, c1), tid, [("a.pdf", PDF)])
    assert len(_filas_adjuntos(tid)) == 1
    conn = db.get_connection()
    try:
        tt.desvincular_cliente(conn, t, c1)
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM tarea_comentarios_cliente_adjuntos").fetchone()[0] == 0
    finally:
        conn.close()
