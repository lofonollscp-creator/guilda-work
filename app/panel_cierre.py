"""«Qué falta para cerrar» (F1): por cada cliente del despacho y trimestre, en qué punto está su contabilización (por leer, por revisar, listas para exportar, exportadas sin confirmar en a3) y cuántos días
quedan para el plazo de presentación. Es una vista sobre `facturas_contables`: no guarda nada. La confirmación en a3 solo se exige a los clientes que ya la usan (alguna factura suya confirmada)."""
from __future__ import annotations

from datetime import date, timedelta

from . import acceso, db, facturas_contables as fc, facturas_periodicas, fiscal_conciliacion

MESES_DE_HISTORIAL = 6                  # cuántos meses atrás se mira para saber si un cliente suele entregar facturas
MESES_PARA_SER_HABITUAL = 3             # con facturas en al menos tantos de esos meses se le considera un cliente que entrega cada mes
DIA_DEL_MES_PARA_AVISAR = 10            # no se avisa antes: es normal que a principios de mes no haya llegado nada todavía
DIAS_SIN_CONFIRMAR = 7                  # una exportada que lleva tanto sin confirmarse en a3 es sospechosa: ¿se llegó a importar el fichero?
PLAZO_DEL_TRIMESTRE = {1: (4, 20), 2: (7, 20), 3: (10, 20), 4: (1, 30)}        # mes y día de presentación del modelo 303 (el del cuarto trimestre es de enero del año siguiente)


def plazo(trimestre: str) -> date:
    fc.rango_del_trimestre(trimestre)
    anio, t = int(trimestre[:4]), int(trimestre[-1])
    mes, dia = PLAZO_DEL_TRIMESTRE[t]
    return date(anio + (t == 4), mes, dia)


def trimestre_actual(hoy: date | None = None) -> str:
    hoy = hoy or date.today()
    return f"{hoy.year}-T{(hoy.month - 1) // 3 + 1}"


def trimestre_anterior(hoy: date | None = None) -> str:
    """El que se está cerrando ahora: el anterior al que corre (en enero, abril, julio y octubre es el de la presentación)."""
    hoy = hoy or date.today()
    t = (hoy.month - 1) // 3
    return f"{hoy.year - (t == 0)}-T{t or 4}"


def _mes_anterior(mes: str, n: int) -> str:
    a, m = int(mes[:4]), int(mes[5:7])
    m -= n
    while m < 1:
        m += 12
        a -= 1
    return f"{a:04d}-{m:02d}"


def sin_entregas(tenant_id: int, hoy: date | None = None) -> dict[int, int]:
    """Los clientes que suelen mandar facturas (en al menos 3 de los 6 meses anteriores) y este mes aún no han mandado ninguna, pasado el día 10: {cliente_fiscal_id: meses con facturas}. Cuenta las anotadas
    por cualquier vía (portal, correo, a mano): lo que importa es que lleguen. No escribe nada."""
    hoy = hoy or date.today()
    if hoy.day < DIA_DEL_MES_PARA_AVISAR:
        return {}
    actual = f"{hoy.year:04d}-{hoy.month:02d}"
    desde = _mes_anterior(actual, MESES_DE_HISTORIAL) + "-01"
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT cliente_fiscal_id, substr(creado_en, 1, 7) AS mes FROM facturas_contables WHERE tenant_id = ? AND creado_en >= ? AND estado != 'descartada' "
                             "GROUP BY cliente_fiscal_id, substr(creado_en, 1, 7)", (tenant_id, desde)).fetchall()
    finally:
        conn.close()
    meses: dict[int, set[str]] = {}
    for f in filas:
        meses.setdefault(f["cliente_fiscal_id"], set()).add(f["mes"])
    return {cid: len(m - {actual}) for cid, m in meses.items() if actual not in m and len(m) >= MESES_PARA_SER_HABITUAL}


def panel(tenant_id: int, usuario_id: int, trimestre: str | None = None, hoy: date | None = None) -> dict:
    """{trimestre, plazo, dias, clientes: [...], resumen}. Cada cliente: id, nombre, total, sin_leer, por_revisar, listas (revisadas), sin_confirmar, exportadas, usa_retorno, cerrado, listo, faltan.
    Los que tienen algo que hacer van primero y, entre ellos, los que más les falta."""
    hoy = hoy or date.today()
    trimestre = trimestre or trimestre_anterior(hoy)
    desde, hasta = fc.rango_del_trimestre(trimestre)
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT x.cliente_fiscal_id, c.nombre, COUNT(*) AS total, "
                             "SUM(CASE WHEN x.estado = 'pendiente' AND x.lectura IN ('pendiente', 'fallida') THEN 1 ELSE 0 END) AS sin_leer, "
                             "SUM(CASE WHEN x.estado = 'pendiente' AND COALESCE(x.lectura, '') NOT IN ('pendiente', 'fallida') THEN 1 ELSE 0 END) AS por_revisar, "
                             "SUM(CASE WHEN x.estado = 'revisada' THEN 1 ELSE 0 END) AS listas, SUM(CASE WHEN x.estado = 'exportada' THEN 1 ELSE 0 END) AS exportadas, "
                             "SUM(CASE WHEN x.estado = 'exportada' AND x.confirmada_en IS NULL THEN 1 ELSE 0 END) AS sin_confirmar, "
                             "SUM(CASE WHEN x.estado = 'exportada' AND x.confirmada_en IS NULL AND x.actualizado_en < ? THEN 1 ELSE 0 END) AS sin_confirmar_antiguas, "
                             "SUM(CASE WHEN x.estado IN ('pendiente', 'revisada') AND EXISTS (SELECT 1 FROM auditoria_eventos a WHERE a.tenant_id = x.tenant_id AND a.entidad = 'factura_contable' "
                             "AND a.accion = 'factura_contable.exportada' AND a.entidad_id = CAST(x.id AS TEXT)) THEN 1 ELSE 0 END) AS a_corregir "
                             "FROM facturas_contables x JOIN clientes_fiscales c ON c.id = x.cliente_fiscal_id WHERE x.tenant_id = ? AND x.fecha BETWEEN ? AND ? AND x.estado != 'descartada' "
                             "AND c.papelera_en IS NULL GROUP BY x.cliente_fiscal_id, c.nombre", ((hoy - timedelta(days=DIAS_SIN_CONFIRMAR)).isoformat(), tenant_id, desde, hasta)).fetchall()
        configurados = {r["cliente_fiscal_id"]: r["nombre"] for r in conn.execute(
            "SELECT k.cliente_fiscal_id, c.nombre FROM contabilidad_clientes k JOIN clientes_fiscales c ON c.id = k.cliente_fiscal_id WHERE k.tenant_id = ? AND k.a3_empresa IS NOT NULL AND c.papelera_en IS NULL", (tenant_id,))}
        rechazados = {r["cliente_fiscal_id"] for r in conn.execute("SELECT DISTINCT cliente_fiscal_id FROM contabilidad_lotes WHERE tenant_id = ? AND estado_a3 = 'rechazado'", (tenant_id,))}
        con_retorno = {r["cliente_fiscal_id"] for r in conn.execute("SELECT DISTINCT cliente_fiscal_id FROM facturas_contables WHERE tenant_id = ? AND confirmada_en IS NOT NULL", (tenant_id,))}
    finally:
        conn.close()
    silenciosos = sin_entregas(tenant_id, hoy)
    periodicas = facturas_periodicas.por_cliente(tenant_id, hoy)
    periodicas_trimestre = facturas_periodicas.por_cliente_del_trimestre(tenant_id, trimestre, hoy)
    desde_t, hasta_t = fc.rango_del_trimestre(trimestre)
    sin_pago = fiscal_conciliacion.sin_pago_por_cliente(tenant_id, date.fromisoformat(desde_t), date.fromisoformat(hasta_t), visibles)
    por_id = {f["cliente_fiscal_id"]: dict(f) for f in filas}
    for cid, nombre in configurados.items():
        por_id.setdefault(cid, {"cliente_fiscal_id": cid, "nombre": nombre, "total": 0, "sin_leer": 0, "por_revisar": 0, "listas": 0, "exportadas": 0, "sin_confirmar": 0, "sin_confirmar_antiguas": 0, "a_corregir": 0})
    cerrados = fc.periodos_cerrados_de_varios(tenant_id, {cid: {trimestre} for cid in por_id if visibles is None or cid in visibles})        # dos consultas para todos los clientes, no dos por cliente
    clientes = []
    for cid, c in por_id.items():
        if visibles is not None and cid not in visibles:
            continue
        c = {k: (v or 0) if k not in ("nombre", "cliente_fiscal_id") else v for k, v in c.items()}
        c["usa_retorno"] = cid in con_retorno
        c["fichero_rechazado"] = cid in rechazados
        if not c["usa_retorno"]:
            c["sin_confirmar"] = c["sin_confirmar_antiguas"] = 0
        c["cerrado"] = bool(cerrados.get(cid, {}).get(trimestre))
        c["faltan"] = c["sin_leer"] + c["por_revisar"] + c["listas"] + c["sin_confirmar"]        # `a_corregir` ya cuenta dentro de por revisar o de listas: son las reabiertas tras exportarlas
        c["listo"] = c["total"] > 0 and c["faltan"] == 0
        c["sin_facturas"] = c["total"] == 0
        c["periodicas_que_faltan"] = len(periodicas.get(cid, []))
        c["periodicas_trimestre"] = len(periodicas_trimestre.get(cid, []))                 # proveedores habituales sin factura en algún mes del trimestre que se cierra
        c["facturas_sin_pago"] = sin_pago.get(cid, 0)                                      # con extractos guardados que cubren el trimestre: facturas sin cobro o pago
        c["sin_entregas_este_mes"] = silenciosos.get(cid, 0)                              # >0 = suele entregar y este mes aún no ha mandado nada (los meses que lo hizo)
        clientes.append(c)
    clientes.sort(key=lambda c: (c["cerrado"], c["listo"], -c["faltan"], c["sin_facturas"] is False, c["nombre"].lower()))
    limite = plazo(trimestre)
    return {"trimestre": trimestre, "plazo": limite.isoformat(), "dias": (limite - hoy).days, "clientes": clientes,
            "resumen": {"clientes": len(clientes), "listos": sum(1 for c in clientes if c["listo"] or c["cerrado"]), "sin_facturas": sum(1 for c in clientes if c["sin_facturas"] and not c["cerrado"]), "sin_entregas": sum(1 for c in clientes if c["sin_entregas_este_mes"]),
                        "faltan": sum(c["faltan"] for c in clientes if not c["cerrado"])}}
