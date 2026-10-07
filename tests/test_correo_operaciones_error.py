"""Detalle de los cambios de correo que el servidor no aceptó: verlos, reintentarlos o descartarlos."""
from app import correo, db
from tests.conftest import iniciar_sesion_de_prueba


def _preparar(cliente, email):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    cuenta = db.crear_cuenta_correo(uid, "Mi cuenta", "imap", "h", 993, "u")
    conn = db.get_connection()
    conn.execute("INSERT INTO correo_mensajes (cuenta_id, carpeta, uid, asunto, remitente, descargado_en) VALUES (?, 'INBOX', '7', 'Factura rara', 'a@b.c', '2026-10-01')", (cuenta,))
    ids = []
    for uid_m, op, estado in (("7", "leido", "error"), ("7", "destacar", "error"), ("8", "eliminar", "pendiente")):
        ids.append(conn.execute(
            "INSERT INTO correo_operaciones (cuenta_id, carpeta, uid, operacion, creada_en, intentos, ultimo_error, estado) VALUES (?, 'INBOX', ?, ?, '2026-10-01', 5, 'NO [CANNOT] boom', ?)",
            (cuenta, uid_m, op, estado)).lastrowid)
    conn.commit()
    conn.close()
    return uid, cuenta, ids


def test_se_listan_solo_las_con_error_con_asunto(cliente):
    uid, _, ids = _preparar(cliente, "oe-1@x.com")
    lista = db.operaciones_correo_con_error(uid)
    assert [o["id"] for o in lista] == ids[:2] and lista[0]["asunto"] == "Factura rara" and lista[0]["cuenta_nombre"] == "Mi cuenta"
    html = cliente.get("/correo/cuentas").get_data(as_text=True)
    assert "Factura rara" in html and "NO [CANNOT] boom" in html and "Reintentar todos" in html
    otro = db.crear_usuario("oe-1b@x.com", "contrasena123")
    assert db.operaciones_correo_con_error(otro) == []


def test_reintentar_y_descartar_respetan_al_usuario(cliente, monkeypatch):
    lanzados = []
    monkeypatch.setattr(correo, "procesar_operaciones_cuenta", lambda c, e=0: lanzados.append(c))
    uid, cuenta, ids = _preparar(cliente, "oe-2@x.com")
    otro = db.crear_usuario("oe-2b@x.com", "contrasena123")
    assert db.reintentar_operaciones_correo(otro) == [] and db.descartar_operaciones_correo(otro) == 0
    assert db.reintentar_operaciones_correo(uid, []) == [] and db.descartar_operaciones_correo(uid, []) == 0
    assert cliente.post("/correo/cuentas/operaciones/reintentar", data={"id": [str(ids[0]), "x"]}).status_code == 302
    conn = db.get_connection()
    fila = conn.execute("SELECT estado, intentos, ultimo_error FROM correo_operaciones WHERE id = ?", (ids[0],)).fetchone()
    conn.close()
    assert tuple(fila) == ("pendiente", 0, None) and [o["id"] for o in db.operaciones_correo_con_error(uid)] == [ids[1]]
    assert cliente.post("/correo/cuentas/operaciones/descartar", data={"todas": "1"}).status_code == 302
    assert db.operaciones_correo_con_error(uid) == []
    conn = db.get_connection()
    restantes = [r[0] for r in conn.execute("SELECT id FROM correo_operaciones ORDER BY id")]
    conn.close()
    assert ids[0] in restantes and ids[2] in restantes and ids[1] not in restantes      # las pendientes no se tocan
    import time; time.sleep(0.2)
    assert lanzados == [cuenta]
