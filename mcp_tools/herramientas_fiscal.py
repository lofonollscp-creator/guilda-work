"""Herramientas MCP del calendario fiscal.

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


def _tenant_id_actual() -> int:
    tenant = _mt.db.tenant_de_usuario(_mt._uid())
    if tenant is None:
        raise ValueError("Tu usuario no tiene un tenant (gestoría) asignado -- pide a un admin que te asigne uno.")
    return tenant["id"]


def _tenant_actual() -> dict:
    """Fila completa del tenant del usuario actual -- para las tools del
    Asistente IA integrado que necesitan más que el id (p.ej. sus
    api_key de Documenso/Baserow), sin pedirle un parámetro `tenant` al
    LLM como sí hacen las tools MCP crudas (facturas_*/firmas_*/hojas_*)."""
    tenant = _mt.db.obtener_tenant(_mt._tenant_id_actual())
    if tenant is None:
        raise ValueError("Tu usuario no tiene un tenant (gestoría) asignado -- pide a un admin que te asigne uno.")
    return tenant


def _guardar_adjunto_para_chat(nombre_archivo: str, contenido: bytes, tipo_mime: str | None = None) -> dict:
    """Guarda un archivo que una tool le manda al usuario por el chat --
    reutiliza ia_adjuntos (mismo sitio que los adjuntos que sube el propio
    usuario), marcado con origen='asistente'. Nunca devuelve el contenido
    en el resultado de la tool (carísimo en tokens, y el LLM no necesita
    "ver" los bytes) -- solo la referencia para que el frontend pinte un
    chip/preview descargable (ver ia_asistente.js:textoMensajeTool)."""
    if len(contenido) > _mt.TAMANO_MAXIMO_ADJUNTO_ASISTENTE_BYTES:
        raise ValueError(
            f"El archivo '{nombre_archivo}' pesa más de "
            f"{_mt.TAMANO_MAXIMO_ADJUNTO_ASISTENTE_BYTES // (1024 * 1024)}MB, no se puede mandar por el chat."
        )
    if not tipo_mime:
        tipo_mime, _ = mimetypes.guess_type(nombre_archivo)
    adjunto_id = _mt.db.crear_adjunto_ia(_mt._uid(), nombre_archivo, tipo_mime, contenido, origen="asistente")
    return {"adjunto_id": adjunto_id, "nombre_archivo": nombre_archivo, "tipo_mime": tipo_mime or "application/octet-stream"}


def _nombre_archivo_seguro(titulo: str) -> str:
    """Quita caracteres no válidos en nombres de fichero (Windows es el más
    restrictivo, mismo criterio sirve para el resto) -- `titulo` lo pone el
    LLM, no confiar en que ya venga limpio."""
    limpio = titulo.strip().translate(_mt._NOMBRE_ARCHIVO_CARACTERES_INVALIDOS)
    return limpio[:100] or "documento"


def generar_documento_al_chat(
    titulo: str, formato: str, columnas: list[str], filas: list[list], notas: str | None = None,
) -> dict:
    """Genera un documento (csv/xlsx/docx/pdf) a partir de una tabla de
    datos que el propio asistente ya ha reunido con otras tools
    (tareas/correo/fiscal/facturas/CRM/hojas...) y lo manda al chat."""
    from app import generador_documentos as gen
    constructores = {"csv": gen.tabla_a_csv, "xlsx": gen.tabla_a_xlsx, "docx": gen.tabla_a_docx, "pdf": gen.tabla_a_pdf}
    if formato not in constructores:
        raise ValueError(f"Formato '{formato}' no soportado -- usa csv, xlsx, docx o pdf.")
    contenido = constructores[formato](titulo, columnas, filas, notas)
    nombre_archivo = f"{_mt._nombre_archivo_seguro(titulo)}.{formato}"
    return _mt._guardar_adjunto_para_chat(nombre_archivo, contenido, tipo_mime=_mt._FORMATOS_DOCUMENTO[formato])


def listar_clientes_fiscales(q: str | None = None) -> list[dict]:
    """Lista los clientes fiscales de la gestoría del usuario actual.
    `q` filtra por nombre/NIF, opcional."""
    return _mt._filas(_mt.db.listar_clientes_fiscales(_mt._tenant_id_actual(), q=q))


def crear_cliente_fiscal(
    nombre: str, nif: str | None = None, notas: str | None = None, modelos_fiscales: list[str] | None = None,
) -> dict:
    """Da de alta un cliente fiscal. `modelos_fiscales` son los códigos de
    modelo que presenta (ej. ["303", "130"]) -- se usan como valor por
    defecto al generar sus vencimientos."""
    tenant_id = _mt._tenant_id_actual()
    from app import alta_cliente
    cliente_id = _mt.db.crear_cliente_fiscal(tenant_id, nombre, nif=nif, notas=notas, modelos_fiscales=modelos_fiscales)
    alta_cliente.vincular_espocrm(tenant_id, cliente_id, nombre)
    return _mt._fila(_mt.db.obtener_cliente_fiscal(tenant_id, cliente_id))


def listar_vencimientos_fiscales(
    estado: str | None = None, cliente_id: int | None = None, desde: str | None = None, hasta: str | None = None,
) -> list[dict]:
    """Vencimientos fiscales de la gestoría (modelos 303/390/130/111/115/200).
    `estado`: pendiente/presentado/fuera_plazo, opcional."""
    return _mt._filas(_mt.db.listar_vencimientos_fiscales(
        _mt._tenant_id_actual(), desde=desde, hasta=hasta, estado=estado, cliente_fiscal_id=cliente_id,
    ))


def generar_vencimientos_fiscales(cliente_id: int, modelos: list[str], anio: int) -> dict:
    """Genera e inserta directamente los vencimientos de `cliente_id` para
    los `modelos` pedidos (códigos AEAT, ej. ["303","130"]) en el año
    fiscal `anio` -- fechas orientativas, no vinculantes (la AEAT las
    desplaza si caen en fin de semana/festivo). A diferencia de la web
    (que deja revisar/editar cada fecha antes de confirmar), aquí se
    crean tal cual; se pueden ajustar después editando el vencimiento."""
    from app.vencimientos_fiscales import generar_vencimientos_propuestos

    tenant_id = _mt._tenant_id_actual()
    if _mt.db.obtener_cliente_fiscal(tenant_id, cliente_id) is None:
        raise ValueError(f"No existe el cliente fiscal #{cliente_id} en tu gestoría.")
    creados = []
    for propuesta in generar_vencimientos_propuestos(modelos, anio):
        vid = _mt.db.crear_vencimiento_fiscal(
            tenant_id, cliente_id, propuesta["modelo"], propuesta["periodo"], propuesta["fecha_limite"],
        )
        creados.append(_mt._fila(_mt.db.obtener_vencimiento_fiscal(tenant_id, vid)))
    return {"creados": len(creados), "vencimientos": creados}


def marcar_presentado_vencimiento_fiscal(vencimiento_id: int) -> dict:
    """Marca un vencimiento fiscal como presentado."""
    from app import obligaciones
    tenant_id = _mt._tenant_id_actual()
    v = _mt.db.obtener_vencimiento_fiscal(tenant_id, vencimiento_id)
    if v is None:
        raise ValueError(f"No existe el vencimiento #{vencimiento_id} en tu gestoría.")
    obligaciones.exigir_para_marcar_presentado(tenant_id, _mt._uid(), v)             # respeta el flujo del despacho (estricto, justificante obligatorio)
    _mt.db.marcar_presentado_vencimiento_fiscal(tenant_id, vencimiento_id, _mt._uid())
    return _mt._fila(_mt.db.obtener_vencimiento_fiscal(tenant_id, vencimiento_id))


def editar_vencimiento_fiscal(
    vencimiento_id: int, modelo: str | None = None, periodo: str | None = None,
    fecha_limite: str | None = None, estado: str | None = None, notas: str | None = None,
) -> dict:
    """Edita los campos indicados (los que se omitan no cambian) de un
    vencimiento fiscal ya existente."""
    from app import obligaciones
    tenant_id = _mt._tenant_id_actual()
    actual = _mt.db.obtener_vencimiento_fiscal(tenant_id, vencimiento_id)
    if actual is None:
        raise ValueError(f"No existe el vencimiento #{vencimiento_id} en tu gestoría.")
    obligaciones.exigir_para_cambiar_estado(tenant_id, _mt._uid(), actual, estado)
    campos = {
        k: v for k, v in {
            "modelo": modelo, "periodo": periodo, "fecha_limite": fecha_limite,
            "estado": estado, "notas": notas,
        }.items() if v is not None
    }
    _mt.db.editar_vencimiento_fiscal(tenant_id, vencimiento_id, **campos)
    return _mt._fila(_mt.db.obtener_vencimiento_fiscal(tenant_id, vencimiento_id))


def resumen_cliente_fiscal(cliente_id: int) -> dict:
    """Resumen agregado de un cliente fiscal: sus vencimientos (con
    estado), y cuántos documentos/mensajes hay en total en el portal de
    cliente para cada uno -- para responder de un vistazo "¿cómo va
    fulanito?" sin tener que consultar vencimiento a vencimiento."""
    tenant_id = _mt._tenant_id_actual()
    cliente = _mt.db.obtener_cliente_fiscal(tenant_id, cliente_id)
    if cliente is None:
        raise ValueError(f"No existe el cliente fiscal #{cliente_id} en tu gestoría.")
    vencimientos = _mt.db.listar_vencimientos_fiscales(tenant_id, cliente_fiscal_id=cliente_id)
    total_documentos = 0
    total_mensajes = 0
    detalle = []
    for v in vencimientos:
        documentos = _mt.db.listar_documentos_vencimiento(v["id"])
        mensajes = _mt.db.listar_mensajes_vencimiento(v["id"])
        total_documentos += len(documentos)
        total_mensajes += len(mensajes)
        detalle.append({
            "id": v["id"], "modelo": v["modelo"], "periodo": v["periodo"],
            "fecha_limite": v["fecha_limite"], "estado": v["estado"],
            "documentos": len(documentos), "mensajes": len(mensajes),
        })
    return {
        "cliente": _mt._fila(cliente),
        "total_vencimientos": len(vencimientos),
        "pendientes": sum(1 for v in vencimientos if v["estado"] == "pendiente"),
        "fuera_de_plazo": sum(1 for v in vencimientos if v["estado"] == "fuera_plazo"),
        "total_documentos": total_documentos,
        "total_mensajes": total_mensajes,
        "vencimientos": detalle,
    }
