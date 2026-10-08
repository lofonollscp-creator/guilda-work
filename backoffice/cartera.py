"""Cartera de clientes de Guilda: puntuación de salud por tenant, histórico de
ingresos (snapshots diarios), alertas semanales y tareas periódicas del
backoffice. Todo lo que lee de registro.db es de solo lectura; lo que escribe
va a la base propia del backoffice."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from app import db as plataforma

from . import auth, dependencias, metricas
from .datos import ESTADOS_RIESGO

ESTADOS_RIESGO_PAGO = ESTADOS_RIESGO

# --- Puntuación de salud -----------------------------------------------------------------

NIVELES = (("sano", 70, "Sano"), ("atencion", 40, "Atención"), ("riesgo", 0, "En riesgo"))


def _nivel(puntos: int) -> tuple[str, str]:
    for clave, minimo, etiqueta in NIVELES:
        if puntos >= minimo:
            return clave, etiqueta
    return "riesgo", "En riesgo"


def puntuacion_tenant(tenant_id: int, act: dict | None = None) -> dict:
    """0-100 a partir de cuatro señales: actividad reciente (30), usuarios que
    entran (25), adopción de funciones (20) y estado del pago (25). Un tenant
    suspendido puntúa 0 y uno sin usuarios todavía no se puntúa («nuevo»)."""
    t = plataforma.obtener_tenant(tenant_id)
    act = act or metricas.actividad_tenant(tenant_id, [])
    if not t["activo"]:
        return {"puntos": 0, "nivel": "riesgo", "etiqueta": "Suspendido", "factores": [], "motivos": ["Tenant suspendido"]}
    n_usuarios = act["usuarios"]["n"]
    if n_usuarios == 0:
        return {"puntos": None, "nivel": "nuevo", "etiqueta": "Nuevo", "factores": [], "motivos": ["Todavía no tiene usuarios"]}

    factores, motivos = [], []

    dias = act["inactivo_dias"]
    if dias is None:
        pts_act = 0
        motivos.append("Nunca se ha usado")
    else:
        pts_act = 30 if dias <= 3 else 24 if dias <= 7 else 16 if dias <= 14 else 8 if dias <= 30 else 0
        if dias > 14:
            motivos.append(f"Sin actividad desde hace {dias} días")
    factores.append(("Actividad reciente", pts_act, 30, "sin actividad" if dias is None else f"hace {dias} d"))

    entran = plataforma_usuarios_con_acceso(tenant_id, 14)
    proxy = min(act["usuarios"]["activos_30"], n_usuarios)
    con_uso = max(entran, proxy)
    pts_usr = round(25 * con_uso / n_usuarios)
    factores.append(("Usuarios que entran", pts_usr, 25, f"{con_uso} de {n_usuarios}"))
    if con_uso == 0:
        motivos.append("Ningún usuario ha entrado en 14 días")

    en_uso = sum(1 for f in act["funciones"] if f["estado"] == "en uso")
    pts_fun = round(20 * min(en_uso, 5) / 5)
    factores.append(("Funciones en uso", pts_fun, 20, f"{en_uso} de {len(act['funciones'])}"))
    if en_uso <= 1:
        motivos.append("Usa muy pocas funciones")

    estado = t["suscripcion_estado"] if "suscripcion_estado" in t.keys() else None
    if estado in ESTADOS_RIESGO_PAGO:
        pts_pago, det = 0, "pago fallido"
        motivos.append("Pago fallido")
    elif estado == "activa":
        pts_pago, det = 25, "suscripción activa"
    elif act["pagos"]["ultimo_pago"]:
        pts_pago, det = 15, "pagos puntuales"
    elif t["plan_id"]:
        pts_pago, det = 8, "plan sin suscripción"
        motivos.append("Tiene plan pero no suscripción")
    else:
        pts_pago, det = 5, "sin plan"
    factores.append(("Pago", pts_pago, 25, det))

    puntos = pts_act + pts_usr + pts_fun + pts_pago
    clave, etiqueta = _nivel(puntos)
    return {"puntos": puntos, "nivel": clave, "etiqueta": etiqueta, "factores": factores, "motivos": motivos}


def plataforma_usuarios_con_acceso(tenant_id: int, dias: int) -> int:
    """Usuarios del tenant con `ultimo_acceso` en los últimos `dias` (0 si la
    columna todavía no existe: el backoffice puede arrancar antes que la app)."""
    conn = plataforma.get_connection()
    try:
        if "ultimo_acceso" not in {f[1] for f in conn.execute("PRAGMA table_info(usuarios)")}:
            return 0
        limite = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
        return conn.execute(
            "SELECT COUNT(*) FROM usuarios WHERE tenant_id = ? AND ultimo_acceso >= ?", (tenant_id, limite)
        ).fetchone()[0]
    finally:
        conn.close()


def cartera() -> dict:
    """Puntuación de todos los tenants, de peor a mejor, y recuento por nivel."""
    conn = plataforma.get_connection()
    try:
        tenants = [dict(f) for f in conn.execute("SELECT id, nombre FROM tenants ORDER BY nombre")]
    finally:
        conn.close()
    filas = []
    for t in tenants:
        p = puntuacion_tenant(t["id"])
        filas.append({**t, **p})
    orden = {"riesgo": 0, "atencion": 1, "sano": 2, "nuevo": 3}
    filas.sort(key=lambda f: (orden[f["nivel"]], f["puntos"] if f["puntos"] is not None else 101, f["nombre"].lower()))
    cuenta = {n: sum(1 for f in filas if f["nivel"] == n) for n in ("sano", "atencion", "riesgo", "nuevo")}
    return {"filas": filas, "cuenta": cuenta}


# --- Histórico de ingresos (snapshots diarios) --------------------------------------------

def tomar_snapshot(dia: date | None = None) -> bool:
    """Guarda cómo está cada tenant hoy (plan, precio, estado). Idempotente por día.
    Devuelve True si ha escrito algo nuevo."""
    dia = (dia or date.today()).isoformat()
    conn = plataforma.get_connection()
    try:
        filas = conn.execute(
            "SELECT t.id, t.plan_id, COALESCE(p.precio_mensual_centimos, 0) AS precio, t.activo, t.suscripcion_estado "
            "FROM tenants t LEFT JOIN planes_guilda p ON p.id = t.plan_id"
        ).fetchall()
    finally:
        conn.close()
    bo = auth.conectar()
    try:
        if bo.execute("SELECT 1 FROM snapshots_tenants WHERE fecha = ? LIMIT 1", (dia,)).fetchone():
            return False
        bo.executemany(
            "INSERT INTO snapshots_tenants (fecha, tenant_id, plan_id, precio_centimos, activo, suscripcion_estado) VALUES (?, ?, ?, ?, ?, ?)",
            [(dia, f["id"], f["plan_id"], f["precio"], f["activo"], f["suscripcion_estado"]) for f in filas],
        )
        bo.commit()
        return True
    finally:
        bo.close()


def _paga(f) -> bool:
    return bool(f["activo"]) and f["suscripcion_estado"] == "activa" and f["precio_centimos"] > 0


def _snapshots() -> dict[str, dict[int, dict]]:
    bo = auth.conectar()
    try:
        out: dict[str, dict[int, dict]] = {}
        for f in bo.execute("SELECT * FROM snapshots_tenants ORDER BY fecha"):
            out.setdefault(f["fecha"], {})[f["tenant_id"]] = dict(f)
        return out
    finally:
        bo.close()


def historial_ingresos(meses: int = 12) -> dict:
    """MRR por mes (último snapshot de cada mes) y movimientos entre snapshots
    consecutivos: altas, bajas (con motivo) y cambios de plan."""
    snaps = _snapshots()
    fechas = sorted(snaps)
    if not fechas:
        return {"meses": [], "eventos": [], "desde": None, "resumen_mes": None}
    por_mes: dict[str, str] = {}
    for f in fechas:
        por_mes[f[:7]] = f
    serie = []
    for mes, f in sorted(por_mes.items())[-meses:]:
        pagan = [s for s in snaps[f].values() if _paga(s)]
        serie.append({"mes": mes, "fecha": f, "mrr": sum(s["precio_centimos"] for s in pagan), "pagan": len(pagan), "tenants": len(snaps[f])})
    nombres = {t["id"]: t["nombre"] for t in plataforma.listar_tenants()}
    eventos = []
    for anterior, actual in zip(fechas, fechas[1:]):
        for tid, ahora in snaps[actual].items():
            antes = snaps[anterior].get(tid)
            nombre = nombres.get(tid, f"Tenant {tid}")
            if antes is None:
                eventos.append({"fecha": actual, "tipo": "nuevo", "tenant": nombre, "tenant_id": tid, "delta": 0, "detalle": "Tenant nuevo"})
                continue
            pa, pn = _paga(antes), _paga(ahora)
            if not pa and pn:
                eventos.append({"fecha": actual, "tipo": "alta", "tenant": nombre, "tenant_id": tid, "delta": ahora["precio_centimos"], "detalle": "Empieza a pagar"})
            elif pa and not pn:
                motivo = "suspendido" if not ahora["activo"] else ("pago fallido" if ahora["suscripcion_estado"] in ESTADOS_RIESGO_PAGO else "cancela la suscripción")
                eventos.append({"fecha": actual, "tipo": "baja", "tenant": nombre, "tenant_id": tid, "delta": -antes["precio_centimos"], "detalle": motivo})
            elif pa and pn and antes["plan_id"] != ahora["plan_id"]:
                d = ahora["precio_centimos"] - antes["precio_centimos"]
                eventos.append({"fecha": actual, "tipo": "mejora" if d > 0 else "reduccion" if d < 0 else "cambio", "tenant": nombre,
                                "tenant_id": tid, "delta": d, "detalle": "Cambia de plan"})
    eventos.sort(key=lambda e: e["fecha"], reverse=True)
    mes_actual = date.today().strftime("%Y-%m")
    del_mes = [e for e in eventos if e["fecha"][:7] == mes_actual]
    resumen = {
        "altas": sum(1 for e in del_mes if e["tipo"] == "alta"), "bajas": sum(1 for e in del_mes if e["tipo"] == "baja"),
        "cambios": sum(1 for e in del_mes if e["tipo"] in ("mejora", "reduccion", "cambio")),
        "mrr_neto": sum(e["delta"] for e in del_mes),
    }
    return {"meses": serie, "eventos": eventos[:60], "desde": fechas[0], "resumen_mes": resumen}


# --- Alertas semanales ------------------------------------------------------------------------

def construir_resumen(ahora: datetime | None = None) -> dict:
    """Lo que merece atención esta semana, listo para mostrar o enviar."""
    ahora = ahora or datetime.now()
    from . import seguimiento

    c = cartera()
    en_seguimiento = seguimiento.silenciados(ahora)
    riesgo = [f for f in c["filas"] if f["nivel"] == "riesgo" and f["id"] not in en_seguimiento]
    atencion = [f for f in c["filas"] if f["nivel"] == "atencion" and f["id"] not in en_seguimiento]
    silenciados = [{**f, "hasta": en_seguimiento[f["id"]]} for f in c["filas"] if f["id"] in en_seguimiento and f["nivel"] in ("riesgo", "atencion")]
    conn = plataforma.get_connection()
    try:
        errores_correo = conn.execute(
            "SELECT COUNT(*) FROM correo_cuentas WHERE ultimo_error_sincronizacion IS NOT NULL AND ultimo_error_sincronizacion != ''"
        ).fetchone()[0]
        desde = (ahora - timedelta(days=7)).isoformat(timespec="seconds")
        webhooks = conn.execute(
            "SELECT COUNT(*) FROM webhooks_entregas WHERE entregado_en >= ? AND NOT (estado_http IS NOT NULL AND estado_http BETWEEN 200 AND 299)",
            (desde,),
        ).fetchone()[0]
        pagos_fallidos = [dict(f) for f in conn.execute(
            f"SELECT id, nombre FROM tenants WHERE suscripcion_estado IN ({','.join('?' * len(ESTADOS_RIESGO_PAGO))})", ESTADOS_RIESGO_PAGO)]
    finally:
        conn.close()
    bo = auth.conectar()
    try:
        limite = (ahora - timedelta(days=3)).isoformat(timespec="seconds")
        cobros = [dict(f) for f in bo.execute(
            "SELECT tenant_id, concepto, importe_centimos, creado_en FROM cobros WHERE estado = 'pendiente' AND creado_en < ? ORDER BY creado_en", (limite,))]
    finally:
        bo.close()
    nombres = {t["id"]: t["nombre"] for t in plataforma.listar_tenants()}
    for cobro in cobros:
        cobro["tenant"] = nombres.get(cobro["tenant_id"], "?")
    hist = historial_ingresos()
    return {
        "generado": ahora.isoformat(timespec="seconds"), "cartera": c["cuenta"], "riesgo": riesgo, "atencion": atencion,
        "en_seguimiento": silenciados, "pagos_fallidos": pagos_fallidos, "cobros_pendientes": cobros, "errores_correo": errores_correo,
        "webhooks_fallidos_7d": webhooks, "mes": hist["resumen_mes"],
        "dependencias": dependencias.ultima(),
    }


def _euros(centimos: int) -> str:
    texto = f"{abs(centimos) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if centimos < 0 else "") + texto + " €"


def texto_resumen(r: dict) -> str:
    c = r["cartera"]
    lineas = [
        "Resumen semanal de Guilda Work", "",
        f"Cartera: {c['sano']} sanos, {c['atencion']} con atención, {c['riesgo']} en riesgo, {c['nuevo']} nuevos.", "",
    ]
    if r["riesgo"]:
        lineas.append("TENANTS EN RIESGO")
        for f in r["riesgo"]:
            lineas.append(f"- {f['nombre']} ({f['puntos'] if f['puntos'] is not None else '—'}/100): " + "; ".join(f["motivos"]))
        lineas.append("")
    if r.get("en_seguimiento"):
        lineas.append("En seguimiento (no se insiste hasta la fecha): " + ", ".join(
            f"{f['nombre']} ({f['hasta'][:10]})" for f in r["en_seguimiento"]))
        lineas.append("")
    if r["atencion"]:
        lineas.append("Piden atención: " + ", ".join(f"{f['nombre']} ({f['puntos']})" for f in r["atencion"]))
        lineas.append("")
    if r["pagos_fallidos"]:
        lineas.append("PAGOS FALLIDOS: " + ", ".join(p["nombre"] for p in r["pagos_fallidos"]))
    if r["cobros_pendientes"]:
        lineas.append("COBROS SIN PAGAR (más de 3 días):")
        for k in r["cobros_pendientes"]:
            lineas.append(f"- {k['tenant']}: {k['concepto']} · {_euros(k['importe_centimos'])} · desde {k['creado_en'][:10]}")
    if r["errores_correo"]:
        lineas.append(f"Cuentas de correo con error de sincronización: {r['errores_correo']}")
    if r["webhooks_fallidos_7d"]:
        lineas.append(f"Entregas de webhooks fallidas (7 días): {r['webhooks_fallidos_7d']}")
    dep = r.get("dependencias")
    if dep and dep.get("vulnerables"):
        lineas.append("DEPENDENCIAS CON VULNERABILIDADES: " + ", ".join(f"{v['paquete']} {v['version']}" for v in dep["vulnerables"][:10]))
    m = r["mes"]
    if m:
        lineas += ["", f"Este mes: {m['altas']} altas, {m['bajas']} bajas, {m['cambios']} cambios de plan · MRR neto {_euros(m['mrr_neto'])}"]
    if len(lineas) <= 4 and not r["riesgo"]:
        lineas.append("Sin incidencias esta semana.")
    return "\n".join(lineas) + "\n"


def enviar_resumen(r: dict | None = None) -> None:
    """Manda el resumen a ALERTAS_ADMIN_EMAIL. Lanza si el correo no está configurado."""
    from app import notificaciones_email

    r = r or construir_resumen()
    notificaciones_email.enviar_alerta_interna(
        f"Guilda Work · resumen semanal ({r['cartera']['riesgo']} en riesgo)", texto_resumen(r),
    )


def _clave_semana(ahora: datetime) -> str:
    anio, semana, _ = ahora.isocalendar()
    return f"resumen-{anio}-W{semana:02d}"


def resumen_semanal_si_toca(ahora: datetime | None = None, hora_minima: int = 8, enviar=None) -> bool:
    """Lunes a partir de las 8:00 y una sola vez por semana (aunque el servicio se reinicie)."""
    ahora = ahora or datetime.now()
    if ahora.weekday() != 0 or ahora.hour < hora_minima:
        return False
    clave = _clave_semana(ahora)
    bo = auth.conectar()
    try:
        if bo.execute("SELECT 1 FROM resumenes_enviados WHERE clave = ?", (clave,)).fetchone():
            return False
        bo.execute("INSERT INTO resumenes_enviados (clave, enviado_en) VALUES (?, ?)", (clave, auth._ahora()))
        bo.commit()  # se reserva antes de enviar: si falla el envío no se reintenta cada 10 minutos
    finally:
        bo.close()
    (enviar or enviar_resumen)()
    return True


# --- Cobros pendientes ---------------------------------------------------------------------------

def refrescar_cobros_pendientes(max_dias: int = 14) -> int:
    """Consulta a Stripe el estado de los cobros puntuales aún pendientes. Devuelve
    cuántos han cambiado. Un fallo con un cobro no impide revisar el resto."""
    from . import facturacion

    if not facturacion.configurado():
        return 0
    limite = (datetime.now() - timedelta(days=max_dias)).isoformat(timespec="seconds")
    bo = auth.conectar()
    try:
        pendientes = [(f["tenant_id"], f["id"]) for f in bo.execute(
            "SELECT id, tenant_id FROM cobros WHERE estado = 'pendiente' AND creado_en >= ?", (limite,))]
    finally:
        bo.close()
    cambiados = 0
    for tenant_id, cobro_id in pendientes:
        try:
            if facturacion.refrescar_cobro(tenant_id, cobro_id) != "pendiente":
                cambiados += 1
        except Exception:  # noqa: BLE001
            continue
    return cambiados


# --- Vigilancia desde fuera de la app principal --------------------------------------------------
# El vigilante de salud de la app vive en el MISMO proceso que las tareas que vigila: si ese
# proceso se cuelga o se cae, nadie avisa. El backoffice es otro proceso, así que repasa los
# latidos y comprueba que la app responde.

FALLOS_SONDA_PARA_AVISAR = 2
_fallos_sonda = 0


def sonda_app() -> bool:
    """¿Responde la app principal por HTTP en local? (cualquier respuesta cuenta: es una sonda de vida)."""
    import os
    import urllib.error
    import urllib.request

    url = f"http://127.0.0.1:{os.environ.get('GUILDA_PORT', '8000')}/"
    try:
        with urllib.request.urlopen(url, timeout=8):
            return True
    except urllib.error.HTTPError:
        return True  # contesta (aunque sea con un error): el proceso está vivo
    except (urllib.error.URLError, OSError):
        return False


def vigilar_app(ahora: datetime | None = None, sonda=None, enviar=None) -> list[str]:
    """Latidos atrasados (por correo, una vez al día por motivo, vía salud.vigilar) y sonda de la app.
    Devuelve los motivos avisados."""
    global _fallos_sonda
    from app import notificaciones_email, salud

    ahora = ahora or datetime.now()
    avisados = list(salud.vigilar(ahora))
    if (sonda or sonda_app)():
        _fallos_sonda = 0
        return avisados
    _fallos_sonda += 1
    dia = ahora.strftime("%Y-%m-%d")
    if _fallos_sonda >= FALLOS_SONDA_PARA_AVISAR and not plataforma.alerta_salud_enviada("app_caida", dia):
        (enviar or notificaciones_email.enviar_alerta_interna)(
            "[Guilda Work] la app no responde",
            f"El backoffice no consigue hablar con la app principal desde hace {_fallos_sonda} comprobaciones seguidas "
            f"({_fallos_sonda * INTERVALO_SEGUNDOS // 60} min o más). Revisa: systemctl status guilda-work.service\n",
        )
        plataforma.marcar_alerta_salud("app_caida", dia)
        avisados.append("app_caida")
    return avisados


# --- Tareas periódicas del proceso del backoffice --------------------------------------------------

INTERVALO_SEGUNDOS = 600


def _historial_salud(ahora: datetime) -> bool:
    from . import seguimiento    # import perezoso: seguimiento.py usa este módulo

    return seguimiento.tomar_historial(ahora.date())


def paso_periodico(ahora: datetime | None = None, enviar=None) -> dict:
    """Una pasada: snapshot del día, estado de cobros y resumen semanal. Cada parte
    es independiente: un fallo no impide las demás, y el resultado queda como latido."""
    from app import salud

    ahora = ahora or datetime.now()
    resultado, errores = {}, []
    for nombre, fn in (
        ("snapshot", lambda: tomar_snapshot(ahora.date())),
        ("salud", lambda: _historial_salud(ahora)),
        ("cobros", refrescar_cobros_pendientes),
        ("resumen", lambda: resumen_semanal_si_toca(ahora, enviar=enviar)),
        ("vigilancia", lambda: vigilar_app(ahora)),
        ("dependencias", lambda: dependencias.auditar_si_toca(ahora)),
    ):
        try:
            resultado[nombre] = fn()
        except Exception as e:  # noqa: BLE001
            errores.append(f"{nombre}: {e}")
    if errores:
        salud.registrar_error("backoffice_tareas", INTERVALO_SEGUNDOS * 3, "; ".join(errores))
    else:
        salud.registrar_ok("backoffice_tareas", INTERVALO_SEGUNDOS * 3, minimo_segundos=300)
    resultado["errores"] = errores
    return resultado


def iniciar_hilo() -> None:
    import logging
    import threading
    import time

    def bucle():
        while True:
            try:
                paso_periodico()
            except Exception:  # noqa: BLE001
                logging.getLogger(__name__).exception("Fallo en las tareas periódicas del backoffice")
            time.sleep(INTERVALO_SEGUNDOS)

    threading.Thread(target=bucle, name="backoffice-tareas", daemon=True).start()
