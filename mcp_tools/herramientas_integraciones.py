"""Herramientas MCP de las integraciones externas (CRM, Drive, firmas, facturación, hojas, citas, webhooks, newsletter...).

Parte de la antigua `__init__.py`, dividida por dominios sin cambiar su comportamiento: todo lo que no está aquí (la conexión, las constantes y las funciones de otros
dominios) se usa a través de `_mt`, que sigue siendo el único espacio de nombres (`_mt.nombre` funciona igual que antes y se puede parchear en los tests)."""
from __future__ import annotations
import base64
import contextvars
import mimetypes
import secrets
import sqlite3
import uuid
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import FastMCP
from app import (
    baserow,
    busqueda,
    calcom,
    chatwoot,
    correo,
    db,
    documenso,
    espocrm,
    eventos,
    export,
    facturascripts,
    importador,
    jitsi,
    kratos,
    listmonk,
    metabase,
    minio_cliente,
    n8n,
    nextcloud,
    ntfy,
    openproject,
    outline,
    outlook_ics,
    paperless,
    stalwart,
    synapse,
    umami,
    uptime_kuma,
)

import mcp_tools as _mt


# --- CRM (EspoCRM) -------------------------------------------------------------

def crm_listar_leads(texto: str | None = None, limite: int = 20) -> list[dict]:
    """Busca/lista Leads del CRM. `texto` filtra por coincidencia parcial."""
    return _mt.espocrm.listar_leads(texto=texto, limite=limite)


def crm_crear_lead(nombre: str, email: str = "", telefono: str = "", empresa: str = "") -> dict | None:
    """Crea un Lead (contacto comercial por convertir) en el CRM, con nombre y, si los hay, email, teléfono y empresa."""
    return _mt.espocrm.crear_lead(nombre, email=email, telefono=telefono, empresa=empresa)


def crm_listar_contactos(texto: str | None = None, limite: int = 20) -> list[dict]:
    """Busca/lista Contactos del CRM."""
    return _mt.espocrm.listar_contactos(texto=texto, limite=limite)


def crm_crear_contacto(nombre: str, email: str = "", telefono: str = "") -> dict | None:
    """Crea un Contacto en el CRM."""
    return _mt.espocrm.crear_contacto(nombre, email=email, telefono=telefono)


def crm_listar_cuentas(texto: str | None = None, limite: int = 20) -> list[dict]:
    """Busca/lista Cuentas (empresas/clientes) del CRM."""
    return _mt.espocrm.listar_cuentas(texto=texto, limite=limite)


def crm_crear_cuenta(nombre: str, sitio_web: str = "") -> dict | None:
    """Crea una Cuenta en el CRM."""
    return _mt.espocrm.crear_cuenta(nombre, sitio_web=sitio_web)


# --- Drive (Nextcloud) -----------------------------------------------------------

def drive_listar_archivos(carpeta: str = "") -> list[dict]:
    """Lista archivos/carpetas del Drive en `carpeta` (ej. "Lueira" para el
    espacio compartido de ese tenant; vacío para la raíz)."""
    return _mt.nextcloud.listar_archivos(carpeta)


def drive_buscar_archivos(texto: str, limite: int = 20) -> list[dict]:
    """Busca archivos por nombre en todo el Drive."""
    return _mt.nextcloud.buscar_archivos(texto, limite=limite)


def drive_subir_archivo(ruta: str, contenido_texto: str) -> dict:
    """Sube un archivo de texto al Drive en `ruta` (ej. "Lueira/nota.txt").
    Para binarios, usa la propia interfaz web de Nextcloud."""
    return _mt.nextcloud.subir_archivo(ruta, contenido_texto.encode("utf-8"))


def drive_descargar_archivo(ruta: str) -> str:
    """Descarga un archivo de texto del Drive por su ruta."""
    return _mt.nextcloud.descargar_archivo(ruta).decode("utf-8", errors="replace")


def enviar_archivo_drive_al_chat(ruta: str) -> dict:
    """Manda un archivo del Drive (foto, PDF, cualquier tipo) al chat del
    Asistente IA integrado -- a diferencia de drive_descargar_archivo (que
    decodifica como texto y rompe con binarios), aquí se maneja el
    contenido en bruto y se guarda como adjunto del chat en vez de
    devolverlo en la respuesta de la tool."""
    contenido = _mt.nextcloud.descargar_archivo(ruta)
    nombre_archivo = ruta.rsplit("/", 1)[-1] or ruta
    return _mt._guardar_adjunto_para_chat(nombre_archivo, contenido)


# --- OpenProject -----------------------------------------------------------------

def proyectos_listar() -> list[dict]:
    """Lista los proyectos de OpenProject."""
    return _mt.openproject.listar_proyectos()


def proyectos_listar_tareas(proyecto_id: int | None = None, texto: str | None = None, limite: int = 20) -> list[dict]:
    """Lista/busca paquetes de trabajo (tareas) de OpenProject."""
    return _mt.openproject.listar_paquetes_trabajo(proyecto_id=proyecto_id, texto=texto, limite=limite)


def proyectos_crear_tarea(proyecto_id: int, asunto: str, tipo_id: int = 1) -> dict:
    """Crea un paquete de trabajo (tarea) en un proyecto de OpenProject."""
    return _mt.openproject.crear_paquete_trabajo(proyecto_id, asunto, tipo_id=tipo_id)


# --- Soporte (Chatwoot) ------------------------------------------------------------

def soporte_listar_conversaciones(estado: str = "open", limite: int = 20) -> list[dict]:
    """Lista conversaciones de la bandeja de soporte (Chatwoot). `estado`:
    open/resolved/pending/all."""
    return _mt.chatwoot.listar_conversaciones(estado_filtro=estado, limite=limite)


def soporte_leer_conversacion(conversacion_id: int) -> list[dict]:
    """Mensajes de una conversación de soporte."""
    return _mt.chatwoot.leer_conversacion(conversacion_id)


def soporte_responder_conversacion(conversacion_id: int, texto: str) -> dict:
    """Responde en una conversación de soporte existente."""
    return _mt.chatwoot.responder_conversacion(conversacion_id, texto)


# --- Analítica (Metabase) ----------------------------------------------------------

def analitica_listar_preguntas() -> list[dict]:
    """Lista las preguntas/consultas guardadas en Metabase."""
    return _mt.metabase.listar_preguntas()


def analitica_ejecutar_pregunta(pregunta_id: int) -> dict:
    """Ejecuta una pregunta ya guardada en Metabase y devuelve sus resultados."""
    return _mt.metabase.ejecutar_pregunta(pregunta_id)


def analitica_listar_dashboards() -> list[dict]:
    """Lista los dashboards guardados en Metabase."""
    return _mt.metabase.listar_dashboards()


# --- Automatizaciones (n8n) --------------------------------------------------------

def automatizaciones_listar_flujos(limite: int = 20) -> list[dict]:
    """Lista los flujos de automatización de n8n."""
    return _mt.n8n.listar_flujos(limite=limite)


def automatizaciones_ejecutar_flujo(flujo_id: str) -> dict:
    """Ejecuta un flujo de n8n ya existente por su id."""
    return _mt.n8n.ejecutar_flujo(flujo_id)


# --- Documentación (Outline) --------------------------------------------------------

def documentacion_listar_colecciones() -> list[dict]:
    """Lista las colecciones (carpetas) de la wiki de Outline."""
    return _mt.outline.listar_colecciones()


def documentacion_buscar(texto: str, limite: int = 20) -> list[dict]:
    """Búsqueda de texto completo en la wiki de Outline."""
    return _mt.outline.buscar_documentos(texto, limite=limite)


def documentacion_leer(documento_id: str) -> dict:
    """Lee un documento completo de la wiki de Outline."""
    return _mt.outline.leer_documento(documento_id)


def documentacion_crear(coleccion_id: str, titulo: str, texto: str = "", publicar: bool = True) -> dict:
    """Crea un documento nuevo en la wiki de Outline."""
    return _mt.outline.crear_documento(coleccion_id, titulo, texto=texto, publicar=publicar)


# --- Chat (Synapse/Matrix) ---------------------------------------------------------

def chat_listar_salas() -> list[dict]:
    """Lista las salas de chat a las que pertenece el asistente."""
    return _mt.synapse.listar_salas()


def chat_enviar_mensaje(sala_id: str, texto: str) -> dict:
    """Envía un mensaje a una sala de chat existente."""
    return _mt.synapse.enviar_mensaje(sala_id, texto)


# --- Almacenamiento de archivos (MinIO) ---------------------------------------------

def almacenamiento_listar_buckets() -> list[dict]:
    """Lista los buckets de MinIO."""
    return _mt.minio_cliente.listar_buckets()


def almacenamiento_listar_archivos(bucket: str, prefijo: str = "", limite: int = 50) -> list[dict]:
    """Lista los archivos de un bucket de MinIO."""
    return _mt.minio_cliente.listar_archivos(bucket, prefijo=prefijo, limite=limite)


def almacenamiento_url_descarga(bucket: str, nombre_archivo: str, expira_minutos: int = 60) -> str:
    """Genera una URL de descarga temporal y firmada para un archivo de MinIO."""
    return _mt.minio_cliente.url_descarga(bucket, nombre_archivo, expira_minutos=expira_minutos)


# --- Monitorización (Uptime Kuma) — solo lectura, ver app/uptime_kuma.py -----------

def monitorizacion_listar_estado() -> list[dict]:
    """Estado actual de cada monitor (activo/caído/pendiente/mantenimiento).
    Solo lectura — Uptime Kuma no tiene API de escritura fuera de Socket.IO."""
    return _mt.uptime_kuma.listar_monitores()


def _datos_facturascripts(tenant: str) -> tuple[str, str]:
    fila = _mt._tenant_autorizado_por_nombre(tenant)
    if fila is None:
        raise ValueError(f"No existe ningún tenant llamado '{tenant}'.")
    if not fila["facturascripts_api_key"]:
        raise ValueError(
            f"El tenant '{tenant}' todavía no tiene una API Key de FacturaScripts guardada "
            "(paso manual pendiente en el backoffice, ver HOSTING.md 8.21)."
        )
    return fila["facturascripts_url"], fila["facturascripts_api_key"]


def facturas_listar_clientes(tenant: str, texto: str | None = None, limite: int = 20) -> list[dict]:
    """Lista/busca clientes en la facturación de un tenant."""
    url, api_key = _mt._datos_facturascripts(tenant)
    return _mt.facturascripts.listar_clientes(url, api_key, texto=texto, limite=limite)


def facturas_crear_cliente(tenant: str, nombre: str, nif: str = "", email: str = "") -> dict:
    """Crea un cliente en la facturación de un tenant."""
    url, api_key = _mt._datos_facturascripts(tenant)
    return _mt.facturascripts.crear_cliente(url, api_key, nombre, nif=nif, email=email)


def facturas_listar_facturas(tenant: str, cliente_codigo: str | None = None, limite: int = 20) -> list[dict]:
    """Lista facturas de cliente de un tenant, opcionalmente filtradas por
    `cliente_codigo`."""
    url, api_key = _mt._datos_facturascripts(tenant)
    return _mt.facturascripts.listar_facturas(url, api_key, cliente_codigo=cliente_codigo, limite=limite)


def facturas_crear_factura(tenant: str, cliente_codigo: str, lineas: list[dict]) -> dict:
    """Crea una factura de cliente. `lineas`: lista de
    {"descripcion": str, "cantidad": float, "precio": float}."""
    url, api_key = _mt._datos_facturascripts(tenant)
    return _mt.facturascripts.crear_factura(url, api_key, cliente_codigo, lineas)


def _api_key_documenso(tenant: str) -> str:
    fila = _mt._tenant_autorizado_por_nombre(tenant)
    if fila is None:
        raise ValueError(f"No existe ningún tenant llamado '{tenant}'.")
    if not fila["documenso_api_key"]:
        raise ValueError(
            f"El tenant '{tenant}' todavía no tiene un token de Documenso guardado "
            "(crea su Equipo y genera un token desde dentro de él, ver HOSTING.md)."
        )
    return fila["documenso_api_key"]


def firmas_listar_documentos(tenant: str, texto: str | None = None, limite: int = 20) -> list[dict]:
    """Lista/busca documentos de firma de un tenant."""
    return _mt.documenso.listar_documentos(_mt._api_key_documenso(tenant), texto=texto, limite=limite)


def firmas_crear_documento(tenant: str, titulo: str, contenido_pdf_base64: str, firmantes: list[dict]) -> dict:
    """Crea un documento para firmar (en borrador, sin enviar todavía).
    `contenido_pdf_base64`: el PDF codificado en base64. `firmantes`:
    lista de {"email": str, "nombre": str} — cada uno recibe un único
    campo de firma en la primera página, posición por defecto."""
    contenido_pdf = base64.b64decode(contenido_pdf_base64)
    return _mt.documenso.crear_documento(_mt._api_key_documenso(tenant), titulo, contenido_pdf, firmantes)


def firmas_enviar_a_firma(tenant: str, documento_id: str) -> dict:
    """Envía un documento en borrador — manda el email de firma a cada
    destinatario."""
    return _mt.documenso.enviar_a_firma(_mt._api_key_documenso(tenant), documento_id)


def firmas_descargar_firmado(tenant: str, documento_id: str) -> str:
    """Descarga un documento (PDF en base64 — firmado del todo o no, el
    propio PDF refleja el estado actual)."""
    contenido = _mt.documenso.descargar_firmado(_mt._api_key_documenso(tenant), documento_id)
    return base64.b64encode(contenido).decode("ascii")


def _api_key_documenso_actual() -> str:
    tenant = _mt._tenant_actual()
    if not tenant["documenso_api_key"]:
        raise ValueError(
            "Tu gestoría todavía no tiene un token de Documenso guardado "
            "(pide a un admin que cree su Equipo y genere un token, ver HOSTING.md)."
        )
    return tenant["documenso_api_key"]


def listar_documentos_firma(texto: str | None = None, limite: int = 20) -> list[dict]:
    """Lista/busca documentos de firma (Documenso) de tu gestoría."""
    return _mt.documenso.listar_documentos(_mt._api_key_documenso_actual(), texto=texto, limite=limite)


def crear_documento_firma(titulo: str, contenido_pdf_base64: str, firmantes: list[dict]) -> dict:
    """Crea un documento para firmar (en borrador, sin enviar todavía).
    `contenido_pdf_base64`: el PDF codificado en base64. `firmantes`: lista
    de {"email": str, "nombre": str}."""
    contenido_pdf = base64.b64decode(contenido_pdf_base64)
    return _mt.documenso.crear_documento(_mt._api_key_documenso_actual(), titulo, contenido_pdf, firmantes)


def enviar_documento_a_firma(documento_id: str) -> dict:
    """Envía un documento en borrador — manda el email de firma a cada
    destinatario. Pide siempre confirmación antes de ejecutar."""
    return _mt.documenso.enviar_a_firma(_mt._api_key_documenso_actual(), documento_id)


def enviar_documento_firmado_al_chat(documento_id: str) -> dict:
    """Manda un documento de Documenso (firmado del todo o no, el propio
    PDF refleja el estado actual) al chat del Asistente IA integrado."""
    contenido = _mt.documenso.descargar_firmado(_mt._api_key_documenso_actual(), documento_id)
    return _mt._guardar_adjunto_para_chat(f"documento-{documento_id}.pdf", contenido, tipo_mime="application/pdf")


def _datos_paperless(tenant: str) -> tuple[str, int, int]:
    fila = _mt._tenant_autorizado_por_nombre(tenant)
    if fila is None:
        raise ValueError(f"No existe ningún tenant llamado '{tenant}'.")
    if not fila["paperless_api_key"]:
        raise ValueError(
            f"El tenant '{tenant}' todavía no tiene Paperless-ngx aprovisionado "
            "(sin PAPERLESS_ADMIN_USER/PASSWORD configuradas, o creado antes de esta integración)."
        )
    return fila["paperless_api_key"], fila["paperless_user_id"], fila["paperless_group_id"]


def documentos_listar(tenant: str, texto: str | None = None, limite: int = 20) -> list[dict]:
    """Lista/busca documentos de un tenant en Paperless-ngx."""
    api_key, _, _ = _mt._datos_paperless(tenant)
    return _mt.paperless.listar_documentos(api_key, texto=texto, limite=limite)


def documentos_subir(tenant: str, titulo: str, contenido_pdf_base64: str, nombre_archivo: str) -> dict:
    """Sube un documento (PDF en base64) a Paperless-ngx para OCR/indexado
    — solo visible/editable por ese tenant."""
    api_key, user_id, group_id = _mt._datos_paperless(tenant)
    contenido_pdf = base64.b64decode(contenido_pdf_base64)
    return _mt.paperless.subir_documento(api_key, user_id, group_id, titulo, contenido_pdf, nombre_archivo)


def documentos_descargar(tenant: str, documento_id: str) -> str:
    """Descarga un documento de un tenant (PDF en base64)."""
    api_key, _, _ = _mt._datos_paperless(tenant)
    contenido = _mt.paperless.descargar_documento(api_key, documento_id)
    return base64.b64encode(contenido).decode("ascii")


def _api_key_baserow(tenant: str) -> str:
    fila = _mt._tenant_autorizado_por_nombre(tenant)
    if fila is None:
        raise ValueError(f"No existe ningún tenant llamado '{tenant}'.")
    if not fila["baserow_api_key"]:
        raise ValueError(
            f"El tenant '{tenant}' todavía no tiene Baserow aprovisionado "
            "(sin BASEROW_ADMIN_EMAIL/PASSWORD configuradas, o creado antes de esta integración)."
        )
    return fila["baserow_api_key"]


def hojas_listar_tablas(tenant: str) -> list[dict]:
    """Lista las tablas del Workspace de un tenant en Baserow."""
    return _mt.baserow.listar_tablas(_mt._api_key_baserow(tenant))


def hojas_listar_filas(tenant: str, tabla_id: int, texto: str | None = None, limite: int = 20) -> list[dict]:
    """Lista/busca filas de una tabla de un tenant."""
    return _mt.baserow.listar_filas(_mt._api_key_baserow(tenant), tabla_id, texto=texto, limite=limite)


def hojas_crear_fila(tenant: str, tabla_id: int, campos: dict) -> dict:
    """Crea una fila en una tabla de un tenant. `campos`: {"Nombre de
    columna": valor, ...} — los nombres de columna son las propias
    claves del diccionario."""
    return _mt.baserow.crear_fila(_mt._api_key_baserow(tenant), tabla_id, campos)


def _api_key_baserow_actual() -> str:
    tenant = _mt._tenant_actual()
    if not tenant["baserow_api_key"]:
        raise ValueError(
            "Tu gestoría todavía no tiene Baserow aprovisionado "
            "(sin BASEROW_ADMIN_EMAIL/PASSWORD configuradas, o creado antes de esta integración)."
        )
    return tenant["baserow_api_key"]


def listar_tablas_hojas() -> list[dict]:
    """Lista las tablas del Workspace de Baserow de tu gestoría."""
    return _mt.baserow.listar_tablas(_mt._api_key_baserow_actual())


def listar_filas_hoja(tabla_id: int, texto: str | None = None, limite: int = 20) -> list[dict]:
    """Lista/busca filas de una tabla de tu gestoría."""
    return _mt.baserow.listar_filas(_mt._api_key_baserow_actual(), tabla_id, texto=texto, limite=limite)


def _api_key_calcom(tenant: str) -> str:
    fila = _mt._tenant_autorizado_por_nombre(tenant)
    if fila is None:
        raise ValueError(f"No existe ningún tenant llamado '{tenant}'.")
    if not fila["calcom_api_key"]:
        raise ValueError(
            f"El tenant '{tenant}' todavía no tiene una API Key de Cal.diy guardada "
            "(paso manual pendiente en el backoffice, ver HOSTING.md 8.25)."
        )
    return fila["calcom_api_key"]


def citas_listar_tipos_evento(tenant: str) -> list[dict]:
    """Lista los tipos de evento (los "servicios" reservables) de un tenant."""
    return _mt.calcom.listar_tipos_evento(_mt._api_key_calcom(tenant))


def citas_listar_reservas(tenant: str, desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Lista las reservas de un tenant, opcionalmente acotadas por fecha
    (ISO 8601)."""
    return _mt.calcom.listar_reservas(_mt._api_key_calcom(tenant), desde=desde, hasta=hasta)


def citas_crear_reserva(tenant: str, tipo_evento_id: int, inicio: str, nombre_asistente: str, email_asistente: str) -> dict:
    """Crea una reserva para un tenant. `inicio`: fecha/hora en ISO 8601
    UTC (ej. "2026-08-01T10:00:00Z"). Genera automáticamente una sala de
    videollamada de Jitsi Meet para la reserva (campo `video_url` en el
    resultado) — si JITSI_JWT_APP_ID/SECRET no están configuradas, la
    reserva se crea igual, sin `video_url`."""
    resultado = _mt.calcom.crear_reserva(_mt._api_key_calcom(tenant), tipo_evento_id, inicio, nombre_asistente, email_asistente)
    if resultado.get("uid"):
        try:
            sala = _mt.jitsi.nombre_sala(tenant, resultado["uid"])
            token = _mt.jitsi.generar_jwt_sala(tenant, nombre_asistente, sala)
            resultado["video_url"] = _mt.jitsi.url_sala(sala, token)
        except _mt.jitsi.ErrorJitsi:
            pass
        try:
            fila_tenant = _mt._tenant_autorizado_por_nombre(tenant)
            _mt.eventos.emitir(
                "cita.reservada", fila_tenant["id"] if fila_tenant else None,
                {"reserva_uid": resultado["uid"], "inicio": inicio, "nombre_asistente": nombre_asistente, "email_asistente": email_asistente},
            )
        except Exception:
            pass
    return resultado


def citas_cancelar_reserva(tenant: str, reserva_uid: str, motivo: str = "") -> dict:
    """Cancela una reserva de un tenant por su identificador (uid)."""
    return _mt.calcom.cancelar_reserva(_mt._api_key_calcom(tenant), reserva_uid, motivo)


def _tenant_id_por_nombre(tenant: str | None) -> int | None:
    if tenant is None:
        return None
    fila = _mt._tenant_autorizado_por_nombre(tenant)
    if fila is None:
        raise ValueError(f"No existe ningún tenant llamado '{tenant}'.")
    return fila["id"]


def _gestiona_webhooks(tenant_id: int | None) -> bool:
    """Admin global y usuario local: todo. Supervisor de un despacho: solo los de su despacho."""
    uid = _mt._uid()
    usuario = _mt.db.obtener_usuario(uid)
    if _mt.db.es_admin(uid) or (usuario is not None and usuario["es_local"]):
        return True
    propio = _mt.db.tenant_de_usuario(uid)
    return tenant_id is not None and propio is not None and propio["id"] == tenant_id and _mt.db.es_supervisor_tenant(uid)


def _exigir_webhooks(tenant_id: int | None) -> None:
    if not _mt._gestiona_webhooks(tenant_id):
        raise ValueError("Solo un supervisor de ese despacho o un administrador puede gestionar sus webhooks.")


def webhooks_listar(tenant: str | None = None) -> list[dict]:
    """Lista los webhooks configurados (de un tenant, o de ámbito local
    si no se indica `tenant`) — sin el `secreto` (ver
    webhooks_crear para eso, solo se enseña una vez al crearlo)."""
    tenant_id = _mt._tenant_id_por_nombre(tenant)
    _mt._exigir_webhooks(tenant_id)
    filas = _mt.db.listar_webhooks(tenant_id)
    return [{k: v for k, v in dict(f).items() if k != "secreto"} for f in filas]


def webhooks_crear(url: str, eventos_suscritos: list[str], tenant: str | None = None) -> dict:
    """Da de alta un webhook — `eventos_suscritos` de entre
    app/eventos.py:EVENTOS (tarea.finalizada, nota.creada,
    cita.reservada, correo.mensaje_nuevo). El `secreto` devuelto (para
    verificar la firma HMAC de cada entrega, ver HOSTING.md) solo se
    enseña esta vez, igual que el resto de credenciales generadas de
    este proyecto. Para quien no es administrador la URL debe ser https y pública."""
    invalidos = [e for e in eventos_suscritos if e not in _mt.eventos.EVENTOS]
    if invalidos:
        raise ValueError(f"Eventos no reconocidos: {invalidos}. Válidos: {_mt.eventos.EVENTOS}")
    tenant_id = _mt._tenant_id_por_nombre(tenant)
    _mt._exigir_webhooks(tenant_id)
    uid = _mt._uid()
    usuario = _mt.db.obtener_usuario(uid)
    de_confianza = _mt.db.es_admin(uid) or (usuario is not None and usuario["es_local"])
    if not de_confianza:
        ok, motivo = _mt.eventos.validar_url_publica(url)
        if not ok:
            raise ValueError(motivo)
    return dict(_mt.db.crear_webhook(uid, tenant_id, url, eventos_suscritos, origen="backoffice" if de_confianza else "mcp"))


def webhooks_borrar(webhook_id: int) -> None:
    """Borra un webhook (y su historial de entregas) por id."""
    w = _mt.db.obtener_webhook(webhook_id)
    if w is None:
        raise ValueError(f"No existe el webhook {webhook_id}.")
    _mt._exigir_webhooks(w["tenant_id"])
    _mt.db.borrar_webhook(webhook_id)


def _datos_listmonk(tenant: str) -> tuple[str, int]:
    fila = _mt._tenant_autorizado_por_nombre(tenant)
    if fila is None:
        raise ValueError(f"No existe ningún tenant llamado '{tenant}'.")
    if not fila["listmonk_api_key"]:
        raise ValueError(
            f"El tenant '{tenant}' todavía no tiene Listmonk aprovisionado "
            "(sin LISTMONK_ADMIN_USER/PASSWORD configuradas, o creado antes de esta integración)."
        )
    return fila["listmonk_api_key"], fila["listmonk_list_id"]


def newsletter_listar_suscriptores(tenant: str, texto: str | None = None, limite: int = 20) -> list[dict]:
    """Lista/busca suscriptores de la lista de un tenant."""
    api_key, list_id = _mt._datos_listmonk(tenant)
    return _mt.listmonk.listar_suscriptores(api_key, list_id, texto=texto, limite=limite)


def newsletter_crear_suscriptor(tenant: str, email: str, nombre: str, atribs: dict | None = None) -> dict:
    """Añade un suscriptor a la lista de un tenant."""
    api_key, list_id = _mt._datos_listmonk(tenant)
    return _mt.listmonk.crear_suscriptor(api_key, list_id, email, nombre, atribs)


def newsletter_listar_campanas(tenant: str) -> list[dict]:
    """Lista las campañas (newsletters) de un tenant."""
    api_key, _ = _mt._datos_listmonk(tenant)
    return _mt.listmonk.listar_campanas(api_key)


def newsletter_crear_campana(tenant: str, nombre: str, asunto: str, cuerpo_html: str) -> dict:
    """Crea una campaña (newsletter) en borrador para la lista de un tenant."""
    api_key, list_id = _mt._datos_listmonk(tenant)
    return _mt.listmonk.crear_campana(api_key, list_id, nombre, asunto, cuerpo_html)


def newsletter_enviar_campana(tenant: str, campana_id: int) -> dict:
    """Envía una campaña de un tenant ya creada."""
    api_key, _ = _mt._datos_listmonk(tenant)
    return _mt.listmonk.enviar_campana(api_key, campana_id)


def _api_key_stalwart(tenant: str) -> str:
    fila = _mt._tenant_autorizado_por_nombre(tenant)
    if fila is None:
        raise ValueError(f"No existe ningún tenant llamado '{tenant}'.")
    if not fila["stalwart_api_key"]:
        raise ValueError(
            f"El tenant '{tenant}' todavía no tiene Stalwart aprovisionado "
            "(sin STALWART_ADMIN_USER/PASSWORD configuradas, sin dominio_correo "
            "en el alta del tenant, o creado antes de esta integración)."
        )
    return fila["stalwart_api_key"]


def correo_stalwart_listar_mensajes(tenant: str, mailbox: str = "INBOX", limite: int = 20) -> list[dict]:
    """Lista los mensajes recientes de un buzón de un tenant (Stalwart)."""
    return _mt.stalwart.listar_mensajes(_mt._api_key_stalwart(tenant), mailbox=mailbox, limite=limite)


def correo_stalwart_leer_mensaje(tenant: str, email_id: str) -> dict:
    """Lee el contenido completo de un mensaje de un tenant (Stalwart)."""
    return _mt.stalwart.leer_mensaje(_mt._api_key_stalwart(tenant), email_id)


def correo_stalwart_enviar_mensaje(tenant: str, para: str, asunto: str, cuerpo: str) -> dict:
    """Envía un mensaje desde la cuenta de correo de un tenant (Stalwart)."""
    return _mt.stalwart.enviar_mensaje(_mt._api_key_stalwart(tenant), para, asunto, cuerpo)


def _datos_ntfy(tenant: str) -> tuple[str, str]:
    fila = _mt._tenant_autorizado_por_nombre(tenant)
    if fila is None:
        raise ValueError(f"No existe ningún tenant llamado '{tenant}'.")
    if not fila["ntfy_token"]:
        raise ValueError(f"El tenant '{tenant}' todavía no tiene ntfy aprovisionado.")
    return fila["ntfy_topic"], fila["ntfy_token"]


def notificaciones_enviar(tenant: str, titulo: str, mensaje: str, prioridad: str = "default") -> dict:
    """Envía una notificación push al móvil/escritorio de un tenant
    (ntfy). `prioridad`: min/low/default/high/urgent."""
    topic, token = _mt._datos_ntfy(tenant)
    _mt.ntfy.enviar(topic, token, titulo, mensaje, prioridad=prioridad)
    return {"enviado": True, "topic": topic}


def videollamadas_crear_sala(tenant: str, nombre_mostrado: str, moderador: bool = True) -> dict:
    """Crea una sala de videollamada nueva para un tenant (Jitsi Meet) y
    devuelve su URL. No hace falta que la sala exista de antemano — se
    crea sola al entrar la primera persona con un enlace válido."""
    if _mt._tenant_autorizado_por_nombre(tenant) is None:
        raise ValueError(f"No existe ningún tenant llamado '{tenant}'.")
    sala = _mt.jitsi.nombre_sala(tenant, uuid.uuid4().hex[:12])
    token = _mt.jitsi.generar_jwt_sala(tenant, nombre_mostrado, sala, moderador=moderador)
    return {"url": _mt.jitsi.url_sala(sala, token), "sala": sala}
