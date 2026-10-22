"""Implementaciones de todas las tools MCP de Guilda Work — notas, tareas,
correo, export/import (lo propio de la app) y, desde la Fase MCP, todo el
stack Docker conectado (EspoCRM, Nextcloud, OpenProject, Chatwoot,
Metabase, n8n, Outline, Synapse, MinIO, Uptime Kuma).

Módulo compartido a propósito entre los dos transportes de servidor MCP
de este proyecto — mismas funciones, sin duplicar nada:

- `mcp_server.py` (stdio): para Claude Code/Desktop y Codex CLI, proceso
  local sin autenticación de por medio (confianza del propio sistema
  operativo, igual que siempre).
- `mcp_server_remoto.py` (streamable-http + OAuth2 vía Ory Hydra): para
  ChatGPT, que solo admite servidores MCP remotos por HTTPS con
  autenticación real (ver HOSTING.md, sección MCP remoto).

Cada función de aquí es una tool normal e independiente — se registra
sobre un `FastMCP` con `mcp.add_tool(funcion)` (ver `registrar_tools`),
en vez de usar el decorador `@mcp.tool()` directamente, para que las dos
instancias de servidor puedan compartir exactamente las mismas funciones
sin copiarlas. Esto también las hace triviales de testear: se llaman
como funciones Python normales, con `monkeypatch` sobre los clientes de
`app/*.py`, sin necesitar un servidor MCP de verdad levantado.

Multiusuario (Fase 1 de la app móvil): de cara a Claude Code/Codex/Claude
Desktop, este servidor sigue operando como un único usuario de confianza —
el "usuario local" (`db.usuario_local_id()`), el mismo que la app de
escritorio — sin ningún parámetro de usuario visible en las tools (no tiene
sentido pedirle a un cliente MCP que se autentique). El Asistente IA
integrado en la propia app (app/ia_herramientas.py) SÍ necesita poder
ejecutar estas mismas funciones "como" el usuario que ha iniciado sesión en
la web, no siempre el local — para eso, `_usuario_id_actual` es una
contextvar que `ia_herramientas.ejecutar()` fija antes de llamar y restaura
después; si nadie la ha fijado (el caso normal, un cliente MCP externo),
`_uid()` cae automáticamente al usuario local.

Herramientas externas del stack Docker (Fase MCP): sin ningún filtrado por
tenant — el MCP sigue actuando como administrador global de confianza,
decisión explícita del usuario (ver plan de esta fase), igual que ya
ocurre con notas/tareas. **Vaultwarden queda excluido a propósito, bajo
ningún concepto**: es un gestor de contraseñas, y exponerlo por MCP
supondría un riesgo real de fuga de credenciales vía un prompt.

Permisos: todas las tools de notas/tareas/calendario/correo (incluidas
carpetas y categorías) son de lectura o escritura directa. La única
excepción es el envío de correo, que es un proceso de DOS pasos deliberado:
preparar_borrador_correo() no envía nada, solo devuelve una vista previa y
un borrador_id; enviar_borrador_correo(id) es la que de verdad envía, y por
eso conviene pedir confirmación explícita al usuario antes de llamarla (el
propio cliente MCP normalmente ya lo pide para acciones "de envío", pero
este diseño de dos pasos da un punto de control adicional pase lo que pase).
Cco (bcc) en preparar_borrador_correo nunca viaja como cabecera visible del
mensaje enviado, solo como destinatario oculto real.
"""
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

# Borradores de correo preparados en esta sesión del servidor (en memoria:
# si el proceso se reinicia, hay que volver a prepararlos con
# preparar_borrador_correo — no hace falta persistirlos en disco).
_BORRADORES_CORREO: dict[str, dict] = {}

# Ver docstring del módulo: normalmente vacía (cliente MCP externo = usuario
# local); app/ia_herramientas.py la fija temporalmente al usuario web actual.
_usuario_id_actual: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "_usuario_id_actual", default=None
)


def _uid() -> int:
    """Resuelve el usuario "actual" para esta llamada, en orden:
    1. `_usuario_id_actual` — el Asistente IA integrado en la app lo fija
       explícitamente al usuario que ha iniciado sesión en la web.
    2. El `sub` del token OAuth2 verificado por `mcp_server_remoto.py`
       (`VerificadorHydra`, ver ese archivo) — el mismo identity_id de
       Kratos que ya usa `app/rutas_hydra.py` al aceptar el login/consent.
       Sin esto, cualquier llamada desde un cliente MCP remoto (Claude
       Desktop, ChatGPT) operaría siempre sobre el usuario local aunque
       cada persona se autentique con su propia cuenta — encontrado en
       vivo: una tarea creada así no aparecía en la web del usuario que
       la pidió, porque quedaba guardada bajo el usuario local (id 1) en
       vez del suyo.
    3. `db.usuario_local_id()` — cliente MCP local (stdio) sin sesión web
       de por medio, mismo comportamiento de siempre para Claude Code/
       Codex CLI en modo escritorio."""
    if _usuario_id_actual.get():
        return _usuario_id_actual.get()
    token = get_access_token()
    if token is not None:
        from app import mcp_acceso

        personal = mcp_acceso.usuario_de_scopes(token.scopes)       # token personal de API
        if personal is not None:
            return personal
    if token is not None and token.subject:
        usuario = db.usuario_por_kratos_id(token.subject)
        if usuario is not None:
            return usuario["id"]
    return db.usuario_local_id()


def _tenant_autorizado_por_nombre(nombre: str | None):
    """Fila del tenant llamado `nombre` SOLO si quien llama puede operar sobre él: es administrador global, es el usuario
    local de escritorio (stdio, su propia máquina) o pertenece a ese despacho. En cualquier otro caso responde igual que
    si no existiera (no se puede averiguar qué despachos hay). Sin esto, cualquier usuario de la gestoría A podía operar
    la facturación, los documentos, el correo o los webhooks de la gestoría B solo con escribir su nombre."""
    fila = db.obtener_tenant_por_nombre(nombre) if nombre else None
    if fila is None:
        return None
    uid = _uid()
    usuario = db.obtener_usuario(uid)
    if db.es_admin(uid) or (usuario is not None and usuario["es_local"]):
        return fila
    propio = db.tenant_de_usuario(uid)
    return fila if propio is not None and propio["id"] == fila["id"] else None


def _fila(fila: sqlite3.Row | None) -> dict | None:
    return dict(fila) if fila is not None else None


def _filas(filas) -> list[dict]:
    return [dict(f) for f in filas]


def _resolver_categoria_id(nombre_o_id: str | int | None) -> int | None:
    """Acepta tanto el id numérico como el nombre del proyecto/categoría."""
    if nombre_o_id in (None, ""):
        return None
    if isinstance(nombre_o_id, int) or str(nombre_o_id).isdigit():
        return int(nombre_o_id)
    uid = _uid()
    for c in db.listar_categorias(uid):
        if c["nombre"].lower() == str(nombre_o_id).lower():
            return c["id"]
    raise ValueError(
        f"No existe ningún proyecto/categoría llamado '{nombre_o_id}'. "
        f"Disponibles: {', '.join(c['nombre'] for c in db.listar_categorias(uid))}"
    )


_AVISO_CORREO_PROTEGIDO = ("Este mensaje está protegido con la clave del despacho y ahora no hay clave disponible: un responsable tiene que desbloquear los documentos "
                           "(Seguridad del despacho), o la conexión necesita un acceso concedido a lo cifrado. No es que esté vacío.")


# --- Facturación (FacturaScripts) — ÚNICO cliente con parámetro `tenant` -----
#
# A diferencia de todas las demás herramientas de este catálogo (una
# instancia compartida, sin concepto de tenant para el MCP — ver
# docstring del módulo), FacturaScripts tiene una instancia física
# distinta POR TENANT (aislamiento real, ver app/facturascripts.py) —
# así que aquí sí hace falta decir de qué tenant se habla en cada
# llamada. `tenant` es el nombre tal cual aparece en el backoffice.


# --- Firmas (Documenso) — segundo cliente con parámetro `tenant` -------------
#
# Igual que FacturaScripts, `tenant` hace falta aquí porque el
# aislamiento entre tenants no lo da una instancia física distinta (es
# una instancia compartida, como EspoCRM/Nextcloud) sino qué token de
# Equipo se use — sin `tenant`, no habría forma de saber qué Equipo debe
# ver/crear cada documento. El Equipo y el token se crean a mano (ver
# HOSTING.md) — no hay API para eso, verificado en vivo (app/documenso.py).


# --- Firmas -- versiones para el Asistente IA integrado, tenant resuelto solo ---
#
# Mismo patrón que listar_facturas_cliente/crear_factura_cliente: nada de
# parámetro `tenant` (el usuario de la web ya tiene uno, no tiene sentido
# pedírselo al LLM), se resuelve vía _tenant_actual().


# --- Documentos (Paperless-ngx) — tercer cliente con parámetro `tenant` ------
#
# A diferencia de Documenso, aquí el aprovisionamiento (Grupo + usuario de
# servicio + token) es 100% automático (ver app/rutas_backoffice.py:
# crear_tenant() → app/paperless.py:aprovisionar_tenant()) — `tenant`
# sigue haciendo falta porque el aislamiento depende de qué usuario de
# servicio/Grupo se use, no de una instancia física distinta.


# --- Hojas (Baserow) — cuarto cliente con parámetro `tenant` -----------------
#
# El token de base de datos de Baserow ya está ligado a un único
# Workspace (ver app/baserow.py) — `tenant` sigue haciendo falta para
# resolver qué token usar, mismo motivo que facturas_*/firmas_*/documentos_*.


# --- Hojas -- versiones para el Asistente IA integrado, tenant resuelto solo ---
# Solo lectura por decisión del usuario -- hojas_crear_fila no se expone aquí.


# --- Citas (Cal.diy) — quinto cliente con parámetro `tenant` ----------------
#
# Instancia compartida (a diferencia de FacturaScripts, ver app/calcom.py)
# — el API Key aquí está ligado a la cuenta de servicio de un tenant, no a
# una instancia física, pero `tenant` sigue haciendo falta para resolver
# cuál usar, mismo motivo que facturas_*/firmas_*/documentos_*/hojas_*.


# --- Webhooks salientes (ver app/eventos.py) --------------------------------
#
# `tenant` es opcional (None = webhooks de ámbito local/sin tenant,
# mismo criterio nullable que el resto de app/db.py) — a diferencia de
# facturas_*/citas_*/newsletter_*, aquí SÍ tiene sentido no pasar
# tenant: el modo escritorio (un único usuario local) también puede
# querer un webhook propio.


# --- Newsletter (Listmonk) — sexto cliente con parámetro `tenant` ----------
#
# Instancia compartida, aislada por Lista/Rol de lista (ver
# app/listmonk.py, verificado en vivo) — `tenant` resuelve qué Lista y
# qué token de servicio usar, mismo motivo que facturas_*/firmas_*/
# documentos_*/hojas_*/citas_*.


# --- Correo Stalwart — séptimo cliente con parámetro `tenant` --------------
#
# Instancia compartida, aislada por Account/ApiKey JMAP (ver
# app/stalwart.py, verificado en vivo: un accountId de otro tenant da
# 403 "forbidden" real del servidor) — `tenant` resuelve qué token de
# servicio usar, mismo motivo que newsletter_*/citas_*.


# --- Notificaciones (ntfy) — octavo cliente con parámetro `tenant` ---------
#
# Instancia compartida, aislada por usuario+topic (ver app/ntfy.py,
# verificado en vivo) — `tenant` resuelve qué topic y qué token propio
# usar, mismo motivo que facturas_*/firmas_*/documentos_*/hojas_*/
# citas_*/correo_stalwart_*.


# --- Videollamadas (Jitsi Meet) — noveno cliente con parámetro `tenant` ----
#
# Instancia compartida (una videollamada no tiene datos persistentes que
# aislar) — `tenant` solo sirve para prefijar el nombre de la sala (ver
# app/jitsi.py:nombre_sala), no hay credencial ni aprovisionamiento por
# tenant como en el resto de esta familia.


# --- Adjuntos del chat de IA (Fase G2) -------------------------------------

_ADJUNTO_MAX_CARACTERES = 20000  # margen razonable de contexto sin reventar la ventana del modelo


# --- Tiquets (soporte interno: errores/sugerencias) -----------------------
#
# A diferencia del resto de este archivo, es un tablero COMPARTIDO entre
# todos los usuarios (ver db.listar_tiquets/db.obtener_tiquet, que no
# filtran por usuario_id) — cualquiera puede leer todos los tiquets, pero
# solo editar/borrar los suyos propios (o cualquiera, si es admin), y solo
# un admin puede moverlos de estado. Mismos permisos exactos que
# app/rutas_tiquets.py, para que MCP nunca pueda hacer por API algo que la
# web no deje hacer por la interfaz.


# --- Calendario fiscal (clientes fiscales + vencimientos) ------------------
#
# A diferencia de tiquets (compartido entre TODOS los usuarios) o de
# fichaje (propio de cada usuario), esto es un dato del TENANT (la
# gestoría) -- se resuelve una vez por llamada con db.tenant_de_usuario(),
# igual que ya hace fichar() más abajo, y se lanza un error legible si el
# usuario no tiene tenant en vez de devolver una lista vacía silenciosa
# (mismo criterio que la propia web/app, ver app/rutas_fiscal.py:_exigir_tenant).


# Tamaño máximo de un archivo que el ASISTENTE puede mandar por el chat (p.ej.
# un documento del Drive o un PDF firmado) -- distinto del tope de subida del
# USUARIO (1MB, solo texto/CSV, ver app/rutas_ia.py:_ADJUNTO_TAMANO_MAXIMO_BYTES).
TAMANO_MAXIMO_ADJUNTO_ASISTENTE_BYTES = 25 * 1024 * 1024


_NOMBRE_ARCHIVO_CARACTERES_INVALIDOS = str.maketrans("", "", "\\/:*?\"<>|")


_FORMATOS_DOCUMENTO = {"csv": "text/csv", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                       "pdf": "application/pdf"}


_CLIENTE_CAMPOS = ("id", "nombre", "tipo", "nif", "email", "telefono", "estado", "responsable_nombre", "notas")
_EXPEDIENTE_CAMPOS = ("id", "titulo", "tipo", "estado", "referencia", "cliente_id", "cliente_nombre", "responsable_nombre", "proximo_plazo", "confidencial", "actualizado_en")
_PLAZO_CAMPOS = ("id", "titulo", "fecha_limite", "estado_calculado", "dias_restantes", "critico", "cliente_nombre", "expediente_id", "expediente_titulo", "responsable_nombre")


# --- Fichaje (registro horario) --------------------------------------------
#
# Deliberadamente acotado a lo propio del usuario actual -- entrada/salida/
# pausas y consultar su propio historial. La exportación de informes de
# administración (CSV/PDF, ver app/fichaje_export.py) es una acción de
# descarga de archivo y encaja mejor como acción web que como tool de IA,
# así que no tiene equivalente aquí.


# --- Papelera ----------------------------------------------------------------

_PAPELERA_RESTAURAR = {
    "menu": db.restaurar_categoria,
    "tarea": db.restaurar_tarea,
    "nota": db.restaurar_nota,
    "tarea_outlook": db.restaurar_tarea_outlook,
}


# --- Backoffice (gestión de tenants/usuarios) ------------------------------
#
# A diferencia del resto de este archivo (que actúa como "administrador de
# confianza" de las integraciones externas sin mirar quién llama), esto SÍ
# comprueba que quien llama es realmente admin de Guilda Work
# (`usuarios.rol = 'admin'`) antes de dejar hacer nada -- exactamente la
# misma condición que ya exige admin_required en la web (ver
# app/auth.py/app/rutas_backoffice.py). El backoffice controla quién tiene
# acceso a qué en toda la plataforma, no un tenant conectado más: MCP no
# debería poder dar aquí más poder del que ya tendría por la web quien
# esté detrás de la sesión.
#
# borrar_tenant NO tiene tool aquí a propósito: la versión web
# (rutas_backoffice.py) desaprovisiona en cascada media docena de
# servicios externos (FacturaScripts, Paperless, Baserow, Cal.diy,
# Listmonk, Stalwart, ntfy, Umami) con manejo de errores propio por
# servicio; replicarlo aquí sin esa misma cobertura dejaría cuentas
# huérfanas en esos servicios de forma silenciosa. Se queda como acción
# solo-web hasta que valga la pena portar esa orquestación completa.


# Proyectos de Guilda Work (los "menús" donde se agrupan notas y tareas;
# nada que ver con proyectos_* de OpenProject).


# Todas las tools de este módulo, en el mismo orden que se documentan en
# README.md — una única lista, para que ambos servidores (local y remoto)
# registren exactamente el mismo conjunto sin poder desincronizarse.
# --- Familias de herramientas (partes de este módulo, mcp_tools/herramientas_*.py). Se cargan aquí, antes del catálogo `TOOLS`, y se reexportan para que `mcp_tools.<nombre>` siga existiendo.
from .herramientas_tareas_notas import (  # noqa: E402,F401
    buscar_semantico,
    listar_notas,
    crear_nota,
    editar_nota,
    listar_tareas,
    crear_tarea,
    editar_tarea,
    completar_tarea,
    consultar_calendario,
)
from .herramientas_correo import (  # noqa: E402,F401
    conectar_cuenta_correo,
    listar_cuentas_correo,
    sincronizar_correo,
    listar_carpetas_correo,
    _con_aviso_protegido,
    listar_bandeja_entrada,
    leer_correo,
    marcar_leido_correo,
    eliminar_correo,
    listar_categorias_correo,
    crear_categoria_correo,
    eliminar_categoria_correo,
    asignar_categoria_correo,
    obtener_firma_correo,
    configurar_firma_correo,
    preparar_borrador_correo,
    enviar_borrador_correo,
)
from .herramientas_exportar import (  # noqa: E402,F401
    exportar_historial,
    importar_historial,
    exportar_tareas,
    importar_tareas,
    listar_papelera,
    restaurar_de_papelera,
    estadisticas_por_categoria,
    estadisticas_por_dia,
)
from .herramientas_integraciones import (  # noqa: E402,F401
    crm_listar_leads,
    crm_crear_lead,
    crm_listar_contactos,
    crm_crear_contacto,
    crm_listar_cuentas,
    crm_crear_cuenta,
    drive_listar_archivos,
    drive_buscar_archivos,
    drive_subir_archivo,
    drive_descargar_archivo,
    enviar_archivo_drive_al_chat,
    proyectos_listar,
    proyectos_listar_tareas,
    proyectos_crear_tarea,
    soporte_listar_conversaciones,
    soporte_leer_conversacion,
    soporte_responder_conversacion,
    analitica_listar_preguntas,
    analitica_ejecutar_pregunta,
    analitica_listar_dashboards,
    automatizaciones_listar_flujos,
    automatizaciones_ejecutar_flujo,
    documentacion_listar_colecciones,
    documentacion_buscar,
    documentacion_leer,
    documentacion_crear,
    chat_listar_salas,
    chat_enviar_mensaje,
    almacenamiento_listar_buckets,
    almacenamiento_listar_archivos,
    almacenamiento_url_descarga,
    monitorizacion_listar_estado,
    _datos_facturascripts,
    facturas_listar_clientes,
    facturas_crear_cliente,
    facturas_listar_facturas,
    facturas_crear_factura,
    _api_key_documenso,
    firmas_listar_documentos,
    firmas_crear_documento,
    firmas_enviar_a_firma,
    firmas_descargar_firmado,
    _api_key_documenso_actual,
    listar_documentos_firma,
    crear_documento_firma,
    enviar_documento_a_firma,
    enviar_documento_firmado_al_chat,
    _datos_paperless,
    documentos_listar,
    documentos_subir,
    documentos_descargar,
    _api_key_baserow,
    hojas_listar_tablas,
    hojas_listar_filas,
    hojas_crear_fila,
    _api_key_baserow_actual,
    listar_tablas_hojas,
    listar_filas_hoja,
    _api_key_calcom,
    citas_listar_tipos_evento,
    citas_listar_reservas,
    citas_crear_reserva,
    citas_cancelar_reserva,
    _tenant_id_por_nombre,
    _gestiona_webhooks,
    _exigir_webhooks,
    webhooks_listar,
    webhooks_crear,
    webhooks_borrar,
    _datos_listmonk,
    newsletter_listar_suscriptores,
    newsletter_crear_suscriptor,
    newsletter_listar_campanas,
    newsletter_crear_campana,
    newsletter_enviar_campana,
    _api_key_stalwart,
    correo_stalwart_listar_mensajes,
    correo_stalwart_leer_mensaje,
    correo_stalwart_enviar_mensaje,
    _datos_ntfy,
    notificaciones_enviar,
    videollamadas_crear_sala,
)
from .herramientas_soporte import (  # noqa: E402,F401
    leer_adjunto_chat,
    listar_tiquets,
    crear_tiquet,
    editar_tiquet,
    eliminar_tiquet,
    cambiar_estado_tiquet,
)
from .herramientas_fiscal import (  # noqa: E402,F401
    _tenant_id_actual,
    _tenant_actual,
    _guardar_adjunto_para_chat,
    _nombre_archivo_seguro,
    generar_documento_al_chat,
    listar_clientes_fiscales,
    crear_cliente_fiscal,
    listar_vencimientos_fiscales,
    generar_vencimientos_fiscales,
    marcar_presentado_vencimiento_fiscal,
    editar_vencimiento_fiscal,
    resumen_cliente_fiscal,
)
from .herramientas_despacho import (  # noqa: E402,F401
    _supervisor_actual,
    _campos,
    listar_clientes_despacho,
    resumen_cliente_despacho,
    listar_expedientes_despacho,
    resumen_expediente_despacho,
    listar_plazos_despacho,
    _exigir_alcance_documentos,
    listar_documentos_despacho,
    leer_documento_despacho,
    _CERT_CAMPOS, _exigir_certificados, _exigir_gestoria, comprobar_certificado, listar_certificados, riesgos_de_certificados, registrar_certificado, renovar_certificado, panel_fiscal, listar_traspasos, proponer_traspaso, resolver_traspaso, listar_avisos_fiscales, acusar_aviso_fiscal, listar_expedientes_control, ver_expediente_control, abrir_expediente_control, marcar_punto_expediente, cambiar_estado_expediente_control, comentar_expediente_control,
    listar_plantillas_correo,
    crear_tarea_recurrente,
    listar_tareas_recurrentes,
    _facturascripts_de_cliente,
    listar_facturas_cliente,
    crear_factura_cliente,
)
from .herramientas_verticales import (  # noqa: E402,F401
    _ctx, _consultas,
    abogados_provision_asunto, abogados_partes_asunto, abogados_agenda_vistas, abogados_comprobar_conflicto, inmobiliaria_listar_inmuebles, inmobiliaria_cruces_de_demanda, inmobiliaria_agenda_visitas, inmobiliaria_resumen,
    mensajes_de_enlace, responder_mensaje_de_enlace,
)
from .herramientas_contabilidad import (  # noqa: E402,F401
    _ctx_conta, _conta,
    contabilidad_listar_facturas, contabilidad_ver_factura, contabilidad_resumen, contabilidad_comprobar_exportacion, contabilidad_anotar_factura, contabilidad_cambiar_estado_factura, contabilidad_leer_factura_con_ia, contabilidad_exportar,
)
from .herramientas_comercial import (  # noqa: E402,F401
    _ctx_comercial, _traducir_comercial, _oportunidad_json,
    comercial_listar_oportunidades, comercial_ver_oportunidad, comercial_embudo, comercial_ver_reunion, comercial_crear_oportunidad, comercial_mover_oportunidad, comercial_anotar_actividad, comercial_crear_reunion, comercial_generar_acta,
    comercial_listar_etapas, comercial_editar_oportunidad, comercial_convertir_en_cliente, comercial_eliminar_oportunidad, comercial_listar_reuniones, comercial_editar_reunion, comercial_guardar_transcripcion, comercial_borrar_transcripcion, comercial_guardar_acta, comercial_crear_tareas_de_acta, comercial_eliminar_reunion,
)
from .herramientas_tareas_trabajo import (  # noqa: E402,F401
    _tt, _como_error, _tarea_visible, _direccion,
    cambiar_estado_tarea_con_motivo, listar_subtareas_tarea, crear_subtarea, listar_clientes_de_tarea, fijar_clientes_de_tarea, listar_tareas_de_cliente, listar_adjuntos_tarea, listar_revisiones_tarea, pedir_revision_tarea, resolver_revision_tarea, listar_conversaciones_cliente_tarea, responder_cliente_tarea, ocultar_comentario_cliente_tarea, listar_dependencias_tarea, anadir_dependencia_tarea, quitar_dependencia_tarea, informe_tareas, listar_reglas_automatizacion, simular_regla_automatizacion, listar_ejecuciones_automatizacion,
)
from .herramientas_fichaje import (  # noqa: E402,F401
    fichar,
    listar_mis_fichajes,
    _tenant_fichaje, _persona,
    listar_mis_ausencias,
    saldo_vacaciones,
    pedir_ausencia,
    cancelar_ausencia,
    listar_ausencias_equipo,
    resolver_ausencia,
    ver_mis_turnos,
    ver_cuadrante,
    asignar_turno,
    ver_bolsa_de_horas,
    ajustar_bolsa_de_horas,
)
from .herramientas_backoffice import (  # noqa: E402,F401
    _exigir_admin,
    backoffice_listar_tenants,
    backoffice_listar_usuarios,
    backoffice_crear_tenant,
    backoffice_renombrar_tenant,
    backoffice_guardar_datos_tenant,
    backoffice_alternar_herramienta_tenant,
    backoffice_crear_usuario,
    backoffice_asignar_tenant_usuario,
    backoffice_cambiar_rol,
    backoffice_asignar_gestor_fichajes,
)
from .herramientas_ampliadas import (  # noqa: E402,F401
    _mensaje_propio,
    mover_correo,
    destacar_correo,
    posponer_correo,
    listar_reglas_correo,
    crear_regla_correo,
    eliminar_regla_correo,
    listar_conversacion_correo,
    crear_tarea_desde_correo,
    guardar_nota_desde_correo,
    listar_proyectos,
    crear_proyecto,
    renombrar_proyecto,
    eliminar_proyecto,
    eliminar_nota,
    eliminar_tarea,
    fijar_nota,
    listar_tareas_hoy,
    listar_companeros,
    asignar_tarea,
    listar_checklist_tarea,
    agregar_item_checklist,
    alternar_item_checklist,
    cambiar_estado_tarea,
    listar_comentarios_tarea,
    comentar_tarea,
    iniciar_cronometro_tarea,
    consumo_ia,
    listar_comunicados,
    webhooks_entregas,
    resumen_del_dia,
    detalle_tarea,
    completar_tareas,
    listar_notificaciones,
)


TOOLS = [
    # Búsqueda semántica (RAG)
    buscar_semantico,
    # Notas
    listar_notas, crear_nota, editar_nota,
    # Tareas
    listar_tareas, crear_tarea, editar_tarea, completar_tarea, consultar_calendario,
    # Correo
    conectar_cuenta_correo,
    listar_cuentas_correo, sincronizar_correo, listar_carpetas_correo, listar_bandeja_entrada,
    leer_correo, marcar_leido_correo, eliminar_correo,
    listar_categorias_correo, crear_categoria_correo, eliminar_categoria_correo, asignar_categoria_correo,
    obtener_firma_correo, configurar_firma_correo,
    preparar_borrador_correo, enviar_borrador_correo,
    # Export/import
    exportar_historial, importar_historial, exportar_tareas, importar_tareas,
    # CRM
    crm_listar_leads, crm_crear_lead, crm_listar_contactos, crm_crear_contacto,
    crm_listar_cuentas, crm_crear_cuenta,
    # Drive
    drive_listar_archivos, drive_buscar_archivos, drive_subir_archivo, drive_descargar_archivo,
    # Proyectos
    proyectos_listar, proyectos_listar_tareas, proyectos_crear_tarea,
    # Soporte
    soporte_listar_conversaciones, soporte_leer_conversacion, soporte_responder_conversacion,
    # Analítica
    analitica_listar_preguntas, analitica_ejecutar_pregunta, analitica_listar_dashboards,
    # Automatizaciones
    automatizaciones_listar_flujos, automatizaciones_ejecutar_flujo,
    # Documentación
    documentacion_listar_colecciones, documentacion_buscar, documentacion_leer, documentacion_crear,
    # Chat
    chat_listar_salas, chat_enviar_mensaje,
    # Almacenamiento
    almacenamiento_listar_buckets, almacenamiento_listar_archivos, almacenamiento_url_descarga,
    # Monitorización
    monitorizacion_listar_estado,
    # Facturación
    facturas_listar_clientes, facturas_crear_cliente, facturas_listar_facturas, facturas_crear_factura,
    # Firmas
    firmas_listar_documentos, firmas_crear_documento, firmas_enviar_a_firma, firmas_descargar_firmado,
    # Documentos
    documentos_listar, documentos_subir, documentos_descargar,
    # Hojas
    hojas_listar_tablas, hojas_listar_filas, hojas_crear_fila,
    # Citas
    citas_listar_tipos_evento, citas_listar_reservas, citas_crear_reserva, citas_cancelar_reserva,
    # Webhooks
    webhooks_listar, webhooks_crear, webhooks_borrar, webhooks_entregas,
    # Newsletter
    newsletter_listar_suscriptores, newsletter_crear_suscriptor,
    newsletter_listar_campanas, newsletter_crear_campana, newsletter_enviar_campana,
    # Correo Stalwart
    correo_stalwart_listar_mensajes, correo_stalwart_leer_mensaje, correo_stalwart_enviar_mensaje,
    # Notificaciones (ntfy)
    notificaciones_enviar,
    # Videollamadas (Jitsi Meet)
    videollamadas_crear_sala,
    # Adjuntos del chat de IA
    leer_adjunto_chat,
    # Tiquets
    listar_tiquets, crear_tiquet, editar_tiquet, eliminar_tiquet, cambiar_estado_tiquet,
    # Calendario fiscal
    listar_clientes_fiscales, crear_cliente_fiscal, listar_vencimientos_fiscales, generar_vencimientos_fiscales,
    marcar_presentado_vencimiento_fiscal, editar_vencimiento_fiscal, resumen_cliente_fiscal,
    listar_plantillas_correo, crear_tarea_recurrente, listar_tareas_recurrentes,
    listar_facturas_cliente, crear_factura_cliente,
    # Núcleo del despacho (solo lectura)
    listar_clientes_despacho, resumen_cliente_despacho, listar_expedientes_despacho, resumen_expediente_despacho, listar_plazos_despacho,
    listar_documentos_despacho, leer_documento_despacho,
    listar_certificados, riesgos_de_certificados, registrar_certificado, renovar_certificado, comprobar_certificado, panel_fiscal, listar_traspasos, proponer_traspaso, resolver_traspaso, listar_avisos_fiscales, acusar_aviso_fiscal, listar_expedientes_control, ver_expediente_control, abrir_expediente_control, marcar_punto_expediente, cambiar_estado_expediente_control, comentar_expediente_control,
    # Gabinete de abogados e Inmobiliaria
    abogados_provision_asunto, abogados_partes_asunto, abogados_agenda_vistas, abogados_comprobar_conflicto, inmobiliaria_listar_inmuebles, inmobiliaria_cruces_de_demanda, inmobiliaria_agenda_visitas, inmobiliaria_resumen, mensajes_de_enlace, responder_mensaje_de_enlace,
    # Facturas para contabilizar
    contabilidad_listar_facturas, contabilidad_ver_factura, contabilidad_resumen, contabilidad_comprobar_exportacion, contabilidad_anotar_factura, contabilidad_cambiar_estado_factura, contabilidad_leer_factura_con_ia, contabilidad_exportar,
    # Trabajo con tareas: estado con motivo, subtareas, clientes, revisiones, informe y automatizaciones
    cambiar_estado_tarea_con_motivo, listar_subtareas_tarea, crear_subtarea, listar_clientes_de_tarea, fijar_clientes_de_tarea, listar_tareas_de_cliente, listar_adjuntos_tarea, listar_revisiones_tarea, pedir_revision_tarea, resolver_revision_tarea, listar_conversaciones_cliente_tarea, responder_cliente_tarea, ocultar_comentario_cliente_tarea, listar_dependencias_tarea, anadir_dependencia_tarea, quitar_dependencia_tarea, informe_tareas, listar_reglas_automatizacion, simular_regla_automatizacion, listar_ejecuciones_automatizacion,
    # Comercial: oportunidades, embudo y reuniones con acta de IA
    comercial_listar_oportunidades, comercial_ver_oportunidad, comercial_embudo, comercial_ver_reunion, comercial_crear_oportunidad, comercial_mover_oportunidad, comercial_anotar_actividad, comercial_crear_reunion, comercial_generar_acta,
    comercial_listar_etapas, comercial_editar_oportunidad, comercial_convertir_en_cliente, comercial_eliminar_oportunidad, comercial_listar_reuniones, comercial_editar_reunion, comercial_guardar_transcripcion, comercial_borrar_transcripcion, comercial_guardar_acta, comercial_crear_tareas_de_acta, comercial_eliminar_reunion,
    # Fichaje
    fichar, listar_mis_fichajes,
    listar_mis_ausencias, saldo_vacaciones, pedir_ausencia, cancelar_ausencia, listar_ausencias_equipo, resolver_ausencia, ver_mis_turnos, ver_cuadrante, asignar_turno, ver_bolsa_de_horas, ajustar_bolsa_de_horas,
    # Correo (acciones), proyectos, papelera y tareas ampliadas
    mover_correo, destacar_correo, posponer_correo, listar_reglas_correo, crear_regla_correo,
    eliminar_regla_correo, listar_conversacion_correo, crear_tarea_desde_correo, guardar_nota_desde_correo,
    resumen_del_dia, detalle_tarea, completar_tareas, listar_notificaciones,
    cambiar_estado_tarea, listar_comentarios_tarea, comentar_tarea, iniciar_cronometro_tarea,
    consumo_ia, listar_comunicados,
    listar_proyectos, crear_proyecto, renombrar_proyecto, eliminar_proyecto, eliminar_nota, eliminar_tarea,
    fijar_nota, listar_tareas_hoy, listar_companeros, asignar_tarea, listar_checklist_tarea,
    agregar_item_checklist, alternar_item_checklist,
    # Papelera
    listar_papelera, restaurar_de_papelera,
    # Estadísticas
    estadisticas_por_categoria, estadisticas_por_dia,
    # Backoffice
    backoffice_listar_tenants, backoffice_listar_usuarios, backoffice_crear_tenant,
    backoffice_renombrar_tenant, backoffice_guardar_datos_tenant, backoffice_alternar_herramienta_tenant,
    backoffice_crear_usuario, backoffice_asignar_tenant_usuario, backoffice_cambiar_rol,
    backoffice_asignar_gestor_fichajes,
]


def tools_filtradas(grupos: set[str] | None = None, solo_lectura: bool = False) -> list:
    """Herramientas a exponer. `grupos` (None = todos) limita por grupo (ver app/herramientas_grupos.py: nucleo,
    tareas_avanzadas, correo, fiscal, fichaje, tiquets, facturacion, crm, archivos, firmas, integraciones, backoffice, otros);
    `solo_lectura` deja únicamente las que consultan. El núcleo siempre se incluye si se filtra por grupos."""
    from app import herramientas_grupos as hg
    from app.ia_herramientas import LECTURA

    elegidas = []
    for tool in TOOLS:
        nombre = tool.__name__
        if grupos is not None and hg.grupo_de(nombre) not in grupos | {"nucleo"}:
            continue
        if solo_lectura and not hg.es_lectura(nombre, LECTURA):
            continue
        elegidas.append(tool)
    return elegidas


def _perfil_desde_entorno() -> tuple[set[str] | None, bool]:
    """`GUILDA_MCP_GRUPOS` (lista separada por comas; vacío = todos) y `GUILDA_MCP_SOLO_LECTURA=1`."""
    import os

    crudo = os.environ.get("GUILDA_MCP_GRUPOS", "").strip()
    grupos = {g.strip() for g in crudo.split(",") if g.strip()} or None
    return grupos, os.environ.get("GUILDA_MCP_SOLO_LECTURA") == "1"


def _anotaciones(nombre: str):
    """Anotaciones estándar de MCP: los clientes las usan para decidir qué piden confirmar. `readOnlyHint` = solo
    consulta; `destructiveHint` = borra o es irreversible/hacia terceros; `openWorldHint` = habla con el exterior."""
    import re

    from mcp.types import ToolAnnotations

    from app import herramientas_grupos as hg
    from app.ia_herramientas import LECTURA, SIEMPRE_CONFIRMAR

    lectura = hg.es_lectura(nombre, LECTURA)
    borra = bool(re.search(r"(^|_)(eliminar|borrar|cancelar)(_|$)", nombre))
    externo = nombre in SIEMPRE_CONFIRMAR or hg.grupo_de(nombre) in ("integraciones", "firmas", "crm", "facturacion", "archivos") or nombre.startswith(("newsletter_", "correo_stalwart_"))
    return ToolAnnotations(
        readOnlyHint=lectura,
        destructiveHint=False if lectura else (borra or nombre in SIEMPRE_CONFIRMAR),
        idempotentHint=lectura or nombre.startswith(("editar_", "fijar_", "marcar_", "completar_", "alternar_")),
        openWorldHint=bool(externo),
    )


def _resumen_argumentos(tool, args: tuple, kwargs: dict) -> dict:
    """La FORMA de los argumentos para la auditoría: números y booleanos tal cual (ids, flags), textos solo con su longitud y
    listas con su tamaño. Nunca el contenido de un texto libre (cuerpos de correo, notas...): es privacidad de los despachos."""
    import inspect

    try:
        ligados = inspect.signature(tool).bind_partial(*args, **kwargs).arguments
    except TypeError:
        return {}
    resumen = {}
    for nombre, valor in ligados.items():
        if isinstance(valor, bool) or isinstance(valor, (int, float)) or valor is None:
            resumen[nombre] = valor
        elif isinstance(valor, str):
            resumen[nombre] = f"texto({len(valor)})"
        elif isinstance(valor, (list, tuple, set, dict)):
            resumen[nombre] = f"{type(valor).__name__}({len(valor)})"
        else:
            resumen[nombre] = type(valor).__name__
    return resumen


def limites_mcp() -> tuple[int, int]:
    """(llamadas por minuto, escrituras por minuto) por persona en el MCP remoto. Configurable por entorno."""
    import os

    def entero(nombre, defecto):
        try:
            return max(1, int(os.environ.get(nombre, defecto)))
        except ValueError:
            return defecto

    return entero("GUILDA_MCP_LIMITE_POR_MINUTO", 120), entero("GUILDA_MCP_LIMITE_ESCRITURAS_POR_MINUTO", 40)


def _con_guardian(tool):
    """Envuelve una herramienta del MCP para que cada llamada quede **medida, limitada y auditada**:

    - respeta el alcance del token personal (áreas y solo lectura);
    - aplica un límite por persona (llamadas y, más bajo, escrituras por minuto) a las conexiones remotas;
    - anota cada llamada (quién, con qué cliente, qué herramienta, resultado, duración y la forma de los argumentos) en
      `mcp_auditoria` y en el uso diario, y suma al uso del token personal en `tokens_api_uso`.

    Sin token (stdio local, la propia máquina del usuario) no se limita, pero sí se anota. El registro nunca rompe la llamada."""
    import functools
    import inspect
    import time

    from app import mcp_utilidad as mu

    firma_original = inspect.signature(tool)
    firma_publica = mu.firma_con_tenant_opcional(firma_original)      # `tenant` obligatorio -> opcional (por defecto, tu despacho)

    @functools.wraps(tool)
    def instrumentada(*args, **kwargs):
        from app import auth, herramientas_grupos as hg, mcp_acceso
        from app.ia_herramientas import LECTURA

        token = get_access_token()
        remoto = token is not None
        cliente = token.client_id if remoto else "local"
        personal = remoto and cliente == "token-personal"
        token_id = mcp_acceso.token_de_scopes(token.scopes) if personal else None
        lectura = hg.es_lectura(tool.__name__, LECTURA)
        try:
            usuario_id = _uid()
        except Exception:  # noqa: BLE001
            usuario_id = None
        inicio = time.monotonic()

        def anotar(resultado: str, detalle: str | None = None) -> None:
            try:
                db.mcp_registrar_llamada(
                    usuario_id, cliente, token_id, tool.__name__, lectura, resultado, detalle,
                    _resumen_argumentos(tool, args, kwargs), int((time.monotonic() - inicio) * 1000),
                )
                if token_id:
                    db.registrar_uso_token(token_id, {"ok": 200, "denegado": 403, "limite": 429}.get(resultado, 500))
            except Exception:  # noqa: BLE001 -- auditar nunca debe romper la herramienta
                pass

        if personal:
            areas, solo_lectura = mcp_acceso.alcance_de_scopes(token.scopes)
            permitido, motivo = hg.herramienta_permitida(tool.__name__, areas, solo_lectura, LECTURA)
            if not permitido:
                anotar("denegado", motivo)
                raise ValueError(motivo)
        if remoto and usuario_id is not None:
            por_minuto, escrituras = limites_mcp()
            cupos = [(f"mcp:{usuario_id}", por_minuto)] + ([] if lectura else [(f"mcp-escritura:{usuario_id}", escrituras)])
            ok, espera = auth.consumir_cupos_nombrados(cupos)
            if not ok:
                anotar("limite", f"más de {por_minuto if lectura else escrituras} por minuto")
                raise ValueError(
                    f"Has superado el límite de llamadas al MCP ({por_minuto} por minuto, {escrituras} de escritura). "
                    f"Espera unos {espera} segundos antes de seguir."
                )
        from app import cifrado_despacho
        secreto = None
        if remoto:       # el secreto con el que se abre su concesión: el propio token personal, o el que Guilda metió en el token OAuth al consentir
            secreto = token.token if personal else next((x[3:] for x in (token.scopes or []) if x.startswith("cs:")), None)
        testigo = cifrado_despacho.fijar_concesion("mcp", secreto)
        try:
            if firma_publica is not None and not kwargs.get("tenant"):
                propio = db.tenant_de_usuario(usuario_id) if usuario_id else None
                if propio is None:
                    raise ValueError("Indica el nombre del despacho (`tenant`): tu usuario no tiene ninguno asignado.")
                kwargs["tenant"] = propio["nombre"]
            from app import estado_herramientas
            estado_herramientas.exigir_servicio(tool.__name__)          # ValueError claro si el servicio del que depende no responde
            resultado = mu.recortar_resultado(tool(*args, **kwargs))
        except Exception as e:  # noqa: BLE001
            anotar("error", f"{type(e).__name__}: {e}")
            raise
        finally:
            cifrado_despacho.restablecer_concesion(testigo)
        anotar("ok")
        return resultado

    instrumentada.__signature__ = firma_publica or firma_original
    if firma_publica is not None:
        instrumentada.__doc__ = (tool.__doc__ or "").rstrip() + mu.NOTA_TENANT
    return instrumentada


def _registrar_prompts_y_recursos(mcp: FastMCP, expuestas: dict) -> None:
    """Prompts (tareas habituales listas para usar) y recursos (datos que el cliente puede adjuntar sin llamar a una herramienta).
    Un recurso lee con la herramienta que lo produce, así que pasa por el mismo control de alcance, límites y auditoría; solo se registra
    si esa herramienta está expuesta en el perfil actual."""
    from mcp.server.fastmcp.prompts import Prompt
    from mcp.server.fastmcp.resources import FunctionResource

    from app import mcp_utilidad as mu

    for nombre, fn in mu.PROMPTS:
        mcp.add_prompt(Prompt.from_function(fn, name=nombre, description=(fn.__doc__ or "").strip()))
    for uri, nombre, descripcion, herramienta in mu.RECURSOS:
        if herramienta in expuestas:
            mcp.add_resource(FunctionResource(uri=uri, name=nombre, description=descripcion, mime_type="application/json", fn=_con_guardian(expuestas[herramienta])))


def registrar_tools(mcp: FastMCP, grupos: set[str] | None = None, solo_lectura: bool | None = None) -> None:
    """Registra las tools de TOOLS sobre una instancia de FastMCP — usado por mcp_server.py (stdio) y
    mcp_server_remoto.py (streamable-http) para exponer exactamente el mismo conjunto sin duplicar código.
    Sin argumentos se lee el perfil del entorno (por defecto: todas, como siempre). Cada tool lleva sus anotaciones
    MCP (solo lectura, destructiva, idempotente, mundo abierto) y un guardián del alcance del token personal."""
    if grupos is None and solo_lectura is None:
        grupos, solo_lectura = _perfil_desde_entorno()
    expuestas = tools_filtradas(grupos, bool(solo_lectura))
    for tool in expuestas:
        mcp.add_tool(_con_guardian(tool), annotations=_anotaciones(tool.__name__))
    _registrar_prompts_y_recursos(mcp, {t.__name__: t for t in expuestas})
