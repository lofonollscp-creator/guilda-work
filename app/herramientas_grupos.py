"""Grupos de herramientas del asistente de IA y del servidor MCP. Mandar las ~90 herramientas del chat en cada turno
cuesta ~8.000 fichas y confunde al modelo: el chat ofrece solo el núcleo y los grupos que la conversación necesita
(por palabras clave, por lo ya usado o porque el modelo los pide con `activar_herramientas`); el MCP externo se puede
limitar por grupos y a solo lectura (`GUILDA_MCP_GRUPOS`, `GUILDA_MCP_SOLO_LECTURA`). Este módulo no importa nada de la
app para poder usarlo desde ambos lados sin ciclos."""
from __future__ import annotations

import json
import re

GRUPOS: dict[str, tuple[str, ...]] = {
    "nucleo": (
        "buscar_semantico", "listar_notas", "crear_nota", "editar_nota", "listar_tareas", "crear_tarea", "editar_tarea",
        "completar_tarea", "consultar_calendario", "listar_tareas_hoy", "listar_proyectos", "activar_herramientas", "resumen_del_dia",
    ),
    "tareas_avanzadas": (
        "eliminar_tarea", "eliminar_nota", "fijar_nota", "detalle_tarea", "completar_tareas", "listar_notificaciones", "consumo_ia", "listar_comunicados",
        "cambiar_estado_tarea", "listar_comentarios_tarea", "comentar_tarea", "iniciar_cronometro_tarea", "crear_proyecto", "renombrar_proyecto", "eliminar_proyecto",
        "asignar_tarea", "listar_companeros", "listar_checklist_tarea", "agregar_item_checklist", "alternar_item_checklist",
        "crear_tarea_recurrente", "listar_tareas_recurrentes", "listar_papelera", "restaurar_de_papelera",
        "exportar_historial", "importar_historial", "exportar_tareas", "importar_tareas",
        "estadisticas_por_categoria", "estadisticas_por_dia",
    ),
    "correo": (
        "listar_cuentas_correo", "sincronizar_correo", "listar_carpetas_correo", "listar_bandeja_entrada", "leer_correo",
        "marcar_leido_correo", "eliminar_correo", "listar_categorias_correo", "crear_categoria_correo",
        "eliminar_categoria_correo", "asignar_categoria_correo", "obtener_firma_correo", "configurar_firma_correo",
        "preparar_borrador_correo", "enviar_borrador_correo", "listar_plantillas_correo", "mover_correo", "destacar_correo",
        "posponer_correo", "listar_reglas_correo", "crear_regla_correo", "eliminar_regla_correo", "listar_conversacion_correo",
        "crear_tarea_desde_correo", "guardar_nota_desde_correo", "conectar_cuenta_correo",
    ),
    "fiscal": (
        "listar_clientes_fiscales", "crear_cliente_fiscal", "listar_vencimientos_fiscales", "generar_vencimientos_fiscales",
        "marcar_presentado_vencimiento_fiscal", "editar_vencimiento_fiscal", "resumen_cliente_fiscal",
    ),
    "fichaje": ("fichar", "listar_mis_fichajes"),
    "tiquets": ("listar_tiquets", "crear_tiquet", "editar_tiquet", "eliminar_tiquet", "cambiar_estado_tiquet"),
    "facturacion": ("listar_facturas_cliente", "crear_factura_cliente"),
    "crm": ("crm_listar_leads", "crm_crear_lead", "crm_listar_contactos", "crm_crear_contacto", "crm_listar_cuentas", "crm_crear_cuenta"),
    "archivos": (
        "drive_listar_archivos", "drive_buscar_archivos", "drive_subir_archivo", "enviar_archivo_drive_al_chat",
        "leer_adjunto_chat", "generar_documento_al_chat", "listar_tablas_hojas", "listar_filas_hoja",
    ),
    "firmas": ("listar_documentos_firma", "crear_documento_firma", "enviar_documento_a_firma", "enviar_documento_firmado_al_chat"),
}

DESCRIPCIONES: dict[str, str] = {
    "tareas_avanzadas": "checklist, asignar a compañeros, proyectos, recurrentes, papelera, exportar/importar, estadísticas",
    "correo": "bandeja, leer/mover/destacar, borradores, reglas, categorías, conversaciones",
    "fiscal": "clientes fiscales y vencimientos (modelos, presentar, generar)",
    "fichaje": "fichar entrada/salida y ver fichajes",
    "tiquets": "tiquets de soporte",
    "facturacion": "facturas de clientes",
    "crm": "leads, contactos y cuentas del CRM",
    "archivos": "Drive, hojas de cálculo y documentos generados",
    "firmas": "documentos para firma electrónica",
}

# Palabras clave (en minúsculas, por prefijo de palabra) que activan un grupo en el chat.
PALABRAS: dict[str, tuple[str, ...]] = {
    "tareas_avanzadas": ("checklist", "subtarea", "asigna", "compañer", "proyecto", "recurrente", "papelera", "estadístic", "estadistic", "exporta", "importa", "fija", "elimina", "borra", "cronómetro", "cronometro", "cronometra", "comenta", "comentario", "mención", "dependencia", "estimaci"),
    "correo": ("correo", "mail", "email", "bandeja", "borrador", "remitente", "adjunto", "responde", "respuesta", "mueve", "destaca", "pospon", "conversaci", "regla"),
    "fiscal": ("fiscal", "vencimiento", "modelo", "iva", "irpf", "impuesto", "presentar", "presentad", "declaraci", "gestor", "cliente"),
    "fichaje": ("fich", "jornada", "entrada", "salida", "horas trabaj"),
    "tiquets": ("tiquet", "ticket", "incidencia"),
    "facturacion": ("factura", "cobr"),
    "crm": ("crm", "lead", "contacto", "oportunidad"),
    "archivos": ("drive", "archivo", "fichero", "documento", "hoja de c", "hojas de c", "hoja", "tabla", "excel", "pdf", "sube", "descarga"),
    "firmas": ("firma", "firmar", "documenso"),
}

_PREFIJOS_MCP_INTEGRACIONES = (
    "almacenamiento_", "analitica_", "automatizaciones_", "chat_", "citas_", "documentacion_", "documentos_", "facturas_",
    "firmas_", "hojas_", "monitorizacion_", "newsletter_", "notificaciones_", "proyectos_", "soporte_", "videollamadas_",
    "webhooks_", "correo_stalwart_", "drive_",
)
_VERBOS_LECTURA = re.compile(r"(^|_)(listar|leer|consultar|buscar|obtener|exportar|estadisticas|resumen|descargar|url|preparar)(_|$)")
_VERBOS_ESCRITURA = re.compile(r"(^|_)(crear|enviar|eliminar|borrar|editar|asignar|cambiar|guardar|importar|subir|marcar|mover|configurar|"
                               r"restaurar|fichar|completar|renombrar|alternar|agregar|cancelar|responder|ejecutar|fijar|posponer|destacar|conectar|generar)(_|$)")

_GRUPO_DE: dict[str, str] = {nombre: grupo for grupo, nombres in GRUPOS.items() for nombre in nombres}


def grupo_de(nombre: str) -> str:
    """Grupo de una herramienta. Las del MCP que no están en el chat se agrupan por prefijo; el resto, en `otros`."""
    if nombre in _GRUPO_DE:
        return _GRUPO_DE[nombre]
    if nombre.startswith("backoffice_"):
        return "backoffice"
    if nombre.startswith(_PREFIJOS_MCP_INTEGRACIONES):
        return "integraciones"
    return "otros"


def es_lectura(nombre: str, lectura_conocida: set[str] | frozenset[str] = frozenset()) -> bool:
    """Herramienta que solo consulta. Una herramienta con verbo de escritura nunca cuenta como lectura."""
    if nombre in lectura_conocida:
        return True
    if _VERBOS_ESCRITURA.search(nombre):
        return False
    return bool(_VERBOS_LECTURA.search(nombre))


def grupos_por_texto(texto: str) -> set[str]:
    bajo = (texto or "").lower()
    return {g for g, palabras in PALABRAS.items() if any(p in bajo for p in palabras)}


def grupos_de_conversacion(mensajes: list[dict], ultimos_usuario: int = 3) -> set[str]:
    """Grupos que hay que ofrecer: núcleo + palabras clave de los últimos mensajes del usuario + grupos de las
    herramientas ya usadas en la conversación + grupos pedidos con `activar_herramientas`."""
    grupos = {"nucleo"}
    textos = [m.get("content") or "" for m in mensajes if m.get("role") == "user" and isinstance(m.get("content"), str)]
    for t in textos[-ultimos_usuario:]:
        grupos |= grupos_por_texto(t)
    for m in mensajes:
        for tc in m.get("tool_calls") or []:
            funcion = tc.get("function") or {}
            nombre = funcion.get("name", "")
            if nombre == "activar_herramientas":
                try:
                    pedidos = json.loads(funcion.get("arguments") or "{}").get("grupos") or []
                except (ValueError, AttributeError):
                    pedidos = []
                grupos |= {g for g in pedidos if g in GRUPOS}
            else:
                grupos.add(grupo_de(nombre))
    grupos.discard("otros")
    return grupos


def texto_activacion(grupos_pedidos: list[str]) -> str:
    """Respuesta de `activar_herramientas`: qué se ha activado (el modelo las verá en su siguiente llamada)."""
    validos = [g for g in grupos_pedidos if g in GRUPOS and g != "nucleo"]
    if not validos:
        return "Grupos disponibles: " + "; ".join(f"{g} ({d})" for g, d in DESCRIPCIONES.items()) + "."
    return "Activadas. Ya puedes usar: " + "; ".join(f"{g}: {', '.join(GRUPOS[g])}" for g in validos) + "."


# --- Áreas de la API (app/api_areas.py) aplicadas a las herramientas, para los tokens personales con áreas -------------
# Una herramienta que no está aquí es «transversal»: mezcla datos de varias áreas o toca integraciones, y solo la puede
# usar una credencial sin restricción de áreas (cerrado por defecto: una herramienta nueva sin clasificar no se filtra).
_HERRAMIENTAS_DE_AREA: dict[str, tuple[str, ...]] = {
    "notas": ("listar_notas", "crear_nota", "editar_nota", "eliminar_nota", "fijar_nota"),
    "tareas": (
        "listar_tareas", "crear_tarea", "editar_tarea", "completar_tarea", "completar_tareas", "detalle_tarea", "eliminar_tarea",
        "consultar_calendario", "listar_tareas_hoy", "listar_proyectos", "crear_proyecto", "renombrar_proyecto", "eliminar_proyecto",
        "asignar_tarea", "listar_companeros", "listar_checklist_tarea", "agregar_item_checklist", "alternar_item_checklist",
        "crear_tarea_recurrente", "listar_tareas_recurrentes",
        "cambiar_estado_tarea", "listar_comentarios_tarea", "comentar_tarea", "iniciar_cronometro_tarea",
    ),
    "correo": tuple(n for n in GRUPOS["correo"] if n not in ("crear_tarea_desde_correo", "guardar_nota_desde_correo")),
    "fiscal": GRUPOS["fiscal"],
    "fichaje": GRUPOS["fichaje"],
    "tiquets": GRUPOS["tiquets"],
    "avisos": ("listar_notificaciones", "consumo_ia", "listar_comunicados"),
    "webhooks": ("webhooks_listar", "webhooks_crear", "webhooks_borrar", "webhooks_entregas"),
}
_AREA_DE_HERRAMIENTA = {nombre: area for area, nombres in _HERRAMIENTAS_DE_AREA.items() for nombre in nombres}


def area_de_herramienta(nombre: str) -> str:
    """Área de la API a la que pertenece una herramienta, o `transversal`."""
    return _AREA_DE_HERRAMIENTA.get(nombre, "transversal")


def herramienta_permitida(nombre: str, areas: list[str], solo_lectura: bool, lectura_conocida=frozenset()) -> tuple[bool, str]:
    """(permitido, motivo) para una credencial con `areas` (vacío = todas) y/o solo lectura."""
    if solo_lectura and not es_lectura(nombre, lectura_conocida):
        return False, "Esta credencial es de solo lectura."
    if areas and area_de_herramienta(nombre) not in areas:
        return False, f"Esta credencial solo tiene acceso a: {', '.join(areas)}."
    return True, ""
