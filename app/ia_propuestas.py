"""Bandeja de propuestas (W3): la IA y las reglas del sistema **proponen**, la persona aprueba o rechaza. Nada se ejecuta solo.

Una propuesta es «crear esta tarea», con su porqué y de dónde sale (`origen`: las alertas de clientes de app/anomalias.py hoy; el asistente y las demás funciones de IA pueden proponer con `proponer`).
Aprobar ejecuta el manejador de su `tipo` con quien aprueba (hoy: `tarea`); rechazar la silencia: la misma propuesta (misma `clave`) no vuelve a salir en `DIAS_SILENCIO` días, así la bandeja aprende
de lo que se descarta y no insiste. Cada aprobación y rechazo queda en la auditoría."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Callable

from . import auditoria, db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ia_propuestas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    clave TEXT NOT NULL,
    tipo TEXT NOT NULL,
    origen TEXT NOT NULL DEFAULT '',
    titulo TEXT NOT NULL,
    detalle TEXT NOT NULL DEFAULT '',
    datos TEXT NOT NULL DEFAULT '{}',
    cliente_fiscal_id INTEGER,
    prioridad TEXT NOT NULL DEFAULT 'normal',
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'aprobada', 'rechazada')),
    creada_en TEXT NOT NULL,
    resuelta_en TEXT,
    resuelta_por INTEGER,
    resultado TEXT
);
CREATE INDEX IF NOT EXISTS idx_ia_propuestas_tenant ON ia_propuestas(tenant_id, estado, creada_en);
CREATE INDEX IF NOT EXISTS idx_ia_propuestas_clave ON ia_propuestas(tenant_id, clave);
"""

DIAS_SILENCIO = 30
MANEJADORES: dict[str, Callable[[dict, int], str]] = {}


class ErrorPropuesta(ValueError):
    """Mensaje apto para enseñarlo."""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def manejador(tipo: str):
    def registrar(f):
        MANEJADORES[tipo] = f
        return f
    return registrar


@manejador("tarea")
def _crear_tarea(p: dict, usuario_id: int) -> str:
    """Crea la tarea (y, si la propuesta trae `avisar_en`, su recordatorio) a nombre de quien aprueba."""
    d = p["datos"]
    tid = db.crear_tarea_outlook(usuario_id, asunto=p["titulo"], cuerpo=p["detalle"] or None, prioridad=p["prioridad"], cliente_fiscal_id=p["cliente_fiscal_id"])
    if d.get("avisar_en"):
        db.anadir_recordatorio_tarea(usuario_id, tid, d["avisar_en"])
    return f"tarea:{tid}"


def _cliente_de(p: dict) -> dict:
    c = db.obtener_cliente_fiscal_por_id(p["cliente_fiscal_id"]) if p["cliente_fiscal_id"] else None
    if c is None or c["tenant_id"] != p["tenant_id"]:
        raise ErrorPropuesta("El cliente de esta propuesta ya no existe.")
    return c


@manejador("peticion_portal")
def _pedir_documentacion(p: dict, usuario_id: int) -> str:
    """Abre en el portal del cliente una petición de documentos (datos: titulo, descripcion, fecha_limite opcional)."""
    from . import portal_peticiones
    d = p["datos"]
    try:
        pid = portal_peticiones.crear(_cliente_de(p), d.get("titulo") or p["titulo"], d.get("descripcion") or p["detalle"], d.get("fecha_limite"), por=usuario_id)
    except ValueError as e:
        raise ErrorPropuesta(str(e)) from e
    return f"peticion:{pid}"


@manejador("mensaje_portal")
def _escribir_al_cliente(p: dict, usuario_id: int) -> str:
    """Abre un hilo en el portal del cliente con el texto propuesto (datos: asunto, texto). Es lo único que llega a un cliente, y solo cuando una persona lo aprueba."""
    from . import portal_conversaciones
    d = p["datos"]
    nombre = db.nombre_mostrado_usuario(usuario_id) or "Despacho"
    try:
        hid = portal_conversaciones.iniciar(_cliente_de(p), d.get("asunto") or p["titulo"], d.get("texto") or p["detalle"], "despacho", nombre, usuario_id=usuario_id)
    except ValueError as e:
        raise ErrorPropuesta(str(e)) from e
    return f"hilo:{hid}"


@manejador("cuenta_tercero")
def _fijar_cuenta(p: dict, usuario_id: int) -> str:
    """Fija la subcuenta de un proveedor o cliente (datos: tipo_tercero, nif, cuenta) para las próximas exportaciones. Las ya exportadas no cambian."""
    from . import facturas_contables as fc
    d = p["datos"]
    try:
        fc.fijar_cuenta_tercero(p["tenant_id"], usuario_id, p["cliente_fiscal_id"], d.get("tipo_tercero", "proveedor"), d.get("nif", ""), d.get("cuenta", ""))
    except ValueError as e:
        raise ErrorPropuesta(str(e)) from e
    return f"cuenta:{d.get('nif')}"


def etiqueta(tipo: str) -> str:
    """Qué hará aprobar esta propuesta, en palabras de quien la lee."""
    from flask_babel import gettext as _
    return {"tarea": _("crear una tarea"), "peticion_portal": _("pedir documentación al cliente por el portal"), "mensaje_portal": _("escribir al cliente por el portal"),
            "cuenta_tercero": _("fijar la subcuenta de un proveedor o cliente")}.get(tipo, tipo)


def proponer(tenant_id: int, *, clave: str, tipo: str, titulo: str, detalle: str = "", origen: str = "", datos: dict | None = None, cliente_fiscal_id: int | None = None, prioridad: str = "normal") -> int | None:
    """Deja una propuesta en la bandeja. Devuelve su id, o None si no hace falta: ya hay una igual pendiente o se aprobó o rechazó hace menos de `DIAS_SILENCIO` días."""
    if tipo not in MANEJADORES:
        raise ErrorPropuesta("No sé ejecutar ese tipo de propuesta.")
    desde = (datetime.now() - timedelta(days=DIAS_SILENCIO)).isoformat(timespec="seconds")
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM ia_propuestas WHERE tenant_id = ? AND clave = ? AND (estado = 'pendiente' OR creada_en >= ?)", (tenant_id, clave, desde)).fetchone():
            return None
        cur = conn.execute("INSERT INTO ia_propuestas (tenant_id, clave, tipo, origen, titulo, detalle, datos, cliente_fiscal_id, prioridad, creada_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, clave[:200], tipo, origen[:40], titulo[:200], detalle[:600], json.dumps(datos or {}, ensure_ascii=False), cliente_fiscal_id, prioridad, _ahora()))
        conn.commit()
        nueva = cur.lastrowid
    finally:
        conn.close()
    _emitir("propuesta.creada", tenant_id, {"propuesta_id": nueva, "tipo": tipo, "origen": origen, "titulo": titulo[:200], "cliente_id": cliente_fiscal_id, "prioridad": prioridad})
    return nueva


def _emitir(evento: str, tenant_id: int, payload: dict) -> None:
    """Avisa a los webhooks del despacho (app/eventos.py). Un fallo al avisar nunca impide guardar ni resolver la propuesta."""
    try:
        from . import eventos
        eventos.emitir(evento, tenant_id, payload)
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger("guilda").warning("No se pudo emitir %s", evento, exc_info=True)


def _fila(f) -> dict:
    d = dict(f)
    d["datos"] = json.loads(d.get("datos") or "{}")
    return d


def obtener(tenant_id: int, propuesta_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM ia_propuestas WHERE tenant_id = ? AND id = ?", (tenant_id, propuesta_id)).fetchone()
    finally:
        conn.close()
    return _fila(f) if f else None


def pendientes(tenant_id: int, cliente_fiscal_id: int | None = None) -> list[dict]:
    """Las pendientes, las urgentes primero y dentro de cada prioridad las más antiguas."""
    sql, args = "SELECT * FROM ia_propuestas WHERE tenant_id = ? AND estado = 'pendiente'", [tenant_id]
    if cliente_fiscal_id is not None:
        sql += " AND cliente_fiscal_id = ?"; args.append(cliente_fiscal_id)
    conn = db.get_connection()
    try:
        filas = [_fila(f) for f in conn.execute(sql + " ORDER BY id", args).fetchall()]
    finally:
        conn.close()
    return sorted(filas, key=lambda p: (0 if p["prioridad"] == "alta" else 1, p["id"]))


def contar(tenant_id: int) -> int:
    conn = db.get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM ia_propuestas WHERE tenant_id = ? AND estado = 'pendiente'", (tenant_id,)).fetchone()[0]
    finally:
        conn.close()


def resueltas(tenant_id: int, dias: int = 30, limite: int = 30) -> list[dict]:
    desde = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
    conn = db.get_connection()
    try:
        return [_fila(f) for f in conn.execute("SELECT * FROM ia_propuestas WHERE tenant_id = ? AND estado <> 'pendiente' AND resuelta_en >= ? ORDER BY resuelta_en DESC, id DESC LIMIT ?", (tenant_id, desde, limite)).fetchall()]
    finally:
        conn.close()


def estadisticas(tenant_id: int, dias: int = 90) -> list[dict]:
    """Por origen y tipo: cuántas se han aprobado y rechazado y la tasa de rechazo, de las más rechazadas a las menos. Con 5 o más resueltas y un 70 % o más rechazadas, `revisar` es True: esa regla probablemente sobra o está muy sensible."""
    desde = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT origen, tipo, estado, COUNT(*) AS n FROM ia_propuestas WHERE tenant_id = ? AND estado <> 'pendiente' AND resuelta_en >= ? GROUP BY origen, tipo, estado", (tenant_id, desde)).fetchall()
    finally:
        conn.close()
    por: dict[tuple[str, str], dict] = {}
    for f in filas:
        d = por.setdefault((f["origen"], f["tipo"]), {"origen": f["origen"], "tipo": f["tipo"], "aprobadas": 0, "rechazadas": 0})
        d["aprobadas" if f["estado"] == "aprobada" else "rechazadas"] += f["n"]
    salida = []
    for d in por.values():
        total = d["aprobadas"] + d["rechazadas"]
        d["total"], d["tasa_rechazo"] = total, round(100 * d["rechazadas"] / total)
        d["revisar"] = total >= 5 and d["tasa_rechazo"] >= 70
        salida.append(d)
    return sorted(salida, key=lambda d: (-d["tasa_rechazo"], -d["total"]))


def _resolver(tenant_id: int, usuario_id: int, propuesta_id: int, estado: str, resultado: str = "") -> bool:
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE ia_propuestas SET estado = ?, resuelta_en = ?, resuelta_por = ?, resultado = ? WHERE tenant_id = ? AND id = ? AND estado = 'pendiente'",
                         (estado, _ahora(), usuario_id, resultado[:200], tenant_id, propuesta_id)).rowcount
        conn.commit()
        return bool(n)
    finally:
        conn.close()


def aprobar(tenant_id: int, usuario_id: int, propuesta_id: int) -> str:
    """Ejecuta la propuesta como quien la aprueba y la cierra. Dos personas pulsando a la vez no la ejecutan dos veces. Devuelve lo que se hizo (p. ej. `tarea:12`)."""
    p = obtener(tenant_id, propuesta_id)
    if p is None:
        raise ErrorPropuesta("Esa propuesta no existe.")
    if p["estado"] != "pendiente":
        raise ErrorPropuesta("Esa propuesta ya estaba resuelta.")
    if not _resolver(tenant_id, usuario_id, propuesta_id, "aprobada"):          # se «reclama» antes de ejecutar: la segunda persona se queda sin nada que hacer
        raise ErrorPropuesta("Esa propuesta ya estaba resuelta.")
    try:
        resultado = MANEJADORES[p["tipo"]](p, usuario_id)
    except Exception:
        conn = db.get_connection()
        try:
            conn.execute("UPDATE ia_propuestas SET estado = 'pendiente', resuelta_en = NULL, resuelta_por = NULL WHERE tenant_id = ? AND id = ?", (tenant_id, propuesta_id))
            conn.commit()
        finally:
            conn.close()
        raise
    conn = db.get_connection()
    try:
        conn.execute("UPDATE ia_propuestas SET resultado = ? WHERE tenant_id = ? AND id = ?", (resultado[:200], tenant_id, propuesta_id))
        conn.commit()
    finally:
        conn.close()
    auditoria.registrar(tenant_id, usuario_id, "ia.propuesta_aprobada", "ia_propuesta", propuesta_id, {"tipo": p["tipo"], "origen": p["origen"], "resultado": resultado})
    _emitir("propuesta.resuelta", tenant_id, {"propuesta_id": propuesta_id, "estado": "aprobada", "tipo": p["tipo"], "origen": p["origen"], "resultado": resultado, "usuario_id": usuario_id})
    return resultado


def rechazar(tenant_id: int, usuario_id: int, propuesta_id: int) -> None:
    if not _resolver(tenant_id, usuario_id, propuesta_id, "rechazada"):
        raise ErrorPropuesta("Esa propuesta ya estaba resuelta.")
    auditoria.registrar(tenant_id, usuario_id, "ia.propuesta_rechazada", "ia_propuesta", propuesta_id, {})
    _emitir("propuesta.resuelta", tenant_id, {"propuesta_id": propuesta_id, "estado": "rechazada", "usuario_id": usuario_id})


def generar_desde_alertas(tenant_id: int, hoy=None) -> int:
    """Deja en la bandeja una propuesta «crear tarea» por cada alerta de clientes (app/anomalias.py) que todavía no tenga una reciente. Idempotente. Devuelve cuántas nuevas."""
    from . import anomalias
    nuevas = 0
    for a in anomalias.detectar(tenant_id, hoy):
        titulo, detalle = anomalias.texto(a)
        if proponer(tenant_id, clave=f"alerta:{anomalias.clave(a)}", tipo="tarea", titulo=titulo, detalle=detalle, origen="alerta", cliente_fiscal_id=a["cliente_id"], prioridad="alta" if a["severidad"] == "alta" else "normal", datos={"alerta": a["tipo"]}):
            nuevas += 1
    return nuevas


def generar_cuentas_de_terceros(tenant_id: int, hoy=None) -> int:
    """Proveedores y clientes de facturas recientes que no tienen subcuenta recordada pero SÍ la tienen en el plan de a3 importado: se propone fijarla (así las próximas facturas salen con esa cuenta). Idempotente."""
    from datetime import date
    from . import facturas_contables as fc
    desde = ((hoy or date.today()) - timedelta(days=90)).isoformat()
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT DISTINCT cliente_fiscal_id, tipo, tercero_nif, tercero_nombre FROM facturas_contables WHERE tenant_id = ? AND estado <> 'descartada' AND fecha >= ? AND COALESCE(tercero_nif, '') <> ''", (tenant_id, desde)).fetchall()
        clientes = {r["id"]: r["nombre"] for r in conn.execute("SELECT id, nombre FROM clientes_fiscales WHERE tenant_id = ?", (tenant_id,)).fetchall()}
    finally:
        conn.close()
    nuevas = 0
    for f in filas:
        cid, nif = f["cliente_fiscal_id"], fc._nif(f["tercero_nif"])
        if cid not in clientes or fc.cuenta_del_tercero(tenant_id, cid, f["tipo"], nif):
            continue
        cuenta = fc.cuenta_del_plan(tenant_id, cid, f["tipo"], nif)
        if not cuenta:
            continue
        tipo_tercero = "proveedor" if f["tipo"] == "recibida" else "cliente"
        if proponer(tenant_id, clave=f"cuenta:{cid}:{tipo_tercero}:{nif}", tipo="cuenta_tercero", origen="facturas", cliente_fiscal_id=cid, datos={"tipo_tercero": tipo_tercero, "nif": nif, "cuenta": cuenta},
                    titulo=f"Fijar la subcuenta {cuenta} de {f['tercero_nombre']}", detalle=f"El plan de a3 de {clientes[cid]} ya la tiene; así las próximas facturas de {f['tercero_nombre']} salen con esa cuenta."):
            nuevas += 1
    return nuevas


def generar_todo(tenant_id: int) -> int:
    """Todo lo que las reglas del sistema proponen hoy (alertas de clientes y cuentas de terceros)."""
    return generar_desde_alertas(tenant_id) + generar_cuentas_de_terceros(tenant_id)


_ULTIMA_GENERACION: dict[int, datetime] = {}


def generar_si_toca(tenant_id: int, minutos: int = 60) -> int:
    """Como `generar_desde_alertas`, pero como mucho una vez cada `minutos` por despacho en este proceso: la ficha de cada cliente la llama y calcular las alertas de todo el despacho no es gratis."""
    ahora = datetime.now()
    ultima = _ULTIMA_GENERACION.get(tenant_id)
    if ultima and ahora - ultima < timedelta(minutes=minutos):
        return 0
    _ULTIMA_GENERACION[tenant_id] = ahora
    return generar_todo(tenant_id)
