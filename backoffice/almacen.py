"""Panel del almacén de objetos: cuánto hay fuera de la base (S3 o carpeta), por despacho y por tabla, qué queda dentro por migrar, cuándo se comprobó
por última vez y una estimación del coste. Solo lectura, salvo `verificar_muestra`, que lee objetos del almacén y anota la fecha de comprobación."""
from __future__ import annotations

import hashlib
from datetime import datetime

from app import almacen_objetos as ao
from app import db as plataforma

PRECIO_GB_MES_USD = 0.023          # S3 Standard en eu-north-1 (orientativo; el almacén real puede ser otro)
MUESTRA_MAXIMA = 200


def _mb(n: int) -> float:
    return round(n / 1024 / 1024, 1)


def estado_almacen() -> dict:
    """{configurado, nombre, error}: qué almacén hay activo, sin tocar nada."""
    try:
        a = ao.almacen()
    except ao.ErrorAlmacenObjetos as e:
        return {"configurado": False, "nombre": None, "error": str(e)}
    return {"configurado": a is not None, "nombre": a.nombre if a else None, "error": None}


def resumen() -> dict:
    """Totales y desglose por tabla y por despacho: fuera (en el almacén) y dentro (contenido que sigue en la base)."""
    conn = plataforma.get_connection()
    try:
        por_tabla = []
        dentro_por_tenant: dict[int, dict] = {}
        for tabla, (union, expr) in ao.DESPACHO.items():
            fuera = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(tamano_bytes), 0) AS b FROM objetos_almacenados WHERE tabla = ?", (tabla,)).fetchone()
            dentro = conn.execute(
                f"SELECT {expr} AS tenant_id, COUNT(*) AS n, COALESCE(SUM(length(t.contenido)), 0) AS b FROM {tabla} t {union} WHERE length(t.contenido) > 0 "
                f"AND NOT EXISTS (SELECT 1 FROM objetos_almacenados o WHERE o.tabla = ? AND o.fila_id = t.id) GROUP BY {expr}", (tabla,)).fetchall()
            n_dentro = b_dentro = 0
            for d in dentro:
                acum = dentro_por_tenant.setdefault(d["tenant_id"], {"n": 0, "b": 0})
                acum["n"] += d["n"]
                acum["b"] += d["b"]
                n_dentro += d["n"]
                b_dentro += d["b"]
            por_tabla.append({"tabla": tabla, "fuera": fuera["n"], "fuera_mb": _mb(fuera["b"]), "dentro": n_dentro, "dentro_mb": _mb(b_dentro)})
        fuera_por_tenant = {f["tenant_id"]: f for f in conn.execute(
            "SELECT tenant_id, COUNT(*) AS n, COALESCE(SUM(tamano_bytes), 0) AS b, MIN(verificado_en) AS mas_antigua, "
            "SUM(CASE WHEN verificado_en IS NULL THEN 1 ELSE 0 END) AS sin_verificar FROM objetos_almacenados GROUP BY tenant_id").fetchall()}
        nombres = {t["id"]: t["nombre"] for t in conn.execute("SELECT id, nombre FROM tenants").fetchall()}
    finally:
        conn.close()
    por_despacho = []
    for tid in sorted(set(fuera_por_tenant) | set(dentro_por_tenant), key=lambda t: -(fuera_por_tenant.get(t, {"b": 0})["b"] if t in fuera_por_tenant else 0)):
        f, d = fuera_por_tenant.get(tid), dentro_por_tenant.get(tid, {"n": 0, "b": 0})
        por_despacho.append({"tenant_id": tid, "nombre": nombres.get(tid, f"#{tid}"), "fuera": f["n"] if f else 0, "fuera_mb": _mb(f["b"]) if f else 0.0,
                             "dentro": d["n"], "dentro_mb": _mb(d["b"]), "sin_verificar": (f["sin_verificar"] or 0) if f else 0})
    bytes_fuera = sum(f["b"] for f in fuera_por_tenant.values())
    return {
        "por_tabla": por_tabla, "por_despacho": por_despacho,
        "objetos": sum(t["fuera"] for t in por_tabla), "fuera_mb": _mb(bytes_fuera),
        "dentro": sum(t["dentro"] for t in por_tabla), "dentro_mb": round(sum(t["dentro_mb"] for t in por_tabla), 1),
        "coste_mes_usd": round(bytes_fuera / 1024 ** 3 * PRECIO_GB_MES_USD, 4),
        "sin_verificar": sum((f["sin_verificar"] or 0) for f in fuera_por_tenant.values()),
    }


def verificar_muestra(limite: int = 50) -> dict:
    """Lee del almacén los `limite` objetos que llevan más tiempo sin comprobarse (los nunca comprobados primero) y contrasta tamaño y SHA-256.
    {revisados, problemas: [texto]}. `ErrorAlmacenObjetos` si no hay almacén."""
    limite = max(1, min(int(limite), MUESTRA_MAXIMA))
    a = ao.almacen()
    if a is None:
        raise ao.ErrorAlmacenObjetos("No hay almacén de objetos configurado.")
    conn = plataforma.get_connection()
    problemas: list[str] = []
    try:
        filas = conn.execute("SELECT * FROM objetos_almacenados ORDER BY (verificado_en IS NOT NULL), verificado_en, id LIMIT ?", (limite,)).fetchall()
        for o in filas:
            etiqueta = f"{o['tabla']} #{o['fila_id']}"
            try:
                datos = a.leer(o["clave"])
            except ao.ErrorAlmacenObjetos as e:
                problemas.append(f"Falta {etiqueta}: {e}")
                continue
            if len(datos) != o["tamano_bytes"] or hashlib.sha256(datos).hexdigest() != o["sha256"]:
                problemas.append(f"Distinto {etiqueta}: no coincide con su registro")
                continue
            conn.execute("UPDATE objetos_almacenados SET verificado_en = ? WHERE id = ?", (datetime.now().isoformat(timespec="seconds"), o["id"]))
        conn.commit()
    finally:
        conn.close()
    return {"revisados": len(filas), "problemas": problemas}
