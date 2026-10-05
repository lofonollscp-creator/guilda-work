"""Exportación CSV/PDF/JSON del registro horario -- mismo criterio que
app/export.py: esta tabla (fichajes, ver db.py) no sabe nada de formatos
de salida, aquí solo se da forma a lo que devuelve
db.fichajes_tenant_crudos()."""
import csv
import io
import json
from datetime import datetime, timedelta

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import db


def _fila_vacia(uid: int, fecha_dia: str, f: dict) -> dict:
    return {
        "usuario_id": uid, "fecha": fecha_dia, "email": f["email"],
        "nombre_completo": f["nombre_completo"], "dni_nie": f["dni_nie"],
        "primera_entrada": None, "ultima_salida": None,
        "segundos_trabajados": 0, "segundos_pausa": 0,
    }


def _repartir_segundos(filas: dict, orden: list, f: dict, uid: int, inicio: datetime, fin: datetime, campo: str) -> None:
    """Reparte el intervalo [inicio, fin) entre los días naturales que
    abarca, sumando los segundos correspondientes a filas[(uid, fecha)][campo]
    -- crea la fila del día si no existía todavía (turno que cruza
    medianoche, o dura más de 24h)."""
    cursor = inicio
    while cursor < fin:
        fecha_dia = cursor.strftime("%Y-%m-%d")
        medianoche_siguiente = datetime(cursor.year, cursor.month, cursor.day) + timedelta(days=1)
        limite = min(fin, medianoche_siguiente)
        clave = (uid, fecha_dia)
        if clave not in filas:
            filas[clave] = _fila_vacia(uid, fecha_dia, f)
            orden.append(clave)
        filas[clave][campo] += (limite - cursor).total_seconds()
        cursor = limite


def filas_diarias(tenant_id: int | None, desde: str | None, hasta: str | None, usuario_id: int | None) -> list[dict]:
    """Agrupa los eventos en bruto por trabajador y día -- primera entrada,
    última salida, horas trabajadas y de pausa de ese día. Igual que
    db.resumen_fichajes_tenant() pero por día en vez de por todo el
    periodo, que es lo que hace falta en un registro exportable de
    verdad (no solo el total). Pública (sin "_") porque también la usa
    app/rutas_fichaje.py para agrupar el historial del propio trabajador
    por día con sus totales, no solo la exportación."""
    crudos = db.fichajes_tenant_crudos(tenant_id, desde, hasta, usuario_id)
    filas: dict[tuple, dict] = {}
    orden: list[tuple] = []
    entrada_abierta: dict[int, datetime] = {}
    pausa_abierta: dict[int, datetime] = {}
    for f in crudos:
        uid = f["usuario_id"]
        fecha = f["marca_tiempo"][:10]
        clave = (uid, fecha)
        if clave not in filas:
            filas[clave] = _fila_vacia(uid, fecha, f)
            orden.append(clave)
        fila = filas[clave]
        marca = datetime.fromisoformat(f["marca_tiempo"])
        if f["tipo"] == "entrada":
            entrada_abierta[uid] = marca
            if fila["primera_entrada"] is None:
                fila["primera_entrada"] = marca
        elif f["tipo"] == "pausa_inicio":
            pausa_abierta[uid] = marca
        elif f["tipo"] == "pausa_fin" and pausa_abierta.get(uid):
            _repartir_segundos(filas, orden, f, uid, pausa_abierta[uid], marca, "segundos_pausa")
            pausa_abierta[uid] = None
        elif f["tipo"] == "salida" and entrada_abierta.get(uid):
            _repartir_segundos(filas, orden, f, uid, entrada_abierta[uid], marca, "segundos_trabajados")
            fila["ultima_salida"] = marca
            entrada_abierta[uid] = None
    return [filas[c] for c in orden]


def _lunes(ahora: datetime) -> datetime:
    return datetime(ahora.year, ahora.month, ahora.day) - timedelta(days=ahora.weekday())


def segundos_por_usuario_semana(tenant_id: int | None, usuario_id: int | None = None, ahora: datetime | None = None) -> dict[int, float]:
    """Segundos trabajados esta semana (lunes a domingo) por trabajador, con la
    misma medida que los totales diarios (entrada -> salida). Se lee desde el
    día anterior al lunes para repartir bien un turno que cruza la medianoche
    del domingo; solo cuentan los días de la semana. No incluye la jornada
    todavía abierta (ver resumen_semana)."""
    ahora = ahora or datetime.now()
    lunes = _lunes(ahora)
    domingo = lunes + timedelta(days=6)
    desde = (lunes - timedelta(days=1)).strftime("%Y-%m-%d")
    totales: dict[int, float] = {}
    for fila in filas_diarias(tenant_id, desde, domingo.strftime("%Y-%m-%d"), usuario_id):
        if fila["fecha"] >= lunes.strftime("%Y-%m-%d"):
            totales[fila["usuario_id"]] = totales.get(fila["usuario_id"], 0) + fila["segundos_trabajados"]
    return totales


def resumen_semana(tenant_id: int | None, usuario_id: int, ahora: datetime | None = None) -> dict:
    """Horas de la semana de un trabajador frente a su jornada contratada.
    `segundos` incluye la jornada abierta hasta ahora; `contratados` es None
    si no tiene jornada semanal indicada."""
    ahora = ahora or datetime.now()
    segundos = segundos_por_usuario_semana(tenant_id, usuario_id, ahora).get(usuario_id, 0.0)
    en_curso = 0.0
    entrada = db.entrada_abierta_fichaje(usuario_id)
    if entrada:
        inicio = max(datetime.fromisoformat(entrada), _lunes(ahora))
        en_curso = max((ahora - inicio).total_seconds(), 0.0)
    jornada = db.obtener_fichaje_datos(usuario_id)["jornada_semanal_horas"]
    contratados = float(jornada) * 3600 if jornada else None
    total = segundos + en_curso
    return {
        "segundos": total, "contratados": contratados, "en_curso": entrada is not None,
        "diferencia": (total - contratados) if contratados is not None else None,
        "porcentaje": min(100, round(total / contratados * 100)) if contratados else None,
    }


def formato_horas(segundos: float | None) -> str:
    """'24 h 30 min' (o '—' sin dato)."""
    if segundos is None:
        return "—"
    minutos = int(round(abs(segundos) / 60))
    texto = f"{minutos // 60} h {minutos % 60:02d} min"
    return f"-{texto}" if segundos < 0 else texto


def _cabecera(tenant, desde: str | None, hasta: str | None) -> tuple[str, str, str]:
    empresa = tenant["nombre"] if tenant else "Sin tenant"
    identificacion = f"CIF: {tenant['cif'] or '—'} · {tenant['direccion_fiscal'] or '—'}" if tenant else ""
    periodo = f"Periodo: {desde or 'inicio'} a {hasta or 'hoy'} · Generado: {db.now_iso()}"
    return empresa, identificacion, periodo


def a_csv(tenant_id: int | None, desde: str | None = None, hasta: str | None = None, usuario_id: int | None = None) -> str:
    tenant = db.obtener_tenant(tenant_id) if tenant_id else None
    empresa, identificacion, periodo = _cabecera(tenant, desde, hasta)
    buf = io.StringIO()
    buf.write(f"# Empresa: {empresa}\n")
    if identificacion:
        buf.write(f"# {identificacion}\n")
    buf.write(f"# {periodo}\n")
    writer = csv.writer(buf)
    writer.writerow(["fecha", "trabajador", "dni_nie", "primera_entrada", "ultima_salida", "horas_trabajadas", "horas_pausa"])
    for f in filas_diarias(tenant_id, desde, hasta, usuario_id):
        writer.writerow([
            f["fecha"],
            f["nombre_completo"] or f["email"],
            f["dni_nie"] or "",
            f["primera_entrada"].strftime("%H:%M") if f["primera_entrada"] else "",
            f["ultima_salida"].strftime("%H:%M") if f["ultima_salida"] else "",
            round(f["segundos_trabajados"] / 3600, 2),
            round(f["segundos_pausa"] / 3600, 2),
        ])
    return buf.getvalue()


def a_json(tenant_id: int | None, desde: str | None = None, hasta: str | None = None, usuario_id: int | None = None) -> str:
    """Export interoperable (Fase G3, "registro horario digital"): detalle
    CRUDO por evento (no el agregado diario de a_csv/a_pdf), con el hash
    de cada fila -- pensado para poder alimentar una futura interfaz del
    Ministerio de Trabajo sin rehacer nada cuando publiquen su
    especificación, y como prueba exportable de integridad hoy mismo
    (ver también /fichaje/admin/verificar-integridad,
    db.verificar_integridad_fichajes)."""
    tenant = db.obtener_tenant(tenant_id) if tenant_id else None
    eventos = []
    for f in db.fichajes_tenant_crudos(tenant_id, desde, hasta, usuario_id):
        eventos.append({
            "id": f["id"],
            "trabajador_email": f["email"],
            "trabajador_nombre_completo": f["nombre_completo"],
            "trabajador_dni_nie": f["dni_nie"],
            "tipo": f["tipo"],
            "marca_tiempo": f["marca_tiempo"],
            "origen": f["origen"],
            "corrige_a": f["corrige_a"],
            "creado_por": f["creado_por"],
            "creado_en": f["creado_en"],
            "latitud": f["latitud"],
            "longitud": f["longitud"],
            "hash": f["hash"],
        })
    documento = {
        "generado_en": db.now_iso(),
        "empresa": {"nombre": tenant["nombre"], "cif": tenant["cif"], "direccion_fiscal": tenant["direccion_fiscal"]} if tenant else None,
        "filtro": {"desde": desde, "hasta": hasta, "usuario_id": usuario_id},
        "esquema": {
            "hash": "Encadenado sha256 de esta fila con la anterior (ver db.py:_hash_fichaje) -- "
                    "verificable en conjunto con /fichaje/admin/verificar-integridad, no fila a fila suelta.",
            "marca_tiempo": "ISO 8601, hora local (Europe/Madrid)",
            "corrige_a": "id del evento original si esta fila es una corrección posterior, null si no",
            "latitud/longitud": "null si el tenant no tiene activada la geolocalización, o si el trabajador no dio permiso",
        },
        "eventos": eventos,
    }
    return json.dumps(documento, ensure_ascii=False, indent=2)


def a_pdf(tenant_id: int | None, desde: str | None = None, hasta: str | None = None, usuario_id: int | None = None) -> bytes:
    tenant = db.obtener_tenant(tenant_id) if tenant_id else None
    empresa, identificacion, periodo = _cabecera(tenant, desde, hasta)
    filas = filas_diarias(tenant_id, desde, hasta, usuario_id)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), title="Registro de fichaje")
    estilos = getSampleStyleSheet()
    elementos = [
        Paragraph(f"Registro de fichaje — {empresa}", estilos["Title"]),
    ]
    if identificacion:
        elementos.append(Paragraph(identificacion, estilos["Normal"]))
    elementos.append(Paragraph(periodo, estilos["Normal"]))
    elementos.append(Spacer(1, 0.6 * cm))

    datos_tabla = [["Fecha", "Trabajador", "DNI/NIE", "Entrada", "Salida", "Horas trab.", "Horas pausa"]]
    for f in filas:
        datos_tabla.append([
            f["fecha"],
            f["nombre_completo"] or f["email"],
            f["dni_nie"] or "",
            f["primera_entrada"].strftime("%H:%M") if f["primera_entrada"] else "",
            f["ultima_salida"].strftime("%H:%M") if f["ultima_salida"] else "",
            f"{round(f['segundos_trabajados'] / 3600, 2)}h",
            f"{round(f['segundos_pausa'] / 3600, 2)}h",
        ])
    tabla = Table(datos_tabla, repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1d23")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8dbe1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f8fa")]),
    ]))
    elementos.append(tabla)
    doc.build(elementos)
    return buf.getvalue()
