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


def test_tools_tiene_86_herramientas():
    assert len(mt.TOOLS) == 86


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


# --- Citas (Cal.diy) — quinto cliente con parámetro `tenant` ----------------

def test_citas_listar_tipos_evento_resuelve_token_del_tenant(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConCitas")
    mt.db.guardar_calcom(tenant_id, "tenant-concitas@calcom.local", "clave-x")
    mt.db.guardar_calcom_api_key(tenant_id, "token-real")

    capturado = {}

    def fake_listar(api_key):
        capturado["api_key"] = api_key
        return [{"id": 1, "title": "Consulta inicial"}]

    monkeypatch.setattr(mt.calcom, "listar_tipos_evento", fake_listar)
    assert mt.citas_listar_tipos_evento("ConCitas") == [{"id": 1, "title": "Consulta inicial"}]
    assert capturado["api_key"] == "token-real"


def test_citas_listar_tipos_evento_tenant_inexistente_lanza_value_error(usuario_id):
    with pytest.raises(ValueError):
        mt.citas_listar_tipos_evento("NoExiste")


def test_citas_listar_reservas_sin_aprovisionar_lanza_value_error(usuario_id):
    mt.db.crear_tenant("SinCalcom")
    with pytest.raises(ValueError):
        mt.citas_listar_reservas("SinCalcom")


def test_citas_listar_reservas_delega_en_calcom(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConCitas2")
    mt.db.guardar_calcom(tenant_id, "tenant-concitas2@calcom.local", "clave-x")
    mt.db.guardar_calcom_api_key(tenant_id, "token-real")

    capturado = {}

    def fake_listar(api_key, desde=None, hasta=None):
        capturado["args"] = (api_key, desde, hasta)
        return [{"uid": "abc123"}]

    monkeypatch.setattr(mt.calcom, "listar_reservas", fake_listar)
    resultado = mt.citas_listar_reservas("ConCitas2", desde="2026-08-01T00:00:00Z")

    assert resultado == [{"uid": "abc123"}]
    assert capturado["args"] == ("token-real", "2026-08-01T00:00:00Z", None)


def test_citas_crear_reserva_delega_en_calcom(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConCitas3")
    mt.db.guardar_calcom(tenant_id, "tenant-concitas3@calcom.local", "clave-x")
    mt.db.guardar_calcom_api_key(tenant_id, "token-real")

    capturado = {}

    def fake_crear(api_key, tipo_evento_id, inicio, nombre_asistente, email_asistente):
        capturado["args"] = (api_key, tipo_evento_id, inicio, nombre_asistente, email_asistente)
        return {"uid": "abc123"}

    monkeypatch.setattr(mt.calcom, "crear_reserva", fake_crear)
    resultado = mt.citas_crear_reserva("ConCitas3", 1, "2026-08-01T10:00:00Z", "Ana", "ana@ejemplo.com")

    assert resultado == {"uid": "abc123"}
    assert capturado["args"] == ("token-real", 1, "2026-08-01T10:00:00Z", "Ana", "ana@ejemplo.com")


def test_citas_crear_reserva_sin_jitsi_configurado_no_incluye_video_url(usuario_id, monkeypatch):
    """Sin JITSI_JWT_APP_ID/SECRET (caso normal en tests), la reserva se
    crea igual, sin `video_url` — mismo criterio que el resto de
    integraciones opcionales de este proyecto."""
    tenant_id = mt.db.crear_tenant("ConCitasSinJitsi")
    mt.db.guardar_calcom(tenant_id, "x@calcom.local", "clave-x")
    mt.db.guardar_calcom_api_key(tenant_id, "token-real")
    monkeypatch.setattr(mt.calcom, "crear_reserva", lambda *a, **k: {"uid": "abc999"})

    resultado = mt.citas_crear_reserva("ConCitasSinJitsi", 1, "2026-08-01T10:00:00Z", "Ana", "ana@ejemplo.com")

    assert resultado == {"uid": "abc999"}
    assert "video_url" not in resultado


def test_citas_crear_reserva_con_jitsi_configurado_incluye_video_url(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConCitasConJitsi")
    mt.db.guardar_calcom(tenant_id, "x@calcom.local", "clave-x")
    mt.db.guardar_calcom_api_key(tenant_id, "token-real")
    monkeypatch.setattr(mt.calcom, "crear_reserva", lambda *a, **k: {"uid": "abc777"})
    monkeypatch.setattr(mt.jitsi, "JITSI_JWT_APP_ID", "guilda_work")
    monkeypatch.setattr(mt.jitsi, "JITSI_JWT_APP_SECRET", "secreto-de-prueba")

    resultado = mt.citas_crear_reserva("ConCitasConJitsi", 1, "2026-08-01T10:00:00Z", "Ana", "ana@ejemplo.com")

    assert resultado["uid"] == "abc777"
    assert resultado["video_url"].startswith(mt.jitsi.JITSI_URL)
    assert "concitasconjitsi" in resultado["video_url"]


# --- Videollamadas (Jitsi Meet) — noveno cliente con parámetro `tenant` ----

def test_videollamadas_crear_sala_tenant_inexistente_lanza_value_error(usuario_id):
    with pytest.raises(ValueError):
        mt.videollamadas_crear_sala("NoExiste", "Ana")


def test_videollamadas_crear_sala_sin_jitsi_configurado_lanza_error(usuario_id):
    mt.db.crear_tenant("ConVideoSinJitsi")
    with pytest.raises(mt.jitsi.ErrorJitsi):
        mt.videollamadas_crear_sala("ConVideoSinJitsi", "Ana")


def test_videollamadas_crear_sala_genera_url_con_prefijo_del_tenant(usuario_id, monkeypatch):
    mt.db.crear_tenant("ConVideoOk")
    monkeypatch.setattr(mt.jitsi, "JITSI_JWT_APP_ID", "guilda_work")
    monkeypatch.setattr(mt.jitsi, "JITSI_JWT_APP_SECRET", "secreto-de-prueba")

    resultado = mt.videollamadas_crear_sala("ConVideoOk", "Ana", moderador=True)

    assert resultado["sala"].startswith("convideook-")
    assert resultado["url"].startswith(mt.jitsi.JITSI_URL)
    assert resultado["sala"] in resultado["url"]
    assert "jwt=" in resultado["url"]


# --- Newsletter (Listmonk) — sexto cliente con parámetro `tenant` ----------

def test_newsletter_listar_suscriptores_resuelve_token_del_tenant(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConNewsletter")
    mt.db.guardar_listmonk(tenant_id, 3, 5, "token-real")

    capturado = {}

    def fake_listar(api_key, list_id, texto=None, limite=20):
        capturado["args"] = (api_key, list_id, texto, limite)
        return [{"email": "a@b.com"}]

    monkeypatch.setattr(mt.listmonk, "listar_suscriptores", fake_listar)
    resultado = mt.newsletter_listar_suscriptores("ConNewsletter")

    assert resultado == [{"email": "a@b.com"}]
    assert capturado["args"] == ("token-real", 3, None, 20)


def test_newsletter_listar_suscriptores_tenant_inexistente_lanza_value_error(usuario_id):
    with pytest.raises(ValueError):
        mt.newsletter_listar_suscriptores("NoExiste")


def test_newsletter_crear_suscriptor_sin_aprovisionar_lanza_value_error(usuario_id):
    mt.db.crear_tenant("SinListmonk")
    with pytest.raises(ValueError):
        mt.newsletter_crear_suscriptor("SinListmonk", "a@b.com", "Ana")


def test_newsletter_crear_suscriptor_delega_en_listmonk(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConNewsletter2")
    mt.db.guardar_listmonk(tenant_id, 3, 5, "token-real")

    capturado = {}

    def fake_crear(api_key, list_id, email, nombre, atribs):
        capturado["args"] = (api_key, list_id, email, nombre, atribs)
        return {"email": email}

    monkeypatch.setattr(mt.listmonk, "crear_suscriptor", fake_crear)
    resultado = mt.newsletter_crear_suscriptor("ConNewsletter2", "ana@ejemplo.com", "Ana")

    assert resultado == {"email": "ana@ejemplo.com"}
    assert capturado["args"] == ("token-real", 3, "ana@ejemplo.com", "Ana", None)


def test_newsletter_listar_campanas_delega_en_listmonk(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConNewsletter3")
    mt.db.guardar_listmonk(tenant_id, 3, 5, "token-real")

    monkeypatch.setattr(mt.listmonk, "listar_campanas", lambda api_key: [{"id": 1}])
    assert mt.newsletter_listar_campanas("ConNewsletter3") == [{"id": 1}]


def test_newsletter_crear_campana_delega_en_listmonk(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConNewsletter4")
    mt.db.guardar_listmonk(tenant_id, 3, 5, "token-real")

    capturado = {}

    def fake_crear(api_key, list_id, nombre, asunto, cuerpo_html):
        capturado["args"] = (api_key, list_id, nombre, asunto, cuerpo_html)
        return {"id": 2, "status": "draft"}

    monkeypatch.setattr(mt.listmonk, "crear_campana", fake_crear)
    resultado = mt.newsletter_crear_campana("ConNewsletter4", "Prueba", "Hola", "<p>hola</p>")

    assert resultado == {"id": 2, "status": "draft"}
    assert capturado["args"] == ("token-real", 3, "Prueba", "Hola", "<p>hola</p>")


def test_newsletter_enviar_campana_delega_en_listmonk(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConNewsletter5")
    mt.db.guardar_listmonk(tenant_id, 3, 5, "token-real")

    capturado = {}

    def fake_enviar(api_key, campana_id):
        capturado["args"] = (api_key, campana_id)
        return {"id": campana_id, "status": "running"}

    monkeypatch.setattr(mt.listmonk, "enviar_campana", fake_enviar)
    resultado = mt.newsletter_enviar_campana("ConNewsletter5", 2)

    assert resultado == {"id": 2, "status": "running"}
    assert capturado["args"] == ("token-real", 2)


# --- Correo Stalwart — séptimo cliente con parámetro `tenant` --------------

def test_correo_stalwart_listar_mensajes_resuelve_token_del_tenant(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConStalwart")
    mt.db.guardar_stalwart(tenant_id, "t1", "d1", "clientea.com", "a1", "token-real")

    capturado = {}

    def fake_listar(api_key, mailbox="INBOX", limite=20):
        capturado["args"] = (api_key, mailbox, limite)
        return [{"subject": "Hola"}]

    monkeypatch.setattr(mt.stalwart, "listar_mensajes", fake_listar)
    resultado = mt.correo_stalwart_listar_mensajes("ConStalwart")

    assert resultado == [{"subject": "Hola"}]
    assert capturado["args"] == ("token-real", "INBOX", 20)


def test_correo_stalwart_listar_mensajes_tenant_inexistente_lanza_value_error(usuario_id):
    with pytest.raises(ValueError):
        mt.correo_stalwart_listar_mensajes("NoExiste")


def test_correo_stalwart_leer_mensaje_sin_aprovisionar_lanza_value_error(usuario_id):
    mt.db.crear_tenant("SinStalwart")
    with pytest.raises(ValueError):
        mt.correo_stalwart_leer_mensaje("SinStalwart", "abc")


def test_correo_stalwart_leer_mensaje_delega_en_stalwart(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConStalwart2")
    mt.db.guardar_stalwart(tenant_id, "t1", "d1", "clientea.com", "a1", "token-real")

    capturado = {}

    def fake_leer(api_key, email_id):
        capturado["args"] = (api_key, email_id)
        return {"id": email_id, "subject": "Hola"}

    monkeypatch.setattr(mt.stalwart, "leer_mensaje", fake_leer)
    resultado = mt.correo_stalwart_leer_mensaje("ConStalwart2", "abc123")

    assert resultado == {"id": "abc123", "subject": "Hola"}
    assert capturado["args"] == ("token-real", "abc123")


def test_correo_stalwart_enviar_mensaje_delega_en_stalwart(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConStalwart3")
    mt.db.guardar_stalwart(tenant_id, "t1", "d1", "clientea.com", "a1", "token-real")

    capturado = {}

    def fake_enviar(api_key, para, asunto, cuerpo):
        capturado["args"] = (api_key, para, asunto, cuerpo)
        return {"id": "env1"}

    monkeypatch.setattr(mt.stalwart, "enviar_mensaje", fake_enviar)
    resultado = mt.correo_stalwart_enviar_mensaje("ConStalwart3", "ana@ejemplo.com", "Hola", "Cuerpo")

    assert resultado == {"id": "env1"}
    assert capturado["args"] == ("token-real", "ana@ejemplo.com", "Hola", "Cuerpo")


def test_notificaciones_enviar_resuelve_topic_y_token_del_tenant(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConNtfy")
    mt.db.guardar_ntfy(tenant_id, "guilda-connfty-1", "token-real")

    capturado = {}

    def fake_enviar(topic, token, titulo, mensaje, prioridad="default", click_url=None):
        capturado["args"] = (topic, token, titulo, mensaje, prioridad)
        return None

    monkeypatch.setattr(mt.ntfy, "enviar", fake_enviar)
    resultado = mt.notificaciones_enviar("ConNtfy", "Aviso", "Ha pasado algo")

    assert resultado == {"enviado": True, "topic": "guilda-connfty-1"}
    assert capturado["args"] == ("guilda-connfty-1", "token-real", "Aviso", "Ha pasado algo", "default")


def test_notificaciones_enviar_tenant_inexistente_lanza_value_error(usuario_id):
    with pytest.raises(ValueError):
        mt.notificaciones_enviar("NoExiste", "Aviso", "Mensaje")


def test_notificaciones_enviar_sin_aprovisionar_lanza_value_error(usuario_id):
    mt.db.crear_tenant("SinNtfy")
    with pytest.raises(ValueError):
        mt.notificaciones_enviar("SinNtfy", "Aviso", "Mensaje")


def test_citas_cancelar_reserva_delega_en_calcom(usuario_id, monkeypatch):
    tenant_id = mt.db.crear_tenant("ConCitas4")
    mt.db.guardar_calcom(tenant_id, "tenant-concitas4@calcom.local", "clave-x")
    mt.db.guardar_calcom_api_key(tenant_id, "token-real")

    capturado = {}

    def fake_cancelar(api_key, reserva_uid, motivo):
        capturado["args"] = (api_key, reserva_uid, motivo)
        return {"uid": "abc123", "status": "cancelled"}

    monkeypatch.setattr(mt.calcom, "cancelar_reserva", fake_cancelar)
    resultado = mt.citas_cancelar_reserva("ConCitas4", "abc123", "no puede asistir")

    assert resultado == {"uid": "abc123", "status": "cancelled"}
    assert capturado["args"] == ("token-real", "abc123", "no puede asistir")
