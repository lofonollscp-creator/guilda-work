"""Cuadrante de turnos (PLAN_MAESTRO §7.4): quien gestiona el fichaje define los turnos del despacho (p. ej. «Mañana 08:00–15:00») y los asigna a cada
persona por día; todo el equipo ve el cuadrante y cada persona recibe un aviso cuando le cambian el turno.

Reglas:
- Una persona tiene como mucho **un turno por día**. Asignar otro lo sustituye; asignar `None` lo quita.
- No se asigna un turno a quien tiene una **ausencia aprobada** ese día; y al aprobar o registrar una ausencia se quitan los turnos que cubría.
- Los turnos se **archivan** en vez de borrarse (los días ya asignados conservan su nombre y horario).
- Un turno puede cruzar la medianoche (`22:00–06:00`): la duración se calcula igualmente."""
from __future__ import annotations

from datetime import date, timedelta

from . import db, nucleo

ESQUEMA = """
CREATE TABLE IF NOT EXISTS turnos_tipos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    inicio TEXT NOT NULL,
    fin TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#6c8cff',
    archivado INTEGER NOT NULL DEFAULT 0,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turnos_tipos_tenant ON turnos_tipos(tenant_id, archivado);
CREATE TABLE IF NOT EXISTS turnos_asignados (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    fecha TEXT NOT NULL,
    turno_id INTEGER NOT NULL REFERENCES turnos_tipos(id),
    asignado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    UNIQUE (usuario_id, fecha)
);
CREATE INDEX IF NOT EXISTS idx_turnos_asignados_fecha ON turnos_asignados(tenant_id, fecha);
CREATE TABLE IF NOT EXISTS fichaje_avisos_turno (
    usuario_id INTEGER NOT NULL,
    entrada_id INTEGER NOT NULL,
    avisado_en TEXT NOT NULL,
    PRIMARY KEY (usuario_id, entrada_id)
);
"""

DIAS_CORTOS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
MAX_RANGO_DIAS = 62


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _fecha(valor, campo: str = "La fecha") -> date:
    try:
        return date.fromisoformat((valor or "").strip()[:10])
    except ValueError:
        raise ValueError(f"{campo}: indica una fecha válida (AAAA-MM-DD).") from None


def _hora(valor, campo: str) -> str:
    v = (valor or "").strip()
    try:
        h, m = v.split(":")
        if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59 and len(m) == 2):
            raise ValueError
    except ValueError:
        raise ValueError(f"{campo}: indica una hora válida (HH:MM).") from None
    return f"{int(h):02d}:{m}"


def horas_del_turno(inicio: str, fin: str) -> float:
    """Duración en horas (un turno de noche que cruza la medianoche suma las 24 h que corresponden)."""
    a = int(inicio[:2]) * 60 + int(inicio[3:5])
    b = int(fin[:2]) * 60 + int(fin[3:5])
    return round(((b - a) % (24 * 60) or 24 * 60) / 60, 2)


# --- Tipos de turno -----------------------------------------------------------------------------------------------------------------------------
def listar_tipos(tenant_id: int, incluir_archivados: bool = False) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute(f"SELECT * FROM turnos_tipos WHERE tenant_id = ? {'' if incluir_archivados else 'AND archivado = 0'} ORDER BY inicio, nombre", (tenant_id,)).fetchall()
    finally:
        conn.close()
    return [dict(f) | {"horas": horas_del_turno(f["inicio"], f["fin"])} for f in filas]


def crear_tipo(tenant_id: int, gestor_id: int, nombre: str, inicio: str, fin: str, color: str | None = None) -> int:
    _exigir_gestor(gestor_id, tenant_id)
    nombre = (nombre or "").strip()[:60]
    if not nombre:
        raise ValueError("Ponle un nombre al turno.")
    ini, fi = _hora(inicio, "Inicio"), _hora(fin, "Fin")
    if ini == fi:
        raise ValueError("El turno no puede empezar y acabar a la misma hora.")
    color = color if color and len(color) == 7 and color.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in color[1:]) else "#6c8cff"
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM turnos_tipos WHERE tenant_id = ? AND archivado = 0 AND lower(nombre) = lower(?)", (tenant_id, nombre)).fetchone():
            raise ValueError("Ya hay un turno con ese nombre.")
        cur = conn.execute("INSERT INTO turnos_tipos (tenant_id, nombre, inicio, fin, color, creado_en) VALUES (?, ?, ?, ?, ?, ?)", (tenant_id, nombre, ini, fi, color, db.now_iso()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def archivar_tipo(tenant_id: int, gestor_id: int, turno_id: int) -> None:
    """El turno deja de poder asignarse; los días ya asignados lo conservan. Los futuros se quitan para no dejar gente con un turno que ya no existe."""
    _exigir_gestor(gestor_id, tenant_id)
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE turnos_tipos SET archivado = 1 WHERE id = ? AND tenant_id = ?", (turno_id, tenant_id))
        if cur.rowcount == 0:
            raise ValueError("No existe ese turno.")
        conn.execute("DELETE FROM turnos_asignados WHERE turno_id = ? AND tenant_id = ? AND fecha >= ?", (turno_id, tenant_id, date.today().isoformat()))
        conn.commit()
    finally:
        conn.close()


def _exigir_gestor(usuario_id: int, tenant_id: int) -> None:
    from . import ausencias
    if not ausencias.puede_gestionar(usuario_id, tenant_id):
        raise ValueError("Solo quien gestiona el fichaje puede organizar los turnos.")


# --- Asignar ---------------------------------------------------------------------------------------------------------------------------------------
def _aviso(usuario_id: int, cuerpo: str) -> None:
    try:
        from . import notificaciones
        notificaciones.crear_y_enviar(usuario_id, "turno", "Tu cuadrante ha cambiado", cuerpo, url="/fichaje/turnos", datos={"tipo": "turno"})
    except Exception:  # noqa: BLE001
        pass


def _ausente(conn, usuario_id: int, dia: str):
    return conn.execute("SELECT tipo FROM ausencias WHERE usuario_id = ? AND estado = 'aprobada' AND desde <= ? AND hasta >= ? LIMIT 1", (usuario_id, dia, dia)).fetchone()


def _poner(conn, tenant_id: int, gestor_id: int, usuario_id: int, dia: date, turno_id: int | None) -> str | None:
    """Asigna (o quita) un turno en una conexión abierta. Devuelve un texto de lo ocurrido, o None si no cambió nada."""
    iso = dia.isoformat()
    previo = conn.execute("SELECT turno_id FROM turnos_asignados WHERE usuario_id = ? AND fecha = ?", (usuario_id, iso)).fetchone()
    if turno_id is None:
        if previo is None:
            return None
        conn.execute("DELETE FROM turnos_asignados WHERE usuario_id = ? AND fecha = ?", (usuario_id, iso))
        return f"{DIAS_CORTOS[dia.weekday()]} {dia.day}/{dia.month}: sin turno"
    t = conn.execute("SELECT * FROM turnos_tipos WHERE id = ? AND tenant_id = ? AND archivado = 0", (turno_id, tenant_id)).fetchone()
    if t is None:
        raise ValueError("Ese turno no existe o está archivado.")
    if previo is not None and previo["turno_id"] == turno_id:
        return None
    aus = _ausente(conn, usuario_id, iso)
    if aus is not None:
        raise ValueError(f"No se puede asignar turno el {iso}: esa persona tiene una ausencia aprobada ({aus['tipo']}).")
    conn.execute("INSERT INTO turnos_asignados (tenant_id, usuario_id, fecha, turno_id, asignado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?) "
                 "ON CONFLICT(usuario_id, fecha) DO UPDATE SET turno_id = excluded.turno_id, asignado_por = excluded.asignado_por, creado_en = excluded.creado_en",
                 (tenant_id, usuario_id, iso, turno_id, gestor_id, db.now_iso()))
    return f"{DIAS_CORTOS[dia.weekday()]} {dia.day}/{dia.month}: {t['nombre']} {t['inicio']}–{t['fin']}"


def asignar(tenant_id: int, gestor_id: int, usuario_id: int, dia, turno_id: int | None) -> bool:
    """Asigna el turno (o lo quita con `None`) a una persona un día. Devuelve si algo cambió; avisa a la persona."""
    _exigir_gestor(gestor_id, tenant_id)
    d = _fecha(dia)
    conn = db.get_connection()
    try:
        nucleo._usuario_de_tenant(conn, usuario_id, tenant_id)
        texto = _poner(conn, tenant_id, gestor_id, usuario_id, d, turno_id)
        conn.commit()
    finally:
        conn.close()
    if texto and usuario_id != gestor_id:
        _aviso(usuario_id, texto)
    return texto is not None


def asignar_semana(tenant_id: int, gestor_id: int, usuario_id: int, lunes, turnos_por_dia: dict[str, int | None]) -> int:
    """Fija de una vez los siete días de una semana de una persona (`{fecha: turno_id | None}`). Todo o nada; un solo aviso con lo cambiado."""
    _exigir_gestor(gestor_id, tenant_id)
    inicio = _fecha(lunes)
    cambios = []
    conn = db.get_connection()
    try:
        nucleo._usuario_de_tenant(conn, usuario_id, tenant_id)
        for i in range(7):
            d = inicio + timedelta(days=i)
            if d.isoformat() in turnos_por_dia:
                t = _poner(conn, tenant_id, gestor_id, usuario_id, d, turnos_por_dia[d.isoformat()])
                if t:
                    cambios.append(t)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if cambios and usuario_id != gestor_id:
        _aviso(usuario_id, "; ".join(cambios[:7]))
    return len(cambios)


def copiar_semana(tenant_id: int, gestor_id: int, desde_lunes, a_lunes, sobrescribir: bool = False) -> int:
    """Copia el cuadrante de toda la plantilla de una semana a otra. Respeta ausencias (esos días se saltan) y, salvo `sobrescribir`, lo ya asignado."""
    _exigir_gestor(gestor_id, tenant_id)
    origen, destino = _fecha(desde_lunes), _fecha(a_lunes)
    if origen.weekday() != 0 or destino.weekday() != 0:
        raise ValueError("Elige lunes como primer día de cada semana.")
    if origen == destino:
        raise ValueError("Elige dos semanas distintas.")
    n = 0
    avisos: dict[int, list[str]] = {}
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT usuario_id, fecha, turno_id FROM turnos_asignados WHERE tenant_id = ? AND fecha >= ? AND fecha <= ?",
                             (tenant_id, origen.isoformat(), (origen + timedelta(days=6)).isoformat())).fetchall()
        for f in filas:
            d = destino + (date.fromisoformat(f["fecha"]) - origen)
            if not sobrescribir and conn.execute("SELECT 1 FROM turnos_asignados WHERE usuario_id = ? AND fecha = ?", (f["usuario_id"], d.isoformat())).fetchone():
                continue
            try:
                t = _poner(conn, tenant_id, gestor_id, f["usuario_id"], d, f["turno_id"])
            except ValueError:
                continue                               # ausente ese día o turno archivado: se salta
            if t:
                n += 1
                avisos.setdefault(f["usuario_id"], []).append(t)
        conn.commit()
    finally:
        conn.close()
    for uid, lineas in avisos.items():
        if uid != gestor_id:
            _aviso(uid, "; ".join(lineas[:7]))
    return n


def liberar(usuario_id: int, desde: str, hasta: str) -> int:
    """Quita los turnos de una persona en un rango (lo llama `ausencias` al aprobar o registrar una ausencia). Devuelve cuántos quitó."""
    conn = db.get_connection()
    try:
        cur = conn.execute("DELETE FROM turnos_asignados WHERE usuario_id = ? AND fecha >= ? AND fecha <= ?", (usuario_id, desde, hasta))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# --- Consultas ------------------------------------------------------------------------------------------------------------------------------------
def _rango(desde, hasta) -> tuple[date, date]:
    d = _fecha(desde, "Desde")
    h = _fecha(hasta or desde, "Hasta")
    if h < d:
        raise ValueError("La fecha de fin no puede ser anterior a la de inicio.")
    if (h - d).days > MAX_RANGO_DIAS:
        raise ValueError(f"Pide como mucho {MAX_RANGO_DIAS} días de una vez.")
    return d, h


def mis_turnos(tenant_id: int, usuario_id: int, desde, hasta=None) -> list[dict]:
    d, h = _rango(desde, hasta)
    conn = db.get_connection()
    try:
        filas = conn.execute(
            "SELECT a.fecha, t.id AS turno_id, t.nombre, t.inicio, t.fin, t.color FROM turnos_asignados a JOIN turnos_tipos t ON t.id = a.turno_id "
            "WHERE a.tenant_id = ? AND a.usuario_id = ? AND a.fecha >= ? AND a.fecha <= ? ORDER BY a.fecha", (tenant_id, usuario_id, d.isoformat(), h.isoformat())).fetchall()
    finally:
        conn.close()
    return [dict(f) | {"horas": horas_del_turno(f["inicio"], f["fin"])} for f in filas]


def cuadrante(tenant_id: int, desde, hasta=None) -> dict:
    """Quién trabaja qué cada día del rango, para todo el despacho: `{"dias": [...], "personas": [{usuario_id, nombre, dias: {fecha: {...}}}]}`.
    Cada celda es un turno (`turno_id`, `nombre`, `inicio`, `fin`, `color`), una ausencia (`ausencia`) o está vacía."""
    d, h = _rango(desde, hasta)
    dias = [(d + timedelta(days=i)).isoformat() for i in range((h - d).days + 1)]
    conn = db.get_connection()
    try:
        turnos = conn.execute(
            "SELECT a.usuario_id, a.fecha, t.id AS turno_id, t.nombre, t.inicio, t.fin, t.color FROM turnos_asignados a JOIN turnos_tipos t ON t.id = a.turno_id "
            "WHERE a.tenant_id = ? AND a.fecha >= ? AND a.fecha <= ?", (tenant_id, dias[0], dias[-1])).fetchall()
        aus = conn.execute("SELECT usuario_id, tipo, desde, hasta FROM ausencias WHERE tenant_id = ? AND estado = 'aprobada' AND desde <= ? AND hasta >= ?", (tenant_id, dias[-1], dias[0])).fetchall()
    finally:
        conn.close()
    personas = {e["id"]: {"usuario_id": e["id"], "nombre": e["nombre"], "dias": {}} for e in nucleo.equipo(tenant_id)}
    for a in aus:
        if a["usuario_id"] in personas:
            for dia in dias:
                if a["desde"] <= dia <= a["hasta"]:
                    personas[a["usuario_id"]]["dias"][dia] = {"ausencia": a["tipo"]}
    for t in turnos:
        if t["usuario_id"] in personas and "ausencia" not in personas[t["usuario_id"]]["dias"].get(t["fecha"], {}):
            personas[t["usuario_id"]]["dias"][t["fecha"]] = {k: t[k] for k in ("turno_id", "nombre", "inicio", "fin", "color")}
    return {"dias": dias, "personas": list(personas.values())}


def lunes_de(dia: date) -> date:
    return dia - timedelta(days=dia.weekday())
