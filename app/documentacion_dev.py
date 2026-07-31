"""Contenido de la Guía para desarrolladores (`/docs`, ver
`app/rutas_docs.py`), la documentación técnica pública para quien quiera
integrar su propio software con una instancia de Guilda Work — por API
REST o conectando un asistente de IA por MCP — o desplegar/extender el
propio proyecto.

Es contenido, no HTML: cada página es una lista de "bloques" (`p`,
`h2`, `callout`, `code`, `steps`, `table`, `cards`) que
`app/templates/docs/pagina.html` renderiza de forma genérica — así
añadir o reordenar contenido no toca la plantilla ni el CSS.

Todo lo que aparece aquí describe comportamiento real de la app en este
mismo commit (endpoints de `app/rutas_api.py`, tools de `mcp_tools.py`,
servidores de `mcp_server.py`/`mcp_server_remoto.py`) — si cambias uno
de esos archivos y la cifra/ruta ya no cuadra, actualiza también esta
página; no hay generación automática todavía.
"""
import mcp_tools as _mt

# --- Cifras derivadas en vivo del propio catálogo de tools, para que no se
# desincronicen de mcp_tools.py como pasó antes con README.md ---
_PREFIJOS_TENANT = (
    "facturas_", "firmas_", "documentos_", "hojas_",
    "citas_", "newsletter_", "correo_stalwart_",
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
}

TOTAL_TOOLS = len(_mt.TOOLS)
TOOLS_TENANT = sum(1 for t in _mt.TOOLS if t.__name__.startswith(_PREFIJOS_TENANT))
TOOLS_PROPIAS = sum(1 for t in _mt.TOOLS if t.__name__ in _PROPIAS_GUILDA_WORK)
TOOLS_STACK_COMPARTIDO = TOTAL_TOOLS - TOOLS_TENANT - TOOLS_PROPIAS


def _familias_tenant() -> list[tuple[str, str, int]]:
    prefijos = [
        ("facturas_", "FacturaScripts", "Facturación"),
        ("firmas_", "Documenso", "Firma electrónica"),
        ("documentos_", "Paperless-ngx", "Gestión documental"),
        ("hojas_", "Baserow", "Hojas de cálculo"),
        ("citas_", "Cal.diy", "Reserva de citas"),
        ("newsletter_", "Listmonk", "Newsletter"),
        ("correo_stalwart_", "Stalwart", "Correo propio"),
    ]
    salida = []
    for prefijo, backend, etiqueta in prefijos:
        n = sum(1 for t in _mt.TOOLS if t.__name__.startswith(prefijo))
        salida.append((etiqueta, backend, n))
    return salida


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
                ("Asistente de IA (MCP)", "Conecta Claude, Codex o ChatGPT directamente contra tu instancia.", "asistente-ia"),
                ("Aislamiento multi-cliente", "Cómo se garantiza que los datos de un tenant nunca los vea otro.", "aislamiento-multicliente"),
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
                "del servidor) — el mismo campo que usa el resto de la app para el registro cronológico. A partir "
                "de aquí, <a href=\"/docs/referencia-api\">la referencia completa</a> cubre tareas con duración, "
                "correo, exportación y el resto de recursos."},
        ],
    },
    {
        "slug": "referencia-api",
        "grupo": "INTEGRACIÓN",
        "titulo": "Referencia de la API",
        "descripcion": "Todos los endpoints REST, agrupados por recurso.",
        "bloques": [
            {"type": "h2", "id": "base-url", "text": "URL base"},
            {"type": "code", "lang": "text", "code": "https://tu-hostname/api/v1"},
            {"type": "p", "html":
                "Todos los endpoints de esta página, salvo <code>/auth/registro</code> y <code>/auth/login</code>, "
                "requieren la cabecera <code>Authorization: Bearer &lt;token&gt;</code> (ver "
                "<a href=\"/docs/autenticacion\">Autenticación</a>) y actúan siempre sobre los datos del usuario "
                "dueño del token — nunca hace falta (ni es posible) pasar un <code>usuario_id</code> a mano."},
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
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["POST", "/tareas", "Crea una tarea (<code>nombre</code>, <code>categoria_id</code>, <code>tipo</code>: <code>duracion</code>|<code>instantanea</code>)."],
                ["PUT", "/tareas/{id}", "Renombra una tarea."],
                ["DELETE", "/tareas/{id}", "Elimina una tarea (va a la papelera)."],
                ["POST", "/tareas/{id}/pausar", "Pausa una tarea en curso."],
                ["POST", "/tareas/{id}/reanudar", "Reanuda una tarea pausada."],
                ["POST", "/tareas/{id}/finalizar", "Finaliza la tarea — calcula la duración total."],
            ]},
            {"type": "h2", "id": "dashboard-historico", "text": "Dashboard, histórico y exportación"},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["GET", "/dashboard", "Resumen del día: menús, tareas activas, notas de hoy, correos sin leer."],
                ["GET", "/historial", "Histórico filtrable por <code>desde</code>/<code>hasta</code>/<code>categoria_id</code>/<code>q</code>."],
                ["GET", "/export", "Exporta el histórico — <code>formato</code>: <code>json</code> (por defecto) | <code>csv</code> | <code>md</code>."],
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
                "distinto del correo-como-herramienta de Stalwart) — bandeja, carpetas, categorías propias, "
                "firma y envío, bajo <code>/api/v1/correo/*</code>. Son 20 endpoints; los más relevantes para "
                "una integración típica:"},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["GET", "/correo/cuentas", "Lista las cuentas de correo conectadas."],
                ["GET", "/correo/mensajes", "Bandeja de entrada (filtrable por cuenta/carpeta)."],
                ["GET", "/correo/mensajes/{id}", "Lee un mensaje completo."],
                ["POST", "/correo/mensajes/{id}/leido", "Marca un mensaje como leído/no leído."],
                ["POST", "/correo/enviar", "Envía un correo nuevo (usa la firma configurada si aplica)."],
            ]},
            {"type": "h2", "id": "ia", "text": "Asistente de IA integrado"},
            {"type": "table", "headers": ["Método", "Ruta", "Descripción"], "rows": [
                ["GET", "/ia/mensajes", "Histórico de la conversación con el asistente."],
                ["POST", "/ia/mensaje", "Envía un mensaje al asistente."],
                ["POST", "/ia/confirmar", "Confirma o cancela una acción sensible pendiente (p. ej. enviar un correo)."],
            ]},
            {"type": "callout", "kind": "info", "html":
                "Esta es la API pensada para clientes propios (apps móviles, scripts, integraciones a medida). "
                "Para que un asistente de IA de terceros (Claude, ChatGPT, Codex) actúe directamente sobre tu "
                "instancia, la vía recomendada es MCP — ver <a href=\"/docs/asistente-ia\">Asistente de IA (MCP)</a>."},
        ],
    },
    {
        "slug": "asistente-ia",
        "grupo": "INTEGRACIÓN",
        "titulo": "Asistente de IA (MCP)",
        "descripcion": "Conecta Claude, Codex o ChatGPT directamente contra tu instancia.",
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
            {"type": "p", "html": "Instala las dependencias del servidor (no se empaquetan en el <code>.exe</code>):"},
            {"type": "code", "lang": "bash", "code": "pip install -r requirements-mcp.txt"},
            {"type": "p", "html": "<b>Claude Code</b>, desde la carpeta del proyecto:"},
            {"type": "code", "lang": "bash", "code": "claude mcp add guilda-work -- python mcp_server.py"},
            {"type": "p", "html": "<b>Codex CLI</b>, en tu <code>config.toml</code>:"},
            {"type": "code", "lang": "toml", "code":
                "[mcp_servers.guilda-work]\n"
                'command = "python"\n'
                'args = ["mcp_server.py"]\n'
                'cwd = "/ruta/a/tu/instancia"'},
            {"type": "p", "html":
                "<b>Claude Desktop</b>: entrada equivalente (<code>command</code>/<code>args</code>/<code>cwd</code>) "
                "en <code>claude_desktop_config.json</code>."},
            {"type": "h2", "id": "remoto", "text": "Conector remoto — ChatGPT"},
            {"type": "p", "html":
                "ChatGPT solo admite servidores MCP <b>remotos por HTTPS</b>, con OAuth 2.1 real — no hay forma de "
                "conectarlo al servidor local. <code>mcp_server_remoto.py</code> expone exactamente las mismas "
                f"{TOTAL_TOOLS} tools por <code>streamable-http</code>, delegando toda la autorización en Ory Hydra "
                "(ya desplegado como proveedor OAuth2 del resto del stack) — este proceso nunca gestiona logins ni "
                "emite tokens él mismo, solo valida cada token que llega contra la introspección de Hydra."},
            {"type": "code", "lang": "bash", "code":
                "export MCP_REMOTO_ORIGIN=https://mcp.tu-hostname\n"
                "export HYDRA_PUBLIC_ORIGIN=https://hydra.tu-hostname\n"
                "python mcp_server_remoto.py"},
            {"type": "callout", "kind": "warn", "html":
                "Requiere el stack Docker + Hydra desplegados de verdad (DNS, registro dinámico de cliente "
                "activado...) — no aplica para uso puramente local. Ver la guía de despliegue, sección "
                "«MCP remoto (ChatGPT)», para el paso a paso completo."},
            {"type": "h2", "id": "catalogo", "text": "Catálogo de tools"},
            {"type": "table", "headers": ["Grupo", "Tools", "Detalle"], "rows": [
                ["Propias de Guilda Work", str(TOOLS_PROPIAS), "Notas, tareas, calendario, correo integrado, categorías de correo, firma, exportar/importar."],
                ["Stack compartido (sin <code>tenant</code>)", str(TOOLS_STACK_COMPARTIDO), "CRM, Drive, Proyectos, Soporte, Analítica, Automatizaciones, Documentación, Chat, Almacenamiento, Monitorización — instancia compartida entre todos los tenants, sin filtrado por tenant en estas tools."],
                ["Con parámetro <code>tenant</code> explícito", str(TOOLS_TENANT), "Ver tabla de familias abajo."],
            ]},
            {"type": "p", "html":
                "Las tools con <code>tenant</code> explícito existen porque, a diferencia del resto, el "
                "aislamiento entre clientes de estas siete herramientas no lo da una instancia compartida con "
                "permisos, sino una instancia física propia, o un token/rol/cuenta propia por tenant — sin ese "
                "parámetro no habría forma de saber qué cliente debe ver cada dato. Ver "
                "<a href=\"/docs/aislamiento-multicliente\">Aislamiento multi-cliente</a> para el detalle de cada "
                "mecanismo."},
            {"type": "table", "headers": ["Herramienta", "Backend", "Tools"], "rows": [
                [etiqueta, backend, str(n)] for etiqueta, backend, n in _familias_tenant()
            ]},
            {"type": "callout", "kind": "info", "html":
                "<b>Enviar correo es la única acción de dos pasos a propósito</b>, tanto en el correo integrado "
                "como en el resto: una tool prepara/previsualiza, otra distinta confirma y envía de verdad — "
                "instruye a tu asistente para que te enseñe el contenido antes de llamar a la segunda."},
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
                "se genera a mano una única vez, no hay endpoint para ello)."},
            {"type": "callout", "kind": "info", "html":
                "El gestor de contraseñas (Vaultwarden) queda <b>excluido a propósito</b> de todo el sistema de "
                "aprovisionamiento e IA — es de uso exclusivamente humano, nunca accesible por ninguna "
                "automatización ni tool de MCP."},
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
                ("Arranca la app", "<code>python run.py</code> — crea <code>data/registro.db</code> la primera vez, sin pasos previos."),
                ("Ejecuta los tests", "<code>pytest tests/ -q</code> — cada módulo de integración externa mockea su cliente HTTP de bajo nivel, ningún test depende de un contenedor real."),
            ]},
            {"type": "code", "lang": "bash", "code":
                "python -m venv .venv\n"
                "source .venv/bin/activate  # .venv\\Scripts\\activate en Windows\n"
                "pip install -r requirements.txt\n"
                "python run.py"},
            {"type": "h2", "id": "cli", "text": "Leer los datos sin arrancar la app"},
            {"type": "p", "html":
                "<code>cli.py</code> es de solo lectura y no requiere que la app esté corriendo — útil para "
                "scripts o para que un agente de IA con acceso a la carpeta consulte el histórico directamente:"},
            {"type": "code", "lang": "bash", "code":
                "python cli.py menus\n"
                "python cli.py export --formato json --desde 2026-07-01 --hasta 2026-07-31"},
            {"type": "h2", "id": "mcp-local", "text": "Servidor MCP en desarrollo"},
            {"type": "code", "lang": "bash", "code":
                "pip install -r requirements-mcp.txt\n"
                "claude mcp add guilda-work-dev -- python mcp_server.py"},
            {"type": "callout", "kind": "info", "html":
                "El paquete <code>mcp</code> vive en un <code>requirements-mcp.txt</code> aparte a propósito — "
                "la app de escritorio empaquetada con PyInstaller no lo necesita, y así el <code>.exe</code> no "
                "carga una dependencia que la mayoría de usuarios nunca usa."},
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
            {"type": "h2", "id": "piezas", "text": "Piezas del stack"},
            {"type": "table", "headers": ["Pieza", "Rol"], "rows": [
                ["<code>docker-compose.yml</code>", "Todos los servicios conectados — una imagen oficial por herramienta, sin forks propios."],
                ["Caddy", "Único punto de entrada real desde internet, HTTPS automático, proxy inverso a cada servicio por subdominio."],
                ["Ory Kratos / Hydra", "Identidad (login/registro) y proveedor OAuth2 para el SSO de las herramientas que lo soportan."],
                ["<code>run.py</code> / <code>serve.py</code>", "El proceso de Guilda Work en sí, fuera de Docker, en el mismo host."],
            ]},
            {"type": "callout", "kind": "warn", "html":
                "Excepciones explícitas a «todo detrás de Caddy en 443»: SSH, OpenVPN y los puertos de correo "
                "real de Stalwart (SMTP/IMAP/POP3) se publican directamente — no son HTTP, Caddy no puede "
                "hacerles de proxy."},
            {"type": "h2", "id": "guia-completa", "text": "Guía completa de despliegue"},
            {"type": "p", "html":
                "El paso a paso detallado — DNS, variables de entorno de cada herramienta, orden de arranque, "
                "registro de clientes OAuth2, backups — vive en <code>HOSTING.md</code>, en la raíz del "
                "repositorio: una sección por herramienta conectada, cada una con su modelo de aislamiento "
                "documentado y, cuando aplica, verificado en vivo contra un contenedor real antes de darlo por "
                "bueno."},
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
