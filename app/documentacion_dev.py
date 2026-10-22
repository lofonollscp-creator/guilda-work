"""Contenido de la Guía para desarrolladores (`/docs`, ver
`app/rutas_docs.py`), la documentación técnica pública para quien quiera
integrar su propio software con una instancia de Guilda Work — por API
REST o conectando un asistente de IA por MCP — o desplegar/extender el
propio proyecto.

Es contenido, no HTML: cada página es una lista de "bloques" (`badges`,
`p`, `h2`, `callout`, `code`, `steps`, `table`, `cards`) que
`app/templates/docs/pagina.html` renderiza de forma genérica — así
añadir o reordenar contenido no toca la plantilla ni el CSS. La única
excepción es una página con `"interactivo": True` (hoy solo
`explorador-api`): en vez de bloques, `app/rutas_docs.py` la renderiza
con `docs/explorador_api.html`, una plantilla aparte cuyo contenido lo
genera `app/static/api_explorer.js` en el cliente a partir del OpenAPI
real (`/api/v1/openapi.json`).

Refundido a partir de README.md y HOSTING.md (secciones 8.9, 8.13,
10 y "Migrar a un dominio propio" sobre todo) — no un resumen aparte
que se pueda desincronizar en silencio: si cambias el comportamiento
real descrito en esos `.md`, actualiza también el bloque
correspondiente aquí.

Todo lo que aparece aquí describe comportamiento real de la app en este
mismo commit (endpoints de `app/rutas_api.py`, tools de `mcp_tools.py`,
servidores de `mcp_server.py`/`mcp_server_remoto.py`) — si cambias uno
de esos archivos y la cifra/ruta ya no cuadra, actualiza también esta
página; no hay generación automática todavía.
"""
import inspect
import re

import mcp_tools as _mt

# --- Cifras derivadas en vivo del propio catálogo de tools, para que no se
# desincronicen de mcp_tools.py como pasó antes con README.md ---
_PREFIJOS_TENANT = (
    "facturas_", "firmas_", "documentos_", "hojas_",
    "citas_", "newsletter_", "correo_stalwart_", "notificaciones_",
    "videollamadas_",
)
_PROPIAS_GUILDA_WORK = {
    "listar_notas", "crear_nota", "editar_nota",
    "listar_tareas", "crear_tarea", "editar_tarea", "completar_tarea", "consultar_calendario",
    "listar_cuentas_correo", "conectar_cuenta_correo", "sincronizar_correo", "listar_carpetas_correo",
    "listar_bandeja_entrada",
    "leer_correo", "marcar_leido_correo", "eliminar_correo",
    "listar_categorias_correo", "crear_categoria_correo", "eliminar_categoria_correo", "asignar_categoria_correo",
    "obtener_firma_correo", "configurar_firma_correo",
    "preparar_borrador_correo", "enviar_borrador_correo",
    "exportar_historial", "importar_historial", "exportar_tareas", "importar_tareas",
    "buscar_semantico", "listar_papelera", "restaurar_de_papelera",
    "estadisticas_por_categoria", "estadisticas_por_dia",
    "webhooks_listar", "webhooks_crear", "webhooks_borrar",
    "listar_tiquets", "crear_tiquet", "editar_tiquet", "eliminar_tiquet", "cambiar_estado_tiquet",
    "abogados_provision_asunto", "abogados_partes_asunto", "abogados_agenda_vistas", "abogados_comprobar_conflicto", "inmobiliaria_listar_inmuebles", "inmobiliaria_cruces_de_demanda", "inmobiliaria_agenda_visitas", "inmobiliaria_resumen", "mensajes_de_enlace", "responder_mensaje_de_enlace", "comprobar_certificado",
    "fichar", "listar_mis_fichajes", "listar_mis_ausencias", "saldo_vacaciones", "pedir_ausencia", "cancelar_ausencia", "listar_ausencias_equipo", "resolver_ausencia", "ver_mis_turnos", "ver_cuadrante", "asignar_turno", "ver_bolsa_de_horas", "ajustar_bolsa_de_horas",
    "backoffice_listar_tenants", "backoffice_listar_usuarios", "backoffice_crear_tenant",
    "backoffice_renombrar_tenant", "backoffice_guardar_datos_tenant", "backoffice_alternar_herramienta_tenant",
    "backoffice_crear_usuario", "backoffice_asignar_tenant_usuario", "backoffice_cambiar_rol",
    "backoffice_asignar_gestor_fichajes",
    "leer_adjunto_chat",
    "listar_clientes_fiscales", "crear_cliente_fiscal",
    "listar_vencimientos_fiscales", "generar_vencimientos_fiscales",
    "marcar_presentado_vencimiento_fiscal", "editar_vencimiento_fiscal", "resumen_cliente_fiscal",
    "listar_plantillas_correo", "crear_tarea_recurrente", "listar_tareas_recurrentes",
    "listar_certificados", "riesgos_de_certificados", "registrar_certificado", "renovar_certificado", "panel_fiscal", "listar_traspasos", "proponer_traspaso", "resolver_traspaso", "listar_clientes_despacho", "resumen_cliente_despacho", "listar_expedientes_despacho", "resumen_expediente_despacho", "listar_plazos_despacho",
    "listar_documentos_despacho", "leer_documento_despacho",
    "listar_facturas_cliente", "crear_factura_cliente",
    "cambiar_estado_tarea_con_motivo", "listar_subtareas_tarea", "crear_subtarea", "listar_clientes_de_tarea", "fijar_clientes_de_tarea", "listar_tareas_de_cliente", "listar_adjuntos_tarea", "listar_revisiones_tarea", "pedir_revision_tarea", "resolver_revision_tarea", "listar_conversaciones_cliente_tarea", "responder_cliente_tarea", "ocultar_comentario_cliente_tarea", "listar_dependencias_tarea", "anadir_dependencia_tarea", "quitar_dependencia_tarea", "comercial_listar_oportunidades", "comercial_ver_oportunidad", "comercial_embudo", "comercial_ver_reunion", "comercial_crear_oportunidad", "comercial_mover_oportunidad", "comercial_anotar_actividad", "comercial_crear_reunion", "comercial_generar_acta", "informe_tareas", "listar_reglas_automatizacion", "simular_regla_automatizacion", "listar_ejecuciones_automatizacion",
    "contabilidad_listar_facturas", "contabilidad_ver_factura", "contabilidad_resumen", "contabilidad_comprobar_exportacion", "contabilidad_anotar_factura", "contabilidad_cambiar_estado_factura", "contabilidad_leer_factura_con_ia", "contabilidad_exportar",
    "mover_correo", "destacar_correo", "posponer_correo", "listar_reglas_correo", "crear_regla_correo",
    "eliminar_regla_correo", "listar_conversacion_correo", "crear_tarea_desde_correo", "guardar_nota_desde_correo",
    "listar_proyectos", "crear_proyecto", "renombrar_proyecto", "eliminar_proyecto", "eliminar_nota",
    "eliminar_tarea", "fijar_nota", "listar_tareas_hoy", "listar_companeros", "asignar_tarea",
    "listar_checklist_tarea", "agregar_item_checklist", "alternar_item_checklist",
    "resumen_del_dia", "detalle_tarea", "completar_tareas", "listar_notificaciones",
    "cambiar_estado_tarea", "listar_comentarios_tarea", "comentar_tarea", "iniciar_cronometro_tarea",
    "consumo_ia", "listar_comunicados", "webhooks_entregas",
}

TOTAL_TOOLS = len(_mt.TOOLS)
TOOLS_TENANT = sum(1 for t in _mt.TOOLS if t.__name__.startswith(_PREFIJOS_TENANT))
TOOLS_PROPIAS = sum(1 for t in _mt.TOOLS if t.__name__ in _PROPIAS_GUILDA_WORK)
TOOLS_STACK_COMPARTIDO = TOTAL_TOOLS - TOOLS_TENANT - TOOLS_PROPIAS
NUM_FAMILIAS_TENANT = len(_PREFIJOS_TENANT)


def _familias_tenant() -> list[tuple[str, str, int]]:
    prefijos = [
        ("facturas_", "FacturaScripts", "Facturación"),
        ("firmas_", "Documenso", "Firma electrónica"),
        ("documentos_", "Paperless-ngx", "Gestión documental"),
        ("hojas_", "Baserow", "Hojas de cálculo"),
        ("citas_", "Cal.diy", "Reserva de citas"),
        ("newsletter_", "Listmonk", "Newsletter"),
        ("correo_stalwart_", "Stalwart", "Correo propio"),
        ("notificaciones_", "ntfy", "Notificaciones push"),
        ("videollamadas_", "Jitsi Meet", "Videollamadas"),
    ]
    salida = []
    for prefijo, backend, etiqueta in prefijos:
        n = sum(1 for t in _mt.TOOLS if t.__name__.startswith(prefijo))
        salida.append((etiqueta, backend, n))
    return salida


# --- Grupos del catálogo completo de tools (para la página de referencia
# "Catálogo completo de tools (MCP)") — el stack compartido no tenía hasta
# ahora una lista real, solo un recuento, lo que dejaba a quien integra sin
# saber los nombres/parámetros exactos que puede llamar.
_GRUPOS_STACK_COMPARTIDO = [
    ("crm_", "CRM (EspoCRM)"),
    ("drive_", "Drive (Nextcloud)"),
    ("proyectos_", "OpenProject (gestión de proyectos de equipo)"),
    ("soporte_", "Soporte (Chatwoot)"),
    ("analitica_", "Analítica (Metabase)"),
    ("automatizaciones_", "Automatizaciones (n8n)"),
    ("documentacion_", "Documentación (Outline)"),
    ("chat_", "Chat (Synapse/Matrix)"),
    ("almacenamiento_", "Almacenamiento (MinIO)"),
    ("monitorizacion_", "Monitorización (Uptime Kuma)"),
]

_GRUPOS_TENANT = [
    ("facturas_", "Facturación (FacturaScripts)"),
    ("firmas_", "Firma electrónica (Documenso)"),
    ("documentos_", "Gestión documental (Paperless-ngx)"),
    ("hojas_", "Hojas de cálculo (Baserow)"),
    ("citas_", "Reserva de citas (Cal.diy)"),
    ("newsletter_", "Newsletter (Listmonk)"),
    ("correo_stalwart_", "Correo propio (Stalwart)"),
    ("notificaciones_", "Notificaciones push (ntfy)"),
    ("videollamadas_", "Videollamadas (Jitsi Meet)"),
]


def _firma_tool(t) -> str:
    """Firma legible de una tool con sus tipos — construida a partir de
    inspect.signature() en vez de escrita a mano, para que nunca se
    desincronice del código real de mcp_tools.py."""
    partes = []
    for nombre, p in inspect.signature(t).parameters.items():
        texto = nombre
        if p.annotation is not inspect.Parameter.empty:
            anotacion = p.annotation if isinstance(p.annotation, str) else getattr(p.annotation, "__name__", str(p.annotation))
            texto += f": {anotacion}"
        if p.default is not inspect.Parameter.empty:
            texto += f" = {p.default!r}"
        partes.append(texto)
    return "(" + ", ".join(partes) + ")"


def _filas_tools_por_nombre(nombres: set) -> list[list[str]]:
    filas = []
    for t in _mt.TOOLS:
        if t.__name__ not in nombres:
            continue
        descripcion = (t.__doc__ or "").strip().splitlines()[0] if t.__doc__ else ""
        filas.append([f"<code>{t.__name__}{_firma_tool(t)}</code>", descripcion])
    return filas


def _filas_tools_por_prefijo(prefijo: str) -> list[list[str]]:
    filas = []
    for t in _mt.TOOLS:
        if not t.__name__.startswith(prefijo):
            continue
        descripcion = (t.__doc__ or "").strip().splitlines()[0] if t.__doc__ else ""
        filas.append([f"<code>{t.__name__}{_firma_tool(t)}</code>", descripcion])
    return filas


# --- Páginas -----------------------------------------------------------------

def _bloques_cambios() -> list[dict]:
    """Bloques de la página «Registro de cambios», generados de `api_versiones.HISTORIAL` (con `código` entre acentos graves)."""
    from . import api_versiones

    def _html(texto: str) -> str:
        return re.sub(r"`([^`]+)`", r"<code>\1</code>", texto.replace("&", "&amp;").replace("<", "&lt;"))

    bloques: list[dict] = [{"type": "p", "html":
        "La cabecera <code>X-API-Version</code> lleva <code>mayor.menor</code>: el <b>menor</b> sube con cada ampliación compatible (campos y rutas "
        "nuevos, siempre opcionales) y el <b>mayor</b> solo si algo se rompe. Programa contra <code>codigo</code> en los errores, no contra su texto. "
        f"Versión actual: <b>{api_versiones.HISTORIAL[0][0]}</b>."}]
    for version, fecha, cambios in api_versiones.HISTORIAL:
        titulo = f"{version} — {fecha}" if version else f"Antes de la cabecera de versión — {fecha}"
        bloques.append({"type": "h2", "id": "v" + (version or fecha).replace(".", "-"), "text": titulo})
        bloques.append({"type": "table", "headers": ["Tipo", "Cambio"], "rows": [[tipo, _html(texto)] for tipo, texto in cambios]})
    return bloques


PAGINAS = [
    {
        "slug": "",
        "grupo": None,
        "titulo": "Guía para desarrolladores",
        "descripcion": "Integra tu propio software con una instancia de Guilda Work por API REST, "
                        "conecta un asistente de IA por MCP, o despliega/extiende el propio proyecto.",
        "bloques": [
            {"type": "badges", "items": [
                "REST / JSON", "Autenticación Bearer", "Búsqueda semántica (RAG)", "Webhooks HMAC", "MCP · stdio + OAuth 2.1",
            ]},
            {"type": "h2", "id": "empezar", "text": "Empezar"},
            {"type": "cards", "items": [
                ("Autenticación", "Consigue un token de API y autentica tus peticiones.", "autenticacion"),
                ("Primera llamada a la API", "Crea tu primera nota vía la API REST.", "primera-llamada"),
            ]},
            {"type": "h2", "id": "opciones", "text": "Opciones de integración"},
            {"type": "cards", "items": [
                ("Referencia de la API", "Todos los endpoints REST, agrupados por recurso — o el explorador interactivo generado desde el OpenAPI real.", "referencia-api"),
                ("Modelos de datos", "La forma exacta de cada objeto: campos, tipos y notas.", "modelos-de-datos"),
                ("Ejemplos", "Recetas completas: curl, Python y JavaScript.", "ejemplos"),
                ("Webhooks", "Recibe notificaciones en tiempo real de eventos en tu cuenta, firmadas con HMAC.", "webhooks"),
                ("Asistente de IA (MCP)", "Conecta Claude Code, Claude Desktop, Codex CLI o ChatGPT directamente contra tu instancia.", "asistente-ia"),
                ("Catálogo completo de tools (MCP)", "Las tools una por una: nombre, parámetros y descripción.", "catalogo-tools-mcp"),
                ("Aislamiento multi-cliente", "Cómo se garantiza que los datos de un tenant nunca los vea otro.", "aislamiento-multicliente"),
            ]},
            {"type": "h2", "id": "configuracion-despliegue", "text": "Configuración y despliegue"},
            {"type": "cards", "items": [
                ("Variables de entorno", "Qué variable activa cada pieza — app, MCP remoto, herramientas conectadas.", "variables-de-entorno"),
                ("Desarrollo local", "Clona el proyecto y levanta tu propio entorno de pruebas.", "desarrollo-local"),
                ("Autoalojamiento", "Despliega tu propia instancia en un VPS con Docker + Caddy.", "autoalojamiento"),
            ]},
            {"type": "callout", "kind": "info", "html":
                "Guilda Work es <b>autoalojado</b>: cada integración habla con <i>tu</i> instancia, no con un "
                "servicio central de terceros. Todas las URLs de esta guía son relativas a tu propio dominio "
                "(<code>https://tu-hostname</code>)."},
        ],
    },
    {
        "slug": "autenticacion",
        "grupo": "EMPEZAR",
        "titulo": "Autenticación",
        "descripcion": "Consigue un token de API y autentica tus peticiones.",
        "bloques": [
            {"type": "p", "html":
                "La API REST (<code>/api/v1/*</code>) usa autenticación por <b>token opaco</b> vía cabecera "
                "<code>Authorization: Bearer &lt;token&gt;</code> — independiente de la cookie de sesión que usa "
                "la propia app web, nunca se mezclan en la misma ruta. El token se obtiene registrando una cuenta "
                "nueva o iniciando sesión en una existente."},
            {"type": "callout", "kind": "info", "html":
                "Por debajo, la contraseña la custodia <b>Ory Kratos</b> (el proveedor de identidad de la "
                "instancia) — esta API nunca ve ni guarda la contraseña en texto plano, solo emite un token "
                "opaco propio tras validar contra Kratos."},
            {"type": "h2", "id": "registro", "text": "Registrar una cuenta nueva"},
            {"type": "code", "lang": "bash", "code":
                'curl -X POST https://tu-hostname/api/v1/auth/registro \\\n'
                '  -H "Content-Type: application/json" \\\n'
                '  -d \'{\n'
                '    "email": "dev@tuempresa.com",\n'
                '    "contrasena": "una-contrasena-de-8-caracteres-o-mas",\n'
                '    "nombre_dispositivo": "Mi integración"\n'
                "  }'"},
            {"type": "code", "lang": "json", "code":
                '{\n'
                '  "ok": true,\n'
                '  "data": {\n'
                '    "token": "kf83h2n...",\n'
                '    "usuario": { "id": 42, "email": "dev@tuempresa.com" }\n'
                "  }\n"
                "}"},
            {"type": "h2", "id": "login", "text": "Iniciar sesión con una cuenta existente"},
            {"type": "code", "lang": "bash", "code":
                'curl -X POST https://tu-hostname/api/v1/auth/login \\\n'
                '  -H "Content-Type: application/json" \\\n'
                '  -d \'{"email": "dev@tuempresa.com", "contrasena": "..."}\''},
            {"type": "p", "html":
                "Cada llamada a <code>/auth/registro</code> o <code>/auth/login</code> emite un token nuevo — "
                "puedes tener varios tokens activos a la vez (uno por dispositivo/integración), y revocar uno "
                "concreto sin afectar a los demás con <code>POST /api/v1/auth/logout</code> (revoca el token que "
                "viaja en la propia petición)."},
            {"type": "h2", "id": "usar-el-token", "text": "Usar el token"},
            {"type": "code", "lang": "bash", "code":
                'curl https://tu-hostname/api/v1/auth/me \\\n'
                '  -H "Authorization: Bearer kf83h2n..."'},
            {"type": "h2", "id": "errores", "text": "Errores de autenticación"},
            {"type": "table", "headers": ["HTTP", "Cuándo"], "rows": [
                ["400", "Email inválido, contraseña de menos de 8 caracteres, o campos obligatorios ausentes."],
                ["401", "Token ausente, revocado o incorrecto — <code>/auth/login</code> con credenciales erróneas también devuelve 401."],
                ["409", "<code>/auth/registro</code> con un email que ya tiene cuenta."],
                ["429", "Límite de intentos superado (ver aviso de abajo)."],
            ]},
            {"type": "callout", "kind": "warn", "html":
                "Los endpoints de <code>/auth/registro</code> y <code>/auth/login</code> están limitados a "
                "<b>10 peticiones por minuto</b> por IP (protección de fuerza bruta) — si automatizas la creación "
                "de cuentas, ten en cuenta ese límite."},
            {"type": "h2", "id": "tokens-solo-lectura", "text": "Tokens de solo lectura, por áreas y con caducidad"},
            {"type": "p", "html":
                "Para una integración que solo debe consultar (un panel, un informe), crea un token con "
                "<code>permisos: \"solo_lectura\"</code>: puede hacer <code>GET</code> pero cualquier otro método "
                "responde <b>403</b> <code>Este token es de solo lectura.</code>. Se crea desde "
                "<b>Mis dispositivos</b> en la web o con <code>POST /tokens</code> "
                "(<code>{\"nombre\": \"...\", \"permisos\": \"completo|solo_lectura\"}</code>); el token en claro "
                "solo se devuelve en ese momento. <code>GET /tokens</code> los lista (con <code>areas</code>, "
                "<code>caduca_en</code>, <code>ultimo_uso_en</code>, <code>ultima_ip</code> y <code>llamadas_30d</code>), "
                "<code>GET /tokens/{id}/uso</code> da las llamadas y errores por día y "
                "<code>DELETE /tokens/{id}</code> revoca uno."},
            {"type": "p", "html":
                "<b>Principio de mínimo privilegio.</b> Al crear un token puedes limitarlo a <b>áreas</b> con "
                "<code>areas</code> (<code>notas</code>, <code>tareas</code>, <code>correo</code>, <code>fiscal</code>, "
                "<code>fichaje</code>, <code>tiquets</code>, <code>ia</code>, <code>avisos</code>): fuera de ellas responde "
                "<b>403</b> con <code>codigo: \"token_area_no_permitida\"</code>. Un token con áreas no puede usar las rutas "
                "transversales (<code>/historial</code>, <code>/dashboard</code>, <code>/export</code>, <code>/papelera</code>, "
                "<code>/buscar</code>, <code>/sync</code>, que mezclan datos de varias áreas) ni gestionar tokens (no puede "
                "crear uno más amplio). Siempre puede leer <code>/auth/me</code>, el perfil y <code>/openapi.json</code>. "
                "Con <code>caduca_dias</code> (1-3650) o <code>caduca_en</code> el token caduca solo "
                "(<b>401</b>, <code>token_caducado</code>); sin caducidad se desconecta tras 90 días sin uso. "
                "Combina con <code>permisos: \"solo_lectura\"</code>: p. ej. un panel que solo lee el calendario fiscal."},
            {"type": "h2", "id": "paginacion", "text": "Paginación opcional"},
            {"type": "p", "html":
                "Los listados de historial, tareas, tiques, clientes y vencimientos fiscales y mensajes de correo "
                "aceptan <code>limit</code> (1–1000) y <code>offset</code>. Sin ellos devuelven todo, como siempre. "
                "La cabecera <code>X-Total-Count</code> lleva el total sin paginar."},
        ],
    },
    {
        "slug": "primera-llamada",
        "grupo": "EMPEZAR",
        "titulo": "Primera llamada a la API",
        "descripcion": "Crea tu primera nota vía la API REST.",
        "bloques": [
            {"type": "p", "html":
                "Todas las respuestas siguen el mismo sobre uniforme: <code>{\"ok\": true, \"data\": ...}</code> "
                "en éxito, <code>{\"ok\": false, \"error\": \"...\"}</code> en fallo — incluidos los errores HTTP "
                "estándar (404, 405...), que nunca devuelven HTML."},
            {"type": "steps", "items": [
                ("Consigue un token", "Sigue la página de <a href=\"/docs/autenticacion\">Autenticación</a> para registrarte o iniciar sesión."),
                ("Crea un proyecto (categoría)", "Las notas y tareas viven dentro de un proyecto — necesitas uno antes de crear nada."),
                ("Crea la nota", "Con el <code>id</code> del proyecto, ya puedes anotar algo."),
            ]},
            {"type": "code", "lang": "bash", "code":
                'TOKEN="kf83h2n..."\n\n'
                '# 1. Crea un proyecto\n'
                'curl -X POST https://tu-hostname/api/v1/categorias \\\n'
                '  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\\n'
                "  -d '{\"nombre\": \"Cliente Alfa\"}'\n"
                "# -> {\"ok\":true,\"data\":{\"id\":7,\"nombre\":\"Cliente Alfa\", ...}}\n\n"
                '# 2. Crea la nota en ese proyecto\n'
                'curl -X POST https://tu-hostname/api/v1/notas \\\n'
                '  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\\n'
                "  -d '{\"texto\": \"Primera nota desde la API\", \"categoria_id\": 7}'\n"
                "# -> {\"ok\":true,\"data\":{\"id\":123,\"texto\":\"Primera nota desde la API\",\n"
                '#      "creada_en":"2026-08-01T10:15:03", "categoria_id":7, ...}}'},
            {"type": "p", "html":
                "La nota queda con fecha y hora exactas de creación (<code>creada_en</code>, ISO 8601, hora local "
                "del servidor) — el mismo campo que usa el resto de la app para el registro cronológico."},
            {"type": "h2", "id": "siguiente-paso", "text": "Siguiente paso"},
            {"type": "cards", "items": [
                ("Referencia de la API", "Tareas con duración, correo, exportación y el resto de recursos.", "referencia-api"),
                ("Ejemplos", "Scripts completos en Python y JavaScript, no solo curl suelto.", "ejemplos"),
            ]},
        ],
    },
    {
        "slug": "referencia-api",
        "grupo": "INTEGRACIÓN",
        "titulo": "Referencia de la API",
        "descripcion": "Todos los endpoints REST, agrupados por recurso.",
        "bloques": [
            {"type": "h2", "id": "base-url", "text": "URL base y formato"},
            {"type": "code", "lang": "text", "code": "https://tu-hostname/api/v1"},
            {"type": "p", "html":
                "Todos los endpoints de esta página, salvo <code>/auth/registro</code> y <code>/auth/login</code>, "
                "requieren la cabecera <code>Authorization: Bearer &lt;token&gt;</code> (ver "
                "<a href=\"/docs/autenticacion\">Autenticación</a>) y actúan siempre sobre los datos del usuario "
                "dueño del token — nunca hace falta (ni es posible) pasar un <code>usuario_id</code> a mano. "
                "Las peticiones con cuerpo van en JSON (<code>Content-Type: application/json</code>); la "
                "respuesta siempre es JSON, con el sobre <code>{\"ok\", \"data\"|\"error\"}</code> descrito en "
                "<a href=\"/docs/primera-llamada\">Primera llamada a la API</a>. Para el detalle de los campos de "
                "cada objeto (<code>Nota</code>, <code>Tarea</code>, <code>Categoria</code>...) ver "
                "<a href=\"/docs/modelos-de-datos\">Modelos de datos</a>."},
            {"type": "callout", "kind": "info", "html":
                "¿Vas a importar esta API en Postman, Insomnia, o generar un cliente automáticamente? "
                "<code>GET /api/v1/openapi.json</code> devuelve el documento OpenAPI 3.0 completo de todos estos "
                "endpoints — generado por introspección del propio código en cada petición (no un archivo aparte "
                "que se pueda desincronizar), sin necesitar token: es documentación pública. Las tablas de esta "
                "página son la referencia legible; ese JSON es la máquina-legible."},
            {"type": "cards", "items": [
                ("Abrir explorador interactivo", "Endpoints filtrables por texto, con parámetros, cuerpo esperado y un curl de ejemplo ya generado.", "explorador-api"),
            ]},
            {"type": "h2", "id": "meta", "text": "Meta"},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["GET", "/api/v1/openapi.json", "Documento OpenAPI 3.0 completo (cuerpos, parámetros, respuestas, códigos de error y ejemplos de cada operación), generado a partir del código. Sin token."],
            ]},
            {"type": "h2", "id": "errores", "text": "Manejo de errores"},
            {"type": "p", "html":
                "El sobre de error es siempre el mismo, en cualquier endpoint de esta API — incluidos los "
                "errores que genera Flask antes de llegar a la vista (404 de ruta inexistente, 405 de método no "
                "permitido): <code>{\"ok\": false, \"error\": \"mensaje legible\", \"codigo\": \"no_encontrado\"}</code>, nunca una "
                "página HTML. <b>Programa contra <code>codigo</code></b> (estable), no contra el texto, que puede cambiar o "
                "traducirse. Códigos: <code>peticion_invalida</code>, <code>token_invalido</code>, <code>token_solo_lectura</code>, <code>token_caducado</code>, <code>token_area_no_permitida</code>, <code>referencia_duplicada</code>, <code>referencia_invalida</code>, <code>valor_invalido</code>, <code>url_invalida</code>, "
                "<code>prohibido</code>, <code>no_encontrado</code>, <code>metodo_no_permitido</code>, <code>conflicto</code>, "
                "<code>idempotencia_conflicto</code>, <code>idempotencia_en_curso</code>, <code>limite_excedido</code> y "
                "<code>error_interno</code>. Algunos errores de validación añaden <code>campo</code>."},
            {"type": "h2", "id": "contrato-openapi", "text": "El contrato OpenAPI"},
            {"type": "p", "html":
                "<code>/api/v1/openapi.json</code> describe <b>todas las operaciones</b>: cuerpo de la petición (JSON o multipart, con sus campos "
                "obligatorios), parámetros de consulta, cabeceras, cada código de respuesta con su esquema, los errores con su "
                "<code>codigo</code>, el área de token que exige cada ruta (<code>x-area</code>) y ejemplos de las operaciones principales. "
                "Se genera <b>del propio código</b> de la API (las columnas de las tablas dan los esquemas de las entidades), así que no puede "
                "quedar desactualizado. Impórtalo en Postman o Insomnia, o genera un cliente con "
                "<code>openapi-generator</code> / <code>openapi-python-client</code> / <code>openapi-typescript</code>."},
            {"type": "p", "html":
                "<b>Garantías de compatibilidad.</b> Una batería de pruebas comprueba en cada cambio que el documento es válido, que lo que devuelve "
                "la API cumple su esquema y que <b>no desaparece nada ya publicado</b>: ni una ruta, ni un campo del cuerpo, ni un parámetro, "
                "ni un código de éxito, ni se vuelve obligatorio un campo que antes no lo era. Lo que se añade es siempre opcional."},
            {"type": "callout", "kind": "info", "html":
                "<b>Particularidad conocida:</b> <code>modelos_fiscales</code> de un cliente fiscal llega como <b>texto JSON</b> "
                "(<code>\"[\\\"303\\\"]\"</code>) en los listados y las escrituras, y como <b>lista</b> solo en "
                "<code>GET /fiscal/clientes/{id}</code>. Al enviarlo, siempre es una lista. El contrato lo documenta así tal cual."},
            {"type": "h2", "id": "uso-externo", "text": "Uso desde integraciones externas"},
            {"type": "table", "headers": ["Mecanismo", "Cómo funciona"], "rows": [
                ["Versión", "Cada respuesta lleva <code>X-API-Version</code> (<code>1.x</code>). El número menor sube con cada ampliación compatible; el mayor solo si algo se rompe. Los campos nuevos siempre son opcionales."],
                ["Límite", "Por usuario (todos sus tokens suman): <b>600 peticiones/minuto</b>, de ellas <b>200 escrituras</b> (POST/PUT/PATCH/DELETE) y <b>20 operaciones pesadas</b> (llamadas a la IA, exportaciones, importaciones, sincronizar un buzón, enviar correo). Cada respuesta lleva <code>X-RateLimit-Limit</code>, <code>X-RateLimit-Remaining</code> y <code>X-RateLimit-Reset</code> (segundos) del cupo más ajustado, y <code>X-RateLimit-Scope</code> (<code>total</code>, <code>escritura</code> o <code>pesada</code>). Al pasarte: <code>429</code> con <code>Retry-After</code> y el cupo en <code>cupo</code>. Una petición rechazada no gasta cupo."],
                ["IP permitidas", "Al crear un token puedes indicar <code>ips_permitidas</code> (IP o redes CIDR, hasta 20). Desde otra dirección responde <code>403</code> con <code>codigo: ip_no_permitida</code>. Un token con IPs <b>no sirve por MCP</b> (allí no se conoce la dirección del cliente)."],
                ["CORS (navegador)", "Por defecto la API no permite llamadas desde páginas web. Con <code>origenes_cors</code> (orígenes exactos como <code>https://panel.ejemplo.com</code>, hasta 10, sin comodines) el token puede usarse desde esas páginas: la respuesta devuelve <code>Access-Control-Allow-Origin</code> con ese origen. El preflight (<code>OPTIONS</code>) solo se concede a orígenes que algún token vivo admite. Evita poner un token en el código de una web pública: úsalo desde un servidor siempre que puedas."],
                ["Verificación en dos pasos", "Cada persona puede activarla en la web (Ajustes → Contraseña y email: app de autenticación y 12 códigos de recuperación de un solo uso). Entonces <code>POST /auth/login</code> con email y contraseña responde <code>401</code> con <code>codigo: requiere_2fa</code>; hay que repetir la llamada añadiendo <code>codigo_2fa</code> (6 dígitos de la app o un código de recuperación). Con un código incorrecto: <code>401 credenciales_o_codigo_incorrectos</code>. Las cuentas sin 2FA no cambian. Los tokens de API ya emitidos siguen valiendo hasta que caduquen o se revoquen."],
                ["Estado del servicio", "<code>GET /api/v1/health</code> (sin token) devuelve <code>200</code> con <code>{\"estado\": \"ok\"}</code> si el servicio atiende y la base de datos responde, y <code>503</code> si no. Pensado para Uptime Kuma o un balanceador."],
                ["Idempotencia", "En cualquier <code>POST</code> añade <code>Idempotency-Key: &lt;cadena única&gt;</code>: si reintentas la misma petición (corte de red) devuelve la respuesta original con <code>Idempotent-Replay: true</code> en vez de crear un duplicado. La misma clave con otro cuerpo da <code>422</code>. Vale 24 h; los errores 5xx no se guardan."],
                ["Caché", "Las lecturas <code>GET</code> llevan <code>ETag</code>; reenvíalo en <code>If-None-Match</code> y recibirás <code>304</code> sin cuerpo si no ha cambiado."],
                ["Campos", "<code>?campos=id,asunto</code> devuelve solo esos campos, en objetos y listas."],
                ["Trazabilidad", "Cada respuesta lleva <code>X-Request-Id</code> (y los errores, <code>request_id</code>). Puedes enviar el tuyo en esa cabecera (8-64 caracteres: letras, números, <code>._-</code>) para correlacionar; al pedir soporte, indica ese id."],
                ["Referencias externas", "Notas, tareas de lista y clientes fiscales admiten <code>referencia_externa</code> (hasta 120 caracteres, única por usuario o despacho). Filtra con <code>?referencia_externa=</code>; <code>GET/PUT /notas|tareas-outlook|fiscal/clientes/por-referencia/{ref}</code> hace <b>upsert</b>: crea (201) o actualiza (200, cabecera <code>X-Guilda-Upsert</code>) sin que guardes nuestros ids. Duplicada: 409 <code>referencia_duplicada</code>."],
                ["Paginación", "<code>limit</code>/<code>offset</code> y total en <code>X-Total-Count</code>."],
                ["Sincronización", "<code>GET /sync</code> da un cursor; después <code>GET /sync?cursor=N</code> devuelve solo lo que cambió (<code>cambios</code> y <code>eliminados</code> de notas, tareas, tareas de lista y proyectos). Ver «Proyectos, checklist, asignación y más»."],
            ]},
            {"type": "table", "headers": ["HTTP", "Significado en esta API"], "rows": [
                ["400", "Datos de entrada inválidos: campo obligatorio ausente, formato incorrecto, valor fuera de rango."],
                ["401", "Token ausente, revocado o incorrecto (ver <a href=\"/docs/autenticacion\">Autenticación</a>)."],
                ["404", "El recurso no existe, o existe pero pertenece a otro usuario — nunca se distingue entre ambos casos, para no filtrar si un id ajeno existe."],
                ["405", "Método HTTP no soportado para esa ruta."],
                ["409", "Conflicto — por ejemplo, <code>/auth/registro</code> con un email ya registrado."],
                ["429", "Límite de peticiones superado (solo aplica a <code>/auth/registro</code> y <code>/auth/login</code>, ver abajo)."],
            ]},
            {"type": "callout", "kind": "warn", "html":
                "El límite de <b>10 peticiones/minuto por IP</b> solo se aplica a <code>/auth/registro</code> y "
                "<code>/auth/login</code> (protección de fuerza bruta) — el resto de la API no tiene un límite de "
                "peticiones propio a nivel de aplicación. Si expones tu instancia a un volumen alto de peticiones "
                "automatizadas, añade tu propio límite en Caddy o en el proxy inverso que tengas delante."},
            {"type": "callout", "kind": "info", "html":
                "<b>Listados.</b> <code>GET /notas</code> (fijadas primero; <code>proyecto_id</code>, <code>q</code>) y "
                "<code>GET /tareas</code> (tareas con duración; <code>desde</code>, <code>hasta</code>, <code>proyecto_id</code>) "
                "tienen listado propio. <code>GET /historial</code> sigue siendo el registro cronológico combinado y "
                "<code>GET /dashboard</code> el resumen del día. Todos los listados admiten <code>limit</code>/<code>offset</code> "
                "y devuelven el total en la cabecera <code>X-Total-Count</code>. Más abajo, "
                "<a href=\"#ampliada\">«Proyectos, checklist, asignación y más»</a>."},
            {"type": "h2", "id": "auth", "text": "Auth"},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["POST", "/auth/registro", "Crea una cuenta nueva y devuelve un token."],
                ["POST", "/auth/login", "Inicia sesión y devuelve un token nuevo."],
                ["POST", "/auth/logout", "Revoca el token de la propia petición."],
                ["GET", "/auth/me", "Datos de la cuenta autenticada."],
            ]},
            {"type": "h2", "id": "categorias", "text": "Proyectos (categorías)"},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["GET", "/categorias", "Lista los proyectos del usuario."],
                ["POST", "/categorias", "Crea un proyecto nuevo (<code>nombre</code>, <code>color</code> opcional)."],
                ["DELETE", "/categorias/{id}", "Elimina un proyecto (va a la papelera)."],
                ["POST", "/categorias/{id}/favorito", "Alterna si el proyecto está marcado como favorito."],
                ["POST", "/categorias/reordenar", "Reordena los proyectos (<code>orden</code>: lista de ids)."],
            ]},
            {"type": "h2", "id": "notas", "text": "Notas"},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["POST", "/notas", "Crea una nota (<code>texto</code>, <code>categoria_id</code>)."],
                ["PUT", "/notas/{id}", "Edita el texto de una nota."],
                ["DELETE", "/notas/{id}", "Elimina una nota (va a la papelera)."],
            ]},
            {"type": "h2", "id": "tareas", "text": "Tareas con duración"},
            {"type": "p", "html":
                "No hay un paso de «iniciar» separado: crear una tarea de tipo <code>duracion</code> la deja "
                "inmediatamente en curso (<code>inicio_en</code> = ahora, <code>estado</code> = "
                "<code>en_curso</code>); crear una de tipo <code>instantanea</code> la crea ya "
                "<code>finalizada</code>, sin <code>fin_en</code>/<code>duracion_segundos</code> por diseño (es "
                "un evento puntual, no algo que se extiende en el tiempo)."},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["POST", "/tareas", "Crea una tarea y la arranca en el mismo paso (<code>nombre</code>, <code>categoria_id</code>, <code>tipo</code>: <code>duracion</code>|<code>instantanea</code>)."],
                ["PUT", "/tareas/{id}", "Renombra una tarea."],
                ["DELETE", "/tareas/{id}", "Elimina una tarea (va a la papelera)."],
                ["POST", "/tareas/{id}/pausar", "Pausa una tarea en curso."],
                ["POST", "/tareas/{id}/reanudar", "Reanuda una tarea pausada."],
                ["POST", "/tareas/{id}/finalizar", "Finaliza la tarea — calcula la duración total descontando el tiempo en pausa."],
            ]},
            {"type": "h2", "id": "tareas-outlook", "text": "Tareas estilo Outlook"},
            {"type": "p", "html":
                "Un segundo tipo de tarea, independiente de las tareas con duración de arriba — con asunto, "
                "cuerpo, prioridad, fechas de inicio/vencimiento y categoría al estilo de Outlook To-Do "
                "(pensado para import/export <code>.ics</code>/<code>.csv</code> compatible)."},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["GET", "/tareas-outlook", "Lista, filtrable por <code>estado</code>/<code>prioridad</code>/<code>categoria</code>/<code>q</code>. <code>ambito</code> opcional: <code>propias</code> (por defecto), <code>asignadas</code>, <code>compartidas</code> o <code>todas</code>; con él cada fila lleva <code>rol</code> (<code>dueno</code>, <code>asignada</code>, <code>compartida</code>)."],
                ["POST", "/tareas-outlook", "Crea una (<code>asunto</code> obligatorio; <code>cuerpo</code>, <code>prioridad</code>, <code>fecha_inicio</code>, <code>fecha_vencimiento</code>, <code>categoria_outlook</code>)."],
                ["PUT", "/tareas-outlook/{id}", "Edita cualquier subconjunto de campos (solo actualiza los presentes en el body)."],
                ["DELETE", "/tareas-outlook/{id}", "Elimina."],
                ["POST", "/tareas-outlook/{id}/completar", "Marca como completada."],
            ]},
            {"type": "h2", "id": "ampliada", "text": "Proyectos, checklist, asignación y más"},
            {"type": "p", "html":
                "Misma autenticación, mismo formato y mismos permisos (un token de solo lectura solo puede hacer <code>GET</code>)."},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["GET", "/sync", "Sin cursor: cursor actual (pídelo antes de la descarga inicial). Con <code>?cursor=N</code>: <code>cambios</code> y <code>eliminados</code> desde entonces, <code>cursor</code> nuevo y <code>hay_mas</code> (<code>limit</code> hasta 1000). <code>reiniciar: true</code> = cursor de más de 30 días, descarga todo de nuevo."],
                ["GET/POST", "/proyectos", "Lista / crea proyectos (<code>nombre</code>, <code>color</code>). Equivale a <code>/categorias</code>."],
                ["PUT/DELETE", "/proyectos/{id}", "Renombra / manda a la papelera."],
                ["GET", "/notas/{id}", "Una nota."],
                ["POST", "/notas/{id}/fijar", "<code>{\"fijada\": true|false}</code>."],
                ["GET", "/tareas-outlook/{id}", "Detalle de una tarea (propia o asignada) con su <code>checklist</code>."],
                ["GET/POST", "/tareas-outlook/{id}/checklist", "Lista / añade una subtarea (<code>texto</code>, máx. 50)."],
                ["POST", "/checklist/{item_id}/alternar", "Marca o desmarca una subtarea (recalcula el porcentaje)."],
                ["POST", "/tareas-outlook/{id}/asignar", "<code>{\"companero_id\": n}</code> (solo del mismo despacho); sin él, desasigna."],
                ["GET", "/companeros", "Compañeros del despacho a quienes asignar."],
                ["GET", "/mi-dia", "Vencidas, de hoy, en curso y asignadas."],
                ["GET", "/correo/mensajes/{id}/conversacion", "Mensajes del mismo hilo."],
                ["POST", "/correo/mensajes/{id}/tarea", "Crea una tarea vinculada al correo (<code>fecha_vencimiento</code> opcional)."],
                ["POST", "/correo/mensajes/{id}/nota", "Guarda el correo como nota."],
                ["GET/DELETE", "/correo/programados[/{id}]", "Envíos programados pendientes / cancela uno."],
                ["GET/DELETE", "/correo/seguimientos[/{id}]", "«Avísame si no responde» (<code>todos=1</code> incluye cerrados) / cancela."],
                ["GET", "/correo/plantillas", "Plantillas de correo."],
                ["GET", "/notificaciones", "Últimas (<code>limit</code>, máx. 100) y <code>no_leidas</code>."],
                ["POST/DELETE", "/notificaciones/leidas, /notificaciones/{id}", "Marca todas como leídas / elimina una."],
                ["GET", "/buscar?q=", "Búsqueda en notas, tareas y correo (<code>limit</code> 1-20)."],
                ["GET", "/ia/consumo", "Consultas de IA del mes del despacho y su tope (<code>ilimitado</code> si no hay)."],
                ["GET", "/comunicados", "Avisos de Guilda vigentes para el usuario."],
                ["POST", "/comunicados/{id}/cerrar", "Cierra un aviso (los críticos no se pueden cerrar: 403)."],
            ]},
            {"type": "h2", "id": "tareas-completas", "text": "Tareas: flujo completo"},
            {"type": "p", "html":
                "Todo lo que se hace con una tarea de lista en la web, también por API. Los permisos son los de siempre "
                "(dueño, colaborador, observador, asignado) y las mismas notificaciones: asignar, compartir, mencionar y "
                "desbloquear avisan a las personas afectadas. Área de token: <code>tareas</code>."},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["POST", "/tareas-outlook/{id}/estado", "<code>{\"estado\": \"no_iniciada|en_progreso|completada|esperando|aplazada\"}</code>. <b>409</b> <code>tarea_bloqueada</code> si espera a otras (también en <code>/completar</code>)."],
                ["GET/POST", "/tareas-outlook/{id}/dependencias", "Qué la bloquea / <code>{\"depende_de_id\": n}</code> (409 si crearía un ciclo)."],
                ["DELETE", "/tareas-outlook/{id}/dependencias/{depende_de_id}", "Quita la dependencia."],
                ["GET/POST", "/tareas-outlook/{id}/comentarios", "Lista / comenta (<code>texto</code>, con @menciones). Lo puede hacer quien ve la tarea."],
                ["DELETE", "/tareas-outlook/{id}/comentarios/{comentario_id}", "Borra un comentario (el suyo, o el dueño)."],
                ["GET", "/tareas-outlook/{id}/actividad", "Historial de cambios."],
                ["GET/POST", "/tareas-outlook/{id}/recordatorios", "Lista / crea (<code>avisar_en</code> o <code>atajo</code>, <code>canales</code>)."],
                ["DELETE/POST", "/tareas-outlook/recordatorios/{rid}[/posponer]", "Borra / pospone (<code>opcion</code>)."],
                ["GET/POST", "/tareas-outlook/{id}/compartir", "Participantes / comparte (<code>usuario_id</code>, <code>rol</code>: <code>colabora</code> | <code>observa</code>; solo el dueño)."],
                ["DELETE", "/tareas-outlook/{id}/compartir/{usuario_id}", "Quita a un participante (o se sale uno mismo)."],
                ["POST", "/tareas-outlook/{id}/cronometro/iniciar", "Empieza a contar tiempo (<code>proyecto_id</code> si la tarea no tiene). Luego se pausa y finaliza con <code>/tareas/{id}/...</code>."],
                ["GET", "/tareas-outlook/{id}/tiempo", "Tiempo registrado (tuyo y del equipo)."],
                ["POST", "/tareas-outlook/{id}/mover", "<code>{\"persona_id\", \"fecha\"}</code>: reasigna y/o cambia el día."],
                ["POST", "/tareas-outlook/{id}/restaurar", "Saca de la papelera."],
                ["DELETE", "/checklist/{item_id}", "Borra una subtarea."],
                ["POST", "/tareas-outlook/lote", "<code>{\"ids\": [...], \"accion\": \"completar|estado|prioridad|fecha|asignar|proyecto|seccion\", \"valor\": \"..\"}</code> (máx. 200) → <code>{ok, fallos}</code>."],
                ["GET", "/tareas-outlook/tablero", "Tareas agrupadas por estado."],
                ["GET", "/tareas-outlook/carga?semana=", "Plan de la semana por persona (horas estimadas frente a capacidad)."],
                ["GET/POST/DELETE", "/tareas-outlook/vistas[/{id}]", "Vistas guardadas: <code>{nombre, filtros, compartida}</code>."],
                ["GET/POST", "/tareas-plantillas", "Plantillas de tareas (<code>nombre</code>, <code>items</code>, <code>compartida</code>)."],
                ["PUT/DELETE", "/tareas-plantillas/{id}", "Edita / borra."],
                ["POST", "/tareas-plantillas/{id}/aplicar", "Crea las tareas (<code>fecha_inicio</code>, <code>proyecto_id</code> o <code>nuevo_proyecto</code>, <code>cliente_fiscal_id</code>, <code>asignada_a</code>, <code>encadenar</code>)."],
                ["GET/POST", "/tareas-recurrentes", "Tareas que se repiten (<code>asunto</code>, <code>periodicidad</code>, <code>dia</code>, <code>mes</code>)."],
                ["POST/DELETE", "/tareas-recurrentes/{id}[/alternar]", "Activa/pausa · borra."],
                ["GET/POST", "/tareas-reglas-vencimiento", "«Una tarea por cada vencimiento del modelo X» (<code>modelo</code>, <code>asunto</code> con {cliente}/{modelo}/{periodo}, <code>crear_dias_antes</code>, <code>vence_dias_antes</code>)."],
                ["POST/DELETE", "/tareas-reglas-vencimiento/{id}[/alternar]", "Activa/pausa · borra."],
            ]},
            {"type": "h2", "id": "fiscal-completo", "text": "Calendario fiscal: flujo completo"},
            {"type": "p", "html":
                "Mismas reglas que la web: todo se limita al despacho del usuario, el expediente del cliente registra quién lo toca "
                "(las acciones por API quedan marcadas «vía API» en el registro de accesos) y los avisos por correo al cliente salen igual. "
                "Área de token: <code>fiscal</code>. Un cliente admite <code>email</code>, <code>pais</code> (ISO, p. ej. ES), <code>idioma</code> "
                "(es|ca|en|fr), <code>recordatorios_portal</code> y <code>referencia_externa</code>."},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["GET", "/fiscal/modelos?pais=", "Modelos fiscales disponibles por país."],
                ["GET", "/fiscal/clientes/{id}/resumen", "Modelos, pendientes y próximos vencimientos."],
                ["GET", "/fiscal/clientes/{id}/accesos", "Registro de accesos al expediente (solo supervisores; RGPD)."],
                ["GET/POST", "/fiscal/clientes/{id}/documentos", "Expediente: lista (metadatos) / sube hasta 10 archivos de 15 MB (multipart <code>archivo</code>, <code>categoria</code>) → resultado por archivo."],
                ["GET/DELETE", "/fiscal/clientes/{id}/documentos/{doc}", "Descarga (siempre como adjunto, nunca como página) / borra."],
                ["POST", "/fiscal/vencimientos", "Alta manual: <code>cliente_id</code>, <code>modelo</code>, <code>periodo</code>, <code>fecha_limite</code>; 409 <code>vencimiento_duplicado</code>."],
                ["GET", "/fiscal/vencimientos", "Filtros <code>estado</code>, <code>cliente_id</code>, <code>desde</code>, <code>hasta</code>, <code>pais</code>; paginación en SQL y <code>X-Total-Count</code>."],
                ["GET", "/fiscal/vencimientos/{id}", "Detalle con documentos, mensajes y si tiene constancia o justificante."],
                ["GET", "/fiscal/vencimientos/propuestas?cliente_id=&anio=", "Vista previa de lo que se generaría (con <code>ya_existe</code>)."],
                ["POST", "/fiscal/clientes/{id}/generar-vencimientos", "<code>{modelos?, anio?}</code> sin duplicar; usa el país del cliente → <code>{creados, ids, omitidos}</code>."],
                ["POST", "/fiscal/vencimientos/generar-masivo", "<code>{anio}</code>: todos los clientes con modelos definidos, sin duplicar."],
                ["POST", "/fiscal/vencimientos/{id}/presentado", "Como en la web: constancia en PDF, justificante opcional (multipart <code>justificante</code>) y evento <code>vencimiento.presentado</code>."],
                ["POST", "/fiscal/vencimientos/{id}/justificante", "Sube el justificante oficial (imagen o PDF, 8 MB)."],
                ["POST", "/fiscal/vencimientos/{id}/constancia", "Regenera la constancia en PDF."],
                ["GET", "/fiscal/vencimientos/{id}/documentos[/{doc}]", "Lo que sube el cliente desde el portal, la constancia y el justificante; descarga."],
                ["GET/POST", "/fiscal/vencimientos/{id}/mensajes", "Conversación con el cliente; al responder se le avisa por correo."],
                ["GET/PUT", "/fiscal/recordatorios", "Días de aviso al cliente antes/después, aviso al equipo y texto propio con marcas."],
                ["GET", "/fiscal/papelera", "Clientes y vencimientos borrados."],
                ["POST", "/fiscal/papelera/{cliente_fiscal|vencimiento_fiscal}/{id}/restaurar", "Recupera un elemento."],
            ]},
            {"type": "p", "html":
                "Lo que no está en la API a propósito: enviar a firma electrónica y cobrar por Stripe (acciones con efecto sobre terceros o dinero "
                "que se hacen desde la ficha del vencimiento, con revisión humana)."},
            {"type": "h2", "id": "extras-api", "text": "Adjuntos de notas, envíos, plantillas y administración del fichaje"},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["GET/POST", "/notas/{id}/adjuntos", "Lista (metadatos) / sube (multipart, varios <code>adjunto</code>): imágenes, PDF, texto o CSV; 5 MB cada uno, 5 por nota. Resultado por archivo."],
                ["GET/DELETE", "/notas/adjuntos/{adjunto_id}", "Descarga (<code>?ver=1</code> en línea si es imagen) / borra."],
                ["GET", "/correo/envios/{id}", "Estado de un envío (<code>pendiente</code>, <code>enviado</code>, <code>cancelado</code>, <code>error</code>)."],
                ["POST", "/correo/envios/{id}/cancelar", "Cancela un envío programado; <code>{\"como_borrador\": true}</code> lo conserva como borrador (409 si ya salió). <code>DELETE /correo/programados/{id}</code> lo descarta."],
                ["GET", "/correo/plantillas/variables", "Variables <code>{{...}}</code> disponibles."],
                ["GET/PUT/DELETE", "/correo/plantillas/{id}", "Ver (con <code>?cliente_fiscal_id=</code> devuelve además <code>renderizada</code> y <code>sin_resolver</code>) / editar cualquier subconjunto / borrar."],
                ["POST", "/correo/plantillas", "Crea: <code>nombre</code>, <code>asunto</code>, <code>cuerpo</code> (HTML con variables), <code>modelo</code>."],
                ["GET", "/fichaje/admin/resumen", "Horas por trabajador del despacho (<code>desde</code>, <code>hasta</code>) y de la semana. Gestores de fichajes; un administrador global añade <code>tenant_id</code>."],
                ["GET", "/fichaje/admin/usuarios/{id}", "Datos y fichajes de un trabajador (el más reciente primero)."],
                ["POST", "/fichaje/admin/usuarios/{id}/corregir", "Corrección auditable: <code>tipo</code>, <code>marca_tiempo</code> (hora REAL), <code>corrige_a</code>, <code>nota</code>. Inserta un fichaje nuevo (origen <code>correccion_admin</code>); no sobrescribe."],
                ["GET", "/fichaje/admin/exportar.csv|pdf|json", "Registro horario (<code>desde</code>, <code>hasta</code>, <code>usuario_id</code>). El JSON lleva el hash de cada fila."],
                ["GET", "/fichaje/admin/verificar-integridad", "Comprueba la cadena de hashes del registro horario."],
            ]},
            {"type": "h2", "id": "webhooks-api", "text": "Webhooks por API"},
            {"type": "p", "html":
                "Para que una integración se dé de alta sola. Solo un <b>supervisor del despacho</b> o un administrador "
                "(los webhooks sacan datos del despacho). La URL debe ser <b>https y pública</b> (se rechazan direcciones "
                "internas y no se siguen redirecciones). Área de token: <code>webhooks</code>."},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["GET/POST", "/webhooks", "Lista / crea (<code>url</code>, <code>eventos</code>). El <code>secreto</code> solo se devuelve al crear."],
                ["GET", "/webhooks/catalogo-eventos", "Eventos disponibles."],
                ["GET/PUT/DELETE", "/webhooks/{id}", "Ver / cambiar (<code>url</code>, <code>eventos</code>, <code>activo</code>) / borrar. Los creados desde el Backoffice son de solo lectura aquí."],
                ["POST", "/webhooks/{id}/rotar-secreto", "Secreto nuevo (el anterior deja de valer al instante)."],
                ["POST", "/webhooks/{id}/probar", "Encola un evento <code>ping</code> (202)."],
                ["GET", "/webhooks/{id}/entregas", "Intentos recientes y estado de la cola."],
                ["POST", "/webhooks/entregas/{cola_id}/reintentar", "Reintenta una entrega fallida."],
            ]},
            {"type": "h2", "id": "dashboard-historico", "text": "Dashboard, histórico y exportación"},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["GET", "/dashboard", "Resumen del día: proyectos, tareas activas, notas de hoy, correos sin leer."],
                ["GET", "/historial", "Histórico filtrable por <code>desde</code>/<code>hasta</code>/<code>categoria_id</code>/<code>q</code>."],
                ["GET", "/export", "Exporta el histórico — <code>formato</code>: <code>json</code> (por defecto) | <code>csv</code> | <code>md</code>, más <code>desde</code>/<code>hasta</code>/<code>categoria_id</code>."],
            ]},
            {"type": "h2", "id": "papelera", "text": "Papelera"},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["GET", "/papelera", "Lista los elementos borrados (notas, tareas, proyectos)."],
                ["POST", "/papelera/{tipo}/{id}/restaurar", "Restaura un elemento — <code>tipo</code>: <code>nota</code>|<code>tarea</code>|<code>menu</code>."],
                ["POST", "/papelera/{tipo}/{id}/eliminar-definitivamente", "Borra un elemento sin posibilidad de restaurarlo."],
            ]},
            {"type": "h2", "id": "correo", "text": "Correo"},
            {"type": "p", "html":
                "El cliente de correo propio de Guilda Work (cuentas IMAP/SMTP conectadas por el usuario, "
                "distinto del correo-como-herramienta de Stalwart, ver <a href=\"/docs/asistente-ia\">Asistente "
                "de IA (MCP)</a>) — bandeja, carpetas, categorías propias, remitentes de confianza, reglas "
                "automáticas, firma y envío."},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["GET", "/correo/cuentas", "Lista las cuentas de correo conectadas."],
                ["POST", "/correo/cuentas", "Conecta una cuenta nueva (<code>host</code>/<code>puerto</code>/<code>usuario</code>/<code>contrasena</code> IMAP, más SMTP opcional)."],
                ["DELETE", "/correo/cuentas/{id}", "Desconecta una cuenta."],
                ["POST", "/correo/cuentas/{id}/sincronizar", "Sincroniza la bandeja (todas las carpetas IMAP se descubren solas)."],
                ["GET", "/correo/carpetas", "Carpetas de una cuenta (<code>cuenta_id</code>)."],
                ["GET", "/correo/mensajes", "Bandeja, filtrable por <code>cuenta_id</code>/<code>carpeta</code>/<code>no_leidos</code>/<code>q</code>/<code>pospuestos</code>."],
                ["GET", "/correo/mensajes/{id}", "Lee un mensaje completo, con sus adjuntos."],
                ["GET", "/correo/mensajes/{mensaje_id}/adjuntos/{adjunto_id}", "Descarga un adjunto."],
                ["DELETE", "/correo/mensajes/{id}", "Elimina un mensaje."],
                ["POST", "/correo/mensajes/{id}/leido", "Marca leído/no leído."],
                ["POST", "/correo/mensajes/{id}/destacar", "Destaca (y opcionalmente fija una fecha de aviso)."],
                ["POST", "/correo/mensajes/{id}/posponer", "Pospone hasta una fecha."],
                ["POST", "/correo/mensajes/{id}/categoria", "Asigna una categoría propia de Guilda Work."],
                ["POST", "/correo/mensajes/{id}/mover", "Mueve a otra carpeta IMAP."],
                ["POST", "/correo/mensajes/lote/{accion}", "Acción en lote sobre varios <code>ids</code> a la vez — <code>accion</code>: <code>leido</code>|<code>destacar</code>|<code>mover</code>|<code>eliminar</code>."],
                ["POST", "/correo/enviar", "Envía un correo. JSON (adjuntos en base64) o <b>multipart</b> (ficheros en <code>adjuntos</code>, mejor para archivos grandes). <code>cc</code>/<code>bcc</code>, <code>en_respuesta_a</code>, <code>seguimiento_dias</code> («avísame si no responde») y <code>programar_para</code> (<code>YYYY-MM-DDTHH:MM</code>: queda en cola, <b>202</b> con <code>envio_id</code>). Máx. 20 adjuntos y 25 MB; base64 inválido: 400 <code>adjunto_invalido</code>."],
                ["GET / POST", "/correo/categorias", "Categorías propias de Guilda Work (no se sincronizan con el servidor de correo)."],
                ["DELETE", "/correo/categorias/{id}", "Elimina una categoría propia."],
                ["GET / POST", "/correo/remitentes-confiables", "Remitentes cuyas imágenes/enlaces se cargan sin aviso previo."],
                ["DELETE", "/correo/remitentes-confiables/{id}", "Quita un remitente de confianza."],
                ["GET / POST", "/correo/reglas-categoria", "Reglas que asignan categoría automáticamente por patrón de remitente."],
                ["DELETE", "/correo/reglas-categoria/{id}", "Elimina una regla."],
                ["GET", "/correo/destinatarios-recientes", "Autocompletado de destinatarios usados antes (<code>q</code>)."],
                ["GET / POST", "/correo/ajustes", "Preferencias: densidad, marcar leído automático, límite de mensajes por sincronización."],
                ["POST", "/correo/firma", "Guarda la firma HTML de una cuenta (con o sin firma en respuestas)."],
            ]},
            {"type": "h2", "id": "ia", "text": "Asistente de IA integrado"},
            {"type": "p", "html":
                "El chat del asistente embebido en la propia app (distinto de conectar Claude/ChatGPT por MCP "
                "contra tu instancia, ver <a href=\"/docs/asistente-ia\">Asistente de IA (MCP)</a> para eso)."},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["GET", "/ia/mensajes", "Mensajes de la conversación activa con el asistente."],
                ["POST", "/ia/mensaje", "Envía un mensaje al asistente."],
                ["POST", "/ia/confirmar", "Confirma o cancela una acción sensible pendiente (p. ej. enviar un correo)."],
                ["POST", "/ia/vaciar", "Abre una conversación nueva en blanco (la anterior se conserva en <code>/ia/conversaciones</code>)."],
                ["GET", "/ia/conversaciones", "Lista las conversaciones del usuario (más reciente primero) y cuál está activa."],
                ["POST", "/ia/conversaciones", "Abre una conversación nueva y la deja activa."],
                ["POST", "/ia/conversaciones/{id}/activar", "Cambia la conversación activa: <code>/ia/mensajes</code> y <code>/ia/mensaje</code> pasan a trabajar con ella."],
                ["POST", "/ia/conversaciones/{id}/renombrar", "Cambia el título (<code>titulo</code>, máx. 60 caracteres). Por defecto es el inicio del primer mensaje."],
                ["DELETE", "/ia/conversaciones/{id}", "Elimina la conversación y sus mensajes."],
                ["GET / POST", "/ia/ajustes", "Modelo, modo autónomo y clave de API del proveedor de IA."],
            ]},
            {"type": "h2", "id": "herramientas", "text": "Herramientas conectadas"},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["GET", "/herramientas", "Catálogo de herramientas conectadas visibles para el usuario (mismo que la pantalla «Herramientas» de la web, sin «Chat» — el móvil usa un cliente Matrix nativo, ver la fila de abajo)."],
                ["GET", "/chat/config", "URL del homeserver de Matrix/Synapse, para el cliente de chat nativo."],
            ]},
            {"type": "callout", "kind": "info", "html":
                "Esta es la API pensada para clientes propios (apps móviles, scripts, integraciones a medida). "
                "Para que un asistente de IA de terceros (Claude, ChatGPT, Codex) actúe directamente sobre tu "
                "instancia, la vía recomendada es MCP — ver <a href=\"/docs/asistente-ia\">Asistente de IA (MCP)</a>."},
        ],
    },
    {
        "slug": "modelos-de-datos",
        "grupo": "INTEGRACIÓN",
        "titulo": "Modelos de datos",
        "descripcion": "La forma exacta de cada objeto que devuelve la API — campos, tipos y notas.",
        "bloques": [
            {"type": "p", "html":
                "Los nombres de campo son los mismos que las columnas reales de SQLite (<code>app/db.py</code>) — "
                "lo que ves aquí es lo que te devuelve la API, sin una capa de serialización intermedia que "
                "pueda renombrar nada. Todos los timestamps son <b>ISO 8601 en hora local del servidor, sin "
                "offset</b> (ej. <code>2026-07-10T14:32:05</code>), nunca UTC ni con zona horaria explícita."},
            {"type": "h2", "id": "categoria", "text": "Categoria (proyecto)"},
            {"type": "table", "headers": ["Campo", "Tipo", "Notas"], "rows": [
                ["<code>id</code>", "integer", ""],
                ["<code>nombre</code>", "string", "Único por usuario."],
                ["<code>color</code>", "string | null", "Código de color hex, opcional."],
                ["<code>creada_en</code>", "string (ISO 8601)", ""],
                ["<code>papelera_en</code>", "string (ISO 8601) | null", "No <code>null</code> si está en la papelera — la API nunca devuelve categorías en la papelera desde <code>/categorias</code>, solo desde <code>/papelera</code>."],
                ["<code>orden</code>", "integer | null", "Posición manual (↑/↓ en el panel de inicio); <code>null</code> = orden alfabético por defecto."],
            ]},
            {"type": "h2", "id": "nota", "text": "Nota"},
            {"type": "table", "headers": ["Campo", "Tipo", "Notas"], "rows": [
                ["<code>id</code>", "integer", ""],
                ["<code>texto</code>", "string", ""],
                ["<code>categoria_id</code>", "integer | null", ""],
                ["<code>tarea_id</code>", "integer | null", "Si la nota quedó asociada a una tarea con duración concreta — la API REST actual no tiene forma de fijar este campo al crear (siempre <code>null</code> vía <code>POST /notas</code>), pero si existe se devuelve igualmente."],
                ["<code>creada_en</code>", "string (ISO 8601)", "Con segundos — es el timestamp que ordena el registro cronológico."],
                ["<code>papelera_en</code>", "string (ISO 8601) | null", ""],
            ]},
            {"type": "h2", "id": "tarea-duracion", "text": "Tarea (con duración)"},
            {"type": "p", "html":
                "No confundir con <b>TareaOutlook</b> (siguiente sección) — son dos modelos independientes, sin "
                "relación entre sí, pensados para cosas distintas: esta es la tarea con cronómetro del registro "
                "de actividad; la otra es una lista de tareas al estilo Microsoft Outlook To-Do."},
            {"type": "table", "headers": ["Campo", "Tipo", "Notas"], "rows": [
                ["<code>id</code>", "integer", ""],
                ["<code>nombre</code>", "string", ""],
                ["<code>categoria_id</code>", "integer", "Obligatorio — a diferencia de <code>Nota</code>, una tarea con duración siempre pertenece a un proyecto."],
                ["<code>tipo</code>", "<code>\"duracion\"</code> | <code>\"instantanea\"</code>", "Fijo desde la creación, no se puede cambiar."],
                ["<code>estado</code>", "<code>\"pendiente\"</code> | <code>\"en_curso\"</code> | <code>\"pausada\"</code> | <code>\"finalizada\"</code>", "Una <code>instantanea</code> nace directamente en <code>finalizada</code>."],
                ["<code>inicio_en</code>", "string (ISO 8601) | null", ""],
                ["<code>fin_en</code>", "string (ISO 8601) | null", "<code>null</code> hasta que se finaliza."],
                ["<code>duracion_segundos</code>", "integer | null", "Calculado al finalizar, descontando el tiempo en pausa — <code>null</code> mientras no está finalizada, y siempre <code>null</code> en tipo <code>instantanea</code> (por diseño, no por estar pendiente)."],
                ["<code>papelera_en</code>", "string (ISO 8601) | null", ""],
            ]},
            {"type": "h2", "id": "tarea-outlook", "text": "TareaOutlook"},
            {"type": "p", "html":
                "Nombres de campo calcados del modelo de objetos de Outlook/iCalendar (VTODO, RFC 5545) a "
                "propósito, para que el mapeo de import/export <code>.ics</code>/<code>.csv</code> sea 1:1 sin "
                "traducir nombres."},
            {"type": "table", "headers": ["Campo", "Tipo", "Notas"], "rows": [
                ["<code>id</code>", "integer", ""],
                ["<code>asunto</code>", "string", "Equivalente a \"Subject\"."],
                ["<code>cuerpo</code>", "string | null", ""],
                ["<code>estado</code>", "<code>\"no_iniciada\"</code> | <code>\"en_progreso\"</code> | <code>\"completada\"</code> | <code>\"esperando\"</code> | <code>\"aplazada\"</code>", "Por defecto <code>no_iniciada</code>."],
                ["<code>porcentaje_completado</code>", "integer", "0-100, por defecto 0."],
                ["<code>prioridad</code>", "<code>\"baja\"</code> | <code>\"normal\"</code> | <code>\"alta\"</code>", "Por defecto <code>normal</code>."],
                ["<code>fecha_inicio</code>", "string (ISO 8601) | null", ""],
                ["<code>fecha_vencimiento</code>", "string (ISO 8601) | null", ""],
                ["<code>fecha_completada</code>", "string (ISO 8601) | null", "Se rellena sola al completar."],
                ["<code>categoria_outlook</code>", "string | null", "Texto libre — no es una <code>Categoria</code>/proyecto, es la categoría de color propia de Outlook."],
                ["<code>outlook_entry_id</code>", "string | null", "EntryID de Outlook, para reconciliar en reimportaciones repetidas del mismo archivo."],
                ["<code>creada_en</code> / <code>actualizada_en</code>", "string (ISO 8601)", ""],
                ["<code>papelera_en</code>", "string (ISO 8601) | null", ""],
            ]},
            {"type": "h2", "id": "cuenta-correo", "text": "CuentaCorreo"},
            {"type": "table", "headers": ["Campo", "Tipo", "Notas"], "rows": [
                ["<code>id</code>", "integer", ""],
                ["<code>nombre</code>", "string", "Nombre visible de la cuenta, elegido por el usuario."],
                ["<code>protocolo</code>", "<code>\"imap\"</code> | <code>\"pop3\"</code>", ""],
                ["<code>host</code> / <code>puerto</code> / <code>usa_tls</code>", "string / integer / boolean", "Conexión de recepción."],
                ["<code>usuario</code>", "string", "Usuario de login del servidor de correo (no el id local)."],
                ["<code>smtp_host</code> / <code>smtp_puerto</code> / <code>smtp_tls</code>", "string | null / integer | null / boolean", "Solo si la cuenta tiene envío configurado."],
                ["<code>creada_en</code> / <code>ultima_sincronizacion</code>", "string (ISO 8601) | null", ""],
                ["<code>firma_html</code>, <code>firma_en_nuevos</code>, <code>firma_en_respuestas</code>", "string | null, boolean, boolean", ""],
            ]},
            {"type": "callout", "kind": "warn", "html":
                "La <b>contraseña de la cuenta de correo nunca aparece</b> en la respuesta de la API — no se "
                "guarda en SQLite en absoluto, vive en el almacén de credenciales del sistema operativo "
                "(keyring), bajo una clave interna por cuenta."},
            {"type": "h2", "id": "mensaje-correo", "text": "MensajeCorreo"},
            {"type": "table", "headers": ["Campo", "Tipo", "Notas"], "rows": [
                ["<code>id</code>", "integer", "Id local (caché) — no es el <code>uid</code> IMAP."],
                ["<code>cuenta_id</code>", "integer", ""],
                ["<code>carpeta</code>", "string", "Por defecto <code>INBOX</code>."],
                ["<code>uid</code>", "string", "Identificador IMAP/POP3 real del mensaje en el servidor."],
                ["<code>asunto</code>, <code>remitente</code>, <code>destinatarios</code>, <code>cc</code>", "string | null", ""],
                ["<code>fecha</code>", "string (ISO 8601) | null", "Fecha del mensaje según su cabecera, no la de sincronización."],
                ["<code>cuerpo_texto</code> / <code>cuerpo_html</code>", "string | null", ""],
                ["<code>message_id</code>", "string | null", "Cabecera <code>Message-ID</code>, para hilos (<code>In-Reply-To</code>/<code>References</code>) al responder."],
                ["<code>leido</code>, <code>destacado</code>", "boolean", ""],
                ["<code>categoria_id</code>", "integer | null", "Categoría de color propia de Guilda Work — nunca se sincroniza con el servidor de correo."],
                ["<code>fecha_aviso</code>, <code>pospuesto_hasta</code>", "string (ISO 8601) | null", ""],
            ]},
            {"type": "callout", "kind": "info", "html":
                "El <b>Cco (bcc) de un mensaje recibido nunca aparece aquí</b> — por diseño del propio correo "
                "electrónico, nadie salvo el remitente original sabe quién iba en copia oculta; no es una "
                "limitación de Guilda Work, ningún cliente de correo puede mostrar ese dato en un mensaje "
                "recibido."},
        ],
    },
    {
        "slug": "explorador-api",
        "grupo": "INTEGRACIÓN",
        "titulo": "Explorador de API interactivo",
        "descripcion": "Todos los endpoints REST, filtrables, con parámetros y un curl de ejemplo — generado en el navegador a partir del OpenAPI real.",
        "interactivo": True,
        "bloques": [],
    },
    {
        "slug": "ejemplos",
        "grupo": "INTEGRACIÓN",
        "titulo": "Ejemplos",
        "descripcion": "Recetas completas: curl, Python y JavaScript.",
        "bloques": [
            {"type": "p", "html":
                "Tres formas equivalentes de hacer lo mismo — registrar (o reutilizar) una cuenta, crear un proyecto "
                "y anotar una tarea con duración ya finalizada — para que elijas la que mejor encaje con tu stack."},
            {"type": "h2", "id": "curl", "text": "curl / bash"},
            {"type": "code", "lang": "bash", "code":
                'BASE="https://tu-hostname/api/v1"\n\n'
                'TOKEN=$(curl -s -X POST "$BASE/auth/login" \\\n'
                '  -H "Content-Type: application/json" \\\n'
                '  -d \'{"email": "dev@tuempresa.com", "contrasena": "..."}\' \\\n'
                "  | python3 -c \"import sys,json; print(json.load(sys.stdin)['data']['token'])\")\n\n"
                'MENU_ID=$(curl -s -X POST "$BASE/categorias" \\\n'
                '  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\\n'
                "  -d '{\"nombre\": \"Cliente Alfa\"}' \\\n"
                "  | python3 -c \"import sys,json; print(json.load(sys.stdin)['data']['id'])\")\n\n"
                'curl -s -X POST "$BASE/tareas" \\\n'
                '  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\\n'
                "  -d \"{\\\"nombre\\\": \\\"Reunión de seguimiento\\\", \\\"categoria_id\\\": $MENU_ID}\""},
            {"type": "h2", "id": "python", "text": "Python"},
            {"type": "code", "lang": "python", "code":
                'import requests\n\n'
                'BASE = "https://tu-hostname/api/v1"\n\n'
                'resp = requests.post(f"{BASE}/auth/login", json={\n'
                '    "email": "dev@tuempresa.com", "contrasena": "...",\n'
                "})\n"
                'token = resp.json()["data"]["token"]\n'
                'cabeceras = {"Authorization": f"Bearer {token}"}\n\n'
                'menu = requests.post(f"{BASE}/categorias", headers=cabeceras,\n'
                '                     json={"nombre": "Cliente Alfa"}).json()["data"]\n\n'
                'tarea = requests.post(f"{BASE}/tareas", headers=cabeceras, json={\n'
                '    "nombre": "Reunión de seguimiento",\n'
                '    "categoria_id": menu["id"],\n'
                "}).json()[\"data\"]\n\n"
                'requests.post(f"{BASE}/tareas/{tarea[\'id\']}/finalizar", headers=cabeceras)'},
            {"type": "h2", "id": "javascript", "text": "JavaScript (fetch)"},
            {"type": "code", "lang": "javascript", "code":
                'const BASE = "https://tu-hostname/api/v1";\n\n'
                "async function api(ruta, opciones = {}) {\n"
                "  const resp = await fetch(`${BASE}${ruta}`, {\n"
                "    ...opciones,\n"
                "    headers: { \"Content-Type\": \"application/json\", ...opciones.headers },\n"
                "  });\n"
                "  return resp.json();\n"
                "}\n\n"
                'const { data: { token } } = await api("/auth/login", {\n'
                '  method: "POST",\n'
                '  body: JSON.stringify({ email: "dev@tuempresa.com", contrasena: "..." }),\n'
                "});\n"
                'const auth = { Authorization: `Bearer ${token}` };\n\n'
                'const { data: menu } = await api("/categorias", {\n'
                '  method: "POST", headers: auth,\n'
                '  body: JSON.stringify({ nombre: "Cliente Alfa" }),\n'
                "});\n\n"
                'await api("/tareas", {\n'
                '  method: "POST", headers: auth,\n'
                '  body: JSON.stringify({ nombre: "Reunión de seguimiento", categoria_id: menu.id }),\n'
                "});"},
            {"type": "h2", "id": "exportar-a-ia", "text": "Exportar el histórico para pegarlo en una conversación de IA"},
            {"type": "p", "html":
                "Sin ningún cliente propio: descarga el histórico filtrado en JSON, CSV o un resumen en "
                "Markdown ya legible, listo para pegar o adjuntar en una conversación con Claude/ChatGPT."},
            {"type": "code", "lang": "bash", "code":
                'curl -s "https://tu-hostname/api/v1/export?formato=md&desde=2026-07-01&hasta=2026-07-31" \\\n'
                '  -H "Authorization: Bearer $TOKEN" -o resumen-julio.md'},
        ],
    },
    {
        "slug": "sdk",
        "grupo": "INTEGRACIÓN",
        "titulo": "SDK y Postman",
        "descripcion": "Cliente de Python, cliente de TypeScript y colección de Postman, generados del contrato de la API de tu instancia.",
        "bloques": [
            {"type": "badges", "items": ["Python", "TypeScript", "Postman", "Sin dependencias"]},
            {"type": "p", "html":
                "Se generan <b>en el momento de descargarlos</b> a partir del <a href=\"/api/v1/openapi.json\">contrato OpenAPI</a> de esta instancia y "
                "ya apuntan a ella: cuando la API se amplía, vuelve a descargarlos. Los tres traen reintentos con retroceso, respeto de "
                "<code>Retry-After</code>, <code>Idempotency-Key</code> automática en los <code>POST</code> (un reintento no duplica), errores con "
                "<code>codigo</code> y <code>request_id</code> y la verificación de la firma de los webhooks."},
            {"type": "table", "headers": ["Descarga", "Para qué"], "rows": [
                ["<a href=\"/docs/sdk/guilda_work.py\" download><code>guilda_work.py</code></a>", "Un solo fichero, solo biblioteca estándar (Python 3.9+). Un método por operación."],
                ["<a href=\"/docs/sdk/guilda-work.ts\" download><code>guilda-work.ts</code></a>", "Un solo fichero con <code>fetch</code> (Node 18+, navegadores, Deno, Bun) y los tipos de todas las entidades."],
                ["<a href=\"/docs/sdk/guilda-work.postman_collection.json\" download><code>guilda-work.postman_collection.json</code></a>", "Colección de Postman (también vale en Insomnia, Bruno o Hoppscotch): una carpeta por tema, ejemplos y variables."],
            ]},
            {"type": "h2", "id": "python", "text": "Python"},
            {"type": "code", "lang": "python", "code":
                "from guilda_work import Cliente, ErrorGuilda, verificar_firma_webhook\n\n"
                "g = Cliente(token=\"TU_TOKEN\")                      # o Cliente().login(email=..., contrasena=...)\n\n"
                "nota = g.crear_nota(texto=\"Llamar al cliente\", referencia_externa=\"CRM-881\")\n"
                "g.upsert_nota(\"CRM-881\", texto=\"Llamar al cliente (hecho)\")        # crea o actualiza por tu propia referencia\n\n"
                "for tarea in g.paginar(g.listar_tareas_outlook, estado=\"en_progreso\"):  # recorre todas las páginas\n"
                "    print(tarea[\"asunto\"])\n\n"
                "try:\n"
                "    g.cambiar_estado_tarea(57, estado=\"completada\")\n"
                "except ErrorGuilda as e:\n"
                "    if e.codigo == \"tarea_bloqueada\":        # programa contra el código, no contra el texto\n"
                "        print(\"espera a otras tareas\", e.request_id)\n\n"
                "g.subir_adjuntos_nota(nota[\"id\"], adjunto=[(\"extracto.pdf\", open(\"extracto.pdf\", \"rb\").read(), \"application/pdf\")])"},
            {"type": "h2", "id": "sincronizar", "text": "Sincronizar sin volver a descargarlo todo"},
            {"type": "code", "lang": "python", "code":
                "cursor = g.sincronizar()[\"cursor\"]          # antes de la descarga completa inicial; guárdalo\n"
                "# ... más tarde:\n"
                "for lote in g.sincronizar_desde(cursor):\n"
                "    aplicar(lote[\"cambios\"], lote[\"eliminados\"])\n"
                "    cursor = lote[\"cursor\"]                  # guarda el último; si lote[\"reiniciar\"], descarga todo otra vez"},
            {"type": "h2", "id": "typescript", "text": "TypeScript"},
            {"type": "code", "lang": "typescript", "code":
                "import { GuildaWork, ErrorGuilda, verificarFirmaWebhook } from \"./guilda-work\";\n\n"
                "const g = new GuildaWork({ token: process.env.GUILDA_TOKEN });\n"
                "const nota = await g.crearNota({ texto: \"Llamar al cliente\", referencia_externa: \"CRM-881\" });\n\n"
                "// Los argumentos de camino van primero, luego el cuerpo y luego la consulta\n"
                "await g.cambiarEstadoTarea(57, { estado: \"en_progreso\" });\n"
                "for await (const t of g.paginar((limit, offset) => g.listarTareasOutlook({ limit, offset }))) console.log(t.asunto);\n\n"
                "try { await g.obtenerNota(99999); } catch (e) { if (e instanceof ErrorGuilda && e.codigo === \"no_encontrado\") { /* ... */ } }"},
            {"type": "h2", "id": "webhooks-verificar", "text": "Verificar webhooks"},
            {"type": "p", "html":
                "Usa siempre el <b>cuerpo crudo</b> recibido y rechaza lo que tarde más de 5 minutos (<code>X-Guilda-Signature-V2</code> lleva marca de tiempo)."},
            {"type": "code", "lang": "python", "code":
                "if not verificar_firma_webhook(request.get_data(), request.headers, secreto):\n"
                "    return \"firma no válida\", 400"},
            {"type": "h2", "id": "postman", "text": "Postman"},
            {"type": "p", "html":
                "Importa el fichero (<b>Import → File</b>), abre la colección y rellena la variable <code>token</code> (o ejecuta <b>auth → login</b>, que la guarda solo). "
                "<code>base_url</code> ya apunta a esta instancia. Cada <code>POST</code> añade su <code>Idempotency-Key</code> y todas las peticiones un "
                "<code>X-Request-Id</code>; los parámetros opcionales vienen desactivados para activarlos con la casilla."},
            {"type": "callout", "kind": "info", "html":
                "<b>Versionado.</b> Los clientes llevan la versión de la API con la que se generaron (<code>VERSION_API</code>). Un cambio compatible solo añade métodos y campos "
                "opcionales; si alguna vez algo se rompe, la versión mayor sube y se avisa. Mientras tanto, un cliente antiguo sigue funcionando."},
        ],
    },
    {
        "slug": "cambios",
        "grupo": "INTEGRACIÓN",
        "titulo": "Registro de cambios",
        "descripcion": "Qué ha cambiado en la API en cada versión (cabecera X-API-Version).",
        "bloques": _bloques_cambios(),
    },
    {
        "slug": "webhooks",
        "grupo": "INTEGRACIÓN",
        "titulo": "Webhooks",
        "descripcion": "Recibe notificaciones en tiempo real de eventos en tu cuenta, firmadas con HMAC.",
        "bloques": [
            {"type": "badges", "items": ["HMAC-SHA256", "cola persistente", "6 intentos"]},
            {"type": "p", "html":
                "Los webhooks te avisan en el momento en que pasa algo relevante — una tarea que se finaliza, "
                "una cita que se reserva — en vez de tener que consultar la API periódicamente para ver si algo "
                "cambió."},
            {"type": "h2", "id": "configuracion", "text": "Configuración"},
            {"type": "p", "html":
                "Da de alta un webhook desde el <b>Backoffice</b> (sección «Webhooks») indicando la URL de "
                "destino y a qué eventos te suscribes, o por MCP con "
                "<code>webhooks_crear(url, eventos_suscritos, tenant=None)</code>. El <code>secreto</code> "
                "devuelto (para verificar la firma de cada entrega) <b>solo se enseña esa vez</b> — apúntalo, "
                "no se puede volver a leer después."},
            {"type": "code", "lang": "json", "code":
                '{\n'
                '  "id": 7,\n'
                '  "tenant_id": null,\n'
                '  "url": "https://tuservidor.com/webhooks/guilda",\n'
                '  "eventos": ["tarea.finalizada", "nota.creada"],\n'
                '  "secreto": "3f8a...solo-se-enseña-una-vez",\n'
                '  "activo": 1\n'
                "}"},
            {"type": "h2", "id": "payload", "text": "Formato del payload"},
            {"type": "code", "lang": "json", "code":
                '{\n'
                '  "id": "evt_1234",\n'
                '  "evento": "tarea.finalizada",\n'
                '  "fecha": "2026-10-10T09:30:00",\n'
                '  "datos": {\n'
                '    "tarea_id": 42,\n'
                '    "nombre": "Reunión de seguimiento",\n'
                '    "duracion_segundos": 2460\n'
                "  }\n"
                "}"},
            {"type": "h2", "id": "cabeceras", "text": "Cabeceras de cada entrega"},
            {"type": "table", "headers": ["Cabecera", "Contenido"], "rows": [
                ["<code>X-Guilda-Event</code>", "Nombre del evento, p. ej. <code>tarea.finalizada</code>."],
                ["<code>X-Guilda-Signature</code>", "<code>sha256=&lt;hex&gt;</code> — HMAC-SHA256 del cuerpo, ver abajo."],
                ["<code>X-Guilda-Signature-V2</code>", "<code>t=&lt;unix&gt;,v1=&lt;hex&gt;</code> — HMAC-SHA256 de <code>\"&lt;unix&gt;.\" + cuerpo</code>. <b>Recomendada</b>: comprueba que <code>t</code> no tenga más de 5 minutos para descartar entregas repetidas."],
                ["<code>X-Guilda-Timestamp</code>", "El mismo <code>&lt;unix&gt;</code> de la firma V2."],
                ["<code>X-Guilda-Delivery</code>", "Id de la entrega, igual en todos los reintentos del mismo evento: úsalo para descartar duplicados."],
            ]},
            {"type": "h2", "id": "verificar-firma", "text": "Verificar la firma"},
            {"type": "p", "html":
                "La firma es un HMAC-SHA256 calculado sobre el <b>cuerpo crudo</b> tal cual se envía, usando el "
                "<code>secreto</code> de ese webhook como clave — mismo esquema que GitHub/Stripe, no uno "
                "propio. Recalcúlala y compárala con <code>X-Guilda-Signature</code> antes de procesar el "
                "evento; hazlo siempre sobre el cuerpo recibido tal cual, nunca sobre un JSON reserializado (el "
                "orden de las claves o los espacios pueden cambiar, y la firma no coincidiría aunque el "
                "contenido sea «el mismo»)."},
            {"type": "code", "lang": "python", "code":
                "import hashlib\n"
                "import hmac\n\n"
                "def firma_valida(cuerpo_crudo: bytes, cabecera_recibida: str, secreto: str) -> bool:\n"
                '    esperada = "sha256=" + hmac.new(secreto.encode(), cuerpo_crudo, hashlib.sha256).hexdigest()\n'
                "    return hmac.compare_digest(cabecera_recibida, esperada)"},
            {"type": "h2", "id": "reintentos", "text": "Reintentos"},
            {"type": "p", "html":
                "Si tu endpoint no responde con un código <b>2xx</b> (o no contesta en 10 s), la entrega se reintenta hasta "
                "<b>6 veces</b> con espera creciente (inmediato, 30 s, 5 min, 30 min, 2 h, 12 h) antes de darla por fallida. "
                "Los envíos pendientes se guardan en una cola persistente: <b>un reinicio del servidor no los pierde</b>. "
                "La garantía es «al menos una vez», así que tu receptor debe tolerar duplicados "
                "(usa <code>X-Guilda-Delivery</code>). Cada intento queda registrado en el log de entregas del Backoffice, "
                "donde también puedes enviar un evento de prueba (<code>ping</code>) y reintentar a mano los fallidos."},
            {"type": "h2", "id": "eventos", "text": "Catálogo de eventos"},
            {"type": "table", "headers": ["Evento", "Se dispara cuando..."], "rows": [
                ["<code>tarea.finalizada</code>", "Se finaliza una tarea con duración (ver <a href=\"/docs/modelos-de-datos\">Modelos de datos</a>)."],
                ["<code>nota.creada</code>", "Se crea una nota — no se dispara al editarla, solo al crearla."],
                ["<code>cita.reservada</code>", "Se crea una reserva de Cal.diy vía <code>citas_crear_reserva</code>."],
                ["<code>correo.mensaje_nuevo</code>", "Una sincronización de correo trae mensajes nuevos (uno por sincronización con novedades, no uno por mensaje)."],
                ["<code>tarea.creada</code>", "Se crea una tarea de la lista (payload: <code>tarea_id</code>, <code>asunto</code>, <code>asignada_a</code>)."],
                ["<code>tarea.completada</code>", "Se completa una tarea de la lista, también desde el tablero o por quien la tiene asignada."],
                ["<code>tarea.asignada</code>", "Se asigna una tarea a un compañero del despacho (no al desasignarla)."],
                ["<code>correo.enviado</code>", "Sale un correo por SMTP (payload: cuenta, destinatarios y asunto; nunca el cuerpo)."],
                ["<code>nota.editada</code>", "Se edita una nota existente."],
                ["<code>vencimiento.presentado</code>", "Se marca como presentado un vencimiento del calendario fiscal."],
                ["<code>cliente.creado</code>", "Se da de alta un cliente fiscal (payload: <code>cliente_id</code>, <code>nombre</code>, <code>nif</code>)."],
                ["<code>correo.sin_respuesta</code>", "Un correo con «avísame si no responde» llega a su plazo sin respuesta."],
                ["<code>ping</code>", "Solo al pulsar «Enviar prueba» en el Backoffice."],
            ]},
            {"type": "callout", "kind": "info", "html":
                "Solo estos eventos de negocio concretos emiten un webhook — no hay un evento por cada "
                "escritura de <code>db.py</code>, sería ruido en el uso diario normal del registro de "
                "actividad."},
            {"type": "h2", "id": "gestion", "text": "Gestión por MCP"},
            {"type": "table", "headers": ["Tool", "Descripción"], "rows": [
                ["<code>webhooks_listar(tenant=None)</code>", "Lista los webhooks configurados (sin el secreto)."],
                ["<code>webhooks_crear(url, eventos_suscritos, tenant=None)</code>", "Da de alta un webhook nuevo."],
                ["<code>webhooks_borrar(webhook_id)</code>", "Borra un webhook (y su historial de entregas)."],
            ]},
        ],
    },
    {
        "slug": "asistente-ia",
        "grupo": "INTEGRACIÓN",
        "titulo": "Asistente de IA (MCP)",
        "descripcion": "Conecta Claude Code, Claude Desktop, Codex CLI o ChatGPT directamente contra tu instancia.",
        "bloques": [
            {"type": "badges", "items": ["stdio (local)", "streamable-http (remoto)", "OAuth 2.1 + DCR"]},
            {"type": "p", "html":
                "Guilda Work expone un servidor <b>MCP</b> (Model Context Protocol) con "
                f"<b>{TOTAL_TOOLS} tools</b> — el mismo catálogo, definido una sola vez en "
                "<code>mcp_tools.py</code>, servido por dos transportes distintos según qué cliente lo consuma."},
            {"type": "table", "headers": ["Servidor", "Transporte", "Para", "Autenticación"], "rows": [
                ["<code>mcp_server.py</code>", "stdio (proceso local)", "Claude Code, Claude Desktop, Codex CLI", "Ninguna — confianza del propio sistema operativo"],
                ["<code>mcp_server_remoto.py</code>", "streamable-http", "ChatGPT (solo admite MCP remoto)", "OAuth 2.1 + Registro Dinámico de Cliente, vía Ory Hydra"],
            ]},
            {"type": "h2", "id": "local", "text": "Conexión local — Claude Code, Claude Desktop, Codex CLI"},
            {"type": "p", "html":
                "<code>mcp_server.py</code> es un script aparte — <b>no se empaqueta en el <code>.exe</code></b> "
                "de escritorio — así que hace falta tener Python y las dependencias del servidor instaladas:"},
            {"type": "code", "lang": "bash", "code": "pip install -r requirements-mcp.txt"},
            {"type": "h2", "id": "claude-code", "text": "Claude Code"},
            {"type": "p", "html": "Desde la carpeta del proyecto:"},
            {"type": "code", "lang": "bash", "code": "claude mcp add guilda-work -- python mcp_server.py"},
            {"type": "p", "html":
                "En Windows, si tienes varios Python instalados (o el de <code>PATH</code> no es el del "
                "<code>.venv</code> del proyecto, que es donde está instalado el paquete <code>mcp</code>), usa "
                "la ruta absoluta del intérprete para evitar que <code>claude mcp add</code> resuelva a un "
                "Python sin la dependencia:"},
            {"type": "code", "lang": "powershell", "code":
                'claude mcp add guilda-work -- "C:\\ruta\\a\\tu\\instancia\\.venv\\Scripts\\python.exe" "C:\\ruta\\a\\tu\\instancia\\mcp_server.py"'},
            {"type": "p", "html":
                "Verifica que Claude Code lo ve con <code>claude mcp list</code> — debería aparecer "
                "<code>guilda-work</code> con estado conectado. Pídele algo simple como “lista mis proyectos” para "
                "confirmar de punta a punta."},
            {"type": "h2", "id": "codex-cli", "text": "Codex CLI"},
            {"type": "p", "html": "Añade en tu <code>config.toml</code> (o el equivalente que use tu instalación):"},
            {"type": "code", "lang": "toml", "code":
                "[mcp_servers.guilda-work]\n"
                'command = "python"\n'
                'args = ["mcp_server.py"]\n'
                'cwd = "/ruta/a/tu/instancia"'},
            {"type": "h2", "id": "claude-desktop", "text": "Claude Desktop"},
            {"type": "p", "html":
                "Entrada equivalente en su archivo de configuración de servidores MCP "
                "(<code>claude_desktop_config.json</code>):"},
            {"type": "code", "lang": "json", "code":
                '{\n'
                '  "mcpServers": {\n'
                '    "guilda-work": {\n'
                '      "command": "python",\n'
                '      "args": ["mcp_server.py"],\n'
                '      "cwd": "/ruta/a/tu/instancia"\n'
                "    }\n"
                "  }\n"
                "}"},
            {"type": "callout", "kind": "info", "html":
                "Los tres clientes locales comparten el mismo criterio de confianza: <code>mcp_server.py</code> "
                "corre como <code>stdio</code> sin autenticación propia — quien puede ejecutar el proceso ya "
                "tiene acceso al sistema donde vive. Para exponerlo a un cliente que no controlas tú (ChatGPT), "
                "hace falta el conector remoto de abajo, con autenticación real."},
            {"type": "h2", "id": "remoto", "text": "Conector remoto — ChatGPT"},
            {"type": "p", "html":
                "ChatGPT solo admite servidores MCP <b>remotos por HTTPS</b>, con OAuth 2.1 real — no hay forma de "
                "conectarlo al servidor local. <code>mcp_server_remoto.py</code> expone exactamente las mismas "
                f"{TOTAL_TOOLS} tools por <code>streamable-http</code>, delegando toda la autorización en Ory Hydra "
                "(ya desplegado como proveedor OAuth2 del resto del stack) — este proceso nunca gestiona logins ni "
                "emite tokens él mismo, solo valida cada token que llega contra la introspección de Hydra "
                "(<b>Resource Server</b>, no un Authorization Server propio)."},
            {"type": "steps", "items": [
                ("Instala las dependencias del servidor MCP",
                 "<code>pip install -r requirements-mcp.txt</code>, si no lo hiciste ya para el conector local."),
                ("Activa el Registro Dinámico de Cliente en Hydra",
                 "Ya está en <code>deploy/hydra/hydra.yml</code> "
                 "(<code>oidc.dynamic_client_registration.enabled: true</code>) — solo falta recrear el "
                 "contenedor para que lo recoja: <code>docker compose up -d --force-recreate hydra</code>."),
                ("Define las variables de entorno",
                 "<code>MCP_REMOTO_ORIGIN</code> (URL pública de este servidor), <code>HYDRA_PUBLIC_ORIGIN</code> "
                 "(URL pública de Hydra) y opcionalmente <code>MCP_REMOTO_PUERTO</code> (por defecto 8017) — ver "
                 "el ejemplo de abajo."),
                ("Publícalo detrás de Caddy",
                 "Ya está el bloque en <code>deploy/Caddyfile</code> "
                 "(<code>mcp.HOSTNAME { reverse_proxy localhost:8017 }</code>) — solo falta que Caddy recargue "
                 "la configuración."),
                ("Arráncalo como proceso persistente",
                 "Mismo patrón que el resto de la app fuera de Docker: copia "
                 "<code>deploy/guilda-work-mcp.service</code> a <code>/etc/systemd/system/</code>, ajusta "
                 "usuario/rutas, y <code>sudo systemctl enable --now guilda-work-mcp</code>."),
                ("Configura las variables de las herramientas que quieras exponer",
                 "Cada una es opcional por separado — ver <a href=\"/docs/variables-de-entorno\">Variables de "
                 "entorno</a> para la lista completa."),
                ("Verifica",
                 "<code>curl https://mcp.tu-hostname/.well-known/oauth-protected-resource</code> debe devolver "
                 "un JSON con <code>resource</code>/<code>authorization_servers</code> (RFC9728) — confirma que "
                 "el servidor sirve y anuncia Hydra como su autorización."),
            ]},
            {"type": "code", "lang": "bash", "code":
                "# .env / /etc/guilda-work.env\n"
                "MCP_REMOTO_ORIGIN=https://mcp.tu-hostname\n"
                "HYDRA_PUBLIC_ORIGIN=https://hydra.tu-hostname\n"
                "MCP_REMOTO_PUERTO=8017"},
            {"type": "p", "html":
                "La verificación completa (ChatGPT conectándose de verdad, flujo OAuth de punta a punta) solo se "
                "puede hacer añadiendo el conector desde <b>Ajustes → Conectores</b> de ChatGPT una vez todo lo "
                "de arriba esté desplegado — pégale la URL pública de <code>MCP_REMOTO_ORIGIN</code>."},
            {"type": "callout", "kind": "warn", "html":
                "Requiere el stack Docker + Hydra desplegados de verdad (DNS, registro dinámico de cliente "
                "activado...) — no aplica para uso puramente local. Ver "
                "<a href=\"/docs/autoalojamiento\">Autoalojamiento</a> para el despliegue base."},
            {"type": "h2", "id": "catalogo", "text": "Catálogo de tools"},
            {"type": "table", "headers": ["Grupo", "Tools", "Detalle"], "rows": [
                ["Propias de Guilda Work", str(TOOLS_PROPIAS), "Notas, tareas estilo Outlook, calendario, correo integrado, categorías de correo, firma, exportar/importar."],
                ["Stack compartido (sin <code>tenant</code>)", str(TOOLS_STACK_COMPARTIDO), "CRM, Drive, OpenProject, Soporte, Analítica, Automatizaciones, Documentación, Chat, Almacenamiento, Monitorización — instancia compartida entre todos los tenants, sin filtrado por tenant en estas tools."],
                ["Con parámetro <code>tenant</code> explícito", str(TOOLS_TENANT), "Ver tabla de familias abajo."],
            ]},
            {"type": "p", "html":
                "Las tools con <code>tenant</code> explícito existen porque, a diferencia del resto, el "
                f"aislamiento entre clientes de estas {NUM_FAMILIAS_TENANT} herramientas no lo da una instancia "
                "compartida con permisos, sino una instancia física propia, o un token/rol/cuenta propia por "
                "tenant — sin ese parámetro no habría forma de saber qué cliente debe ver cada dato. Ver "
                "<a href=\"/docs/aislamiento-multicliente\">Aislamiento multi-cliente</a> para el detalle de cada "
                "mecanismo."},
            {"type": "table", "headers": ["Herramienta", "Backend", "Tools"], "rows": [
                [etiqueta, backend, str(n)] for etiqueta, backend, n in _familias_tenant()
            ]},
            {"type": "cards", "items": [
                ("Catálogo completo de tools (MCP)", f"Las {TOTAL_TOOLS} tools una por una: nombre, parámetros con tipos y descripción.", "catalogo-tools-mcp"),
            ]},
            {"type": "h2", "id": "mcp-util", "text": "Respuestas acotadas, despacho por defecto, prompts y recursos"},
            {"type": "table", "headers": ["Qué", "Cómo funciona"], "rows": [
                ["Respuestas acotadas", "Un texto de más de <b>12 000 caracteres</b> se corta diciendo cuántos había en total, y un listado que pasa de <b>60 000</b> se corta con un último elemento <code>{\"_truncado\": true, \"total\": ..., \"mostrados\": ...}</code> para que el modelo pida un filtro o una página más pequeña (<code>GUILDA_MCP_MAX_TEXTO</code>, <code>GUILDA_MCP_MAX_CHARS</code>). <code>leer_correo</code> no devuelve el HTML salvo con <code>incluir_html=true</code>."],
                ["<code>tenant</code> opcional", "En las herramientas con <code>tenant</code> explícito el parámetro es opcional: si no lo indicas se usa <b>tu propio despacho</b>. Quien no tiene despacho (p. ej. un administrador global) debe nombrarlo; uno ajeno sigue vetado."],
                ["Prompts", "Cinco indicaciones listas para el cliente: <code>resumen_del_dia_prompt</code>, <code>ficha_cliente</code>, <code>preparar_vencimiento</code>, <code>revisar_correo</code> y <code>cierre_de_trimestre</code>. Solo nombran herramientas que existen (lo comprueba un test)."],
                ["Recursos", "Lecturas de solo lectura que el cliente puede adjuntar al contexto: <code>guilda://resumen-del-dia</code>, <code>guilda://proyectos</code>, <code>guilda://tareas/hoy</code>, <code>guilda://fiscal/clientes</code> y <code>guilda://consumo-ia</code>. Pasan por el mismo guardián que las herramientas (áreas, solo lectura, límites y auditoría) y solo existen si su herramienta está expuesta en el perfil."],
                ["Perfiles", "<code>GUILDA_MCP_GRUPOS=fiscal,correo</code> limita los grupos expuestos (el núcleo siempre entra) y <code>GUILDA_MCP_SOLO_LECTURA=1</code> deja solo las de lectura."],
            ]},
            {"type": "h2", "id": "busqueda-semantica", "text": "Búsqueda semántica (RAG)"},
            {"type": "p", "html":
                "<code>buscar_semantico(consulta, tenant=None)</code> no busca coincidencias de texto exacto — "
                "convierte la consulta en un vector con un modelo de embeddings local (Ollama) y devuelve las "
                "notas, tareas y mensajes de correo más parecidos por significado, aunque no compartan ni una "
                "palabra literal con la pregunta. Útil para preguntas del tipo “¿qué dije sobre el contrato de "
                "alquiler?” cuando no recuerdas si escribiste “alquiler”, “arrendamiento” o “renta”."},
            {"type": "code", "lang": "text", "code":
                'buscar_semantico(consulta="problemas de facturación con un cliente")\n'
                "→ encuentra notas que mencionan \"impago\", \"retraso en el cobro\" o \"factura pendiente\",\n"
                "  aunque ninguna contenga literalmente la palabra \"facturación\"."},
            {"type": "callout", "kind": "info", "html":
                "El índice vectorial vive en Meilisearch (campo <code>_vectors</code>, <code>userProvided</code>), "
                "reindexado por <code>scripts/reindexar_embeddings.py</code> — el aislamiento por tenant es el "
                "mismo que el resto de la búsqueda, nunca cruza datos entre clientes."},
            {"type": "h2", "id": "webhooks-mcp", "text": "Webhooks"},
            {"type": "p", "html":
                "Recibe una notificación HTTP en tiempo real cuando ocurre algo en tu cuenta (tarea finalizada, "
                "nota creada, cita reservada, correo nuevo), en vez de tener que preguntar por sondeo. Se gestionan "
                "con <code>webhooks_listar</code>/<code>webhooks_crear</code>/<code>webhooks_borrar</code> — ver "
                "<a href=\"/docs/webhooks\">Webhooks</a> para el formato del payload, la firma HMAC y el catálogo "
                "completo de eventos."},
            {"type": "callout", "kind": "danger", "html":
                "<b>Las tareas <i>con duración</i> (iniciar/pausar/reanudar/finalizar, la función central del "
                "registro de actividad) NO tienen tools de MCP</b> — <code>listar_tareas</code>/<code>crear_tarea</code>/"
                "<code>editar_tarea</code>/<code>completar_tarea</code>/<code>consultar_calendario</code> operan "
                "sobre las <b>tareas estilo Outlook</b> (independientes, sin cronómetro), no sobre las de "
                "duración. Un asistente de IA puede leer y exportar el histórico de tareas con duración "
                "(<code>exportar_historial</code>/<code>importar_historial</code>), pero no puede arrancar, "
                "pausar ni finalizar una — eso hoy solo se hace desde la app web o la API REST "
                "(<code>POST /api/v1/tareas</code> crea y arranca directamente; "
                "<code>POST /api/v1/tareas/{id}/pausar|reanudar|finalizar</code> controla el resto del ciclo de "
                "vida, ver <a href=\"/docs/referencia-api#tareas\">Referencia de la API</a>). Ver "
                "<a href=\"/docs/modelos-de-datos\">Modelos de datos</a> para la diferencia completa entre ambos "
                "tipos de tarea."},
            {"type": "callout", "kind": "info", "html":
                "<b>Enviar correo es la única acción de dos pasos a propósito</b>, tanto en el correo integrado "
                "como en el resto: una tool prepara/previsualiza, otra distinta confirma y envía de verdad — "
                "instruye a tu asistente para que te enseñe el contenido antes de llamar a la segunda. El "
                "<code>bcc</code> nunca viaja como cabecera visible del mensaje enviado."},
            {"type": "callout", "kind": "danger", "html":
                "Vaultwarden (el gestor de contraseñas) queda <b>excluido a propósito, bajo ningún concepto</b>, "
                "de todo esto — no tiene tools, ni variable de entorno, ni forma de activarlo por MCP."},
        ],
    },
    {
        "slug": "catalogo-tools-mcp",
        "grupo": "INTEGRACIÓN",
        "titulo": "Catálogo completo de tools (MCP)",
        "descripcion": f"Las {TOTAL_TOOLS} tools de mcp_tools.py, una por una: nombre, parámetros con tipos y descripción.",
        "bloques": [
            {"type": "p", "html":
                "Generado a partir del propio código de <code>mcp_tools.py</code> (firma real vía "
                "<code>inspect.signature()</code> + primera línea del docstring de cada función) — nunca se "
                "desincroniza de lo que de verdad expone el servidor MCP. Usa <kbd>Ctrl</kbd>+<kbd>K</kbd> para "
                "buscar una tool por nombre."},
            {"type": "h2", "id": "uso-y-limites", "text": "Credenciales, límites y auditoría"},
            {"type": "p", "html":
                "El servidor MCP remoto acepta un <b>token OAuth</b> (ChatGPT, Claude...) o un <b>token personal de API</b> "
                "(<code>Authorization: Bearer ...</code>), que hereda sus <code>areas</code> y su solo lectura: una herramienta fuera de ese "
                "alcance responde con un error claro y nunca se ejecuta. Cada herramienta lleva anotaciones MCP (solo lectura, destructiva, "
                "idempotente, mundo abierto) para que el cliente sepa qué pedir confirmar."},
            {"type": "table", "headers": ["Control", "Cómo funciona"], "rows": [
                ["Límite por persona", "<b>120 llamadas por minuto</b> y <b>40 de escritura por minuto</b> (<code>GUILDA_MCP_LIMITE_POR_MINUTO</code>, <code>GUILDA_MCP_LIMITE_ESCRITURAS_POR_MINUTO</code>). Al pasarte la herramienta devuelve un error con los segundos de espera; la llamada rechazada no se ejecuta ni gasta cupo."],
                ["Uso por token", "Las llamadas por MCP suman al uso del token personal (<code>GET /tokens/{id}/uso</code>)."],
                ["Auditoría", "Cada llamada queda registrada 90 días: quién, con qué cliente, qué herramienta, resultado (<code>ok</code>, <code>error</code>, <code>denegado</code>, <code>limite</code>), duración y la <b>forma</b> de los argumentos (números y ids tal cual; de un texto, solo su longitud). Nunca se guarda el contenido de correos, notas o documentos."],
            ]},
            {"type": "h2", "id": "propias", "text": "Propias de Guilda Work"},
            {"type": "table", "headers": ["Tool", "Descripción"], "rows": _filas_tools_por_nombre(_PROPIAS_GUILDA_WORK)},
            {"type": "h2", "id": "stack-compartido", "text": "Stack compartido (sin tenant)"},
            *[
                bloque
                for prefijo, etiqueta in _GRUPOS_STACK_COMPARTIDO
                for bloque in (
                    {"type": "h2", "id": f"grupo-{prefijo.strip('_')}", "text": etiqueta},
                    {"type": "table", "headers": ["Tool", "Descripción"], "rows": _filas_tools_por_prefijo(prefijo)},
                )
            ],
            {"type": "h2", "id": "con-tenant", "text": "Con parámetro tenant explícito"},
            {"type": "p", "html":
                "El primer parámetro <code>tenant</code> es siempre el <b>nombre</b> del tenant tal y como está "
                "dado de alta en el backoffice (no su id numérico) — ver "
                "<a href=\"/docs/aislamiento-multicliente\">Aislamiento multi-cliente</a>."},
            *[
                bloque
                for prefijo, etiqueta in _GRUPOS_TENANT
                for bloque in (
                    {"type": "h2", "id": f"grupo-{prefijo.strip('_')}", "text": etiqueta},
                    {"type": "table", "headers": ["Tool", "Descripción"], "rows": _filas_tools_por_prefijo(prefijo)},
                )
            ],
        ],
    },
    {
        "slug": "aislamiento-multicliente",
        "grupo": "INTEGRACIÓN",
        "titulo": "Aislamiento multi-cliente",
        "descripcion": "Cómo se garantiza que los datos de un tenant nunca los vea otro.",
        "bloques": [
            {"type": "p", "html":
                "Guilda Work es multi-tenant: cada cliente (<b>tenant</b>) tiene sus propios usuarios, y sus datos "
                "nunca son visibles para otro — tanto en el registro de actividad propio como en cada una de las "
                "herramientas conectadas del catálogo. No es una convención de interfaz: cada mecanismo de "
                "aislamiento se ha verificado contra la herramienta real antes de darlo por bueno."},
            {"type": "h2", "id": "patrones", "text": "Patrones de aislamiento usados"},
            {"type": "table", "headers": ["Patrón", "Herramientas", "Cómo funciona"], "rows": [
                ["Instancia compartida + grupo/rol OIDC", "EspoCRM, Nextcloud, Paperless-ngx",
                 "Un único despliegue para todos los tenants; el login SSO mapea el Equipo/Grupo/Rol del usuario según su tenant, y la propia herramienta filtra por ese grupo."],
                ["Instancia física propia por tenant", "FacturaScripts",
                 "Cada tenant tiene su propio contenedor + base de datos — el único caso sin aislamiento lógico posible (el plugin de multiempresa disponible no restringe accesos)."],
                ["Instancia compartida + token/rol por tenant", "Documenso, Baserow, Listmonk",
                 "Un despliegue compartido; cada tenant tiene su propio token de API o rol con permisos restringidos a sus propios recursos (Equipo/Workspace/Lista según la herramienta)."],
                ["Instancia compartida + cuenta individual", "Cal.diy",
                 "Sin Equipos/SSO en su edición libre — cada tenant tiene su propia cuenta de usuario dentro de la instancia compartida."],
                ["Instancia compartida + Tenant/Domain/Account", "Stalwart (correo propio)",
                 "Objetos JMAP <code>Tenant</code>/<code>Domain</code>/<code>Account</code> nativos del servidor de correo — verificado en vivo que cruzar el <code>accountId</code> de otro tenant devuelve un <code>403 forbidden</code> real del servidor, no un filtro de cliente."],
            ]},
            {"type": "h2", "id": "alta-de-tenant", "text": "Dar de alta un cliente nuevo"},
            {"type": "p", "html":
                "Un solo paso desde el backoffice (o <code>python cli.py crear-tenant</code>): el sistema prepara "
                "automáticamente el espacio del tenant en cada herramienta conectada que tenga aprovisionamiento "
                "automático — sin configuración manual añadida, salvo un puñado de pasos que por diseño de la "
                "propia herramienta externa no se pueden hacer por API (p. ej. la clave de API de FacturaScripts "
                "se genera a mano una única vez, no hay endpoint para ello). El backoffice también permite "
                "asignar usuarios existentes a un tenant y dar de alta a personas nuevas directamente dentro de "
                "uno."},
            {"type": "callout", "kind": "info", "html":
                "El gestor de contraseñas (Vaultwarden) queda <b>excluido a propósito</b> de todo el sistema de "
                "aprovisionamiento e IA — es de uso exclusivamente humano, nunca accesible por ninguna "
                "automatización ni tool de MCP."},
        ],
    },
    {
        "slug": "variables-de-entorno",
        "grupo": "CONFIGURACIÓN",
        "titulo": "Variables de entorno",
        "descripcion": "Qué variable activa cada pieza — app, MCP remoto, herramientas conectadas.",
        "bloques": [
            {"type": "p", "html":
                "Cada herramienta conectada es opcional por separado: sin su variable configurada, las tools de "
                "solo lectura de esa herramienta devuelven una lista vacía y las de escritura fallan con un "
                "mensaje claro — sin tumbar el resto del servidor. Esta página cubre las variables de la app y "
                "del servidor MCP; las de despliegue de cada pieza del stack Docker (contraseñas de base de "
                "datos, orígenes públicos...) están documentadas herramienta por herramienta en la guía de "
                "autoalojamiento."},
            {"type": "h2", "id": "app", "text": "La app en sí"},
            {"type": "table", "headers": ["Variable", "Para qué"], "rows": [
                ["<code>GUILDA_SECRET_KEY</code>", "Firma las cookies de sesión Flask — genera un valor real en producción (<code>python -c \"import secrets; print(secrets.token_hex(32))\"</code>), nunca dejes que se genere uno aleatorio en cada arranque."],
                ["<code>GUILDA_HOST</code>", "Interfaz donde escucha <code>serve.py</code> — <code>127.0.0.1</code> en producción (Caddy hace de proxy inverso delante), no <code>0.0.0.0</code>."],
                ["<code>GUILDA_PORT</code>", "Puerto interno del proceso Flask (por defecto 8000)."],
            ]},
            {"type": "h2", "id": "mcp-remoto", "text": "Servidor MCP remoto (ChatGPT)"},
            {"type": "table", "headers": ["Variable", "Para qué"], "rows": [
                ["<code>MCP_REMOTO_ORIGIN</code>", "URL pública de <code>mcp_server_remoto.py</code> — el identificador que ChatGPT compara contra el token recibido (RFC8707)."],
                ["<code>HYDRA_PUBLIC_ORIGIN</code>", "URL pública de Ory Hydra — el <code>issuer_url</code> que ChatGPT descubre y usa para el registro dinámico de cliente y el login real."],
                ["<code>MCP_REMOTO_PUERTO</code>", "Puerto donde escucha el proceso (por defecto 8017) — Caddy le hace de proxy inverso, nunca se publica directo a internet."],
            ]},
            {"type": "table", "headers": ["Variable", "Para qué"], "rows": [
                ["<code>MCP_REMOTO_CLIENTES</code>", "Nombres de clientes OAuth que pueden usar el MCP además de los que pasan por la pantalla de consentimiento (por defecto <code>claude-desktop</code>)."],
                ["<code>GUILDA_MCP_GRUPOS</code>, <code>GUILDA_MCP_SOLO_LECTURA</code>", "Perfil del servidor MCP: grupos de herramientas expuestos y modo solo lectura."],
                ["<code>GUILDA_MCP_LIMITE_POR_MINUTO</code>, <code>GUILDA_MCP_LIMITE_ESCRITURAS_POR_MINUTO</code>", "Límites por persona (120 y 40 por defecto)."],
                ["<code>GUILDA_MCP_MAX_TEXTO</code>, <code>GUILDA_MCP_MAX_CHARS</code>", "Tamaño máximo de un texto (12 000) y de un listado (60 000) en las respuestas del MCP."],
            ]},
            {"type": "h2", "id": "api-y-ayuda", "text": "API y ayuda"},
            {"type": "table", "headers": ["Variable", "Para qué"], "rows": [
                ["<code>GUILDA_API_LIMITE_POR_MINUTO</code>", "Peticiones por minuto y persona en <code>/api/v1</code> (600 por defecto)."],
                ["<code>GUILDA_API_LIMITE_ESCRITURAS_POR_MINUTO</code>, <code>GUILDA_API_LIMITE_PESADAS_POR_MINUTO</code>", "Cupos propios de las escrituras (200) y de las operaciones pesadas (20) por minuto y persona."],
                ["<code>GUILDA_LIMITER_URI</code>", "Almacén de los límites de uso (en memoria por defecto; con varios procesos, Redis)."],
                ["<code>GUILDA_FICHAJE_AVISO_HORAS</code>", "Horas de jornada abierta tras las que se avisa de una salida olvidada."],
                ["<code>GUILDA_FIREBASE_CREDENTIALS_PATH</code>", "Ruta al JSON de cuenta de servicio de Firebase para las notificaciones push a la app móvil. Sin ella, el push queda desactivado (las notificaciones dentro de la app siguen funcionando)."],
                ["<code>GUILDA_CSP</code>", "Política de contenido de la app web: <code>reportar</code> (por defecto: el navegador avisa a <code>/csp-report</code> de lo que bloquearía, sin bloquear), <code>forzar</code> (bloquea los scripts que no sean del sitio ni lleven el nonce de la petición) o <code>no</code>."],
                ["<code>GUILDA_AYUDA_URL</code>", "Dirección del centro de ayuda a la que enlaza cada pantalla (por defecto <code>https://help.guildawork.com</code>)."],
            ]},
            {"type": "h2", "id": "herramientas", "text": "Herramientas conectadas (MCP y backoffice)"},
            {"type": "p", "html":
                "Cada tool de MCP que toca el stack compartido (sin <code>tenant</code>, ver "
                "<a href=\"/docs/asistente-ia\">Asistente de IA (MCP)</a>) necesita el token de API de esa "
                "herramienta:"},
            {"type": "table", "headers": ["Variable", "Herramienta", "Nota"], "rows": [
                ["<code>ESPOCRM_API_KEY</code>", "EspoCRM (CRM)", ""],
                ["<code>NEXTCLOUD_ADMIN_USER</code> / <code>_PASSWORD</code>", "Nextcloud (Drive)", ""],
                ["<code>OPENPROJECT_API_TOKEN</code>", "OpenProject (gestión de proyectos de equipo)", ""],
                ["<code>CHATWOOT_AGENT_API_TOKEN</code>", "Chatwoot (Soporte)", "Token de un <b>agente normal</b> (su perfil → Ajustes de acceso a la API) — distinto de <code>CHATWOOT_PLATFORM_API_TOKEN</code>, que solo gestiona altas de usuarios."],
                ["<code>METABASE_API_KEY</code>", "Metabase (Analítica)", ""],
                ["<code>N8N_API_KEY</code>", "n8n (Automatizaciones)", ""],
                ["<code>OUTLINE_API_TOKEN</code>", "Outline (Documentación)", ""],
                ["<code>SYNAPSE_BOT_ACCESS_TOKEN</code>", "Synapse/Matrix (Chat)", "Token de un usuario «bot» dedicado (créalo con <code>register_new_matrix_user</code> dentro del contenedor) — nunca reutilices el token de una persona real."],
                ["<code>MINIO_ROOT_PASSWORD</code>", "MinIO (Almacenamiento)", ""],
                ["<code>UPTIME_KUMA_API_KEY</code>", "Uptime Kuma (Monitorización)", ""],
            ]},
            {"type": "p", "html":
                f"Las {NUM_FAMILIAS_TENANT} herramientas con parámetro <code>tenant</code> explícito no usan una "
                "única variable global — su credencial se genera y guarda automáticamente por tenant al "
                "aprovisionarlo (backoffice o <code>cli.py crear-tenant</code>), salvo el puñado de pasos manuales "
                "documentados en la guía de autoalojamiento para cada una."},
            {"type": "callout", "kind": "danger", "html":
                "No hay ninguna variable para Vaultwarden en esta lista, a propósito — queda excluido del MCP "
                "bajo cualquier circunstancia."},
        ],
    },
    {
        "slug": "desarrollo-local",
        "grupo": "DESPLIEGUE",
        "titulo": "Desarrollo local",
        "descripcion": "Clona el proyecto y levanta tu propio entorno de pruebas.",
        "bloques": [
            {"type": "p", "html":
                "Guilda Work es una app Flask + SQLite (Python 3.11+), sin dependencias obligatorias de "
                "infraestructura para el modo de escritorio — el modo hospedado (multi-tenant, SSO, herramientas "
                "conectadas) sí necesita el stack Docker completo, ver <a href=\"/docs/autoalojamiento\">Autoalojamiento</a>."},
            {"type": "steps", "items": [
                ("Entorno virtual y dependencias",
                 "<code>python -m venv .venv</code>, actívalo, y <code>pip install -r requirements.txt</code>."),
                ("Arranca la app", "<code>python run.py</code> — crea <code>data/registro.db</code> la primera vez, sin pasos previos. Abre una ventana nativa (WebView2), no un navegador."),
                ("Ejecuta los tests", "<code>pip install -r requirements-dev.txt && pytest</code> — cada módulo de integración externa mockea su cliente HTTP de bajo nivel; ningún test toca <code>data/registro.db</code> ni depende de un contenedor real, cada uno usa su propia base de datos temporal."),
            ]},
            {"type": "code", "lang": "bash", "code":
                "python -m venv .venv\n"
                "source .venv/bin/activate  # .venv\\Scripts\\activate en Windows\n"
                "pip install -r requirements.txt\n"
                "python run.py"},
            {"type": "h2", "id": "estructura", "text": "Estructura del proyecto"},
            {"type": "code", "lang": "text", "code":
                "app/\n"
                "  main.py         # rutas Flask + arranque de la ventana nativa (pywebview)\n"
                "  db.py           # esquema y acceso a SQLite\n"
                "  export.py       # exportación a JSON/CSV/Markdown + resumen automático nocturno\n"
                "  importador.py   # importación de JSON/CSV de vuelta a la base\n"
                "  ai_local.py     # integración con Ollama / LM Studio\n"
                "  rutas_api.py    # API REST con token (ver Referencia de la API)\n"
                "  rutas_docs.py   # esta misma Guía para desarrolladores\n"
                "  rutas_tareas.py # blueprint de la pestaña Tareas (lista + calendario estilo Outlook)\n"
                "  rutas_correo.py # blueprint del cliente de correo IMAP/POP3/SMTP\n"
                "  correo.py       # lógica de correo (conexión, sincronización, envío HTML)\n"
                "  templates/      # HTML (Jinja2)\n"
                "  static/         # CSS/JS, logo.png, favicon.ico\n"
                "data/\n"
                "  registro.db     # se crea automáticamente\n"
                "  backups/        # copias diarias automáticas\n"
                "exports/auto/     # resúmenes automáticos nocturnos (Markdown)\n"
                "tests/            # pytest\n"
                "run.py            # punto de entrada (arranca el servidor + la ventana)\n"
                "cli.py            # acceso a los datos por línea de comandos, sin servidor\n"
                "mcp_server.py         # servidor MCP local (stdio) para Claude/Codex\n"
                "mcp_server_remoto.py  # servidor MCP remoto (streamable-http + OAuth2) para ChatGPT\n"
                "requirements.txt      # dependencias para ejecutar la app\n"
                "requirements-dev.txt  # + pytest\n"
                "requirements-mcp.txt  # + mcp, solo para los servidores MCP"},
            {"type": "h2", "id": "cli", "text": "Leer los datos sin arrancar la app"},
            {"type": "p", "html":
                "<code>cli.py</code> es de solo lectura y no requiere que la app esté corriendo — útil para "
                "scripts o para que un agente de IA con acceso a la carpeta consulte el histórico directamente:"},
            {"type": "code", "lang": "bash", "code":
                "python cli.py menus\n"
                "python cli.py export --formato json --desde 2026-07-01 --hasta 2026-07-31\n"
                "python cli.py demo    # datos de ejemplo para pruebas/demos\n"
                "python cli.py backup  # fuerza una copia de seguridad ahora mismo"},
            {"type": "p", "html":
                "También puedes leer <code>data/registro.db</code> directamente con <code>sqlite3</code> "
                "(esquema en <code>app/db.py</code>) para consultas que la CLI no cubra."},
            {"type": "h2", "id": "mcp-local", "text": "Servidor MCP en desarrollo"},
            {"type": "code", "lang": "bash", "code":
                "pip install -r requirements-mcp.txt\n"
                "claude mcp add guilda-work-dev -- python mcp_server.py"},
            {"type": "callout", "kind": "info", "html":
                "El paquete <code>mcp</code> vive en un <code>requirements-mcp.txt</code> aparte a propósito — "
                "la app de escritorio empaquetada con PyInstaller no lo necesita, y así el <code>.exe</code> no "
                "carga una dependencia que la mayoría de usuarios nunca usa."},
            {"type": "h2", "id": "exe", "text": "Generar el .exe de escritorio (Windows)"},
            {"type": "code", "lang": "bash", "code":
                'pyinstaller --onefile --windowed --name "GuildaWork" ^\n'
                '  --icon "assets/icon.ico" ^\n'
                '  --add-data "app/templates;app/templates" ^\n'
                '  --add-data "app/static;app/static" ^\n'
                "  run.py"},
            {"type": "p", "html":
                "El ejecutable queda en <code>dist/GuildaWork.exe</code>. La primera vez que se ejecuta crea "
                "<code>data/registro.db</code> junto al propio <code>.exe</code> (no en una carpeta temporal), "
                "así que los datos persisten entre ejecuciones aunque lo muevas de sitio — llévate la carpeta "
                "<code>data/</code> con él si lo haces. Este modo no pasa por MCP ni por la API REST multi-tenant: "
                "es un único usuario local de confianza, sin pantalla de login."},
        ],
    },
    {
        "slug": "autoalojamiento",
        "grupo": "DESPLIEGUE",
        "titulo": "Autoalojamiento",
        "descripcion": "Despliega tu propia instancia en un VPS con Docker + Caddy.",
        "bloques": [
            {"type": "p", "html":
                f"El modo hospedado añade multi-tenant real, SSO (Ory Kratos/Hydra) y el catálogo completo de "
                f"{TOTAL_TOOLS - TOOLS_PROPIAS} herramientas conectadas del stack Docker — todo autoalojado, sin "
                "servicios de terceros de por medio."},
            {"type": "h2", "id": "proveedor", "text": "Elegir proveedor"},
            {"type": "table", "headers": ["Proveedor", "Precio aprox./mes", "Notas"], "rows": [
                ["Hetzner Cloud (CX22)", "~4,5 €", "Mejor relación calidad/precio, datacenters en Alemania/Finlandia — recomendación por defecto."],
                ["Contabo", "~4-5 €", "Más RAM/disco por el precio, rendimiento algo más variable."],
                ["DigitalOcean", "~6 $", "Muy bien documentado, buena opción si es tu primer VPS."],
                ["Oracle Cloud «Always Free»", "Gratis", "4 núcleos ARM + 24GB RAM gratis para siempre, pero el alta de cuenta es errática."],
            ]},
            {"type": "p", "html":
                "Para el uso de esta app (un solo backend Flask + SQLite, tráfico bajo) sobra la oferta más "
                "pequeña de cualquiera: 1 vCPU / 1-2GB RAM, Ubuntu 22.04 o 24.04 LTS."},
            {"type": "h2", "id": "piezas", "text": "Piezas del stack"},
            {"type": "table", "headers": ["Pieza", "Rol"], "rows": [
                ["<code>docker-compose.yml</code>", "Todos los servicios conectados — una imagen oficial por herramienta, sin forks propios."],
                ["Caddy", "Único punto de entrada real desde internet, HTTPS automático (Let's Encrypt), proxy inverso a cada servicio por subdominio."],
                ["Ory Kratos / Hydra", "Identidad (login/registro) y proveedor OAuth2 para el SSO de las herramientas que lo soportan, y para el conector MCP remoto."],
                ["Ollama", "Modelo de embeddings local, usado por la búsqueda semántica (<code>buscar_semantico</code>) — ver <a href=\"/docs/asistente-ia#busqueda-semantica\">Búsqueda semántica (RAG)</a>."],
                ["<code>serve.py</code>", "El proceso de Guilda Work en sí, fuera de Docker, en el mismo host — gestionado por <code>systemd</code> para que arranque solo y se reinicie si muere."],
            ]},
            {"type": "callout", "kind": "warn", "html":
                "Excepciones explícitas a «todo detrás de Caddy en 443»: SSH, OpenVPN y los puertos de correo "
                "real de Stalwart (SMTP/IMAP/POP3) se publican directamente — no son HTTP, Caddy no puede "
                "hacerles de proxy."},
            {"type": "h2", "id": "hardening", "text": "Acceso y hardening básico"},
            {"type": "p", "html":
                "Usuario propio sin privilegios de root para el día a día (con <code>sudo</code> cuando haga "
                "falta), cortafuegos limitado a SSH/HTTP/HTTPS, y login SSH solo por clave (nunca por "
                "contraseña) una vez confirmado que tu clave ya está copiada al servidor."},
            {"type": "code", "lang": "bash", "code":
                "adduser guilda\n"
                "usermod -aG sudo guilda\n"
                "ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw enable\n"
                "# Copia tu clave ANTES de desactivar el login por contraseña:\n"
                "ssh-copy-id -i ~/.ssh/id_ed25519.pub guilda@TU_IP"},
            {"type": "h2", "id": "hostname", "text": "Hostname sin dominio propio"},
            {"type": "p", "html":
                "Sin comprar un dominio todavía, <a href=\"https://sslip.io\" target=\"_blank\" "
                "rel=\"noopener\">sslip.io</a> da un hostname que resuelve automáticamente a la IP de tu "
                "servidor (<code>203.0.113.10</code> → <code>203-0-113-10.sslip.io</code>), suficiente para que "
                "Caddy pida un certificado real. Cuando compres un dominio, migrar es cuestión de apuntar sus "
                "registros DNS a la misma IP y actualizar los orígenes públicos (<code>*_PUBLIC_ORIGIN</code>) "
                "en tu <code>.env</code> — el resto del stack no cambia."},
            {"type": "h2", "id": "guia-completa", "text": "Guía completa de despliegue"},
            {"type": "p", "html":
                "El paso a paso detallado de cada pieza — variables de entorno completas, orden de arranque, "
                "registro de clientes OAuth2, backups, y una sección por cada una de las herramientas conectadas "
                "con su modelo de aislamiento documentado (y, cuando aplica, verificado en vivo contra un "
                "contenedor real antes de darlo por bueno) — vive en <code>HOSTING.md</code>, en la raíz del "
                "repositorio."},
            {"type": "p", "html":
                "El modo hospedado también es lo que activa la búsqueda semántica y las notificaciones salientes "
                "— ninguna de las dos depende de un servicio nuevo que desplegar aparte:"},
            {"type": "cards", "items": [
                ("Búsqueda semántica (RAG)", "Encuentra por significado, no por texto exacto — necesita Ollama, ya listado arriba.", "asistente-ia"),
                ("Webhooks", "Notifica a una URL externa en tiempo real cuando pasa algo, firmado con HMAC.", "webhooks"),
                ("Explorador de API interactivo", "Endpoints filtrables generados en el navegador desde el OpenAPI real, sin configuración adicional.", "explorador-api"),
            ]},
            {"type": "callout", "kind": "info", "html":
                "Cada aviso de reputación (p. ej. montar correo saliente propio con Stalwart) está documentado "
                "explícitamente donde aplica — no es un problema de la integración, es inherente a autoalojar "
                "ese tipo de servicio."},
        ],
    },
]

_POR_SLUG = {p["slug"]: p for p in PAGINAS}


def obtener_pagina(slug: str) -> dict | None:
    return _POR_SLUG.get(slug)


def navegacion() -> list[tuple[str, list[dict]]]:
    """Agrupa las páginas (menos la portada) por su `grupo`, en el orden en
    que aparecen en PAGINAS, para pintar el árbol de navegación lateral."""
    grupos: list[tuple[str, list[dict]]] = []
    indice = {}
    for pagina in PAGINAS:
        grupo = pagina["grupo"]
        if grupo is None:
            continue
        if grupo not in indice:
            indice[grupo] = []
            grupos.append((grupo, indice[grupo]))
        indice[grupo].append(pagina)
    return grupos


def pagina_adyacente(slug: str) -> tuple[dict | None, dict | None]:
    """(anterior, siguiente) de `slug` en el mismo orden plano que ya
    pinta la barra lateral (`navegacion()`, grupos en el orden de
    `PAGINAS`) — la portada (`grupo is None`) no entra en esta
    secuencia, ni aparece nunca como anterior/siguiente de nadie."""
    orden = [p for _, paginas in navegacion() for p in paginas]
    indices = [i for i, p in enumerate(orden) if p["slug"] == slug]
    if not indices:
        return None, None
    i = indices[0]
    anterior = orden[i - 1] if i > 0 else None
    siguiente = orden[i + 1] if i < len(orden) - 1 else None
    return anterior, siguiente


_QUITA_ETIQUETAS = re.compile(r"<[^>]+>")


def _texto_plano(html: str) -> str:
    return _QUITA_ETIQUETAS.sub("", html).strip()


def indice_busqueda() -> list[dict]:
    """Índice plano para el buscador (Ctrl/Cmd+K) — una entrada por página
    (título + descripción) y una por sección `h2` (título de la página +
    de la sección, con un fragmento del texto que sigue). Se sirve
    embebido en cada página (ver app/templates/docs/pagina.html), no por
    una ruta JSON aparte — con ~10 páginas no compensa la complejidad de
    una petición extra."""
    entradas = []
    for pagina in PAGINAS:
        href = f"/docs/{pagina['slug']}" if pagina["slug"] else "/docs/"
        grupo = pagina["grupo"] or ""
        entradas.append({
            "titulo": pagina["titulo"],
            "contexto": grupo,
            "texto": pagina["descripcion"],
            "href": href,
        })

        titulo_seccion = None
        id_seccion = None
        texto_acumulado = []

        def _cerrar_seccion():
            if titulo_seccion is None:
                return
            fragmento = " ".join(texto_acumulado).strip()
            entradas.append({
                "titulo": titulo_seccion,
                "contexto": pagina["titulo"],
                "texto": fragmento[:200],
                "href": f"{href}#{id_seccion}",
            })

        for bloque in pagina["bloques"]:
            if bloque["type"] == "h2":
                _cerrar_seccion()
                titulo_seccion = bloque["text"]
                id_seccion = bloque["id"]
                texto_acumulado = []
            elif bloque["type"] in ("p", "callout") and titulo_seccion is not None:
                texto_acumulado.append(_texto_plano(bloque["html"]))
        _cerrar_seccion()

    return entradas
