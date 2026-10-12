"""Herramientas MCP del núcleo del despacho: clientes, expedientes, plazos y documentos.

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


# --- Núcleo del despacho: clientes, expedientes y plazos (solo lectura) --------------------------------------------------------------------------
# Sirven igual a la gestoría, al gabinete de abogados y a la inmobiliaria: un inmueble o un asunto es un expediente. Respetan las mismas reglas que
# las pantallas (despacho propio, expedientes confidenciales solo para quien participa o supervisa); la IA y el MCP nunca ven más que la persona.
def _supervisor_actual() -> bool:
    return bool(_mt.db.es_admin(_mt._uid()) or _mt.db.es_supervisor_tenant(_mt._uid()))


def _campos(fila, claves: tuple[str, ...]) -> dict:
    d = dict(fila)
    return {k: d.get(k) for k in claves}


def listar_clientes_despacho(q: str | None = None, limite: int = 25) -> list[dict]:
    """Clientes del despacho (ficha común a gestoría, abogados e inmobiliaria). `q` busca por nombre, NIF, correo, teléfono o contacto."""
    from app import nucleo
    filas, _total = nucleo.listar_clientes(_mt._tenant_id_actual(), q=q, limite=max(1, min(int(limite or 25), 100)))
    return [_mt._campos(f, _mt._CLIENTE_CAMPOS) for f in filas]


def resumen_cliente_despacho(cliente_id: int) -> dict:
    """Todo de un cliente de un vistazo: su ficha, contactos, expedientes visibles para ti, plazos abiertos y horas del último mes."""
    from app import nucleo
    t, u, sup = _mt._tenant_id_actual(), _mt._uid(), _mt._supervisor_actual()
    cliente = nucleo.obtener_cliente(t, cliente_id)
    if cliente is None:
        raise ValueError(f"No existe el cliente #{cliente_id} en tu despacho.")
    exps, total = nucleo.listar_expedientes(t, u, sup, cliente_id=cliente_id, limite=20)
    plazos = nucleo.listar_plazos(t, u, sup, cliente_id=cliente_id, estado="abiertos", limite=20)
    return {
        "cliente": _mt._campos(cliente, _mt._CLIENTE_CAMPOS), "etiquetas": nucleo.etiquetas_de(cliente_id),
        "contactos": [_mt._campos(c, ("nombre", "cargo", "email", "telefono", "rol", "principal")) for c in nucleo.listar_contactos(t, cliente_id)],
        "expedientes": [_mt._campos(x, _mt._EXPEDIENTE_CAMPOS) for x in exps], "total_expedientes": total,
        "plazos_abiertos": [_mt._campos(z, _mt._PLAZO_CAMPOS) for z in plazos],
    }


def listar_expedientes_despacho(cliente_id: int | None = None, estado: str | None = None, tipo: str | None = None, q: str | None = None, limite: int = 25) -> list[dict]:
    """Expedientes del despacho visibles para ti (en abogados, asuntos; en inmobiliaria, operaciones). Filtra por cliente, estado, tipo o texto."""
    from app import nucleo
    filas, _total = nucleo.listar_expedientes(_mt._tenant_id_actual(), _mt._uid(), _mt._supervisor_actual(), cliente_id=cliente_id, estado=estado, tipo=tipo, q=q,
                                              limite=max(1, min(int(limite or 25), 100)))
    return [_mt._campos(f, _mt._EXPEDIENTE_CAMPOS) for f in filas]


def resumen_expediente_despacho(expediente_id: int) -> dict:
    """Un expediente de un vistazo: datos, equipo, plazos abiertos y las últimas anotaciones de su línea de tiempo."""
    from app import nucleo
    t, u, sup = _mt._tenant_id_actual(), _mt._uid(), _mt._supervisor_actual()
    exp = nucleo.obtener_expediente(t, expediente_id, u, sup)
    if exp is None:
        raise ValueError(f"No existe el expediente #{expediente_id} en tu despacho, o no tienes acceso.")
    return {
        "expediente": _mt._campos(exp, _mt._EXPEDIENTE_CAMPOS),
        "equipo": [_mt._campos(m, ("id", "nombre")) for m in nucleo.miembros_de(expediente_id)],
        "plazos_abiertos": [_mt._campos(z, _mt._PLAZO_CAMPOS) for z in nucleo.listar_plazos(t, u, sup, expediente_id=expediente_id, estado="abiertos", limite=20)],
        "ultimas_anotaciones": [_mt._campos(e, ("tipo", "texto", "autor", "creado_en")) for e in nucleo.linea_de_tiempo(t, u, expediente_id, sup, limite=10)],
    }


def listar_plazos_despacho(estado: str = "abiertos", dias: int = 30, cliente_id: int | None = None, expediente_id: int | None = None) -> list[dict]:
    """Plazos del despacho (vencimientos procesales, de contrato, de gestión...) más urgentes primero. `estado`: abiertos, vencido, hoy, proximo, cumplido.
    `dias` limita a los que vencen dentro de ese número de días (0 = sin límite)."""
    from datetime import date, timedelta
    from app import nucleo
    hasta = (date.today() + timedelta(days=int(dias))).isoformat() if dias else None
    filas = nucleo.listar_plazos(_mt._tenant_id_actual(), _mt._uid(), _mt._supervisor_actual(), estado=estado or "abiertos", cliente_id=cliente_id, expediente_id=expediente_id,
                                 hasta=hasta, limite=50)
    return [_mt._campos(z, _mt._PLAZO_CAMPOS) for z in filas]


def _exigir_alcance_documentos() -> None:
    """Una conexión OAuth de terceros (ChatGPT, Claude...) solo toca los documentos si la persona se lo concedió al autorizarla (alcance `guilda:documentos`).
    Los tokens personales se limitan por áreas; la IA interna y el MCP local de escritorio no pasan por aquí."""
    token = _mt.get_access_token()
    if token is not None and token.client_id != "token-personal" and "guilda:documentos" not in (token.scopes or []):
        raise ValueError("Esta conexión no tiene permiso para los documentos del despacho: hay que autorizarla de nuevo concediendo el acceso a documentos.")


def listar_documentos_despacho(cliente_id: int | None = None, expediente_id: int | None = None) -> dict:
    """Documentos de un cliente o de un expediente del despacho (solo nombres y datos, no el contenido). Si el despacho tiene el cifrado activado y está
    bloqueado, lo dice en `aviso`: el contenido no se podrá leer hasta que un responsable lo desbloquee."""
    from app import almacen_documentos, cifrado_despacho
    _mt._exigir_alcance_documentos()
    if cliente_id is None and expediente_id is None:
        raise ValueError("Indica cliente_id o expediente_id.")
    t = _mt._tenant_id_actual()
    docs = almacen_documentos.listar(t, _mt._uid(), cliente_id=cliente_id, expediente_id=expediente_id, limite=100)
    e = cifrado_despacho.estado(t)
    res = {"documentos": [_mt._campos(d, ("id", "nombre_archivo", "tipo_mime", "tamano_bytes", "categoria", "origen", "creado_en", "cifrado")) for d in docs]}
    if e["activo"] and not e["desbloqueado"] and not cifrado_despacho.tiene_concesion(t):
        res["aviso"] = "Los documentos están protegidos y el despacho está bloqueado: un responsable debe desbloquearlos (Seguridad > Cifrado de documentos) para poder leer su contenido."
    return res


def leer_documento_despacho(documento_id: int) -> dict:
    """Texto de un documento del despacho (solo archivos de texto, CSV, JSON o similares; hasta 20.000 caracteres). Si está cifrado y el despacho está
    bloqueado, no se puede leer y se explica por qué. La lectura queda en el registro de accesos."""
    from app import almacen_documentos, cifrado_despacho
    _mt._exigir_alcance_documentos()
    try:
        d = almacen_documentos.leer(_mt._tenant_id_actual(), _mt._uid(), documento_id, via="asistente")
    except cifrado_despacho.DespachoBloqueado as e:
        raise ValueError(str(e)) from e
    if d is None:
        raise ValueError(f"No existe el documento #{documento_id} en tu despacho, o no tienes acceso.")
    mime = (d["tipo_mime"] or "").lower()
    if not (mime.startswith("text/") or mime in ("application/json", "application/xml", "application/csv")):
        raise ValueError(f"«{d['nombre_archivo']}» es un archivo de tipo {mime or 'desconocido'}: solo se puede leer como texto el contenido de archivos de texto.")
    texto = d["contenido"].decode("utf-8", errors="replace")
    return {"id": d["id"], "nombre": d["nombre_archivo"], "texto": texto[:20000], "truncado": len(texto) > 20000}


def listar_plantillas_correo() -> list[dict]:
    """Plantillas de respuesta guardadas del usuario actual (ver Correo >
    Ajustes en la web) -- para poder reutilizar un texto ya escrito antes
    al redactar una respuesta."""
    from app import correo
    return _mt._filas(correo.listar_plantillas(_mt._uid()))


def crear_tarea_recurrente(asunto: str, periodicidad: str, dia: int, categoria_id: int | None = None) -> dict:
    """Crea una regla de tarea recurrente (semanal o mensual) que genera
    una tarea nueva automáticamente cada periodo -- no confundir con
    crear_tarea, que crea una tarea suelta de una sola vez. `periodicidad`:
    "semanal" o "mensual". `dia`: si es semanal, 0=lunes..6=domingo; si es
    mensual, día del mes (1-31, se ajusta al último día si el mes no llega
    a ese número)."""
    if periodicidad not in ("semanal", "mensual"):
        raise ValueError("periodicidad debe ser 'semanal' o 'mensual'.")
    uid = _mt._uid()
    regla_id = _mt.db.crear_tarea_recurrente(uid, asunto, periodicidad, dia, categoria_id=categoria_id)
    return _mt._fila(next((r for r in _mt.db.listar_tareas_recurrentes(uid) if r["id"] == regla_id), None))


def listar_tareas_recurrentes() -> list[dict]:
    """Lista las reglas de tarea recurrente del usuario actual, activas o pausadas."""
    return _mt._filas(_mt.db.listar_tareas_recurrentes(_mt._uid()))


def _facturascripts_de_cliente(cliente_id: int) -> tuple[dict, dict]:
    """Comprueba que el cliente existe en la gestoría del usuario actual y
    está vinculado a FacturaScripts -- compartido por listar/crear factura
    de abajo, para no repetir las mismas dos comprobaciones dos veces."""
    tenant_id = _mt._tenant_id_actual()
    cliente = _mt.db.obtener_cliente_fiscal(tenant_id, cliente_id)
    if cliente is None:
        raise ValueError(f"No existe el cliente fiscal #{cliente_id} en tu gestoría.")
    if not cliente["facturascripts_cliente_codigo"]:
        raise ValueError(f"El cliente #{cliente_id} todavía no está vinculado a FacturaScripts.")
    tenant = _mt.db.obtener_tenant(tenant_id)
    return cliente, tenant


def listar_facturas_cliente(cliente_id: int, limite: int = 20) -> list[dict]:
    """Últimas facturas de FacturaScripts de un cliente fiscal ya vinculado
    (ver "Vincular con FacturaScripts" en su ficha)."""
    from app import facturascripts
    cliente, tenant = _mt._facturascripts_de_cliente(cliente_id)
    return facturascripts.listar_facturas(
        tenant["facturascripts_url"], tenant["facturascripts_api_key"],
        cliente_codigo=cliente["facturascripts_cliente_codigo"], limite=limite,
    )


def crear_factura_cliente(cliente_id: int, concepto: str, importe: float) -> dict:
    """Crea una factura de una sola línea en FacturaScripts para un cliente
    fiscal ya vinculado. Pide siempre confirmación antes de ejecutar (ver
    ESCRITURA en app/ia_herramientas.py) -- nunca se factura sin que el
    usuario haya visto y confirmado el importe exacto."""
    from app import facturascripts
    cliente, tenant = _mt._facturascripts_de_cliente(cliente_id)
    return facturascripts.crear_factura(
        tenant["facturascripts_url"], tenant["facturascripts_api_key"],
        cliente["facturascripts_cliente_codigo"], [{"descripcion": concepto, "cantidad": 1, "precio": importe}],
    )
