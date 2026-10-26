"""Consultas del backoffice sobre la base de datos de la plataforma (la misma
registro.db que usa la app, vía app.db). Aquí solo hay lectura y las escrituras
administrativas concretas (tenants, asignaciones y permisos)."""
from __future__ import annotations

import math
import secrets
import sqlite3
from datetime import datetime, timedelta

from app import db as plataforma
from app.bd.errores import ErrorIntegridad
from app import herramientas

ESTADOS_RIESGO = ("pago_fallido", "past_due", "unpaid")
DIAS_SIN_ACTIVIDAD_CHURN = 30
POR_PAGINA_OPCIONES = (10, 25, 50, 100)


def _con():
    return plataforma.get_connection()


def paginar(total: int, pagina: int, por_pagina: int) -> dict:
    por_pagina = por_pagina if por_pagina in POR_PAGINA_OPCIONES else 25
    paginas = max(1, math.ceil(total / por_pagina))
    pagina = min(max(1, pagina), paginas)
    return {
        "total": total, "pagina": pagina, "paginas": paginas, "por_pagina": por_pagina,
        "desde": 0 if total == 0 else (pagina - 1) * por_pagina + 1, "hasta": min(total, pagina * por_pagina),
        "offset": (pagina - 1) * por_pagina,
    }


# --- Dashboard --------------------------------------------------------------

def kpis_dashboard() -> dict:
    conn = _con()
    try:
        marcadores = ",".join("?" * len(ESTADOS_RIESGO))
        activas = conn.execute("SELECT COUNT(*) FROM tenants WHERE suscripcion_estado = 'activa' AND id > 0").fetchone()[0]
        mrr = conn.execute(
            "SELECT COALESCE(SUM(p.precio_mensual_centimos), 0) FROM tenants t JOIN planes_guilda p ON p.id = t.plan_id "
            "WHERE t.suscripcion_estado = 'activa'"
        ).fetchone()[0]
        en_riesgo = conn.execute(
            f"SELECT COUNT(*) FROM tenants WHERE suscripcion_estado IN ({marcadores})", ESTADOS_RIESGO
        ).fetchone()[0]
        mrr_riesgo = conn.execute(
            f"SELECT COALESCE(SUM(p.precio_mensual_centimos), 0) FROM tenants t JOIN planes_guilda p ON p.id = t.plan_id "
            f"WHERE t.suscripcion_estado IN ({marcadores})", ESTADOS_RIESGO,
        ).fetchone()[0]
        tiers = conn.execute(
            """SELECT COALESCE(p.nombre, 'Sin plan') AS nombre, COUNT(*) AS n
               FROM tenants t LEFT JOIN planes_guilda p ON p.id = t.plan_id GROUP BY p.id ORDER BY n DESC, nombre"""
        ).fetchall()
        extras = conn.execute(
            "SELECT COUNT(*) FROM tenants_extras_activos WHERE activo_hasta IS NULL OR activo_hasta >= ?", (plataforma.now_iso(),)
        ).fetchone()[0]
        desde = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
        webhooks = conn.execute(
            "SELECT COUNT(*) FROM webhooks_entregas WHERE entregado_en >= ? "
            "AND NOT (estado_http IS NOT NULL AND estado_http BETWEEN 200 AND 299)", (desde,),
        ).fetchone()[0]
        totales = {
            "tenants": conn.execute("SELECT COUNT(*) FROM tenants WHERE id > 0").fetchone()[0],
            "tenants_activos": conn.execute("SELECT COUNT(*) FROM tenants WHERE activo = 1 AND id > 0").fetchone()[0],
            "usuarios": conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0],
            "usuarios_sin_tenant": conn.execute("SELECT COUNT(*) FROM usuarios WHERE tenant_id IS NULL").fetchone()[0],
            "clientes": conn.execute("SELECT COUNT(*) FROM clientes_fiscales WHERE papelera_en IS NULL").fetchone()[0],
        }
    finally:
        conn.close()
    churn = tenants_en_riesgo_churn()
    return {
        "suscripciones_activas": activas, "mrr": mrr, "arr": mrr * 12, "pagos_en_riesgo": en_riesgo, "mrr_en_riesgo": mrr_riesgo,
        "tiers": [dict(t) for t in tiers], "extras_activos": extras, "webhooks_fallidos": webhooks,
        "churn": churn, **totales,
    }


def tenants_en_riesgo_churn() -> list[dict]:
    """Tenants con pago fallido, suspendidos o activos pero sin actividad en 30 días."""
    limite = (datetime.now() - timedelta(days=DIAS_SIN_ACTIVIDAD_CHURN)).isoformat(timespec="seconds")
    resultado = []
    conn = _con()
    try:
        filas = conn.execute("SELECT id, nombre, activo, suscripcion_estado FROM tenants WHERE id > 0 ORDER BY nombre").fetchall()
    finally:
        conn.close()
    for t in filas:
        if t["suscripcion_estado"] in ESTADOS_RIESGO:
            motivo = "pago fallido"
        elif not t["activo"]:
            motivo = "suspendido"
        else:
            ultima = plataforma.ultima_actividad_tenant(t["id"])
            if ultima is not None and ultima >= limite:
                continue
            if ultima is None:
                continue  # tenant recién creado sin uso: todavía no es señal de abandono
            motivo = f"sin actividad desde {ultima[:10]}"
        resultado.append({"id": t["id"], "nombre": t["nombre"], "motivo": motivo})
    return resultado


# --- Tenants ----------------------------------------------------------------

def listar_tenants(q: str = "", estado: str = "", plan: str = "", orden: str = "nombre", pagina: int = 1, por_pagina: int = 25):
    donde, params = ["t.id > 0"], []
    if q.strip():
        donde.append("LOWER(t.nombre) LIKE LOWER(?) ESCAPE '\\'")
        params.append("%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if estado == "activo":
        donde.append("t.activo = 1")
    elif estado == "suspendido":
        donde.append("t.activo = 0")
    if plan == "ninguno":
        donde.append("t.plan_id IS NULL")
    elif plan.isdigit():
        donde.append("t.plan_id = ?")
        params.append(int(plan))
    ordenes = {"nombre": "LOWER(t.nombre)", "usuarios": "n_usuarios DESC, t.nombre", "recientes": "t.creado_en DESC"}
    conn = _con()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM tenants t WHERE {' AND '.join(donde)}", params).fetchone()[0]
        pag = paginar(total, pagina, por_pagina)
        filas = conn.execute(
            # (sin subconsultas correlacionadas: Citus no las admite cuando en el FROM hay una tabla de referencia —`tenants`—; los recuentos se agrupan antes y se unen)
            f"""SELECT t.id, t.nombre, t.activo, t.creado_en, t.suscripcion_estado, p.nombre AS plan, COALESCE(u.n, 0) AS n_usuarios, COALESCE(c.n, 0) AS n_clientes
                FROM tenants t LEFT JOIN planes_guilda p ON p.id = t.plan_id
                LEFT JOIN (SELECT tenant_id, COUNT(*) AS n FROM usuarios GROUP BY tenant_id) u ON u.tenant_id = t.id
                LEFT JOIN (SELECT tenant_id, COUNT(*) AS n FROM clientes_fiscales WHERE papelera_en IS NULL GROUP BY tenant_id) c ON c.tenant_id = t.id
                WHERE {' AND '.join(donde)} ORDER BY {ordenes.get(orden, ordenes['nombre'])} LIMIT ? OFFSET ?""",
            [*params, pag["por_pagina"], pag["offset"]],
        ).fetchall()
    finally:
        conn.close()
    return [dict(f, ultima_actividad=plataforma.ultima_actividad_tenant(f["id"])) for f in filas], pag


def planes() -> list[dict]:
    conn = _con()
    try:
        return [dict(p) for p in conn.execute("SELECT id, nombre FROM planes_guilda ORDER BY nombre").fetchall()]
    finally:
        conn.close()


def detalle_tenant(tenant_id: int) -> dict | None:
    conn = _con()
    try:
        t = conn.execute(
            "SELECT t.*, p.nombre AS plan, p.precio_mensual_centimos AS plan_precio FROM tenants t "
            "LEFT JOIN planes_guilda p ON p.id = t.plan_id WHERE t.id = ?", (tenant_id,),
        ).fetchone()
        if t is None:
            return None
        usuarios = conn.execute("SELECT COUNT(*) FROM usuarios WHERE tenant_id = ?", (tenant_id,)).fetchone()[0]
        clientes = conn.execute(
            "SELECT COUNT(*) FROM clientes_fiscales WHERE tenant_id = ? AND papelera_en IS NULL", (tenant_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    ocultas = plataforma.herramientas_ocultas_de_tenant(tenant_id)
    modulos = [{"id": h["id"], "nombre": h["nombre"], "descripcion": h.get("descripcion", ""), "activo": h["id"] not in ocultas}
               for h in herramientas.HERRAMIENTAS]
    return {
        "tenant": dict(t), "n_usuarios": usuarios, "n_clientes": clientes, "modulos": modulos,
        "ultima_actividad": plataforma.ultima_actividad_tenant(tenant_id),
        "extras": [dict(e) for e in plataforma.listar_extras_activos_tenant(tenant_id)],
        "equipo": plataforma.estadisticas_equipo_por_usuario(tenant_id),
    }


def crear_tenant(nombre: str) -> int:
    nombre = nombre.strip()
    if not nombre or len(nombre) > 120:
        raise ValueError("Indica el nombre de la organización (máx. 120 caracteres).")
    try:
        return plataforma.crear_tenant(nombre)
    except ErrorIntegridad:
        raise ValueError("Ya existe un tenant con ese nombre.") from None


def renombrar_tenant(tenant_id: int, nombre: str) -> None:
    nombre = nombre.strip()
    if not nombre or len(nombre) > 120:
        raise ValueError("Indica un nombre válido (máx. 120 caracteres).")
    try:
        plataforma.renombrar_tenant(tenant_id, nombre)
    except ErrorIntegridad:
        raise ValueError("Ya existe un tenant con ese nombre.") from None


def alternar_modulo(tenant_id: int, modulo_id: str) -> bool:
    """Devuelve el nuevo estado (True = activo)."""
    if modulo_id not in {h["id"] for h in herramientas.HERRAMIENTAS}:
        raise ValueError("Módulo desconocido.")
    if modulo_id in plataforma.herramientas_ocultas_de_tenant(tenant_id):
        plataforma.mostrar_herramienta(tenant_id, modulo_id)
        return True
    plataforma.ocultar_herramienta(tenant_id, modulo_id)
    return False


# --- Usuarios ---------------------------------------------------------------

def _col_acceso(conn) -> str:
    """`u.ultimo_acceso` si la app ya migró la columna; si no, NULL (el backoffice
    es otro proceso y puede arrancar antes que la app principal)."""
    cols = {f[1] for f in conn.execute("PRAGMA table_info(usuarios)")}
    return "u.ultimo_acceso" if "ultimo_acceso" in cols else "NULL"


def listar_usuarios(q: str = "", tenant: str = "", rol: str = "", orden: str = "creado", pagina: int = 1, por_pagina: int = 25):
    donde, params = ["1=1"], []
    if q.strip():
        like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        donde.append("(LOWER(u.email) LIKE LOWER(?) ESCAPE '\\' OR LOWER(COALESCE(p.nombre_mostrado, '')) LIKE LOWER(?) ESCAPE '\\')")
        params += [like, like]
    if tenant == "ninguno":
        donde.append("u.tenant_id IS NULL")
    elif tenant.isdigit():
        donde.append("u.tenant_id = ?")
        params.append(int(tenant))
    if rol == "admin":
        donde.append("u.rol = 'admin'")
    elif rol == "gestor":
        donde.append("u.gestor_fichajes = 1")
    elif rol == "supervisor":
        donde.append("u.supervisor_tenant = 1")
    elif rol == "usuario":
        donde.append("u.rol = 'usuario' AND u.gestor_fichajes = 0 AND u.supervisor_tenant = 0")
    ordenes = {
        "creado": "u.creado_en DESC", "email": "LOWER(u.email)", "nombre": "LOWER(COALESCE(NULLIF(p.nombre_mostrado, ''), u.email))",
    }
    conn = _con()
    try:
        base = f"FROM usuarios u LEFT JOIN usuario_perfil p ON p.usuario_id = u.id LEFT JOIN tenants t ON t.id = u.tenant_id WHERE {' AND '.join(donde)}"
        total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
        pag = paginar(total, pagina, por_pagina)
        filas = conn.execute(
            f"""SELECT u.id, u.email, u.rol, u.gestor_fichajes, u.supervisor_tenant, u.tenant_id, u.idioma, u.creado_en, {_col_acceso(conn)} AS ultimo_acceso,
                       COALESCE(NULLIF(p.nombre_mostrado, ''), u.email) AS nombre, t.nombre AS tenant, t.activo AS tenant_activo,
                       (SELECT COUNT(*) FROM tokens_api k WHERE k.usuario_id = u.id) AS dispositivos
                {base} ORDER BY {ordenes.get(orden, ordenes['creado'])} LIMIT ? OFFSET ?""",
            [*params, pag["por_pagina"], pag["offset"]],
        ).fetchall()
    finally:
        conn.close()
    return [dict(f) for f in filas], pag


def detalle_usuario(usuario_id: int) -> dict | None:
    conn = _con()
    try:
        u = conn.execute(
            """SELECT u.id, u.email, u.rol, u.gestor_fichajes, u.supervisor_tenant, u.tenant_id, u.idioma, u.creado_en, """ + _col_acceso(conn) + """ AS ultimo_acceso,
                      COALESCE(NULLIF(p.nombre_mostrado, ''), u.email) AS nombre, t.nombre AS tenant
               FROM usuarios u LEFT JOIN usuario_perfil p ON p.usuario_id = u.id LEFT JOIN tenants t ON t.id = u.tenant_id
               WHERE u.id = ?""", (usuario_id,),
        ).fetchone()
        _volcar_uso()
        dispositivos = conn.execute(
            "SELECT id, nombre_dispositivo, creado_en, ultimo_uso_en, permisos FROM tokens_api WHERE usuario_id = ? ORDER BY COALESCE(ultimo_uso_en, creado_en) DESC",
            (usuario_id,),
        ).fetchall() if u else []
    finally:
        conn.close()
    return None if u is None else {"usuario": dict(u), "dispositivos": [dict(d) for d in dispositivos]}


def asignar_tenant(usuario_id: int, tenant_id: int | None) -> None:
    if tenant_id is None:
        plataforma.desasignar_tenant(usuario_id)
    else:
        if plataforma.obtener_tenant(tenant_id) is None:
            raise ValueError("El tenant no existe.")
        plataforma.asignar_tenant(usuario_id, tenant_id)


def alternar_permiso(usuario_id: int, permiso: str) -> bool:
    """admin | gestor | supervisor. Devuelve el nuevo estado."""
    usuario = plataforma.obtener_usuario(usuario_id)
    if usuario is None:
        raise ValueError("El usuario no existe.")
    if permiso == "admin":
        if usuario["rol"] == "admin":
            plataforma.quitar_admin(usuario["email"])
            return False
        plataforma.hacer_admin(usuario["email"])
        return True
    if permiso == "gestor":
        nuevo = not usuario["gestor_fichajes"]
        plataforma.asignar_gestor_fichajes(usuario_id, nuevo)
        return nuevo
    if permiso == "supervisor":
        nuevo = not usuario["supervisor_tenant"]
        plataforma.asignar_supervisor_tenant(usuario_id, nuevo)
        return nuevo
    raise ValueError("Permiso desconocido.")


def revocar_dispositivo(usuario_id: int, token_id: int) -> bool:
    return plataforma.revocar_token_api_por_id(usuario_id, token_id)


def crear_usuario(email: str, tenant_id: int | None) -> tuple[int, str]:
    """Crea la identidad (Kratos) y la fila local; devuelve (id, contraseña
    temporal). La contraseña solo se muestra una vez en pantalla."""
    from app import kratos

    email = email.strip().lower()
    if "@" not in email or len(email) > 254 or " " in email:
        raise ValueError("Indica un email válido.")
    if plataforma.obtener_usuario_por_email(email) is not None:
        raise ValueError("Ya existe un usuario con ese email.")
    if tenant_id is not None and plataforma.obtener_tenant(tenant_id) is None:
        raise ValueError("El tenant no existe.")
    temporal = secrets.token_urlsafe(12)
    try:
        identidad = kratos.crear_identidad(email, temporal)
    except kratos.ErrorKratos as e:
        raise ValueError(f"No se pudo crear la identidad: {e}") from e
    usuario_id = plataforma.crear_usuario_vinculado_a_kratos(email, identidad)
    if tenant_id is not None:
        plataforma.asignar_tenant(usuario_id, tenant_id)
    return usuario_id, temporal


def personal_tenant(tenant_id: int) -> dict:
    """Ausencias, turnos y bolsa de horas de un despacho de un vistazo (solo lectura, salvo los días por defecto): para dar soporte sin entrar como nadie."""
    from datetime import date, timedelta
    from app import ausencias, bolsa_horas, turnos
    hoy = date.today()
    return {
        "dias_vacaciones": ausencias.dias_anuales(tenant_id),
        "pendientes": [dict(a) for a in ausencias.listar(tenant_id, estado="pendiente", limite=50)],
        "fuera_hoy": [dict(a) for a in ausencias.quien_falta(tenant_id, hoy)],
        "saldos": ausencias.saldos_del_equipo(tenant_id, hoy.year),
        "bolsa": bolsa_horas.resumen_equipo(tenant_id),
        "texto_horas": bolsa_horas.texto_horas,
        "tipos_turno": turnos.listar_tipos(tenant_id),
        "turnos_proximos": sum(1 for p in turnos.cuadrante(tenant_id, hoy.isoformat(), (hoy + timedelta(days=13)).isoformat())["personas"] for d in p["dias"].values() if "turno_id" in d),
    }


def _volcar_uso() -> None:
    """Lo que esta misma aplicación aún tiene en memoria del uso de los tokens (se vuelca cada 30 s); el backoffice normalmente corre en otro proceso y verá el dato con ese retraso."""
    try:
        from app import uso_diferido
        uso_diferido.volcar()
    except Exception:                                                                    # noqa: BLE001
        pass
