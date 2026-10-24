"""Mensajes seguros entre el despacho y la persona del enlace público (cliente del Gabinete de abogados, propietario de la Inmobiliaria) sin que esa persona tenga cuenta.

Es **opt-in por enlace**: el enlace nace de solo lectura y el despacho marca «permitir mensajes» al crearlo; revocar o dejar caducar el enlace corta también los mensajes. Solo texto
(sin adjuntos, sin HTML), con tope de largo y de mensajes al día por enlace, y limitado por IP en las rutas públicas. Los mensajes cuelgan del expediente y los ven quienes pueden ver
ese expediente. Cuando escribe la persona externa se avisa a las personas del equipo del expediente (centro de notificaciones y push, respetando sus preferencias)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from . import db, enlaces_publicos, nucleo, notificaciones

logger = logging.getLogger(__name__)

MAX_TEXTO = 2000
MAX_NOMBRE = 80
MAX_POR_DIA = 30
ESQUEMA = """
CREATE TABLE IF NOT EXISTS mensajes_enlace (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    vertical_id TEXT NOT NULL,
    expediente_id INTEGER NOT NULL REFERENCES expedientes(id) ON DELETE CASCADE,
    enlace_id INTEGER,
    autor TEXT NOT NULL CHECK (autor IN ('despacho', 'externo')),
    usuario_id INTEGER REFERENCES usuarios(id),
    nombre TEXT,
    texto TEXT NOT NULL,
    creado_en TEXT NOT NULL,
    leido_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_mensajes_enlace_exp ON mensajes_enlace(tenant_id, vertical_id, expediente_id, id);
"""


def _texto(valor, maximo: int, campo: str, obligatorio: bool = True) -> str | None:
    t = (valor or "").replace("\r\n", "\n").strip()
    if not t:
        if obligatorio:
            raise ValueError(f"{campo}: escribe algo.")
        return None
    if len(t) > maximo:
        raise ValueError(f"{campo}: máximo {maximo} caracteres.")
    return t


def hilo(vertical_id: str, tenant_id: int, expediente_id: int, limite: int = 100) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT id, autor, nombre, texto, creado_en, leido_en, usuario_id FROM mensajes_enlace WHERE tenant_id = ? AND vertical_id = ? AND expediente_id = ? "
                             "ORDER BY id DESC LIMIT ?", (tenant_id, vertical_id, expediente_id, limite)).fetchall()
    finally:
        conn.close()
    return [dict(f) for f in reversed(filas)]


def para_pagina_publica(vertical_id: str, resuelto: dict) -> dict:
    """Lo que enseña la página pública: si el enlace admite mensajes y el hilo. El nombre del miembro del despacho no se enseña (solo «el despacho»)."""
    if not resuelto["enlace"].get("permite_mensajes"):
        return {"permite_mensajes": False, "mensajes": []}
    mensajes = [{"autor": m["autor"], "nombre": m["nombre"] if m["autor"] == "externo" else None, "texto": m["texto"], "creado_en": m["creado_en"]}
                for m in hilo(vertical_id, resuelto["enlace"]["tenant_id"], resuelto["expediente"]["id"])]
    return {"permite_mensajes": True, "mensajes": mensajes}


def _equipo_del_expediente(tenant_id: int, expediente_id: int) -> list[int]:
    """A quién avisar: el responsable del expediente y quienes están en su equipo (sin repetir). Si no hay nadie, quien lo creó."""
    conn = db.get_connection()
    try:
        x = conn.execute("SELECT responsable_id, creado_por FROM expedientes WHERE id = ? AND tenant_id = ?", (expediente_id, tenant_id)).fetchone()
    finally:
        conn.close()
    ids = [i for i in ([x["responsable_id"]] if x else []) + [m["id"] for m in nucleo.miembros_de(expediente_id)] if i]
    if not ids and x and x["creado_por"]:
        ids = [x["creado_por"]]
    return list(dict.fromkeys(ids))


def _avisar_al_equipo(tenant_id: int, expediente_id: int, titulo: str, texto: str, url: str) -> None:
    for uid in _equipo_del_expediente(tenant_id, expediente_id):
        try:
            if db.notificacion_tipo_activa(uid, "portal_mensaje_nuevo"):
                notificaciones.crear_y_enviar(uid, "portal_mensaje_nuevo", titulo, texto[:100], url=url, datos={"tipo": "portal_mensaje_nuevo", "expediente_id": expediente_id})
        except Exception:  # noqa: BLE001 -- un aviso fallido no debe perder el mensaje
            logger.exception("No se pudo avisar de un mensaje del enlace a %s", uid)


def enviar_externo(vertical_id: str, token: str, nombre: str | None, texto: str) -> int:
    """La persona del enlace escribe al despacho. `ValueError` con un mensaje legible si el enlace no vale, no admite mensajes, o se pasa de tope."""
    r = enlaces_publicos.resolver(vertical_id, token)
    if r is None or not r["enlace"].get("permite_mensajes"):
        raise ValueError("Este enlace no admite mensajes.")
    texto = _texto(texto, MAX_TEXTO, "Mensaje")
    nombre = _texto(nombre, MAX_NOMBRE, "Nombre", obligatorio=False)
    e, x = r["enlace"], r["expediente"]
    conn = db.get_connection()
    try:
        desde = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
        hoy = conn.execute("SELECT COUNT(*) FROM mensajes_enlace WHERE enlace_id = ? AND vertical_id = ? AND autor = 'externo' AND creado_en >= ?", (e["id"], vertical_id, desde)).fetchone()[0]
        if hoy >= MAX_POR_DIA:
            raise ValueError("Has enviado muchos mensajes hoy. Inténtalo mañana o llama al despacho.")
        cur = conn.execute("INSERT INTO mensajes_enlace (tenant_id, vertical_id, expediente_id, enlace_id, autor, nombre, texto, creado_en) VALUES (?, ?, ?, ?, 'externo', ?, ?, ?)",
                           (e["tenant_id"], vertical_id, x["id"], e["id"], nombre, texto, db.now_iso()))
        nucleo._evento(conn, x["id"], "mensaje", "Mensaje nuevo de la persona del enlace.", None)
        conn.commit()
        mensaje_id = cur.lastrowid
    finally:
        conn.close()
    _avisar_al_equipo(e["tenant_id"], x["id"], f"Mensaje nuevo en «{x['titulo']}»", texto, f"/expedientes/{x['id']}")
    return mensaje_id


def responder(vertical_id: str, tenant_id: int, usuario_id: int, expediente_id: int, texto: str, supervisor: bool = False) -> int:
    """Un miembro del despacho contesta. Solo quien puede ver el expediente. Solo tiene sentido si el expediente tiene un enlace vivo que admita mensajes (si no, nadie lo leería)."""
    if nucleo.obtener_expediente(tenant_id, expediente_id, usuario_id, supervisor) is None:
        raise ValueError("Expediente no encontrado.")
    if not enlace_vivo_con_mensajes(vertical_id, tenant_id, expediente_id):
        raise ValueError("No hay ningún enlace activo que admita mensajes: crea uno con «permitir mensajes».")
    texto = _texto(texto, MAX_TEXTO, "Mensaje")
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO mensajes_enlace (tenant_id, vertical_id, expediente_id, autor, usuario_id, texto, creado_en, leido_en) VALUES (?, ?, ?, 'despacho', ?, ?, ?, ?)",
                           (tenant_id, vertical_id, expediente_id, usuario_id, texto, db.now_iso(), db.now_iso()))
        nucleo._evento(conn, expediente_id, "mensaje", "Mensaje enviado a la persona del enlace.", usuario_id)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def enlace_vivo_con_mensajes(vertical_id: str, tenant_id: int, expediente_id: int) -> bool:
    conn = db.get_connection()
    try:
        return conn.execute(f"SELECT 1 FROM {enlaces_publicos.TABLAS[vertical_id]} WHERE tenant_id = ? AND expediente_id = ? AND permite_mensajes = 1 AND revocado_en IS NULL AND expira_en >= ? LIMIT 1",
                            (tenant_id, expediente_id, db.now_iso())).fetchone() is not None
    finally:
        conn.close()


def no_leidos(vertical_id: str, tenant_id: int, expediente_id: int) -> int:
    conn = db.get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM mensajes_enlace WHERE tenant_id = ? AND vertical_id = ? AND expediente_id = ? AND autor = 'externo' AND leido_en IS NULL",
                            (tenant_id, vertical_id, expediente_id)).fetchone()[0]
    finally:
        conn.close()


def marcar_leidos(vertical_id: str, tenant_id: int, expediente_id: int) -> None:
    conn = db.get_connection()
    try:
        conn.execute("UPDATE mensajes_enlace SET leido_en = ? WHERE tenant_id = ? AND vertical_id = ? AND expediente_id = ? AND autor = 'externo' AND leido_en IS NULL",
                     (db.now_iso(), tenant_id, vertical_id, expediente_id))
        conn.commit()
    finally:
        conn.close()


def contexto_panel(vertical_id: str, tenant_id: int, expediente_id: int) -> dict:
    """Para el panel del expediente: el hilo (y, al abrirlo, se marca como leído lo que escribió la persona externa)."""
    h = hilo(vertical_id, tenant_id, expediente_id)
    sin_leer = sum(1 for m in h if m["autor"] == "externo" and not m["leido_en"])
    if sin_leer:
        marcar_leidos(vertical_id, tenant_id, expediente_id)
    return {"mensajes": h, "sin_leer": sin_leer, "activo": enlace_vivo_con_mensajes(vertical_id, tenant_id, expediente_id)}


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    conn.execute("DELETE FROM mensajes_enlace WHERE tenant_id = ?", (tenant_id,))


def pendientes_del_equipo(tenant_id: int, usuario_id: int, supervisor: bool = False, limite: int = 50) -> list[dict]:
    """Expedientes con mensajes de clientes o propietarios sin leer que la persona puede ver (el más reciente primero): `[{vertical, expediente_id, titulo, cliente, n, ultimo, nombre}]`."""
    cond_vis, p_vis = nucleo._visible_sql(usuario_id, supervisor, "x")
    conn = db.get_connection()
    try:
        filas = conn.execute(
            f"SELECT m.vertical_id, m.expediente_id, x.titulo, c.nombre AS cliente, COUNT(*) AS n, MAX(m.creado_en) AS ultimo, "
            f"(SELECT m2.nombre FROM mensajes_enlace m2 WHERE m2.expediente_id = m.expediente_id AND m2.vertical_id = m.vertical_id AND m2.autor = 'externo' AND m2.leido_en IS NULL ORDER BY m2.id DESC LIMIT 1) AS nombre "
            f"FROM mensajes_enlace m JOIN expedientes x ON x.id = m.expediente_id AND x.tenant_id = m.tenant_id LEFT JOIN clientes c ON c.id = x.cliente_id "
            f"WHERE m.tenant_id = ? AND m.autor = 'externo' AND m.leido_en IS NULL AND x.papelera_en IS NULL AND {cond_vis} "
            f"GROUP BY m.vertical_id, m.expediente_id, x.titulo, c.nombre, m.tenant_id ORDER BY ultimo DESC LIMIT ?", [tenant_id, *p_vis, limite]).fetchall()
    finally:
        conn.close()
    return [{"vertical": f["vertical_id"], "expediente_id": f["expediente_id"], "titulo": f["titulo"], "cliente": f["cliente"], "n": f["n"], "ultimo": f["ultimo"], "nombre": f["nombre"]} for f in filas]
