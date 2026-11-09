"""Conformidad del cliente con su declaración antes de presentarla (modelo 303): el despacho se la pide, el cliente ve en su portal el resultado y las facturas que lo componen y contesta «de acuerdo» o «hay un error».

**Informa, no bloquea**: presentar no depende de la respuesta (el despacho decide), pero la ficha de la declaración enseña lo que contestó el cliente. Sin tablas nuevas: la petición y la respuesta son eventos de la auditoría
(`fiscal.conformidad.pedida` y `fiscal.conformidad.respuesta`). Una petición nueva anula la respuesta anterior; las respuestas anteriores a la última petición no cuentan."""
from __future__ import annotations

import json
import re

from . import auditoria, db, facturas_contables as fc, fiscal_nucleo as fn

ACCION_PEDIDA = "fiscal.conformidad.pedida"
ACCION_RESPUESTA = "fiscal.conformidad.respuesta"
ESTADOS_PEDIBLES = ("revisada", "exportada")
MAX_COMENTARIO = 500


def _eventos(conn, tenant_id: int, ids: list[int]) -> dict[int, dict]:
    """{declaracion_id: {pedida_en, resultado_centimos, respuesta: None | {resultado, comentario, en}}} con la última petición y la respuesta que viene DESPUÉS de ella."""
    if not ids:
        return {}
    filas = conn.execute(f"SELECT id, entidad_id, accion, detalle, creado_en FROM auditoria_eventos WHERE tenant_id = ? AND entidad = 'fiscal_declaracion' AND accion IN (?, ?) "
                         f"AND entidad_id IN ({','.join('?' * len(ids))}) ORDER BY id", (tenant_id, ACCION_PEDIDA, ACCION_RESPUESTA, *[str(i) for i in ids])).fetchall()
    res: dict[int, dict] = {}
    for e in filas:
        did = int(e["entidad_id"])
        try:
            detalle = json.loads(e["detalle"] or "{}") or {}
        except ValueError:
            detalle = {}
        if e["accion"] == ACCION_PEDIDA:
            res[did] = {"pedida_en": e["creado_en"][:16], "resultado_centimos": detalle.get("resultado_centimos"), "respuesta": None}
        elif did in res:
            res[did]["respuesta"] = {"resultado": detalle.get("resultado"), "comentario": detalle.get("comentario") or "", "en": e["creado_en"][:16]}
    return res


def estado_de(tenant_id: int, declaracion_id: int) -> dict | None:
    """El estado de la conformidad de UNA declaración, o None si nunca se pidió."""
    conn = db.get_connection()
    try:
        return _eventos(conn, tenant_id, [declaracion_id]).get(declaracion_id)
    finally:
        conn.close()


def pedir(tenant_id: int, usuario_id: int, declaracion_id: int) -> dict:
    """El despacho pide al cliente que revise la declaración. Solo mientras esté revisada o exportada; vuelve a pedirla si cambió algo. Avisa al cliente por correo si hay correo saliente y email en su ficha."""
    d = fn.obtener_declaracion(tenant_id, usuario_id, declaracion_id)             # comprueba el acceso de la persona
    if d["modelo"] != "303":
        raise ValueError("Por ahora solo se pide la conformidad del modelo 303.")
    if d["estado"] not in ESTADOS_PEDIBLES:
        raise ValueError("Solo se puede pedir la conformidad de una declaración revisada o exportada.")
    if d["bloqueos"]:
        raise ValueError("La declaración tiene bloqueos: no se enseña al cliente.")
    auditoria.registrar(tenant_id, usuario_id, ACCION_PEDIDA, "fiscal_declaracion", declaracion_id, {"resultado_centimos": d["resultado_centimos"], "estado": d["estado"]})
    return {"avisado": _avisar_por_correo(tenant_id, d)}


def _avisar_por_correo(tenant_id: int, d: dict) -> bool:
    from . import portal_avisos, portal_recordatorios
    cliente = db.obtener_cliente_fiscal_por_id(d["cliente_fiscal_id"])
    if cliente is None:
        return False
    periodo = f"{d['periodo']} {d['ejercicio']}"
    _ = portal_recordatorios._

    def texto():
        return {"asunto": _("Revisa tu modelo 303 de %(periodo)s", periodo=periodo), "boton": _("Revisar mi modelo 303"),
                "lineas": [_("Hola, %(nombre)s.", nombre=cliente["nombre"]),
                           _("Tu gestoría ha preparado tu modelo 303 de %(periodo)s y quiere que lo veas antes de presentarlo.", periodo=periodo),
                           _("Si todo está bien, pulsa «De acuerdo»; si falta algo o no cuadra, dínoslo desde ahí.")],
                "push": _("Tu modelo 303 de %(periodo)s espera tu revisión.", periodo=periodo)}
    return portal_avisos.avisar(cliente, f"/portal/declaraciones/{d['id']}", texto, accion="decidir") > 0


def pendientes_del_cliente(cliente_fiscal_id: int) -> list[dict]:
    """Las declaraciones del cliente cuya conformidad se pidió y aún no ha contestado (y que siguen sin presentar): [{id, ejercicio, periodo, estado, resultado_centimos, tipo_declaracion, pedida_en}]."""
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    if cliente is None:
        return []
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute("SELECT id, ejercicio, periodo, estado, resultado_centimos, tipo_declaracion FROM fiscal_declaraciones WHERE tenant_id = ? AND cliente_fiscal_id = ? AND modelo = '303' "
                                               "AND estado IN ('revisada', 'exportada') ORDER BY ejercicio DESC, periodo DESC, id DESC", (cliente["tenant_id"], cliente_fiscal_id))]
        ev = _eventos(conn, cliente["tenant_id"], [f["id"] for f in filas])
    finally:
        conn.close()
    return [{**f, "pedida_en": ev[f["id"]]["pedida_en"]} for f in filas if f["id"] in ev and ev[f["id"]]["respuesta"] is None]


def pendientes_por_cliente(tenant_id: int) -> dict[int, int]:
    """{cliente_fiscal_id: cuántas conformidades tiene pendientes de contestar} de todo el despacho, en dos consultas (la versión «de un cliente» no sirve para recorrer miles)."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT id, cliente_fiscal_id FROM fiscal_declaraciones WHERE tenant_id = ? AND modelo = '303' AND estado IN ('revisada', 'exportada')", (tenant_id,)).fetchall()
        ev = _eventos(conn, tenant_id, [f["id"] for f in filas])
    finally:
        conn.close()
    res: dict[int, int] = {}
    for f in filas:
        if f["id"] in ev and ev[f["id"]]["respuesta"] is None:
            res[f["cliente_fiscal_id"]] = res.get(f["cliente_fiscal_id"], 0) + 1
    return res


def ver_para_cliente(cliente_fiscal_id: int, declaracion_id: int) -> dict | None:
    """La declaración tal como la ve el cliente (resumen, facturas y su respuesta), o None si no es suya o nunca se le pidió la conformidad."""
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    if cliente is None:
        return None
    conn = db.get_connection()
    try:
        ev = _eventos(conn, cliente["tenant_id"], [declaracion_id]).get(declaracion_id)
    finally:
        conn.close()
    if ev is None:
        return None
    try:
        resumen = fn.resumen_para_cliente(cliente["tenant_id"], cliente_fiscal_id, declaracion_id)
    except fn.ErrorFiscal:
        return None
    return {**resumen, "conformidad": ev, "modificada": ev["resultado_centimos"] is not None and ev["resultado_centimos"] != resumen["declaracion"]["resultado_centimos"]}


def responder(cliente_fiscal_id: int, declaracion_id: int, resultado: str, comentario: str = "") -> None:
    """El cliente contesta `conforme` o `error` (con el comentario obligatorio). Solo a una petición vigente y sin contestar. Avisa al equipo."""
    if resultado not in ("conforme", "error"):
        raise ValueError("Elige «De acuerdo» o «Hay un error».")
    comentario = re.sub(r"[ \t]+", " ", comentario or "").strip()
    if resultado == "error" and not comentario:
        raise ValueError("Cuéntanos qué hay que corregir.")
    if len(comentario) > MAX_COMENTARIO:
        raise ValueError(f"El comentario no puede pasar de {MAX_COMENTARIO} caracteres.")
    if not any(p["id"] == declaracion_id for p in pendientes_del_cliente(cliente_fiscal_id)):
        raise ValueError("Esta declaración ya no está pendiente de tu conformidad.")
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    auditoria.registrar(cliente["tenant_id"], None, ACCION_RESPUESTA, "fiscal_declaracion", declaracion_id, {"resultado": resultado, "comentario": comentario if resultado == "error" else ""})
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT ejercicio, periodo FROM fiscal_declaraciones WHERE id = ? AND tenant_id = ?", (declaracion_id, cliente["tenant_id"])).fetchone()
    finally:
        conn.close()
    periodo = f"{f['periodo']} {f['ejercicio']}" if f else ""
    titulo = f"{cliente['nombre']} da su conformidad al 303 {periodo}" if resultado == "conforme" else f"{cliente['nombre']} dice que hay un error en el 303 {periodo}"
    fc.avisar_al_equipo(cliente, titulo, comentario or periodo, f"/guilda-fiscal/declaracion/{declaracion_id}", {"declaracion_id": declaracion_id})
