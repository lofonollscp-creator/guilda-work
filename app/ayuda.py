"""Ayuda contextual: cada pantalla de la app enlaza con su artículo del centro de ayuda (`help.guildawork.com`, un sitio
estático aparte, repo `guilda-help`). Se resuelve por el nombre del endpoint: gana el prefijo más largo, y una pantalla
sin artículo propio apunta a la portada de la ayuda (nunca a un enlace roto)."""
from __future__ import annotations

import os

# Prefijo de endpoint -> ruta del artículo en el centro de ayuda. Los artículos viven en guilda-help/contenido/<ruta>.md.
MAPA = {
    "inicio": "primeros-pasos/bienvenida",
    "ver_menu": "primeros-pasos/crear-tu-primer-menu",
    "proyectos.": "primeros-pasos/crear-tu-primer-menu",
    "proyectos.notas": "trabajo-diario/notas",
    "lista_notas": "trabajo-diario/notas",
    "editar_nota": "trabajo-diario/notas",
    "tareas.": "trabajo-diario/tareas",
    "tareas.hoy": "trabajo-diario/mi-dia",
    "tareas.editar": "trabajo-diario/tareas-subtareas-recordatorios-y-tiempo",
    "tareas.ver": "trabajo-diario/tareas-subtareas-recordatorios-y-tiempo",
    "tareas.tablero": "trabajo-diario/tareas-subtareas-recordatorios-y-tiempo",
    "tareas.carga": "trabajo-diario/tareas-en-equipo",
    "tareas.plantillas": "trabajo-diario/plantillas-y-recurrentes",
    "tareas.recurrentes": "trabajo-diario/plantillas-y-recurrentes",
    "tareas.sincronizar": "trabajo-diario/plantillas-y-recurrentes",
    "correo.": "trabajo-diario/correo",
    "correo.cuentas": "primeros-pasos/conectar-correo",
    "correo.editar_cuenta": "primeros-pasos/conectar-correo",
    "correo.ajustes": "trabajo-diario/correo-avanzado",
    "correo.programados": "trabajo-diario/correo-avanzado",
    "correo.equipo": "trabajo-diario/tareas-en-equipo",
    "correo.redactar": "trabajo-diario/correo-avanzado",
    "correo.borradores": "trabajo-diario/correo-avanzado",
    "tiquets.": "trabajo-diario/tiquets",
    "fichaje.": "trabajo-diario/fichaje",
    "fiscal.": "trabajo-diario/calendario-fiscal",
    "fiscal.recordatorios": "trabajo-diario/recordatorios-a-clientes",
    "fiscal.papelera": "datos-y-administracion/papelera",
    "herramientas": "herramientas/catalogo-de-apps-conectadas",
    "ia.": "asistente-ia/usar-el-asistente",
    "ia.ajustes": "asistente-ia/ajustes-y-limites",
    "hydra_bridge.": "asistente-ia/conectar-chatgpt-o-claude",
    "historial": "datos-y-administracion/historico",
    "informe_ia": "datos-y-administracion/historico",
    "estadisticas": "datos-y-administracion/estadisticas",
    "papelera": "datos-y-administracion/papelera",
    "importar": "datos-y-administracion/importar",
    "procesar_importacion": "datos-y-administracion/importar",
    "mis_dispositivos": "mi-cuenta/dispositivos-y-tokens",
    "ajustes": "mi-cuenta/centro-de-ajustes",
    "ajustes_perfil": "mi-cuenta/perfil-y-avatar",
    "ajustes_cuenta": "mi-cuenta/verificacion-en-dos-pasos",
}


def base() -> str:
    return os.environ.get("GUILDA_AYUDA_URL", "https://help.guildawork.com").rstrip("/")


def ruta_de(endpoint: str | None) -> str | None:
    """Artículo (ruta sin barras) de una pantalla, o None si no tiene uno propio."""
    if not endpoint:
        return None
    mejor = None
    for prefijo, ruta in MAPA.items():
        if endpoint.startswith(prefijo) and (mejor is None or len(prefijo) > len(mejor[0])):
            mejor = (prefijo, ruta)
    return mejor[1] if mejor else None


IDIOMAS = ("ca", "en", "fr")  # el español está en la raíz del sitio de ayuda


def url_de(endpoint: str | None, idioma: str | None = None) -> tuple[str, bool]:
    """(url, es_especifica): el artículo de esa pantalla en el idioma de la persona, o la portada de la ayuda."""
    raiz = f"{base()}/{idioma}" if idioma in IDIOMAS else base()
    ruta = ruta_de(endpoint)
    return (f"{raiz}/{ruta}/", True) if ruta else (raiz + "/", False)
