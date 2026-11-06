"""Auditoría de toda la plataforma: los eventos de todos los despachos (quién hizo qué y cuándo) con filtros y exportación a CSV, y las acciones del propio backoffice con su
cadena de integridad. Solo lectura."""
from __future__ import annotations

import csv
import io

from app import db as plataforma

from . import auth

LIMITE_PAGINA = 100
LIMITE_EXPORTACION = 20000
COLUMNAS = ("id", "creado_en", "despacho", "actor", "accion", "entidad", "entidad_id", "detalle")


def _como(texto: str) -> str:
    return "%" + texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def buscar(*, tenant_id: int | None = None, accion: str = "", actor: str = "", desde: str = "", hasta: str = "", antes_de_id: int | None = None, limite: int = LIMITE_PAGINA) -> list[dict]:
    """Eventos de todos los despachos (o de uno), los más recientes primero. `accion` y `actor` buscan por trozo de texto; `desde` y `hasta` son fechas AAAA-MM-DD."""
    donde, p = ["1 = 1"], []
    if tenant_id:
        donde.append("a.tenant_id = ?"); p.append(tenant_id)
    if accion.strip():
        donde.append("LOWER(a.accion) LIKE ? ESCAPE '\\'"); p.append(_como(accion.strip().lower()))
    if actor.strip():
        donde.append("LOWER(u.email) LIKE ? ESCAPE '\\'"); p.append(_como(actor.strip().lower()))
    if desde:
        donde.append("a.creado_en >= ?"); p.append(desde[:10])
    if hasta:
        donde.append("substr(a.creado_en, 1, 10) <= ?"); p.append(hasta[:10])
    if antes_de_id:
        donde.append("a.id < ?"); p.append(antes_de_id)
    conn = plataforma.get_connection()
    try:
        filas = conn.execute(
            "SELECT a.id, a.tenant_id, t.nombre AS despacho, u.email AS actor, a.accion, a.entidad, a.entidad_id, a.detalle, a.creado_en FROM auditoria_eventos a "
            f"LEFT JOIN tenants t ON t.id = a.tenant_id LEFT JOIN usuarios u ON u.id = a.usuario_id WHERE {' AND '.join(donde)} ORDER BY a.id DESC LIMIT ?",
            [*p, max(1, min(limite, LIMITE_EXPORTACION))]).fetchall()
    finally:
        conn.close()
    return [dict(f) for f in filas]


def _celda(valor) -> str:
    """Un valor para el CSV; si empieza como una fórmula de hoja de cálculo se le antepone una comilla para que no se ejecute al abrirlo."""
    texto = "" if valor is None else str(valor)
    return "'" + texto if texto[:1] in ("=", "+", "-", "@", "\t", "\r") else texto


def a_csv(filas: list[dict], columnas: tuple[str, ...] = COLUMNAS) -> str:
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(columnas)
    for f in filas:
        escritor.writerow([_celda(f.get(c)) for c in columnas])
    return salida.getvalue()


def acciones_del_backoffice(limite: int = LIMITE_EXPORTACION) -> list[dict]:
    return [dict(f) for f in auth.listar_auditoria(limite)]
