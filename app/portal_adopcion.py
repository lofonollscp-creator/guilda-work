"""Adopción del portal, para el despacho: qué clientes lo usan, cuáles nunca entraron y cuáles llevan tiempo sin hacerlo, con un botón para reenviarles la invitación.

Todo sale de lo que ya existe (sesiones del portal, facturas subidas, mensajes): no se rastrea nada nuevo de nadie. El **embudo de uso** (cuántos clientes llegan a cada paso: tienen acceso → han entrado → han subido una
factura → han escrito) es agregado, sin nombres, y es opcional: cada despacho lo enciende si lo quiere ver (por defecto, apagado)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import db

DIAS_INACTIVO = 30
MAX_INVITACIONES_A_LA_VEZ = 50


def embudo_activo(tenant_id: int) -> bool:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT embudo_uso FROM portal_recordatorios_config WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    return bool(f and f["embudo_uso"])


def fijar_embudo(tenant_id: int, activar: bool) -> None:
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_recordatorios_config SET embudo_uso = ? WHERE tenant_id = ?", (1 if activar else 0, tenant_id)).rowcount
        if not n:
            cfg = db.CONFIG_RECORDATORIOS_DEFECTO
            conn.execute("INSERT INTO portal_recordatorios_config (tenant_id, dias_antes, dias_despues, avisar_equipo, asunto, cuerpo, actualizado_en, embudo_uso) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (tenant_id, ",".join(str(x) for x in cfg["dias_antes"]), "", int(cfg["avisar_equipo"]), "", "", db.now_iso(), 1 if activar else 0))
        conn.commit()
    finally:
        conn.close()


def _por_cliente(conn, sql: str, tenant_id: int) -> dict[int, str | int]:
    return {f[0]: f[1] for f in conn.execute(sql, (tenant_id,)).fetchall()}


def resumen(tenant_id: int, hoy: date | None = None) -> dict:
    """{clientes: [{id, nombre, email, estado, ultimo_acceso, personas}], cuentas: {estado: n}, embudo: {...}} de los clientes del despacho.
    Estados: `sin_correo` (no hay a quién invitar), `nunca` (con correo, aún no ha entrado), `inactivo` (lleva más de 30 días sin entrar) y `activo`."""
    hoy = hoy or date.today()
    limite = (datetime.combine(hoy, datetime.min.time()) - timedelta(days=DIAS_INACTIVO)).isoformat(timespec="seconds")
    conn = db.get_connection()
    try:
        clientes = conn.execute("SELECT id, nombre, email FROM clientes_fiscales WHERE tenant_id = ? AND papelera_en IS NULL ORDER BY nombre", (tenant_id,)).fetchall()
        ultimo = _por_cliente(conn, "SELECT cliente_fiscal_id, MAX(ultimo_uso_en) FROM portal_sesiones WHERE tenant_id = ? GROUP BY cliente_fiscal_id", tenant_id)
        personas = _por_cliente(conn, "SELECT cliente_fiscal_id, COUNT(*) FROM portal_contactos WHERE tenant_id = ? AND baja_en IS NULL GROUP BY cliente_fiscal_id", tenant_id)
        subieron = {f[0] for f in conn.execute("SELECT DISTINCT cliente_fiscal_id FROM facturas_contables WHERE tenant_id = ? AND origen = 'portal'", (tenant_id,)).fetchall()}
        escribieron = {f[0] for f in conn.execute("SELECT DISTINCT c.cliente_fiscal_id FROM portal_conversaciones c JOIN portal_conversaciones_mensajes m ON m.conversacion_id = c.id AND m.tenant_id = c.tenant_id "
                                                  "WHERE c.tenant_id = ? AND m.de = 'cliente'", (tenant_id,)).fetchall()}
    finally:
        conn.close()
    filas, cuentas = [], {"sin_correo": 0, "nunca": 0, "inactivo": 0, "activo": 0}
    for c in clientes:
        correo = (c["email"] or "").strip()
        ult = ultimo.get(c["id"])
        estado = "sin_correo" if not correo else ("nunca" if not ult else ("inactivo" if ult < limite else "activo"))
        cuentas[estado] += 1
        filas.append({"id": c["id"], "nombre": c["nombre"], "email": correo, "estado": estado, "ultimo_acceso": ult, "personas": personas.get(c["id"], 0) + (1 if correo else 0)})
    con_acceso = [f for f in filas if f["email"]]
    embudo = {"con_acceso": len(con_acceso), "han_entrado": sum(1 for f in con_acceso if f["ultimo_acceso"]), "activos": cuentas["activo"],
              "han_subido": sum(1 for f in con_acceso if f["id"] in subieron), "han_escrito": sum(1 for f in con_acceso if f["id"] in escribieron)}
    return {"clientes": filas, "cuentas": cuentas, "embudo": embudo}


def invitar(cliente, base_url: str, ip: str | None) -> bool:
    """Manda a la persona titular un enlace de acceso nuevo al portal. False si no tiene correo o no se pudo enviar el correo (el servidor de correo no está configurado o rechazó el envío)."""
    from flask import url_for
    from .notificaciones_email import ErrorNotificacionesEmail, enviar_enlace_portal
    correo = (cliente["email"] or "").strip().lower()
    if not correo:
        return False
    token = db.crear_acceso_cliente_fiscal(cliente["id"], ip, email=correo)
    enlace = base_url.rstrip("/") + url_for("portal_cliente.entrar_con_token", token=token, r="1")
    try:
        enviar_enlace_portal(correo, enlace, tenant_id=cliente["tenant_id"])
    except ErrorNotificacionesEmail:
        return False
    return True
