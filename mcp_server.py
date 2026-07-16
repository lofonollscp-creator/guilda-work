"""Servidor MCP de Guilda Work — expone notas, tareas (con duración y estilo
Outlook), calendario, correo (carpetas IMAP, categorías, Cc/Cco, firma) y
export/import a cualquier cliente MCP (Claude Code, Claude Desktop, Codex
CLI...).

Sigue el mismo patrón que cli.py: importa app.db/app.export/etc. directamente
y llama a db.init_db() al arrancar, sin tocar Flask ni pywebview para nada.
No se empaqueta en el .exe — se ejecuta con:

    python mcp_server.py

y se registra en el cliente MCP que corresponda (ver README.md).

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

import contextvars
import sqlite3
import uuid

from mcp.server.fastmcp import FastMCP

from app import correo, db, export, importador, outlook_ics

mcp = FastMCP("guilda-work")

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

@mcp.tool()
def listar_notas(desde: str | None = None, hasta: str | None = None, texto: str | None = None) -> list[dict]:
    """Lista notas del log de actividad (fechas 'YYYY-MM-DD', `texto` filtra por coincidencia parcial)."""
    filas = db.historial(_uid(), desde=desde, hasta=hasta, texto=texto)
    return [dict(f) for f in filas if f["origen"] == "nota"]


@mcp.tool()
def crear_nota(texto: str, categoria: str | int | None = None) -> dict:
    """Crea una nota rápida con el timestamp actual. `categoria` puede ser el nombre o el id del menú."""
    uid = _uid()
    categoria_id = _resolver_categoria_id(categoria)
    nota_id = db.crear_nota(uid, texto, categoria_id=categoria_id)
    return _fila(db.obtener_nota(uid, nota_id))


@mcp.tool()
def editar_nota(nota_id: int, texto: str) -> dict:
    """Edita el texto de una nota existente."""
    uid = _uid()
    db.editar_nota(uid, nota_id, texto)
    nota = db.obtener_nota(uid, nota_id)
    if nota is None:
        raise ValueError(f"No existe la nota {nota_id} (o está en la papelera).")
    return _fila(nota)


# --- Tareas al estilo Outlook (lista + calendario) ----------------------------

@mcp.tool()
def listar_tareas(
    estado: str | None = None, prioridad: str | None = None, categoria: str | None = None,
    texto: str | None = None, desde: str | None = None, hasta: str | None = None,
) -> list[dict]:
    """Lista tareas (estilo Outlook). `desde`/`hasta` filtran por fecha de vencimiento (YYYY-MM-DD)."""
    return _filas(db.listar_tareas_outlook(
        _uid(), estado=estado, prioridad=prioridad, categoria_outlook=categoria, texto=texto, desde=desde, hasta=hasta,
    ))


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
def completar_tarea(tarea_id: int) -> dict:
    """Marca una tarea como completada (100%, fecha de finalización = ahora)."""
    uid = _uid()
    db.completar_tarea_outlook(uid, tarea_id)
    tarea = db.obtener_tarea_outlook(uid, tarea_id)
    if tarea is None:
        raise ValueError(f"No existe la tarea {tarea_id} (o está en la papelera).")
    return _fila(tarea)


@mcp.tool()
def consultar_calendario(desde: str, hasta: str) -> list[dict]:
    """Tareas con vencimiento entre `desde` y `hasta` (YYYY-MM-DD, inclusive) — para vistas tipo calendario."""
    return _filas(db.listar_tareas_outlook(_uid(), desde=desde, hasta=hasta))


# --- Correo --------------------------------------------------------------------

@mcp.tool()
def listar_cuentas_correo() -> list[dict]:
    """Lista las cuentas de correo configuradas (sin la contraseña, que vive en keyring)."""
    return _filas(db.listar_cuentas_correo(_uid()))


@mcp.tool()
def sincronizar_correo(cuenta_id: int) -> dict:
    """Descarga los mensajes nuevos. En IMAP, de TODAS las carpetas de la
    cuenta (se descubren solas); en POP3, de la única bandeja posible."""
    return correo.sincronizar_bandeja(_uid(), cuenta_id)


@mcp.tool()
def listar_carpetas_correo(cuenta_id: int) -> list[dict]:
    """Carpetas de una cuenta (ej. "INBOX", "[Gmail]/Sent Mail"...). Las
    cuentas POP3 siempre devuelven una única "INBOX" sintética — POP3 no
    tiene carpetas a nivel de protocolo."""
    return correo.listar_carpetas(_uid(), cuenta_id)


@mcp.tool()
def listar_bandeja_entrada(
    cuenta_id: int, carpeta: str = "INBOX", solo_no_leidos: bool = False,
    texto: str | None = None, limite: int = 20,
) -> list[dict]:
    """Lista mensajes ya descargados de una carpeta de una cuenta (usa
    sincronizar_correo antes si quieres los más recientes; listar_carpetas_correo
    para ver qué carpetas existen)."""
    return _filas(correo.listar_mensajes(cuenta_id, carpeta=carpeta, solo_no_leidos=solo_no_leidos, texto=texto, limite=limite))


@mcp.tool()
def leer_correo(mensaje_id: int) -> dict:
    """Devuelve un mensaje completo (asunto, remitente, destinatarios, Cc,
    cuerpo en texto y HTML, categoría). Cco nunca aparece aquí ni en ningún
    mensaje recibido — por diseño del correo electrónico, nadie salvo el
    remitente original sabe quién iba en copia oculta."""
    if not db.mensaje_correo_pertenece_a_usuario(_uid(), mensaje_id):
        raise ValueError(f"No existe el mensaje {mensaje_id}.")
    mensaje = correo.obtener_mensaje(mensaje_id)
    return _fila(mensaje)


@mcp.tool()
def marcar_leido_correo(mensaje_id: int, leido: bool = True) -> dict:
    """Marca un mensaje como leído (o no leído, con leido=False)."""
    if not db.mensaje_correo_pertenece_a_usuario(_uid(), mensaje_id):
        raise ValueError(f"No existe el mensaje {mensaje_id}.")
    correo.marcar_leido(mensaje_id, leido)
    return _fila(correo.obtener_mensaje(mensaje_id))


@mcp.tool()
def eliminar_correo(mensaje_id: int) -> dict:
    """Borra un mensaje de la caché local (no del servidor). Si sigue en el
    buzón real, una futura sincronización volverá a descargarlo."""
    if not db.mensaje_correo_pertenece_a_usuario(_uid(), mensaje_id):
        raise ValueError(f"No existe el mensaje {mensaje_id}.")
    correo.eliminar_mensaje(mensaje_id)
    return {"eliminado": True}


# --- Categorías de correo (propias de Guilda Work, no se sincronizan) --------

@mcp.tool()
def listar_categorias_correo() -> list[dict]:
    """Categorías de color propias de Guilda Work para clasificar correos
    (no existen en el servidor: IMAP/POP3 genérico no tiene un estándar real
    de categorías con color, eso es propietario de Exchange/Outlook)."""
    return _filas(correo.listar_categorias(_uid()))


@mcp.tool()
def crear_categoria_correo(nombre: str, color: str) -> dict:
    """Crea una categoría de correo. `color` en formato hexadecimal, ej. "#e0555a"."""
    categoria_id = correo.crear_categoria(_uid(), nombre, color)
    return {"id": categoria_id, "nombre": nombre, "color": color}


@mcp.tool()
def eliminar_categoria_correo(categoria_id: int) -> dict:
    """Elimina una categoría. Los mensajes que la tuvieran asignada quedan sin categoría."""
    correo.eliminar_categoria(_uid(), categoria_id)
    return {"eliminada": True}


@mcp.tool()
def asignar_categoria_correo(mensaje_id: int, categoria_id: int | None = None) -> dict:
    """Asigna una categoría a un mensaje, o la quita si `categoria_id` es None."""
    if not db.mensaje_correo_pertenece_a_usuario(_uid(), mensaje_id):
        raise ValueError(f"No existe el mensaje {mensaje_id}.")
    correo.asignar_categoria(mensaje_id, categoria_id)
    return _fila(correo.obtener_mensaje(mensaje_id))


# --- Firma de correo -----------------------------------------------------------

@mcp.tool()
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


@mcp.tool()
def configurar_firma_correo(cuenta_id: int, firma_html: str, en_nuevos: bool = True, en_respuestas: bool = True) -> dict:
    """Guarda la firma HTML de una cuenta y cuándo debe aplicarse."""
    correo.guardar_firma(_uid(), cuenta_id, firma_html, en_nuevos, en_respuestas)
    return obtener_firma_correo(cuenta_id)


@mcp.tool()
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


@mcp.tool()
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

@mcp.tool()
def exportar_historial(formato: str = "json", desde: str | None = None, hasta: str | None = None, categoria: str | None = None) -> str:
    """Exporta notas y tareas con duración. `formato`: json, csv o md."""
    uid = _uid()
    categoria_id = _resolver_categoria_id(categoria)
    if formato == "csv":
        return export.a_csv(uid, desde, hasta, categoria_id)
    if formato == "md":
        return export.a_markdown(uid, desde, hasta, categoria_id)
    return export.a_json(uid, desde, hasta, categoria_id)


@mcp.tool()
def importar_historial(contenido: str, formato: str = "json") -> dict:
    """Importa notas y tareas con duración desde un JSON o CSV (mismo formato que exportar_historial)."""
    uid = _uid()
    if formato == "csv":
        return importador.importar_csv(uid, contenido)
    return importador.importar_json(uid, contenido)


@mcp.tool()
def exportar_tareas(formato: str = "ics", desde: str | None = None, hasta: str | None = None) -> str:
    """Exporta tareas estilo Outlook a .ics o .csv, compatibles con Microsoft Outlook."""
    tareas = db.listar_tareas_outlook(_uid(), desde=desde, hasta=hasta)
    if formato == "csv":
        return outlook_ics.exportar_csv_outlook(tareas)
    return outlook_ics.exportar_ics(tareas)


@mcp.tool()
def importar_tareas(contenido: str, formato: str = "ics") -> dict:
    """Importa tareas desde un archivo .ics o .csv exportado de Outlook (o de Guilda Work)."""
    uid = _uid()
    if formato == "csv":
        return outlook_ics.importar_csv_outlook(uid, contenido)
    return outlook_ics.importar_ics(uid, contenido)


if __name__ == "__main__":
    db.init_db()  # idempotente: por si es la primera vez que se usa la app
    mcp.run()
