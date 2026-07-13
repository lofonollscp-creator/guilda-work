"""Servidor MCP de Guilda Work — expone notas, tareas (con duración y estilo
Outlook), calendario, correo y export/import a cualquier cliente MCP (Claude
Code, Claude Desktop, Codex CLI...).

Sigue el mismo patrón que cli.py: importa app.db/app.export/etc. directamente
y llama a db.init_db() al arrancar, sin tocar Flask ni pywebview para nada.
No se empaqueta en el .exe — se ejecuta con:

    python mcp_server.py

y se registra en el cliente MCP que corresponda (ver README.md).

Permisos: todas las tools de notas/tareas/calendario/correo son de lectura o
escritura directa. La única excepción es el envío de correo, que es un
proceso de DOS pasos deliberado: preparar_borrador_correo() no envía nada,
solo devuelve una vista previa y un borrador_id; enviar_borrador_correo(id)
es la que de verdad envía, y por eso conviene pedir confirmación explícita
al usuario antes de llamarla (el propio cliente MCP normalmente ya lo pide
para acciones "de envío", pero este diseño de dos pasos da un punto de
control adicional pase lo que pase).
"""
from __future__ import annotations

import sqlite3
import uuid

from mcp.server.fastmcp import FastMCP

from app import correo, db, export, importador, outlook_ics

mcp = FastMCP("guilda-work")

# Borradores de correo preparados en esta sesión del servidor (en memoria:
# si el proceso se reinicia, hay que volver a prepararlos con
# preparar_borrador_correo — no hace falta persistirlos en disco).
_BORRADORES_CORREO: dict[str, dict] = {}


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
    for c in db.listar_categorias():
        if c["nombre"].lower() == str(nombre_o_id).lower():
            return c["id"]
    raise ValueError(
        f"No existe ningún menú/categoría llamado '{nombre_o_id}'. "
        f"Disponibles: {', '.join(c['nombre'] for c in db.listar_categorias())}"
    )


# --- Notas -------------------------------------------------------------------

@mcp.tool()
def listar_notas(desde: str | None = None, hasta: str | None = None, texto: str | None = None) -> list[dict]:
    """Lista notas del log de actividad (fechas 'YYYY-MM-DD', `texto` filtra por coincidencia parcial)."""
    filas = db.historial(desde=desde, hasta=hasta, texto=texto)
    return [dict(f) for f in filas if f["origen"] == "nota"]


@mcp.tool()
def crear_nota(texto: str, categoria: str | int | None = None) -> dict:
    """Crea una nota rápida con el timestamp actual. `categoria` puede ser el nombre o el id del menú."""
    categoria_id = _resolver_categoria_id(categoria)
    nota_id = db.crear_nota(texto, categoria_id=categoria_id)
    return _fila(db.obtener_nota(nota_id))


@mcp.tool()
def editar_nota(nota_id: int, texto: str) -> dict:
    """Edita el texto de una nota existente."""
    db.editar_nota(nota_id, texto)
    nota = db.obtener_nota(nota_id)
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
        estado=estado, prioridad=prioridad, categoria_outlook=categoria, texto=texto, desde=desde, hasta=hasta,
    ))


@mcp.tool()
def crear_tarea(
    asunto: str, prioridad: str = "normal", fecha_inicio: str | None = None,
    fecha_vencimiento: str | None = None, categoria: str | None = None, cuerpo: str | None = None,
) -> dict:
    """Crea una tarea (estilo Outlook). `prioridad`: baja/normal/alta. Fechas en 'YYYY-MM-DD'."""
    tarea_id = db.crear_tarea_outlook(
        asunto, cuerpo=cuerpo, prioridad=prioridad, fecha_inicio=fecha_inicio,
        fecha_vencimiento=fecha_vencimiento, categoria_outlook=categoria,
    )
    return _fila(db.obtener_tarea_outlook(tarea_id))


@mcp.tool()
def editar_tarea(
    tarea_id: int, asunto: str | None = None, cuerpo: str | None = None, estado: str | None = None,
    prioridad: str | None = None, fecha_inicio: str | None = None, fecha_vencimiento: str | None = None,
    categoria: str | None = None,
) -> dict:
    """Edita los campos indicados de una tarea existente (solo se tocan los que se pasen)."""
    campos = {
        "asunto": asunto, "cuerpo": cuerpo, "estado": estado, "prioridad": prioridad,
        "fecha_inicio": fecha_inicio, "fecha_vencimiento": fecha_vencimiento, "categoria_outlook": categoria,
    }
    db.editar_tarea_outlook(tarea_id, **{k: v for k, v in campos.items() if v is not None})
    tarea = db.obtener_tarea_outlook(tarea_id)
    if tarea is None:
        raise ValueError(f"No existe la tarea {tarea_id} (o está en la papelera).")
    return _fila(tarea)


@mcp.tool()
def completar_tarea(tarea_id: int) -> dict:
    """Marca una tarea como completada (100%, fecha de finalización = ahora)."""
    db.completar_tarea_outlook(tarea_id)
    tarea = db.obtener_tarea_outlook(tarea_id)
    if tarea is None:
        raise ValueError(f"No existe la tarea {tarea_id} (o está en la papelera).")
    return _fila(tarea)


@mcp.tool()
def consultar_calendario(desde: str, hasta: str) -> list[dict]:
    """Tareas con vencimiento entre `desde` y `hasta` (YYYY-MM-DD, inclusive) — para vistas tipo calendario."""
    return _filas(db.listar_tareas_outlook(desde=desde, hasta=hasta))


# --- Correo --------------------------------------------------------------------

@mcp.tool()
def listar_cuentas_correo() -> list[dict]:
    """Lista las cuentas de correo configuradas (sin la contraseña, que vive en keyring)."""
    return _filas(db.listar_cuentas_correo())


@mcp.tool()
def sincronizar_correo(cuenta_id: int) -> dict:
    """Descarga los mensajes nuevos de la bandeja de entrada de esa cuenta."""
    return correo.sincronizar_bandeja(cuenta_id)


@mcp.tool()
def listar_bandeja_entrada(cuenta_id: int, solo_no_leidos: bool = False, texto: str | None = None, limite: int = 20) -> list[dict]:
    """Lista mensajes ya descargados de una cuenta (usa sincronizar_correo antes si quieres los más recientes)."""
    return _filas(correo.listar_mensajes(cuenta_id, solo_no_leidos=solo_no_leidos, texto=texto, limite=limite))


@mcp.tool()
def leer_correo(mensaje_id: int) -> dict:
    """Devuelve un mensaje completo (asunto, remitente, cuerpo en texto y HTML)."""
    mensaje = correo.obtener_mensaje(mensaje_id)
    if mensaje is None:
        raise ValueError(f"No existe el mensaje {mensaje_id}.")
    return _fila(mensaje)


@mcp.tool()
def preparar_borrador_correo(
    cuenta_id: int, destinatarios: str, asunto: str, cuerpo_html: str, en_respuesta_a: str | None = None,
) -> dict:
    """Prepara un borrador de correo para revisar antes de enviarlo. NO envía nada.

    Devuelve un `borrador_id` y una vista previa en texto plano. Para enviarlo
    de verdad hace falta una llamada aparte a enviar_borrador_correo(borrador_id)
    — confirma con el usuario el contenido antes de hacer esa segunda llamada."""
    borrador_id = str(uuid.uuid4())
    _BORRADORES_CORREO[borrador_id] = {
        "cuenta_id": cuenta_id, "destinatarios": destinatarios, "asunto": asunto,
        "cuerpo_html": cuerpo_html, "en_respuesta_a": en_respuesta_a,
    }
    return {
        "borrador_id": borrador_id,
        "cuenta_id": cuenta_id,
        "destinatarios": destinatarios,
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
        borrador["cuenta_id"], borrador["destinatarios"], borrador["asunto"],
        borrador["cuerpo_html"], en_respuesta_a=borrador["en_respuesta_a"],
    )
    del _BORRADORES_CORREO[borrador_id]
    return {"enviado": True}


# --- Exportar / importar --------------------------------------------------------

@mcp.tool()
def exportar_historial(formato: str = "json", desde: str | None = None, hasta: str | None = None, categoria: str | None = None) -> str:
    """Exporta notas y tareas con duración. `formato`: json, csv o md."""
    categoria_id = _resolver_categoria_id(categoria)
    if formato == "csv":
        return export.a_csv(desde, hasta, categoria_id)
    if formato == "md":
        return export.a_markdown(desde, hasta, categoria_id)
    return export.a_json(desde, hasta, categoria_id)


@mcp.tool()
def importar_historial(contenido: str, formato: str = "json") -> dict:
    """Importa notas y tareas con duración desde un JSON o CSV (mismo formato que exportar_historial)."""
    if formato == "csv":
        return importador.importar_csv(contenido)
    return importador.importar_json(contenido)


@mcp.tool()
def exportar_tareas(formato: str = "ics", desde: str | None = None, hasta: str | None = None) -> str:
    """Exporta tareas estilo Outlook a .ics o .csv, compatibles con Microsoft Outlook."""
    tareas = db.listar_tareas_outlook(desde=desde, hasta=hasta)
    if formato == "csv":
        return outlook_ics.exportar_csv_outlook(tareas)
    return outlook_ics.exportar_ics(tareas)


@mcp.tool()
def importar_tareas(contenido: str, formato: str = "ics") -> dict:
    """Importa tareas desde un archivo .ics o .csv exportado de Outlook (o de Guilda Work)."""
    if formato == "csv":
        return outlook_ics.importar_csv_outlook(contenido)
    return outlook_ics.importar_ics(contenido)


if __name__ == "__main__":
    db.init_db()  # idempotente: por si es la primera vez que se usa la app
    mcp.run()
