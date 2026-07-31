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
import sqlite3
import uuid

from mcp.server.fastmcp import FastMCP

from app import (
    baserow,
    calcom,
    chatwoot,
    correo,
    db,
    documenso,
    espocrm,
    export,
    facturascripts,
    importador,
    listmonk,
    metabase,
    minio_cliente,
    n8n,
    nextcloud,
    openproject,
    outline,
    outlook_ics,
    paperless,
    synapse,
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
    return _usuario_id_actual.get() or db.usuario_local_id()


def _fila(fila: sqlite3.Row | None) -> dict | None:
    return dict(fila) if fila is not None else None


def _filas(filas) -> list[dict]:
    return [dict(f) for f in filas]


def _resolver_categoria_id(nombre_o_id: str | int | None) -> int | None:
    """Acepta tanto el id numérico como el nombre del menú/categoría."""
    if nombre_o_id in (None, ""):
        return None
    if isinstance(nombre_o_id, int) or str(nombre_o_id).isdigit():
        return int(nombre_o_id)
    uid = _uid()
    for c in db.listar_categorias(uid):
        if c["nombre"].lower() == str(nombre_o_id).lower():
            return c["id"]
    raise ValueError(
        f"No existe ningún menú/categoría llamado '{nombre_o_id}'. "
        f"Disponibles: {', '.join(c['nombre'] for c in db.listar_categorias(uid))}"
    )


# --- Notas -------------------------------------------------------------------

def listar_notas(desde: str | None = None, hasta: str | None = None, texto: str | None = None) -> list[dict]:
    """Lista notas del log de actividad (fechas 'YYYY-MM-DD', `texto` filtra por coincidencia parcial)."""
    filas = db.historial(_uid(), desde=desde, hasta=hasta, texto=texto)
    return [dict(f) for f in filas if f["origen"] == "nota"]


def crear_nota(texto: str, categoria: str | int | None = None) -> dict:
    """Crea una nota rápida con el timestamp actual. `categoria` puede ser el nombre o el id del menú."""
    uid = _uid()
    categoria_id = _resolver_categoria_id(categoria)
    nota_id = db.crear_nota(uid, texto, categoria_id=categoria_id)
    return _fila(db.obtener_nota(uid, nota_id))


def editar_nota(nota_id: int, texto: str) -> dict:
    """Edita el texto de una nota existente."""
    uid = _uid()
    db.editar_nota(uid, nota_id, texto)
    nota = db.obtener_nota(uid, nota_id)
    if nota is None:
        raise ValueError(f"No existe la nota {nota_id} (o está en la papelera).")
    return _fila(nota)


# --- Tareas al estilo Outlook (lista + calendario) ----------------------------

def listar_tareas(
    estado: str | None = None, prioridad: str | None = None, categoria: str | None = None,
    texto: str | None = None, desde: str | None = None, hasta: str | None = None,
) -> list[dict]:
    """Lista tareas (estilo Outlook). `desde`/`hasta` filtran por fecha de vencimiento (YYYY-MM-DD)."""
    return _filas(db.listar_tareas_outlook(
        _uid(), estado=estado, prioridad=prioridad, categoria_outlook=categoria, texto=texto, desde=desde, hasta=hasta,
    ))


def crear_tarea(
    asunto: str, prioridad: str = "normal", fecha_inicio: str | None = None,
    fecha_vencimiento: str | None = None, categoria: str | None = None, cuerpo: str | None = None,
) -> dict:
    """Crea una tarea (estilo Outlook). `prioridad`: baja/normal/alta. Fechas en 'YYYY-MM-DD'."""
    uid = _uid()
    tarea_id = db.crear_tarea_outlook(
        uid, asunto, cuerpo=cuerpo, prioridad=prioridad, fecha_inicio=fecha_inicio,
        fecha_vencimiento=fecha_vencimiento, categoria_outlook=categoria,
    )
    return _fila(db.obtener_tarea_outlook(uid, tarea_id))


def editar_tarea(
    tarea_id: int, asunto: str | None = None, cuerpo: str | None = None, estado: str | None = None,
    prioridad: str | None = None, fecha_inicio: str | None = None, fecha_vencimiento: str | None = None,
    categoria: str | None = None,
) -> dict:
    """Edita los campos indicados de una tarea existente (solo se tocan los que se pasen)."""
    uid = _uid()
    campos = {
        "asunto": asunto, "cuerpo": cuerpo, "estado": estado, "prioridad": prioridad,
        "fecha_inicio": fecha_inicio, "fecha_vencimiento": fecha_vencimiento, "categoria_outlook": categoria,
    }
    db.editar_tarea_outlook(uid, tarea_id, **{k: v for k, v in campos.items() if v is not None})
    tarea = db.obtener_tarea_outlook(uid, tarea_id)
    if tarea is None:
        raise ValueError(f"No existe la tarea {tarea_id} (o está en la papelera).")
    return _fila(tarea)


def completar_tarea(tarea_id: int) -> dict:
    """Marca una tarea como completada (100%, fecha de finalización = ahora)."""
    uid = _uid()
    db.completar_tarea_outlook(uid, tarea_id)
    tarea = db.obtener_tarea_outlook(uid, tarea_id)
    if tarea is None:
        raise ValueError(f"No existe la tarea {tarea_id} (o está en la papelera).")
    return _fila(tarea)


def consultar_calendario(desde: str, hasta: str) -> list[dict]:
    """Tareas con vencimiento entre `desde` y `hasta` (YYYY-MM-DD, inclusive) — para vistas tipo calendario."""
    return _filas(db.listar_tareas_outlook(_uid(), desde=desde, hasta=hasta))


# --- Correo --------------------------------------------------------------------

def listar_cuentas_correo() -> list[dict]:
    """Lista las cuentas de correo configuradas (sin la contraseña, que vive en keyring)."""
    return _filas(db.listar_cuentas_correo(_uid()))


def sincronizar_correo(cuenta_id: int) -> dict:
    """Descarga los mensajes nuevos. En IMAP, de TODAS las carpetas de la
    cuenta (se descubren solas); en POP3, de la única bandeja posible."""
    return correo.sincronizar_bandeja(_uid(), cuenta_id)


def listar_carpetas_correo(cuenta_id: int) -> list[dict]:
    """Carpetas de una cuenta (ej. "INBOX", "[Gmail]/Sent Mail"...). Las
    cuentas POP3 siempre devuelven una única "INBOX" sintética — POP3 no
    tiene carpetas a nivel de protocolo."""
    return correo.listar_carpetas(_uid(), cuenta_id)


def listar_bandeja_entrada(
    cuenta_id: int, carpeta: str = "INBOX", solo_no_leidos: bool = False,
    texto: str | None = None, limite: int = 20,
) -> list[dict]:
    """Lista mensajes ya descargados de una carpeta de una cuenta (usa
    sincronizar_correo antes si quieres los más recientes; listar_carpetas_correo
    para ver qué carpetas existen)."""
    return _filas(correo.listar_mensajes(cuenta_id, carpeta=carpeta, solo_no_leidos=solo_no_leidos, texto=texto, limite=limite))


def leer_correo(mensaje_id: int) -> dict:
    """Devuelve un mensaje completo (asunto, remitente, destinatarios, Cc,
    cuerpo en texto y HTML, categoría). Cco nunca aparece aquí ni en ningún
    mensaje recibido — por diseño del correo electrónico, nadie salvo el
    remitente original sabe quién iba en copia oculta."""
    if not db.mensaje_correo_pertenece_a_usuario(_uid(), mensaje_id):
        raise ValueError(f"No existe el mensaje {mensaje_id}.")
    mensaje = correo.obtener_mensaje(mensaje_id)
    return _fila(mensaje)


def marcar_leido_correo(mensaje_id: int, leido: bool = True) -> dict:
    """Marca un mensaje como leído (o no leído, con leido=False)."""
    if not db.mensaje_correo_pertenece_a_usuario(_uid(), mensaje_id):
        raise ValueError(f"No existe el mensaje {mensaje_id}.")
    correo.marcar_leido(mensaje_id, leido)
    return _fila(correo.obtener_mensaje(mensaje_id))


def eliminar_correo(mensaje_id: int) -> dict:
    """Borra un mensaje de la caché local (no del servidor). Si sigue en el
    buzón real, una futura sincronización volverá a descargarlo."""
    if not db.mensaje_correo_pertenece_a_usuario(_uid(), mensaje_id):
        raise ValueError(f"No existe el mensaje {mensaje_id}.")
    correo.eliminar_mensaje(mensaje_id)
    return {"eliminado": True}


# --- Categorías de correo (propias de Guilda Work, no se sincronizan) --------

def listar_categorias_correo() -> list[dict]:
    """Categorías de color propias de Guilda Work para clasificar correos
    (no existen en el servidor: IMAP/POP3 genérico no tiene un estándar real
    de categorías con color, eso es propietario de Exchange/Outlook)."""
    return _filas(correo.listar_categorias(_uid()))


def crear_categoria_correo(nombre: str, color: str) -> dict:
    """Crea una categoría de correo. `color` en formato hexadecimal, ej. "#e0555a"."""
    categoria_id = correo.crear_categoria(_uid(), nombre, color)
    return {"id": categoria_id, "nombre": nombre, "color": color}


def eliminar_categoria_correo(categoria_id: int) -> dict:
    """Elimina una categoría. Los mensajes que la tuvieran asignada quedan sin categoría."""
    correo.eliminar_categoria(_uid(), categoria_id)
    return {"eliminada": True}


def asignar_categoria_correo(mensaje_id: int, categoria_id: int | None = None) -> dict:
    """Asigna una categoría a un mensaje, o la quita si `categoria_id` es None."""
    if not db.mensaje_correo_pertenece_a_usuario(_uid(), mensaje_id):
        raise ValueError(f"No existe el mensaje {mensaje_id}.")
    correo.asignar_categoria(mensaje_id, categoria_id)
    return _fila(correo.obtener_mensaje(mensaje_id))


# --- Firma de correo -----------------------------------------------------------

def obtener_firma_correo(cuenta_id: int) -> dict:
    """Firma HTML configurada para una cuenta y cuándo se aplica (en nuevos
    y/o en respuestas/reenvíos). Útil para incluirla al preparar un borrador
    si quieres que el correo salga firmado."""
    cuenta = db.obtener_cuenta_correo(_uid(), cuenta_id)
    if cuenta is None:
        raise ValueError(f"No existe la cuenta {cuenta_id}.")
    return {
        "firma_html": cuenta["firma_html"],
        "firma_en_nuevos": bool(cuenta["firma_en_nuevos"]),
        "firma_en_respuestas": bool(cuenta["firma_en_respuestas"]),
    }


def configurar_firma_correo(cuenta_id: int, firma_html: str, en_nuevos: bool = True, en_respuestas: bool = True) -> dict:
    """Guarda la firma HTML de una cuenta y cuándo debe aplicarse."""
    correo.guardar_firma(_uid(), cuenta_id, firma_html, en_nuevos, en_respuestas)
    return obtener_firma_correo(cuenta_id)


def preparar_borrador_correo(
    cuenta_id: int, destinatarios: str, asunto: str, cuerpo_html: str,
    cc: str = "", bcc: str = "", en_respuesta_a: str | None = None,
) -> dict:
    """Prepara un borrador de correo para revisar antes de enviarlo. NO envía nada.

    `cc`/`bcc` (Cco) son cadenas con uno o varios correos separados por
    comas; `bcc` nunca viajará como cabecera visible del mensaje, solo como
    destinatario oculto en el envío real. Devuelve un `borrador_id` y una
    vista previa en texto plano. Para enviarlo de verdad hace falta una
    llamada aparte a enviar_borrador_correo(borrador_id) — confirma con el
    usuario el contenido antes de hacer esa segunda llamada."""
    borrador_id = str(uuid.uuid4())
    _BORRADORES_CORREO[borrador_id] = {
        "usuario_id": _uid(), "cuenta_id": cuenta_id, "destinatarios": destinatarios, "cc": cc, "bcc": bcc,
        "asunto": asunto, "cuerpo_html": cuerpo_html, "en_respuesta_a": en_respuesta_a,
    }
    return {
        "borrador_id": borrador_id,
        "cuenta_id": cuenta_id,
        "destinatarios": destinatarios,
        "cc": cc,
        "bcc": bcc,
        "asunto": asunto,
        "vista_previa_texto": correo.html_a_texto_plano(cuerpo_html),
    }


def enviar_borrador_correo(borrador_id: str) -> dict:
    """Envía de verdad el borrador preparado con preparar_borrador_correo.

    Esta acción NO se puede deshacer. Pide confirmación explícita al usuario
    antes de llamarla."""
    borrador = _BORRADORES_CORREO.get(borrador_id)
    if borrador is None:
        raise ValueError(
            "Ese borrador no existe (puede que el servidor se haya reiniciado desde que se preparó). "
            "Prepara uno nuevo con preparar_borrador_correo."
        )
    correo.construir_y_enviar(
        borrador["usuario_id"], borrador["cuenta_id"], borrador["destinatarios"], borrador["asunto"], borrador["cuerpo_html"],
        cc=borrador.get("cc", ""), bcc=borrador.get("bcc", ""), en_respuesta_a=borrador["en_respuesta_a"],
    )
    del _BORRADORES_CORREO[borrador_id]
    return {"enviado": True}


# --- Exportar / importar --------------------------------------------------------

def exportar_historial(formato: str = "json", desde: str | None = None, hasta: str | None = None, categoria: str | None = None) -> str:
    """Exporta notas y tareas con duración. `formato`: json, csv o md."""
    uid = _uid()
    categoria_id = _resolver_categoria_id(categoria)
    if formato == "csv":
        return export.a_csv(uid, desde, hasta, categoria_id)
    if formato == "md":
        return export.a_markdown(uid, desde, hasta, categoria_id)
    return export.a_json(uid, desde, hasta, categoria_id)


def importar_historial(contenido: str, formato: str = "json") -> dict:
    """Importa notas y tareas con duración desde un JSON o CSV (mismo formato que exportar_historial)."""
    uid = _uid()
    if formato == "csv":
        return importador.importar_csv(uid, contenido)
    return importador.importar_json(uid, contenido)


def exportar_tareas(formato: str = "ics", desde: str | None = None, hasta: str | None = None) -> str:
    """Exporta tareas estilo Outlook a .ics o .csv, compatibles con Microsoft Outlook."""
    tareas = db.listar_tareas_outlook(_uid(), desde=desde, hasta=hasta)
    if formato == "csv":
        return outlook_ics.exportar_csv_outlook(tareas)
    return outlook_ics.exportar_ics(tareas)


def importar_tareas(contenido: str, formato: str = "ics") -> dict:
    """Importa tareas desde un archivo .ics o .csv exportado de Outlook (o de Guilda Work)."""
    uid = _uid()
    if formato == "csv":
        return outlook_ics.importar_csv_outlook(uid, contenido)
    return outlook_ics.importar_ics(uid, contenido)


# --- CRM (EspoCRM) -------------------------------------------------------------

def crm_listar_leads(texto: str | None = None, limite: int = 20) -> list[dict]:
    """Busca/lista Leads del CRM. `texto` filtra por coincidencia parcial."""
    return espocrm.listar_leads(texto=texto, limite=limite)


def crm_crear_lead(nombre: str, email: str = "", telefono: str = "", empresa: str = "") -> dict | None:
    """Crea un Lead en el CRM."""
    return espocrm.crear_lead(nombre, email=email, telefono=telefono, empresa=empresa)


def crm_listar_contactos(texto: str | None = None, limite: int = 20) -> list[dict]:
    """Busca/lista Contactos del CRM."""
    return espocrm.listar_contactos(texto=texto, limite=limite)


def crm_crear_contacto(nombre: str, email: str = "", telefono: str = "") -> dict | None:
    """Crea un Contacto en el CRM."""
    return espocrm.crear_contacto(nombre, email=email, telefono=telefono)


def crm_listar_cuentas(texto: str | None = None, limite: int = 20) -> list[dict]:
    """Busca/lista Cuentas (empresas/clientes) del CRM."""
    return espocrm.listar_cuentas(texto=texto, limite=limite)


def crm_crear_cuenta(nombre: str, sitio_web: str = "") -> dict | None:
    """Crea una Cuenta en el CRM."""
    return espocrm.crear_cuenta(nombre, sitio_web=sitio_web)


# --- Drive (Nextcloud) -----------------------------------------------------------

def drive_listar_archivos(carpeta: str = "") -> list[dict]:
    """Lista archivos/carpetas del Drive en `carpeta` (ej. "Lueira" para el
    espacio compartido de ese tenant; vacío para la raíz)."""
    return nextcloud.listar_archivos(carpeta)


def drive_buscar_archivos(texto: str, limite: int = 20) -> list[dict]:
    """Busca archivos por nombre en todo el Drive."""
    return nextcloud.buscar_archivos(texto, limite=limite)


def drive_subir_archivo(ruta: str, contenido_texto: str) -> dict:
    """Sube un archivo de texto al Drive en `ruta` (ej. "Lueira/nota.txt").
    Para binarios, usa la propia interfaz web de Nextcloud."""
    return nextcloud.subir_archivo(ruta, contenido_texto.encode("utf-8"))


def drive_descargar_archivo(ruta: str) -> str:
    """Descarga un archivo de texto del Drive por su ruta."""
    return nextcloud.descargar_archivo(ruta).decode("utf-8", errors="replace")


# --- OpenProject -----------------------------------------------------------------

def proyectos_listar() -> list[dict]:
    """Lista los proyectos de OpenProject."""
    return openproject.listar_proyectos()


def proyectos_listar_tareas(proyecto_id: int | None = None, texto: str | None = None, limite: int = 20) -> list[dict]:
    """Lista/busca paquetes de trabajo (tareas) de OpenProject."""
    return openproject.listar_paquetes_trabajo(proyecto_id=proyecto_id, texto=texto, limite=limite)


def proyectos_crear_tarea(proyecto_id: int, asunto: str, tipo_id: int = 1) -> dict:
    """Crea un paquete de trabajo (tarea) en un proyecto de OpenProject."""
    return openproject.crear_paquete_trabajo(proyecto_id, asunto, tipo_id=tipo_id)


# --- Soporte (Chatwoot) ------------------------------------------------------------

def soporte_listar_conversaciones(estado: str = "open", limite: int = 20) -> list[dict]:
    """Lista conversaciones de la bandeja de soporte (Chatwoot). `estado`:
    open/resolved/pending/all."""
    return chatwoot.listar_conversaciones(estado_filtro=estado, limite=limite)


def soporte_leer_conversacion(conversacion_id: int) -> list[dict]:
    """Mensajes de una conversación de soporte."""
    return chatwoot.leer_conversacion(conversacion_id)


def soporte_responder_conversacion(conversacion_id: int, texto: str) -> dict:
    """Responde en una conversación de soporte existente."""
    return chatwoot.responder_conversacion(conversacion_id, texto)


# --- Analítica (Metabase) ----------------------------------------------------------

def analitica_listar_preguntas() -> list[dict]:
    """Lista las preguntas/consultas guardadas en Metabase."""
    return metabase.listar_preguntas()


def analitica_ejecutar_pregunta(pregunta_id: int) -> dict:
    """Ejecuta una pregunta ya guardada en Metabase y devuelve sus resultados."""
    return metabase.ejecutar_pregunta(pregunta_id)


def analitica_listar_dashboards() -> list[dict]:
    """Lista los dashboards guardados en Metabase."""
    return metabase.listar_dashboards()


# --- Automatizaciones (n8n) --------------------------------------------------------

def automatizaciones_listar_flujos(limite: int = 20) -> list[dict]:
    """Lista los flujos de automatización de n8n."""
    return n8n.listar_flujos(limite=limite)


def automatizaciones_ejecutar_flujo(flujo_id: str) -> dict:
    """Ejecuta un flujo de n8n ya existente por su id."""
    return n8n.ejecutar_flujo(flujo_id)


# --- Documentación (Outline) --------------------------------------------------------

def documentacion_listar_colecciones() -> list[dict]:
    """Lista las colecciones (carpetas) de la wiki de Outline."""
    return outline.listar_colecciones()


def documentacion_buscar(texto: str, limite: int = 20) -> list[dict]:
    """Búsqueda de texto completo en la wiki de Outline."""
    return outline.buscar_documentos(texto, limite=limite)


def documentacion_leer(documento_id: str) -> dict:
    """Lee un documento completo de la wiki de Outline."""
    return outline.leer_documento(documento_id)


def documentacion_crear(coleccion_id: str, titulo: str, texto: str = "", publicar: bool = True) -> dict:
    """Crea un documento nuevo en la wiki de Outline."""
    return outline.crear_documento(coleccion_id, titulo, texto=texto, publicar=publicar)


# --- Chat (Synapse/Matrix) ---------------------------------------------------------

def chat_listar_salas() -> list[dict]:
    """Lista las salas de chat a las que pertenece el asistente."""
    return synapse.listar_salas()


def chat_enviar_mensaje(sala_id: str, texto: str) -> dict:
    """Envía un mensaje a una sala de chat existente."""
    return synapse.enviar_mensaje(sala_id, texto)


# --- Almacenamiento de archivos (MinIO) ---------------------------------------------

def almacenamiento_listar_buckets() -> list[dict]:
    """Lista los buckets de MinIO."""
    return minio_cliente.listar_buckets()


def almacenamiento_listar_archivos(bucket: str, prefijo: str = "", limite: int = 50) -> list[dict]:
    """Lista los archivos de un bucket de MinIO."""
    return minio_cliente.listar_archivos(bucket, prefijo=prefijo, limite=limite)


def almacenamiento_url_descarga(bucket: str, nombre_archivo: str, expira_minutos: int = 60) -> str:
    """Genera una URL de descarga temporal y firmada para un archivo de MinIO."""
    return minio_cliente.url_descarga(bucket, nombre_archivo, expira_minutos=expira_minutos)


# --- Monitorización (Uptime Kuma) — solo lectura, ver app/uptime_kuma.py -----------

def monitorizacion_listar_estado() -> list[dict]:
    """Estado actual de cada monitor (activo/caído/pendiente/mantenimiento).
    Solo lectura — Uptime Kuma no tiene API de escritura fuera de Socket.IO."""
    return uptime_kuma.listar_monitores()


# --- Facturación (FacturaScripts) — ÚNICO cliente con parámetro `tenant` -----
#
# A diferencia de todas las demás herramientas de este catálogo (una
# instancia compartida, sin concepto de tenant para el MCP — ver
# docstring del módulo), FacturaScripts tiene una instancia física
# distinta POR TENANT (aislamiento real, ver app/facturascripts.py) —
# así que aquí sí hace falta decir de qué tenant se habla en cada
# llamada. `tenant` es el nombre tal cual aparece en el backoffice.

def _datos_facturascripts(tenant: str) -> tuple[str, str]:
    fila = db.obtener_tenant_por_nombre(tenant)
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
    url, api_key = _datos_facturascripts(tenant)
    return facturascripts.listar_clientes(url, api_key, texto=texto, limite=limite)


def facturas_crear_cliente(tenant: str, nombre: str, nif: str = "", email: str = "") -> dict:
    """Crea un cliente en la facturación de un tenant."""
    url, api_key = _datos_facturascripts(tenant)
    return facturascripts.crear_cliente(url, api_key, nombre, nif=nif, email=email)


def facturas_listar_facturas(tenant: str, cliente_codigo: str | None = None, limite: int = 20) -> list[dict]:
    """Lista facturas de cliente de un tenant, opcionalmente filtradas por
    `cliente_codigo`."""
    url, api_key = _datos_facturascripts(tenant)
    return facturascripts.listar_facturas(url, api_key, cliente_codigo=cliente_codigo, limite=limite)


def facturas_crear_factura(tenant: str, cliente_codigo: str, lineas: list[dict]) -> dict:
    """Crea una factura de cliente. `lineas`: lista de
    {"descripcion": str, "cantidad": float, "precio": float}."""
    url, api_key = _datos_facturascripts(tenant)
    return facturascripts.crear_factura(url, api_key, cliente_codigo, lineas)


# --- Firmas (Documenso) — segundo cliente con parámetro `tenant` -------------
#
# Igual que FacturaScripts, `tenant` hace falta aquí porque el
# aislamiento entre tenants no lo da una instancia física distinta (es
# una instancia compartida, como EspoCRM/Nextcloud) sino qué token de
# Equipo se use — sin `tenant`, no habría forma de saber qué Equipo debe
# ver/crear cada documento. El Equipo y el token se crean a mano (ver
# HOSTING.md) — no hay API para eso, verificado en vivo (app/documenso.py).

def _api_key_documenso(tenant: str) -> str:
    fila = db.obtener_tenant_por_nombre(tenant)
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
    return documenso.listar_documentos(_api_key_documenso(tenant), texto=texto, limite=limite)


def firmas_crear_documento(tenant: str, titulo: str, contenido_pdf_base64: str, firmantes: list[dict]) -> dict:
    """Crea un documento para firmar (en borrador, sin enviar todavía).
    `contenido_pdf_base64`: el PDF codificado en base64. `firmantes`:
    lista de {"email": str, "nombre": str} — cada uno recibe un único
    campo de firma en la primera página, posición por defecto."""
    contenido_pdf = base64.b64decode(contenido_pdf_base64)
    return documenso.crear_documento(_api_key_documenso(tenant), titulo, contenido_pdf, firmantes)


def firmas_enviar_a_firma(tenant: str, documento_id: str) -> dict:
    """Envía un documento en borrador — manda el email de firma a cada
    destinatario."""
    return documenso.enviar_a_firma(_api_key_documenso(tenant), documento_id)


def firmas_descargar_firmado(tenant: str, documento_id: str) -> str:
    """Descarga un documento (PDF en base64 — firmado del todo o no, el
    propio PDF refleja el estado actual)."""
    contenido = documenso.descargar_firmado(_api_key_documenso(tenant), documento_id)
    return base64.b64encode(contenido).decode("ascii")


# --- Documentos (Paperless-ngx) — tercer cliente con parámetro `tenant` ------
#
# A diferencia de Documenso, aquí el aprovisionamiento (Grupo + usuario de
# servicio + token) es 100% automático (ver app/rutas_backoffice.py:
# crear_tenant() → app/paperless.py:aprovisionar_tenant()) — `tenant`
# sigue haciendo falta porque el aislamiento depende de qué usuario de
# servicio/Grupo se use, no de una instancia física distinta.

def _datos_paperless(tenant: str) -> tuple[str, int, int]:
    fila = db.obtener_tenant_por_nombre(tenant)
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
    api_key, _, _ = _datos_paperless(tenant)
    return paperless.listar_documentos(api_key, texto=texto, limite=limite)


def documentos_subir(tenant: str, titulo: str, contenido_pdf_base64: str, nombre_archivo: str) -> dict:
    """Sube un documento (PDF en base64) a Paperless-ngx para OCR/indexado
    — solo visible/editable por ese tenant."""
    api_key, user_id, group_id = _datos_paperless(tenant)
    contenido_pdf = base64.b64decode(contenido_pdf_base64)
    return paperless.subir_documento(api_key, user_id, group_id, titulo, contenido_pdf, nombre_archivo)


def documentos_descargar(tenant: str, documento_id: str) -> str:
    """Descarga un documento de un tenant (PDF en base64)."""
    api_key, _, _ = _datos_paperless(tenant)
    contenido = paperless.descargar_documento(api_key, documento_id)
    return base64.b64encode(contenido).decode("ascii")


# --- Hojas (Baserow) — cuarto cliente con parámetro `tenant` -----------------
#
# El token de base de datos de Baserow ya está ligado a un único
# Workspace (ver app/baserow.py) — `tenant` sigue haciendo falta para
# resolver qué token usar, mismo motivo que facturas_*/firmas_*/documentos_*.

def _api_key_baserow(tenant: str) -> str:
    fila = db.obtener_tenant_por_nombre(tenant)
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
    return baserow.listar_tablas(_api_key_baserow(tenant))


def hojas_listar_filas(tenant: str, tabla_id: int, texto: str | None = None, limite: int = 20) -> list[dict]:
    """Lista/busca filas de una tabla de un tenant."""
    return baserow.listar_filas(_api_key_baserow(tenant), tabla_id, texto=texto, limite=limite)


def hojas_crear_fila(tenant: str, tabla_id: int, campos: dict) -> dict:
    """Crea una fila en una tabla de un tenant. `campos`: {"Nombre de
    columna": valor, ...} — los nombres de columna son las propias
    claves del diccionario."""
    return baserow.crear_fila(_api_key_baserow(tenant), tabla_id, campos)


# --- Citas (Cal.diy) — quinto cliente con parámetro `tenant` ----------------
#
# Instancia compartida (a diferencia de FacturaScripts, ver app/calcom.py)
# — el API Key aquí está ligado a la cuenta de servicio de un tenant, no a
# una instancia física, pero `tenant` sigue haciendo falta para resolver
# cuál usar, mismo motivo que facturas_*/firmas_*/documentos_*/hojas_*.

def _api_key_calcom(tenant: str) -> str:
    fila = db.obtener_tenant_por_nombre(tenant)
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
    return calcom.listar_tipos_evento(_api_key_calcom(tenant))


def citas_listar_reservas(tenant: str, desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Lista las reservas de un tenant, opcionalmente acotadas por fecha
    (ISO 8601)."""
    return calcom.listar_reservas(_api_key_calcom(tenant), desde=desde, hasta=hasta)


def citas_crear_reserva(tenant: str, tipo_evento_id: int, inicio: str, nombre_asistente: str, email_asistente: str) -> dict:
    """Crea una reserva para un tenant. `inicio`: fecha/hora en ISO 8601
    UTC (ej. "2026-08-01T10:00:00Z")."""
    return calcom.crear_reserva(_api_key_calcom(tenant), tipo_evento_id, inicio, nombre_asistente, email_asistente)


def citas_cancelar_reserva(tenant: str, reserva_uid: str, motivo: str = "") -> dict:
    """Cancela una reserva de un tenant por su identificador (uid)."""
    return calcom.cancelar_reserva(_api_key_calcom(tenant), reserva_uid, motivo)


# --- Newsletter (Listmonk) — sexto cliente con parámetro `tenant` ----------
#
# Instancia compartida, aislada por Lista/Rol de lista (ver
# app/listmonk.py, verificado en vivo) — `tenant` resuelve qué Lista y
# qué token de servicio usar, mismo motivo que facturas_*/firmas_*/
# documentos_*/hojas_*/citas_*.

def _datos_listmonk(tenant: str) -> tuple[str, int]:
    fila = db.obtener_tenant_por_nombre(tenant)
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
    api_key, list_id = _datos_listmonk(tenant)
    return listmonk.listar_suscriptores(api_key, list_id, texto=texto, limite=limite)


def newsletter_crear_suscriptor(tenant: str, email: str, nombre: str, atribs: dict | None = None) -> dict:
    """Añade un suscriptor a la lista de un tenant."""
    api_key, list_id = _datos_listmonk(tenant)
    return listmonk.crear_suscriptor(api_key, list_id, email, nombre, atribs)


def newsletter_listar_campanas(tenant: str) -> list[dict]:
    """Lista las campañas (newsletters) de un tenant."""
    api_key, _ = _datos_listmonk(tenant)
    return listmonk.listar_campanas(api_key)


def newsletter_crear_campana(tenant: str, nombre: str, asunto: str, cuerpo_html: str) -> dict:
    """Crea una campaña (newsletter) en borrador para la lista de un tenant."""
    api_key, list_id = _datos_listmonk(tenant)
    return listmonk.crear_campana(api_key, list_id, nombre, asunto, cuerpo_html)


def newsletter_enviar_campana(tenant: str, campana_id: int) -> dict:
    """Envía una campaña de un tenant ya creada."""
    api_key, _ = _datos_listmonk(tenant)
    return listmonk.enviar_campana(api_key, campana_id)


# Todas las tools de este módulo, en el mismo orden que se documentan en
# README.md — una única lista, para que ambos servidores (local y remoto)
# registren exactamente el mismo conjunto sin poder desincronizarse.
TOOLS = [
    # Notas
    listar_notas, crear_nota, editar_nota,
    # Tareas
    listar_tareas, crear_tarea, editar_tarea, completar_tarea, consultar_calendario,
    # Correo
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
    # Newsletter
    newsletter_listar_suscriptores, newsletter_crear_suscriptor,
    newsletter_listar_campanas, newsletter_crear_campana, newsletter_enviar_campana,
]


def registrar_tools(mcp: FastMCP) -> None:
    """Registra todas las tools de TOOLS sobre una instancia de FastMCP —
    usado por mcp_server.py (stdio) y mcp_server_remoto.py (streamable-http)
    para exponer exactamente el mismo conjunto sin duplicar código."""
    for tool in TOOLS:
        mcp.add_tool(tool)
