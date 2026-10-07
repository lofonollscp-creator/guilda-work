"""Métricas de uso de un tenant y embudo de activación (solo lectura sobre
registro.db). Alimentan la sección «Actividad» de la ficha del tenant, el
«Customer Journey» y las alertas de riesgo. No modifican nada."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from app import db as plataforma
from . import auth

DIAS_INACTIVO = 30


def _iso(dias: int) -> str:
    return (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")


def hace(iso: str | None) -> str:
    """«hace 24 horas», «hace 3 días»… o «sin actividad»."""
    if not iso:
        return "sin actividad"
    try:
        delta = datetime.now() - datetime.fromisoformat(str(iso)[:19])
    except ValueError:
        return "—"
    seg = max(int(delta.total_seconds()), 0)
    if seg < 3600:
        n = max(seg // 60, 1)
        return f"hace {n} minuto{'s' if n != 1 else ''}"
    if seg < 86400:
        n = seg // 3600
        return f"hace {n} hora{'s' if n != 1 else ''}"
    n = seg // 86400
    if n < 60:
        return f"hace {n} día{'s' if n != 1 else ''}"
    n = n // 30
    return f"hace {n} meses"


def _uno(conn, sql: str, params=()) -> int:
    fila = conn.execute(sql, params).fetchone()
    return int(fila[0] or 0) if fila else 0


def _en(ids: list[int]) -> str:
    return ",".join("?" * len(ids))


def _cuenta(conn, tabla: str, columna_fecha: str, ids: list[int], col_usuario: str = "usuario_id", extra: str = "") -> dict:
    """Total, últimos 30 y 90 días y última fecha de una tabla ligada a usuarios."""
    if not ids:
        return {"total": 0, "d30": 0, "d90": 0, "ultima": None, "usuarios": 0}
    marc = _en(ids)
    base = f"FROM {tabla} WHERE {col_usuario} IN ({marc}) {extra}"
    return {
        "total": _uno(conn, f"SELECT COUNT(*) {base}", ids),
        "d30": _uno(conn, f"SELECT COUNT(*) {base} AND {columna_fecha} >= ?", [*ids, _iso(30)]),
        "d90": _uno(conn, f"SELECT COUNT(*) {base} AND {columna_fecha} >= ?", [*ids, _iso(90)]),
        "ultima": (conn.execute(f"SELECT MAX({columna_fecha}) {base}", ids).fetchone() or [None])[0],
        "usuarios": _uno(conn, f"SELECT COUNT(DISTINCT {col_usuario}) {base} AND {columna_fecha} >= ?", [*ids, _iso(30)]),
    }


def _cobros(tenant_id: int) -> dict:
    """Cobros puntuales gestionados desde el backoffice (tabla cobros)."""
    out = {"cobra_online": False, "ultimo_pago": None, "cobrado_30": 0, "cobrado_90": 0, "pendientes": 0}
    conn = auth.conectar()
    try:
        for f in conn.execute("SELECT importe_centimos, estado, creado_en, actualizado_en FROM cobros WHERE tenant_id = ?", (tenant_id,)):
            if f["estado"] == "pendiente":
                out["pendientes"] += 1
            if f["estado"] != "pagado":
                continue
            fecha = f["actualizado_en"] or f["creado_en"]
            if not out["ultimo_pago"] or fecha > out["ultimo_pago"]:
                out["ultimo_pago"] = fecha
            if fecha >= _iso(30):
                out["cobrado_30"] += f["importe_centimos"]
            if fecha >= _iso(90):
                out["cobrado_90"] += f["importe_centimos"]
    finally:
        conn.close()
    return out


def actividad_tenant(tenant_id: int, modulos: list[dict]) -> dict:
    """Todo lo que muestra la pestaña Actividad: estado, tarjetas por área y
    módulos activados frente a uso real."""
    ids = plataforma.usuarios_de_tenant(tenant_id)
    t = plataforma.obtener_tenant(tenant_id)
    conn = plataforma.get_connection()
    try:
        tareas = _cuenta(conn, "tareas", "COALESCE(fin_en, inicio_en)", ids, extra="AND papelera_en IS NULL")
        lista = _cuenta(conn, "tareas_outlook", "creada_en", ids, extra="AND papelera_en IS NULL")
        notas = _cuenta(conn, "notas", "creada_en", ids, extra="AND papelera_en IS NULL")
        fichajes = _cuenta(conn, "fichajes", "marca_tiempo", ids)
        tiquets = _cuenta(conn, "tiquets", "creado_en", ids)
        ia = _cuenta(conn, "ia_mensajes", "creado_en", ids, extra="AND rol = 'user'")
        envios = _cuenta(conn, "correo_envios", "creado_en", ids, extra="AND estado = 'enviado'")
        tokens = _cuenta(conn, "tokens_api", "COALESCE(ultimo_uso_en, creado_en)", ids)
        cuentas_correo = _uno(conn, f"SELECT COUNT(*) FROM correo_cuentas WHERE usuario_id IN ({_en(ids)})", ids) if ids else 0
        correo = {"total": 0, "d30": 0, "d90": 0, "ultima": None, "usuarios": 0}
        if ids:
            base = f"FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id WHERE c.usuario_id IN ({_en(ids)})"
            correo = {
                "total": _uno(conn, f"SELECT COUNT(*) {base}", ids),
                "d30": _uno(conn, f"SELECT COUNT(*) {base} AND m.fecha >= ?", [*ids, _iso(30)]),
                "d90": _uno(conn, f"SELECT COUNT(*) {base} AND m.fecha >= ?", [*ids, _iso(90)]),
                "ultima": conn.execute(f"SELECT MAX(m.fecha) {base}", ids).fetchone()[0],
                "usuarios": _uno(conn, f"SELECT COUNT(DISTINCT c.usuario_id) {base} AND m.fecha >= ?", [*ids, _iso(30)]),
            }
        clientes = _uno(conn, "SELECT COUNT(*) FROM clientes_fiscales WHERE tenant_id = ? AND papelera_en IS NULL", (tenant_id,))
        venc = conn.execute(
            "SELECT COUNT(*) AS n, SUM(estado = 'presentado') AS presentados, MAX(actualizado_en) AS ultima "
            "FROM vencimientos_fiscales WHERE tenant_id = ? AND papelera_en IS NULL", (tenant_id,)).fetchone()
        usuarios = conn.execute(
            "SELECT COUNT(*) AS n, MAX(creado_en) AS ultimo FROM usuarios WHERE tenant_id = ?", (tenant_id,)).fetchone()
        webhooks = _uno(conn, "SELECT COUNT(*) FROM webhooks WHERE tenant_id = ? AND activo = 1", (tenant_id,))
    finally:
        conn.close()

    ultima = plataforma.ultima_actividad_tenant(tenant_id)
    try:
        inactivo_dias = (datetime.now() - datetime.fromisoformat(str(ultima)[:19])).days if ultima else None
    except ValueError:
        inactivo_dias = None
    if not t["activo"]:
        estado = ("suspendido", "Suspendido")
    elif not ids:
        estado = ("nuevo", "Sin usuarios")
    elif inactivo_dias is None:
        estado = ("riesgo", "Sin uso todavía")
    elif inactivo_dias > DIAS_INACTIVO:
        estado = ("riesgo", "Inactivo")
    else:
        estado = ("ok", "Activo")

    pagos = _cobros(tenant_id)
    pagos["suscripcion"] = bool(t["stripe_subscription_id"]) if "stripe_subscription_id" in t.keys() else False
    pagos["cobra_online"] = pagos["suscripcion"] or bool(pagos["ultimo_pago"])

    en_uso = [  # (clave módulo/función, nombre, métricas, enlace de explicación)
        ("tareas", "Tareas y cronómetro", {"d30": tareas["d30"] + lista["d30"], "ultima": max(filter(None, [tareas["ultima"], lista["ultima"]]), default=None), "usuarios": max(tareas["usuarios"], lista["usuarios"])}),
        ("notas", "Notas", notas),
        ("correo", "Correo", {**correo, "d30": correo["d30"] + envios["d30"], "extra": f"{cuentas_correo} cuenta(s) conectada(s)"}),
        ("fichaje", "Fichaje", fichajes),
        ("clientes", "Clientes y vencimientos fiscales", {"d30": clientes if venc["ultima"] and venc["ultima"] >= _iso(30) else 0, "ultima": venc["ultima"], "usuarios": 0, "extra": f"{clientes} cliente(s), {venc['n'] or 0} vencimiento(s)"}),
        ("tiquets", "Tiquets", tiquets),
        ("ia", "Asistente de IA", ia),
        ("api", "API y webhooks", {**tokens, "extra": f"{webhooks} webhook(s) activo(s)"}),
    ]
    funciones = []
    for clave, nombre, m in en_uso:
        d30 = m.get("d30", 0)
        funciones.append({
            "clave": clave, "nombre": nombre, "d30": d30, "ultima": m.get("ultima"), "usuarios": m.get("usuarios", 0),
            "extra": m.get("extra", ""), "estado": "en uso" if d30 else ("sin uso reciente" if m.get("ultima") else "nunca usado"),
        })
    ocultos = [m for m in modulos if not m["activo"]]
    return {
        "estado": estado, "ultima": ultima, "hace": hace(ultima), "inactivo_dias": inactivo_dias,
        "tareas": {"d30": tareas["d30"] + lista["d30"], "d90": tareas["d90"] + lista["d90"], "ultima": max(filter(None, [tareas["ultima"], lista["ultima"]]), default=None), "total": tareas["total"] + lista["total"]},
        "correo": {**correo, "enviados_30": envios["d30"], "enviados_90": envios["d90"], "cuentas": cuentas_correo},
        "fichaje": fichajes, "notas": notas,
        "vencimientos": {"total": venc["n"] or 0, "presentados": int(venc["presentados"] or 0), "clientes": clientes, "ultima": venc["ultima"]},
        "pagos": pagos,
        "usuarios": {"n": usuarios["n"], "ultimo": usuarios["ultimo"], "activos_30": max((f["usuarios"] for f in funciones), default=0)},
        "funciones": funciones, "modulos_ocultos": len(ocultos), "modulos_total": len(modulos),
    }


# --- Customer Journey (embudo de activación) ---------------------------------

ETAPAS = (
    ("creado", "Tenant creado"), ("usuarios", "Con usuarios"), ("plan", "Con plan"),
    ("uso", "Primer uso"), ("recurrente", "Uso reciente (30 d)"), ("pago", "Con pago"),
)


def journey() -> dict:
    """Etapa alcanzada por cada tenant y totales del embudo."""
    conn = plataforma.get_connection()
    try:
        tenants = [dict(f) for f in conn.execute("SELECT id, nombre, activo, plan_id, creado_en, stripe_subscription_id FROM tenants ORDER BY id")]
    finally:
        conn.close()
    cobrados = set()
    ac = auth.conectar()
    try:
        cobrados = {f[0] for f in ac.execute("SELECT DISTINCT tenant_id FROM cobros WHERE estado = 'pagado'")}
    finally:
        ac.close()
    filas = []
    for t in tenants:
        ids = plataforma.usuarios_de_tenant(t["id"])
        ultima = plataforma.ultima_actividad_tenant(t["id"])
        reciente = bool(ultima and ultima >= _iso(30))
        pago = bool(t["stripe_subscription_id"]) or t["id"] in cobrados
        logros = {"creado": True, "usuarios": bool(ids), "plan": bool(t["plan_id"]), "uso": bool(ultima), "recurrente": reciente, "pago": pago}
        alcanzadas = sum(1 for k, _ in ETAPAS if logros[k])
        siguiente = next((n for k, n in ETAPAS if not logros[k]), None)
        filas.append({**t, "logros": logros, "alcanzadas": alcanzadas, "siguiente": siguiente, "ultima": ultima})
    totales = [{"clave": k, "nombre": n, "n": sum(1 for f in filas if f["logros"][k])} for k, n in ETAPAS]
    return {"filas": filas, "totales": totales, "n": len(filas)}


# --- Notas internas del equipo de Guilda sobre un tenant ---------------------

def notas_tenant(tenant_id: int) -> list[dict]:
    conn = auth.conectar()
    try:
        return [dict(f) for f in conn.execute("SELECT * FROM notas_tenant WHERE tenant_id = ? ORDER BY id DESC LIMIT 100", (tenant_id,))]
    finally:
        conn.close()


def añadir_nota(tenant_id: int, texto: str, admin: str) -> None:
    texto = texto.strip()
    if not texto or len(texto) > 2000:
        raise ValueError("La nota no puede estar vacía ni superar 2000 caracteres.")
    conn = auth.conectar()
    try:
        conn.execute("INSERT INTO notas_tenant (tenant_id, texto, admin_usuario, creado_en) VALUES (?, ?, ?, ?)", (tenant_id, texto, admin, auth._ahora()))
        conn.commit()
    finally:
        conn.close()


def borrar_nota(tenant_id: int, nota_id: int) -> None:
    conn = auth.conectar()
    try:
        conn.execute("DELETE FROM notas_tenant WHERE id = ? AND tenant_id = ?", (nota_id, tenant_id))
        conn.commit()
    finally:
        conn.close()
