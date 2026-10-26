"""Acceso a datos de la plataforma: usuarios, despachos, facturación, tokens de API, notificaciones, auditoría, webhooks, perfil y papelera.

Parte de la antigua `db.py`, dividida por dominios sin cambiar su comportamiento: todo lo que no está aquí (la conexión, las constantes y las funciones de otros
dominios) se usa a través de `_db`, que sigue siendo el único espacio de nombres (`_db.nombre` funciona igual que antes y se puede parchear en los tests)."""
import hashlib
import json
import time
import os
import re
import random
import secrets
import sqlite3
import sys
from datetime import date, datetime, timedelta

from . import uso_diferido
from pathlib import Path
from werkzeug.security import check_password_hash, generate_password_hash

from .bd.errores import ErrorBD, ErrorIntegridad
from . import db as _db


# --- Usuarios / autenticación ------------------------------------------------

def crear_usuario(email: str, contrasena: str) -> int:
    """Crea una cuenta con la contraseña ya hasheada (nunca en texto plano).
    Lanza ErrorIntegridad (sqlite3.IntegrityError o la de psycopg) si el email ya existe (el email es UNIQUE)."""
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO usuarios (email, contrasena_hash, creado_en) VALUES (?, ?, ?)",
            (email.strip().lower(), _db.generate_password_hash(contrasena), _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def obtener_usuario_por_email(email: str) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM usuarios WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
    finally:
        conn.close()


def obtener_usuario(usuario_id: int) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    finally:
        conn.close()


def onboarding_visible(usuario_id: int) -> bool:
    conn = _db.get_connection()
    try:
        fila = conn.execute("SELECT onboarding_visible FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        return bool(fila["onboarding_visible"]) if fila else False
    finally:
        conn.close()


def ocultar_onboarding(usuario_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE usuarios SET onboarding_visible = 0 WHERE id = ?", (usuario_id,))
        conn.commit()
    finally:
        conn.close()


def idioma_usuario(usuario_id: int) -> str | None:
    """None si el usuario nunca ha elegido idioma explícitamente -- el
    selector de locale (app/main.py) cae entonces al del navegador."""
    conn = _db.get_connection()
    try:
        fila = conn.execute("SELECT idioma FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        return fila["idioma"] if fila else None
    finally:
        conn.close()


def cambiar_idioma_usuario(usuario_id: int, codigo: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE usuarios SET idioma = ? WHERE id = ?", (codigo, usuario_id))
        conn.commit()
    finally:
        conn.close()


def listar_usuarios() -> list[sqlite3.Row]:
    """Todos los usuarios con el nombre de su tenant (si tiene), para el
    backoffice (Fase 7c) — no existe paginación porque el uso previsto es
    un puñado de usuarios, no miles."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT usuarios.*, tenants.nombre AS tenant_nombre "
            "FROM usuarios LEFT JOIN tenants ON tenants.id = usuarios.tenant_id "
            "ORDER BY usuarios.email"
        ).fetchall()
    finally:
        conn.close()


def es_admin(usuario_id: int) -> bool:
    usuario = _db.obtener_usuario(usuario_id)
    return usuario is not None and usuario["rol"] == "admin"


def hacer_admin(email: str) -> None:
    """Lanza ValueError si no existe ningún usuario con ese email."""
    conn = _db.get_connection()
    try:
        cur = conn.execute("UPDATE usuarios SET rol = 'admin' WHERE email = ?", (email.strip().lower(),))
        if cur.rowcount == 0:
            raise ValueError(f"No existe ningún usuario con el email '{email}'.")
        conn.commit()
    finally:
        conn.close()


def es_gestor_fichajes(usuario_id: int) -> bool:
    usuario = _db.obtener_usuario(usuario_id)
    return usuario is not None and bool(usuario["gestor_fichajes"])


def asignar_gestor_fichajes(usuario_id: int, valor: bool) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE usuarios SET gestor_fichajes = ? WHERE id = ?", (int(valor), usuario_id))
        conn.commit()
    finally:
        conn.close()


def es_supervisor_tenant(usuario_id: int) -> bool:
    usuario = _db.obtener_usuario(usuario_id)
    return usuario is not None and bool(usuario["supervisor_tenant"])


def asignar_supervisor_tenant(usuario_id: int, valor: bool) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE usuarios SET supervisor_tenant = ? WHERE id = ?", (int(valor), usuario_id))
        conn.commit()
    finally:
        conn.close()


def usuario_pertenece_a_tenant(usuario_id: int, tenant_id: int) -> bool:
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            "SELECT 1 FROM usuarios WHERE id = ? AND tenant_id = ?", (usuario_id, tenant_id),
        ).fetchone()
        return fila is not None
    finally:
        conn.close()


def fijar_fichaje_geolocalizacion(tenant_id: int, valor: bool) -> None:
    """Opt-in por tenant (Fase G3) -- una gestoría sin trabajadores en
    remoto no tiene por qué recoger ubicación al fichar (RGPD). Ver
    app/rutas_fichaje.py:marcar()."""
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE tenants SET fichaje_geolocalizacion = ? WHERE id = ?", (int(valor), tenant_id))
        conn.commit()
    finally:
        conn.close()


def quitar_admin(email: str) -> None:
    """Lanza ValueError si no existe ningún usuario con ese email."""
    conn = _db.get_connection()
    try:
        cur = conn.execute("UPDATE usuarios SET rol = 'usuario' WHERE email = ?", (email.strip().lower(),))
        if cur.rowcount == 0:
            raise ValueError(f"No existe ningún usuario con el email '{email}'.")
        conn.commit()
    finally:
        conn.close()


def verificar_credenciales(email: str, contrasena: str) -> sqlite3.Row | None:
    """Devuelve la fila del usuario si el email existe y la contraseña es
    correcta; None en cualquier otro caso (sin distinguir el motivo, para no
    filtrar si un email concreto existe o no).

    Solo queda en uso para el usuario "local" del modo escritorio (que
    nunca pasa por Kratos, ver `usuario_local_id`) — el login real
    (hospedado, web/API) verifica credenciales contra Kratos a partir de
    la Fase 7a; ver `app/kratos.py`."""
    usuario = _db.obtener_usuario_por_email(email)
    if usuario is None or not _db.check_password_hash(usuario["contrasena_hash"], contrasena):
        return None
    return usuario


# --- Vínculo con la identidad de Ory Kratos (Fase 7a) -------------------

def usuario_por_kratos_id(identity_id: str) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM usuarios WHERE kratos_identity_id = ?", (identity_id,)
        ).fetchone()
    finally:
        conn.close()


def vincular_kratos_id(usuario_id: int, identity_id: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE usuarios SET kratos_identity_id = ? WHERE id = ?", (identity_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


def crear_usuario_vinculado_a_kratos(email: str, identity_id: str) -> int:
    """Crea la fila local de `usuarios` para una identidad que YA existe en
    Kratos (login/registro real, a partir de la Fase 7a) — no guarda
    ninguna contraseña propia, Kratos es quien la custodia."""
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO usuarios (email, contrasena_hash, kratos_identity_id, creado_en) "
            "VALUES (?, ?, ?, ?)",
            (email.strip().lower(), "", identity_id, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# --- Tenants (Fase 7c.3) -------------------------------------------------

def crear_tenant(nombre: str) -> int:
    """Lanza ErrorIntegridad (sqlite3.IntegrityError o la de psycopg) si el nombre ya existe (UNIQUE)."""
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO tenants (nombre, creado_en) VALUES (?, ?)",
            (nombre.strip(), _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_tenants() -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute("SELECT * FROM tenants WHERE id > 0 ORDER BY nombre").fetchall()           # el 0 es «Plataforma», no un despacho
    finally:
        conn.close()


def listar_tenants_con_conteo() -> list[sqlite3.Row]:
    """Como listar_tenants(), pero con el nº de usuarios asignados a cada
    uno (columna `n_usuarios`) — para la tabla del backoffice (Fase 7c)."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT tenants.*, COUNT(usuarios.id) AS n_usuarios "
            "FROM tenants LEFT JOIN usuarios ON usuarios.tenant_id = tenants.id "
            "GROUP BY tenants.id ORDER BY tenants.nombre"
        ).fetchall()
    finally:
        conn.close()


def resumen_equipos_tenants() -> dict[int, dict]:
    """Por tenant: usuarios totales, administradores, gestores de fichajes,
    supervisores, clientes fiscales activos y nombre del plan -- una sola
    consulta para las pantallas de visión global del backoffice."""
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            """SELECT t.id,
                      COALESCE(u.n, 0) AS usuarios, COALESCE(u.admins, 0) AS admins, COALESCE(u.gestores, 0) AS gestores, COALESCE(u.supervisores, 0) AS supervisores,
                      COALESCE(c.n, 0) AS clientes, p.nombre AS plan
               FROM tenants t
               LEFT JOIN (SELECT tenant_id, COUNT(*) AS n, SUM(CASE WHEN rol = 'admin' THEN 1 ELSE 0 END) AS admins,
                                 SUM(CASE WHEN gestor_fichajes = 1 THEN 1 ELSE 0 END) AS gestores, SUM(CASE WHEN supervisor_tenant = 1 THEN 1 ELSE 0 END) AS supervisores
                          FROM usuarios WHERE tenant_id IS NOT NULL GROUP BY tenant_id) u ON u.tenant_id = t.id
               LEFT JOIN (SELECT tenant_id, COUNT(*) AS n FROM clientes_fiscales WHERE papelera_en IS NULL GROUP BY tenant_id) c ON c.tenant_id = t.id
               LEFT JOIN planes_guilda p ON p.id = t.plan_id WHERE t.id > 0"""
        ).fetchall()
        return {f["id"]: dict(f) for f in filas}
    finally:
        conn.close()


def resumen_usuarios_backoffice() -> dict[int, dict]:
    """Por usuario: nº de dispositivos/tokens y último uso de cualquiera de ellos."""
    uso_diferido.volcar()
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            """SELECT usuario_id, COUNT(*) AS dispositivos, MAX(COALESCE(ultimo_uso_en, creado_en)) AS ultimo_uso
               FROM tokens_api GROUP BY usuario_id"""
        ).fetchall()
        return {f["usuario_id"]: dict(f) for f in filas}
    finally:
        conn.close()


def resumen_plataforma() -> dict:
    """Métricas agregadas para la pantalla "Resumen" del backoffice --
    una sola función porque todas las consultas son baratas (COUNT/SUM
    sobre tablas pequeñas) y siempre se piden juntas."""
    conn = _db.get_connection()
    try:
        tenants_total = conn.execute("SELECT COUNT(*) FROM tenants WHERE id > 0").fetchone()[0]
        tenants_activos = conn.execute("SELECT COUNT(*) FROM tenants WHERE activo = 1 AND id > 0").fetchone()[0]
        usuarios_total = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        mrr_centimos = conn.execute(
            "SELECT COALESCE(SUM(pg.precio_mensual_centimos), 0) FROM tenants t "
            "JOIN planes_guilda pg ON pg.id = t.plan_id "
            "WHERE t.suscripcion_estado = 'activa'"
        ).fetchone()[0]
        tenants_recientes = conn.execute(
            "SELECT id, nombre, creado_en FROM tenants WHERE id > 0 ORDER BY creado_en DESC LIMIT 5"
        ).fetchall()
        return {
            "tenants_total": tenants_total,
            "tenants_activos": tenants_activos,
            "usuarios_total": usuarios_total,
            "mrr_centimos": mrr_centimos,
            "tenants_recientes": tenants_recientes,
        }
    finally:
        conn.close()


def listar_suscripciones_tenants() -> list[sqlite3.Row]:
    """Todos los tenants con su plan (si tiene) y estado de suscripción,
    para la vista agregada de Ingresos del backoffice -- JOIN con
    planes_guilda para traer nombre/precio en una sola consulta."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT tenants.*, planes_guilda.nombre AS plan_nombre, "
            "planes_guilda.precio_mensual_centimos AS plan_precio_centimos "
            "FROM tenants LEFT JOIN planes_guilda ON planes_guilda.id = tenants.plan_id "
            "ORDER BY tenants.nombre"
        ).fetchall()
    finally:
        conn.close()


def renombrar_tenant(tenant_id: int, nuevo_nombre: str) -> None:
    """Lanza ErrorIntegridad (sqlite3.IntegrityError o la de psycopg) si el nombre ya existe (UNIQUE)."""
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE tenants SET nombre = ? WHERE id = ?", (nuevo_nombre.strip(), tenant_id))
        conn.commit()
    finally:
        conn.close()


def alternar_activo_tenant(tenant_id: int, valor: bool) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE tenants SET activo = ? WHERE id = ?", (int(valor), tenant_id))
        conn.commit()
    finally:
        conn.close()


def ultima_actividad_tenant(tenant_id: int) -> str | None:
    """Fecha/hora del registro más reciente entre tareas/notas/fichajes/
    correo de cualquier usuario del tenant -- ISO 8601 o None si el tenant
    no tiene ninguna actividad todavía. Solo para mostrar "hace X" en el
    backoffice, no se usa para ninguna decisión de negocio."""
    ids = _db.usuarios_de_tenant(tenant_id)
    if not ids:
        return None
    conn = _db.get_connection()
    try:
        marcadores = ",".join("?" * len(ids))
        fila = conn.execute(
            f"""SELECT MAX(fecha) AS ultima FROM (
                SELECT MAX(COALESCE(fin_en, inicio_en)) AS fecha FROM tareas WHERE usuario_id IN ({marcadores})
                UNION ALL
                SELECT MAX(creada_en) AS fecha FROM notas WHERE usuario_id IN ({marcadores})
                UNION ALL
                SELECT MAX(creado_en) AS fecha FROM fichajes WHERE usuario_id IN ({marcadores})
                UNION ALL
                SELECT MAX(m.fecha) AS fecha FROM correo_mensajes m
                    JOIN correo_cuentas cu ON cu.id = m.cuenta_id
                    WHERE cu.usuario_id IN ({marcadores})
            )""",
            ids * 4,
        ).fetchone()
        return fila["ultima"] if fila else None
    finally:
        conn.close()


# --- Stripe Connect (bloque 5 -- cada tenant cobra a sus clientes) --------

def guardar_stripe_account_id(tenant_id: int, stripe_account_id: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE tenants SET stripe_account_id = ? WHERE id = ?", (stripe_account_id, tenant_id))
        conn.commit()
    finally:
        conn.close()


def marcar_stripe_onboarding_completado(tenant_id: int, valor: bool) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE tenants SET stripe_onboarding_completado = ? WHERE id = ?", (int(valor), tenant_id))
        conn.commit()
    finally:
        conn.close()


def registrar_pago_vencimiento(vencimiento_id: int, stripe_checkout_session_id: str, importe_centimos: int) -> bool:
    """True si se registró un pago nuevo, False si esta sesión de
    Checkout ya se había procesado antes (el webhook de Stripe puede
    reintentar la misma entrega -- stripe_checkout_session_id es UNIQUE,
    así que un segundo intento no duplica el registro)."""
    conn = _db.get_connection()
    try:
        try:
            conn.execute(
                "INSERT INTO vencimientos_fiscales_pagos (vencimiento_id, stripe_checkout_session_id, importe_centimos, pagado_en) "
                "VALUES (?, ?, ?, ?)",
                (vencimiento_id, stripe_checkout_session_id, importe_centimos, _db.now_iso()),
            )
            conn.commit()
            return True
        except ErrorIntegridad:
            return False
    finally:
        conn.close()


def pago_de_vencimiento(vencimiento_id: int) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM vencimientos_fiscales_pagos WHERE vencimiento_id = ? ORDER BY id DESC LIMIT 1",
            (vencimiento_id,),
        ).fetchone()
    finally:
        conn.close()


# --- Facturación de plataforma (bloque 6 -- Guilda Work cobra a sus tenants)

def crear_plan_guilda(nombre: str, descripcion: str | None, precio_mensual_centimos: int | None, max_usuarios: int | None) -> int:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO planes_guilda (nombre, descripcion, precio_mensual_centimos, max_usuarios, creado_en) "
            "VALUES (?, ?, ?, ?, ?)",
            (nombre.strip(), descripcion, precio_mensual_centimos, max_usuarios, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_planes_guilda(solo_activos: bool = False) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        sql = "SELECT * FROM planes_guilda"
        if solo_activos:
            sql += " WHERE activo = 1"
        sql += " ORDER BY precio_mensual_centimos IS NULL, precio_mensual_centimos, nombre"
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def obtener_plan_guilda(plan_id: int) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute("SELECT * FROM planes_guilda WHERE id = ?", (plan_id,)).fetchone()
    finally:
        conn.close()


def editar_plan_guilda(plan_id: int, nombre: str, descripcion: str | None, precio_mensual_centimos: int | None, max_usuarios: int | None) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE planes_guilda SET nombre = ?, descripcion = ?, precio_mensual_centimos = ?, max_usuarios = ? WHERE id = ?",
            (nombre.strip(), descripcion, precio_mensual_centimos, max_usuarios, plan_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_stripe_price_id_plan(plan_id: int, stripe_price_id: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE planes_guilda SET stripe_price_id = ? WHERE id = ?", (stripe_price_id, plan_id))
        conn.commit()
    finally:
        conn.close()


def crear_extra_guilda(nombre: str, descripcion: str | None, precio_centimos: int | None) -> int:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO extras_guilda (nombre, descripcion, precio_centimos, creado_en) VALUES (?, ?, ?, ?)",
            (nombre.strip(), descripcion, precio_centimos, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_extras_guilda() -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute("SELECT * FROM extras_guilda ORDER BY nombre").fetchall()
    finally:
        conn.close()


def obtener_extra_guilda(extra_id: int) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute("SELECT * FROM extras_guilda WHERE id = ?", (extra_id,)).fetchone()
    finally:
        conn.close()


def guardar_stripe_price_id_extra(extra_id: int, stripe_price_id: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE extras_guilda SET stripe_price_id = ? WHERE id = ?", (stripe_price_id, extra_id))
        conn.commit()
    finally:
        conn.close()


def editar_extra_guilda(extra_id: int, nombre: str, descripcion: str | None, precio_centimos: int | None) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE extras_guilda SET nombre = ?, descripcion = ?, precio_centimos = ? WHERE id = ?",
            (nombre.strip(), descripcion, precio_centimos, extra_id),
        )
        conn.commit()
    finally:
        conn.close()


def limpiar_stripe_price_id_plan(plan_id: int) -> None:
    """Los Price de Stripe son inmutables -- si cambia el precio de un
    plan ya sincronizado, el stripe_price_id guardado deja de
    corresponder al importe mostrado. Se limpia para que
    "Sincronizar con Stripe" vuelva a estar disponible y cree un Price
    nuevo con el importe correcto (el Price antiguo queda huérfano en
    Stripe, sin usarse más, pero Stripe no permite borrarlos)."""
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE planes_guilda SET stripe_price_id = NULL WHERE id = ?", (plan_id,))
        conn.commit()
    finally:
        conn.close()


def limpiar_stripe_price_id_extra(extra_id: int) -> None:
    """Mismo motivo que limpiar_stripe_price_id_plan, para extras."""
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE extras_guilda SET stripe_price_id = NULL WHERE id = ?", (extra_id,))
        conn.commit()
    finally:
        conn.close()


def asignar_plan_tenant(tenant_id: int, plan_id: int | None) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE tenants SET plan_id = ? WHERE id = ?", (plan_id, tenant_id))
        conn.commit()
    finally:
        conn.close()


def guardar_stripe_customer_id(tenant_id: int, stripe_customer_id: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE tenants SET stripe_customer_id = ? WHERE id = ?", (stripe_customer_id, tenant_id))
        conn.commit()
    finally:
        conn.close()


def guardar_stripe_subscription_id(tenant_id: int, stripe_subscription_id: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE tenants SET stripe_subscription_id = ? WHERE id = ?", (stripe_subscription_id, tenant_id))
        conn.commit()
    finally:
        conn.close()


def actualizar_suscripcion_estado(tenant_id: int, estado: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE tenants SET suscripcion_estado = ? WHERE id = ?", (estado, tenant_id))
        conn.commit()
    finally:
        conn.close()


def tenant_por_stripe_customer_id(stripe_customer_id: str) -> sqlite3.Row | None:
    """Usado por el webhook de Stripe (evento ligado a un customer, no a
    un tenant_id de Guilda Work directamente) para resolver a qué tenant
    corresponde."""
    conn = _db.get_connection()
    try:
        return conn.execute("SELECT * FROM tenants WHERE stripe_customer_id = ?", (stripe_customer_id,)).fetchone()
    finally:
        conn.close()


def activar_extra_tenant(tenant_id: int, extra_id: int, cantidad: int = 1, activo_hasta: str | None = None) -> int:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO tenants_extras_activos (tenant_id, extra_id, cantidad, activo_desde, activo_hasta, creado_en) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tenant_id, extra_id, cantidad, _db.now_iso(), activo_hasta, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_extras_activos_tenant(tenant_id: int) -> list[sqlite3.Row]:
    """Solo los que no han caducado -- activo_hasta NULL es indefinido,
    con fecha se compara contra el momento actual."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT tea.*, eg.nombre, eg.precio_centimos FROM tenants_extras_activos tea "
            "JOIN extras_guilda eg ON eg.id = tea.extra_id "
            "WHERE tea.tenant_id = ? AND (tea.activo_hasta IS NULL OR tea.activo_hasta >= ?) "
            "ORDER BY tea.activo_desde DESC",
            (tenant_id, _db.now_iso()),
        ).fetchall()
    finally:
        conn.close()


def desactivar_extra_tenant(tenant_extra_id: int) -> None:
    """Corta un extra activo AHORA (fija activo_hasta a un instante ya
    pasado) en vez de borrar la fila -- listar_extras_activos_tenant()
    ya deja de devolverlo desde la siguiente consulta, pero el
    historial de que estuvo activo se conserva, mismo criterio de "no
    perder datos" que el resto del proyecto. Un segundo antes de ahora
    (no exactamente ahora) porque now_iso() solo tiene precisión de
    segundo y el filtro de listar_extras_activos_tenant es inclusive
    (activo_hasta >= ahora) -- con el mismo instante, una consulta en
    el mismo segundo seguiría viéndolo activo."""
    conn = _db.get_connection()
    try:
        activo_hasta = (_db.datetime.now() - _db.timedelta(seconds=1)).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE tenants_extras_activos SET activo_hasta = ? WHERE id = ?",
            (activo_hasta, tenant_extra_id),
        )
        conn.commit()
    finally:
        conn.close()


def contar_fichajes_tenant(tenant_id: int) -> int:
    conn = _db.get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM fichajes WHERE tenant_id = ?", (tenant_id,)).fetchone()[0]
    finally:
        conn.close()


def borrar_tenant(tenant_id: int, incluir_fichajes: bool = False) -> None:
    if tenant_id == 0:
        raise ValueError("El despacho «Plataforma» es interno y no se puede borrar.")
    """Borra el tenant y todo lo que cuelga de él (clientes fiscales con sus
    vencimientos, documentos, mensajes, pagos y accesos del portal; webhooks y
    sus entregas; extras y accesos de facturación). Los usuarios quedan sin
    tenant, no se borran. En SQLite se conservan también sus tareas, notas y correo; en PostgreSQL con despachos, lo que se creó en ese despacho (también lo
    personal) se borra con él: la columna de despacho de cada fila no se puede cambiar.

    El registro de jornada (fichajes) hay que conservarlo cuatro años por ley
    (art. 34.9 ET): si el tenant tiene fichajes, se rechaza el borrado salvo que
    se pida expresamente `incluir_fichajes`. Todo ocurre en una sola
    transacción: o se borra todo o no se toca nada."""
    conn = _db.get_connection()
    try:
        if not incluir_fichajes:
            n = conn.execute("SELECT COUNT(*) FROM fichajes WHERE tenant_id = ?", (tenant_id,)).fetchone()[0]
            if n:
                raise ValueError(
                    f"El tenant tiene {n} fichajes, que la ley obliga a conservar cuatro años. "
                    "Expórtalos y confirma que quieres borrarlos también."
                )
        if _db._bd.es_postgres(conn):
            conn.modo_secuencial()
        from . import auditoria, avisos, certificados, traspasos
        auditoria.purgar_tenant(conn, tenant_id)                   # el despacho se elimina entero: su rastro también (solo aquí se puede borrar)
        avisos.borrar_datos_de_tenant(conn, tenant_id)
        traspasos.borrar_datos_de_tenant(conn, tenant_id)
        certificados.borrar_datos_de_tenant(conn, tenant_id)      # antes que los clientes fiscales: sus vínculos los referencian
        from . import automatizaciones, tareas_trabajo
        automatizaciones.borrar_datos_de_tenant(conn, tenant_id)
        tareas_trabajo.borrar_datos_de_tenant(conn, tenant_id)    # antes que los clientes fiscales: tarea_clientes los referencia
        conn.execute("DELETE FROM concesiones_cliente WHERE tenant_id = ?", (tenant_id,))
        venc = "SELECT id FROM vencimientos_fiscales WHERE tenant_id = ?"
        clientes = "SELECT id FROM clientes_fiscales WHERE tenant_id = ?"
        conn.execute(f"DELETE FROM vencimientos_fiscales_pagos WHERE vencimiento_id IN ({venc})", (tenant_id,))
        conn.execute("DELETE FROM vencimientos_fiscales WHERE tenant_id = ?", (tenant_id,))  # documentos, mensajes y recordatorios en cascada
        for tabla in ("correo_mensajes", "tareas_outlook", "notas", "correo_reglas"):
            conn.execute(f"UPDATE {tabla} SET cliente_fiscal_id = NULL WHERE cliente_fiscal_id IN ({clientes})", (tenant_id,))
        conn.execute(f"DELETE FROM clientes_fiscales_accesos WHERE cliente_fiscal_id IN ({clientes})", (tenant_id,))
        conn.execute("DELETE FROM clientes_fiscales WHERE tenant_id = ?", (tenant_id,))
        from . import nucleo
        nucleo.borrar_datos_de_tenant(conn, tenant_id)
        conn.execute("DELETE FROM webhooks_entregas WHERE webhook_id IN (SELECT id FROM webhooks WHERE tenant_id = ?)", (tenant_id,))
        conn.execute("DELETE FROM webhooks WHERE tenant_id = ?", (tenant_id,))
        conn.execute("DELETE FROM fichaje_avisos WHERE entrada_id IN (SELECT id FROM fichajes WHERE tenant_id = ?)", (tenant_id,))
        conn.execute("DELETE FROM fichaje_avisos_turno WHERE entrada_id IN (SELECT id FROM fichajes WHERE tenant_id = ?)", (tenant_id,))
        conn.execute("DELETE FROM fichajes WHERE tenant_id = ?", (tenant_id,))
        conn.execute("DELETE FROM tenants_extras_activos WHERE tenant_id = ?", (tenant_id,))
        conn.execute("DELETE FROM facturacion_accesos WHERE tenant_id = ?", (tenant_id,))
        conn.execute("DELETE FROM tenants_herramientas_ocultas WHERE tenant_id = ?", (tenant_id,))
        if _db._bd.es_postgres(conn):
            _db._bd.tenant.borrar_filas_de_tenant(conn, tenant_id)
        conn.execute("DELETE FROM usuarios_tenants WHERE tenant_id = ?", (tenant_id,))
        # quien tenía este despacho como principal pasa al siguiente que tenga, o a ninguno
        conn.execute("UPDATE usuarios SET tenant_id = (SELECT MIN(m.tenant_id) FROM usuarios_tenants m WHERE m.usuario_id = usuarios.id) WHERE tenant_id = ?", (tenant_id,))
        conn.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def desasignar_tenant(usuario_id: int) -> None:
    """La persona deja TODOS sus despachos."""
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE usuarios SET tenant_id = NULL WHERE id = ?", (usuario_id,))
        conn.execute("DELETE FROM usuarios_tenants WHERE usuario_id = ?", (usuario_id,))
        conn.commit()
    finally:
        conn.close()


def obtener_tenant(tenant_id: int) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()


# --- Visibilidad de herramientas por tenant ----------------------------------

def ocultar_herramienta(tenant_id: int, herramienta_id: str) -> None:
    """Idempotente: ocultar dos veces la misma herramienta no falla."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "INSERT INTO tenants_herramientas_ocultas (tenant_id, herramienta_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (tenant_id, herramienta_id),
        )
        conn.commit()
    finally:
        conn.close()


def mostrar_herramienta(tenant_id: int, herramienta_id: str) -> None:
    """Idempotente: quitar la ocultación de una herramienta ya visible no falla."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "DELETE FROM tenants_herramientas_ocultas WHERE tenant_id = ? AND herramienta_id = ?",
            (tenant_id, herramienta_id),
        )
        conn.commit()
    finally:
        conn.close()


def herramientas_ocultas_de_tenant(tenant_id: int) -> set[str]:
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            "SELECT herramienta_id FROM tenants_herramientas_ocultas WHERE tenant_id = ?",
            (tenant_id,),
        ).fetchall()
        return {f["herramienta_id"] for f in filas}
    finally:
        conn.close()


def herramientas_ocultas_de_tenants(tenant_ids: list[int]) -> dict[int, set[str]]:
    """Igual que herramientas_ocultas_de_tenant() pero para varios tenants a
    la vez (una consulta con IN en vez de una por tenant) -- usado en el
    backoffice, que antes hacía una llamada por tenant listado."""
    if not tenant_ids:
        return {}
    conn = _db.get_connection()
    try:
        marcas = ",".join("?" * len(tenant_ids))
        filas = conn.execute(
            f"SELECT tenant_id, herramienta_id FROM tenants_herramientas_ocultas WHERE tenant_id IN ({marcas})",
            tenant_ids,
        ).fetchall()
        resultado: dict[int, set[str]] = {tid: set() for tid in tenant_ids}
        for f in filas:
            resultado[f["tenant_id"]].add(f["herramienta_id"])
        return resultado
    finally:
        conn.close()


def adopcion_herramientas(ocultas_por_tenant: dict[int, set[str]], catalogo_ids: list[str]) -> dict[str, int]:
    """Nº de tenants que tienen cada herramienta VISIBLE (no oculta) --
    para la pantalla "Catálogo de herramientas" del backoffice. Cálculo
    en Python (no SQL) porque la fuente de verdad ya está en memoria
    tras herramientas_ocultas_de_tenants(), sin tabla propia que
    consultar -- ausencia de fila = visible, ver db.py más arriba."""
    return {
        herramienta_id: sum(1 for ocultas in ocultas_por_tenant.values() if herramienta_id not in ocultas)
        for herramienta_id in catalogo_ids
    }


def guardar_facturascripts(tenant_id: int, url: str, admin_user: str, admin_pass: str) -> None:
    """Guarda cómo llegar a la instancia de FacturaScripts recién
    aprovisionada de un tenant — ver app/facturascripts.py:aprovisionar_tenant."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET facturascripts_url = ?, facturascripts_admin_user = ?, "
            "facturascripts_admin_pass = ? WHERE id = ?",
            (url, admin_user, admin_pass, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_facturascripts_api_key(tenant_id: int, api_key: str) -> None:
    """La API Key se genera a mano dentro de cada instancia (paso manual,
    ver HOSTING.md 8.21) — esto solo la guarda una vez que el admin la
    pega en el backoffice."""
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE tenants SET facturascripts_api_key = ? WHERE id = ?", (api_key, tenant_id))
        conn.commit()
    finally:
        conn.close()


def guardar_documenso_api_key(tenant_id: int, api_key: str) -> None:
    """El token se genera a mano dentro del Equipo de Documenso de ese
    tenant (paso manual, ver HOSTING.md) — esto solo lo guarda una vez
    que el admin lo pega en el backoffice."""
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE tenants SET documenso_api_key = ? WHERE id = ?", (api_key, tenant_id))
        conn.commit()
    finally:
        conn.close()


def guardar_paperless(tenant_id: int, group_id: int, user_id: int, api_key: str) -> None:
    """A diferencia de facturascripts/documenso, aquí no hay ningún paso
    manual: app/paperless.py:aprovisionar_tenant() crea el Grupo, el
    usuario de servicio y su token por API, esto solo los guarda."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET paperless_group_id = ?, paperless_user_id = ?, paperless_api_key = ? WHERE id = ?",
            (group_id, user_id, api_key, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_baserow(tenant_id: int, workspace_id: int, api_key: str) -> None:
    """Igual que guardar_paperless: sin pasos manuales,
    app/baserow.py:aprovisionar_tenant() crea el Workspace y su token
    por API, esto solo los guarda."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET baserow_workspace_id = ?, baserow_api_key = ? WHERE id = ?",
            (workspace_id, api_key, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_calcom(tenant_id: int, email: str, admin_pass: str) -> None:
    """Guarda el usuario de servicio de Cal.diy recién creado para un
    tenant — ver app/calcom.py:aprovisionar_tenant. admin_pass se enseña
    una sola vez en el backoffice, igual que facturascripts_admin_pass."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET calcom_email = ?, calcom_admin_pass = ? WHERE id = ?",
            (email, admin_pass, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_calcom_api_key(tenant_id: int, api_key: str) -> None:
    """La API Key se genera a mano desde la propia cuenta de servicio
    (paso manual, ver HOSTING.md 8.25) — esto solo la guarda una vez que
    el admin la pega en el backoffice."""
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE tenants SET calcom_api_key = ? WHERE id = ?", (api_key, tenant_id))
        conn.commit()
    finally:
        conn.close()


def guardar_listmonk(tenant_id: int, list_id: int, list_role_id: int, api_key: str) -> None:
    """Igual que guardar_paperless: sin pasos manuales,
    app/listmonk.py:aprovisionar_tenant() crea la Lista, el Rol de lista
    y el usuario de servicio por API, esto solo los guarda."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET listmonk_list_id = ?, listmonk_list_role_id = ?, listmonk_api_key = ? WHERE id = ?",
            (list_id, list_role_id, api_key, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_stalwart(
    tenant_id: int,
    stalwart_tenant_id: str,
    domain_id: str,
    domain_name: str,
    account_id: str,
    api_key: str,
) -> None:
    """Igual que guardar_listmonk: sin pasos manuales,
    app/stalwart.py:aprovisionar_tenant() crea el Tenant, el Domain
    (con el dominio propio real del cliente), la Account y el ApiKey por
    API, esto solo los guarda."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET stalwart_tenant_id = ?, stalwart_domain_id = ?, "
            "stalwart_domain_name = ?, stalwart_account_id = ?, stalwart_api_key = ? "
            "WHERE id = ?",
            (stalwart_tenant_id, domain_id, domain_name, account_id, api_key, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_ntfy(tenant_id: int, topic: str, token: str) -> None:
    """Igual que guardar_stalwart: sin pasos manuales,
    app/ntfy.py:aprovisionar_tenant() crea el usuario+ACL+token, esto
    solo los guarda."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET ntfy_topic = ?, ntfy_token = ? WHERE id = ?",
            (topic, token, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_umami(tenant_id: int, team_id: str, website_id: str) -> None:
    """Igual que guardar_ntfy: sin pasos manuales,
    app/umami.py:aprovisionar_tenant() crea el Team+sitio, esto solo los
    guarda."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET umami_team_id = ?, umami_website_id = ? WHERE id = ?",
            (team_id, website_id, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def obtener_tenant_por_nombre(nombre: str) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute("SELECT * FROM tenants WHERE nombre = ?", (nombre.strip(),)).fetchone()
    finally:
        conn.close()


def asignar_tenant(usuario_id: int, tenant_id: int) -> None:
    """MUEVE a la persona a ese despacho: pasa a ser su único despacho y el principal (como siempre). Para pertenecer a varios, `anadir_usuario_a_tenant`."""
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE usuarios SET tenant_id = ? WHERE id = ?", (tenant_id, usuario_id))
        conn.execute("DELETE FROM usuarios_tenants WHERE usuario_id = ? AND tenant_id != ?", (usuario_id, tenant_id))
        conn.execute("INSERT INTO usuarios_tenants (usuario_id, tenant_id, creado_en) VALUES (?, ?, ?) ON CONFLICT DO NOTHING", (usuario_id, tenant_id, _db.now_iso()))
        conn.commit()
    finally:
        conn.close()


def tenants_de_usuario(usuario_id: int) -> list[dict]:
    """Despachos de la persona, el principal primero: [{id, nombre, principal}]."""
    conn = _db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            "SELECT t.id, t.nombre, CASE WHEN t.id = u.tenant_id THEN 1 ELSE 0 END AS principal FROM usuarios_tenants m JOIN tenants t ON t.id = m.tenant_id "
            "JOIN usuarios u ON u.id = m.usuario_id WHERE m.usuario_id = ? ORDER BY principal DESC, LOWER(t.nombre), t.id", (usuario_id,))]
    finally:
        conn.close()


def tenant_activo(usuario_id: int, preferido: int | None = None) -> int | None:
    """Despacho con el que trabaja la persona en esta sesión: el `preferido` (el que eligió en el selector) si sigue siendo suyo; si no, el principal."""
    conn = _db.get_connection(plataforma=True)
    try:
        principal = conn.execute("SELECT tenant_id FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        principal = principal["tenant_id"] if principal else None
        if preferido is None or preferido == principal:
            return principal
        return preferido if conn.execute("SELECT 1 FROM usuarios_tenants WHERE usuario_id = ? AND tenant_id = ?", (usuario_id, preferido)).fetchone() else principal
    finally:
        conn.close()


_ATRIBUTOS_POR_DESPACHO = ("gestor_fichajes", "supervisor_tenant", "custodio_certificados", "tarifa_hora_centimos")


def atributos_en_despacho(usuario_id: int, tenant_id: int | None) -> dict:
    """gestor_fichajes, supervisor_tenant, custodio_certificados y tarifa_hora_centimos de la persona EN ese despacho: en el principal, los de `usuarios`; en los demás, los de su pertenencia."""
    vacio = {"gestor_fichajes": 0, "supervisor_tenant": 0, "custodio_certificados": 0, "tarifa_hora_centimos": None}
    if tenant_id is None:
        return vacio
    conn = _db.get_connection(plataforma=True)
    try:
        u = conn.execute("SELECT tenant_id, gestor_fichajes, supervisor_tenant, custodio_certificados, tarifa_hora_centimos FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if u is None:
            return vacio
        if u["tenant_id"] == tenant_id:
            return {k: u[k] for k in _ATRIBUTOS_POR_DESPACHO}
        m = conn.execute("SELECT gestor_fichajes, supervisor_tenant, custodio_certificados, tarifa_hora_centimos FROM usuarios_tenants WHERE usuario_id = ? AND tenant_id = ?",
                         (usuario_id, tenant_id)).fetchone()
        return {k: m[k] for k in _ATRIBUTOS_POR_DESPACHO} if m else vacio
    finally:
        conn.close()


def fijar_atributos_en_despacho(usuario_id: int, tenant_id: int, **atributos) -> None:
    """Cambia atributos de la persona en ese despacho (en el principal, en `usuarios`; en los demás, en su pertenencia). Solo los cuatro conocidos."""
    desconocidos = set(atributos) - set(_ATRIBUTOS_POR_DESPACHO)
    if desconocidos:
        raise ValueError(f"Atributo desconocido: {', '.join(sorted(desconocidos))}")
    if not atributos:
        return
    conn = _db.get_connection(plataforma=True)
    try:
        u = conn.execute("SELECT tenant_id FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if u is None:
            raise ValueError("La persona no existe.")
        tabla, clave = ("usuarios", ("id = ?", (usuario_id,))) if u["tenant_id"] == tenant_id else ("usuarios_tenants", ("usuario_id = ? AND tenant_id = ?", (usuario_id, tenant_id)))
        if tabla == "usuarios_tenants" and conn.execute("SELECT 1 FROM usuarios_tenants WHERE usuario_id = ? AND tenant_id = ?", (usuario_id, tenant_id)).fetchone() is None:
            raise ValueError("La persona no pertenece a ese despacho.")
        conn.execute(f"UPDATE {tabla} SET " + ", ".join(f"{k} = ?" for k in atributos) + f" WHERE {clave[0]}", (*atributos.values(), *clave[1]))
        conn.commit()
    finally:
        conn.close()


def es_miembro_de_tenant(usuario_id: int, tenant_id: int) -> bool:
    conn = _db.get_connection()
    try:
        return conn.execute("SELECT 1 FROM usuarios_tenants WHERE usuario_id = ? AND tenant_id = ?", (usuario_id, tenant_id)).fetchone() is not None
    finally:
        conn.close()


def anadir_usuario_a_tenant(usuario_id: int, tenant_id: int) -> None:
    """La persona pasa a pertenecer también a ese despacho (sin dejar los suyos). Si no tenía ninguno, este es el principal."""
    conn = _db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM usuarios WHERE id = ?", (usuario_id,)).fetchone() is None:
            raise ValueError("La persona no existe.")
        if conn.execute("SELECT 1 FROM tenants WHERE id = ?", (tenant_id,)).fetchone() is None:
            raise ValueError("El despacho no existe.")
        conn.execute("INSERT INTO usuarios_tenants (usuario_id, tenant_id, creado_en) VALUES (?, ?, ?) ON CONFLICT DO NOTHING", (usuario_id, tenant_id, _db.now_iso()))
        conn.execute("UPDATE usuarios SET tenant_id = ? WHERE id = ? AND tenant_id IS NULL", (tenant_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def quitar_usuario_de_tenant(usuario_id: int, tenant_id: int) -> None:
    """La persona deja ese despacho. Si era el principal, pasa a serlo el siguiente que tenga (o ninguno)."""
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM usuarios_tenants WHERE usuario_id = ? AND tenant_id = ?", (usuario_id, tenant_id))
        conn.execute("UPDATE usuarios SET tenant_id = (SELECT MIN(m.tenant_id) FROM usuarios_tenants m WHERE m.usuario_id = usuarios.id) WHERE id = ? AND tenant_id = ?", (usuario_id, tenant_id))
        conn.commit()
    finally:
        conn.close()


def fijar_tenant_principal(usuario_id: int, tenant_id: int) -> None:
    """El despacho principal de la persona, que tiene que ser uno de los suyos."""
    conn = _db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM usuarios_tenants WHERE usuario_id = ? AND tenant_id = ?", (usuario_id, tenant_id)).fetchone() is None:
            raise ValueError("La persona no pertenece a ese despacho.")
        conn.execute("UPDATE usuarios SET tenant_id = ? WHERE id = ?", (tenant_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def guardar_datos_tenant(tenant_id: int, cif: str | None, direccion_fiscal: str | None) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET cif = ?, direccion_fiscal = ? WHERE id = ?",
            (cif or None, direccion_fiscal or None, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def zona_horaria_valida(nombre: str | None) -> bool:
    from zoneinfo import ZoneInfo

    try:
        ZoneInfo(nombre or "")
        return bool(nombre)
    except Exception:
        return False


def zona_horaria_tenant(tenant_id: int | None) -> str:
    """Huso horario IANA del tenant; por defecto la hora oficial de España peninsular."""
    if tenant_id:
        tenant = _db.obtener_tenant(tenant_id)
        if tenant and tenant["zona_horaria"] and _db.zona_horaria_valida(tenant["zona_horaria"]):
            return tenant["zona_horaria"]
    return _db.ZONA_HORARIA_DEFECTO


def guardar_zona_horaria_tenant(tenant_id: int, zona: str) -> None:
    if not _db.zona_horaria_valida(zona):
        raise ValueError("Huso horario no válido")
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE tenants SET zona_horaria = ? WHERE id = ?", (zona, tenant_id))
        conn.commit()
    finally:
        conn.close()


def registrar_acceso(usuario_id: int, cada_minutos: int = 10) -> None:
    """Anota `usuarios.ultimo_acceso` (solo para mostrarlo en el backoffice).
    Como mucho una escritura cada `cada_minutos` por usuario, para no cargar
    SQLite con una escritura por petición; un fallo nunca rompe la petición."""
    # Memoria del proceso: sin esto cada petición ejecutaba el UPDATE (aunque no cambiara
    # ninguna fila) y con él una transacción de escritura por página vista.
    marca = time.monotonic()
    if marca - _db._ULTIMO_ACCESO_ANOTADO.get(usuario_id, -1e9) < cada_minutos * 60:
        return
    _db._ULTIMO_ACCESO_ANOTADO[usuario_id] = marca
    ahora = _db.datetime.now()
    limite = (ahora - _db.timedelta(minutes=cada_minutos)).isoformat(timespec="seconds")
    try:
        conn = _db.get_connection()
        try:
            conn.execute(
                "UPDATE usuarios SET ultimo_acceso = ? WHERE id = ? AND (ultimo_acceso IS NULL OR ultimo_acceso < ?)",
                (ahora.isoformat(timespec="seconds"), usuario_id, limite),
            )
            conn.commit()
        finally:
            conn.close()
    except ErrorBD:
        pass


def tenant_de_usuario(usuario_id: int) -> sqlite3.Row | None:
    """El tenant del usuario, o None si no tiene ninguno asignado todavía."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT tenants.* FROM tenants "
            "JOIN usuarios ON usuarios.tenant_id = tenants.id "
            "WHERE usuarios.id = ?",
            (usuario_id,),
        ).fetchone()
    finally:
        conn.close()


def contexto_de_acceso(usuario_id: int) -> dict | None:
    """Lo que `token_required` necesita saber de quien llama, en UNA consulta: su despacho principal (`tenant_id`, None si no tiene), si es administrador global y sus dos permisos de fichaje.
    Antes eran cuatro lecturas (`tenant_de_usuario`, `es_admin`, `es_gestor_fichajes`, `es_supervisor_tenant`): con PostgreSQL cada una es un viaje (≈ 1 ms) en cada petición de la API.
    None si la persona no existe."""
    conn = _db.get_connection()
    try:
        f = conn.execute(
            "SELECT u.rol, u.gestor_fichajes, u.supervisor_tenant, t.id AS tenant_id FROM usuarios u LEFT JOIN tenants t ON t.id = u.tenant_id WHERE u.id = ?", (usuario_id,)).fetchone()
    finally:
        conn.close()
    if f is None:
        return None
    return {"tenant_id": f["tenant_id"], "es_admin": f["rol"] == "admin", "gestor_fichajes": bool(f["gestor_fichajes"]), "supervisor_tenant": bool(f["supervisor_tenant"])}


def usuarios_de_tenant(tenant_id: int) -> list[int]:
    """IDs de los usuarios asignados a un tenant -- patrón reutilizable para
    cualquier consulta futura que necesite agregar entre varios usuarios de
    un mismo tenant (p.ej. reasignar un vencimiento fiscal a otro miembro
    del equipo), en vez de que cada función nueva reinvente el JOIN a mano.
    Deliberadamente no se añadió `tenant_id` a tareas/notas/categorias (se
    quedaría obsoleto si un usuario cambia de tenant) -- este helper es la
    forma correcta de agregar por tenant sin ese problema."""
    conn = _db.get_connection()
    try:
        filas = conn.execute("SELECT id FROM usuarios WHERE tenant_id = ?", (tenant_id,)).fetchall()
        return [f["id"] for f in filas]
    finally:
        conn.close()


def usuario_local_id() -> int:
    """Para procesos locales de confianza (cli.py, mcp_server.py) que no
    pasan por login web: resuelve (o crea la primera vez) el usuario local
    fijo, y lo usan siempre como su `usuario_id`."""
    conn = _db.get_connection()
    try:
        uid = _db._resolver_usuario_local(conn)
        conn.commit()
        return uid
    finally:
        conn.close()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def crear_token_api(
    usuario_id: int, nombre_dispositivo: str | None = None, permisos: str = "completo",
    areas=None, caduca_en: str | None = None, origenes_cors=None, ips_permitidas=None,
) -> str:
    """`permisos`: "completo" (como siempre) o "solo_lectura" (solo GET: lo aplica auth.token_required).
    `areas`: lista de áreas de app/api_areas.py a las que se limita el token (vacío = todas).
    `caduca_en`: fecha/hora ISO a partir de la cual deja de valer (vacío = no caduca, solo por inactividad).
    `origenes_cors`: orígenes web que pueden llamar a la API con este token desde un navegador (vacío = ninguno).
    `ips_permitidas`: IP o redes CIDR desde las que se puede usar (vacío = cualquiera); un token con IPs no sirve por MCP."""
    from . import api_areas, token_restricciones

    if permisos not in _db.PERMISOS_TOKEN_API:
        raise ValueError("Permisos de token no válidos.")
    areas = api_areas.validar_areas(areas)
    origenes_cors = token_restricciones.validar_origenes(origenes_cors)
    ips_permitidas = token_restricciones.validar_ips(ips_permitidas)
    if caduca_en:
        try:
            caduca_en = _db.datetime.fromisoformat(str(caduca_en)).isoformat(timespec="seconds")
        except ValueError:
            raise ValueError("La fecha de caducidad no es válida.")
        if caduca_en <= _db.now_iso():
            raise ValueError("La fecha de caducidad ya ha pasado.")
    else:
        caduca_en = None
    token = secrets.token_urlsafe(32)
    conn = _db.get_connection()
    try:
        conn.execute(
            "INSERT INTO tokens_api (usuario_id, token_hash, nombre_dispositivo, creado_en, permisos, areas, caduca_en, origenes_cors, ips_permitidas) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (usuario_id, _db._hash_token(token), nombre_dispositivo, _db.now_iso(), permisos, json.dumps(areas) if areas else None, caduca_en,
             json.dumps(origenes_cors) if origenes_cors else None, json.dumps(ips_permitidas) if ips_permitidas else None),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def usuario_id_por_token(token: str) -> int | None:
    autenticado = _db.autenticar_token(token)
    return autenticado[0] if autenticado else None


def autenticar_token(token: str) -> tuple[int, str] | None:
    """(usuario_id, permisos), o None si el token no existe, o si lleva
    TOKEN_API_DIAS_INACTIVIDAD días sin usarse (se borra en el momento, no
    hace falta una tarea periódica aparte: con que se compruebe en cada uso
    es suficiente para un catálogo de tokens que no es previsible que
    crezca mucho)."""
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            "SELECT id, usuario_id, creado_en, ultimo_uso_en, permisos FROM tokens_api WHERE token_hash = ?",
            (_db._hash_token(token),),
        ).fetchone()
        if fila is None:
            return None
        ultima_actividad = fila["ultimo_uso_en"] or fila["creado_en"]
        limite = (_db.datetime.now() - _db.timedelta(days=_db.TOKEN_API_DIAS_INACTIVIDAD)).isoformat(timespec="seconds")
        if ultima_actividad < limite:
            conn.execute("DELETE FROM tokens_api WHERE token_hash = ?", (_db._hash_token(token),))
            conn.commit()
            return None
        ahora = _db.now_iso()
        if uso_diferido.tocar_token(fila["id"], fila["ultimo_uso_en"], None, ahora):          # con el diferido activo solo se anota en memoria (ver app/uso_diferido.py)
            conn.execute("UPDATE tokens_api SET ultimo_uso_en = ? WHERE token_hash = ?", (ahora, _db._hash_token(token)))
            conn.commit()
        return fila["usuario_id"], fila["permisos"]
    finally:
        conn.close()


def autenticar_token_completo(token: str, ip: str | None = None) -> dict | None:
    """Como `autenticar_token`, pero con todo lo que hace falta para aplicar las restricciones del token:
    {'usuario_id', 'permisos', 'areas' (lista), 'token_id'}; {'caducado': True} si pasó su fecha de caducidad; o None."""
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            "SELECT id, usuario_id, creado_en, ultimo_uso_en, permisos, areas, caduca_en, origenes_cors, ips_permitidas FROM tokens_api WHERE token_hash = ?",
            (_db._hash_token(token),),
        ).fetchone()
        if fila is None:
            return None
        ahora = _db.now_iso()
        if fila["caduca_en"] and fila["caduca_en"] <= ahora:
            return {"caducado": True}
        ultima_actividad = fila["ultimo_uso_en"] or fila["creado_en"]
        if ultima_actividad < (_db.datetime.now() - _db.timedelta(days=_db.TOKEN_API_DIAS_INACTIVIDAD)).isoformat(timespec="seconds"):
            conn.execute("DELETE FROM tokens_api WHERE id = ?", (fila["id"],))
            conn.commit()
            return None
        ips = json.loads(fila["ips_permitidas"]) if fila["ips_permitidas"] else []
        from . import token_restricciones
        if not token_restricciones.ip_permitida(ip, ips):
            return {"ip_no_permitida": True}      # no cuenta como uso ni actualiza la última IP: no es una llamada legítima
        if uso_diferido.tocar_token(fila["id"], fila["ultimo_uso_en"], ip, ahora):            # tabla de referencia: fuera de la ruta caliente (app/uso_diferido.py)
            conn.execute("UPDATE tokens_api SET ultimo_uso_en = ?, ultima_ip = COALESCE(?, ultima_ip) WHERE id = ?", (ahora, ip, fila["id"]))
            conn.commit()
        return {"usuario_id": fila["usuario_id"], "permisos": fila["permisos"], "areas": json.loads(fila["areas"]) if fila["areas"] else [], "token_id": fila["id"],
                "origenes_cors": json.loads(fila["origenes_cors"]) if fila["origenes_cors"] else []}
    finally:
        conn.close()


def origen_cors_conocido(origen: str) -> bool:
    """¿Algún token vivo admite este origen? Solo sirve para contestar el preflight (que no lleva token); la decisión
    real la toma cada petición con SU token. Con caché de 30 s."""
    import time as _t

    guardado = _db._CACHE_ORIGENES.get(origen)
    if guardado and _t.monotonic() - guardado[0] < 30:
        return guardado[1]
    conn = _db.get_connection()
    try:
        filas = conn.execute("SELECT origenes_cors FROM tokens_api WHERE origenes_cors IS NOT NULL AND (caduca_en IS NULL OR caduca_en > ?)", (_db.now_iso(),)).fetchall()
    finally:
        conn.close()
    conocido = any(origen in json.loads(f["origenes_cors"]) for f in filas)
    _db._CACHE_ORIGENES[origen] = (_t.monotonic(), conocido)
    if len(_db._CACHE_ORIGENES) > 200:
        _db._CACHE_ORIGENES.clear()
    return conocido


def registrar_uso_token(token_id: int, status: int) -> None:
    """Suma una llamada (y un error si status >= 400) al contador del día de ese token. En PostgreSQL se acumula en memoria y se vuelca cada 30 s (app/uso_diferido.py):
    escribir aquí en cada petición, en una tabla de referencia de Citus, provocaba interbloqueos distribuidos con peticiones simultáneas."""
    uso_diferido.sumar_uso_token(token_id, status)


def uso_de_token(token_id: int, dias: int = 30) -> list[dict]:
    uso_diferido.volcar()
    desde = (_db.date.today() - _db.timedelta(days=dias - 1)).isoformat()
    conn = _db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            "SELECT dia, llamadas, errores FROM tokens_api_uso WHERE token_id = ? AND dia >= ? ORDER BY dia", (token_id, desde))]
    finally:
        conn.close()


def listar_todos_los_tokens_api(tenant_id: int | None = None, dias: int = 30) -> list[dict]:
    """Todos los tokens (opcionalmente de un despacho) con su uso reciente, para el backoffice. Nunca el token."""
    uso_diferido.volcar()
    desde = (_db.date.today() - _db.timedelta(days=dias - 1)).isoformat()
    filtro, params = ("WHERE u.tenant_id = ?", [tenant_id]) if tenant_id is not None else ("", [])
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            f"""SELECT k.id, k.usuario_id, u.email, t.nombre AS tenant, k.nombre_dispositivo, k.permisos, k.areas, k.caduca_en,
                       k.creado_en, k.ultimo_uso_en, k.ultima_ip,
                       COALESCE((SELECT SUM(llamadas) FROM tokens_api_uso x WHERE x.token_id = k.id AND x.dia >= ?), 0) AS llamadas,
                       COALESCE((SELECT SUM(errores) FROM tokens_api_uso x WHERE x.token_id = k.id AND x.dia >= ?), 0) AS errores
                FROM tokens_api k JOIN usuarios u ON u.id = k.usuario_id LEFT JOIN tenants t ON t.id = u.tenant_id
                {filtro} ORDER BY COALESCE(k.ultimo_uso_en, k.creado_en) DESC""",
            [desde, desde, *params],
        ).fetchall()
    finally:
        conn.close()
    return [{**dict(f), "areas": json.loads(f["areas"]) if f["areas"] else []} for f in filas]


def revocar_token_api_cualquiera(token_id: int) -> bool:
    """Revoca por id sin comprobar dueño (solo para el backoffice)."""
    conn = _db.get_connection()
    try:
        cur = conn.execute("DELETE FROM tokens_api WHERE id = ?", (token_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def id_de_token(token: str) -> int | None:
    conn = _db.get_connection()
    try:
        f = conn.execute("SELECT id FROM tokens_api WHERE token_hash = ?", (_db._hash_token(token),)).fetchone()
        return f["id"] if f else None
    finally:
        conn.close()


def revocar_token_api(token: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM tokens_api WHERE token_hash = ?", (_db._hash_token(token),))
        conn.commit()
    finally:
        conn.close()


def listar_tokens_api(usuario_id: int):
    """Dispositivos móviles con sesión activa de este usuario (para la
    pantalla "Mis dispositivos" y, con verificación de tenant en la propia
    ruta, para que un admin revoque los de un compañero de tenant) — nunca
    expone el token ni su hash, solo lo necesario para reconocerlo y
    decidir si revocarlo."""
    uso_diferido.volcar()
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT id, nombre_dispositivo, creado_en, ultimo_uso_en, permisos, areas, caduca_en, ultima_ip, origenes_cors, ips_permitidas, "
            "COALESCE((SELECT SUM(llamadas) FROM tokens_api_uso x WHERE x.token_id = tokens_api.id AND x.dia >= ?), 0) AS llamadas_30d "
            "FROM tokens_api WHERE usuario_id = ? ORDER BY COALESCE(ultimo_uso_en, creado_en) DESC",
            ((_db.date.today() - _db.timedelta(days=29)).isoformat(), usuario_id),
        ).fetchall()
    finally:
        conn.close()


def revocar_token_api_por_id(usuario_id: int, token_id: int) -> bool:
    """Revoca por id en vez de por token (la web nunca tiene el token en
    claro, solo el móvil lo guarda). Exige usuario_id para que un usuario
    no pueda revocar el token de otro solo adivinando su id — quien llame
    a esto con el id de un compañero de tenant debe haber verificado antes
    que puede administrar sus dispositivos (ver backoffice)."""
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM tokens_api WHERE id = ? AND usuario_id = ?", (token_id, usuario_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def crear_lead_contacto(
    nombre: str, email: str, empresa: str | None = None,
    telefono: str | None = None, mensaje: str | None = None,
) -> int:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO leads_contacto (nombre, empresa, email, telefono, mensaje, creado_en) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (nombre, empresa, email, telefono, mensaje, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_leads_contacto():
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM leads_contacto ORDER BY atendido ASC, creado_en DESC"
        ).fetchall()
    finally:
        conn.close()


def marcar_lead_atendido(lead_id: int, atendido: bool) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE leads_contacto SET atendido = ? WHERE id = ?", (1 if atendido else 0, lead_id))
        conn.commit()
    finally:
        conn.close()


# --- Dispositivos push (ver app/push.py) --------------------------------

def registrar_dispositivo_push(usuario_id: int, fcm_token: str, plataforma: str) -> None:
    """Alta o refresco de un token FCM. REPLACE por fcm_token (UNIQUE): si
    el mismo dispositivo ya estaba registrado a otro usuario_id (reinstalo
    la app con otra cuenta), se reasigna al usuario actual en vez de dejar
    dos filas o rechazar el alta."""
    conn = _db.get_connection()
    try:
        ahora = _db.now_iso()
        conn.execute(
            "INSERT INTO dispositivos_push (usuario_id, fcm_token, plataforma, creado_en, actualizado_en) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(fcm_token) DO UPDATE SET usuario_id = excluded.usuario_id, "
            "plataforma = excluded.plataforma, actualizado_en = excluded.actualizado_en",
            (usuario_id, fcm_token, plataforma, ahora, ahora),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_dispositivo_push(usuario_id: int, fcm_token: str) -> None:
    """Se llama en logout (ver /api/v1/dispositivos-push DELETE) para dejar
    de mandar push a un dispositivo del que el usuario ya ha cerrado
    sesión -- exige usuario_id igual que revocar_token_api_por_id, mismo
    motivo (que no se pueda borrar el token de otro adivinando el valor)."""
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM dispositivos_push WHERE fcm_token = ? AND usuario_id = ?", (fcm_token, usuario_id))
        conn.commit()
    finally:
        conn.close()


def tokens_push_de_usuario(usuario_id: int) -> list[str]:
    conn = _db.get_connection()
    try:
        filas = conn.execute("SELECT fcm_token FROM dispositivos_push WHERE usuario_id = ?", (usuario_id,)).fetchall()
        return [f["fcm_token"] for f in filas]
    finally:
        conn.close()


def eliminar_tokens_push(tokens: list[str]) -> None:
    """Limpieza cuando app/push.py detecta que FCM ha rechazado un token
    (desinstalado, expirado) -- se borra en vez de reintentar para
    siempre."""
    if not tokens:
        return
    conn = _db.get_connection()
    try:
        marcadores = ",".join("?" for _ in tokens)
        conn.execute(f"DELETE FROM dispositivos_push WHERE fcm_token IN ({marcadores})", tokens)
        conn.commit()
    finally:
        conn.close()


# --- Centro de notificaciones (app/notificaciones.py) -----------------------

def crear_notificacion(usuario_id: int, tipo: str, titulo: str, cuerpo: str | None, url: str | None) -> int:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO notificaciones (usuario_id, tipo, titulo, cuerpo, url, creado_en) VALUES (?, ?, ?, ?, ?, ?)",
            (usuario_id, tipo, titulo, cuerpo, url, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_notificaciones(usuario_id: int, limite: int = 10) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM notificaciones WHERE usuario_id = ? ORDER BY creado_en DESC LIMIT ?",
            (usuario_id, limite),
        ).fetchall()
    finally:
        conn.close()


def contar_notificaciones_no_leidas(usuario_id: int) -> int:
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            "SELECT COUNT(*) AS n FROM notificaciones WHERE usuario_id = ? AND leido_en IS NULL", (usuario_id,),
        ).fetchone()
        return fila["n"]
    finally:
        conn.close()


def marcar_notificaciones_leidas(usuario_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE notificaciones SET leido_en = ? WHERE usuario_id = ? AND leido_en IS NULL",
            (_db.now_iso(), usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def marcar_notificacion_leida(usuario_id: int, notificacion_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE notificaciones SET leido_en = ? WHERE id = ? AND usuario_id = ? AND leido_en IS NULL",
            (_db.now_iso(), notificacion_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_notificacion(usuario_id: int, notificacion_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "DELETE FROM notificaciones WHERE id = ? AND usuario_id = ?",
            (notificacion_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_todas_notificaciones(usuario_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM notificaciones WHERE usuario_id = ?", (usuario_id,))
        conn.commit()
    finally:
        conn.close()


def _crear_triggers_cambios(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS api_cambios (
               id INTEGER PRIMARY KEY AUTOINCREMENT, entidad TEXT NOT NULL, entidad_id INTEGER NOT NULL,
               accion TEXT NOT NULL, usuario_id INTEGER NOT NULL, usuario2_id INTEGER,
               creado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime')))"""
    )
    conn.execute("CREATE TABLE IF NOT EXISTS api_cambios_purgado (id INTEGER PRIMARY KEY CHECK (id = 1), max_id INTEGER NOT NULL)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_api_cambios_u1 ON api_cambios(usuario_id, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_api_cambios_u2 ON api_cambios(usuario2_id, id)")
    for tabla, entidad in _db._ENTIDADES_CAMBIOS:
        asignable = tabla == "tareas_outlook"
        u2_new = "NEW.asignada_a" if asignable else "NULL"
        u2_old = "OLD.asignada_a" if asignable else "NULL"
        conn.execute(f"DROP TRIGGER IF EXISTS trg_cambios_{tabla}_ai")
        conn.execute(f"DROP TRIGGER IF EXISTS trg_cambios_{tabla}_au")
        conn.execute(f"DROP TRIGGER IF EXISTS trg_cambios_{tabla}_ad")
        conn.execute(
            f"""CREATE TRIGGER trg_cambios_{tabla}_ai AFTER INSERT ON {tabla} BEGIN
                    INSERT INTO api_cambios (entidad, entidad_id, accion, usuario_id, usuario2_id)
                    VALUES ('{entidad}', NEW.id, CASE WHEN NEW.papelera_en IS NOT NULL THEN 'delete' ELSE 'upsert' END, NEW.usuario_id, {u2_new});
                END"""
        )
        extra = ""
        if asignable:
            # quien dejó de tener la tarea asignada ya no la ve: se le avisa como borrado
            extra = """INSERT INTO api_cambios (entidad, entidad_id, accion, usuario_id)
                       SELECT 'tareas_outlook', NEW.id, 'delete', OLD.asignada_a WHERE OLD.asignada_a IS NOT NULL AND OLD.asignada_a IS NOT NEW.asignada_a;"""
        conn.execute(
            f"""CREATE TRIGGER trg_cambios_{tabla}_au AFTER UPDATE ON {tabla} BEGIN
                    INSERT INTO api_cambios (entidad, entidad_id, accion, usuario_id, usuario2_id)
                    VALUES ('{entidad}', NEW.id, CASE WHEN NEW.papelera_en IS NOT NULL THEN 'delete' ELSE 'upsert' END, NEW.usuario_id, {u2_new});
                    {extra}
                END"""
        )
        conn.execute(
            f"""CREATE TRIGGER trg_cambios_{tabla}_ad AFTER DELETE ON {tabla} BEGIN
                    INSERT INTO api_cambios (entidad, entidad_id, accion, usuario_id, usuario2_id)
                    VALUES ('{entidad}', OLD.id, 'delete', OLD.usuario_id, {u2_old});
                END"""
        )
    _db._purgar_cambios(conn)


def _purgar_cambios(conn: sqlite3.Connection) -> None:
    limite = (_db.datetime.now() - _db.timedelta(days=_db.CAMBIOS_RETENCION_DIAS)).strftime("%Y-%m-%d %H:%M:%S")
    maximo = conn.execute("SELECT MAX(id) FROM api_cambios WHERE creado_en < ?", (limite,)).fetchone()[0]
    if maximo:
        conn.execute("DELETE FROM api_cambios WHERE id <= ?", (maximo,))
        conn.execute("INSERT INTO api_cambios_purgado (id, max_id) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET max_id = CASE WHEN api_cambios_purgado.max_id > excluded.max_id THEN api_cambios_purgado.max_id ELSE excluded.max_id END", (maximo,))


def _ventana_sync_seg(conn) -> int:
    """Segundos que un cambio espera antes de entregarse con PostgreSQL (0 = sin espera; siempre 0 con SQLite, que tiene un único escritor).

    `api_cambios.id` se asigna al insertar, pero el orden en que las transacciones CONFIRMAN no es el de sus ids: si A (id 100) confirma después que B (id 101) y un cliente ya ha leído
    hasta 101, A no se le entrega nunca (reproducido, docs/plan-ux-ui-app-y-postgresql.md P-01). Solución provisional: no se entrega nada a partir del primer cambio «joven» (creado hace
    menos de esta ventana), de modo que las transacciones lentas tienen ese margen para confirmar. Límite honesto: una transacción que dure más que la ventana aún puede perderse; el
    diseño definitivo (cursor por transacción confirmada, `xid8`) es PG-07 del plan."""
    if not _db._bd.es_postgres(conn):
        return 0
    try:
        return max(0, int(os.environ.get("GUILDA_SYNC_VENTANA_SEG", "5")))
    except ValueError:
        return 5


def _barrera_sync(conn, desde_id: int, ventana: int) -> int | None:
    """El id del primer cambio posterior a `desde_id` que todavía está dentro de la ventana (nada se entrega a partir de él), o None si no hay ninguno."""
    if ventana <= 0:
        return None
    f = conn.execute(
        "SELECT MIN(id) FROM api_cambios WHERE id > ? AND creado_en > to_char(localtimestamp - (? * interval '1 second'), 'YYYY-MM-DD HH24:MI:SS')", (desde_id, ventana)).fetchone()
    return f[0] if f and f[0] is not None else None


def cursor_cambios_actual() -> int:
    conn = _db.get_connection()
    try:
        ventana = _db._ventana_sync_seg(conn)
        barrera = _db._barrera_sync(conn, 0, ventana)
        if barrera is not None:                                 # el cursor «actual» no puede adelantarse al primer cambio aún joven
            maximo = conn.execute("SELECT COALESCE(MAX(id), 0) FROM api_cambios WHERE id < ?", (barrera,)).fetchone()[0]
            return maximo or _db._cursor_minimo_cero(conn)
        return conn.execute("SELECT COALESCE(MAX(id), 0) FROM api_cambios").fetchone()[0] or _db._cursor_minimo_cero(conn)
    finally:
        conn.close()


def _cursor_minimo_cero(conn: sqlite3.Connection) -> int:
    """Sin filas en la tabla (nunca hubo cambios o se purgaron todos): el cursor es el último purgado, o 0."""
    f = conn.execute("SELECT max_id FROM api_cambios_purgado WHERE id = 1").fetchone()
    return f["max_id"] if f else 0


def cambios_desde(usuario_id: int, cursor: int, limite: int = 500) -> dict:
    """Cambios visibles para `usuario_id` con id > cursor, sin repetir: de cada (entidad, id) solo el último estado.
    Devuelve {'cursor', 'hay_mas', 'reiniciar', 'cambios': [(entidad, id, accion)]}. `reiniciar` = el cursor es más
    antiguo que lo conservado: hay que volver a descargar todo."""
    conn = _db.get_connection()
    try:
        if random.random() < 0.01:
            _db._purgar_cambios(conn)
            conn.commit()
        f = conn.execute("SELECT max_id FROM api_cambios_purgado WHERE id = 1").fetchone()
        if f and cursor < f["max_id"]:
            return {"cursor": _db.cursor_cambios_actual(), "hay_mas": False, "reiniciar": True, "cambios": []}
        barrera = _db._barrera_sync(conn, cursor, _db._ventana_sync_seg(conn))
        filas = conn.execute(
            """SELECT id, entidad, entidad_id, accion FROM api_cambios
               WHERE id > ? AND (usuario_id = ? OR usuario2_id = ?) AND id < ? ORDER BY id LIMIT ?""",
            (cursor, usuario_id, usuario_id, barrera if barrera is not None else 9223372036854775807, limite + 1),
        ).fetchall()
    finally:
        conn.close()
    hay_mas = len(filas) > limite
    filas = filas[:limite]
    ultimo: dict[tuple[str, int], str] = {}
    for fila in filas:
        ultimo[(fila["entidad"], fila["entidad_id"])] = fila["accion"]
    nuevo_cursor = filas[-1]["id"] if filas else max(cursor, _db.cursor_cambios_actual() if not hay_mas else cursor)
    return {"cursor": nuevo_cursor, "hay_mas": hay_mas, "reiniciar": False, "cambios": [(e, i, a) for (e, i), a in ultimo.items()]}


def idempotencia_reservar(usuario_id: int, clave: str, huella: str) -> tuple:
    """('nuevo',) si es la primera vez (queda reservada); ('repetida', status, cuerpo) si ya se respondió;
    ('conflicto',) si la misma clave se usó con otra petición; ('en_curso',) si aún se está procesando."""
    conn = _db.get_connection()
    try:
        # Antes se borraban TODAS las caducadas en cada reserva (una escritura en una tabla de referencia por petición); ahora solo la fila de esta clave si ya caducó, y la limpieza general, una de cada cien.
        limite = (_db.datetime.now() - _db.timedelta(hours=_db.IDEMPOTENCIA_HORAS)).isoformat(timespec="seconds")
        try:
            conn.execute("INSERT INTO api_idempotencia (usuario_id, clave, huella, creado_en) VALUES (?, ?, ?, ?)", (usuario_id, clave, huella, _db.now_iso()))
            conn.commit()
            if random.random() < 0.01:
                conn.execute("DELETE FROM api_idempotencia WHERE creado_en < ?", (limite,))
                conn.commit()
            return ("nuevo",)
        except ErrorIntegridad:
            conn.rollback()
        f = conn.execute("SELECT huella, estado, status, cuerpo, creado_en FROM api_idempotencia WHERE usuario_id = ? AND clave = ?", (usuario_id, clave)).fetchone()
        if f is not None and f["creado_en"] < limite:               # la clave ya caducó: se puede reutilizar
            conn.execute("DELETE FROM api_idempotencia WHERE usuario_id = ? AND clave = ? AND creado_en < ?", (usuario_id, clave, limite))
            conn.execute("INSERT INTO api_idempotencia (usuario_id, clave, huella, creado_en) VALUES (?, ?, ?, ?)", (usuario_id, clave, huella, _db.now_iso()))
            conn.commit()
            return ("nuevo",)
        if f is None:
            return ("en_curso",)
        if f["huella"] != huella:
            return ("conflicto",)
        if f["estado"] != "listo":
            return ("en_curso",)
        return ("repetida", f["status"], f["cuerpo"])
    finally:
        conn.close()


def idempotencia_guardar(usuario_id: int, clave: str, status: int, cuerpo: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE api_idempotencia SET estado = 'listo', status = ?, cuerpo = ? WHERE usuario_id = ? AND clave = ?", (status, cuerpo, usuario_id, clave))
        conn.commit()
    finally:
        conn.close()


def idempotencia_liberar(usuario_id: int, clave: str) -> None:
    """La petición falló (5xx o excepción): se puede reintentar con la misma clave."""
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM api_idempotencia WHERE usuario_id = ? AND clave = ?", (usuario_id, clave))
        conn.commit()
    finally:
        conn.close()


def validar_referencia_externa(valor) -> str | None:
    """Texto limpio de 1 a 120 caracteres sin saltos de línea, o None si viene vacío. ValueError si no vale."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if not isinstance(valor, (str, int)) or isinstance(valor, bool):
        raise ValueError("referencia_externa debe ser un texto.")
    texto = str(valor).strip()
    if len(texto) > 120 or any(ord(c) < 32 for c in texto):
        raise ValueError("referencia_externa admite hasta 120 caracteres y sin saltos de línea.")
    return texto


def id_por_referencia_externa(tabla: str, dueno_id: int, referencia: str) -> int | None:
    columna = _db._DUENO_REFERENCIA[tabla]
    conn = _db.get_connection()
    try:
        f = conn.execute(f"SELECT id FROM {tabla} WHERE {columna} = ? AND referencia_externa = ? AND papelera_en IS NULL", (dueno_id, referencia)).fetchone()
        return f["id"] if f else None
    finally:
        conn.close()


def fijar_referencia_externa(tabla: str, dueno_id: int, fila_id: int, referencia: str | None) -> None:
    """Asigna (o quita con None) la referencia externa. ValueError('duplicada') si otra fila del mismo dueño ya la tiene."""
    columna = _db._DUENO_REFERENCIA[tabla]
    conn = _db.get_connection()
    try:
        try:
            conn.execute(f"UPDATE {tabla} SET referencia_externa = ? WHERE id = ? AND {columna} = ?", (referencia, fila_id, dueno_id))
            conn.commit()
        except ErrorIntegridad:
            conn.rollback()
            raise ValueError("duplicada")
    finally:
        conn.close()


def mcp_registrar_llamada(
    usuario_id: int | None, cliente: str, token_id: int | None, herramienta: str, lectura: bool, resultado: str,
    detalle: str | None = None, argumentos: dict | None = None, duracion_ms: int | None = None,
) -> None:
    """Una fila de auditoría y el contador diario. Nunca debe romper la llamada que audita (el que la llama lo captura)."""
    tenant = _db.tenant_de_usuario(usuario_id) if usuario_id else None
    conn = _db.get_connection()
    try:
        conn.execute(
            "INSERT INTO mcp_auditoria (creado_en, usuario_id, tenant_id, cliente, token_id, herramienta, lectura, resultado, detalle, argumentos, duracion_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_db.now_iso(), usuario_id, tenant["id"] if tenant else None, cliente[:80], token_id, herramienta, 1 if lectura else 0, resultado,
             (detalle or "")[:300] or None, json.dumps(argumentos, ensure_ascii=False) if argumentos else None, duracion_ms),
        )
        if random.random() < 0.01:
            limite = (_db.datetime.now() - _db.timedelta(days=_db.MCP_AUDITORIA_RETENCION_DIAS)).isoformat(timespec="seconds")
            conn.execute("DELETE FROM mcp_auditoria WHERE creado_en < ?", (limite,))
        conn.commit()
    finally:
        conn.close()
    if usuario_id:                                      # contador diario (tabla de referencia): en memoria y volcado cada 30 s; la purga de `mcp_uso` va con el volcado
        uso_diferido.sumar_uso_mcp(usuario_id, herramienta, resultado != "ok")


def mcp_resumen(dias: int = 30, tenant_id: int | None = None) -> dict:
    """Totales, uso por herramienta y por persona de los últimos `dias` días, y los últimos fallos."""
    uso_diferido.volcar()
    desde = (_db.date.today() - _db.timedelta(days=dias - 1)).isoformat()
    filtro, params = ("AND u.tenant_id = ?", [tenant_id]) if tenant_id is not None else ("", [])
    conn = _db.get_connection()
    try:
        base = f"FROM mcp_uso m JOIN usuarios u ON u.id = m.usuario_id WHERE m.dia >= ? {filtro}"
        totales = conn.execute(f"SELECT COALESCE(SUM(m.llamadas), 0) AS llamadas, COALESCE(SUM(m.errores), 0) AS errores, COUNT(DISTINCT m.usuario_id) AS usuarios {base}", [desde, *params]).fetchone()
        por_herramienta = [dict(f) for f in conn.execute(
            f"SELECT m.herramienta, SUM(m.llamadas) AS llamadas, SUM(m.errores) AS errores {base} GROUP BY m.herramienta ORDER BY llamadas DESC LIMIT 25", [desde, *params])]
        por_usuario = [dict(f) for f in conn.execute(
            f"SELECT u.id AS usuario_id, u.email, t.nombre AS tenant, SUM(m.llamadas) AS llamadas, SUM(m.errores) AS errores "
            f"FROM mcp_uso m JOIN usuarios u ON u.id = m.usuario_id LEFT JOIN tenants t ON t.id = u.tenant_id WHERE m.dia >= ? {filtro} "
            f"GROUP BY u.id, u.email, t.nombre ORDER BY llamadas DESC LIMIT 25", [desde, *params])]
        por_dia = [dict(f) for f in conn.execute(f"SELECT m.dia, SUM(m.llamadas) AS llamadas, SUM(m.errores) AS errores {base} GROUP BY m.dia ORDER BY m.dia", [desde, *params])]
    finally:
        conn.close()
    return {"desde": desde, "llamadas": totales["llamadas"], "errores": totales["errores"], "usuarios": totales["usuarios"],
            "por_herramienta": por_herramienta, "por_usuario": por_usuario, "por_dia": por_dia}


def mcp_auditoria_listar(
    limite: int = 100, usuario_id: int | None = None, tenant_id: int | None = None, herramienta: str | None = None,
    resultado: str | None = None, solo_escrituras: bool = False,
) -> list[dict]:
    cond, params = ["1 = 1"], []
    for columna, valor in (("a.usuario_id", usuario_id), ("a.tenant_id", tenant_id), ("a.herramienta", herramienta or None), ("a.resultado", resultado or None)):
        if valor is not None:
            cond.append(f"{columna} = ?"); params.append(valor)
    if solo_escrituras:
        cond.append("a.lectura = 0")
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            f"""SELECT a.*, u.email, t.nombre AS tenant FROM mcp_auditoria a LEFT JOIN usuarios u ON u.id = a.usuario_id LEFT JOIN tenants t ON t.id = a.tenant_id
                WHERE {' AND '.join(cond)} ORDER BY a.id DESC LIMIT ?""", [*params, max(1, min(limite, 1000))],
        ).fetchall()
    finally:
        conn.close()
    return [dict(f) for f in filas]


def registrar_auditoria(usuario_id: int | None, accion: str, detalle: str | None = None) -> None:
    """Nunca debe romper la acción que audita -- quien llama (rutas_backoffice.py)
    la envuelve en su propio try/except best-effort, mismo criterio que el
    resto de efectos secundarios "de segunda fila" del proyecto (eventos,
    notificaciones)."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "INSERT INTO auditoria_backoffice (usuario_id, accion, detalle, creado_en) VALUES (?, ?, ?, ?)",
            (usuario_id, accion, detalle, _db.now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def listar_auditoria_backoffice(limite: int = 200) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT a.*, u.email AS usuario_email
               FROM auditoria_backoffice a LEFT JOIN usuarios u ON u.id = a.usuario_id
               ORDER BY a.id DESC LIMIT ?""",
            (limite,),
        ).fetchall()
    finally:
        conn.close()


def exportar_datos_tenant(tenant_id: int) -> dict:
    tenant = _db.obtener_tenant(tenant_id)
    if tenant is None:
        raise ValueError(f"No existe el tenant #{tenant_id}.")
    usuarios_ids = _db.usuarios_de_tenant(tenant_id)
    conn = _db.get_connection()
    try:
        usuarios = []
        if usuarios_ids:
            marcadores_usuarios = ",".join("?" * len(usuarios_ids))
            usuarios = [
                dict(u) for u in conn.execute(
                    f"SELECT id, email, rol, creado_en FROM usuarios WHERE id IN ({marcadores_usuarios})",
                    usuarios_ids,
                ).fetchall()
            ]

        clientes_fiscales = [
            dict(c) for c in conn.execute(
                "SELECT * FROM clientes_fiscales WHERE tenant_id = ?", (tenant_id,)
            ).fetchall()
        ]

        vencimientos_fiscales = []
        for v in conn.execute("SELECT * FROM vencimientos_fiscales WHERE tenant_id = ?", (tenant_id,)).fetchall():
            v = dict(v)
            v["documentos"] = [
                {**dict(d), "url_descarga": f"/fiscal/vencimientos/{v['id']}/documentos/{d['id']}"}
                for d in conn.execute(
                    "SELECT id, nombre_archivo, tipo_mime, tamano_bytes, creado_en "
                    "FROM vencimientos_fiscales_documentos WHERE vencimiento_id = ?",
                    (v["id"],),
                ).fetchall()
            ]
            v["mensajes"] = [
                dict(m) for m in conn.execute(
                    "SELECT autor, usuario_id, texto, creado_en, leido_en "
                    "FROM vencimientos_fiscales_mensajes WHERE vencimiento_id = ?",
                    (v["id"],),
                ).fetchall()
            ]
            vencimientos_fiscales.append(v)

        tareas, notas, tiquets, correos = [], [], [], []
        if usuarios_ids:
            marcadores = ",".join("?" * len(usuarios_ids))
            tareas = [
                dict(t) for t in conn.execute(
                    f"SELECT id, usuario_id, nombre, tipo, estado, inicio_en, fin_en, duracion_segundos "
                    f"FROM tareas WHERE usuario_id IN ({marcadores}) AND papelera_en IS NULL",
                    usuarios_ids,
                ).fetchall()
            ]
            notas = [
                dict(n) for n in conn.execute(
                    f"SELECT id, usuario_id, texto, creada_en FROM notas "
                    f"WHERE usuario_id IN ({marcadores}) AND papelera_en IS NULL",
                    usuarios_ids,
                ).fetchall()
            ]
            tiquets = [
                dict(t) for t in conn.execute(
                    f"SELECT id, usuario_id, tipo, titulo, descripcion, estado, prioridad, "
                    f"usuario_asignado_id, creado_en FROM tiquets WHERE usuario_id IN ({marcadores})",
                    usuarios_ids,
                ).fetchall()
            ]
            from . import correo_cifrado
            correos = [
                dict(c) for c in correo_cifrado.completar(conn.execute(
                    f"""SELECT m.id, m.asunto, m.remitente, m.destinatarios, m.fecha, cu.usuario_id
                        FROM correo_mensajes m JOIN correo_cuentas cu ON cu.id = m.cuenta_id
                        WHERE cu.usuario_id IN ({marcadores})""",
                    usuarios_ids,
                ).fetchall())
            ]

        tareas_lista, comentarios_tareas, notas_internas_correo, asignaciones_correo = [], [], [], []
        fichajes = [
            dict(f) for f in conn.execute(
                "SELECT id, usuario_id, tipo, marca_tiempo, origen, nota, corrige_a, creado_por, creado_en "
                "FROM fichajes WHERE tenant_id = ? ORDER BY marca_tiempo", (tenant_id,),
            ).fetchall()
        ]
        if usuarios_ids:
            marcadores = ",".join("?" * len(usuarios_ids))
            tareas_lista = [
                dict(t) for t in conn.execute(
                    f"""SELECT id, usuario_id, asunto, cuerpo, estado, prioridad, fecha_vencimiento, fecha_completada,
                               asignada_a, cliente_fiscal_id, creada_en
                        FROM tareas_outlook WHERE usuario_id IN ({marcadores}) AND papelera_en IS NULL""",
                    usuarios_ids,
                ).fetchall()
            ]
            if tareas_lista:
                ids_tareas = [t["id"] for t in tareas_lista]
                comentarios_tareas = [
                    dict(c) for c in conn.execute(
                        f"SELECT tarea_id, usuario_id, texto, creado_en FROM tarea_comentarios "
                        f"WHERE tarea_id IN ({','.join('?' * len(ids_tareas))})", ids_tareas,
                    ).fetchall()
                ]
            notas_internas_correo = [
                dict(n) for n in conn.execute(
                    f"SELECT mensaje_id, usuario_id, texto, creado_en FROM correo_notas_internas WHERE usuario_id IN ({marcadores})",
                    usuarios_ids,
                ).fetchall()
            ]
            asignaciones_correo = [
                dict(a) for a in conn.execute(
                    f"SELECT mensaje_id, asignado_a, asignado_por, estado, actualizado_en FROM correo_equipo "
                    f"WHERE asignado_a IN ({marcadores}) OR asignado_por IN ({marcadores})",
                    usuarios_ids + usuarios_ids,
                ).fetchall()
            ]
        return {
            "tenant": {"id": tenant["id"], "nombre": tenant["nombre"], "creado_en": tenant["creado_en"]},
            "generado_en": _db.now_iso(),
            "usuarios": usuarios,
            "clientes_fiscales": clientes_fiscales,
            "vencimientos_fiscales": vencimientos_fiscales,
            "tareas": tareas,
            "tareas_lista": tareas_lista,
            "comentarios_tareas": comentarios_tareas,
            "notas": notas,
            "tiquets": tiquets,
            "correos": correos,
            "correo_equipo_asignaciones": asignaciones_correo,
            "correo_equipo_notas_internas": notas_internas_correo,
            "fichajes": fichajes,
        }
    finally:
        conn.close()


def crear_webhook(usuario_id: int, tenant_id: int | None, url: str, eventos: list[str], origen: str = "backoffice") -> dict:
    """`eventos` es una lista de nombres (ver app/eventos.py:EVENTOS) —
    se guarda como JSON, no una tabla aparte: no hace falta consultarlos
    por separado, siempre se leen todos juntos para un webhook dado.
    `origen`: `backoffice` (de confianza, puede apuntar a servicios internos) | `api` | `mcp` (URL pública obligatoria:
    ver eventos.validar_url_publica)."""
    secreto = secrets.token_urlsafe(32)
    conn = _db.get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO webhooks (tenant_id, usuario_id, url, eventos, secreto, creado_en, origen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, usuario_id, url, json.dumps(eventos), secreto, _db.now_iso(), origen),
        )
        conn.commit()
        w = dict(_db.obtener_webhook(cursor.lastrowid))
        w["tenant_id"] = w["tenant_id"] or None                      # el webhook de toda la plataforma: NULL en SQLite, 0 en PostgreSQL
        return w
    finally:
        conn.close()


def actualizar_webhook(webhook_id: int, url: str | None = None, eventos: list[str] | None = None, activo: bool | None = None) -> None:
    conn = _db.get_connection()
    try:
        if url is not None:
            conn.execute("UPDATE webhooks SET url = ? WHERE id = ?", (url, webhook_id))
        if eventos is not None:
            conn.execute("UPDATE webhooks SET eventos = ? WHERE id = ?", (json.dumps(eventos), webhook_id))
        if activo is not None:
            conn.execute("UPDATE webhooks SET activo = ? WHERE id = ?", (1 if activo else 0, webhook_id))
        conn.commit()
    finally:
        conn.close()


def rotar_secreto_webhook(webhook_id: int) -> str:
    """Genera un secreto nuevo (el anterior deja de valer al instante) y lo devuelve: solo se enseña esta vez."""
    secreto = secrets.token_urlsafe(32)
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE webhooks SET secreto = ? WHERE id = ?", (secreto, webhook_id))
        conn.commit()
        return secreto
    finally:
        conn.close()


def cola_webhook_obtener(cola_id: int) -> dict | None:
    conn = _db.get_connection()
    try:
        f = conn.execute("SELECT * FROM webhooks_cola WHERE id = ?", (cola_id,)).fetchone()
        return dict(f) if f else None
    finally:
        conn.close()


def obtener_webhook(webhook_id: int) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute("SELECT * FROM webhooks WHERE id = ?", (webhook_id,)).fetchone()
    finally:
        conn.close()


def listar_webhooks(tenant_id: int | None) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        if tenant_id is None:
            return conn.execute(
                "SELECT * FROM webhooks WHERE COALESCE(tenant_id, 0) = 0 ORDER BY creado_en DESC"
            ).fetchall()
        return conn.execute(
            "SELECT * FROM webhooks WHERE tenant_id = ? ORDER BY creado_en DESC", (tenant_id,)
        ).fetchall()
    finally:
        conn.close()


def listar_todos_los_webhooks() -> dict[int | None, list[sqlite3.Row]]:
    """Igual que llamar a listar_webhooks() para None + cada tenant, pero en
    una sola consulta -- usado en el backoffice, que antes hacía una
    consulta por tenant listado."""
    conn = _db.get_connection()
    try:
        filas = conn.execute("SELECT * FROM webhooks ORDER BY COALESCE(tenant_id, 0) <> 0, tenant_id, creado_en DESC").fetchall()
        resultado: dict[int | None, list[sqlite3.Row]] = {}
        for w in filas:
            resultado.setdefault(w["tenant_id"] or None, []).append(w)
        return resultado
    finally:
        conn.close()


def borrar_webhook(webhook_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM webhooks_entregas WHERE webhook_id = ?", (webhook_id,))
        conn.execute("DELETE FROM webhooks_cola WHERE webhook_id = ?", (webhook_id,))
        conn.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
        conn.commit()
    finally:
        conn.close()


def webhooks_para_evento(evento: str, tenant_id: int | None) -> list[sqlite3.Row]:
    """Webhooks activos de este tenant (o del ámbito local si `tenant_id`
    es None) suscritos a `evento` — el filtro por evento se hace en
    Python (sobre `eventos` como JSON), no en SQL: la tabla no está
    pensada para volúmenes altos de webhooks por tenant."""
    candidatos = _db.listar_webhooks(tenant_id)
    return [w for w in candidatos if w["activo"] and evento in json.loads(w["eventos"])]


# ---- Cola persistente de webhooks ------------------------------------------------------------------------------

def cola_webhook_encolar(webhook_id: int, evento: str, payload: dict) -> int:
    ahora = _db.now_iso()
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO webhooks_cola (webhook_id, evento, payload_json, estado, proximo_intento, creado_en) VALUES (?, ?, ?, 'pendiente', ?, ?)",
            (webhook_id, evento, json.dumps(payload, ensure_ascii=False, default=str), ahora, ahora),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def cola_webhook_reclamar(ahora: str, limite: int) -> list[dict]:
    """Marca como `entregando` (de forma atómica por fila: dos procesos no se pisan) lo que toca entregar y lo devuelve."""
    conn = _db.get_connection()
    try:
        candidatas = conn.execute(
            "SELECT * FROM webhooks_cola WHERE estado = 'pendiente' AND proximo_intento <= ? ORDER BY proximo_intento, id LIMIT ?", (ahora, limite)
        ).fetchall()
        reclamadas = []
        for f in candidatas:
            cur = conn.execute("UPDATE webhooks_cola SET estado = 'entregando', reclamado_en = ? WHERE id = ? AND estado = 'pendiente'", (ahora, f["id"]))
            if cur.rowcount == 1:
                reclamadas.append(dict(f))
        conn.commit()
        return reclamadas
    finally:
        conn.close()


def cola_webhook_cerrar(cola_id: int, estado: str, error: str | None, intentos: int | None = None) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE webhooks_cola SET estado = ?, ultimo_error = ?, cerrado_en = ?, intentos = COALESCE(?, intentos) WHERE id = ?",
            (estado, error, _db.now_iso(), intentos, cola_id),
        )
        conn.commit()
    finally:
        conn.close()


def cola_webhook_reprogramar(cola_id: int, intentos: int, proximo_intento: str, error: str | None) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE webhooks_cola SET estado = 'pendiente', intentos = ?, proximo_intento = ?, ultimo_error = ?, reclamado_en = NULL WHERE id = ?",
            (intentos, proximo_intento, error, cola_id),
        )
        conn.commit()
    finally:
        conn.close()


def cola_webhook_recuperar_atascados(antes_de: str) -> int:
    """Lo que se quedó `entregando` (caída del proceso a mitad) vuelve a pendiente."""
    conn = _db.get_connection()
    try:
        cur = conn.execute("UPDATE webhooks_cola SET estado = 'pendiente', reclamado_en = NULL WHERE estado = 'entregando' AND reclamado_en < ?", (antes_de,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def cola_webhook_purgar(entregados_antes_de: str, fallidos_antes_de: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM webhooks_cola WHERE estado = 'entregado' AND cerrado_en < ?", (entregados_antes_de,))
        conn.execute("DELETE FROM webhooks_cola WHERE estado = 'fallido' AND cerrado_en < ?", (fallidos_antes_de,))
        conn.commit()
    finally:
        conn.close()


def cola_webhook_resumen() -> dict:
    """Recuento por estado (para el backoffice y el panel de salud)."""
    conn = _db.get_connection()
    try:
        filas = conn.execute("SELECT estado, COUNT(*) AS n FROM webhooks_cola GROUP BY estado").fetchall()
    finally:
        conn.close()
    return {f["estado"]: f["n"] for f in filas}


def cola_webhook_de(webhook_id: int, limite: int = 20) -> list[dict]:
    conn = _db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            "SELECT id, evento, estado, intentos, proximo_intento, ultimo_error, creado_en FROM webhooks_cola WHERE webhook_id = ? ORDER BY id DESC LIMIT ?",
            (webhook_id, limite))]
    finally:
        conn.close()


def cola_webhook_reintentar(cola_id: int) -> bool:
    """Devuelve un envío fallido a pendiente (intento inmediato, contador a cero)."""
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "UPDATE webhooks_cola SET estado = 'pendiente', intentos = 0, proximo_intento = ?, cerrado_en = NULL, reclamado_en = NULL WHERE id = ? AND estado = 'fallido'",
            (_db.now_iso(), cola_id),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def registrar_entrega_webhook(
    webhook_id: int, evento: str, estado_http: int | None, intento_num: int, error: str | None = None
) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "INSERT INTO webhooks_entregas (webhook_id, evento, estado_http, intento_num, entregado_en, error) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (webhook_id, evento, estado_http, intento_num, _db.now_iso(), error),
        )
        # Poda: solo las últimas _MAX_ENTREGAS_POR_WEBHOOK por webhook —
        # el log de entregas es para depurar, no un histórico permanente.
        conn.execute(
            "DELETE FROM webhooks_entregas WHERE webhook_id = ? AND id NOT IN ("
            "  SELECT id FROM webhooks_entregas WHERE webhook_id = ? "
            "  ORDER BY id DESC LIMIT ?"
            ")",
            (webhook_id, webhook_id, _db._MAX_ENTREGAS_POR_WEBHOOK),
        )
        conn.commit()
    finally:
        conn.close()


def entregas_de_webhook(webhook_id: int, limite: int = 20) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM webhooks_entregas WHERE webhook_id = ? ORDER BY id DESC LIMIT ?",
            (webhook_id, limite),
        ).fetchall()
    finally:
        conn.close()


def entregas_de_webhooks(webhook_ids: list[int], limite: int = 5) -> dict[int, list[sqlite3.Row]]:
    """Igual que entregas_de_webhook() pero para varios webhooks a la vez
    (una consulta con ventana en vez de una por webhook) -- usado en el
    backoffice, que antes hacía una llamada por webhook listado."""
    if not webhook_ids:
        return {}
    conn = _db.get_connection()
    try:
        marcas = ",".join("?" * len(webhook_ids))
        filas = conn.execute(
            f"""SELECT id, webhook_id, evento, estado_http, intento_num, entregado_en, error FROM (
                    SELECT *, ROW_NUMBER() OVER (PARTITION BY webhook_id ORDER BY id DESC) AS _orden
                    FROM webhooks_entregas WHERE webhook_id IN ({marcas})
                ) WHERE _orden <= ?""",
            [*webhook_ids, limite],
        ).fetchall()
        resultado: dict[int, list[sqlite3.Row]] = {wid: [] for wid in webhook_ids}
        for f in filas:
            resultado[f["webhook_id"]].append(f)
        return resultado
    finally:
        conn.close()


# --- Papelera ----------------------------------------------------------------

def papelera(usuario_id: int) -> list[dict]:
    """Proyectos, tareas/eventos y notas que están en la papelera, más recientes primero."""
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            """
            SELECT * FROM (
                SELECT 'menu' AS origen, c.id AS id, c.nombre AS texto, NULL AS tipo,
                       NULL AS categoria_nombre, NULL AS categoria_color, c.papelera_en AS papelera_en
                FROM categorias c
                WHERE c.usuario_id = ? AND c.papelera_en IS NOT NULL

                UNION ALL

                SELECT 'tarea' AS origen, t.id AS id, t.nombre AS texto, t.tipo AS tipo,
                       c.nombre AS categoria_nombre, c.color AS categoria_color, t.papelera_en AS papelera_en
                FROM tareas t JOIN categorias c ON c.id = t.categoria_id
                WHERE t.usuario_id = ? AND t.papelera_en IS NOT NULL

                UNION ALL

                SELECT 'nota' AS origen, n.id AS id, n.texto AS texto, NULL AS tipo,
                       c.nombre AS categoria_nombre, c.color AS categoria_color, n.papelera_en AS papelera_en
                FROM notas n LEFT JOIN categorias c ON c.id = n.categoria_id
                WHERE n.usuario_id = ? AND n.papelera_en IS NOT NULL

                UNION ALL

                SELECT 'tarea_outlook' AS origen, tk.id AS id, tk.asunto AS texto, NULL AS tipo,
                       COALESCE(ck.nombre, tk.categoria_outlook) AS categoria_nombre, ck.color AS categoria_color, tk.papelera_en AS papelera_en
                FROM tareas_outlook tk LEFT JOIN categorias ck ON ck.id = tk.categoria_id
                WHERE tk.usuario_id = ? AND tk.papelera_en IS NOT NULL
            )
            ORDER BY papelera_en DESC
            """,
            (usuario_id, usuario_id, usuario_id, usuario_id),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def vaciar_papelera_antigua(dias: int = 30, usuario_id: int | None = None) -> None:
    """Purga definitivamente (sin posibilidad de recuperar) lo que lleva en
    la papelera más de `dias` días. Sin `usuario_id`, purga de TODOS los
    usuarios (uso interno: se llama al arrancar la app, igual que la copia
    de seguridad); con `usuario_id`, solo la papelera de ese usuario (uso
    desde la ruta web "Vaciar papelera", que actúa en nombre de quien la
    pulsa, no de todo el tenant). clientes_fiscales/vencimientos_fiscales se
    purgan siempre por tenant_id (ver más abajo), sin importar `usuario_id`
    -- no tienen ese campo, son datos de la gestoría, no de un usuario."""
    conn = _db.get_connection()
    try:
        limite = (_db.datetime.now() - _db.timedelta(days=dias)).isoformat(timespec="seconds")
        filtro_usuario = " AND usuario_id = ?" if usuario_id is not None else ""
        params = (limite, usuario_id) if usuario_id is not None else (limite,)
        ids_categorias = [
            (r["id"], r["usuario_id"]) for r in conn.execute(
                f"SELECT id, usuario_id FROM categorias WHERE papelera_en IS NOT NULL AND papelera_en < ?{filtro_usuario}", params
            )
        ]
        ids_tareas = [
            (r["id"], r["usuario_id"]) for r in conn.execute(
                f"SELECT id, usuario_id FROM tareas WHERE papelera_en IS NOT NULL AND papelera_en < ?{filtro_usuario}", params
            )
        ]
        ids_notas = [
            (r["id"], r["usuario_id"]) for r in conn.execute(
                f"SELECT id, usuario_id FROM notas WHERE papelera_en IS NOT NULL AND papelera_en < ?{filtro_usuario}", params
            )
        ]
        ids_tareas_outlook = [
            (r["id"], r["usuario_id"]) for r in conn.execute(
                f"SELECT id, usuario_id FROM tareas_outlook WHERE papelera_en IS NOT NULL AND papelera_en < ?{filtro_usuario}", params
            )
        ]
        ids_clientes_fiscales = [
            (r["id"], r["tenant_id"]) for r in conn.execute(
                "SELECT id, tenant_id FROM clientes_fiscales WHERE papelera_en IS NOT NULL AND papelera_en < ?", (limite,)
            )
        ]
        ids_vencimientos_fiscales = [
            (r["id"], r["tenant_id"]) for r in conn.execute(
                "SELECT id, tenant_id FROM vencimientos_fiscales WHERE papelera_en IS NOT NULL AND papelera_en < ?", (limite,)
            )
        ]
    finally:
        conn.close()

    for nid, uid in ids_notas:
        _db.eliminar_nota_definitivamente(uid, nid)
    for tid, uid in ids_tareas:
        _db.eliminar_tarea_definitivamente(uid, tid)
    for cid, uid in ids_categorias:
        _db.eliminar_categoria_definitivamente(uid, cid)
    for tid, uid in ids_tareas_outlook:
        _db.eliminar_tarea_outlook_definitivamente(uid, tid)
    for vid, tid in ids_vencimientos_fiscales:
        _db.eliminar_vencimiento_fiscal_definitivamente(tid, vid)
    for cid, tid in ids_clientes_fiscales:
        _db.eliminar_cliente_fiscal_definitivamente(tid, cid)


def obtener_perfil_usuario(usuario_id: int) -> sqlite3.Row:
    conn = _db.get_connection()
    try:
        # Solo se escribe la primera vez: un INSERT OR IGNORE en cada visita abría una
        # transacción de escritura por página vista aunque la fila ya existiera.
        fila = conn.execute("SELECT * FROM usuario_perfil WHERE usuario_id = ?", (usuario_id,)).fetchone()
        if fila is None:
            conn.execute("INSERT INTO usuario_perfil (usuario_id) VALUES (?) ON CONFLICT DO NOTHING", (usuario_id,))
            conn.commit()
            fila = conn.execute("SELECT * FROM usuario_perfil WHERE usuario_id = ?", (usuario_id,)).fetchone()
        return fila
    finally:
        conn.close()


def guardar_perfil_usuario(
    usuario_id: int,
    nombre_mostrado: str | None = None,
    notificar_push_vencimientos: bool | None = None,
    notificar_push_tiquets: bool | None = None,
    notificar_resumen_semanal: bool | None = None,
    notificar_push_correo: bool | None = None,
    notificar_push_portal_mensajes: bool | None = None,
    avisos_cliente_por_correo: bool | None = None,
    cargo: str | None = None,
    telefono: str | None = None,
    silencio_desde: str | None = None,
    silencio_hasta: str | None = None,
    resumen_diario: bool | None = None,
    resumen_diario_hora: int | None = None,
    resumen_diario_email: bool | None = None,
) -> None:
    """Solo actualiza los campos que se pasan explícitos (no-None) -- así
    la ruta puede llamar con únicamente el nombre, o únicamente las
    notificaciones, sin pisar el resto con valores por defecto."""
    conn = _db.get_connection()
    try:
        conn.execute("INSERT INTO usuario_perfil (usuario_id) VALUES (?) ON CONFLICT DO NOTHING", (usuario_id,))
        asignaciones, valores = [], []
        if nombre_mostrado is not None:
            asignaciones.append("nombre_mostrado = ?")
            valores.append(nombre_mostrado.strip() or None)
        if notificar_push_vencimientos is not None:
            asignaciones.append("notificar_push_vencimientos = ?")
            valores.append(int(notificar_push_vencimientos))
        if notificar_push_tiquets is not None:
            asignaciones.append("notificar_push_tiquets = ?")
            valores.append(int(notificar_push_tiquets))
        if notificar_resumen_semanal is not None:
            asignaciones.append("notificar_resumen_semanal = ?")
            valores.append(int(notificar_resumen_semanal))
        for columna, valor in (("resumen_diario", resumen_diario), ("resumen_diario_email", resumen_diario_email)):
            if valor is not None:
                asignaciones.append(f"{columna} = ?")
                valores.append(int(valor))
        if resumen_diario_hora is not None:
            asignaciones.append("resumen_diario_hora = ?")
            valores.append(max(5, min(int(resumen_diario_hora), 20)))
        if notificar_push_correo is not None:
            asignaciones.append("notificar_push_correo = ?")
            valores.append(int(notificar_push_correo))
        if notificar_push_portal_mensajes is not None:
            asignaciones.append("notificar_push_portal_mensajes = ?")
            valores.append(int(notificar_push_portal_mensajes))
        if avisos_cliente_por_correo is not None:
            asignaciones.append("avisos_cliente_por_correo = ?")
            valores.append(int(avisos_cliente_por_correo))
        for columna, valor, largo in (("cargo", cargo, 80), ("telefono", telefono, 30)):
            if valor is not None:
                asignaciones.append(f"{columna} = ?")
                valores.append(valor.strip()[:largo] or None)
        if silencio_desde is not None or silencio_hasta is not None:
            # Las dos horas van juntas y válidas, o ninguna (una franja a medias no significa nada)
            desde, hasta = _db._hora_valida(silencio_desde), _db._hora_valida(silencio_hasta)
            if not (desde and hasta and desde != hasta):
                desde = hasta = None
            asignaciones += ["silencio_desde = ?", "silencio_hasta = ?"]
            valores += [desde, hasta]
        if asignaciones:
            conn.execute(
                f"UPDATE usuario_perfil SET {', '.join(asignaciones)} WHERE usuario_id = ?",
                [*valores, usuario_id],
            )
        conn.commit()
    finally:
        conn.close()


def guardar_apariencia_usuario(usuario_id: int, tema: str | None = None, densidad: str | None = None) -> None:
    """Tema y densidad en la cuenta (se aplican en cualquier dispositivo). Valores no válidos se ignoran. Viven en `usuarios` (como el idioma)
    porque esa fila ya se lee en cada petición: así aplicarlos no cuesta una consulta más por página."""
    asignaciones, valores = [], []
    if tema in _db.TEMAS_VALIDOS:
        asignaciones.append("tema = ?"); valores.append(tema)
    if densidad in _db.DENSIDADES_VALIDAS:
        asignaciones.append("densidad = ?"); valores.append(densidad)
    if not asignaciones:
        return
    conn = _db.get_connection()
    try:
        conn.execute(f"UPDATE usuarios SET {', '.join(asignaciones)} WHERE id = ?", [*valores, usuario_id])
        conn.commit()
    finally:
        conn.close()


def apariencia_usuario(usuario_id: int) -> dict:
    conn = _db.get_connection()
    try:
        f = conn.execute("SELECT tema, densidad FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    finally:
        conn.close()
    return {"tema": f["tema"] if f else None, "densidad": f["densidad"] if f else None}


def _hora_valida(texto: str | None) -> str | None:
    """«08:30» -> «08:30»; cualquier otra cosa -> None."""
    import re as _re

    m = _re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", (texto or "").strip())
    return f"{m.group(1)}:{m.group(2)}" if m else None


def en_horas_de_silencio(usuario_id: int, ahora=None) -> bool:
    """¿Está la persona en su franja de «no molestar» (hora local del despacho)? Con desde > hasta la franja cruza la medianoche
    (22:00-08:00). Solo silencia el push al móvil: la notificación sigue apareciendo en la aplicación."""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _Zona

    perfil = _db.obtener_perfil_usuario(usuario_id)
    desde, hasta = _db._hora_valida(perfil["silencio_desde"]), _db._hora_valida(perfil["silencio_hasta"])
    if not (desde and hasta) or desde == hasta:
        return False
    if ahora is None:
        tenant = _db.tenant_de_usuario(usuario_id)
        try:
            ahora = _dt.now(_Zona(_db.zona_horaria_tenant(tenant["id"] if tenant else None)))
        except Exception:
            ahora = _dt.now()
    actual = ahora.strftime("%H:%M")
    return (desde <= actual < hasta) if desde < hasta else (actual >= desde or actual < hasta)


def notificacion_tipo_activa(usuario_id: int, tipo: str) -> bool:
    """Antes de esta función, notificar_push_vencimientos/
    notificar_push_tiquets se podían editar desde /ajustes/perfil pero
    NINGÚN punto de emisión las comprobaba de verdad -- desactivarlas no
    hacía nada. Quien emite una notificación debe llamar a esto primero
    (ver app/main.py, app/rutas_portal_cliente.py, app/correo.py,
    app/rutas_tiquets.py)."""
    columna = _db._COLUMNAS_PREFERENCIA_NOTIFICACION.get(tipo)
    if columna is None:
        return True
    perfil = _db.obtener_perfil_usuario(usuario_id)
    return bool(perfil[columna])


def guardar_avatar_usuario(usuario_id: int, contenido: bytes, tipo_mime: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("INSERT INTO usuario_perfil (usuario_id) VALUES (?) ON CONFLICT DO NOTHING", (usuario_id,))
        conn.execute(
            "UPDATE usuario_perfil SET avatar_contenido = ?, avatar_tipo_mime = ? WHERE usuario_id = ?",
            (contenido, tipo_mime, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_avatar_usuario(usuario_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE usuario_perfil SET avatar_contenido = NULL, avatar_tipo_mime = NULL WHERE usuario_id = ?",
            (usuario_id,),
        )
        conn.commit()
    finally:
        conn.close()


def crear_adjunto_ia(
    usuario_id: int, nombre_archivo: str, tipo_mime: str | None, contenido: bytes, origen: str = "usuario"
) -> int:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO ia_adjuntos (usuario_id, nombre_archivo, tipo_mime, contenido, creado_en, origen) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (usuario_id, nombre_archivo, tipo_mime, contenido, _db.now_iso(), origen),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def obtener_adjunto_ia(usuario_id: int, adjunto_id: int) -> sqlite3.Row | None:
    """Filtra por usuario_id -- un adjunto es privado a quien lo subió, ni
    siquiera otro miembro del mismo tenant puede leerlo (a diferencia de
    tiquets, esto no es un tablero compartido)."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM ia_adjuntos WHERE id = ? AND usuario_id = ?", (adjunto_id, usuario_id)
        ).fetchone()
    finally:
        conn.close()


def usuarios_con_resumen_semanal_activo() -> list[int]:
    """Usados por el hilo _resumen_ia_semanal (app/main.py) -- quién ha
    activado la casilla correspondiente en su perfil (Fase G1)."""
    conn = _db.get_connection()
    try:
        return [
            r["usuario_id"]
            for r in conn.execute(
                "SELECT usuario_id FROM usuario_perfil WHERE notificar_resumen_semanal = 1"
            ).fetchall()
        ]
    finally:
        conn.close()


def perfiles_con_resumen_diario() -> list:
    """Quién tiene activado el resumen diario de pendientes (hilo de app/resumen_pendientes.py)."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT usuario_id, resumen_diario_hora, resumen_diario_email, resumen_diario_ultimo FROM usuario_perfil WHERE resumen_diario = 1").fetchall()
    finally:
        conn.close()


def marcar_resumen_diario_entregado(usuario_id: int, dia: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE usuario_perfil SET resumen_diario_ultimo = ? WHERE usuario_id = ?", (dia, usuario_id))
        conn.commit()
    finally:
        conn.close()


def nombre_mostrado_usuario(usuario_id: int) -> str | None:
    """Atajo de solo lectura para el resto de la app (p.ej. sustituir el
    email crudo por el nombre elegido donde se muestre autoría) -- evita
    que cada sitio tenga que llamar a obtener_perfil_usuario() entero."""
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            "SELECT nombre_mostrado FROM usuario_perfil WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()
        return fila["nombre_mostrado"] if fila else None
    finally:
        conn.close()
