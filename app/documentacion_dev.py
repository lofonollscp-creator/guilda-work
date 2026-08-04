"""Contenido de la Guía para desarrolladores (`/docs`, ver
`app/rutas_docs.py`), la documentación técnica pública para quien quiera
integrar su propio software con una instancia de Guilda Work — por API
REST o conectando un asistente de IA por MCP — o desplegar/extender el
propio proyecto.

Es contenido, no HTML: cada página es una lista de "bloques" (`p`,
`h2`, `callout`, `code`, `steps`, `table`, `cards`) que
`app/templates/docs/pagina.html` renderiza de forma genérica — así
añadir o reordenar contenido no toca la plantilla ni el CSS.

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
    "listar_cuentas_correo", "sincronizar_correo", "listar_carpetas_correo", "listar_bandeja_entrada",
    "leer_correo", "marcar_leido_correo", "eliminar_correo",
    "listar_categorias_correo", "crear_categoria_correo", "eliminar_categoria_correo", "asignar_categoria_correo",
    "obtener_firma_correo", "configurar_firma_correo",
    "preparar_borrador_correo", "enviar_borrador_correo",
    "exportar_historial", "importar_historial", "exportar_tareas", "importar_tareas",
    "buscar_semantico",
    "webhooks_listar", "webhooks_crear", "webhooks_borrar",
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
    ("proyectos_", "Proyectos (OpenProject)"),
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

PAGINAS = [
    {
        "slug": "",
        "grupo": None,
        "titulo": "Guía para desarrolladores",
        "descripcion": "Integra tu propio software con una instancia de Guilda Work por API REST, "
                        "conecta un asistente de IA por MCP, o despliega/extiende el propio proyecto.",
        "bloques": [
            {"type": "h2", "id": "empezar", "text": "Empezar"},
            {"type": "cards", "items": [
                ("Autenticación", "Consigue un token de API y autentica tus peticiones.", "autenticacion"),
                ("Primera llamada a la API", "Crea tu primera nota vía la API REST.", "primera-llamada"),
            ]},
            {"type": "h2", "id": "opciones", "text": "Opciones de integración"},
            {"type": "cards", "items": [
                ("Referencia de la API", "Todos los endpoints REST, agrupados por recurso.", "referencia-api"),
                ("Modelos de datos", "La forma exacta de cada objeto: campos, tipos y notas.", "modelos-de-datos"),
                ("Ejemplos", "Recetas completas: curl, Python y JavaScript.", "ejemplos"),
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
                ("Crea un menú (categoría)", "Las notas y tareas viven dentro de un menú — necesitas uno antes de crear nada."),
                ("Crea la nota", "Con el <code>id</code> del menú, ya puedes anotar algo."),
            ]},
            {"type": "code", "lang": "bash", "code":
                'TOKEN="kf83h2n..."\n\n'
                '# 1. Crea un menú\n'
                'curl -X POST https://tu-hostname/api/v1/categorias \\\n'
                '  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\\n'
                "  -d '{\"nombre\": \"Cliente Alfa\"}'\n"
                "# -> {\"ok\":true,\"data\":{\"id\":7,\"nombre\":\"Cliente Alfa\", ...}}\n\n"
                '# 2. Crea la nota en ese menú\n'
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
            {"type": "h2", "id": "errores", "text": "Manejo de errores"},
            {"type": "p", "html":
                "El sobre de error es siempre el mismo, en cualquier endpoint de esta API — incluidos los "
                "errores que genera Flask antes de llegar a la vista (404 de ruta inexistente, 405 de método no "
                "permitido): <code>{\"ok\": false, \"error\": \"mensaje legible\"}</code>, nunca una página HTML."},
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
                "<b>Notas y tareas con duración no tienen un endpoint <code>GET</code> de listado propio</b> — se "
                "leen siempre a través de <code>GET /historial</code> (filtrable por fecha/menú/texto) o de "
                "<code>GET /dashboard</code> (resumen del día). Es la misma vía que usa la propia app web: el "
                "registro cronológico combinado es el modelo mental central de Guilda Work, no una lista por "
                "tipo de objeto. Las tareas estilo Outlook (<a href=\"#tareas-outlook\">más abajo</a>) sí tienen "
                "su propio <code>GET /tareas-outlook</code>, porque no viven en ese registro cronológico."},
            {"type": "h2", "id": "auth", "text": "Auth"},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["POST", "/auth/registro", "Crea una cuenta nueva y devuelve un token."],
                ["POST", "/auth/login", "Inicia sesión y devuelve un token nuevo."],
                ["POST", "/auth/logout", "Revoca el token de la propia petición."],
                ["GET", "/auth/me", "Datos de la cuenta autenticada."],
            ]},
            {"type": "h2", "id": "categorias", "text": "Menús (categorías)"},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["GET", "/categorias", "Lista los menús del usuario."],
                ["POST", "/categorias", "Crea un menú nuevo (<code>nombre</code>, <code>color</code> opcional)."],
                ["DELETE", "/categorias/{id}", "Elimina un menú (va a la papelera)."],
                ["POST", "/categorias/{id}/favorito", "Alterna si el menú está marcado como favorito."],
                ["POST", "/categorias/reordenar", "Reordena los menús (<code>orden</code>: lista de ids)."],
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
                ["GET", "/tareas-outlook", "Lista, filtrable por <code>estado</code>/<code>prioridad</code>/<code>categoria</code>/<code>q</code>."],
                ["POST", "/tareas-outlook", "Crea una (<code>asunto</code> obligatorio; <code>cuerpo</code>, <code>prioridad</code>, <code>fecha_inicio</code>, <code>fecha_vencimiento</code>, <code>categoria_outlook</code>)."],
                ["PUT", "/tareas-outlook/{id}", "Edita cualquier subconjunto de campos (solo actualiza los presentes en el body)."],
                ["DELETE", "/tareas-outlook/{id}", "Elimina."],
                ["POST", "/tareas-outlook/{id}/completar", "Marca como completada."],
            ]},
            {"type": "h2", "id": "dashboard-historico", "text": "Dashboard, histórico y exportación"},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["GET", "/dashboard", "Resumen del día: menús, tareas activas, notas de hoy, correos sin leer."],
                ["GET", "/historial", "Histórico filtrable por <code>desde</code>/<code>hasta</code>/<code>categoria_id</code>/<code>q</code>."],
                ["GET", "/export", "Exporta el histórico — <code>formato</code>: <code>json</code> (por defecto) | <code>csv</code> | <code>md</code>, más <code>desde</code>/<code>hasta</code>/<code>categoria_id</code>."],
            ]},
            {"type": "h2", "id": "papelera", "text": "Papelera"},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["GET", "/papelera", "Lista los elementos borrados (notas, tareas, menús)."],
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
                ["POST", "/correo/enviar", "Envía un correo (adjuntos en base64, <code>cc</code>/<code>bcc</code> soportados)."],
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
                ["GET", "/ia/mensajes", "Histórico de la conversación con el asistente."],
                ["POST", "/ia/mensaje", "Envía un mensaje al asistente."],
                ["POST", "/ia/confirmar", "Confirma o cancela una acción sensible pendiente (p. ej. enviar un correo)."],
                ["POST", "/ia/vaciar", "Vacía la conversación."],
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
            {"type": "h2", "id": "categoria", "text": "Categoria (menú)"},
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
                ["<code>categoria_id</code>", "integer", "Obligatorio — a diferencia de <code>Nota</code>, una tarea con duración siempre pertenece a un menú."],
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
                ["<code>categoria_outlook</code>", "string | null", "Texto libre — no es una <code>Categoria</code>/menú, es la categoría de color propia de Outlook."],
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
        "slug": "ejemplos",
        "grupo": "INTEGRACIÓN",
        "titulo": "Ejemplos",
        "descripcion": "Recetas completas: curl, Python y JavaScript.",
        "bloques": [
            {"type": "p", "html":
                "Tres formas equivalentes de hacer lo mismo — registrar (o reutilizar) una cuenta, crear un menú "
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
        "slug": "asistente-ia",
        "grupo": "INTEGRACIÓN",
        "titulo": "Asistente de IA (MCP)",
        "descripcion": "Conecta Claude Code, Claude Desktop, Codex CLI o ChatGPT directamente contra tu instancia.",
        "bloques": [
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
                "<code>guilda-work</code> con estado conectado. Pídele algo simple como “lista mis menús” para "
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
                ["Stack compartido (sin <code>tenant</code>)", str(TOOLS_STACK_COMPARTIDO), "CRM, Drive, Proyectos, Soporte, Analítica, Automatizaciones, Documentación, Chat, Almacenamiento, Monitorización — instancia compartida entre todos los tenants, sin filtrado por tenant en estas tools."],
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
            {"type": "h2", "id": "herramientas", "text": "Herramientas conectadas (MCP y backoffice)"},
            {"type": "p", "html":
                "Cada tool de MCP que toca el stack compartido (sin <code>tenant</code>, ver "
                "<a href=\"/docs/asistente-ia\">Asistente de IA (MCP)</a>) necesita el token de API de esa "
                "herramienta:"},
            {"type": "table", "headers": ["Variable", "Herramienta", "Nota"], "rows": [
                ["<code>ESPOCRM_API_KEY</code>", "EspoCRM (CRM)", ""],
                ["<code>NEXTCLOUD_ADMIN_USER</code> / <code>_PASSWORD</code>", "Nextcloud (Drive)", ""],
                ["<code>OPENPROJECT_API_TOKEN</code>", "OpenProject (Proyectos)", ""],
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
