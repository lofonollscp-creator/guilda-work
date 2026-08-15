"""Herramientas del Asistente IA (OpenRouter): mismo catálogo de
notas/tareas/correo que expone mcp_server.py a Claude/Codex vía MCP
(desde la Fase MCP, mcp_server.py también expone el resto del stack
Docker — CRM/Drive/etc., ver mcp_tools.py —, pero ese catálogo ampliado
no forma parte de este asistente interno, que se queda solo con lo
propio de Guilda Work), en formato "tools" de OpenAI (que OpenRouter
también acepta) para que el asistente dentro de la propia app pueda
hacer exactamente lo mismo.

No hay lógica de negocio duplicada: `ejecutar()` llama directamente a las
funciones ya definidas en mcp_tools.py (que a su vez son wrappers finos
sobre app/db.py, app/correo.py y app/export.py) — al no llevar decorador
`@mcp.tool()` (ver mcp_tools.py), son invocables como cualquier función
normal de Python (verificado: `type(mcp_tools.listar_notas) is function`).
"""
import mcp_tools
from app.correo import ErrorCorreo


class ErrorHerramientaIA(Exception):
    """Error legible para mostrar en el chat cuando una herramienta falla."""


def _param(tipo: str, descripcion: str) -> dict:
    return {"type": tipo, "description": descripcion}


def _tool(nombre: str, descripcion: str, propiedades: dict, requeridos: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": nombre,
            "description": descripcion,
            "parameters": {
                "type": "object",
                "properties": propiedades,
                "required": requeridos,
            },
        },
    }


HERRAMIENTAS: list[dict] = [
    _tool(
        "buscar_semantico",
        "Busca por significado (no solo palabra exacta) en notas/tareas/correo del usuario actual. Útil para preguntas del tipo '¿qué dijo el cliente X sobre el IVA?'.",
        {
            "texto": _param("string", "Qué buscar."),
            "limite": _param("integer", "Nº máximo de resultados, por defecto 5."),
        },
        ["texto"],
    ),
    _tool(
        "listar_notas",
        "Lista notas del log de actividad (fechas 'YYYY-MM-DD', texto filtra por coincidencia parcial).",
        {
            "desde": _param("string", "Fecha inicial YYYY-MM-DD, opcional."),
            "hasta": _param("string", "Fecha final YYYY-MM-DD, opcional."),
            "texto": _param("string", "Filtro de texto parcial, opcional."),
        },
        [],
    ),
    _tool(
        "crear_nota",
        "Crea una nota rápida con el timestamp actual.",
        {
            "texto": _param("string", "Contenido de la nota."),
            "categoria": _param("string", "Nombre o id del menú/categoría, opcional."),
        },
        ["texto"],
    ),
    _tool(
        "editar_nota",
        "Edita el texto de una nota existente.",
        {
            "nota_id": _param("integer", "Id de la nota."),
            "texto": _param("string", "Nuevo texto."),
        },
        ["nota_id", "texto"],
    ),
    _tool(
        "listar_tareas",
        "Lista tareas estilo Outlook. desde/hasta filtran por fecha de vencimiento (YYYY-MM-DD).",
        {
            "estado": _param("string", "pendiente/en_curso/completada, opcional."),
            "prioridad": _param("string", "baja/normal/alta, opcional."),
            "categoria": _param("string", "Categoría outlook, opcional."),
            "texto": _param("string", "Filtro de texto parcial, opcional."),
            "desde": _param("string", "Fecha inicial YYYY-MM-DD, opcional."),
            "hasta": _param("string", "Fecha final YYYY-MM-DD, opcional."),
        },
        [],
    ),
    _tool(
        "crear_tarea",
        "Crea una tarea estilo Outlook.",
        {
            "asunto": _param("string", "Asunto de la tarea."),
            "prioridad": _param("string", "baja/normal/alta, por defecto normal."),
            "fecha_inicio": _param("string", "YYYY-MM-DD, opcional."),
            "fecha_vencimiento": _param("string", "YYYY-MM-DD, opcional."),
            "categoria": _param("string", "Categoría outlook, opcional."),
            "cuerpo": _param("string", "Cuerpo/descripción, opcional."),
        },
        ["asunto"],
    ),
    _tool(
        "editar_tarea",
        "Edita los campos indicados de una tarea existente (solo se tocan los que se pasen).",
        {
            "tarea_id": _param("integer", "Id de la tarea."),
            "asunto": _param("string", "Nuevo asunto, opcional."),
            "cuerpo": _param("string", "Nuevo cuerpo, opcional."),
            "estado": _param("string", "Nuevo estado, opcional."),
            "prioridad": _param("string", "Nueva prioridad, opcional."),
            "fecha_inicio": _param("string", "YYYY-MM-DD, opcional."),
            "fecha_vencimiento": _param("string", "YYYY-MM-DD, opcional."),
            "categoria": _param("string", "Nueva categoría outlook, opcional."),
        },
        ["tarea_id"],
    ),
    _tool(
        "completar_tarea",
        "Marca una tarea como completada (100%, fecha de finalización = ahora).",
        {"tarea_id": _param("integer", "Id de la tarea.")},
        ["tarea_id"],
    ),
    _tool(
        "consultar_calendario",
        "Tareas con vencimiento entre desde y hasta (YYYY-MM-DD, inclusive).",
        {
            "desde": _param("string", "Fecha inicial YYYY-MM-DD."),
            "hasta": _param("string", "Fecha final YYYY-MM-DD."),
        },
        ["desde", "hasta"],
    ),
    _tool(
        "listar_cuentas_correo",
        "Lista las cuentas de correo configuradas (sin la contraseña).",
        {},
        [],
    ),
    _tool(
        "sincronizar_correo",
        "Descarga los mensajes nuevos de una cuenta de correo (todas las carpetas en IMAP).",
        {"cuenta_id": _param("integer", "Id de la cuenta de correo.")},
        ["cuenta_id"],
    ),
    _tool(
        "listar_carpetas_correo",
        "Carpetas reales de una cuenta de correo.",
        {"cuenta_id": _param("integer", "Id de la cuenta de correo.")},
        ["cuenta_id"],
    ),
    _tool(
        "listar_bandeja_entrada",
        "Lista mensajes ya descargados de una carpeta de una cuenta.",
        {
            "cuenta_id": _param("integer", "Id de la cuenta de correo."),
            "carpeta": _param("string", "Carpeta, por defecto INBOX."),
            "solo_no_leidos": _param("boolean", "Filtrar solo no leídos, opcional."),
            "texto": _param("string", "Filtro de texto parcial, opcional."),
            "limite": _param("integer", "Máximo de mensajes a devolver, por defecto 20."),
        },
        ["cuenta_id"],
    ),
    _tool(
        "leer_correo",
        "Devuelve un mensaje completo (asunto, remitente, destinatarios, Cc, cuerpo, categoría).",
        {"mensaje_id": _param("integer", "Id del mensaje.")},
        ["mensaje_id"],
    ),
    _tool(
        "marcar_leido_correo",
        "Marca un mensaje como leído o no leído.",
        {
            "mensaje_id": _param("integer", "Id del mensaje."),
            "leido": _param("boolean", "True para leído, False para no leído. Por defecto True."),
        },
        ["mensaje_id"],
    ),
    _tool(
        "eliminar_correo",
        "Borra un mensaje de la caché local (no del servidor).",
        {"mensaje_id": _param("integer", "Id del mensaje.")},
        ["mensaje_id"],
    ),
    _tool(
        "listar_categorias_correo",
        "Categorías de color propias de Guilda Work para clasificar correos.",
        {},
        [],
    ),
    _tool(
        "crear_categoria_correo",
        "Crea una categoría de correo.",
        {
            "nombre": _param("string", "Nombre de la categoría."),
            "color": _param("string", "Color hexadecimal, ej. #e0555a."),
        },
        ["nombre", "color"],
    ),
    _tool(
        "eliminar_categoria_correo",
        "Elimina una categoría de correo. Los mensajes que la tuvieran quedan sin categoría.",
        {"categoria_id": _param("integer", "Id de la categoría.")},
        ["categoria_id"],
    ),
    _tool(
        "asignar_categoria_correo",
        "Asigna una categoría a un mensaje, o la quita si no se pasa categoria_id.",
        {
            "mensaje_id": _param("integer", "Id del mensaje."),
            "categoria_id": _param("integer", "Id de la categoría, omitir para quitarla."),
        },
        ["mensaje_id"],
    ),
    _tool(
        "obtener_firma_correo",
        "Firma HTML configurada para una cuenta y cuándo se aplica.",
        {"cuenta_id": _param("integer", "Id de la cuenta de correo.")},
        ["cuenta_id"],
    ),
    _tool(
        "configurar_firma_correo",
        "Guarda la firma HTML de una cuenta y cuándo debe aplicarse.",
        {
            "cuenta_id": _param("integer", "Id de la cuenta de correo."),
            "firma_html": _param("string", "Firma en HTML."),
            "en_nuevos": _param("boolean", "Aplicar en correos nuevos, por defecto True."),
            "en_respuestas": _param("boolean", "Aplicar en respuestas/reenvíos, por defecto True."),
        },
        ["cuenta_id", "firma_html"],
    ),
    _tool(
        "preparar_borrador_correo",
        "Prepara un borrador de correo para revisar antes de enviarlo. NO envía nada.",
        {
            "cuenta_id": _param("integer", "Id de la cuenta remitente."),
            "destinatarios": _param("string", "Direcciones separadas por comas."),
            "asunto": _param("string", "Asunto del correo."),
            "cuerpo_html": _param("string", "Cuerpo del correo en HTML."),
            "cc": _param("string", "Direcciones en copia, separadas por comas, opcional."),
            "bcc": _param("string", "Direcciones en copia oculta, separadas por comas, opcional."),
            "en_respuesta_a": _param("string", "Message-ID al que responde, opcional."),
        },
        ["cuenta_id", "destinatarios", "asunto", "cuerpo_html"],
    ),
    _tool(
        "enviar_borrador_correo",
        "Envía de verdad el borrador preparado con preparar_borrador_correo. No se puede deshacer.",
        {"borrador_id": _param("string", "Id del borrador devuelto por preparar_borrador_correo.")},
        ["borrador_id"],
    ),
    _tool(
        "exportar_historial",
        "Exporta notas y tareas con duración (formato json, csv o md).",
        {
            "formato": _param("string", "json, csv o md. Por defecto json."),
            "desde": _param("string", "Fecha inicial YYYY-MM-DD, opcional."),
            "hasta": _param("string", "Fecha final YYYY-MM-DD, opcional."),
            "categoria": _param("string", "Nombre o id del menú/categoría, opcional."),
        },
        [],
    ),
    _tool(
        "importar_historial",
        "Importa notas y tareas con duración desde un JSON o CSV.",
        {
            "contenido": _param("string", "Contenido del archivo a importar."),
            "formato": _param("string", "json o csv. Por defecto json."),
        },
        ["contenido"],
    ),
    _tool(
        "exportar_tareas",
        "Exporta tareas estilo Outlook a .ics o .csv.",
        {
            "formato": _param("string", "ics o csv. Por defecto ics."),
            "desde": _param("string", "Fecha inicial YYYY-MM-DD, opcional."),
            "hasta": _param("string", "Fecha final YYYY-MM-DD, opcional."),
        },
        [],
    ),
    _tool(
        "importar_tareas",
        "Importa tareas desde un archivo .ics o .csv exportado de Outlook (o de Guilda Work).",
        {
            "contenido": _param("string", "Contenido del archivo a importar."),
            "formato": _param("string", "ics o csv. Por defecto ics."),
        },
        ["contenido"],
    ),
    _tool(
        "listar_tiquets",
        "Lista tiquets de soporte (errores/sugerencias sobre Guilda Work). Tablero compartido: de todos los usuarios, no solo el propio.",
        {
            "estado": _param("string", "sin_revisar/en_revision/finalizado, opcional."),
            "tipo": _param("string", "error/sugerencia, opcional."),
        },
        [],
    ),
    _tool(
        "crear_tiquet",
        "Crea un tiquet de soporte (error o sugerencia) a nombre del usuario actual.",
        {
            "tipo": _param("string", "error o sugerencia."),
            "titulo": _param("string", "Título del tiquet."),
            "descripcion": _param("string", "Descripción, opcional."),
        },
        ["tipo", "titulo"],
    ),
    _tool(
        "editar_tiquet",
        "Edita un tiquet propio, solo mientras siga 'sin_revisar'.",
        {
            "tiquet_id": _param("integer", "Id/número del tiquet (el '#N' de la tarjeta)."),
            "titulo": _param("string", "Nuevo título, opcional."),
            "descripcion": _param("string", "Nueva descripción, opcional."),
            "tipo": _param("string", "error o sugerencia, opcional."),
        },
        ["tiquet_id"],
    ),
    _tool(
        "eliminar_tiquet",
        "Elimina un tiquet propio, o cualquiera si eres administrador.",
        {
            "tiquet_id": _param("integer", "Id/número del tiquet."),
        },
        ["tiquet_id"],
    ),
    _tool(
        "cambiar_estado_tiquet",
        "Mueve un tiquet a otro estado del Kanban (sin_revisar/en_revision/finalizado). Solo administradores.",
        {
            "tiquet_id": _param("integer", "Id/número del tiquet."),
            "estado": _param("string", "sin_revisar, en_revision o finalizado."),
        },
        ["tiquet_id", "estado"],
    ),
    _tool(
        "fichar",
        "Marca un fichaje del usuario actual (registro horario). Falla si la secuencia no es válida o si faltan los datos personales exigidos.",
        {
            "tipo": _param("string", "entrada, pausa_inicio, pausa_fin o salida."),
        },
        ["tipo"],
    ),
    _tool(
        "listar_mis_fichajes",
        "Historial de fichajes del usuario actual, opcionalmente filtrado por fecha.",
        {
            "desde": _param("string", "Fecha YYYY-MM-DD, opcional."),
            "hasta": _param("string", "Fecha YYYY-MM-DD, opcional."),
        },
        [],
    ),
    _tool(
        "listar_papelera",
        "Lista lo que hay en la papelera del usuario actual (menús, tareas, notas, tareas outlook eliminados pero no purgados).",
        {},
        [],
    ),
    _tool(
        "restaurar_de_papelera",
        "Restaura un elemento de la papelera. `origen` es el campo que devuelve listar_papelera.",
        {
            "origen": _param("string", "menu, tarea, nota o tarea_outlook."),
            "id": _param("integer", "Id del elemento a restaurar."),
        },
        ["origen", "id"],
    ),
    _tool(
        "estadisticas_por_categoria",
        "Tiempo dedicado a tareas con duración ya finalizadas, agrupado por menú.",
        {
            "desde": _param("string", "Fecha YYYY-MM-DD, opcional."),
            "hasta": _param("string", "Fecha YYYY-MM-DD, opcional."),
        },
        [],
    ),
    _tool(
        "estadisticas_por_dia",
        "Igual que estadisticas_por_categoria pero agrupado por día.",
        {
            "desde": _param("string", "Fecha YYYY-MM-DD, opcional."),
            "hasta": _param("string", "Fecha YYYY-MM-DD, opcional."),
        },
        [],
    ),
    # Calendario fiscal (Fase G2): dato del TENANT (la gestoría), no del
    # usuario -- mcp_tools._tenant_id_actual() lanza un error legible si el
    # usuario no tiene tenant asignado, mismo criterio que ya usan
    # cambiar_estado_tiquet (admin-only) o fichar (necesita datos previos):
    # se listan igual para todos, la restricción se aplica al ejecutar.
    _tool(
        "listar_clientes_fiscales",
        "Lista los clientes fiscales de la gestoría del usuario actual (para quien lleve un calendario fiscal).",
        {"q": _param("string", "Filtro por nombre o NIF, opcional.")},
        [],
    ),
    _tool(
        "crear_cliente_fiscal",
        "Da de alta un cliente fiscal de la gestoría.",
        {
            "nombre": _param("string", "Nombre o razón social."),
            "nif": _param("string", "NIF/CIF, opcional."),
            "notas": _param("string", "Notas, opcional."),
            "modelos_fiscales": _param("array", "Códigos de modelo que presenta, ej. ['303','130'], opcional."),
        },
        ["nombre"],
    ),
    _tool(
        "listar_vencimientos_fiscales",
        "Lista vencimientos fiscales (modelos 303/390/130/111/115/200) de la gestoría, opcionalmente filtrados.",
        {
            "estado": _param("string", "pendiente/presentado/fuera_plazo, opcional."),
            "cliente_id": _param("integer", "Id del cliente fiscal, opcional."),
            "desde": _param("string", "Fecha YYYY-MM-DD, opcional."),
            "hasta": _param("string", "Fecha YYYY-MM-DD, opcional."),
        },
        [],
    ),
    _tool(
        "leer_adjunto_chat",
        "Lee el texto de un archivo (texto/CSV) que el usuario subió al chat con el botón de clip. Úsalo cuando el usuario mencione 'el archivo adjunto' o similar.",
        {"adjunto_id": _param("integer", "Id del adjunto, mencionado en el mensaje del usuario.")},
        ["adjunto_id"],
    ),
    _tool(
        "generar_vencimientos_fiscales",
        "Genera e inserta directamente los vencimientos de un cliente fiscal para los modelos y año pedidos. Fechas orientativas, no vinculantes.",
        {
            "cliente_id": _param("integer", "Id del cliente fiscal."),
            "modelos": _param("array", "Códigos de modelo, ej. ['303','130']."),
            "anio": _param("integer", "Año fiscal a generar."),
        },
        ["cliente_id", "modelos", "anio"],
    ),
]

# Herramientas que solo leen datos: libres siempre, nunca piden confirmación.
LECTURA: set[str] = {
    "listar_notas", "listar_tareas", "consultar_calendario", "listar_cuentas_correo",
    "sincronizar_correo", "listar_carpetas_correo", "listar_bandeja_entrada", "leer_correo",
    "listar_categorias_correo", "obtener_firma_correo", "exportar_historial", "exportar_tareas",
    "preparar_borrador_correo", "listar_tiquets", "listar_mis_fichajes",
    "buscar_semantico", "listar_papelera", "estadisticas_por_categoria", "estadisticas_por_dia",
    "listar_clientes_fiscales", "listar_vencimientos_fiscales", "leer_adjunto_chat",
}

# Herramientas que modifican datos: piden confirmación salvo modo autónomo activado.
ESCRITURA: set[str] = {
    "crear_nota", "editar_nota", "crear_tarea", "editar_tarea", "completar_tarea",
    "marcar_leido_correo", "eliminar_correo", "crear_categoria_correo", "eliminar_categoria_correo",
    "asignar_categoria_correo", "configurar_firma_correo", "importar_historial", "importar_tareas",
    "crear_tiquet", "editar_tiquet", "eliminar_tiquet", "cambiar_estado_tiquet", "fichar",
    "restaurar_de_papelera", "crear_cliente_fiscal", "generar_vencimientos_fiscales",
}

# Piden confirmación SIEMPRE, incluso con el modo autónomo activado: son
# acciones externas irreversibles (enviar un correo de verdad a un tercero).
SIEMPRE_CONFIRMAR: set[str] = {"enviar_borrador_correo"}

_NOMBRES_VALIDOS = LECTURA | ESCRITURA | SIEMPRE_CONFIRMAR


def necesita_confirmacion(nombre: str, modo_autonomo: bool) -> bool:
    if nombre in SIEMPRE_CONFIRMAR:
        return True
    if nombre in LECTURA:
        return False
    return not modo_autonomo


def ejecutar(usuario_id: int, nombre: str, argumentos: dict):
    """Ejecuta una tool "como" `usuario_id` — ninguna tool de mcp_tools.py
    expone un parámetro de usuario (un cliente MCP externo como Claude Code
    no tiene ese concepto), así que se fija temporalmente vía la contextvar
    `_usuario_id_actual` que sus funciones internas consultan."""
    if nombre not in _NOMBRES_VALIDOS:
        raise ErrorHerramientaIA(f"Herramienta desconocida: '{nombre}'.")
    funcion = getattr(mcp_tools, nombre, None)
    if funcion is None:
        raise ErrorHerramientaIA(f"Herramienta '{nombre}' no está implementada en mcp_tools.")
    token = mcp_tools._usuario_id_actual.set(usuario_id)
    try:
        return funcion(**argumentos)
    except (ValueError, ErrorCorreo) as e:
        raise ErrorHerramientaIA(str(e)) from e
    finally:
        mcp_tools._usuario_id_actual.reset(token)
