"""Seguimiento de la salud de los clientes: evolución de la puntuación (histórico diario), tendencia de uso
(últimas dos semanas frente a las dos anteriores), siguiente paso sugerido y registro de contactos.
La puntuación en sí vive en cartera.py; aquí solo se mira cómo cambia y qué hacer con ella. Lo que lee de
registro.db es de solo lectura; lo que escribe va a la base propia del backoffice."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from app import db as plataforma

from . import auth, cartera, metricas

VENTANA_TENDENCIA_DIAS = 14
CAIDA_RELEVANTE = -30            # % de variación a partir del cual se avisa de que el uso cae
MAX_POSPONER_DIAS = 90


# --- Histórico de puntuaciones -----------------------------------------------------------------

def tomar_historial(dia: date | None = None) -> bool:
    """Guarda la puntuación de hoy de cada tenant. Idempotente por día; True si ha escrito."""
    dia_iso = (dia or date.today()).isoformat()
    bo = auth.conectar()
    try:
        if bo.execute("SELECT 1 FROM salud_historial WHERE fecha = ? LIMIT 1", (dia_iso,)).fetchone():
            return False
    finally:
        bo.close()
    filas = cartera.cartera()["filas"]
    bo = auth.conectar()
    try:
        bo.executemany(
            "INSERT OR IGNORE INTO salud_historial (fecha, tenant_id, puntos, nivel) VALUES (?, ?, ?, ?)",
            [(dia_iso, f["id"], f["puntos"], f["nivel"]) for f in filas],
        )
        bo.commit()
    finally:
        bo.close()
    return bool(filas)


def historial(tenant_id: int, dias: int = 90) -> list[dict]:
    desde = (date.today() - timedelta(days=dias)).isoformat()
    bo = auth.conectar()
    try:
        return [dict(f) for f in bo.execute(
            "SELECT fecha, puntos, nivel FROM salud_historial WHERE tenant_id = ? AND fecha >= ? ORDER BY fecha", (tenant_id, desde))]
    finally:
        bo.close()


def variacion_puntos(puntos_ahora: int | None, serie: list[dict], dias: int = 7, hoy: date | None = None) -> int | None:
    """Puntos de más o de menos frente a la última foto de hace `dias` o más (None si no hay con qué comparar)."""
    if puntos_ahora is None:
        return None
    limite = ((hoy or date.today()) - timedelta(days=dias)).isoformat()
    antes = [f for f in serie if f["fecha"] <= limite and f["puntos"] is not None]
    return puntos_ahora - antes[-1]["puntos"] if antes else None


# --- Tendencia de uso ----------------------------------------------------------------------------

_FUENTES = (
    ("tareas", "COALESCE(fin_en, inicio_en)", "usuario_id", "AND papelera_en IS NULL"),
    ("tareas_outlook", "creada_en", "usuario_id", "AND papelera_en IS NULL"),
    ("notas", "creada_en", "usuario_id", "AND papelera_en IS NULL"),
    ("fichajes", "marca_tiempo", "usuario_id", ""),
    ("correo_envios", "creado_en", "usuario_id", "AND estado = 'enviado'"),
    ("ia_mensajes", "creado_en", "usuario_id", "AND rol = 'user'"),
)


def tendencia_uso(tenant_id: int, ahora: datetime | None = None) -> dict:
    """Acciones de las últimas dos semanas frente a las dos anteriores:
    {'actual', 'anterior', 'variacion'} (variacion en %, None si antes no había nada)."""
    ahora = ahora or datetime.now()
    ids = plataforma.usuarios_de_tenant(tenant_id)
    if not ids:
        return {"actual": 0, "anterior": 0, "variacion": None}
    corte = (ahora - timedelta(days=VENTANA_TENDENCIA_DIAS)).isoformat(timespec="seconds")
    inicio = (ahora - timedelta(days=2 * VENTANA_TENDENCIA_DIAS)).isoformat(timespec="seconds")
    marcas = ",".join("?" * len(ids))
    actual = anterior = 0
    conn = plataforma.get_connection()
    try:
        for tabla, fecha, columna, extra in _FUENTES:
            fila = conn.execute(
                f"""SELECT COALESCE(SUM({fecha} >= ?), 0), COALESCE(SUM({fecha} >= ? AND {fecha} < ?), 0)
                    FROM {tabla} WHERE {columna} IN ({marcas}) {extra} AND {fecha} >= ?""",
                [corte, inicio, corte, *ids, inicio],
            ).fetchone()
            actual += int(fila[0] or 0)
            anterior += int(fila[1] or 0)
    finally:
        conn.close()
    variacion = round((actual - anterior) * 100 / anterior) if anterior else None
    return {"actual": actual, "anterior": anterior, "variacion": variacion}


def cae_el_uso(tendencia: dict) -> bool:
    return tendencia["variacion"] is not None and tendencia["variacion"] <= CAIDA_RELEVANTE


# --- Siguiente paso sugerido -----------------------------------------------------------------

def accion_sugerida(salud: dict, act: dict, tendencia: dict) -> str | None:
    """Una recomendación corta según lo que más pesa, o None si el cliente está bien."""
    if salud["nivel"] == "nuevo":
        return "Ayudarle con la puesta en marcha: invitar a su equipo y crear el primer cliente." if salud["motivos"] else None
    motivos = " ".join(salud.get("motivos", []))
    if "Tenant suspendido" in motivos:
        return "Está suspendido: confirmar si es una baja o reactivarlo."
    if "Pago fallido" in motivos:
        return "Revisar el cobro y escribirle antes de que se enfríe."
    if "Nunca se ha usado" in motivos:
        return "Llamar para una sesión de puesta en marcha: no ha llegado a usar la plataforma."
    if "Sin actividad desde hace" in motivos or "Ningún usuario ha entrado" in motivos:
        return "Contactar: lleva semanas sin usarla. Preguntar si hay algún obstáculo."
    if cae_el_uso(tendencia):
        return f"El uso ha caído un {abs(tendencia['variacion'])} % en dos semanas: preguntar si algo ha cambiado."
    sin_usar = [f["nombre"] for f in act.get("funciones", []) if f["estado"] != "en uso"]
    if "Usa muy pocas funciones" in motivos and sin_usar:
        return "Enseñarle más funciones, por ejemplo: " + ", ".join(sin_usar[:3]) + "."
    if "Tiene plan pero no suscripción" in motivos:
        return "Tiene plan pero no suscripción: ofrecerle activarla."
    return None


# --- Contactos y silencio -----------------------------------------------------------------------

def obtener(tenant_id: int) -> dict:
    bo = auth.conectar()
    try:
        f = bo.execute("SELECT * FROM seguimiento_tenant WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        bo.close()
    return dict(f) if f else {"tenant_id": tenant_id, "ultimo_contacto": None, "posponer_hasta": None}


def silenciado(seg: dict, ahora: datetime | None = None) -> bool:
    hasta = seg.get("posponer_hasta")
    return bool(hasta and hasta > (ahora or datetime.now()).isoformat(timespec="seconds"))


def silenciados(ahora: datetime | None = None) -> dict[int, str]:
    """{tenant_id: hasta cuándo} de los que están en seguimiento ahora mismo."""
    bo = auth.conectar()
    try:
        return {f["tenant_id"]: f["posponer_hasta"] for f in bo.execute(
            "SELECT tenant_id, posponer_hasta FROM seguimiento_tenant WHERE posponer_hasta > ?",
            ((ahora or datetime.now()).isoformat(timespec="seconds"),))}
    finally:
        bo.close()


def _guardar(tenant_id: int, admin: str, **campos) -> None:
    bo = auth.conectar()
    try:
        bo.execute("INSERT OR IGNORE INTO seguimiento_tenant (tenant_id) VALUES (?)", (tenant_id,))
        bo.execute(
            f"UPDATE seguimiento_tenant SET {', '.join(c + ' = ?' for c in campos)}, admin_usuario = ?, actualizado_en = ? WHERE tenant_id = ?",
            [*campos.values(), admin, auth._ahora(), tenant_id],
        )
        bo.commit()
    finally:
        bo.close()


def registrar_contacto(tenant_id: int, texto: str, admin: str, posponer_dias: int = 0) -> None:
    """Anota el contacto como nota interna y lo marca como último contacto; opcionalmente silencia al tenant
    en el resumen semanal durante `posponer_dias` (para no insistir mientras se resuelve)."""
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("Cuenta brevemente qué se habló o se acordó.")
    if not 0 <= posponer_dias <= MAX_POSPONER_DIAS:
        raise ValueError(f"El seguimiento va de 0 a {MAX_POSPONER_DIAS} días.")
    metricas.añadir_nota(tenant_id, "Contacto: " + texto, admin)
    campos = {"ultimo_contacto": auth._ahora()}
    if posponer_dias:
        campos["posponer_hasta"] = (datetime.now() + timedelta(days=posponer_dias)).isoformat(timespec="seconds")
    _guardar(tenant_id, admin, **campos)


def reanudar(tenant_id: int, admin: str) -> None:
    _guardar(tenant_id, admin, posponer_hasta=None)


# --- Lista de clientes por salud -----------------------------------------------------------------

def ranking(nivel: str | None = None, ahora: datetime | None = None) -> dict:
    """Todos los tenants, de peor a mejor, con su puntuación, cómo ha cambiado, la tendencia de uso, el
    último contacto y el siguiente paso sugerido."""
    ahora = ahora or datetime.now()
    conn = plataforma.get_connection()
    try:
        tenants = [dict(f) for f in conn.execute("SELECT id, nombre FROM tenants ORDER BY nombre")]
    finally:
        conn.close()
    bo = auth.conectar()
    try:
        seguimientos = {f["tenant_id"]: dict(f) for f in bo.execute("SELECT * FROM seguimiento_tenant")}
        series: dict[int, list] = {}
        for f in bo.execute("SELECT tenant_id, fecha, puntos, nivel FROM salud_historial WHERE fecha >= ? ORDER BY fecha",
                            ((ahora.date() - timedelta(days=30)).isoformat(),)):
            series.setdefault(f["tenant_id"], []).append(dict(f))
    finally:
        bo.close()
    filas = []
    for t in tenants:
        act = metricas.actividad_tenant(t["id"], [])
        salud = cartera.puntuacion_tenant(t["id"], act)
        tendencia = tendencia_uso(t["id"], ahora)
        seg = seguimientos.get(t["id"], {})
        filas.append({
            **t, **salud, "variacion": variacion_puntos(salud["puntos"], series.get(t["id"], []), 7, ahora.date()),
            "tendencia": tendencia, "ultima": act["ultima"], "ultimo_contacto": seg.get("ultimo_contacto"),
            "silenciado_hasta": seg.get("posponer_hasta") if silenciado(seg, ahora) else None,
            "siguiente": accion_sugerida(salud, act, tendencia),
        })
    orden = {"riesgo": 0, "atencion": 1, "sano": 2, "nuevo": 3}
    filas.sort(key=lambda f: (orden[f["nivel"]], f["puntos"] if f["puntos"] is not None else 101, f["nombre"].lower()))
    cuenta = {n: sum(1 for f in filas if f["nivel"] == n) for n in orden}
    if nivel in orden:
        filas = [f for f in filas if f["nivel"] == nivel]
    return {"filas": filas, "cuenta": cuenta, "filtro": nivel if nivel in orden else None}
