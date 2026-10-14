"""Oficinas, roles y alcance de los clientes fiscales (especificación de control fiscal, RF-14 y RF-15).

Modelo:
- Un despacho puede tener **oficinas**; cada cliente fiscal tiene una **oficina principal** (o ninguna) y se puede **compartir** con otras oficinas o personas (`concesiones_cliente`).
- Las **membresías** combinan un **rol** (coordinador, gestor, revisor fiscal, auditor) y un **alcance** (toda la organización, una oficina o un cliente), con vigencia y revocación.
- Los **supervisores** del despacho son su dirección: ven y hacen todo (rol «director»). El superadmin de la plataforma, también.

Reglas de visibilidad (denegar por defecto, pero sin romper a quien no usa oficinas):
- Si el despacho **no tiene oficinas**, nada cambia: todo el equipo ve todos los clientes, como hasta ahora.
- Si las tiene, una persona ve los clientes de **sus oficinas**, los que se le hayan concedido a ella o a una de sus oficinas, los de las membresías de cliente y, si tiene una membresía de
  organización (revisor fiscal, auditor…), todos. Los clientes **sin oficina asignada** los ve todo el equipo hasta que se asignen (así crear la primera oficina no deja a nadie a ciegas).
- El **auditor** solo lee: no modifica nada.

Se aplica en la capa de datos (listas, conteos, fichas, documentos, calendario, exportaciones, API, IA y MCP), no solo en las pantallas: `restriccion()` añade el filtro a la consulta y
`puede_ver_cliente()` comprueba un cliente concreto. El «actor» sale del contexto (petición web, token de API o herramienta de IA/MCP); sin actor (tareas de fondo del sistema) no se filtra."""
from __future__ import annotations

import time
from datetime import date

from . import auditoria, db

ROLES = (("coordinador", "Coordinador de oficina"), ("gestor", "Gestor"), ("revisor_fiscal", "Revisor fiscal"), ("auditor", "Auditor"))
ALCANCES = ("organizacion", "oficina", "cliente")
_CACHE_OFICINAS: dict[int, tuple[bool, float]] = {}
_TTL = 30.0


# --- Quién actúa -----------------------------------------------------------------------------------------------------------------------------
def actor_actual() -> int | None:
    """La persona en nombre de la que se está leyendo: la de la herramienta de IA/MCP en curso, o la de la petición web o de API. `None` en las tareas del sistema."""
    try:
        import mcp_tools
        if mcp_tools._usuario_id_actual.get() or mcp_tools.get_access_token() is not None:
            return mcp_tools._uid()
    except Exception:  # noqa: BLE001
        pass
    try:
        from flask import g, has_request_context
        if has_request_context():
            return g.get("usuario_id")
    except Exception:  # noqa: BLE001
        pass
    return None


# --- Oficinas --------------------------------------------------------------------------------------------------------------------------------
def tiene_oficinas(tenant_id: int) -> bool:
    """¿El despacho usa oficinas? (con una caché de 30 s: se consulta en cada lista fiscal y casi nunca cambia)."""
    ahora = time.monotonic()
    c = _CACHE_OFICINAS.get(tenant_id)
    if c is not None and c[1] > ahora:
        return c[0]
    conn = db.get_connection()
    try:
        hay = conn.execute("SELECT 1 FROM oficinas WHERE tenant_id = ? AND activa = 1 LIMIT 1", (tenant_id,)).fetchone() is not None
    finally:
        conn.close()
    _CACHE_OFICINAS[tenant_id] = (hay, ahora + _TTL)
    return hay


def invalidar(tenant_id: int | None = None) -> None:
    if tenant_id is None:
        _CACHE_OFICINAS.clear()
    else:
        _CACHE_OFICINAS.pop(tenant_id, None)


def _hoy() -> str:
    return date.today().isoformat()


def es_directivo(usuario_id: int) -> bool:
    """Dirección del despacho (supervisor) o superadmin: ven y hacen todo."""
    return bool(db.es_admin(usuario_id) or db.es_supervisor_tenant(usuario_id))


def membresias_vigentes(tenant_id: int, usuario_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            "SELECT * FROM membresias WHERE tenant_id = ? AND usuario_id = ? AND revocada_en IS NULL AND vigente_desde <= ? AND (vigente_hasta IS NULL OR vigente_hasta >= ?) ORDER BY id",
            (tenant_id, usuario_id, _hoy(), _hoy()))]
    finally:
        conn.close()


def roles_de(tenant_id: int, usuario_id: int) -> set[str]:
    """Roles efectivos: los de sus membresías vigentes y «director» si es supervisor o administrador."""
    roles = {m["rol"] for m in membresias_vigentes(tenant_id, usuario_id)}
    if es_directivo(usuario_id):
        roles.add("director")
    return roles


def puede_autorizar(tenant_id: int, usuario_id: int) -> bool:
    """Aprobar obligaciones y marcarlas «no aplica» o «anulada»: dirección o revisor fiscal."""
    r = roles_de(tenant_id, usuario_id)
    return bool(r & {"director", "revisor_fiscal"})


def es_solo_auditor(tenant_id: int, usuario_id: int) -> bool:
    r = roles_de(tenant_id, usuario_id)
    return "auditor" in r and not (r & {"director", "coordinador", "gestor", "revisor_fiscal"})


# --- Visibilidad de clientes ---------------------------------------------------------------------------------------------------------------------
def _alcance(tenant_id: int, usuario_id: int):
    """`None` = ve todos los clientes; si no, (oficinas, clientes) a los que llega por sus membresías y concesiones."""
    if not tiene_oficinas(tenant_id) or es_directivo(usuario_id):
        return None
    ms = membresias_vigentes(tenant_id, usuario_id)
    if any(m["alcance_tipo"] == "organizacion" for m in ms):
        return None
    oficinas = {m["alcance_id"] for m in ms if m["alcance_tipo"] == "oficina"}
    clientes = {m["alcance_id"] for m in ms if m["alcance_tipo"] == "cliente"}
    return oficinas, clientes


def _condicion(tenant_id: int, usuario_id: int, columna: str) -> tuple[str, list]:
    """Fragmento SQL (sin `AND` inicial) que limita `columna` (un id de cliente fiscal) a lo que la persona puede ver, o ("", []) si lo ve todo."""
    a = _alcance(tenant_id, usuario_id)
    if a is None:
        return "", []
    oficinas, clientes = a
    marca_of = ",".join("?" * len(oficinas)) or "NULL"
    marca_cl = ",".join("?" * len(clientes)) or "NULL"
    conc = (f"SELECT cliente_fiscal_id FROM concesiones_cliente WHERE tenant_id = ? AND revocada_en IS NULL AND (vigente_hasta IS NULL OR vigente_hasta >= ?) "
            f"AND (usuario_id = ? OR oficina_id IN ({marca_of}))")
    sql = (f"{columna} IN (SELECT id FROM clientes_fiscales WHERE tenant_id = ? AND (oficina_id IS NULL OR oficina_id IN ({marca_of}) OR id IN ({marca_cl}) OR id IN ({conc})))")
    params = [tenant_id, *oficinas, *clientes, tenant_id, _hoy(), usuario_id, *oficinas]
    return sql, params


def restriccion(tenant_id: int, columna: str) -> tuple[str, list]:
    """Para las consultas de la capa de datos: `(" AND <filtro>", params)` para el actor actual, o ("", []) si no hay actor o lo ve todo."""
    uid = actor_actual()
    if uid is None or not tiene_oficinas(tenant_id):
        return "", []                      # sin actor (sistema) o sin oficinas: nada que filtrar, y sin tocar la base de datos más allá de la caché
    u = db.obtener_usuario(uid)
    if u is None or u["tenant_id"] != tenant_id:
        return "", []                      # superadmin de otro ámbito o contexto sin despacho: no es un miembro de este despacho
    sql, params = _condicion(tenant_id, uid, columna)
    return (f" AND {sql}", params) if sql else ("", [])


def puede_ver_cliente(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> bool:
    sql, params = _condicion(tenant_id, usuario_id, "c.id")
    if not sql:
        return True
    conn = db.get_connection()
    try:
        return conn.execute(f"SELECT 1 FROM clientes_fiscales c WHERE c.id = ? AND c.tenant_id = ? AND {sql}", [cliente_fiscal_id, tenant_id, *params]).fetchone() is not None
    finally:
        conn.close()


def puede_modificar_cliente(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> bool:
    return puede_ver_cliente(tenant_id, usuario_id, cliente_fiscal_id) and not es_solo_auditor(tenant_id, usuario_id)


def clientes_visibles(tenant_id: int, usuario_id: int) -> set[int] | None:
    """Ids de clientes fiscales que ve la persona (`None` = todos). Para pantallas que cuentan o filtran en Python."""
    sql, params = _condicion(tenant_id, usuario_id, "c.id")
    if not sql:
        return None
    conn = db.get_connection()
    try:
        return {f["id"] for f in conn.execute(f"SELECT c.id FROM clientes_fiscales c WHERE c.tenant_id = ? AND c.papelera_en IS NULL AND {sql}", [tenant_id, *params])}
    finally:
        conn.close()


# --- Gestión (oficinas, asignación, concesiones, membresías) ------------------------------------------------------------------------------------
def _exigir_directivo(tenant_id: int, usuario_id: int) -> None:
    u = db.obtener_usuario(usuario_id)
    if u is None or u["tenant_id"] != tenant_id or not es_directivo(usuario_id):
        raise ValueError("Solo la dirección del despacho (supervisores) puede hacer esto.")


def _oficinas_que_coordina(tenant_id: int, usuario_id: int) -> set[int]:
    return {m["alcance_id"] for m in membresias_vigentes(tenant_id, usuario_id) if m["rol"] == "coordinador" and m["alcance_tipo"] == "oficina"}


def listar_oficinas(tenant_id: int, incluir_archivadas: bool = False) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            "SELECT o.*, (SELECT COUNT(*) FROM clientes_fiscales c WHERE c.oficina_id = o.id AND c.papelera_en IS NULL) AS clientes, "
            "(SELECT COUNT(DISTINCT usuario_id) FROM membresias m WHERE m.alcance_tipo = 'oficina' AND m.alcance_id = o.id AND m.revocada_en IS NULL) AS personas "
            f"FROM oficinas o WHERE o.tenant_id = ? {'' if incluir_archivadas else 'AND o.activa = 1'} ORDER BY lower(o.nombre)", (tenant_id,))]
    finally:
        conn.close()


def crear_oficina(tenant_id: int, usuario_id: int, nombre: str) -> int:
    _exigir_directivo(tenant_id, usuario_id)
    nombre = (nombre or "").strip()[:80]
    if not nombre:
        raise ValueError("Ponle un nombre a la oficina.")
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM oficinas WHERE tenant_id = ? AND lower(nombre) = lower(?) AND activa = 1", (tenant_id, nombre)).fetchone():
            raise ValueError("Ya hay una oficina con ese nombre.")
        cur = conn.execute("INSERT INTO oficinas (tenant_id, nombre, creado_en) VALUES (?, ?, ?)", (tenant_id, nombre, db.now_iso()))
        auditoria.registrar(tenant_id, usuario_id, "oficina.crear", "oficina", cur.lastrowid, {"nombre": nombre}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    invalidar(tenant_id)
    return cur.lastrowid


def archivar_oficina(tenant_id: int, usuario_id: int, oficina_id: int) -> None:
    """Una oficina con clientes no se archiva: primero hay que reasignarlos (si no, esos clientes quedarían atados a una oficina que ya no se ve)."""
    _exigir_directivo(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        o = conn.execute("SELECT * FROM oficinas WHERE id = ? AND tenant_id = ? AND activa = 1", (oficina_id, tenant_id)).fetchone()
        if o is None:
            raise ValueError("No existe esa oficina.")
        n = conn.execute("SELECT COUNT(*) FROM clientes_fiscales WHERE oficina_id = ? AND papelera_en IS NULL", (oficina_id,)).fetchone()[0]
        if n:
            raise ValueError(f"La oficina tiene {n} cliente(s): reasígnalos antes de archivarla.")
        conn.execute("UPDATE oficinas SET activa = 0 WHERE id = ?", (oficina_id,))
        conn.execute("UPDATE membresias SET revocada_en = ? WHERE tenant_id = ? AND alcance_tipo = 'oficina' AND alcance_id = ? AND revocada_en IS NULL", (db.now_iso(), tenant_id, oficina_id))
        auditoria.registrar(tenant_id, usuario_id, "oficina.archivar", "oficina", oficina_id, {"nombre": o["nombre"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    invalidar(tenant_id)


def asignar_cliente_a_oficina(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, oficina_id: int | None) -> None:
    """Fija la oficina principal de un cliente (`None` la quita). La dirección, o quien coordina la oficina de origen y la de destino."""
    conn = db.get_connection()
    try:
        c = conn.execute("SELECT oficina_id, nombre FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (cliente_fiscal_id, tenant_id)).fetchone()
        if c is None:
            raise ValueError("No existe ese cliente.")
        if oficina_id is not None and conn.execute("SELECT 1 FROM oficinas WHERE id = ? AND tenant_id = ? AND activa = 1", (oficina_id, tenant_id)).fetchone() is None:
            raise ValueError("No existe esa oficina.")
        if not es_directivo(usuario_id):
            coordina = _oficinas_que_coordina(tenant_id, usuario_id)
            if not ({c["oficina_id"], oficina_id} - {None}) <= coordina or (c["oficina_id"] is None and oficina_id is None):
                raise ValueError("Solo la dirección o quien coordina esas oficinas puede mover el cliente.")
        conn.execute("UPDATE clientes_fiscales SET oficina_id = ?, version = version + 1 WHERE id = ?", (oficina_id, cliente_fiscal_id))
        auditoria.registrar(tenant_id, usuario_id, "cliente.oficina", "cliente_fiscal", cliente_fiscal_id, {"de": c["oficina_id"], "a": oficina_id}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def conceder_cliente(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, *, oficina_id: int | None = None, para_usuario_id: int | None = None, nivel: str = "gestion", hasta: str | None = None) -> int:
    """Comparte un cliente con otra oficina o con una persona (con vigencia). La dirección, o quien coordina la oficina del cliente."""
    if (oficina_id is None) == (para_usuario_id is None):
        raise ValueError("Indica a una oficina o a una persona (una sola).")
    if nivel not in ("lectura", "gestion"):
        raise ValueError("Nivel no válido.")
    if hasta:
        try:
            date.fromisoformat(hasta[:10])
        except ValueError:
            raise ValueError("La fecha de fin debe tener el formato AAAA-MM-DD.") from None
    conn = db.get_connection()
    try:
        c = conn.execute("SELECT oficina_id FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (cliente_fiscal_id, tenant_id)).fetchone()
        if c is None:
            raise ValueError("No existe ese cliente.")
        if not es_directivo(usuario_id) and (c["oficina_id"] is None or c["oficina_id"] not in _oficinas_que_coordina(tenant_id, usuario_id)):
            raise ValueError("Solo la dirección o quien coordina la oficina del cliente puede compartirlo.")
        if oficina_id is not None and conn.execute("SELECT 1 FROM oficinas WHERE id = ? AND tenant_id = ? AND activa = 1", (oficina_id, tenant_id)).fetchone() is None:
            raise ValueError("No existe esa oficina.")
        if para_usuario_id is not None and conn.execute("SELECT 1 FROM usuarios WHERE id = ? AND tenant_id = ?", (para_usuario_id, tenant_id)).fetchone() is None:
            raise ValueError("Esa persona no pertenece al despacho.")
        cur = conn.execute("INSERT INTO concesiones_cliente (tenant_id, cliente_fiscal_id, oficina_id, usuario_id, nivel, vigente_hasta, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, cliente_fiscal_id, oficina_id, para_usuario_id, nivel, (hasta or "")[:10] or None, usuario_id, db.now_iso()))
        auditoria.registrar(tenant_id, usuario_id, "concesion.crear", "cliente_fiscal", cliente_fiscal_id, {"oficina_id": oficina_id, "usuario_id": para_usuario_id, "nivel": nivel, "hasta": hasta}, conn=conn)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def revocar_concesion(tenant_id: int, usuario_id: int, concesion_id: int) -> None:
    conn = db.get_connection()
    try:
        k = conn.execute("SELECT * FROM concesiones_cliente WHERE id = ? AND tenant_id = ? AND revocada_en IS NULL", (concesion_id, tenant_id)).fetchone()
        if k is None:
            raise ValueError("No existe esa concesión.")
        c = conn.execute("SELECT oficina_id FROM clientes_fiscales WHERE id = ?", (k["cliente_fiscal_id"],)).fetchone()
        if not es_directivo(usuario_id) and (c is None or c["oficina_id"] not in _oficinas_que_coordina(tenant_id, usuario_id)):
            raise ValueError("Solo la dirección o quien coordina la oficina del cliente puede retirar el acceso.")
        conn.execute("UPDATE concesiones_cliente SET revocada_en = ? WHERE id = ?", (db.now_iso(), concesion_id))
        auditoria.registrar(tenant_id, usuario_id, "concesion.revocar", "cliente_fiscal", k["cliente_fiscal_id"], {"concesion_id": concesion_id}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def concesiones_de(tenant_id: int, cliente_fiscal_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            "SELECT k.*, o.nombre AS oficina, COALESCE(NULLIF(p.nombre_mostrado, ''), u.email) AS persona FROM concesiones_cliente k LEFT JOIN oficinas o ON o.id = k.oficina_id "
            "LEFT JOIN usuarios u ON u.id = k.usuario_id LEFT JOIN usuario_perfil p ON p.usuario_id = k.usuario_id "
            "WHERE k.tenant_id = ? AND k.cliente_fiscal_id = ? AND k.revocada_en IS NULL ORDER BY k.id", (tenant_id, cliente_fiscal_id))]
    finally:
        conn.close()


def dar_membresia(tenant_id: int, usuario_id: int, para_usuario_id: int, rol: str, alcance_tipo: str, alcance_id: int | None = None, hasta: str | None = None) -> int:
    """Da un rol con alcance a una persona del despacho. La dirección puede todo; quien coordina una oficina puede dar gestor o auditor en esa oficina."""
    if rol not in dict(ROLES) or alcance_tipo not in ALCANCES:
        raise ValueError("Rol o alcance no válidos.")
    if alcance_tipo == "organizacion":
        alcance_id = None
    elif alcance_id is None:
        raise ValueError("Indica la oficina o el cliente.")
    if rol == "coordinador" and alcance_tipo != "oficina":
        raise ValueError("Un coordinador lo es de una oficina.")
    if rol == "revisor_fiscal" and alcance_tipo != "organizacion":
        raise ValueError("El revisor fiscal lo es de toda la organización.")
    if hasta:
        try:
            date.fromisoformat(hasta[:10])
        except ValueError:
            raise ValueError("La fecha de fin debe tener el formato AAAA-MM-DD.") from None
    if not es_directivo(usuario_id):
        if not (rol in ("gestor", "auditor") and alcance_tipo == "oficina" and alcance_id in _oficinas_que_coordina(tenant_id, usuario_id)):
            raise ValueError("Solo la dirección, o quien coordina la oficina (para gestores y auditores de ella), puede dar roles.")
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM usuarios WHERE id = ? AND tenant_id = ?", (para_usuario_id, tenant_id)).fetchone() is None:
            raise ValueError("Esa persona no pertenece al despacho.")
        if alcance_tipo == "oficina" and conn.execute("SELECT 1 FROM oficinas WHERE id = ? AND tenant_id = ? AND activa = 1", (alcance_id, tenant_id)).fetchone() is None:
            raise ValueError("No existe esa oficina.")
        if alcance_tipo == "cliente" and conn.execute("SELECT 1 FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (alcance_id, tenant_id)).fetchone() is None:
            raise ValueError("No existe ese cliente.")
        if conn.execute("SELECT 1 FROM membresias WHERE tenant_id = ? AND usuario_id = ? AND rol = ? AND alcance_tipo = ? AND COALESCE(alcance_id, 0) = ? AND revocada_en IS NULL",
                        (tenant_id, para_usuario_id, rol, alcance_tipo, alcance_id or 0)).fetchone():
            raise ValueError("Esa persona ya tiene ese rol con ese alcance.")
        cur = conn.execute("INSERT INTO membresias (tenant_id, usuario_id, rol, alcance_tipo, alcance_id, vigente_desde, vigente_hasta, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, para_usuario_id, rol, alcance_tipo, alcance_id, _hoy(), (hasta or "")[:10] or None, usuario_id, db.now_iso()))
        auditoria.registrar(tenant_id, usuario_id, "membresia.crear", "usuario", para_usuario_id, {"rol": rol, "alcance": alcance_tipo, "alcance_id": alcance_id, "hasta": hasta}, conn=conn)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def revocar_membresia(tenant_id: int, usuario_id: int, membresia_id: int) -> None:
    conn = db.get_connection()
    try:
        m = conn.execute("SELECT * FROM membresias WHERE id = ? AND tenant_id = ? AND revocada_en IS NULL", (membresia_id, tenant_id)).fetchone()
        if m is None:
            raise ValueError("No existe esa membresía.")
        if not es_directivo(usuario_id) and not (m["rol"] in ("gestor", "auditor") and m["alcance_tipo"] == "oficina" and m["alcance_id"] in _oficinas_que_coordina(tenant_id, usuario_id)):
            raise ValueError("Solo la dirección, o quien coordina la oficina, puede retirar roles.")
        conn.execute("UPDATE membresias SET revocada_en = ? WHERE id = ?", (db.now_iso(), membresia_id))
        auditoria.registrar(tenant_id, usuario_id, "membresia.revocar", "usuario", m["usuario_id"], {"rol": m["rol"], "alcance": m["alcance_tipo"], "alcance_id": m["alcance_id"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def membresias_del_despacho(tenant_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            "SELECT m.*, COALESCE(NULLIF(p.nombre_mostrado, ''), u.email) AS persona, o.nombre AS oficina, c.nombre AS cliente FROM membresias m JOIN usuarios u ON u.id = m.usuario_id "
            "LEFT JOIN usuario_perfil p ON p.usuario_id = m.usuario_id LEFT JOIN oficinas o ON o.id = m.alcance_id AND m.alcance_tipo = 'oficina' "
            "LEFT JOIN clientes_fiscales c ON c.id = m.alcance_id AND m.alcance_tipo = 'cliente' WHERE m.tenant_id = ? AND m.revocada_en IS NULL ORDER BY lower(persona), m.id", (tenant_id,))]
    finally:
        conn.close()
