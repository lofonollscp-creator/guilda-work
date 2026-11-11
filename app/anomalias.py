"""Alertas de anomalías (W7): lo que se sale de lo normal en los clientes del despacho, con reglas claras y explicables (nada de «caja negra»): cada alerta dice qué regla saltó y con qué números, y lleva el
enlace a donde se arregla. No usa IA para decidir; la IA, si se quiere, solo redacta la explicación a partir de estos mismos datos.

Reglas:
* **sin_facturas** — un cliente que subía facturas con regularidad (al menos 3 en el último año) lleva sin subir ninguna más del triple de su intervalo habitual (y más de 45 días).
* **gasto_atipico** — una factura recibida reciente que cuesta más de 3 desviaciones típicas y más del doble de la media de las anteriores del mismo cliente (con al menos 8 anteriores y 300 € de importe).
* **duplicada** — dos facturas del mismo cliente, mismo proveedor e importe y fechas a menos de 3 días.
* **vencimiento_sin_documentos** — un modelo pendiente que vence en 7 días o menos y para el que se pidió documentación que no ha llegado.
* **vencido_sin_presentar** — un modelo pendiente cuya fecha límite ya pasó.
Sin tablas: se calcula al abrir la pantalla con lo que ya hay."""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from . import db

SEVERIDADES = {"alta": 0, "media": 1, "baja": 2}
MIN_FACTURAS_HABITUALES = 3
MIN_DIAS_SIN_FACTURAS = 45
FACTOR_INTERVALO = 3
MIN_ANTERIORES_GASTO = 8
MIN_IMPORTE_GASTO_CENT = 30000
VENTANA_RECIENTE_DIAS = 30
DIAS_DUPLICADA = 3
DIAS_VENCIMIENTO_PROXIMO = 7


def _d(texto: str | None) -> date | None:
    try:
        return date.fromisoformat((texto or "")[:10])
    except ValueError:
        return None


def _eur(c: int) -> str:
    return f"{c / 100:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _clientes(conn, tenant_id: int) -> dict[int, str]:
    return {f["id"]: f["nombre"] for f in conn.execute("SELECT id, nombre FROM clientes_fiscales WHERE tenant_id = ?", (tenant_id,)).fetchall()}


def _facturas(conn, tenant_id: int, desde: date) -> list[dict]:
    return [dict(f) for f in conn.execute(
        "SELECT id, cliente_fiscal_id, tipo, fecha, tercero_nombre, tercero_nif, total_centimos, creado_en FROM facturas_contables "
        "WHERE tenant_id = ? AND estado <> 'descartada' AND fecha >= ? ORDER BY fecha, id", (tenant_id, desde.isoformat())).fetchall()]


def sin_facturas(facturas: list[dict], nombres: dict[int, str], hoy: date) -> list[dict]:
    por: dict[int, list[date]] = {}
    for f in facturas:
        d = _d(f["fecha"])
        if d:
            por.setdefault(f["cliente_fiscal_id"], []).append(d)
    salida = []
    for cid, fechas in por.items():
        fechas.sort()
        if len(fechas) < MIN_FACTURAS_HABITUALES or cid not in nombres:
            continue
        huecos = [(b - a).days for a, b in zip(fechas, fechas[1:])]
        tipico = statistics.median(huecos[-10:]) if huecos else 0
        sin = (hoy - fechas[-1]).days
        if sin > max(MIN_DIAS_SIN_FACTURAS, FACTOR_INTERVALO * tipico):
            salida.append({"tipo": "sin_facturas", "severidad": "media", "cliente_id": cid, "cliente": nombres[cid],
                           "datos": {"dias_sin": sin, "intervalo_habitual": round(tipico), "ultima": fechas[-1].isoformat()}})
    return salida


def gasto_atipico(facturas: list[dict], nombres: dict[int, str], hoy: date) -> list[dict]:
    por: dict[int, list[dict]] = {}
    for f in facturas:
        if f["tipo"] == "recibida" and f["total_centimos"] > 0:
            por.setdefault(f["cliente_fiscal_id"], []).append(f)
    salida = []
    limite = hoy - timedelta(days=VENTANA_RECIENTE_DIAS)
    for cid, lista in por.items():
        for f in lista:
            d = _d(f["fecha"])
            if not d or d < limite or f["total_centimos"] < MIN_IMPORTE_GASTO_CENT or cid not in nombres:
                continue
            antes = [x["total_centimos"] for x in lista if x["id"] != f["id"] and (_d(x["fecha"]) or hoy) < d]
            if len(antes) < MIN_ANTERIORES_GASTO:
                continue
            media, desv = statistics.mean(antes), statistics.pstdev(antes)
            if f["total_centimos"] > media + 3 * desv and f["total_centimos"] > 2 * media:
                salida.append({"tipo": "gasto_atipico", "severidad": "media", "cliente_id": cid, "cliente": nombres[cid], "factura_id": f["id"],
                               "datos": {"importe": f["total_centimos"], "media": round(media), "proveedor": f["tercero_nombre"], "fecha": f["fecha"]}})
    return salida


def duplicadas(facturas: list[dict], nombres: dict[int, str], hoy: date) -> list[dict]:
    salida, vistas = [], set()
    reciente = hoy - timedelta(days=60)
    for i, a in enumerate(facturas):
        for b in facturas[i + 1:]:
            if a["cliente_fiscal_id"] != b["cliente_fiscal_id"] or a["tipo"] != b["tipo"] or a["total_centimos"] != b["total_centimos"]:
                continue
            da, db_ = _d(a["fecha"]), _d(b["fecha"])
            if not da or not db_ or abs((da - db_).days) > DIAS_DUPLICADA or max(da, db_) < reciente:
                continue
            misma = (a["tercero_nif"] and a["tercero_nif"] == b["tercero_nif"]) or (a["tercero_nombre"] or "").strip().lower() == (b["tercero_nombre"] or "").strip().lower()
            if misma and (a["id"], b["id"]) not in vistas and a["cliente_fiscal_id"] in nombres:
                vistas.add((a["id"], b["id"]))
                salida.append({"tipo": "duplicada", "severidad": "alta", "cliente_id": a["cliente_fiscal_id"], "cliente": nombres[a["cliente_fiscal_id"]], "factura_id": b["id"],
                               "datos": {"importe": a["total_centimos"], "proveedor": a["tercero_nombre"], "otra_factura_id": a["id"]}})
    return salida


def vencimientos(conn, tenant_id: int, nombres: dict[int, str], hoy: date) -> list[dict]:
    salida = []
    filas = conn.execute("SELECT v.id, v.cliente_fiscal_id, v.modelo, v.periodo, v.fecha_limite, COALESCE(v.documento_solicitado, '') AS pedido, "
                         "(SELECT COUNT(*) FROM vencimientos_fiscales_documentos d WHERE d.vencimiento_id = v.id) AS docs "
                         "FROM vencimientos_fiscales v WHERE v.tenant_id = ? AND v.estado = 'pendiente' AND v.papelera_en IS NULL AND v.fecha_limite <= ?",
                         (tenant_id, (hoy + timedelta(days=DIAS_VENCIMIENTO_PROXIMO)).isoformat())).fetchall()
    for v in filas:
        limite = _d(v["fecha_limite"])
        if limite is None or v["cliente_fiscal_id"] not in nombres:
            continue
        base = {"cliente_id": v["cliente_fiscal_id"], "cliente": nombres[v["cliente_fiscal_id"]], "vencimiento_id": v["id"], "modelo": v["modelo"], "periodo": v["periodo"], "fecha_limite": v["fecha_limite"]}
        dias = (limite - hoy).days
        if dias < 0:
            salida.append({"tipo": "vencido_sin_presentar", "severidad": "alta", "datos": {"dias": -dias}, **base})
        elif v["pedido"].strip() and not v["docs"]:
            salida.append({"tipo": "vencimiento_sin_documentos", "severidad": "alta" if dias <= 3 else "media", "datos": {"dias": dias, "pedido": v["pedido"].strip()[:120]}, **base})
    return salida


def detectar(tenant_id: int, hoy: date | None = None) -> list[dict]:
    """Todas las alertas del despacho, las más graves primero (y dentro de cada gravedad, por cliente)."""
    hoy = hoy or date.today()
    conn = db.get_connection()
    try:
        nombres = _clientes(conn, tenant_id)
        facturas = _facturas(conn, tenant_id, hoy - timedelta(days=365))
        alertas = vencimientos(conn, tenant_id, nombres, hoy)
    finally:
        conn.close()
    alertas += sin_facturas(facturas, nombres, hoy) + gasto_atipico(facturas, nombres, hoy) + duplicadas(facturas, nombres, hoy)
    return sorted(alertas, key=lambda a: (SEVERIDADES[a["severidad"]], a["cliente"].lower(), a["tipo"]))


def texto(a: dict) -> tuple[str, str]:
    """(título, detalle) legibles y traducidos de una alerta. Se compone aquí, con los números de la regla, para que se entienda por qué saltó."""
    from flask_babel import gettext as _
    d = a["datos"]
    if a["tipo"] == "sin_facturas":
        return (_("%(c)s lleva %(n)s días sin subir facturas", c=a["cliente"], n=d["dias_sin"]),
                _("Lo habitual es una cada %(n)s días; la última es del %(f)s.", n=d["intervalo_habitual"], f=d["ultima"]))
    if a["tipo"] == "gasto_atipico":
        return (_("Gasto fuera de lo normal en %(c)s", c=a["cliente"]),
                _("%(p)s: %(i)s, cuando la media de sus facturas es %(m)s.", p=d["proveedor"], i=_eur(d["importe"]), m=_eur(d["media"])))
    if a["tipo"] == "duplicada":
        return (_("Posible factura duplicada de %(c)s", c=a["cliente"]),
                _("%(p)s por %(i)s, con fechas a menos de %(n)s días.", p=d["proveedor"], i=_eur(d["importe"]), n=DIAS_DUPLICADA))
    if a["tipo"] == "vencimiento_sin_documentos":
        return (_("Modelo %(m)s de %(c)s vence en %(n)s días sin documentación", m=a["modelo"], c=a["cliente"], n=d["dias"]),
                _("Se pidió «%(p)s» y no ha llegado nada.", p=d["pedido"]))
    return (_("Modelo %(m)s de %(c)s sin presentar", m=a["modelo"], c=a["cliente"]),
            _("La fecha límite pasó hace %(n)s días.", n=d["dias"]))
