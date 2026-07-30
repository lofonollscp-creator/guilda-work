"""Tests de mcp_tools.py — el módulo compartido de tools entre
mcp_server.py (stdio) y mcp_server_remoto.py (streamable-http/OAuth).

No se prueba cada tool una por una (las de notas/tareas/correo ya tienen
cobertura indirecta a través de app/db.py y tests/test_ia_herramientas.py,
que las ejecuta vía app/ia_herramientas.py:ejecutar) — el foco aquí es:
1) que TOOLS/registrar_tools sigan expuestas y coherentes tras el
   refactor que las sacó de mcp_server.py, y
2) que los wrappers finos de las herramientas EXTERNAS nuevas (CRM,
   Drive, OpenProject, Chatwoot, Metabase, n8n, Outline, Synapse, MinIO,
   Uptime Kuma) llamen de verdad a la función correcta del cliente
   correspondiente con los argumentos correctos — mockeando esos
   clientes, sin ningún servicio real levantado.
"""
import pytest
from mcp.server.fastmcp import FastMCP

import mcp_tools as mt


def test_tools_no_tiene_nombres_duplicados():
    nombres = [t.__name__ for t in mt.TOOLS]
    assert len(nombres) == len(set(nombres))


def test_tools_tiene_72_herramientas():
    assert len(mt.TOOLS) == 72


def test_registrar_tools_las_registra_todas():
    mcp = FastMCP("test")
    mt.registrar_tools(mcp)
    assert len(mcp._tool_manager.list_tools()) == len(mt.TOOLS)


def test_listar_notas_sigue_funcionando_tras_el_refactor(usuario_id):
    resultado = mt.crear_nota("nota de prueba")
    assert resultado["texto"] == "nota de prueba"
    assert any(n["texto"] == "nota de prueba" for n in mt.listar_notas())


# --- CRM (EspoCRM) -----------------------------------------------------------

def test_crm_listar_leads_delega_en_espocrm(monkeypatch):
    monkeypatch.setattr(mt.espocrm, "listar_leads", lambda **k: [{"id": "1"}])
    assert mt.crm_listar_leads(texto="Ana") == [{"id": "1"}]


def test_crm_crear_lead_delega_en_espocrm(monkeypatch):
    capturado = {}

    def fake_crear_lead(nombre, **k):
        capturado["nombre"] = nombre
        return {"id": "l1"}

    monkeypatch.setattr(mt.espocrm, "crear_lead", fake_crear_lead)
    assert mt.crm_crear_lead("Ana García")["id"] == "l1"
    assert capturado["nombre"] == "Ana García"


# --- Drive (Nextcloud) --------------------------------------------------------

def test_drive_listar_archivos_delega_en_nextcloud(monkeypatch):
    monkeypatch.setattr(mt.nextcloud, "listar_archivos", lambda carpeta: [{"nombre": "a.pdf"}])
    assert mt.drive_listar_archivos("Lueira") == [{"nombre": "a.pdf"}]


def test_drive_subir_archivo_codifica_texto_a_bytes(monkeypatch):
    capturado = {}

    def fake_subir(ruta, contenido):
        capturado["ruta"] = ruta
        capturado["contenido"] = contenido
        return {"ruta": ruta, "subido": True}

    monkeypatch.setattr(mt.nextcloud, "subir_archivo", fake_subir)
    mt.drive_subir_archivo("Lueira/nota.txt", "hola")
    assert capturado["contenido"] == b"hola"


# --- OpenProject ---------------------------------------------------------------

def test_proyectos_crear_tarea_delega_en_openproject(monkeypatch):
    capturado = {}

    def fake_crear(proyecto_id, asunto, tipo_id=1):
        capturado["args"] = (proyecto_id, asunto, tipo_id)
        return {"id": 5}

    monkeypatch.setattr(mt.openproject, "crear_paquete_trabajo", fake_crear)
    assert mt.proyectos_crear_tarea(1, "Nueva")["id"] == 5
    assert capturado["args"] == (1, "Nueva", 1)


# --- Chatwoot --------------------------------------------------------------------

def test_soporte_responder_conversacion_delega_en_chatwoot(monkeypatch):
    monkeypatch.setattr(mt.chatwoot, "responder_conversacion", lambda cid, texto: {"id": cid, "content": texto})
    assert mt.soporte_responder_conversacion(3, "gracias") == {"id": 3, "content": "gracias"}


# --- Metabase ---------------------------------------------------------------------

def test_analitica_ejecutar_pregunta_delega_en_metabase(monkeypatch):
    monkeypatch.setattr(mt.metabase, "ejecutar_pregunta", lambda pid: {"columnas": [], "filas": []})
    assert mt.analitica_ejecutar_pregunta(1) == {"columnas": [], "filas": []}


# --- n8n -----------------------------------------------------------------------------

def test_automatizaciones_ejecutar_flujo_delega_en_n8n(monkeypatch):
    monkeypatch.setattr(mt.n8n, "ejecutar_flujo", lambda fid: {"data": {"finished": True}})
    assert mt.automatizaciones_ejecutar_flujo("42")["data"]["finished"] is True


# --- Outline -------------------------------------------------------------------------

def test_documentacion_crear_delega_en_outline(monkeypatch):
    capturado = {}

    def fake_crear(coleccion_id, titulo, texto="", publicar=True):
        capturado["args"] = (coleccion_id, titulo, texto, publicar)
        return {"id": "d1"}

    monkeypatch.setattr(mt.outline, "crear_documento", fake_crear)
    assert mt.documentacion_crear("col1", "Título")["id"] == "d1"
    assert capturado["args"] == ("col1", "Título", "", True)


# --- Synapse -------------------------------------------------------------------------

def test_chat_enviar_mensaje_delega_en_synapse(monkeypatch):
    monkeypatch.setattr(mt.synapse, "enviar_mensaje", lambda sala, texto: {"event_id": "e1"})
    assert mt.chat_enviar_mensaje("!sala:matrix.local", "hola") == {"event_id": "e1"}


# --- MinIO ---------------------------------------------------------------------------

def test_almacenamiento_url_descarga_delega_en_minio(monkeypatch):
    monkeypatch.setattr(mt.minio_cliente, "url_descarga", lambda bucket, nombre, expira_minutos=60: "https://url-firmada")
    assert mt.almacenamiento_url_descarga("b", "f.pdf") == "https://url-firmada"


# --- Uptime Kuma (solo lectura) -----------------------------------------------------

def test_monitorizacion_listar_estado_delega_en_uptime_kuma(monkeypatch):
    monkeypatch.setattr(mt.uptime_kuma, "listar_monitores", lambda: [{"nombre": "Guilda Work", "estado": "activo"}])
    assert mt.monitorizacion_listar_estado() == [{"nombre": "Guilda Work", "estado": "activo"}]


# --- Facturación (FacturaScripts) — único cliente con parámetro `tenant` -----

def test_facturas_listar_clientes_resuelve_url_y_api_key_del_tenant(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("Lueira")
    mt.db.guardar_facturascripts(tenant_id, "http://127.0.0.1:8107/", "admin", "pass")
    mt.db.guardar_facturascripts_api_key(tenant_id, "clave-api")

    capturado = {}

    def fake_listar_clientes(url, api_key, **k):
        capturado["url"] = url
        capturado["api_key"] = api_key
        return [{"nombre": "Ana"}]

    monkeypatch.setattr(mt.facturascripts, "listar_clientes", fake_listar_clientes)
    resultado = mt.facturas_listar_clientes("Lueira")

    assert resultado == [{"nombre": "Ana"}]
    assert capturado["url"] == "http://127.0.0.1:8107/"
    assert capturado["api_key"] == "clave-api"


def test_facturas_listar_clientes_tenant_inexistente_lanza_value_error(usuario_id):
    with pytest.raises(ValueError):
        mt.facturas_listar_clientes("NoExiste")


def test_facturas_crear_cliente_sin_api_key_pendiente_lanza_value_error(usuario_id):
    mt.db.crear_tenant("SinApiKey")
    with pytest.raises(ValueError):
        mt.facturas_crear_cliente("SinApiKey", "Ana")


def test_facturas_crear_factura_delega_en_facturascripts(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConFacturas")
    mt.db.guardar_facturascripts(tenant_id, "http://127.0.0.1:8108/", "admin", "pass")
    mt.db.guardar_facturascripts_api_key(tenant_id, "clave-api")

    capturado = {}

    def fake_crear_factura(url, api_key, cliente_codigo, lineas):
        capturado["args"] = (url, api_key, cliente_codigo, lineas)
        return {"idfactura": "1"}

    monkeypatch.setattr(mt.facturascripts, "crear_factura", fake_crear_factura)
    lineas = [{"descripcion": "Servicio", "cantidad": 1, "precio": 50}]
    resultado = mt.facturas_crear_factura("ConFacturas", "5", lineas)

    assert resultado == {"idfactura": "1"}
    assert capturado["args"] == ("http://127.0.0.1:8108/", "clave-api", "5", lineas)


# --- Firmas (Documenso) — único otro cliente con parámetro `tenant` --------

def test_firmas_listar_documentos_resuelve_token_del_tenant(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConFirmas")
    mt.db.guardar_documenso_api_key(tenant_id, "token-real")

    capturado = {}

    def fake_listar(api_key, **k):
        capturado["api_key"] = api_key
        return [{"id": "envelope_1"}]

    monkeypatch.setattr(mt.documenso, "listar_documentos", fake_listar)
    assert mt.firmas_listar_documentos("ConFirmas") == [{"id": "envelope_1"}]
    assert capturado["api_key"] == "token-real"


def test_firmas_listar_documentos_tenant_inexistente_lanza_value_error(usuario_id):
    with pytest.raises(ValueError):
        mt.firmas_listar_documentos("NoExiste")


def test_firmas_crear_documento_sin_token_pendiente_lanza_value_error(usuario_id):
    mt.db.crear_tenant("SinToken")
    with pytest.raises(ValueError):
        mt.firmas_crear_documento("SinToken", "Título", "cGRm", [{"email": "a@b.com"}])


def test_firmas_crear_documento_decodifica_base64(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConFirmas2")
    mt.db.guardar_documenso_api_key(tenant_id, "token-real")

    capturado = {}

    def fake_crear(api_key, titulo, contenido_pdf, firmantes):
        capturado["args"] = (api_key, titulo, contenido_pdf, firmantes)
        return {"id": "envelope_1"}

    monkeypatch.setattr(mt.documenso, "crear_documento", fake_crear)
    import base64
    contenido_b64 = base64.b64encode(b"%PDF-contenido").decode("ascii")
    resultado = mt.firmas_crear_documento("ConFirmas2", "Título", contenido_b64, [{"email": "a@b.com"}])

    assert resultado == {"id": "envelope_1"}
    assert capturado["args"][2] == b"%PDF-contenido"


def test_firmas_descargar_firmado_codifica_base64(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConFirmas3")
    mt.db.guardar_documenso_api_key(tenant_id, "token-real")

    monkeypatch.setattr(mt.documenso, "descargar_firmado", lambda api_key, doc_id: b"%PDF-firmado")
    resultado = mt.firmas_descargar_firmado("ConFirmas3", "envelope_1")

    import base64
    assert base64.b64decode(resultado) == b"%PDF-firmado"


# --- Documentos (Paperless-ngx) — tercer cliente con parámetro `tenant` -----

def test_documentos_listar_resuelve_token_del_tenant(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConDocumentos")
    mt.db.guardar_paperless(tenant_id, 5, 9, "token-real")

    capturado = {}

    def fake_listar(api_key, **k):
        capturado["api_key"] = api_key
        return [{"id": 1, "title": "Factura"}]

    monkeypatch.setattr(mt.paperless, "listar_documentos", fake_listar)
    assert mt.documentos_listar("ConDocumentos") == [{"id": 1, "title": "Factura"}]
    assert capturado["api_key"] == "token-real"


def test_documentos_listar_tenant_inexistente_lanza_value_error(usuario_id):
    with pytest.raises(ValueError):
        mt.documentos_listar("NoExiste")


def test_documentos_subir_sin_aprovisionar_lanza_value_error(usuario_id):
    mt.db.crear_tenant("SinPaperless")
    with pytest.raises(ValueError):
        mt.documentos_subir("SinPaperless", "Título", "cGRm", "doc.pdf")


def test_documentos_subir_decodifica_base64_y_pasa_owner_y_grupo(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConDocumentos2")
    mt.db.guardar_paperless(tenant_id, 5, 9, "token-real")

    capturado = {}

    def fake_subir(api_key, owner_id, group_id, titulo, contenido_pdf, nombre_archivo):
        capturado["args"] = (api_key, owner_id, group_id, titulo, contenido_pdf, nombre_archivo)
        return {"id": 42}

    monkeypatch.setattr(mt.paperless, "subir_documento", fake_subir)
    import base64
    contenido_b64 = base64.b64encode(b"%PDF-contenido").decode("ascii")
    resultado = mt.documentos_subir("ConDocumentos2", "Título", contenido_b64, "doc.pdf")

    assert resultado == {"id": 42}
    assert capturado["args"] == ("token-real", 9, 5, "Título", b"%PDF-contenido", "doc.pdf")


def test_documentos_descargar_codifica_base64(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConDocumentos3")
    mt.db.guardar_paperless(tenant_id, 5, 9, "token-real")

    monkeypatch.setattr(mt.paperless, "descargar_documento", lambda api_key, doc_id: b"%PDF-descargado")
    resultado = mt.documentos_descargar("ConDocumentos3", "42")

    import base64
    assert base64.b64decode(resultado) == b"%PDF-descargado"


# --- Hojas (Baserow) — cuarto cliente con parámetro `tenant` ----------------

def test_hojas_listar_tablas_resuelve_token_del_tenant(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConHojas")
    mt.db.guardar_baserow(tenant_id, 5, "token-real")

    capturado = {}

    def fake_listar(api_key):
        capturado["api_key"] = api_key
        return [{"id": 1, "name": "Clientes"}]

    monkeypatch.setattr(mt.baserow, "listar_tablas", fake_listar)
    assert mt.hojas_listar_tablas("ConHojas") == [{"id": 1, "name": "Clientes"}]
    assert capturado["api_key"] == "token-real"


def test_hojas_listar_tablas_tenant_inexistente_lanza_value_error(usuario_id):
    with pytest.raises(ValueError):
        mt.hojas_listar_tablas("NoExiste")


def test_hojas_listar_filas_sin_aprovisionar_lanza_value_error(usuario_id):
    mt.db.crear_tenant("SinBaserow")
    with pytest.raises(ValueError):
        mt.hojas_listar_filas("SinBaserow", 42)


def test_hojas_listar_filas_delega_en_baserow(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConHojas2")
    mt.db.guardar_baserow(tenant_id, 5, "token-real")

    capturado = {}

    def fake_listar(api_key, tabla_id, texto=None, limite=20):
        capturado["args"] = (api_key, tabla_id, texto, limite)
        return [{"id": 1, "field_1": "Ana"}]

    monkeypatch.setattr(mt.baserow, "listar_filas", fake_listar)
    resultado = mt.hojas_listar_filas("ConHojas2", 42, texto="Ana")

    assert resultado == [{"id": 1, "field_1": "Ana"}]
    assert capturado["args"] == ("token-real", 42, "Ana", 20)


def test_hojas_crear_fila_delega_en_baserow(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConHojas3")
    mt.db.guardar_baserow(tenant_id, 5, "token-real")

    capturado = {}

    def fake_crear(api_key, tabla_id, campos):
        capturado["args"] = (api_key, tabla_id, campos)
        return {"id": 1, "Nombre": "Ana"}

    monkeypatch.setattr(mt.baserow, "crear_fila", fake_crear)
    resultado = mt.hojas_crear_fila("ConHojas3", 42, {"Nombre": "Ana"})

    assert resultado == {"id": 1, "Nombre": "Ana"}
    assert capturado["args"] == ("token-real", 42, {"Nombre": "Ana"})
