"""Registro de accesos a un cliente: quién abrió su ficha, descargó o subió documentos, etc. (supervisores)."""
import io
from datetime import datetime, timedelta

from app import correo, db
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_proyectos_paginas import _otro_cliente


def _preparar(cliente, email):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    tenant = db.crear_tenant(f"Despacho accesos {email}")
    db.asignar_tenant(uid, tenant)
    return uid, tenant, db.crear_cliente_fiscal(tenant, "Sol y Mar SL")


def _acciones(tenant, cli):
    return [a["accion"] for a in reversed(db.listar_accesos_cliente(tenant, cli))]


def test_registrar_valida_y_no_rompe():
    tenant = db.crear_tenant("Despacho acc")
    assert db.registrar_acceso_cliente(tenant, 1, None, "inventada") is False
    assert db.registrar_acceso_cliente(None, 1, None, "ficha_vista") is False
    assert db.registrar_acceso_cliente(tenant, 1, None, "documento_subido", "x" * 500) is True
    assert len(db.listar_accesos_cliente(tenant, 1)[0]["detalle"]) == 200
    assert db.listar_accesos_cliente(tenant, 1)[0]["usuario"] == "—"                             # sin usuario (p. ej. un proceso)


def test_la_ficha_vista_no_se_repite_en_la_ventana():
    tenant = db.crear_tenant("Despacho ventana")
    ana, luis = (db.crear_usuario(f"ca-{n}@x.com", "contrasena123") for n in "al")
    assert db.registrar_acceso_cliente(tenant, 5, ana, "ficha_vista") is True
    assert db.registrar_acceso_cliente(tenant, 5, ana, "ficha_vista") is False                   # misma persona, mismo cliente, enseguida
    assert db.registrar_acceso_cliente(tenant, 5, luis, "ficha_vista") is True                   # otra persona
    assert db.registrar_acceso_cliente(tenant, 6, ana, "ficha_vista") is True                    # otro cliente
    conn = db.get_connection()
    conn.execute("UPDATE cliente_accesos SET creado_en = ? WHERE usuario_id = ?", ((datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds"), ana))
    conn.commit()
    conn.close()
    assert db.registrar_acceso_cliente(tenant, 5, ana, "ficha_vista") is True                    # pasada la ventana vuelve a anotarse
    assert db.registrar_acceso_cliente(tenant, 5, ana, "documento_descargado", "a.pdf") is True  # y el resto de acciones siempre se anotan
    assert db.registrar_acceso_cliente(tenant, 5, ana, "documento_descargado", "a.pdf") is True


def test_purga_de_lo_antiguo():
    tenant = db.crear_tenant("Despacho purga")
    db.registrar_acceso_cliente(tenant, 1, None, "cliente_editado")
    db.registrar_acceso_cliente(tenant, 1, None, "cliente_editado")
    conn = db.get_connection()
    conn.execute("UPDATE cliente_accesos SET creado_en = '2020-01-01T00:00:00' WHERE id = (SELECT MIN(id) FROM cliente_accesos)")
    conn.commit()
    conn.close()
    assert db.purgar_accesos_antiguos() == 1 and len(db.listar_accesos_cliente(tenant, 1)) == 1


def test_las_acciones_de_la_plataforma_quedan_registradas(cliente):
    uid, tenant, cli = _preparar(cliente, "ca-1@x.com")
    cliente.get(f"/fiscal/clientes/{cli}")
    cliente.post(f"/fiscal/clientes/{cli}/documentos", data={"archivo": [(io.BytesIO(b"contenido"), "contrato.pdf")], "categoria": "Contratos"}, content_type="multipart/form-data")
    doc = db.listar_documentos_cliente(tenant, cli)[0]["id"]
    cliente.get(f"/fiscal/clientes/{cli}/documentos/{doc}")
    cliente.post(f"/fiscal/clientes/{cli}/documentos/{doc}/eliminar")
    cliente.post(f"/fiscal/clientes/{cli}/editar", data={"nombre": "Sol y Mar SL", "pais": "ES", "idioma": "es"})
    cuenta = db.crear_cuenta_correo(uid, "c", "imap", "h", 993, "u")
    conn = db.get_connection()
    mid = conn.execute("INSERT INTO correo_mensajes (cuenta_id, carpeta, uid, asunto, remitente, descargado_en) VALUES (?, 'INBOX', 1, 'Extractos', 'a@b.c', '2026-10-01')", (cuenta,)).lastrowid
    conn.commit()
    conn.close()
    db.guardar_adjuntos_correo(mid, [{"nombre": "e.pdf", "tipo": "application/pdf", "bytes": b"%PDF"}])
    correo.archivar_correo_en_expediente(uid, mid, cli)
    correo.archivar_correo_en_expediente(uid, mid, cli, automatico=True)                         # lo automático (reglas) no se anota como acción de una persona
    v = db.crear_vencimiento_fiscal(tenant, cli, "303", "2T", "2026-12-01")
    dv = db.subir_documento_vencimiento(v, "justificante.pdf", "application/pdf", b"%PDF")
    cliente.get(f"/fiscal/vencimientos/{v}/documentos/{dv}")
    cliente.post(f"/fiscal/clientes/{cli}/eliminar")
    assert _acciones(tenant, cli) == ["ficha_vista", "documento_subido", "documento_descargado", "documento_eliminado", "cliente_editado",
                                      "correo_archivado", "vencimiento_documento_descargado", "cliente_eliminado"]
    detalles = {a["accion"]: a["detalle"] for a in db.listar_accesos_cliente(tenant, cli)}
    assert detalles["documento_subido"] == "contrato.pdf" and detalles["documento_descargado"] == "contrato.pdf" and detalles["vencimiento_documento_descargado"] == "justificante.pdf"
    assert db.listar_accesos_cliente(tenant, cli)[0]["usuario"] == "ca-1@x.com"


def test_solo_los_supervisores_ven_el_registro(cliente):
    uid, tenant, cli = _preparar(cliente, "ca-2@x.com")
    html = cliente.get(f"/fiscal/clientes/{cli}").get_data(as_text=True)
    assert "Quién ha accedido" not in html and cliente.get(f"/fiscal/clientes/{cli}/accesos.csv").status_code == 404
    conn = db.get_connection()
    conn.execute("UPDATE usuarios SET supervisor_tenant = 1 WHERE id = ?", (uid,))
    conn.commit()
    conn.close()
    cliente.get(f"/fiscal/clientes/{cli}/documentos/99999")                                      # un 404 no anota nada
    html = cliente.get(f"/fiscal/clientes/{cli}").get_data(as_text=True)
    assert "Quién ha accedido" in html and "Ha abierto la ficha" in html and "ca-2@x.com" in html
    r = cliente.get(f"/fiscal/clientes/{cli}/accesos.csv")
    assert r.status_code == 200 and r.mimetype == "text/csv" and r.headers["Content-Disposition"].startswith("attachment")
    texto = r.get_data(as_text=True)
    assert texto.startswith("﻿fecha,usuario,accion,detalle") and "ca-2@x.com" in texto and "Ha abierto la ficha" in texto
    with _otro_cliente("ca-3@x.com") as (otro, id_otro):
        db.asignar_tenant(id_otro, db.crear_tenant("Despacho ajeno accesos"))
        conn = db.get_connection()
        conn.execute("UPDATE usuarios SET supervisor_tenant = 1 WHERE id = ?", (id_otro,))
        conn.commit()
        conn.close()
        assert otro.get(f"/fiscal/clientes/{cli}/accesos.csv").status_code == 404                # ni siendo supervisor de otro despacho
        assert db.listar_accesos_cliente(db.crear_tenant("Otro"), cli) == []
