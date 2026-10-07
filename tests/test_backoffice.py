"""Tests del backoffice (Fase 7c): rol admin y gestión de tenants/usuarios,
tanto a nivel de app/db.py como de las rutas de app/rutas_backoffice.py.
"""
import pytest

from app import db
from tests.conftest import iniciar_sesion_de_prueba


# --- app/db.py -----------------------------------------------------------

def test_usuario_nuevo_no_es_admin_por_defecto(usuario_id):
    assert db.es_admin(usuario_id) is False


def test_hacer_admin_y_quitar_admin(usuario_id):
    usuario = db.obtener_usuario(usuario_id)
    db.hacer_admin(usuario["email"])
    assert db.es_admin(usuario_id) is True
    db.quitar_admin(usuario["email"])
    assert db.es_admin(usuario_id) is False


def test_hacer_admin_email_inexistente_lanza_value_error():
    with pytest.raises(ValueError):
        db.hacer_admin("no-existe@ejemplo.com")


def test_listar_usuarios_incluye_tenant(usuario_id):
    tenant_id = db.crear_tenant("Lueira")
    db.asignar_tenant(usuario_id, tenant_id)
    usuarios = db.listar_usuarios()
    fila = next(u for u in usuarios if u["id"] == usuario_id)
    assert fila["tenant_nombre"] == "Lueira"


def test_listar_tenants_con_conteo(usuario_id):
    tenant_id = db.crear_tenant("Lueira")
    db.crear_tenant("Guilda")
    db.asignar_tenant(usuario_id, tenant_id)
    tenants = {t["nombre"]: t["n_usuarios"] for t in db.listar_tenants_con_conteo()}
    assert tenants["Lueira"] == 1
    assert tenants["Guilda"] == 0


def test_renombrar_tenant():
    tenant_id = db.crear_tenant("Lueira")
    db.renombrar_tenant(tenant_id, "Lueira SL")
    assert db.obtener_tenant(tenant_id)["nombre"] == "Lueira SL"


def test_borrar_tenant_desasigna_a_sus_usuarios(usuario_id):
    tenant_id = db.crear_tenant("Lueira")
    db.asignar_tenant(usuario_id, tenant_id)
    db.borrar_tenant(tenant_id)
    assert db.obtener_tenant(tenant_id) is None
    assert db.tenant_de_usuario(usuario_id) is None


def test_desasignar_tenant(usuario_id):
    tenant_id = db.crear_tenant("Lueira")
    db.asignar_tenant(usuario_id, tenant_id)
    db.desasignar_tenant(usuario_id)
    assert db.tenant_de_usuario(usuario_id) is None


# --- app/rutas_backoffice.py ----------------------------------------------













































































































# --- Umami (analítica web) --------------------------------------------------













# --- Observabilidad (Grafana+Loki) — oculta por defecto ---------------------





# --- Portainer — oculta por defecto ------------------------------------------





# --- Webhooks ------------------------------------------------------------





def test_backoffice_crear_webhook_sin_eventos_no_lo_crea(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-wh3@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    cliente.post("/backoffice/webhooks", data={"tenant_id": "", "url": "https://ejemplo.com/hook"}, follow_redirects=True)
    assert db.listar_webhooks(None) == []


def test_backoffice_crear_webhook_ignora_eventos_no_reconocidos(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-wh4@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    cliente.post(
        "/backoffice/webhooks",
        data={"tenant_id": "", "url": "https://ejemplo.com/hook", "eventos": ["evento.inventado"]},
        follow_redirects=True,
    )
    assert db.listar_webhooks(None) == []












# --- Log de auditoría (app/db.py, app/rutas_backoffice.py) -----------------

def test_registrar_y_listar_auditoria(usuario_id):
    db.registrar_auditoria(usuario_id, "crear_tenant", "Lueira")
    entradas = db.listar_auditoria_backoffice()
    assert len(entradas) == 1
    assert entradas[0]["accion"] == "crear_tenant"
    assert entradas[0]["detalle"] == "Lueira"
    assert entradas[0]["usuario_email"] is not None


def test_listar_auditoria_orden_mas_reciente_primero(usuario_id):
    db.registrar_auditoria(usuario_id, "primera_accion", None)
    db.registrar_auditoria(usuario_id, "segunda_accion", None)
    entradas = db.listar_auditoria_backoffice()
    assert [e["accion"] for e in entradas] == ["segunda_accion", "primera_accion"]












# --- Exportación de datos de un tenant (GDPR, solo lectura) -----------------

def test_exportar_datos_tenant_incluye_lo_esperado(usuario_id):
    tenant_id = db.crear_tenant("Gestoria Export")
    db.asignar_tenant(usuario_id, tenant_id)
    cliente_id = db.crear_cliente_fiscal(tenant_id, "Cliente Export", nif="B123")
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", "2026-04-20")
    db.subir_documento_vencimiento(v_id, "factura.pdf", "application/pdf", b"contenido-pdf")
    db.crear_mensaje_vencimiento(v_id, "cliente", "¿Falta algo?")
    cid = db.crear_categoria(usuario_id, "Guilda")
    db.crear_tarea(usuario_id, "Tarea export", cid, "instantanea")
    db.crear_nota(usuario_id, "Nota export")
    db.crear_tiquet(usuario_id, tipo="error", titulo="Tiquet export")

    export = db.exportar_datos_tenant(tenant_id)

    assert export["tenant"]["nombre"] == "Gestoria Export"
    assert len(export["usuarios"]) == 1
    assert export["usuarios"][0]["id"] == usuario_id
    assert "contrasena_hash" not in export["usuarios"][0]
    assert len(export["clientes_fiscales"]) == 1
    assert export["clientes_fiscales"][0]["nif"] == "B123"
    assert len(export["vencimientos_fiscales"]) == 1
    vencimiento_exportado = export["vencimientos_fiscales"][0]
    assert len(vencimiento_exportado["documentos"]) == 1
    assert vencimiento_exportado["documentos"][0]["nombre_archivo"] == "factura.pdf"
    assert "url_descarga" in vencimiento_exportado["documentos"][0]
    assert "contenido" not in vencimiento_exportado["documentos"][0]
    assert len(vencimiento_exportado["mensajes"]) == 1
    assert len(export["tareas"]) == 1
    assert len(export["notas"]) == 1
    assert len(export["tiquets"]) == 1


def test_exportar_datos_tenant_no_mezcla_datos_de_otro_tenant(usuario_id):
    tenant_a = db.crear_tenant("Gestoria Export A")
    tenant_b = db.crear_tenant("Gestoria Export B")
    db.asignar_tenant(usuario_id, tenant_a)
    db.crear_cliente_fiscal(tenant_a, "Cliente A")
    otro_id = db.crear_usuario("export-otro@ejemplo.com", "contrasena123")
    db.asignar_tenant(otro_id, tenant_b)
    db.crear_cliente_fiscal(tenant_b, "Cliente B")

    export = db.exportar_datos_tenant(tenant_a)

    assert [c["nombre"] for c in export["clientes_fiscales"]] == ["Cliente A"]
    assert [u["id"] for u in export["usuarios"]] == [usuario_id]


def test_exportar_datos_tenant_inexistente_lanza_value_error():
    with pytest.raises(ValueError):
        db.exportar_datos_tenant(999999)


def test_exportar_datos_tenant_sin_usuarios_no_falla():
    tenant_id = db.crear_tenant("Gestoria Export Vacia")
    export = db.exportar_datos_tenant(tenant_id)
    assert export["usuarios"] == []
    assert export["tareas"] == []
