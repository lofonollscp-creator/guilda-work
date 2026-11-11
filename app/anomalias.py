"""Alertas de anomalías (W7): lo que se sale de lo normal en los clientes del despacho, con reglas claras y explicables (nada de «caja negra»): cada alerta dice qué regla saltó y con qué números, y lleva el
enlace a donde se arregla. No usa IA para decidir; la IA, si se quiere, solo redacta la explicación a partir de estos mismos datos.

Reglas:
* **sin_facturas** — un cliente que subía facturas con regularidad (al menos 3 en el último año) lleva sin subir ninguna más del triple de su intervalo habitual (y más de 45 días).
* **gasto_atipico** — una factura recibida reciente que cuesta más de 3 desviaciones típicas y más del doble de la media de las anteriores del mismo cliente (con al menos 8 anteriores y 300 € de importe).
* **duplicada** — dos facturas del mismo cliente, mismo proveedor e importe y fechas a menos de 3 días.
* **vencimiento_sin_documentos** — un modelo pendiente que vence en 7 días o menos y para el que se pidió documentación que no ha llegado.
* **vencido_sin_presentar** — un modelo pendiente cuya fecha límite ya pasó.
* **iva_desviado** — el IVA de lo que va de trimestre se aleja más de un 50 % (por defecto) de lo que cabría esperar por la media de los cuatro trimestres anteriores, prorrateada por el tiempo transcurrido.
* **sin_entrar_portal** — un cliente con una petición de documentos abierta cuyas personas no entran al portal desde hace más de 30 días (o nunca).
* **proveedor_nuevo** — una factura recibida reciente de un proveedor que ese cliente no había tenido nunca, con un importe alto (1.000 € por defecto).

Los umbrales de cada regla son los de `UMBRALES_POR_DEFECTO` y la dirección los ajusta por despacho (`ia_despacho.umbrales`).
Sin tablas: se calcula al abrir la pantalla con lo que ya hay."""
from __future__ import annotations

import json
import statistics
from datetime import date, timedelta

from . import db

SEVERIDADES = {"alta": 0, "media": 1, "baja": 2}
UMBRALES_POR_DEFECTO = {"dias_sin_facturas": 45, "importe_gasto": 300, "dias_vencimiento": 7, "iva_desvio_pct": 50, "dias_sin_entrar": 30, "importe_proveedor_nuevo": 1000}
LIMITES = {"dias_sin_facturas": (15, 365), "importe_gasto": (50, 100000), "dias_vencimiento": (1, 30), "iva_desvio_pct": (10, 500), "dias_sin_entrar": (7, 365), "importe_proveedor_nuevo": (100, 1000000)}
MIN_FACTURAS_HABITUALES = 3
FACTOR_INTERVALO = 3
MIN_ANTERIORES_GASTO = 8
VENTANA_RECIENTE_DIAS = 30
DIAS_DUPLICADA = 3


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


def sin_facturas(facturas: list[dict], nombres: dict[int, str], hoy: date, u: dict | None = None) -> list[dict]:
    minimo = (u or UMBRALES_POR_DEFECTO)["dias_sin_facturas"]
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
        if sin > max(minimo, FACTOR_INTERVALO * tipico):
            salida.append({"tipo": "sin_facturas", "severidad": "media", "cliente_id": cid, "cliente": nombres[cid],
                           "datos": {"dias_sin": sin, "intervalo_habitual": round(tipico), "ultima": fechas[-1].isoformat()}})
    return salida


def gasto_atipico(facturas: list[dict], nombres: dict[int, str], hoy: date, u: dict | None = None) -> list[dict]:
    minimo = (u or UMBRALES_POR_DEFECTO)["importe_gasto"] * 100
    por: dict[int, list[dict]] = {}
    for f in facturas:
        if f["tipo"] == "recibida" and f["total_centimos"] > 0:
            por.setdefault(f["cliente_fiscal_id"], []).append(f)
    salida = []
    limite = hoy - timedelta(days=VENTANA_RECIENTE_DIAS)
    for cid, lista in por.items():
        for f in lista:
            d = _d(f["fecha"])
            if not d or d < limite or f["total_centimos"] < minimo or cid not in nombres:
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


def vencimientos(conn, tenant_id: int, nombres: dict[int, str], hoy: date, u: dict | None = None) -> list[dict]:
    salida = []
    dias_prox = (u or UMBRALES_POR_DEFECTO)["dias_vencimiento"]
    filas = conn.execute("SELECT v.id, v.cliente_fiscal_id, v.modelo, v.periodo, v.fecha_limite, COALESCE(v.documento_solicitado, '') AS pedido, "
                         "(SELECT COUNT(*) FROM vencimientos_fiscales_documentos d WHERE d.vencimiento_id = v.id) AS docs "
                         "FROM vencimientos_fiscales v WHERE v.tenant_id = ? AND v.estado = 'pendiente' AND v.papelera_en IS NULL AND v.fecha_limite <= ?",
                         (tenant_id, (hoy + timedelta(days=dias_prox)).isoformat())).fetchall()
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


def _trimestre(d: date) -> tuple[int, int]:
    return d.year, (d.month - 1) // 3 + 1


def iva_desviado(conn, tenant_id: int, nombres: dict[int, str], hoy: date, u: dict) -> list[dict]:
    """IVA (repercutido menos soportado) del trimestre en curso frente a la media prorrateada de los cuatro anteriores; solo con al menos tres trimestres de histórico y 500 € de IVA medio."""
    desde = date(hoy.year - 2, 1, 1).isoformat()
    por: dict[tuple[int, int, int], int] = {}
    for f in conn.execute("SELECT f.cliente_fiscal_id AS c, f.tipo, f.fecha, COALESCE(SUM(l.cuota_iva), 0) AS iva FROM facturas_contables f LEFT JOIN facturas_contables_lineas l ON l.factura_id = f.id "
                          "WHERE f.tenant_id = ? AND f.estado <> 'descartada' AND f.fecha >= ? GROUP BY f.id, f.cliente_fiscal_id, f.tipo, f.fecha", (tenant_id, desde)).fetchall():
        d = _d(f["fecha"])
        if d:
            clave = (f["c"], *_trimestre(d))
            por[clave] = por.get(clave, 0) + (f["iva"] if f["tipo"] == "emitida" else -f["iva"])
    actual = _trimestre(hoy)
    inicio = date(hoy.year, 3 * (actual[1] - 1) + 1, 1)
    fin = date(hoy.year + (actual[1] == 4), (3 * actual[1]) % 12 + 1, 1)
    transcurrido = max(0.0, min(1.0, (hoy - inicio).days / max(1, (fin - inicio).days)))
    salida = []
    for cid in {k[0] for k in por}:
        previos = []
        y, q = actual
        for _ in range(4):
            q -= 1
            if q == 0:
                y, q = y - 1, 4
            if (cid, y, q) in por:
                previos.append(por[(cid, y, q)])
        if len(previos) < 3 or cid not in nombres or transcurrido < 0.5:
            continue
        media = statistics.mean(previos)
        if abs(media) < 50000:
            continue
        esperado, real = media * transcurrido, por.get((cid, *actual), 0)
        if abs(real - esperado) > abs(media) * u["iva_desvio_pct"] / 100:
            salida.append({"tipo": "iva_desviado", "severidad": "media", "cliente_id": cid, "cliente": nombres[cid], "datos": {"real": round(real), "esperado": round(esperado), "media": round(media)}})
    return salida


def sin_entrar_portal(conn, tenant_id: int, nombres: dict[int, str], hoy: date, u: dict) -> list[dict]:
    limite = (hoy - timedelta(days=u["dias_sin_entrar"])).isoformat()
    salida = []
    for f in conn.execute("SELECT DISTINCT p.cliente_fiscal_id AS c FROM portal_peticiones p WHERE p.tenant_id = ? AND p.estado = 'pendiente'", (tenant_id,)).fetchall():
        cid = f["c"]
        ultimo = conn.execute("SELECT MAX(ultimo_acceso_en) FROM portal_contactos WHERE tenant_id = ? AND cliente_fiscal_id = ? AND baja_en IS NULL", (tenant_id, cid)).fetchone()[0]
        if cid in nombres and (ultimo is None or ultimo[:10] < limite):
            salida.append({"tipo": "sin_entrar_portal", "severidad": "media", "cliente_id": cid, "cliente": nombres[cid], "datos": {"ultimo": (ultimo or "")[:10], "dias": u["dias_sin_entrar"]}})
    return salida


def proveedor_nuevo(facturas: list[dict], nombres: dict[int, str], hoy: date, u: dict) -> list[dict]:
    minimo = u["importe_proveedor_nuevo"] * 100
    limite = hoy - timedelta(days=VENTANA_RECIENTE_DIAS)
    vistos: dict[tuple[int, str], date] = {}
    for f in facturas:
        d = _d(f["fecha"])
        clave = (f["cliente_fiscal_id"], (f["tercero_nif"] or f["tercero_nombre"] or "").strip().upper())
        if f["tipo"] == "recibida" and d and clave[1] and (clave not in vistos or d < vistos[clave]):
            vistos[clave] = d
    salida = []
    for f in facturas:
        clave = (f["cliente_fiscal_id"], (f["tercero_nif"] or f["tercero_nombre"] or "").strip().upper())
        d = _d(f["fecha"])
        if f["tipo"] == "recibida" and d and d >= limite and f["total_centimos"] >= minimo and vistos.get(clave) == d and f["cliente_fiscal_id"] in nombres:
            primera = [x for x in facturas if (x["cliente_fiscal_id"], (x["tercero_nif"] or x["tercero_nombre"] or "").strip().upper()) == clave and x["tipo"] == "recibida"]
            if len(primera) == 1:                                                             # esta es la única factura de ese proveedor en todo el histórico del cliente (un año)
                salida.append({"tipo": "proveedor_nuevo", "severidad": "baja", "cliente_id": f["cliente_fiscal_id"], "cliente": nombres[f["cliente_fiscal_id"]], "factura_id": f["id"],
                               "datos": {"importe": f["total_centimos"], "proveedor": f["tercero_nombre"], "fecha": f["fecha"]}})
    return salida


def detectar(tenant_id: int, hoy: date | None = None, umbrales: dict | None = None) -> list[dict]:
    """Todas las alertas del despacho, las más graves primero (y dentro de cada gravedad, por cliente). Los umbrales son los del despacho (`ia_despacho.umbrales`) salvo que se pasen otros."""
    hoy = hoy or date.today()
    if umbrales is None:
        from . import ia_despacho
        umbrales = ia_despacho.umbrales(tenant_id)
    conn = db.get_connection()
    try:
        nombres = _clientes(conn, tenant_id)
        facturas = _facturas(conn, tenant_id, hoy - timedelta(days=365))
        alertas = vencimientos(conn, tenant_id, nombres, hoy, umbrales) + iva_desviado(conn, tenant_id, nombres, hoy, umbrales) + sin_entrar_portal(conn, tenant_id, nombres, hoy, umbrales)
    finally:
        conn.close()
    alertas += sin_facturas(facturas, nombres, hoy, umbrales) + gasto_atipico(facturas, nombres, hoy, umbrales) + duplicadas(facturas, nombres, hoy) + proveedor_nuevo(facturas, nombres, hoy, umbrales)
    return sorted(alertas, key=lambda a: (SEVERIDADES[a["severidad"]], a["cliente"].lower(), a["tipo"]))


_CACHE: dict[int, tuple[float, list[dict]]] = {}


def detectar_cacheado(tenant_id: int, segundos: int = 600) -> list[dict]:
    """Como `detectar`, pero reutiliza el resultado de hace menos de `segundos` en este proceso: para los sitios que lo piden a menudo (resumen, ficha) en despachos grandes. La pantalla de alertas siempre calcula en vivo."""
    import time
    ahora = time.monotonic()
    hit = _CACHE.get(tenant_id)
    if hit and ahora - hit[0] < segundos:
        return hit[1]
    res = detectar(tenant_id)
    _CACHE[tenant_id] = (ahora, res)
    return res


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
    if a["tipo"] == "iva_desviado":
        return (_("El IVA de %(c)s se sale de lo habitual este trimestre", c=a["cliente"]),
                _("Lleva %(r)s y por la media de los trimestres anteriores (%(m)s) cabría esperar %(e)s.", r=_eur(d["real"]), m=_eur(d["media"]), e=_eur(d["esperado"])))
    if a["tipo"] == "sin_entrar_portal":
        return (_("%(c)s tiene documentos pedidos y no entra al portal", c=a["cliente"]),
                _("Última entrada: %(f)s.", f=d["ultimo"]) if d["ultimo"] else _("No ha entrado nunca."))
    if a["tipo"] == "proveedor_nuevo":
        return (_("Proveedor nuevo con un importe alto en %(c)s", c=a["cliente"]),
                _("%(p)s: %(i)s el %(f)s; es la primera vez que aparece.", p=d["proveedor"], i=_eur(d["importe"]), f=d["fecha"]))
    return (_("Modelo %(m)s de %(c)s sin presentar", m=a["modelo"], c=a["cliente"]),
            _("La fecha límite pasó hace %(n)s días.", n=d["dias"]))


def clave(a: dict) -> str:
    """Un identificador estable de la alerta (regla + cliente + lo que la provoca) para poder referirse a ella desde un formulario sin guardarla en ninguna tabla."""
    return ":".join(str(x) for x in (a["tipo"], a["cliente_id"], a.get("factura_id") or a.get("vencimiento_id") or ""))
