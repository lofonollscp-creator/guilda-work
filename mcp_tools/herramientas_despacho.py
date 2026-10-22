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


# --- Certificados digitales (solo lectura; solo custodios y supervisores del despacho) -------------------------------------------------------
_CERT_CAMPOS = ("id", "nombre_comun", "sujeto", "emisor", "numero_serie", "not_before", "not_after", "temporal", "dias_restantes", "estado_operativo", "renovacion", "vinculos_activos",
                "nif_sugerido", "nif_confirmado", "custodio_nombre", "pendiente_de_comprobar")


def _exigir_certificados() -> int:
    from app import certificados
    t = _mt._tenant_id_actual()
    if not certificados.puede_gestionar(_mt._uid(), t):
        raise ValueError("Solo los custodios de certificados y los supervisores del despacho pueden consultar los certificados.")
    return t


def listar_certificados(q: str | None = None, temporal: str | None = None) -> list[dict]:
    """Certificados digitales del despacho, los más próximos a caducar primero. `temporal`: vigente, caducado o todavia_no_vigente. Cadena y revocación aparecen como «no comprobada»
    si nadie las ha comprobado: una fecha vigente no acredita que el certificado sea utilizable."""
    from app import certificados
    t = _mt._exigir_certificados()
    return [{**_mt._campos(c, _mt._CERT_CAMPOS), "cadena": c["cadena"]["resultado"], "revocacion": c["revocacion"]["resultado"], "clave": c["clave"]["resultado"]}
            for c in certificados.listar(t, q=q or None, temporal=temporal or None)[:50]]


def riesgos_de_certificados(dias: int = 90) -> list[dict]:
    """Obligaciones fiscales pendientes cuyo certificado caduca antes del vencimiento, está suspendido o no está registrado (cobertura desconocida)."""
    from app import certificados
    return certificados.riesgos(_mt._exigir_certificados(), horizonte_dias=max(1, min(int(dias or 90), 365)))[:100]


def registrar_certificado(tipo: str, caduca: str | None = None, cliente_id: int | None = None, titular: str | None = None, emitido: str | None = None, avisar_cliente: bool | None = None) -> dict:
    """Apunta un certificado digital SIN archivo (de quién es, tipo y caducidad). `tipo`: fnmt_persona_fisica, fnmt_representante, fnmt_representante_sin_personalidad, dnie, accv, izenpe, camerfirma,
    firmaprofesional u otro. `caduca` AAAA-MM-DD (o `emitido`, para proponer la habitual del tipo). `cliente_id` es el cliente fiscal; sin él, indica `titular`. Solo custodios y supervisores."""
    from app import certificados
    t = _mt._exigir_certificados()
    r = certificados.alta_rapida(t, _mt._uid(), tipo=tipo, caduca=caduca, emitido=emitido, cliente_fiscal_id=cliente_id, titular=titular, avisar_cliente=avisar_cliente)
    c = certificados.obtener(t, r["id"])
    return {"id": r["id"], "nuevo": r["nuevo"], **{k: c[k] for k in ("cliente_nombre", "nombre_comun", "tipo_certificado", "caduca_el", "dias_restantes")}}


def renovar_certificado(certificado_id: int, nueva_caducidad: str, funciona: bool = False) -> dict:
    """«Ya está renovado»: apunta la nueva caducidad. El certificado nuevo hereda cliente, tipo, custodio y servicios; el anterior pasa a «sustituido». Si daba servicio a algún cliente hay que confirmar
    con `funciona` que el nuevo funciona. Solo custodios y supervisores."""
    from app import certificados
    t = _mt._exigir_certificados()
    r = certificados.renovado(t, _mt._uid(), int(certificado_id), nueva_caducidad, funciona=bool(funciona))
    return {"id": r["id"], "anterior_id": r["anterior_id"], "caduca_el": certificados.obtener(t, r["id"])["caduca_el"]}


def comprobar_certificado(certificado_id: int) -> dict:
    """Comprueba ahora la cadena de confianza y la revocación (OCSP y CRL) de un certificado con archivo, y lo anota como evaluación automática. Hace consultas a las direcciones que el propio
    certificado declara. Ante un fallo de red o una CA desconocida el resultado es «indeterminada», nunca «válida». Solo custodios y supervisores."""
    from app import certificados
    t = _mt._exigir_certificados()
    certificados.comprobar_ahora(t, _mt._uid(), int(certificado_id))
    c = certificados.obtener(t, int(certificado_id))
    return {"id": c["id"], "cadena": c["cadena"], "revocacion": c["revocacion"], "temporal": c.get("temporal")}


def _exigir_gestoria() -> int:
    from app import verticales
    t = _mt._tenant_id_actual()
    if not verticales.esta_activo(t, "gestoria"):
        raise ValueError("El control fiscal solo está disponible para gestorías.")
    return t


def panel_fiscal() -> dict:
    """Qué mirar hoy en el despacho, en el ámbito de quien pregunta: obligaciones vencidas sin presentar, las que vencen en 7 días, bloqueadas, para revisar, traspasos sin aceptar, riesgos de
    certificados (solo custodios y supervisores), reparto de carga por responsable y oficina e indicadores con su muestra. Cada elemento trae su causa. Un indicador sin datos es `null`, no 100 %."""
    from app import panel_fiscal as _panel
    t = _mt._exigir_gestoria()
    p = _panel.construir(t, _mt._uid())
    return {k: p[k] for k in ("generado_en", "ambito", "totales", "hoy_lista", "bloqueadas", "traspasos", "riesgos_certificados", "carga_por_responsable", "carga_por_oficina", "indicadores")}


def listar_traspasos(estado: str | None = None) -> list[dict]:
    """Traspasos de clientes entre personas u oficinas. `estado`: pendiente, aceptado, rechazado o cancelado."""
    from app import traspasos
    t = _mt._exigir_gestoria()
    if estado and estado not in traspasos.ESTADOS:
        raise ValueError("Estado no válido: pendiente, aceptado, rechazado o cancelado.")
    campos = ("id", "cliente", "cliente_fiscal_id", "de_nombre", "a_nombre", "a_oficina", "estado", "nota", "motivo", "proximo_vencimiento", "creado_en", "version")
    return [{k: x[k] for k in campos} for x in traspasos.listar(t, _mt._uid(), estado=estado or None)]


def proponer_traspaso(cliente_id: int, a_usuario_id: int, a_oficina_id: int | None = None, nota: str | None = None) -> dict:
    """Propone pasar un cliente fiscal a otra persona del despacho (y, si se indica, a otra oficina). Hasta que lo acepte, el cliente sigue siendo de quien lo lleva ahora."""
    from app import traspasos
    t = _mt._exigir_gestoria()
    nuevo = traspasos.proponer(t, _mt._uid(), int(cliente_id), int(a_usuario_id), a_oficina_id=int(a_oficina_id) if a_oficina_id else None, nota=nota)
    x = traspasos.obtener(t, nuevo)
    return {"id": nuevo, "cliente": x["cliente"], "a_nombre": x["a_nombre"], "estado": x["estado"]}


def resolver_traspaso(traspaso_id: int, accion: str, motivo: str | None = None) -> dict:
    """Resuelve un traspaso: `aceptar` (quien lo recibe o la dirección), `rechazar` (con `motivo`) o `cancelar` (quien lo propuso o la dirección)."""
    from app import traspasos
    t = _mt._exigir_gestoria()
    uid = _mt._uid()
    if accion == "aceptar":
        traspasos.aceptar(t, uid, int(traspaso_id))
    elif accion == "rechazar":
        traspasos.rechazar(t, uid, int(traspaso_id), motivo or "")
    elif accion == "cancelar":
        traspasos.cancelar(t, uid, int(traspaso_id))
    else:
        raise ValueError("Acción no válida: aceptar, rechazar o cancelar.")
    x = traspasos.obtener(t, int(traspaso_id))
    return {"id": x["id"], "cliente": x["cliente"], "estado": x["estado"]}


def listar_avisos_fiscales(estado: str = "abierta", solo_mios: bool = False) -> list[dict]:
    """Avisos del control fiscal (obligaciones vencidas o a punto de vencer, bloqueadas con el plazo cerca, traspasos sin aceptar, certificados a punto de caducar). `estado`: abierta (sin atender), acusada o resuelta."""
    from app import avisos
    t = _mt._exigir_gestoria()
    if estado not in avisos.ESTADOS:
        raise ValueError("Estado no válido: abierta, acusada o resuelta.")
    campos = ("id", "tipo", "severidad", "titulo", "detalle", "cliente", "destinatario", "nivel", "estado", "horas_abierta", "acusada_por_nombre", "nota_acuse", "url")
    return [{k: a[k] for k in campos} for a in avisos.listar(t, _mt._uid(), estado=estado) if not solo_mios or a["destinatario_id"] == _mt._uid()]


def acusar_aviso_fiscal(aviso_id: int, nota: str | None = None) -> dict:
    """«Lo he visto, lo llevo»: el aviso deja de repetirse y de escalar. NO presenta ni cierra la obligación."""
    from app import avisos
    t = _mt._exigir_gestoria()
    avisos.acusar(t, _mt._uid(), int(aviso_id), nota)
    a = avisos.obtener(t, int(aviso_id))
    return {"id": a["id"], "estado": a["estado"], "titulo": a["titulo"], "cliente": a["cliente"]}


def listar_expedientes_control(estado: str | None = None, tipo: str | None = None, incluir_cerrados: bool = False) -> list[dict]:
    """Expedientes de control fiscal (campaña, obligación, renovación, requerimiento, incidencia) con su avance, prioridad y fecha objetivo. Estados: abierto, en_curso, pendiente_cliente,
    pendiente_tercero, en_revision, resuelto, cerrado."""
    from app import control_expedientes as ce
    t = _mt._exigir_gestoria()
    if tipo and tipo not in ce.IDS_TIPOS:
        raise ValueError("Tipo no válido: " + ", ".join(ce.IDS_TIPOS) + ".")
    campos = ("id", "tipo", "titulo", "estado", "cliente", "prioridad", "fecha_objetivo", "puntos", "puntos_hechos", "obligatorios_pendientes")
    return [{k: x[k] for k in campos} for x in ce.listar(t, _mt._uid(), estado=estado, tipo=tipo, solo_abiertos=not incluir_cerrados)]


def ver_expediente_control(expediente_id: int) -> dict:
    """Ficha de un expediente de control: datos, lista de comprobación (con lo obligatorio que falta para cerrar) y documentos con sus versiones."""
    from app import control_expedientes as ce
    t = _mt._exigir_gestoria()
    d = ce.detalle(t, _mt._uid(), int(expediente_id))
    return {**{k: d[k] for k in ("id", "tipo", "titulo", "estado", "cliente", "responsable", "faltan_obligatorios")}, "control": d["control"],
            "lista": [{k: p[k] for k in ("id", "texto", "obligatorio", "asignado", "fecha_limite", "hecho_en")} for p in d["lista"]],
            "documentos": [{"id": x["id"], "nombre": x["nombre_archivo"], "version": x["version"], "conservar_hasta": x["conservar_hasta"]} for x in d["documentos"]]}


def abrir_expediente_control(tipo: str | None = None, titulo: str | None = None, cliente_fiscal_id: int | None = None, obligacion_id: int | None = None, prioridad: str = "normal",
                             fecha_objetivo: str | None = None) -> dict:
    """Abre un expediente de control. Para una obligación existente indica `obligacion_id` (se reutiliza el que ya esté abierto). Si no, `cliente_fiscal_id`, `tipo` (control_campana, control_obligacion,
    control_renovacion, control_requerimiento o control_incidencia) y `titulo`."""
    from app import acceso, control_expedientes as ce, nucleo
    t = _mt._exigir_gestoria()
    uid = _mt._uid()
    if obligacion_id:
        r = ce.abrir_desde_obligacion(t, uid, int(obligacion_id))
        return {"id": r["id"], "nuevo": r["nuevo"]}
    if not cliente_fiscal_id or not acceso.puede_modificar_cliente(t, uid, int(cliente_fiscal_id)):
        raise ValueError("Indica un cliente fiscal que exista (o una obligación).")
    nuevo = ce.crear(t, uid, nucleo.vincular_cliente_fiscal(t, int(cliente_fiscal_id)), tipo or "", titulo or "", prioridad=prioridad, fecha_objetivo=fecha_objetivo)
    return {"id": nuevo, "nuevo": True}


def marcar_punto_expediente(punto_id: int, hecho: bool = True, nota: str | None = None) -> dict:
    """Marca un punto de la lista de comprobación de un expediente como hecho (o lo reabre con hecho=false)."""
    from app import control_expedientes as ce
    t = _mt._exigir_gestoria()
    ce.marcar_punto(t, _mt._uid(), int(punto_id), bool(hecho), nota)
    return {"id": int(punto_id), "hecho": bool(hecho)}


def cambiar_estado_expediente_control(expediente_id: int, estado: str, excepcion: str | None = None) -> dict:
    """Cambia el estado de un expediente de control. Cerrar exige completar los puntos obligatorios o una `excepcion` (motivo) que solo autoriza la dirección o un revisor fiscal."""
    from app import control_expedientes as ce, nucleo
    t = _mt._exigir_gestoria()
    uid = _mt._uid()
    ce._exp(t, uid, int(expediente_id))
    nucleo.cambiar_estado_expediente(t, uid, int(expediente_id), estado, bool(_mt.db.es_supervisor_tenant(uid)), excepcion=excepcion)
    x = ce.detalle(t, uid, int(expediente_id))
    return {"id": x["id"], "estado": x["estado"], "faltan_obligatorios": x["faltan_obligatorios"]}


def comentar_expediente_control(expediente_id: int, texto: str) -> dict:
    """Añade un comentario a un expediente de control. No puede llevar contraseñas ni claves. `@nombre` avisa solo a quien puede ver el expediente."""
    from app import control_expedientes as ce, nucleo
    t = _mt._exigir_gestoria()
    uid = _mt._uid()
    ce._exp(t, uid, int(expediente_id))
    r = nucleo.anotar_expediente(t, uid, int(expediente_id), texto, bool(_mt.db.es_supervisor_tenant(uid))) or {}
    return {"avisadas": r.get("avisadas", []), "sin_acceso": r.get("sin_acceso", []), "no_encontradas": r.get("no_encontradas", [])}
