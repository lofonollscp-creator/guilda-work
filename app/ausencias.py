"""Ausencias, vacaciones y permisos (PLAN_MAESTRO §7.4): quien trabaja las pide, quien gestiona el fichaje del despacho (gestor de fichajes,
supervisor o administrador) las aprueba o rechaza, y las vacaciones descuentan de un saldo anual.

Reglas:
- Solo cuentan los **días laborables** (lunes a viernes sin festivos nacionales ni los del despacho; el mismo calendario que los plazos). Un solo día
  puede pedirse **medio día** (0,5).
- Solo `vacaciones` descuenta saldo. Permisos, asuntos propios, bajas y otros se registran y se aprueban pero no gastan días.
- Saldo del año = días anuales del despacho (22 por defecto) o los que se le hayan fijado a esa persona ese año. Cuentan las aprobadas y las pendientes
  (así no se pueden pedir dos veces los mismos días). Una solicitud no puede cruzar de año: se pide en dos.
- No se solapan dos solicitudes vivas (pendiente o aprobada) de la misma persona.
- Quien gestiona puede **registrar** una ausencia de otra persona (queda aprobada) y **cancelar** cualquiera; cada persona cancela las suyas mientras no hayan
  acabado.
Todo avisa por la campana y el móvil a quien corresponda."""
from __future__ import annotations

from datetime import date, timedelta

from flask_babel import lazy_gettext as _l

from . import db, nucleo

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ausencias (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL CHECK (tipo IN ('vacaciones', 'asuntos_propios', 'permiso', 'baja', 'otro')),
    desde TEXT NOT NULL,
    hasta TEXT NOT NULL,
    medio_dia INTEGER NOT NULL DEFAULT 0,
    dias REAL NOT NULL,
    motivo TEXT,
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'aprobada', 'rechazada', 'cancelada')),
    creada_por INTEGER REFERENCES usuarios(id),
    resuelta_por INTEGER REFERENCES usuarios(id),
    resuelta_en TEXT,
    comentario TEXT,
    creada_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ausencias_tenant ON ausencias(tenant_id, estado, desde);
CREATE INDEX IF NOT EXISTS idx_ausencias_usuario ON ausencias(usuario_id, desde);
CREATE TABLE IF NOT EXISTS ausencias_saldos (
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    anio INTEGER NOT NULL,
    dias REAL NOT NULL,
    PRIMARY KEY (tenant_id, usuario_id, anio)
);
CREATE TABLE IF NOT EXISTS ausencias_config (
    tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    dias_vacaciones REAL NOT NULL DEFAULT 22
);
"""

TIPOS = (("vacaciones", _l("Vacaciones")), ("asuntos_propios", _l("Asuntos propios")), ("permiso", _l("Permiso retribuido")),
         ("baja", _l("Baja médica")), ("otro", _l("Otro")))
ESTADOS = (("pendiente", _l("Pendiente")), ("aprobada", _l("Aprobada")), ("rechazada", _l("Rechazada")), ("cancelada", _l("Cancelada")))
CONSUMEN_SALDO = frozenset({"vacaciones"})
DIAS_POR_DEFECTO = 22
VIVAS = ("pendiente", "aprobada")


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _fecha(valor, campo: str) -> date:
    try:
        return date.fromisoformat((valor or "").strip()[:10])
    except ValueError:
        raise ValueError(f"{campo}: indica una fecha válida (AAAA-MM-DD).") from None


def dias_laborables(tenant_id: int, desde: date, hasta: date, medio_dia: bool = False) -> float:
    """Días laborables entre dos fechas, ambas incluidas. `medio_dia` solo vale para un único día laborable (0,5)."""
    anios = tuple(range(desde.year, hasta.year + 1))
    cal = nucleo.calendario_del_despacho(tenant_id, "general", anios)
    n, d = 0, desde
    while d <= hasta:
        if cal.es_habil(d):
            n += 1
        d += timedelta(days=1)
    return 0.5 if (medio_dia and n == 1) else float(n)


# --- Saldo -----------------------------------------------------------------------------------------------------------------------------------------
def dias_anuales(tenant_id: int, usuario_id: int | None = None, anio: int | None = None) -> float:
    conn = db.get_connection()
    try:
        if usuario_id and anio:
            f = conn.execute("SELECT dias FROM ausencias_saldos WHERE tenant_id = ? AND usuario_id = ? AND anio = ?", (tenant_id, usuario_id, anio)).fetchone()
            if f:
                return float(f["dias"])
        f = conn.execute("SELECT dias_vacaciones FROM ausencias_config WHERE tenant_id = ?", (tenant_id,)).fetchone()
        return float(f["dias_vacaciones"]) if f else float(DIAS_POR_DEFECTO)
    finally:
        conn.close()


def fijar_dias_anuales(tenant_id: int, dias: float) -> None:
    dias = _dias_validos(dias)
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO ausencias_config (tenant_id, dias_vacaciones) VALUES (?, ?) ON CONFLICT(tenant_id) DO UPDATE SET dias_vacaciones = excluded.dias_vacaciones", (tenant_id, dias))
        conn.commit()
    finally:
        conn.close()


def fijar_saldo(tenant_id: int, usuario_id: int, anio: int, dias: float | None) -> None:
    """Días de vacaciones de UNA persona ese año (por antigüedad, contrato...). `None` vuelve a los del despacho."""
    conn = db.get_connection()
    try:
        nucleo._usuario_de_tenant(conn, usuario_id, tenant_id)
        if dias is None:
            conn.execute("DELETE FROM ausencias_saldos WHERE tenant_id = ? AND usuario_id = ? AND anio = ?", (tenant_id, usuario_id, anio))
        else:
            conn.execute("INSERT INTO ausencias_saldos (tenant_id, usuario_id, anio, dias) VALUES (?, ?, ?, ?) ON CONFLICT(tenant_id, usuario_id, anio) DO UPDATE SET dias = excluded.dias",
                         (tenant_id, usuario_id, anio, _dias_validos(dias)))
        conn.commit()
    finally:
        conn.close()


def _dias_validos(dias) -> float:
    try:
        v = float(str(dias).replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError("Indica un número de días.") from None
    if not 0 <= v <= 366:
        raise ValueError("Los días deben estar entre 0 y 366.")
    return round(v * 2) / 2


def _consumidos(conn, tenant_id: int, usuario_id: int, anio: int, estado: str, excepto_id: int | None = None) -> float:
    fila = conn.execute(
        "SELECT COALESCE(SUM(dias), 0) AS n FROM ausencias WHERE tenant_id = ? AND usuario_id = ? AND estado = ? AND tipo = 'vacaciones' AND substr(desde, 1, 4) = ? AND id != ?",
        (tenant_id, usuario_id, estado, str(anio), excepto_id or 0)).fetchone()
    return float(fila["n"])


def saldo(tenant_id: int, usuario_id: int, anio: int | None = None) -> dict:
    anio = anio or date.today().year
    conn = db.get_connection()
    try:
        total = dias_anuales(tenant_id, usuario_id, anio)
        usadas, pendientes = _consumidos(conn, tenant_id, usuario_id, anio, "aprobada"), _consumidos(conn, tenant_id, usuario_id, anio, "pendiente")
    finally:
        conn.close()
    return {"anio": anio, "total": total, "aprobadas": usadas, "pendientes": pendientes, "disponibles": total - usadas - pendientes}


# --- Quién puede qué ------------------------------------------------------------------------------------------------------------------------------
def puede_gestionar(usuario_id: int, tenant_id: int | None) -> bool:
    """Gestor de fichajes o supervisor del despacho (el superadmin entra por la administración del fichaje)."""
    if not tenant_id:
        return False
    u = db.obtener_usuario(usuario_id)
    if u is None or u["tenant_id"] != tenant_id:
        return False
    return bool(db.es_gestor_fichajes(usuario_id) or db.es_supervisor_tenant(usuario_id))


def _gestores(tenant_id: int, excepto: int | None = None) -> list[int]:
    return [u for u in db.usuarios_de_tenant(tenant_id) if u != excepto and puede_gestionar(u, tenant_id)]


def _avisar(usuario_id: int, titulo: str, cuerpo: str, url: str) -> None:
    try:
        from . import notificaciones
        notificaciones.crear_y_enviar(usuario_id, "ausencia", titulo, cuerpo, url=url, datos={"tipo": "ausencia"})
    except Exception:  # noqa: BLE001  (un aviso que falla nunca debe impedir la gestión)
        pass


def _liberar_turnos(usuario_id: int, desde: str, hasta: str) -> None:
    """Una ausencia aprobada cubre esos días: si había turnos asignados, se quitan."""
    try:
        from . import turnos
        turnos.liberar(usuario_id, desde, hasta)
    except Exception:  # noqa: BLE001
        pass


def _nombre(usuario_id: int) -> str:
    u = db.obtener_usuario(usuario_id)
    return db.nombre_mostrado_usuario(usuario_id) or (u["email"] if u else "?")


def _rango(a) -> str:
    d, h = a["desde"], a["hasta"]
    f = lambda s: f"{s[8:10]}/{s[5:7]}"  # noqa: E731
    return f(d) if d == h else f"{f(d)} – {f(h)}"


# --- Solicitar, resolver, cancelar -------------------------------------------------------------------------------------------------------------
def solicitar(tenant_id: int, usuario_id: int, tipo: str, desde, hasta=None, *, motivo: str | None = None, medio_dia: bool = False, por: int | None = None) -> int:
    """Pide (o, si `por` es quien gestiona y no la propia persona, registra ya aprobada) una ausencia. Devuelve su id."""
    if tipo not in dict(TIPOS):
        raise ValueError("Elige un tipo de ausencia válido.")
    d, h = _fecha(desde, "Desde"), _fecha(hasta or desde, "Hasta")
    if h < d:
        raise ValueError("La fecha de fin no puede ser anterior a la de inicio.")
    if (h - d).days > 365:
        raise ValueError("Una ausencia no puede durar más de un año.")
    if d.year != h.year:
        raise ValueError("Una ausencia no puede cruzar de año: pídela en dos tramos.")
    if medio_dia and d != h:
        raise ValueError("Solo se puede pedir medio día para un único día.")
    n = dias_laborables(tenant_id, d, h, medio_dia)
    if n <= 0:
        raise ValueError("Ese periodo no incluye ningún día laborable.")
    registra_otro = por is not None and por != usuario_id
    if registra_otro and not puede_gestionar(por, tenant_id):
        raise ValueError("Solo quien gestiona el fichaje puede registrar la ausencia de otra persona.")
    conn = db.get_connection()
    try:
        nucleo._usuario_de_tenant(conn, usuario_id, tenant_id)
        solapa = conn.execute(
            "SELECT desde, hasta FROM ausencias WHERE usuario_id = ? AND estado IN ('pendiente', 'aprobada') AND desde <= ? AND hasta >= ? LIMIT 1", (usuario_id, h.isoformat(), d.isoformat())).fetchone()
        if solapa:
            raise ValueError(f"Ya hay una ausencia del {solapa['desde']} al {solapa['hasta']} que se solapa con estas fechas.")
        if tipo in CONSUMEN_SALDO:
            total = dias_anuales(tenant_id, usuario_id, d.year)
            gastados = _consumidos(conn, tenant_id, usuario_id, d.year, "aprobada") + _consumidos(conn, tenant_id, usuario_id, d.year, "pendiente")
            if gastados + n > total:
                raise ValueError(f"No te quedan días suficientes: pides {n:g} y tienes {max(total - gastados, 0):g} disponibles en {d.year}.")
        estado = "aprobada" if registra_otro else "pendiente"
        cur = conn.execute(
            "INSERT INTO ausencias (tenant_id, usuario_id, tipo, desde, hasta, medio_dia, dias, motivo, estado, creada_por, resuelta_por, resuelta_en, creada_en) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, usuario_id, tipo, d.isoformat(), h.isoformat(), int(medio_dia), n, (motivo or "").strip()[:500] or None, estado, por or usuario_id,
             por if registra_otro else None, db.now_iso() if registra_otro else None, db.now_iso()))
        conn.commit()
        aid = cur.lastrowid
    finally:
        conn.close()
    a = {"desde": d.isoformat(), "hasta": h.isoformat()}
    if registra_otro:
        _liberar_turnos(usuario_id, a["desde"], a["hasta"])
    nombre_tipo = str(dict(TIPOS)[tipo])
    if registra_otro:
        _avisar(usuario_id, "Se ha registrado una ausencia tuya", f"{nombre_tipo} · {_rango(a)} · {n:g} día(s).", "/fichaje/ausencias")
    else:
        for gestor in _gestores(tenant_id, excepto=usuario_id):
            _avisar(gestor, "Ausencia por aprobar", f"{_nombre(usuario_id)}: {nombre_tipo} · {_rango(a)} · {n:g} día(s).", "/fichaje/ausencias/equipo")
    return aid


def obtener(tenant_id: int, ausencia_id: int):
    conn = db.get_connection()
    try:
        return conn.execute(
            "SELECT a.*, COALESCE(NULLIF(p.nombre_mostrado, ''), u.email) AS persona FROM ausencias a JOIN usuarios u ON u.id = a.usuario_id "
            "LEFT JOIN usuario_perfil p ON p.usuario_id = a.usuario_id WHERE a.id = ? AND a.tenant_id = ?", (ausencia_id, tenant_id)).fetchone()
    finally:
        conn.close()


def resolver(tenant_id: int, gestor_id: int, ausencia_id: int, aprobar: bool, comentario: str | None = None) -> None:
    if not puede_gestionar(gestor_id, tenant_id):
        raise ValueError("Solo quien gestiona el fichaje puede aprobar o rechazar ausencias.")
    a = obtener(tenant_id, ausencia_id)
    if a is None:
        raise ValueError("No existe esa ausencia.")
    if a["estado"] != "pendiente":
        raise ValueError("Esa ausencia ya está resuelta.")
    conn = db.get_connection()
    try:
        if aprobar and a["tipo"] in CONSUMEN_SALDO:
            anio = int(a["desde"][:4])
            gastados = _consumidos(conn, tenant_id, a["usuario_id"], anio, "aprobada")
            if gastados + a["dias"] > dias_anuales(tenant_id, a["usuario_id"], anio):
                raise ValueError("Con los días que ya tiene aprobados, esta persona se quedaría sin saldo. Ajusta sus días anuales o recházala.")
        cur = conn.execute("UPDATE ausencias SET estado = ?, resuelta_por = ?, resuelta_en = ?, comentario = ? WHERE id = ? AND tenant_id = ? AND estado = 'pendiente'",
                           ("aprobada" if aprobar else "rechazada", gestor_id, db.now_iso(), (comentario or "").strip()[:500] or None, ausencia_id, tenant_id))
        conn.commit()
        if cur.rowcount == 0:
            raise ValueError("Esa ausencia ya está resuelta.")
    finally:
        conn.close()
    if aprobar:
        _liberar_turnos(a["usuario_id"], a["desde"], a["hasta"])
    resumen = f"{dict(TIPOS)[a['tipo']]} · {_rango(a)}"
    _avisar(a["usuario_id"], "Ausencia aprobada" if aprobar else "Ausencia rechazada", resumen + (f" — {comentario.strip()}" if (comentario or "").strip() else ""), "/fichaje/ausencias")


def cancelar(tenant_id: int, usuario_id: int, ausencia_id: int) -> None:
    """La persona cancela la suya (si no ha terminado ya); quien gestiona, cualquiera del despacho."""
    a = obtener(tenant_id, ausencia_id)
    if a is None:
        raise ValueError("No existe esa ausencia.")
    gestor = puede_gestionar(usuario_id, tenant_id)
    if a["usuario_id"] != usuario_id and not gestor:
        raise ValueError("No puedes cancelar la ausencia de otra persona.")
    if a["estado"] not in VIVAS:
        raise ValueError("Esa ausencia ya no está activa.")
    if a["hasta"] < date.today().isoformat() and not gestor:
        raise ValueError("Esa ausencia ya ha pasado.")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE ausencias SET estado = 'cancelada', resuelta_por = ?, resuelta_en = ? WHERE id = ? AND tenant_id = ?", (usuario_id, db.now_iso(), ausencia_id, tenant_id))
        conn.commit()
    finally:
        conn.close()
    if a["usuario_id"] != usuario_id:
        _avisar(a["usuario_id"], "Se ha cancelado una ausencia tuya", f"{dict(TIPOS)[a['tipo']]} · {_rango(a)}", "/fichaje/ausencias")
    elif a["estado"] == "aprobada":
        for gestor_id in _gestores(tenant_id, excepto=usuario_id):
            _avisar(gestor_id, "Ausencia cancelada", f"{_nombre(usuario_id)} ha cancelado: {dict(TIPOS)[a['tipo']]} · {_rango(a)}", "/fichaje/ausencias/equipo")


# --- Consultas ------------------------------------------------------------------------------------------------------------------------------------
def listar(tenant_id: int, *, usuario_id: int | None = None, estado: str | None = None, anio: int | None = None, desde: str | None = None, limite: int = 300) -> list:
    donde, p = ["a.tenant_id = ?"], [tenant_id]
    for col, val in (("a.usuario_id", usuario_id), ("a.estado", estado)):
        if val:
            donde.append(f"{col} = ?"); p.append(val)
    if anio:
        donde.append("substr(a.desde, 1, 4) = ?"); p.append(str(anio))
    if desde:
        donde.append("a.hasta >= ?"); p.append(desde)
    conn = db.get_connection()
    try:
        return conn.execute(
            "SELECT a.*, COALESCE(NULLIF(p.nombre_mostrado, ''), u.email) AS persona FROM ausencias a JOIN usuarios u ON u.id = a.usuario_id "
            f"LEFT JOIN usuario_perfil p ON p.usuario_id = a.usuario_id WHERE {' AND '.join(donde)} ORDER BY a.desde DESC, a.id DESC LIMIT ?", [*p, max(1, min(limite, 1000))]).fetchall()
    finally:
        conn.close()


def quien_falta(tenant_id: int, dia: date | None = None) -> list:
    """Quién está ausente (aprobada) ese día, para el equipo."""
    iso = (dia or date.today()).isoformat()
    conn = db.get_connection()
    try:
        return conn.execute(
            "SELECT a.*, COALESCE(NULLIF(p.nombre_mostrado, ''), u.email) AS persona FROM ausencias a JOIN usuarios u ON u.id = a.usuario_id "
            "LEFT JOIN usuario_perfil p ON p.usuario_id = a.usuario_id WHERE a.tenant_id = ? AND a.estado = 'aprobada' AND a.desde <= ? AND a.hasta >= ? ORDER BY persona",
            (tenant_id, iso, iso)).fetchall()
    finally:
        conn.close()


def saldos_del_equipo(tenant_id: int, anio: int | None = None) -> list[dict]:
    anio = anio or date.today().year
    return [{"usuario_id": e["id"], "persona": e["nombre"], **saldo(tenant_id, e["id"], anio)} for e in nucleo.equipo(tenant_id)]
