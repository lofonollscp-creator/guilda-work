"""API del control fiscal (fase A): flujo de trabajo de las obligaciones, indicadores, evidencias, auditoría, oficinas, roles y concesiones. Área de token: `fiscal`.
Capa fina sobre `obligaciones.py`, `acceso.py` y `auditoria.py`: mismas reglas que la web. Concurrencia: `If-Match: "<version>"` (o `version` en el cuerpo) → 412 si cambió."""
from flask import abort, g, request

from . import acceso, auditoria, db, obligaciones
from .auth import token_required
from .rutas_api import _body, _dict, _err, _exigir_tenant_api, _ok, _ok_paginado, api_bp


def _version_esperada(datos: dict | None = None) -> int | None:
    """La versión que quien llama dice haber leído: cabecera `If-Match` (con o sin comillas) o campo `version` del cuerpo."""
    crudo = (request.headers.get("If-Match") or "").strip()
    if crudo.startswith("W/"):
        crudo = crudo[2:]
    crudo = crudo.strip('"')
    if crudo.isdigit():
        return int(crudo)
    v = (datos or {}).get("version")
    return int(v) if isinstance(v, int) or (isinstance(v, str) and v.isdigit()) else None


def _conflicto(e: Exception):
    return _err(str(e), 412, "version_obsoleta")


def _vencimiento_o_404(vencimiento_id: int):
    v = db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id)
    if v is None:
        abort(404, "Vencimiento no encontrado.")
    return v


def _exigir_direccion() -> None:
    if not acceso.es_directivo(g.usuario_id):
        abort(403, "Solo la dirección del despacho (supervisores) puede hacer esto.")


# --- Flujo de trabajo -----------------------------------------------------------------------------------------------------------------------

@api_bp.route("/fiscal/vencimientos/<int:vencimiento_id>/flujo", methods=["GET"])
@token_required
def flujo_vencimiento(vencimiento_id: int):
    """Fase de trabajo de la obligación, sus indicadores (`vencida`, `en_riesgo`, `bloqueada`, `presentada_tarde`), las fases a las que TÚ puedes moverla ahora, las evidencias de presentación
    y la configuración de flujo del despacho. `version` es el valor para `If-Match`."""
    error = _exigir_tenant_api()
    if error:
        return error
    v = _vencimiento_o_404(vencimiento_id)
    return _ok(obligaciones.resumen(g.tenant_id, g.usuario_id, v))


@api_bp.route("/fiscal/vencimientos/<int:vencimiento_id>/transiciones", methods=["POST"])
@token_required
def transicionar_vencimiento(vencimiento_id: int):
    """Mueve la obligación de fase. Cuerpo: `{"destino": "presentada", "motivo": "...", "presentacion": {"presentado_en": "2026-10-13T09:15", "organismo": "AEAT", "referencia": "CSV...", "documento_id": 5}, "version": 3}`.
    `destino`: `en_preparacion`, `en_revision`, `aprobada`, `presentada`, `cerrada`, `no_aplica`, `anulada` o `pendiente`. Aprobar y declarar «no aplica» o «anulada» es de la dirección o el revisor fiscal
    (esas dos, con motivo); devolver a preparación exige motivo. Una presentación queda como **declarada por quien la registra**, no como confirmada. 400 si no se puede; 412 si la `version` ya cambió."""
    error = _exigir_tenant_api()
    if error:
        return error
    _vencimiento_o_404(vencimiento_id)
    datos = _body()
    try:
        r = obligaciones.transicionar(g.tenant_id, g.usuario_id, vencimiento_id, datos.get("destino", ""), motivo=datos.get("motivo"), presentacion=datos.get("presentacion"), version=_version_esperada(datos))
    except obligaciones.ConflictoDeVersion as e:
        return _conflicto(e)
    except ValueError as e:
        return _err(str(e), 400, "transicion_invalida")
    return _ok(r)


@api_bp.route("/fiscal/vencimientos/<int:vencimiento_id>/bloqueo", methods=["PUT"])
@token_required
def bloquear_vencimiento(vencimiento_id: int):
    """Marca o quita el bloqueo (indicador, no fase): `{"bloqueada": true, "motivo": "Esperando los extractos del banco"}`. Un bloqueo no detiene el plazo legal."""
    error = _exigir_tenant_api()
    if error:
        return error
    _vencimiento_o_404(vencimiento_id)
    datos = _body()
    try:
        obligaciones.bloquear(g.tenant_id, g.usuario_id, vencimiento_id, datos.get("motivo"), bloqueada=bool(datos.get("bloqueada", True)))
    except ValueError as e:
        return _err(str(e), 400, "bloqueo_invalido")
    return _ok(obligaciones.resumen(g.tenant_id, g.usuario_id, db.obtener_vencimiento_fiscal(g.tenant_id, vencimiento_id)))


@api_bp.route("/fiscal/flujo", methods=["GET"])
@token_required
def configuracion_flujo():
    """Cómo trabaja el despacho las obligaciones: `flujo_estricto` (revisión y aprobación obligatorias) y `exigir_justificante` (sin justificante no se presenta ni se cierra)."""
    error = _exigir_tenant_api()
    if error:
        return error
    return _ok(obligaciones.config(g.tenant_id))


@api_bp.route("/fiscal/flujo", methods=["PUT"])
@token_required
def guardar_configuracion_flujo():
    """Solo la dirección del despacho. Cuerpo: `{"flujo_estricto": true, "exigir_justificante": false}`."""
    error = _exigir_tenant_api()
    if error:
        return error
    _exigir_direccion()
    d = _body()
    actual = obligaciones.config(g.tenant_id)
    obligaciones.guardar_config(g.tenant_id, g.usuario_id, flujo_estricto=bool(d.get("flujo_estricto", actual["flujo_estricto"])), exigir_justificante=bool(d.get("exigir_justificante", actual["exigir_justificante"])))
    return _ok(obligaciones.config(g.tenant_id))


# --- Auditoría -----------------------------------------------------------------------------------------------------------------------------

@api_bp.route("/fiscal/auditoria", methods=["GET"])
@token_required
def eventos_de_auditoria():
    """Eventos de auditoría del despacho (solo de anexado), los más recientes primero. Solo la dirección, los auditores y los revisores fiscales. Filtros: `entidad`
    (`obligacion`, `certificado`, `cliente_fiscal`, `oficina`, `usuario`…), `entidad_id`, `usuario_id`, `accion`, `desde`, `hasta`; paginación por cursor con `antes_de_id` y `limite` (100 por defecto)."""
    error = _exigir_tenant_api()
    if error:
        return error
    if not (acceso.roles_de(g.tenant_id, g.usuario_id) & {"director", "auditor", "revisor_fiscal"}):
        abort(403, "Solo la dirección, los auditores y los revisores fiscales pueden consultar la auditoría.")
    a = request.args
    return _ok_paginado(auditoria.listar(g.tenant_id, entidad=a.get("entidad"), entidad_id=a.get("entidad_id"), usuario_id=a.get("usuario_id", type=int), accion=a.get("accion"),
                                         desde=a.get("desde"), hasta=a.get("hasta"), antes_de_id=a.get("antes_de_id", type=int), limite=a.get("limite", 100, type=int)))


# --- Oficinas, roles y concesiones ----------------------------------------------------------------------------------------------------------

@api_bp.route("/fiscal/oficinas", methods=["GET"])
@token_required
def listar_oficinas_api():
    """Oficinas del despacho con el número de clientes y de personas de cada una."""
    error = _exigir_tenant_api()
    if error:
        return error
    return _ok_paginado(acceso.listar_oficinas(g.tenant_id))


@api_bp.route("/fiscal/oficinas", methods=["POST"])
@token_required
def crear_oficina_api():
    """Solo la dirección. Cuerpo: `{"nombre": "Girona"}`. Al crear la primera oficina el despacho empieza a repartir sus clientes: los que no tengan oficina los sigue viendo todo el equipo."""
    error = _exigir_tenant_api()
    if error:
        return error
    try:
        oid = acceso.crear_oficina(g.tenant_id, g.usuario_id, _body().get("nombre", ""))
    except ValueError as e:
        return _err(str(e), 403 if "Solo la dirección" in str(e) else 400, "oficina_invalida")
    return _ok({"id": oid}, 201)


@api_bp.route("/fiscal/oficinas/<int:oficina_id>/archivar", methods=["POST"])
@token_required
def archivar_oficina_api(oficina_id: int):
    """Solo la dirección; la oficina no puede tener clientes (reasígnalos antes)."""
    error = _exigir_tenant_api()
    if error:
        return error
    try:
        acceso.archivar_oficina(g.tenant_id, g.usuario_id, oficina_id)
    except ValueError as e:
        return _err(str(e), 403 if "Solo la dirección" in str(e) else 409, "oficina_no_archivable")
    return _ok({"archivada": True})


@api_bp.route("/fiscal/clientes/<int:cliente_id>/oficina", methods=["PUT"])
@token_required
def asignar_oficina_api(cliente_id: int):
    """Fija la oficina principal del cliente: `{"oficina_id": 3}` (`null` la quita). La dirección, o quien coordina las oficinas implicadas."""
    error = _exigir_tenant_api()
    if error:
        return error
    if db.obtener_cliente_fiscal(g.tenant_id, cliente_id) is None:
        abort(404, "Cliente fiscal no encontrado.")
    try:
        acceso.asignar_cliente_a_oficina(g.tenant_id, g.usuario_id, cliente_id, _body().get("oficina_id"))
    except ValueError as e:
        return _err(str(e), 403 if "Solo la dirección" in str(e) else 400, "oficina_invalida")
    return _ok(_dict(db.obtener_cliente_fiscal(g.tenant_id, cliente_id)))


@api_bp.route("/fiscal/clientes/<int:cliente_id>/concesiones", methods=["GET"])
@token_required
def listar_concesiones_api(cliente_id: int):
    error = _exigir_tenant_api()
    if error:
        return error
    if db.obtener_cliente_fiscal(g.tenant_id, cliente_id) is None:
        abort(404, "Cliente fiscal no encontrado.")
    return _ok_paginado(acceso.concesiones_de(g.tenant_id, cliente_id))


@api_bp.route("/fiscal/clientes/<int:cliente_id>/concesiones", methods=["POST"])
@token_required
def conceder_cliente_api(cliente_id: int):
    """Comparte el cliente con otra oficina (`oficina_id`) o con una persona (`usuario_id`): `{"usuario_id": 7, "nivel": "lectura", "hasta": "2026-12-31"}`. Con vigencia opcional; se puede retirar."""
    error = _exigir_tenant_api()
    if error:
        return error
    if db.obtener_cliente_fiscal(g.tenant_id, cliente_id) is None:
        abort(404, "Cliente fiscal no encontrado.")
    d = _body()
    try:
        kid = acceso.conceder_cliente(g.tenant_id, g.usuario_id, cliente_id, oficina_id=d.get("oficina_id"), para_usuario_id=d.get("usuario_id"), nivel=d.get("nivel", "gestion"), hasta=d.get("hasta"))
    except ValueError as e:
        return _err(str(e), 403 if "Solo la dirección" in str(e) else 400, "concesion_invalida")
    return _ok({"id": kid}, 201)


@api_bp.route("/fiscal/concesiones/<int:concesion_id>", methods=["DELETE"])
@token_required
def revocar_concesion_api(concesion_id: int):
    error = _exigir_tenant_api()
    if error:
        return error
    try:
        acceso.revocar_concesion(g.tenant_id, g.usuario_id, concesion_id)
    except ValueError as e:
        return _err(str(e), 403 if "Solo la dirección" in str(e) else 404, "concesion_no_revocable")
    return _ok({"revocada": True})


@api_bp.route("/fiscal/membresias", methods=["GET"])
@token_required
def listar_membresias_api():
    """Roles con alcance del despacho (coordinador, gestor, revisor fiscal, auditor). Solo la dirección y los coordinadores."""
    error = _exigir_tenant_api()
    if error:
        return error
    if not (acceso.roles_de(g.tenant_id, g.usuario_id) & {"director", "coordinador"}):
        abort(403, "Solo la dirección y los coordinadores pueden ver los roles del despacho.")
    return _ok_paginado(acceso.membresias_del_despacho(g.tenant_id))


@api_bp.route("/fiscal/membresias", methods=["POST"])
@token_required
def dar_membresia_api():
    """Da un rol con alcance: `{"usuario_id": 7, "rol": "gestor", "alcance": "oficina", "alcance_id": 3, "hasta": "2026-12-31"}`. Roles: `coordinador` (de una oficina), `gestor`, `revisor_fiscal` (de toda
    la organización) y `auditor` (solo lectura). La dirección puede todo; un coordinador puede dar gestor o auditor en su oficina."""
    error = _exigir_tenant_api()
    if error:
        return error
    d = _body()
    try:
        mid = acceso.dar_membresia(g.tenant_id, g.usuario_id, d.get("usuario_id") or 0, d.get("rol", ""), d.get("alcance", ""), d.get("alcance_id"), d.get("hasta"))
    except ValueError as e:
        return _err(str(e), 403 if "Solo la dirección" in str(e) else 400, "membresia_invalida")
    return _ok({"id": mid}, 201)


@api_bp.route("/fiscal/membresias/<int:membresia_id>", methods=["DELETE"])
@token_required
def revocar_membresia_api(membresia_id: int):
    error = _exigir_tenant_api()
    if error:
        return error
    try:
        acceso.revocar_membresia(g.tenant_id, g.usuario_id, membresia_id)
    except ValueError as e:
        return _err(str(e), 403 if "Solo la dirección" in str(e) else 404, "membresia_no_revocable")
    return _ok({"revocada": True})


# --- Panel y traspasos (fase E) ---------------------------------------------------------------------------------------------------------------
@api_bp.route("/fiscal/panel", methods=["GET"])
@token_required
def panel_fiscal_api():
    """Qué mirar hoy y cómo va el despacho, en el ámbito de quien consulta: vencidas, próximas (7 días), bloqueadas, obligaciones para revisar, traspasos sin aceptar, riesgos de certificados
    (solo custodios y supervisores), reparto por responsable y oficina e indicadores. Cada elemento trae su `causa`; los indicadores traen tamaño de muestra y exclusiones, y un porcentaje
    sin muestra es `null` (nunca 100 %). No promete ausencia de sanciones."""
    error = _exigir_tenant_api()
    if error:
        return error
    from . import panel_fiscal
    return _ok(panel_fiscal.construir(g.tenant_id, g.usuario_id))


@api_bp.route("/fiscal/traspasos", methods=["GET"])
@token_required
def listar_traspasos_api():
    """Traspasos de clientes visibles para quien consulta. Filtro opcional `estado`: `pendiente`, `aceptado`, `rechazado` o `cancelado`."""
    error = _exigir_tenant_api()
    if error:
        return error
    from . import traspasos
    estado = request.args.get("estado")
    if estado and estado not in traspasos.ESTADOS:
        return _err("Estado no válido.", 400, "traspaso_no_valido")
    return _ok_paginado(traspasos.listar(g.tenant_id, g.usuario_id, estado=estado or None))


@api_bp.route("/fiscal/traspasos", methods=["POST"])
@token_required
def proponer_traspaso_api():
    """Propone pasar un cliente a otra persona: `{"cliente_id": 12, "a_usuario_id": 5, "a_oficina_id": 2, "nota": "Falta el 303 del T3"}`. Hasta que lo acepte, el responsable anterior
    conserva el cliente. Solo uno pendiente por cliente (409 si ya hay otro)."""
    error = _exigir_tenant_api()
    if error:
        return error
    from . import traspasos
    d = _body()
    try:
        nuevo = traspasos.proponer(g.tenant_id, g.usuario_id, int(d.get("cliente_id") or 0), int(d.get("a_usuario_id") or 0), a_oficina_id=int(d["a_oficina_id"]) if d.get("a_oficina_id") else None, nota=d.get("nota"))
    except (ValueError, TypeError) as e:
        return _err(str(e), 409 if "pendiente de aceptar" in str(e) else 400, "traspaso_no_valido")
    return _ok(traspasos.obtener(g.tenant_id, nuevo), 201)


def _resolver_traspaso(traspaso_id: int, funcion, *a):
    from . import traspasos
    if traspasos.obtener(g.tenant_id, traspaso_id) is None:
        abort(404, "Traspaso no encontrado.")
    try:
        funcion(g.tenant_id, g.usuario_id, traspaso_id, *a, version=_version_esperada(_body()))
    except traspasos.ConflictoDeVersion as e:
        return _conflicto(e)
    except ValueError as e:
        return _err(str(e), 403 if "Solo " in str(e) else 400, "traspaso_no_valido")
    return _ok(traspasos.obtener(g.tenant_id, traspaso_id))


@api_bp.route("/fiscal/traspasos/<int:traspaso_id>/aceptar", methods=["POST"])
@token_required
def aceptar_traspaso_api(traspaso_id: int):
    """Quien lo recibe (o la dirección). Cambia el responsable y, si se indicó, la oficina; si el receptor no veía el cliente se le concede acceso de gestión. `If-Match` con la `version` leída."""
    error = _exigir_tenant_api()
    if error:
        return error
    from . import traspasos
    return _resolver_traspaso(traspaso_id, traspasos.aceptar)


@api_bp.route("/fiscal/traspasos/<int:traspaso_id>/rechazar", methods=["POST"])
@token_required
def rechazar_traspaso_api(traspaso_id: int):
    """Quien lo recibe (o la dirección). Cuerpo: `{"motivo": "Estoy de baja esa semana"}` (obligatorio). El cliente sigue con su responsable anterior."""
    error = _exigir_tenant_api()
    if error:
        return error
    from . import traspasos
    return _resolver_traspaso(traspaso_id, traspasos.rechazar, str(_body().get("motivo") or ""))


@api_bp.route("/fiscal/traspasos/<int:traspaso_id>/cancelar", methods=["POST"])
@token_required
def cancelar_traspaso_api(traspaso_id: int):
    """Quien lo propuso, el responsable actual o la dirección."""
    error = _exigir_tenant_api()
    if error:
        return error
    from . import traspasos
    return _resolver_traspaso(traspaso_id, traspasos.cancelar)


@api_bp.route("/fiscal/clientes/<int:cliente_id>/responsable", methods=["PUT"])
@token_required
def asignar_responsable_api(cliente_id: int):
    """Fija quién lleva el cliente sin traspaso (dirección o coordinación de su oficina). Cuerpo: `{"responsable_id": 5}` (`null` lo quita). No se puede con un traspaso pendiente."""
    error = _exigir_tenant_api()
    if error:
        return error
    from . import traspasos
    r = _body().get("responsable_id")
    try:
        traspasos.asignar_responsable(g.tenant_id, g.usuario_id, cliente_id, int(r) if r else None)
    except (ValueError, TypeError) as e:
        return _err(str(e), 403 if "Solo " in str(e) else 400, "responsable_no_valido")
    return _ok({"cliente_id": cliente_id, "responsable_id": int(r) if r else None})
