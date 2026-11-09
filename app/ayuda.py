"""Ayuda contextual: cada pantalla de la app enlaza con su artículo del centro de ayuda (`help.guildawork.com`, un sitio
estático aparte, repo `guilda-help`). Se resuelve por el nombre del endpoint: gana el prefijo más largo, y una pantalla
sin artículo propio apunta a la portada de la ayuda (nunca a un enlace roto)."""
from __future__ import annotations

import os

# Prefijo de endpoint -> ruta del artículo en el centro de ayuda. Los artículos viven en guilda-help/contenido/<ruta>.md.
MAPA = {
    "inicio": "primeros-pasos/bienvenida",
    "ver_menu": "primeros-pasos/crear-tu-primer-menu",
    "proyectos.notas": "trabajo-diario/notas",
    "hoy.": "trabajo-diario/hoy",
    "proyectos.": "gestion-del-despacho/proyectos",
    "tareas.informes": "trabajo-diario/informes-y-automatizaciones-de-tareas",
    "tareas.automatizaciones": "trabajo-diario/informes-y-automatizaciones-de-tareas",
    "contactos.": "trabajo-diario/contactos-y-correo-de-equipo",
    "correo.equipo": "trabajo-diario/contactos-y-correo-de-equipo",
    "seguridad.": "datos-y-administracion/cifrado-de-documentos",
    "seguridad.privacidad": "datos-y-administracion/privacidad-y-retencion",
    "seguridad.vaciar_papelera": "datos-y-administracion/privacidad-y-retencion",
    "seguridad.exportar_cliente": "datos-y-administracion/privacidad-y-retencion",
    "mis_datos.": "mi-cuenta/mis-datos-y-privacidad",
    "marca.": "gestion-del-despacho/marca-del-despacho",
    "exportar": "datos-y-administracion/historico",
    "editar_tarea": "trabajo-diario/tareas-subtareas-recordatorios-y-tiempo",
    "guilda_fiscal.": "guilda-fiscal/empezar",
    "guilda_fiscal.apunte": "guilda-fiscal/apuntes-y-facturas",
    "guilda_fiscal.registrar_facturas": "guilda-fiscal/apuntes-y-facturas",
    "guilda_fiscal.importar_libro": "guilda-fiscal/apuntes-y-facturas",
    "guilda_fiscal.periodo": "guilda-fiscal/calcular-el-modelo-303",
    "guilda_fiscal.declaracion": "guilda-fiscal/calcular-el-modelo-303",
    "guilda_fiscal.resumen_anual_390": "guilda-fiscal/otros-modelos-y-herramientas",
    "guilda_fiscal.modelo_130": "guilda-fiscal/otros-modelos-y-herramientas",
    "guilda_fiscal.conciliacion": "guilda-fiscal/otros-modelos-y-herramientas",
    "guilda_fiscal.captura": "guilda-fiscal/otros-modelos-y-herramientas",
    "guilda_fiscal.informe_trimestral_pdf": "guilda-fiscal/otros-modelos-y-herramientas",
    "guilda_fiscal.recordatorios": "trabajo-diario/recordatorios-a-clientes",
    "guilda_fiscal.vencimientos": "trabajo-diario/calendario-fiscal",
    "juridico.": "asistente-juridico/consultar-con-fuentes",
    "juridico.biblioteca": "asistente-juridico/biblioteca-informes-y-fuentes",
    "juridico.documento": "asistente-juridico/biblioteca-informes-y-fuentes",
    "juridico.lista_informes": "asistente-juridico/biblioteca-informes-y-fuentes",
    "juridico.informe": "asistente-juridico/biblioteca-informes-y-fuentes",
    "juridico.fuentes": "asistente-juridico/biblioteca-informes-y-fuentes",
    "juridico.panel_calidad": "asistente-juridico/calidad-del-asistente",
    "documentos_firma.": "gestion-del-despacho/documentos-para-firmar",
    "fiscal_masivo.": "gestion-del-despacho/cambios-en-lote",
    "comercial.masivo": "gestion-del-despacho/cambios-en-lote",
    "marketing.": "gestion-del-despacho/marketing-del-comercial",
    "honorarios.": "guilda-fiscal/honorarios-por-tramos",
    "cobros.": "gestion-del-despacho/facturar-desde-un-expediente",
    "clientes.": "gestion-del-despacho/clientes-expedientes-y-plazos",
    "expedientes.": "gestion-del-despacho/clientes-expedientes-y-plazos",
    "plazos.": "gestion-del-despacho/clientes-expedientes-y-plazos",
    "tiempo.": "gestion-del-despacho/clientes-expedientes-y-plazos",
    "abogados.": "gestion-del-despacho/gabinete-de-abogados",
    "inmobiliaria.": "gestion-del-despacho/inmobiliaria",
    "comercial.": "gestion-del-despacho/comercial-citas-y-videollamadas",
    "citas.": "gestion-del-despacho/comercial-citas-y-videollamadas",
    "videollamadas.": "gestion-del-despacho/comercial-citas-y-videollamadas",
    "certificados.": "gestion-del-despacho/certificados-digitales",
    "control_fiscal.": "gestion-del-despacho/control-fiscal-avisos-traspasos-oficinas",
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
    "correo.redactar": "trabajo-diario/correo-avanzado",
    "correo.borradores": "trabajo-diario/correo-avanzado",
    "tiquets.": "trabajo-diario/tiquets",
    "fichaje.": "trabajo-diario/fichaje",
    "fichaje.ausencias_equipo": "trabajo-diario/ausencias-y-vacaciones",
    "fichaje.mis_ausencias": "trabajo-diario/ausencias-y-vacaciones",
    "fichaje.cuadrante_turnos": "trabajo-diario/turnos",
    "fichaje.mi_bolsa_de_horas": "trabajo-diario/bolsa-de-horas",
    "portal_cliente.": "portal-de-cliente/acceder-al-portal",
    "portal_cliente.dashboard": "portal-de-cliente/recorrer-el-portal",
    "portal_cliente.impuestos": "portal-de-cliente/recorrer-el-portal",
    "portal_cliente.glosario": "portal-de-cliente/recorrer-el-portal",
    "portal_cliente.actividad": "portal-de-cliente/recorrer-el-portal",
    "portal_cliente.firma": "portal-de-cliente/firmar-y-pagar",
    "portal_cliente.honorarios": "portal-de-cliente/firmar-y-pagar",
    "portal_cliente.recibo_honorarios": "portal-de-cliente/firmar-y-pagar",
    "portal_cliente.carpeta": "portal-de-cliente/mi-carpeta",
    "portal_cliente.conversacion": "portal-de-cliente/escribir-a-tu-gestoria",
    "portal_cliente.cuenta": "portal-de-cliente/mi-cuenta-y-avisos",
    "portal_cliente.guardar_preferencias": "portal-de-cliente/mi-cuenta-y-avisos",
    "portal_cliente.segundo_factor": "portal-de-cliente/seguridad-de-tu-cuenta",
    "portal_cliente.cerrar_": "portal-de-cliente/seguridad-de-tu-cuenta",
    "portal_cliente.peticion": "portal-de-cliente/lo-que-te-pide-tu-gestoria",
    "portal_cliente.cuestionario": "portal-de-cliente/cuestionarios-de-tu-gestoria",
    "portal_cliente.avisos": "portal-de-cliente/avisos-del-portal",
    "portal_cliente.justificantes": "portal-de-cliente/movimientos-del-banco-y-tiquets",
    "portal_cliente.extracto": "portal-de-cliente/revisar-mi-extracto-del-banco",
    "portal_cliente.buscar": "portal-de-cliente/buscar-en-el-portal",
    "portal_cliente.calendario": "portal-de-cliente/tus-plazos-en-tu-agenda",
    "portal_cliente.subida_rapida": "portal-de-cliente/subir-facturas-desde-el-movil",
    "portal_cliente.compartir": "portal-de-cliente/subir-facturas-desde-el-movil",
    "portal_cliente.factura": "portal-de-cliente/mis-facturas",
    "portal_cliente.citas": "portal-de-cliente/pedir-una-cita",
    "portal_cliente.declaracion": "portal-de-cliente/lo-que-te-pide-tu-gestoria",
    "portal_cliente.personas": "portal-de-cliente/personas-con-acceso",
    "portal_cliente.facturas": "portal-de-cliente/mis-facturas",
    "portal_cliente.documentos": "portal-de-cliente/subir-documentos-y-mandar-mensajes",
    "portal_cliente.descargar": "portal-de-cliente/subir-documentos-y-mandar-mensajes",
    "portal_cliente.mensajes": "portal-de-cliente/subir-documentos-y-mandar-mensajes",
    "fiscal.": "trabajo-diario/calendario-fiscal",
    "fiscal.recordatorios": "trabajo-diario/recordatorios-a-clientes",
    "fiscal.papelera": "datos-y-administracion/papelera",
    "contabilidad.": "contabilizacion-de-facturas/empezar",
    "contabilidad.lista": "contabilizacion-de-facturas/anotar-y-revisar-facturas",
    "contabilidad.nueva": "contabilizacion-de-facturas/anotar-y-revisar-facturas",
    "contabilidad.ver": "contabilizacion-de-facturas/anotar-y-revisar-facturas",
    "contabilidad.subir": "contabilizacion-de-facturas/anotar-y-revisar-facturas",
    "contabilidad.comprobar": "contabilizacion-de-facturas/generar-el-fichero-para-a3",
    "contabilidad.lotes": "contabilizacion-de-facturas/generar-el-fichero-para-a3",
    "contabilidad.descargar_lote": "contabilizacion-de-facturas/generar-el-fichero-para-a3",
    "contabilidad.configuracion": "contabilizacion-de-facturas/ajustes-de-a3",
    "contabilidad.ajustes": "contabilizacion-de-facturas/ajustes-de-a3",
    "contabilidad.plan": "contabilizacion-de-facturas/ajustes-de-a3",
    "contabilidad.reglas": "contabilizacion-de-facturas/ajustes-de-a3",
    "contabilidad.recordatorios": "contabilizacion-de-facturas/recordar-y-automatizar",
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
