"""Bolsa de horas (PLAN_MAESTRO §7.4): cuántas horas lleva cada persona **a favor o en contra** respecto a su jornada contratada.

    saldo = horas trabajadas (fichaje) + ajustes manuales − horas que tocaba trabajar

- **Qué tocaba**: la jornada semanal contratada (Fichaje › Mis datos) repartida en los días laborables (lunes a viernes sin festivos, como los plazos).
  Las semanas en las que la persona tiene **turnos asignados en el cuadrante** (app/turnos.py) mandan los turnos: cada día se espera la duración de su turno y los días sin turno de esa semana,
  nada (también vale para quien trabaja fines de semana o noches). Las semanas sin cuadrante siguen con la jornada semanal. Sin jornada contratada pero con turnos, también hay bolsa.
  Los días con una **ausencia aprobada** (vacaciones, permiso, baja…) no se esperan; medio día, la mitad.
- **Qué trabajó**: la misma medida que el resumen semanal del fichaje (entrada → salida, tal como se registró; sin tocar el registro horario).
- **Ajustes**: quien gestiona el fichaje puede sumar o restar minutos con un motivo («Compensado con tarde libre», «Horas extra del cierre»), y se avisa a la persona.
- Cuenta días completos: por defecto desde el 1 de enero (o su fecha de alta o su primer fichaje, si son posteriores) **hasta ayer**; el día en curso aún no ha terminado.
- Sin jornada contratada ni turnos no hay bolsa: se muestran las horas trabajadas y se pide rellenar la jornada."""
from __future__ import annotations

from datetime import date, timedelta

from . import db, fichaje_export, nucleo, turnos

ESQUEMA = """
CREATE TABLE IF NOT EXISTS bolsa_horas_ajustes (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    fecha TEXT NOT NULL,
    minutos INTEGER NOT NULL,
    motivo TEXT NOT NULL,
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bolsa_ajustes ON bolsa_horas_ajustes(usuario_id, fecha);
"""

MAX_DIAS = 731
MAX_AJUSTE_MINUTOS = 60 * 200


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _fecha(valor, campo: str) -> date:
    try:
        return date.fromisoformat((valor or "").strip()[:10])
    except ValueError:
        raise ValueError(f"{campo}: indica una fecha válida (AAAA-MM-DD).") from None


def texto_horas(segundos: float | None, con_signo: bool = False) -> str:
    """«3 h 20 min» (o «+3 h 20 min» / «−1 h 05 min» con signo)."""
    if segundos is None:
        return "—"
    minutos = round(abs(segundos) / 60)
    cuerpo = f"{minutos // 60} h {minutos % 60:02d} min"
    if not con_signo:
        return ("−" if segundos < 0 and minutos else "") + cuerpo
    return ("+" if segundos >= 0 or not minutos else "−") + cuerpo if minutos else cuerpo


def _fechas_cubiertas(conn, usuario_id: int, desde: date, hasta: date) -> dict[str, float]:
    """Día → fracción del día que cubre una ausencia aprobada (1 = entero, 0,5 = medio día)."""
    res: dict[str, float] = {}
    for a in conn.execute("SELECT desde, hasta, medio_dia FROM ausencias WHERE usuario_id = ? AND estado = 'aprobada' AND desde <= ? AND hasta >= ?",
                          (usuario_id, hasta.isoformat(), desde.isoformat())):
        d, h = date.fromisoformat(a["desde"]), date.fromisoformat(a["hasta"])
        while d <= h:
            res[d.isoformat()] = max(res.get(d.isoformat(), 0), 0.5 if a["medio_dia"] else 1.0)
            d += timedelta(days=1)
    return res


def _turnos_en(conn, usuario_id: int, desde: date, hasta: date) -> dict[str, float]:
    """Día → horas del turno asignado ese día, para las semanas (lunes a domingo) en las que la persona tiene algún turno dentro del periodo; los días de esas semanas sin turno valen 0."""
    asignados = {f["fecha"]: turnos.horas_del_turno(f["inicio"], f["fin"]) for f in conn.execute(
        "SELECT a.fecha, t.inicio, t.fin FROM turnos_asignados a JOIN turnos_tipos t ON t.id = a.turno_id WHERE a.usuario_id = ? AND a.fecha >= ? AND a.fecha <= ?",
        (usuario_id, desde.isoformat(), hasta.isoformat()))}
    semanas = {turnos.lunes_de(date.fromisoformat(f)) for f in asignados}
    res: dict[str, float] = {}
    for lunes in semanas:
        for i in range(7):
            dia = lunes + timedelta(days=i)
            if desde <= dia <= hasta:
                res[dia.isoformat()] = asignados.get(dia.isoformat(), 0.0)
    return res


def _primer_fichaje(usuario_id: int) -> date | None:
    """El día del primer fichaje de la persona: antes de empezar a fichar no hay bolsa que contar (si no, quien empieza en octubre arrancaría con diez meses «en contra»)."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT MIN(marca_tiempo) AS m FROM fichajes WHERE usuario_id = ?", (usuario_id,)).fetchone()
    finally:
        conn.close()
    return date.fromisoformat(f["m"][:10]) if f and f["m"] else None


def calcular(tenant_id: int, usuario_id: int, desde=None, hasta=None, hoy: date | None = None) -> dict:
    """La bolsa de horas de una persona en un periodo (ver el principio del módulo para el criterio)."""
    hoy = hoy or date.today()
    datos = db.obtener_fichaje_datos(usuario_id)
    jornada = datos["jornada_semanal_horas"] if datos is not None else None
    alta = None
    if datos is not None and datos["fecha_alta"]:
        try:
            alta = date.fromisoformat(datos["fecha_alta"][:10])
        except ValueError:
            alta = None
    d = _fecha(desde, "Desde") if desde else max(date(hoy.year, 1, 1), alta or date(hoy.year, 1, 1), _primer_fichaje(usuario_id) or hoy)
    h = _fecha(hasta, "Hasta") if hasta else hoy - timedelta(days=1)
    if (h - d).days > MAX_DIAS:
        raise ValueError("Pide como mucho dos años de una vez.")
    vacia = {"usuario_id": usuario_id, "desde": d.isoformat(), "hasta": h.isoformat(), "jornada_semanal_horas": jornada, "sin_jornada": not jornada, "dias_laborables": 0,
             "dias_justificados": 0.0, "esperado_seg": 0.0, "trabajado_seg": 0.0, "ajustes_seg": 0.0, "saldo_seg": 0.0 if jornada else None, "por_mes": [], "dias_con_turno": 0}
    if h < d:
        return vacia
    cal = nucleo.calendario_del_despacho(tenant_id, "general", tuple(range(d.year, h.year + 1)))
    por_dia_seg = float(jornada) * 3600 / 5 if jornada else 0.0
    conn = db.get_connection()
    try:
        cubiertas = _fechas_cubiertas(conn, usuario_id, d, h)
        por_turno = _turnos_en(conn, usuario_id, d, h)
        ajustes = conn.execute("SELECT fecha, minutos FROM bolsa_horas_ajustes WHERE usuario_id = ? AND fecha >= ? AND fecha <= ?", (usuario_id, d.isoformat(), h.isoformat())).fetchall()
    finally:
        conn.close()
    con_esperado = bool(jornada) or any(v > 0 for v in por_turno.values())
    meses: dict[str, dict] = {}

    def mes(clave: str) -> dict:
        return meses.setdefault(clave, {"mes": clave, "esperado_seg": 0.0, "trabajado_seg": 0.0, "ajustes_seg": 0.0})
    laborables, justificados, esperado = 0, 0.0, 0.0
    dia = d
    while dia <= h:
        clave = dia.isoformat()
        if clave in por_turno:                       # semana con cuadrante: manda el turno de ese día
            base = por_turno[clave] * 3600
            cuenta = base > 0
        else:
            base = por_dia_seg
            cuenta = cal.es_habil(dia)
        if cuenta:
            laborables += 1
            fraccion = cubiertas.get(clave, 0.0)
            justificados += fraccion
            e = base * (1 - fraccion)
            esperado += e
            mes(clave[:7])["esperado_seg"] += e
        dia += timedelta(days=1)
    trabajado = 0.0
    for f in fichaje_export.filas_diarias(tenant_id, d.isoformat(), h.isoformat(), usuario_id):
        if d.isoformat() <= f["fecha"] <= h.isoformat():
            trabajado += f["segundos_trabajados"]
            mes(f["fecha"][:7])["trabajado_seg"] += f["segundos_trabajados"]
    adj = 0.0
    for a in ajustes:
        adj += a["minutos"] * 60
        mes(a["fecha"][:7])["ajustes_seg"] += a["minutos"] * 60
    for m in meses.values():
        m["saldo_seg"] = (m["trabajado_seg"] + m["ajustes_seg"] - m["esperado_seg"]) if con_esperado else None
    vacia.update(dias_laborables=laborables, dias_justificados=justificados, esperado_seg=esperado, trabajado_seg=trabajado, ajustes_seg=adj, sin_jornada=not con_esperado,
                 saldo_seg=(trabajado + adj - esperado) if con_esperado else None, por_mes=[meses[k] for k in sorted(meses)], dias_con_turno=sum(1 for v in por_turno.values() if v > 0))
    return vacia


# --- Ajustes manuales ---------------------------------------------------------------------------------------------------------------------------
def anadir_ajuste(tenant_id: int, gestor_id: int, usuario_id: int, minutos, motivo: str, fecha=None) -> int:
    from . import ausencias
    if not ausencias.puede_gestionar(gestor_id, tenant_id):
        raise ValueError("Solo quien gestiona el fichaje puede ajustar la bolsa de horas.")
    try:
        minutos = int(round(float(str(minutos).replace(",", "."))))
    except (TypeError, ValueError):
        raise ValueError("Indica los minutos (positivos suman, negativos restan).") from None
    if minutos == 0 or abs(minutos) > MAX_AJUSTE_MINUTOS:
        raise ValueError("El ajuste debe ser distinto de cero y de menos de 200 horas.")
    motivo = (motivo or "").strip()[:300]
    if not motivo:
        raise ValueError("Indica el motivo del ajuste.")
    dia = _fecha(fecha, "Fecha") if fecha else date.today()
    conn = db.get_connection()
    try:
        nucleo._usuario_de_tenant(conn, usuario_id, tenant_id)
        cur = conn.execute("INSERT INTO bolsa_horas_ajustes (tenant_id, usuario_id, fecha, minutos, motivo, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, usuario_id, dia.isoformat(), minutos, motivo, gestor_id, db.now_iso()))
        conn.commit()
        aid = cur.lastrowid
    finally:
        conn.close()
    if usuario_id != gestor_id:
        try:
            from . import notificaciones
            notificaciones.crear_y_enviar(usuario_id, "bolsa_horas", "Ajuste en tu bolsa de horas", f"{texto_horas(minutos * 60, True)} · {motivo}", url="/fichaje/bolsa", datos={"tipo": "bolsa_horas"})
        except Exception:  # noqa: BLE001
            pass
    return aid


def listar_ajustes(tenant_id: int, usuario_id: int, desde=None, hasta=None, limite: int = 100) -> list:
    donde, p = ["a.tenant_id = ?", "a.usuario_id = ?"], [tenant_id, usuario_id]
    if desde:
        donde.append("a.fecha >= ?"); p.append(_fecha(desde, "Desde").isoformat())
    if hasta:
        donde.append("a.fecha <= ?"); p.append(_fecha(hasta, "Hasta").isoformat())
    conn = db.get_connection()
    try:
        return conn.execute(
            "SELECT a.*, COALESCE(NULLIF(pr.nombre_mostrado, ''), u.email) AS creado_por_nombre FROM bolsa_horas_ajustes a LEFT JOIN usuarios u ON u.id = a.creado_por "
            f"LEFT JOIN usuario_perfil pr ON pr.usuario_id = a.creado_por WHERE {' AND '.join(donde)} ORDER BY a.fecha DESC, a.id DESC LIMIT ?", [*p, max(1, min(limite, 500))]).fetchall()
    finally:
        conn.close()


def resumen_equipo(tenant_id: int, desde=None, hasta=None, hoy: date | None = None) -> list[dict]:
    """La bolsa de todo el despacho: primero quien más horas debe, para verlo de un vistazo."""
    res = []
    for e in nucleo.equipo(tenant_id):
        b = calcular(tenant_id, e["id"], desde, hasta, hoy)
        res.append({"usuario_id": e["id"], "nombre": e["nombre"], **{k: b[k] for k in ("sin_jornada", "jornada_semanal_horas", "esperado_seg", "trabajado_seg", "ajustes_seg", "saldo_seg")}})
    return sorted(res, key=lambda r: (r["saldo_seg"] is None, r["saldo_seg"] if r["saldo_seg"] is not None else 0))
