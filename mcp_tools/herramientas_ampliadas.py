"""Herramientas MCP ampliadas: acciones de correo, proyectos, papelera y tareas.

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


# --- Acciones de correo, proyectos, papelera y tareas ampliadas (Bloque 4) --------

def _mensaje_propio(mensaje_id: int):
    if not _mt.db.mensaje_correo_pertenece_a_usuario(_mt._uid(), mensaje_id):
        raise ValueError(f"No existe el mensaje {mensaje_id}.")
    return _mt.db.obtener_mensaje_correo(mensaje_id)


def mover_correo(mensaje_id: int, carpeta_destino: str) -> dict:
    """Mueve un mensaje a otra carpeta del servidor IMAP (listar_carpetas_correo
    muestra las que existen). Actúa de verdad en el servidor; POP3 no tiene carpetas."""
    _mt._mensaje_propio(mensaje_id)
    _mt.correo.mover_mensaje(_mt._uid(), mensaje_id, carpeta_destino)
    return {"movido": True, "carpeta": carpeta_destino}


def destacar_correo(mensaje_id: int, destacado: bool = True, fecha_aviso: str | None = None) -> dict:
    """Destaca (o quita el destacado de) un mensaje; `fecha_aviso` (YYYY-MM-DD) es un recordatorio opcional."""
    _mt._mensaje_propio(mensaje_id)
    _mt.correo.destacar_mensaje(mensaje_id, destacado, fecha_aviso)
    return _mt._fila(_mt.correo.obtener_mensaje(mensaje_id))


def posponer_correo(mensaje_id: int, hasta: str | None = None) -> dict:
    """Oculta un mensaje de la bandeja hasta la fecha `hasta` (YYYY-MM-DD). Sin fecha, deja de estar pospuesto."""
    _mt._mensaje_propio(mensaje_id)
    _mt.correo.posponer_mensaje(mensaje_id, hasta or None)
    return _mt._fila(_mt.correo.obtener_mensaje(mensaje_id))


def listar_reglas_correo() -> list[dict]:
    """Reglas avanzadas de correo (condición por remitente y/o asunto + acciones sobre los correos nuevos)."""
    return _mt._filas(_mt.db.listar_reglas_correo(_mt._uid()))


def crear_regla_correo(
    remitente: str | None = None, asunto_contiene: str | None = None, categoria_id: int | None = None,
    marcar_leido: bool = False, destacar: bool = False, cliente_fiscal_id: int | None = None,
) -> dict:
    """Crea una regla que se aplica a los correos NUEVOS que cumplan todas las condiciones.
    `remitente`: "x@y.com" exacto, "@dominio.com" o texto contenido. Al menos una condición
    (remitente o asunto) y una acción (categoría, marcar leído, destacar, cliente fiscal)."""
    regla_id = _mt.db.crear_regla_correo(
        _mt._uid(), remitente, asunto_contiene, categoria_id=categoria_id, marcar_leido=marcar_leido,
        destacar=destacar, cliente_fiscal_id=cliente_fiscal_id,
    )
    return {"id": regla_id}


def eliminar_regla_correo(regla_id: int) -> dict:
    """Elimina una regla avanzada de correo (no afecta a los mensajes ya procesados)."""
    _mt.db.eliminar_regla_correo(_mt._uid(), regla_id)
    return {"eliminada": True}


def listar_conversacion_correo(mensaje_id: int) -> list[dict]:
    """Los mensajes de la misma conversación (hilo) que `mensaje_id`, del más antiguo al más reciente."""
    mensaje = _mt._mensaje_propio(mensaje_id)
    return _mt._con_aviso_protegido(_mt._filas(_mt.db.mensajes_del_hilo_correo(mensaje["cuenta_id"], mensaje["hilo_clave"]))) or [
        {"id": mensaje["id"], "asunto": mensaje["asunto"], "remitente": mensaje["remitente"], "fecha": mensaje["fecha"]}
    ]


def crear_tarea_desde_correo(mensaje_id: int, fecha_vencimiento: str | None = None) -> dict:
    """Crea una tarea a partir de un correo (asunto del correo, vinculada a él y a su cliente fiscal)."""
    mensaje = _mt._mensaje_propio(mensaje_id)
    uid = _mt._uid()
    tarea_id = _mt.db.crear_tarea_outlook(
        uid, (mensaje["asunto"] or "(sin asunto)").strip()[:200],
        cuerpo=f"Correo de {mensaje['remitente'] or ''}", fecha_vencimiento=fecha_vencimiento or None,
        cliente_fiscal_id=mensaje["cliente_fiscal_id"], mensaje_correo_id=mensaje_id,
    )
    return _mt._fila(_mt.db.obtener_tarea_outlook(uid, tarea_id))


def guardar_nota_desde_correo(mensaje_id: int) -> dict:
    """Guarda un correo como nota (título = asunto, texto = extracto del cuerpo, vinculada al correo)."""
    mensaje = _mt._mensaje_propio(mensaje_id)
    uid = _mt._uid()
    texto = f"De: {mensaje['remitente'] or ''}\n\n{(mensaje['cuerpo_texto'] or '').strip()[:2000]}"
    nota_id = _mt.db.crear_nota(
        uid, texto, titulo=(mensaje["asunto"] or "(sin asunto)").strip()[:120],
        cliente_fiscal_id=mensaje["cliente_fiscal_id"], mensaje_correo_id=mensaje_id,
    )
    return _mt._fila(_mt.db.obtener_nota(uid, nota_id))


def listar_proyectos() -> list[dict]:
    """Proyectos propios de Guilda Work (donde se agrupan notas y tareas con cronómetro)."""
    return _mt._filas(_mt.db.listar_categorias(_mt._uid()))


def crear_proyecto(nombre: str, color: str | None = None) -> dict:
    """Crea un proyecto. `color` opcional en hexadecimal, ej. "#4f8cff"."""
    uid = _mt._uid()
    if not nombre.strip():
        raise ValueError("El proyecto necesita un nombre.")
    proyecto_id = _mt.db.crear_categoria(uid, nombre.strip(), color)
    return _mt._fila(_mt.db.obtener_categoria(uid, proyecto_id))


def renombrar_proyecto(proyecto: str | int, nombre: str, color: str | None = None) -> dict:
    """Renombra un proyecto (por nombre o id) y, si se indica, cambia su color."""
    uid = _mt._uid()
    proyecto_id = _mt._resolver_categoria_id(proyecto)
    if proyecto_id is None or _mt.db.obtener_categoria(uid, proyecto_id) is None:
        raise ValueError(f"No existe el proyecto {proyecto!r}.")
    if not nombre.strip():
        raise ValueError("El proyecto necesita un nombre.")
    _mt.db.renombrar_categoria(uid, proyecto_id, nombre.strip(), color)
    return _mt._fila(_mt.db.obtener_categoria(uid, proyecto_id))


def eliminar_proyecto(proyecto: str | int) -> dict:
    """Manda un proyecto, con sus notas y tareas, a la PAPELERA (recuperable con
    restaurar_de_papelera durante 30 días; no borra nada de verdad)."""
    uid = _mt._uid()
    proyecto_id = _mt._resolver_categoria_id(proyecto)
    if proyecto_id is None or _mt.db.obtener_categoria(uid, proyecto_id) is None:
        raise ValueError(f"No existe el proyecto {proyecto!r}.")
    _mt.db.eliminar_categoria(uid, proyecto_id)
    return {"en_papelera": True, "origen": "menu", "id": proyecto_id}


def eliminar_nota(nota_id: int) -> dict:
    """Manda una nota a la PAPELERA (recuperable con restaurar_de_papelera)."""
    uid = _mt._uid()
    if _mt.db.obtener_nota(uid, nota_id) is None:
        raise ValueError(f"No existe la nota {nota_id} (o ya está en la papelera).")
    _mt.db.eliminar_nota(uid, nota_id)
    return {"en_papelera": True, "origen": "nota", "id": nota_id}


def eliminar_tarea(tarea_id: int) -> dict:
    """Manda una tarea (de la lista) a la PAPELERA (recuperable con restaurar_de_papelera)."""
    uid = _mt._uid()
    if _mt.db.obtener_tarea_outlook(uid, tarea_id) is None:
        raise ValueError(f"No existe la tarea {tarea_id} (o ya está en la papelera).")
    _mt.db.eliminar_tarea_outlook(uid, tarea_id)
    return {"en_papelera": True, "origen": "tarea_outlook", "id": tarea_id}


def fijar_nota(nota_id: int, fijada: bool = True) -> dict:
    """Fija (o desfija) una nota: las fijadas salen primero en su proyecto."""
    uid = _mt._uid()
    nota = _mt.db.obtener_nota(uid, nota_id)
    if nota is None:
        raise ValueError(f"No existe la nota {nota_id} (o está en la papelera).")
    if bool(nota["fijada"]) != bool(fijada):
        _mt.db.alternar_fijada_nota(uid, nota_id)
    return _mt._fila(_mt.db.obtener_nota(uid, nota_id))


def listar_tareas_hoy() -> dict:
    """"Mi día": tareas vencidas, que vencen hoy, en curso y asignadas a mí, pendientes."""
    return {seccion: _mt._filas(filas) for seccion, filas in _mt.db.tareas_para_hoy(_mt._uid()).items()}


def listar_companeros() -> list[dict]:
    """Compañeros del mismo despacho a quienes se puede asignar una tarea (id y nombre)."""
    return _mt._filas(_mt.db.listar_companeros_tenant(_mt._uid()))


def asignar_tarea(tarea_id: int, companero_id: int | None = None) -> dict:
    """Asigna una tarea propia a un compañero del despacho (ver listar_companeros) o,
    sin `companero_id`, la desasigna. El compañero la ve y puede completarla."""
    uid = _mt._uid()
    if not _mt.db.asignar_tarea_outlook(uid, tarea_id, companero_id):
        raise ValueError("No se puede asignar: la tarea no es tuya o el compañero no es de tu despacho.")
    return _mt._fila(_mt.db.obtener_tarea_outlook(uid, tarea_id))


def listar_checklist_tarea(tarea_id: int) -> list[dict]:
    """Subtareas (checklist) de una tarea."""
    if _mt.db.obtener_tarea_outlook_visible(_mt._uid(), tarea_id) is None:
        raise ValueError(f"No existe la tarea {tarea_id}.")
    return _mt._filas(_mt.db.listar_checklist(tarea_id))


def agregar_item_checklist(tarea_id: int, texto: str) -> dict:
    """Añade una subtarea al checklist de una tarea propia (máx. 50, 200 caracteres cada una)."""
    item_id = _mt.db.agregar_item_checklist(_mt._uid(), tarea_id, texto)
    if item_id is None:
        raise ValueError("No se ha podido añadir: la tarea no es tuya, el texto está vacío o el checklist está lleno.")
    return {"id": item_id, "checklist": _mt._filas(_mt.db.listar_checklist(tarea_id))}


def alternar_item_checklist(item_id: int) -> dict:
    """Marca o desmarca una subtarea del checklist (recalcula el porcentaje de la tarea)."""
    if not _mt.db.alternar_item_checklist(_mt._uid(), item_id):
        raise ValueError(f"No existe la subtarea {item_id} o no tienes acceso.")
    return {"alternada": True}


def cambiar_estado_tarea(tarea_id: int, estado: str) -> dict:
    """Cambia el estado de una tarea de la lista: no_iniciada, en_progreso, completada, esperando o aplazada. Respeta las
    dependencias: una tarea que espera a otras no puede pasar a en_progreso ni a completada."""
    uid = _mt._uid()
    if estado not in ("no_iniciada", "en_progreso", "completada", "esperando", "aplazada"):
        raise ValueError("estado debe ser no_iniciada, en_progreso, completada, esperando o aplazada.")
    if _mt.db.obtener_tarea_outlook_visible(uid, tarea_id) is None:
        raise ValueError(f"No existe la tarea {tarea_id} (o no tienes acceso).")
    if estado in ("en_progreso", "completada") and _mt.db.tarea_bloqueada(tarea_id):
        raise ValueError("Esta tarea espera a otras que todavía no están completadas.")
    if not _mt.db.cambiar_estado_tarea_outlook(uid, tarea_id, estado):
        raise ValueError("No tienes permiso para cambiar el estado de esta tarea.")
    return _mt._fila(_mt.db.obtener_tarea_outlook_visible(uid, tarea_id))


def listar_comentarios_tarea(tarea_id: int) -> list[dict]:
    """Comentarios de una tarea (de la más antigua a la más reciente)."""
    if _mt.db.obtener_tarea_outlook_visible(_mt._uid(), tarea_id) is None:
        raise ValueError(f"No existe la tarea {tarea_id} (o no tienes acceso).")
    return _mt._filas(_mt.db.listar_comentarios_tarea(_mt._uid(), tarea_id))


def comentar_tarea(tarea_id: int, texto: str) -> dict:
    """Añade un comentario a una tarea que ves (puedes @mencionar a compañeros del despacho; se les avisa)."""
    uid = _mt._uid()
    if _mt.db.obtener_tarea_outlook_visible(uid, tarea_id) is None:
        raise ValueError(f"No existe la tarea {tarea_id} (o no tienes acceso).")
    resultado = _mt.db.comentar_tarea_outlook(uid, tarea_id, texto)
    if resultado is None:
        raise ValueError("El comentario no puede estar vacío.")
    return {"id": resultado["id"], "comentarios": _mt._filas(_mt.db.listar_comentarios_tarea(uid, tarea_id))[-3:]}


def iniciar_cronometro_tarea(tarea_id: int, proyecto: str | int | None = None) -> dict:
    """Empieza a contar tiempo sobre una tarea de la lista. Si la tarea no tiene proyecto, indica `proyecto` (nombre o id)."""
    uid = _mt._uid()
    if _mt.db.obtener_tarea_outlook_visible(uid, tarea_id) is None:
        raise ValueError(f"No existe la tarea {tarea_id} (o no tienes acceso).")
    categoria = _mt._resolver_categoria_id(proyecto) if proyecto is not None else None
    return {"tarea_cronometro_id": _mt.db.iniciar_cronometro_tarea_outlook(uid, tarea_id, categoria)}


def consumo_ia() -> dict:
    """Consultas de IA que ha usado tu despacho este mes y su tope (o `ilimitado`)."""
    from app import ia_consumo

    tenant = _mt.db.tenant_de_usuario(_mt._uid())
    return ia_consumo.estado(tenant["id"]) if tenant is not None else {"ilimitado": True, "usadas": 0, "limite": None}


def listar_comunicados() -> list[dict]:
    """Avisos vigentes de Guilda para ti (mantenimientos, novedades, incidencias)."""
    from app import comunicados

    tenant = _mt.db.tenant_de_usuario(_mt._uid())
    return comunicados.activos_para(_mt._uid(), tenant["id"] if tenant else None)


def webhooks_entregas(webhook_id: int, limite: int = 20) -> dict:
    """Últimos intentos de entrega de un webhook y lo que sigue en cola (pendiente o fallido). Solo supervisores del despacho."""
    w = _mt.db.obtener_webhook(webhook_id)
    if w is None:
        raise ValueError(f"No existe el webhook {webhook_id}.")
    _mt._exigir_webhooks(w["tenant_id"])
    limite = max(1, min(limite, 100))
    return {"intentos": _mt._filas(_mt.db.entregas_de_webhook(webhook_id, limite)), "cola": _mt.db.cola_webhook_de(webhook_id, limite)}


def resumen_del_dia() -> dict:
    """Todo lo que importa hoy en UNA llamada: «mi día» (vencidas, hoy, en curso, asignadas), vencimientos fiscales de los
    próximos 7 días, correos sin leer y notificaciones sin leer. Úsala para «¿qué tengo hoy?» en vez de varias consultas."""
    from datetime import date, timedelta

    uid = _mt._uid()
    tenant = _mt.db.tenant_de_usuario(uid)
    vencimientos = []
    if tenant is not None:
        hasta = (date.today() + timedelta(days=7)).isoformat()
        vencimientos = _mt._filas(_mt.db.listar_vencimientos_fiscales(tenant["id"], estado="pendiente", hasta=hasta))
    por_cuenta = _mt.db.contar_no_leidos_por_cuenta_y_carpeta(uid)
    return {
        "mi_dia": {seccion: _mt._filas(filas) for seccion, filas in _mt.db.tareas_para_hoy(uid).items()},
        "vencimientos_7_dias": vencimientos,
        "correos_sin_leer": sum(sum(c.values()) for c in por_cuenta.values()),
        "notificaciones_sin_leer": _mt.db.contar_notificaciones_no_leidas(uid),
    }


def detalle_tarea(tarea_id: int) -> dict:
    """Una tarea de la lista con su checklist y su cliente fiscal/correo de origen, en una sola llamada."""
    tarea = _mt.db.obtener_tarea_outlook_visible(_mt._uid(), tarea_id)
    if tarea is None:
        raise ValueError(f"No existe la tarea {tarea_id} (o está en la papelera).")
    return {**_mt._fila(tarea), "checklist": _mt._filas(_mt.db.listar_checklist(tarea_id))}


def completar_tareas(tarea_ids: list[int]) -> dict:
    """Completa varias tareas de una vez (máx. 50). Devuelve cuáles se completaron y cuáles no existen."""
    uid = _mt._uid()
    hechas, fallidas = [], []
    for tarea_id in list(dict.fromkeys(tarea_ids))[:50]:
        if _mt.db.obtener_tarea_outlook(uid, tarea_id) is None:
            fallidas.append(tarea_id)
            continue
        _mt.db.completar_tarea_outlook(uid, tarea_id)
        hechas.append(tarea_id)
    return {"completadas": hechas, "no_encontradas": fallidas}


def listar_notificaciones(limite: int = 20) -> dict:
    """Notificaciones recientes del usuario y cuántas hay sin leer."""
    return {
        "sin_leer": _mt.db.contar_notificaciones_no_leidas(_mt._uid()),
        "notificaciones": _mt._filas(_mt.db.listar_notificaciones(_mt._uid(), max(1, min(limite, 100)))),
    }
