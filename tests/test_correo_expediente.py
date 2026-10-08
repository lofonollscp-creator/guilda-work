"""Del correo al expediente del cliente: archivar adjuntos y el correo, reglas automáticas, descarga segura y permisos."""
import pytest

from app import correo, db
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_proyectos_paginas import _otro_cliente


def _preparar(cliente, email, adjuntos=()):
    return _sembrar(iniciar_sesion_de_prueba(cliente, email, "contrasena123"), email, adjuntos)


def _sembrar(uid, email, adjuntos=()):
    tenant = db.crear_tenant(f"Despacho exp {email}")
    db.asignar_tenant(uid, tenant)
    cli = db.crear_cliente_fiscal(tenant, "Sol y Mar SL", email="sol@mar.com")
    cuenta = db.crear_cuenta_correo(uid, "c", "imap", "h", 993, "u")
    conn = db.get_connection()
    mid = conn.execute(
        "INSERT INTO correo_mensajes (cuenta_id, carpeta, uid, asunto, remitente, destinatarios, fecha, cuerpo_texto, descargado_en) "
        "VALUES (?, 'INBOX', 1, 'Extractos: septiembre!', 'sol@mar.com', 'yo@x.com', '2026-10-02T10:00:00', 'Adjunto los extractos.', '2026-10-02')", (cuenta,)
    ).lastrowid
    conn.commit()
    conn.close()
    db.guardar_adjuntos_correo(mid, [{"nombre": n, "tipo": t, "bytes": b} for n, t, b in adjuntos])
    return uid, tenant, cli, mid


ADJ = [("extracto.pdf", "application/pdf", b"%PDF-1.4 extracto"), ("logo.png", "image/png", b"\x89PNG" + b"x" * 100), ("grande.png", "image/png", b"\x89PNG" + b"y" * 40000)]


def test_archivar_adjuntos_y_correo(cliente):
    uid, tenant, cli, mid = _preparar(cliente, "ex-1@x.com", ADJ)
    r = correo.archivar_correo_en_expediente(uid, mid, cli, guardar_correo=True, categoria="Extractos")
    assert r == {"archivados": 4, "duplicados": 0, "omitidos": 0}
    docs = {d["nombre_archivo"]: d for d in db.listar_documentos_cliente(tenant, cli)}
    assert set(docs) == {"extracto.pdf", "logo.png", "grande.png", "Correo 2026-10-02 - Extractos septiembre.txt"}
    assert docs["extracto.pdf"]["origen"] == "correo" and docs["extracto.pdf"]["categoria"] == "Extractos" and docs["extracto.pdf"]["asunto_origen"] == "Extractos: septiembre!"
    texto = bytes(db.obtener_documento_cliente(tenant, cli, docs["Correo 2026-10-02 - Extractos septiembre.txt"]["id"])["contenido"]).decode()
    assert "De: sol@mar.com" in texto and "Asunto: Extractos: septiembre!" in texto and "Adjunto los extractos." in texto
    assert db.obtener_mensaje_correo(mid)["cliente_fiscal_id"] == cli                         # y el correo queda vinculado al cliente
    # repetir no duplica
    assert correo.archivar_correo_en_expediente(uid, mid, cli, guardar_correo=True) == {"archivados": 0, "duplicados": 4, "omitidos": 0}
    assert len(db.listar_documentos_cliente(tenant, cli)) == 4


def test_solo_los_adjuntos_elegidos_y_modo_automatico_omite_logos(cliente):
    uid, tenant, cli, mid = _preparar(cliente, "ex-2@x.com", ADJ)
    ids = {a["nombre_archivo"]: a["id"] for a in db.listar_adjuntos_correo(mid)}
    assert correo.archivar_correo_en_expediente(uid, mid, cli, adjunto_ids=[ids["extracto.pdf"]])["archivados"] == 1
    assert correo.archivar_correo_en_expediente(uid, mid, cli, adjunto_ids=[])["archivados"] == 0
    r = correo.archivar_correo_en_expediente(uid, mid, cli, automatico=True)
    assert r == {"archivados": 1, "duplicados": 1, "omitidos": 1}                              # grande.png entra; logo.png (pequeña) no
    assert {d["nombre_archivo"] for d in db.listar_documentos_cliente(tenant, cli)} == {"extracto.pdf", "grande.png"}


def test_validaciones_del_archivado(cliente):
    uid, tenant, cli, mid = _preparar(cliente, "ex-3@x.com", ADJ)
    otro_tenant = db.crear_tenant("Otro despacho exp")
    ajeno_cli = db.crear_cliente_fiscal(otro_tenant, "De otro")
    with pytest.raises(correo.ErrorCorreo):
        correo.archivar_correo_en_expediente(uid, mid, ajeno_cli)                              # cliente de otro despacho
    with pytest.raises(correo.ErrorCorreo):
        correo.archivar_correo_en_expediente(uid, 99999, cli)
    otro = db.crear_usuario("ex-3b@x.com", "contrasena123")
    db.asignar_tenant(otro, tenant)
    with pytest.raises(correo.ErrorCorreo):
        correo.archivar_correo_en_expediente(otro, mid, cli)                                    # el correo es de otra persona, aunque sea del mismo despacho
    assert db.listar_documentos_cliente(tenant, cli) == []


def test_limites_y_nombres(cliente, monkeypatch):
    uid, tenant, cli, _ = _preparar(cliente, "ex-4@x.com")
    assert db.archivar_documento_cliente(uid, cli, "a", None, b"")[0] == "vacio"
    assert db.archivar_documento_cliente(uid, cli, "a", None, b"x" * (db.MAX_DOCUMENTO_CLIENTE_BYTES + 1))[0] == "grande"
    r, doc = db.archivar_documento_cliente(uid, cli, "../../etc/pa<s>s?wd.txt", None, b"hola", origen="inventado")
    fila = db.obtener_documento_cliente(tenant, cli, doc)
    assert (r, fila["nombre_archivo"], fila["tipo_mime"], fila["origen"]) == ("ok", "passwd.txt", "application/octet-stream", "subida")
    assert db.archivar_documento_cliente(uid, cli, "...", None, b"otro")[0] == "ok"
    assert db.obtener_documento_cliente(tenant, cli, 2)["nombre_archivo"] == "documento"
    monkeypatch.setattr(db, "MAX_DOCUMENTOS_POR_CLIENTE", 2)
    assert db.archivar_documento_cliente(uid, cli, "c", None, b"tercero")[0] == "limite"


def test_regla_automatica_archiva_al_llegar(cliente):
    uid, tenant, cli, mid = _preparar(cliente, "ex-5@x.com", ADJ)
    with pytest.raises(ValueError, match="elige el cliente"):
        db.crear_regla_correo(uid, "@mar.com", archivar_adjuntos=True, marcar_leido=True)
    db.crear_regla_correo(uid, "sol@mar.com", cliente_fiscal_id=cli, archivar_adjuntos=True)
    assert db.listar_reglas_correo(uid)[0]["archivar_adjuntos"] == 1
    correo._aplicar_categoria_automatica(uid, mid, "Sol <sol@mar.com>", "Extractos")
    assert {d["nombre_archivo"] for d in db.listar_documentos_cliente(tenant, cli)} == {"extracto.pdf", "grande.png"}
    # una regla sin la casilla no archiva nada
    uid2, tenant2, cli2, mid2 = _sembrar(db.crear_usuario("ex-5b@x.com", "contrasena123"), "ex-5b@x.com", ADJ)
    db.crear_regla_correo(uid2, "sol@mar.com", cliente_fiscal_id=cli2)
    correo._aplicar_categoria_automatica(uid2, mid2, "sol@mar.com", "x")
    assert db.listar_documentos_cliente(tenant2, cli2) == []


def test_flujo_web_archivar_ver_descargar_y_borrar(cliente):
    uid, tenant, cli, mid = _preparar(cliente, "ex-6@x.com", ADJ[:1])
    adj = db.listar_adjuntos_correo(mid)[0]["id"]
    html = cliente.get("/correo/", query_string={"cuenta_id": db.listar_cuentas_correo(uid)[0]["id"], "mensaje_id": mid}).get_data(as_text=True)
    assert "Archivar en el expediente de un cliente" in html and "extracto.pdf" in html
    r = cliente.post(f"/correo/{mid}/expediente", data={"cliente_fiscal_id": cli, "adjunto": [adj, "x"], "guardar_correo": "on", "categoria": "Extractos"})
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/fiscal/clientes/{cli}#expediente")
    ficha = cliente.get(f"/fiscal/clientes/{cli}").get_data(as_text=True)
    assert "Expediente" in ficha and "extracto.pdf" in ficha and "Extractos" in ficha and "del correo" in ficha
    doc = [d for d in db.listar_documentos_cliente(tenant, cli) if d["nombre_archivo"] == "extracto.pdf"][0]
    d = cliente.get(f"/fiscal/clientes/{cli}/documentos/{doc['id']}")
    assert d.status_code == 200 and d.data == b"%PDF-1.4 extracto" and d.headers["Content-Disposition"].startswith("attachment")
    assert d.headers["X-Content-Type-Options"] == "nosniff" and d.mimetype == "application/pdf"
    assert cliente.post(f"/correo/{mid}/expediente", data={}).status_code == 400
    assert cliente.post(f"/correo/{mid}/expediente", data={"cliente_fiscal_id": 99999}).status_code == 404
    assert cliente.post(f"/fiscal/clientes/{cli}/documentos/{doc['id']}/eliminar").status_code == 302
    assert cliente.get(f"/fiscal/clientes/{cli}/documentos/{doc['id']}").status_code == 404


def test_subida_manual_y_tipos_peligrosos(cliente):
    import io
    uid, tenant, cli, _ = _preparar(cliente, "ex-7@x.com")
    r = cliente.post(f"/fiscal/clientes/{cli}/documentos", data={
        "categoria": "Contratos", "archivo": [(io.BytesIO(b"<script>alert(1)</script>"), "pagina.html"), (io.BytesIO(b"contrato"), "contrato.txt")],
    }, content_type="multipart/form-data")
    assert r.status_code == 302
    docs = {d["nombre_archivo"]: d for d in db.listar_documentos_cliente(tenant, cli)}
    assert set(docs) == {"pagina.html", "contrato.txt"} and docs["contrato.txt"]["categoria"] == "Contratos" and docs["contrato.txt"]["origen"] == "subida"
    d = cliente.get(f"/fiscal/clientes/{cli}/documentos/{docs['pagina.html']['id']}")
    assert d.mimetype == "application/octet-stream" and d.headers["Content-Disposition"].startswith("attachment")        # nunca se interpreta como página


def test_aislamiento_entre_despachos_y_permiso_de_borrado(cliente):
    uid, tenant, cli, mid = _preparar(cliente, "ex-8@x.com", ADJ[:1])
    correo.archivar_correo_en_expediente(uid, mid, cli)
    doc = db.listar_documentos_cliente(tenant, cli)[0]["id"]
    with _otro_cliente("ex-8b@x.com") as (ajeno, id_ajeno):
        db.asignar_tenant(id_ajeno, db.crear_tenant("Despacho ajeno exp"))
        assert ajeno.get(f"/fiscal/clientes/{cli}/documentos/{doc}").status_code == 404
        assert ajeno.post(f"/fiscal/clientes/{cli}/documentos/{doc}/eliminar").status_code == 404
        assert ajeno.post(f"/fiscal/clientes/{cli}/documentos", data={}).status_code == 404
    with _otro_cliente("ex-8c@x.com") as (colega, id_colega):
        db.asignar_tenant(id_colega, tenant)
        assert colega.get(f"/fiscal/clientes/{cli}/documentos/{doc}").status_code == 200            # el expediente es del despacho
        assert colega.post(f"/fiscal/clientes/{cli}/documentos/{doc}/eliminar").status_code == 404   # pero solo borra quien lo subió o un supervisor
        conn = db.get_connection()
        conn.execute("UPDATE usuarios SET supervisor_tenant = 1 WHERE id = ?", (id_colega,))
        conn.commit()
        conn.close()
        assert colega.post(f"/fiscal/clientes/{cli}/documentos/{doc}/eliminar").status_code == 302
