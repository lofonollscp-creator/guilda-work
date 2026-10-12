"""Herramientas MCP del correo, sus categorías y la firma.

Parte de la antigua `__init__.py`, dividida por dominios sin cambiar su comportamiento: todo lo que no está aquí (la conexión, las constantes y las funciones de otros
dominios) se usa a través de `_mt`, que sigue siendo el único espacio de nombres (`_mt.nombre` funciona igual que antes y se puede parchear en los tests)."""
from __future__ import annotations
import base64
import contextvars
import mimetypes
import secrets
import sqlite3
import uuid
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import FastMCP
from app import (
    baserow,
    busqueda,
    calcom,
    chatwoot,
    correo,
    db,
    documenso,
    espocrm,
    eventos,
    export,
    facturascripts,
    importador,
    jitsi,
    kratos,
    listmonk,
    metabase,
    minio_cliente,
    n8n,
    nextcloud,
    ntfy,
    openproject,
    outline,
    outlook_ics,
    paperless,
    stalwart,
    synapse,
    umami,
    uptime_kuma,
)

import mcp_tools as _mt


# --- Correo --------------------------------------------------------------------

def conectar_cuenta_correo(
    nombre: str, protocolo: str, host: str, puerto: int, usuario: str, contrasena: str,
    usa_tls: bool = True, smtp_host: str | None = None,
    smtp_puerto: int | None = None, smtp_tls: bool = True,
) -> dict:
    """Conecta una cuenta de correo IMAP o POP3 nueva (protocolo: "imap" o
    "pop3"). Prueba la conexión antes de guardar nada — si las credenciales
    o el servidor son incorrectos, no crea la cuenta. La contraseña se
    guarda cifrada en el almacén de credenciales del sistema, nunca en la
    base de datos. Si no se indican smtp_host/smtp_puerto, se asume el
    mismo servidor y la misma contraseña que para IMAP/POP3 (lo habitual en
    la inmensa mayoría de proveedores) para enviar correo más adelante."""
    cuenta_id = _mt.correo.guardar_cuenta(
        _mt._uid(), nombre=nombre, protocolo=protocolo, host=host, puerto=puerto,
        usuario=usuario, contrasena=contrasena, usa_tls=usa_tls,
        smtp_host=smtp_host, smtp_puerto=smtp_puerto, smtp_tls=smtp_tls,
    )
    return _mt._fila(_mt.db.obtener_cuenta_correo(_mt._uid(), cuenta_id))


def listar_cuentas_correo() -> list[dict]:
    """Lista las cuentas de correo configuradas (sin la contraseña, que vive en keyring)."""
    return _mt._filas(_mt.db.listar_cuentas_correo(_mt._uid()))


def sincronizar_correo(cuenta_id: int) -> dict:
    """Descarga los mensajes nuevos. En IMAP, de TODAS las carpetas de la
    cuenta (se descubren solas); en POP3, de la única bandeja posible."""
    return _mt.correo.sincronizar_bandeja(_mt._uid(), cuenta_id)


def listar_carpetas_correo(cuenta_id: int) -> list[dict]:
    """Carpetas de una cuenta (ej. "INBOX", "[Gmail]/Sent Mail"...). Las
    cuentas POP3 siempre devuelven una única "INBOX" sintética — POP3 no
    tiene carpetas a nivel de protocolo."""
    return _mt.correo.listar_carpetas(_mt._uid(), cuenta_id)


def _con_aviso_protegido(filas: list[dict]) -> list[dict]:
    for f in filas:
        if f.get("protegido"):
            f["aviso"] = _mt._AVISO_CORREO_PROTEGIDO
    return filas


def listar_bandeja_entrada(
    cuenta_id: int, carpeta: str = "INBOX", solo_no_leidos: bool = False,
    texto: str | None = None, limite: int = 20, con_adjuntos: bool = False,
    desde: str | None = None, hasta: str | None = None, solo_destacados: bool = False,
) -> list[dict]:
    """Lista mensajes ya descargados de una carpeta de una cuenta (usa
    sincronizar_correo antes si quieres los más recientes; listar_carpetas_correo
    para ver qué carpetas existen). `texto` busca en asunto, remitente,
    destinatarios y cuerpo. Filtros opcionales: `con_adjuntos`, `solo_destacados`
    y fechas `desde`/`hasta` (YYYY-MM-DD, `hasta` inclusive)."""
    return _mt._con_aviso_protegido(_mt._filas(_mt.correo.listar_mensajes(
        cuenta_id, carpeta=carpeta, solo_no_leidos=solo_no_leidos, texto=texto, limite=limite,
        con_adjuntos=con_adjuntos, desde=desde or None, hasta=hasta or None, solo_destacados=solo_destacados,
    )))


def leer_correo(mensaje_id: int, incluir_html: bool = False) -> dict:
    """Devuelve un mensaje completo (asunto, remitente, destinatarios, Cc,
    cuerpo en texto, categoría). Cco nunca aparece aquí ni en ningún
    mensaje recibido — por diseño del correo electrónico, nadie salvo el
    remitente original sabe quién iba en copia oculta. El HTML solo se
    incluye con `incluir_html=True` (repite el texto y gasta mucho contexto);
    los cuerpos larguísimos se recortan avisando de cuánto había."""
    if not _mt.db.mensaje_correo_pertenece_a_usuario(_mt._uid(), mensaje_id):
        raise ValueError(f"No existe el mensaje {mensaje_id}.")
    mensaje = _mt._fila(_mt.correo.obtener_mensaje(mensaje_id))
    if not incluir_html and mensaje:
        mensaje.pop("cuerpo_html", None)
    if mensaje:
        _mt._con_aviso_protegido([mensaje])
    return mensaje


def marcar_leido_correo(mensaje_id: int, leido: bool = True) -> dict:
    """Marca un mensaje como leído (o no leído, con leido=False)."""
    if not _mt.db.mensaje_correo_pertenece_a_usuario(_mt._uid(), mensaje_id):
        raise ValueError(f"No existe el mensaje {mensaje_id}.")
    _mt.correo.marcar_leido(mensaje_id, leido)
    return _mt._fila(_mt.correo.obtener_mensaje(mensaje_id))


def eliminar_correo(mensaje_id: int) -> dict:
    """Borra un mensaje de la caché local (no del servidor). Si sigue en el
    buzón real, una futura sincronización volverá a descargarlo."""
    if not _mt.db.mensaje_correo_pertenece_a_usuario(_mt._uid(), mensaje_id):
        raise ValueError(f"No existe el mensaje {mensaje_id}.")
    _mt.correo.eliminar_mensaje(mensaje_id)
    return {"eliminado": True}


# --- Categorías de correo (propias de Guilda Work, no se sincronizan) --------

def listar_categorias_correo() -> list[dict]:
    """Categorías de color propias de Guilda Work para clasificar correos
    (no existen en el servidor: IMAP/POP3 genérico no tiene un estándar real
    de categorías con color, eso es propietario de Exchange/Outlook)."""
    return _mt._filas(_mt.correo.listar_categorias(_mt._uid()))


def crear_categoria_correo(nombre: str, color: str) -> dict:
    """Crea una categoría de correo. `color` en formato hexadecimal, ej. "#e0555a"."""
    categoria_id = _mt.correo.crear_categoria(_mt._uid(), nombre, color)
    return {"id": categoria_id, "nombre": nombre, "color": color}


def eliminar_categoria_correo(categoria_id: int) -> dict:
    """Elimina una categoría. Los mensajes que la tuvieran asignada quedan sin categoría."""
    _mt.correo.eliminar_categoria(_mt._uid(), categoria_id)
    return {"eliminada": True}


def asignar_categoria_correo(mensaje_id: int, categoria_id: int | None = None) -> dict:
    """Asigna una categoría a un mensaje, o la quita si `categoria_id` es None."""
    if not _mt.db.mensaje_correo_pertenece_a_usuario(_mt._uid(), mensaje_id):
        raise ValueError(f"No existe el mensaje {mensaje_id}.")
    _mt.correo.asignar_categoria(_mt._uid(), mensaje_id, categoria_id)
    return _mt._fila(_mt.correo.obtener_mensaje(mensaje_id))


# --- Firma de correo -----------------------------------------------------------

def obtener_firma_correo(cuenta_id: int) -> dict:
    """Firma HTML configurada para una cuenta y cuándo se aplica (en nuevos
    y/o en respuestas/reenvíos). Útil para incluirla al preparar un borrador
    si quieres que el correo salga firmado."""
    cuenta = _mt.db.obtener_cuenta_correo(_mt._uid(), cuenta_id)
    if cuenta is None:
        raise ValueError(f"No existe la cuenta {cuenta_id}.")
    return {
        "firma_html": cuenta["firma_html"],
        "firma_en_nuevos": bool(cuenta["firma_en_nuevos"]),
        "firma_en_respuestas": bool(cuenta["firma_en_respuestas"]),
    }


def configurar_firma_correo(cuenta_id: int, firma_html: str, en_nuevos: bool = True, en_respuestas: bool = True) -> dict:
    """Guarda la firma HTML de una cuenta y cuándo debe aplicarse."""
    _mt.correo.guardar_firma(_mt._uid(), cuenta_id, firma_html, en_nuevos, en_respuestas)
    return _mt.obtener_firma_correo(cuenta_id)


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
    _mt._BORRADORES_CORREO[borrador_id] = {
        "usuario_id": _mt._uid(), "cuenta_id": cuenta_id, "destinatarios": destinatarios, "cc": cc, "bcc": bcc,
        "asunto": asunto, "cuerpo_html": cuerpo_html, "en_respuesta_a": en_respuesta_a,
    }
    return {
        "borrador_id": borrador_id,
        "cuenta_id": cuenta_id,
        "destinatarios": destinatarios,
        "cc": cc,
        "bcc": bcc,
        "asunto": asunto,
        "vista_previa_texto": _mt.correo.html_a_texto_plano(cuerpo_html),
    }


def enviar_borrador_correo(borrador_id: str) -> dict:
    """Envía de verdad el borrador preparado con preparar_borrador_correo.

    Esta acción NO se puede deshacer. Pide confirmación explícita al usuario
    antes de llamarla."""
    borrador = _mt._BORRADORES_CORREO.get(borrador_id)
    if borrador is None:
        raise ValueError(
            "Ese borrador no existe (puede que el servidor se haya reiniciado desde que se preparó). "
            "Prepara uno nuevo con preparar_borrador_correo."
        )
    _mt.correo.construir_y_enviar(
        borrador["usuario_id"], borrador["cuenta_id"], borrador["destinatarios"], borrador["asunto"], borrador["cuerpo_html"],
        cc=borrador.get("cc", ""), bcc=borrador.get("bcc", ""), en_respuesta_a=borrador["en_respuesta_a"],
    )
    del _mt._BORRADORES_CORREO[borrador_id]
    return {"enviado": True}
