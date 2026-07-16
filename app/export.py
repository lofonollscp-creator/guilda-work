"""Exportación de datos a JSON y CSV para análisis por una IA."""
import csv
import io
import json
from datetime import datetime, timedelta

from . import db

EXPORTS_AUTO_DIR = db.RAIZ_PROYECTO / "exports" / "auto"


def construir_export(usuario_id: int, desde: str | None, hasta: str | None, categoria_id: int | None) -> dict:
    filas = db.historial(usuario_id, desde=desde, hasta=hasta, categoria_id=categoria_id)
    registros = []
    for f in filas:
        registros.append({
            "origen": f["origen"],  # 'nota' o 'tarea'
            "id": f["id"],
            "texto_o_nombre": f["texto"],
            "tipo": f["tipo"],  # 'duracion' | 'instantanea' | null para notas
            "estado": f["estado"],
            "categoria": f["categoria_nombre"],
            "timestamp_inicio": f["timestamp"],
            "timestamp_fin": f["fin_en"],
            "duracion_segundos": f["duracion_segundos"],
        })
    return {
        "generado_en": db.now_iso(),
        "filtro": {"desde": desde, "hasta": hasta, "categoria_id": categoria_id},
        "esquema": {
            "origen": "'nota' = entrada de log libre; 'tarea' = tarea con duración o evento instantáneo",
            "tipo": "solo aplica a origen=tarea: 'duracion' (tiene inicio y fin) o 'instantanea' (un único timestamp)",
            "timestamp_inicio": "ISO 8601, hora local (Europe/Madrid)",
            "timestamp_fin": "ISO 8601, NULL si es nota o tarea instantánea o aún en curso",
            "duracion_segundos": "solo para tareas tipo=duracion ya finalizadas",
        },
        "registros": registros,
    }


def a_json(usuario_id: int, desde=None, hasta=None, categoria_id=None) -> str:
    return json.dumps(construir_export(usuario_id, desde, hasta, categoria_id), ensure_ascii=False, indent=2)


def a_csv(usuario_id: int, desde=None, hasta=None, categoria_id=None) -> str:
    data = construir_export(usuario_id, desde, hasta, categoria_id)
    buf = io.StringIO()
    campos = ["origen", "id", "texto_o_nombre", "tipo", "estado", "categoria",
              "timestamp_inicio", "timestamp_fin", "duracion_segundos"]
    writer = csv.DictWriter(buf, fieldnames=campos)
    writer.writeheader()
    for r in data["registros"]:
        writer.writerow(r)
    return buf.getvalue()


def a_markdown(usuario_id: int, desde=None, hasta=None, categoria_id=None) -> str:
    """Resumen legible en Markdown, agrupado por categoría."""
    data = construir_export(usuario_id, desde, hasta, categoria_id)
    por_categoria: dict[str, list[dict]] = {}
    for r in data["registros"]:
        por_categoria.setdefault(r["categoria"] or "Sin categoría", []).append(r)

    rango = []
    if desde:
        rango.append(f"desde {desde}")
    if hasta:
        rango.append(f"hasta {hasta}")
    titulo_rango = f" ({' '.join(rango)})" if rango else ""

    lineas = [f"# Registro de actividad{titulo_rango}", ""]
    for categoria in sorted(por_categoria):
        registros = por_categoria[categoria]
        segundos_totales = sum(r["duracion_segundos"] or 0 for r in registros)
        lineas.append(f"## {categoria}")
        if segundos_totales:
            lineas.append(f"*Tiempo total en tareas con duración: {segundos_totales // 3600}h {(segundos_totales % 3600) // 60}m*")
        lineas.append("")
        for r in sorted(registros, key=lambda r: r["timestamp_inicio"] or ""):
            hora = (r["timestamp_inicio"] or "")[:16].replace("T", " ")
            if r["origen"] == "nota":
                etiqueta = "Nota"
            elif r["tipo"] == "instantanea":
                etiqueta = "Evento"
            else:
                dur = r["duracion_segundos"]
                etiqueta = f"Tarea ({dur // 60}min)" if dur is not None else "Tarea (en curso)"
            lineas.append(f"- `{hora}` **{etiqueta}** — {r['texto_o_nombre']}")
        lineas.append("")

    return "\n".join(lineas)


def generar_resumen_automatico_si_hace_falta(dias_atras: int = 1, mantener_dias: int = 30) -> None:
    """Genera (si no existe ya) un resumen en Markdown del día de ayer, en
    `exports/auto/`. Como la app no está necesariamente abierta a
    medianoche, esto se llama al arrancar (igual que el backup): en vez de
    depender de que el proceso siga vivo a una hora fija, comprueba en cada
    arranque si falta el resumen del día anterior y lo crea entonces.
    """
    fecha = (datetime.now() - timedelta(days=dias_atras)).strftime("%Y-%m-%d")
    EXPORTS_AUTO_DIR.mkdir(parents=True, exist_ok=True)
    destino = EXPORTS_AUTO_DIR / f"resumen_{fecha}.md"
    if not destino.exists():
        contenido = a_markdown(db.usuario_local_id(), desde=fecha, hasta=fecha)
        destino.write_text(contenido, encoding="utf-8")

    limite = datetime.now() - timedelta(days=mantener_dias)
    for f in EXPORTS_AUTO_DIR.glob("resumen_*.md"):
        try:
            fecha_archivo = datetime.strptime(f.stem.removeprefix("resumen_"), "%Y-%m-%d")
        except ValueError:
            continue
        if fecha_archivo < limite:
            f.unlink(missing_ok=True)
