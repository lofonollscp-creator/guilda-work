"""Herramientas MCP del fichaje.

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


def fichar(tipo: str) -> dict:
    """Marca un fichaje del usuario actual: tipo = "entrada" | "pausa_inicio"
    | "pausa_fin" | "salida". Lanza un error legible si la secuencia no es
    válida (p.ej. fichar salida sin haber fichado entrada antes)."""
    uid = _mt._uid()
    tenant = _mt.db.tenant_de_usuario(uid)
    if not _mt.db.fichaje_datos_completos(uid):
        raise ValueError("Antes de fichar hace falta rellenar nombre completo y DNI/NIE en Fichaje → Mis datos.")
    fichaje_id = _mt.db.fichar(uid, tenant["id"] if tenant else None, tipo, origen="ia")
    return {"id": fichaje_id, "tipo": tipo, "estado_actual": _mt.db.estado_actual_fichaje(uid)}


def listar_mis_fichajes(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Historial de fichajes del usuario actual, opcionalmente filtrado
    por fecha (YYYY-MM-DD)."""
    return _mt._filas(_mt.db.listar_fichajes(_mt._uid(), desde=desde, hasta=hasta))


# --- Ausencias, vacaciones, turnos y bolsa de horas ------------------------------------------------------------------------------------------
# Mismas reglas que las pantallas y la API (app/ausencias.py, app/turnos.py, app/bolsa_horas.py): las acciones de gestión (aprobar, asignar turnos, ajustar la
# bolsa) solo las puede hacer quien gestiona el fichaje del despacho; la IA y el MCP nunca pueden más que la persona.
def _tenant_fichaje() -> int:
    t = _mt.db.tenant_de_usuario(_mt._uid())
    if t is None:
        raise ValueError("Esta función necesita pertenecer a un despacho.")
    return t["id"]


def _persona(fila) -> dict:
    return {k: v for k, v in dict(fila).items() if k not in ("tenant_id", "creada_por", "resuelta_por")}


def listar_mis_ausencias(anio: int | None = None, estado: str | None = None) -> list[dict]:
    """Tus ausencias, vacaciones y permisos (más recientes primero). `estado`: pendiente, aprobada, rechazada o cancelada."""
    from app import ausencias
    return [_mt._persona(a) for a in ausencias.listar(_mt._tenant_fichaje(), usuario_id=_mt._uid(), anio=anio, estado=estado)]


def saldo_vacaciones(anio: int | None = None) -> dict:
    """Tus días de vacaciones del año: los que te corresponden, los aprobados, los pendientes de aprobar y los que te quedan."""
    from app import ausencias
    return ausencias.saldo(_mt._tenant_fichaje(), _mt._uid(), anio)


def pedir_ausencia(tipo: str, desde: str, hasta: str | None = None, motivo: str | None = None, medio_dia: bool = False, usuario_id: int | None = None) -> dict:
    """Pide una ausencia. `tipo`: vacaciones, asuntos_propios, permiso, baja u otro. `desde`/`hasta` AAAA-MM-DD (sin `hasta`, un solo día). Solo cuentan los días
    laborables y solo las vacaciones gastan saldo. Quien gestiona el fichaje puede indicar `usuario_id` para registrar la de otra persona (queda aprobada)."""
    from app import ausencias
    t = _mt._tenant_fichaje()
    aid = ausencias.solicitar(t, int(usuario_id or _mt._uid()), tipo, desde, hasta, motivo=motivo, medio_dia=bool(medio_dia), por=_mt._uid())
    return _mt._persona(ausencias.obtener(t, aid))


def cancelar_ausencia(ausencia_id: int) -> dict:
    """Cancela una ausencia tuya pendiente o aprobada que no haya terminado (quien gestiona el fichaje, cualquiera del despacho)."""
    from app import ausencias
    t = _mt._tenant_fichaje()
    ausencias.cancelar(t, _mt._uid(), int(ausencia_id))
    return _mt._persona(ausencias.obtener(t, int(ausencia_id)))


def listar_ausencias_equipo(estado: str = "pendiente") -> list[dict]:
    """Solo quien gestiona el fichaje: las ausencias del despacho (por defecto, las pendientes de aprobar)."""
    from app import ausencias
    t = _mt._tenant_fichaje()
    if not ausencias.puede_gestionar(_mt._uid(), t):
        raise ValueError("Solo quien gestiona el fichaje del despacho puede ver las ausencias del equipo.")
    return [_mt._persona(a) | {"persona": a["persona"]} for a in ausencias.listar(t, estado=estado or None)]


def resolver_ausencia(ausencia_id: int, decision: str, comentario: str | None = None) -> dict:
    """Solo quien gestiona el fichaje: `decision` = aprobar o rechazar una ausencia pendiente. Avisa a la persona."""
    from app import ausencias
    t = _mt._tenant_fichaje()
    if decision not in ("aprobar", "rechazar"):
        raise ValueError("`decision` debe ser «aprobar» o «rechazar».")
    ausencias.resolver(t, _mt._uid(), int(ausencia_id), decision == "aprobar", comentario)
    return _mt._persona(ausencias.obtener(t, int(ausencia_id)))


def ver_mis_turnos(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Tus turnos entre dos fechas (por defecto, las próximas dos semanas)."""
    from datetime import date, timedelta
    from app import turnos
    hoy = date.today()
    return turnos.mis_turnos(_mt._tenant_fichaje(), _mt._uid(), desde or hoy.isoformat(), hasta or (hoy + timedelta(days=14)).isoformat())


def ver_cuadrante(desde: str | None = None, hasta: str | None = None) -> dict:
    """El cuadrante de turnos de todo el despacho (quién trabaja qué cada día, y quién está ausente). Por defecto, la semana en curso; máximo 62 días."""
    from datetime import date, timedelta
    from app import turnos
    lunes = turnos.lunes_de(date.today())
    return turnos.cuadrante(_mt._tenant_fichaje(), desde or lunes.isoformat(), hasta or (lunes + timedelta(days=6)).isoformat())


def asignar_turno(usuario_id: int, fecha: str, turno_id: int | None = None) -> dict:
    """Solo quien gestiona el fichaje: asigna un turno a una persona un día (`turno_id` vacío lo quita). Falla si esa persona está ausente ese día. Avisa a la persona.
    Los turnos disponibles se ven con `ver_cuadrante` / en la pantalla de turnos."""
    from app import turnos
    return {"cambiado": turnos.asignar(_mt._tenant_fichaje(), _mt._uid(), int(usuario_id), fecha, int(turno_id) if turno_id else None)}


def ver_bolsa_de_horas(usuario_id: int | None = None, desde: str | None = None, hasta: str | None = None) -> dict:
    """Bolsa de horas (lo trabajado frente a lo que tocaba según la jornada contratada, descontando ausencias aprobadas, más ajustes). Las cifras van en segundos y
    `saldo_seg` positivo es a favor. Por defecto la tuya, del 1 de enero (o tu primer fichaje) hasta ayer; quien gestiona el fichaje puede pedir la de otra persona con `usuario_id`."""
    from app import ausencias, bolsa_horas
    t, yo = _mt._tenant_fichaje(), _mt._uid()
    if usuario_id and int(usuario_id) != yo and not ausencias.puede_gestionar(yo, t):
        raise ValueError("Solo quien gestiona el fichaje puede ver la bolsa de horas de otra persona.")
    return bolsa_horas.calcular(t, int(usuario_id or yo), desde, hasta)


def ajustar_bolsa_de_horas(usuario_id: int, minutos: int, motivo: str, fecha: str | None = None) -> dict:
    """Solo quien gestiona el fichaje: suma (minutos positivos) o resta (negativos) horas a la bolsa de una persona, con motivo. Avisa a la persona."""
    from app import bolsa_horas
    return {"id": bolsa_horas.anadir_ajuste(_mt._tenant_fichaje(), _mt._uid(), int(usuario_id), minutos, motivo, fecha)}
