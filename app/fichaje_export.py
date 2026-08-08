"""Exportación CSV/PDF del registro horario -- mismo criterio que
app/export.py: esta tabla (fichajes, ver db.py) no sabe nada de formatos
de salida, aquí solo se da forma a lo que devuelve
db.fichajes_tenant_crudos()."""
import csv
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import db


def _filas_diarias(tenant_id: int | None, desde: str | None, hasta: str | None, usuario_id: int | None) -> list[dict]:
    """Agrupa los eventos en bruto por trabajador y día -- primera entrada,
    última salida, horas trabajadas y de pausa de ese día. Igual que
    db.resumen_fichajes_tenant() pero por día en vez de por todo el
    periodo, que es lo que hace falta en un registro exportable de
    verdad (no solo el total)."""
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
            filas[clave] = {
                "usuario_id": uid, "fecha": fecha, "email": f["email"],
                "nombre_completo": f["nombre_completo"], "dni_nie": f["dni_nie"],
                "primera_entrada": None, "ultima_salida": None,
                "segundos_trabajados": 0, "segundos_pausa": 0,
            }
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
            fila["segundos_pausa"] += (marca - pausa_abierta[uid]).total_seconds()
            pausa_abierta[uid] = None
        elif f["tipo"] == "salida" and entrada_abierta.get(uid):
            fila["segundos_trabajados"] += (marca - entrada_abierta[uid]).total_seconds()
            fila["ultima_salida"] = marca
            entrada_abierta[uid] = None
    return [filas[c] for c in orden]


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
    for f in _filas_diarias(tenant_id, desde, hasta, usuario_id):
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


def a_pdf(tenant_id: int | None, desde: str | None = None, hasta: str | None = None, usuario_id: int | None = None) -> bytes:
    tenant = db.obtener_tenant(tenant_id) if tenant_id else None
    empresa, identificacion, periodo = _cabecera(tenant, desde, hasta)
    filas = _filas_diarias(tenant_id, desde, hasta, usuario_id)

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
