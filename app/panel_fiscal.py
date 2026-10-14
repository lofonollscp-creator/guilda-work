"""Panel del control fiscal (especificación de control fiscal, secciones 3 y 14): qué hay que mirar hoy, cómo está repartida la carga y cómo se cumple.

Reglas de la especificación que se respetan aquí:
- **Todo riesgo explica su causa y ofrece una acción** (cada elemento trae `causa` y un enlace de acción).
- **«Sin información» no es «correcto»**: un indicador sin muestra devuelve `None`, no 100 %; y los clientes sin responsable o sin certificado cubren se cuentan aparte.
- **Muestra y exclusiones a la vista**: cada porcentaje trae `n` (tamaño de muestra), el periodo y lo que se ha dejado fuera (no aplica / anuladas).
- **El ámbito es el de quien mira**: con oficinas, cada persona ve solo sus clientes (`acceso.clientes_visibles`); la dirección ve todo. El auditor ve lo mismo que lee.
- Un panel no promete ausencia de sanciones: mide el trabajo del despacho, no su resultado ante la administración."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import acceso, certificados, db, obligaciones, traspasos

DIAS_PROXIMOS = 7
DIAS_INDICADOR = 90
LIMITE_LISTA = 25


def _marcas(n: int) -> str:
    return ",".join("?" * n) or "NULL"


def construir(tenant_id: int, usuario_id: int, hoy: date | None = None) -> dict:
    hoy = hoy or date.today()
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        filtro, p = "", []
        if visibles is not None:
            filtro, p = f" AND v.cliente_fiscal_id IN ({_marcas(len(visibles))})", list(visibles)
        filas = conn.execute(
            "SELECT v.id, v.cliente_fiscal_id, v.modelo, v.periodo, substr(v.fecha_limite, 1, 10) AS limite, v.fase, v.bloqueada, v.bloqueo_motivo, v.presentada_tarde, v.usuario_id AS preparador, "
            "c.nombre AS cliente, c.oficina_id, c.responsable_id, o.nombre AS oficina FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id "
            "LEFT JOIN oficinas o ON o.id = c.oficina_id WHERE v.tenant_id = ? AND v.papelera_en IS NULL AND c.papelera_en IS NULL" + filtro, [tenant_id, *p]).fetchall()
        cf, cp = "", []
        if visibles is not None:
            cf, cp = f" AND c.id IN ({_marcas(len(visibles))})", list(visibles)
        clientes = conn.execute("SELECT c.id, c.nombre, c.oficina_id, c.responsable_id, o.nombre AS oficina FROM clientes_fiscales c LEFT JOIN oficinas o ON o.id = c.oficina_id "
                                "WHERE c.tenant_id = ? AND c.papelera_en IS NULL" + cf, [tenant_id, *cp]).fetchall()
    finally:
        conn.close()
    hoy_s, prox_s = hoy.isoformat(), (hoy + timedelta(days=DIAS_PROXIMOS)).isoformat()
    activas = [f for f in filas if f["fase"] in obligaciones.ACTIVAS]

    def item(f, causa: str, **extra) -> dict:
        return {"vencimiento_id": f["id"], "cliente_id": f["cliente_fiscal_id"], "cliente": f["cliente"], "modelo": f["modelo"], "periodo": f["periodo"], "fecha_limite": f["limite"], "fase": f["fase"],
                "responsable": traspasos._nombre(f["responsable_id"]), "causa": causa, "url": f"/fiscal/vencimientos/{f['id']}/editar", **extra}

    vencidas = sorted((item(f, "vencida", dias=(hoy - date.fromisoformat(f["limite"])).days) for f in activas if f["limite"] < hoy_s), key=lambda x: x["fecha_limite"])
    proximas = sorted((item(f, "bloqueada" if f["bloqueada"] else "proxima", dias=(date.fromisoformat(f["limite"]) - hoy).days, motivo=f["bloqueo_motivo"])
                       for f in activas if hoy_s <= f["limite"] <= prox_s), key=lambda x: x["fecha_limite"])
    bloqueadas = [item(f, "bloqueada", motivo=f["bloqueo_motivo"], dias=(date.fromisoformat(f["limite"]) - hoy).days) for f in activas if f["bloqueada"]]
    en_revision = [item(f, "para_revisar") for f in activas if f["fase"] == "en_revision"] if acceso.puede_autorizar(tenant_id, usuario_id) else []
    tr = [t for t in traspasos.listar(tenant_id, usuario_id, estado="pendiente")]
    for t in tr:
        t["urgente"] = t["dias_al_vencimiento"] is not None and t["dias_al_vencimiento"] <= traspasos.DIAS_ESCALADO
        t["para_mi"] = t["a_usuario_id"] == usuario_id
    # Certificados: solo quien los gestiona los ve; «cobertura desconocida» se muestra como riesgo, nunca como correcto.
    ve_cert = certificados.puede_gestionar(usuario_id, tenant_id)
    riesgos_cert, cert_resumen = [], None
    if ve_cert:
        riesgos_cert = [r for r in certificados.riesgos(tenant_id) if visibles is None or r["cliente_fiscal_id"] in visibles]
        cert_resumen = certificados.resumen(tenant_id)
    # Carga: por oficina y por responsable (con las obligaciones activas, las que vencen pronto y las vencidas).
    def carga(clave_f, clave_c, nombre) -> list[dict]:
        grupos: dict = {}
        for c in clientes:
            g = grupos.setdefault(c[clave_c], {"id": c[clave_c], "nombre": nombre(c), "clientes": 0, "activas": 0, "proximas": 0, "vencidas": 0, "bloqueadas": 0})
            g["clientes"] += 1
        for f in activas:
            g = grupos.get(f[clave_f])
            if g is None:
                continue
            g["activas"] += 1
            g["proximas"] += 1 if hoy_s <= f["limite"] <= prox_s else 0
            g["vencidas"] += 1 if f["limite"] < hoy_s else 0
            g["bloqueadas"] += 1 if f["bloqueada"] else 0
        return sorted(grupos.values(), key=lambda g: (-g["vencidas"], -g["proximas"], -g["activas"]))
    por_responsable = carga("responsable_id", "responsable_id", lambda c: traspasos._nombre(c["responsable_id"]))
    por_oficina = carga("oficina_id", "oficina_id", lambda c: c["oficina"]) if acceso.tiene_oficinas(tenant_id) else []
    # Indicadores con muestra y exclusiones.
    desde = (hoy - timedelta(days=DIAS_INDICADOR)).isoformat()
    periodo = [f for f in filas if desde <= f["limite"] < hoy_s]
    excluidas = [f for f in periodo if f["fase"] in ("no_aplica", "anulada")]
    aplicables = [f for f in periodo if f["fase"] not in ("no_aplica", "anulada")]
    a_tiempo = [f for f in aplicables if f["fase"] in obligaciones.PRESENTADAS and not f["presentada_tarde"]]
    sin_resp = [c for c in clientes if c["responsable_id"] is None]
    indicadores = {
        "en_plazo": {"n": len(aplicables), "buenas": len(a_tiempo), "porcentaje": round(100 * len(a_tiempo) / len(aplicables)) if aplicables else None, "excluidas": len(excluidas), "dias": DIAS_INDICADOR},
        "clientes": {"n": len(clientes), "sin_responsable": len(sin_resp)},
        "bloqueadas": len(bloqueadas),
        "sin_evidencia": None,
    }
    conn = db.get_connection()
    try:
        ids_pres = [f["id"] for f in filas if f["fase"] in obligaciones.PRESENTADAS]
        if ids_pres:
            con = {r[0] for r in conn.execute(f"SELECT DISTINCT vencimiento_id FROM obligaciones_evidencias WHERE vencimiento_id IN ({_marcas(len(ids_pres))})", ids_pres)}
            indicadores["sin_evidencia"] = {"n": len(ids_pres), "sin": len(ids_pres) - len(con)}
        if ve_cert:
            tot = conn.execute("SELECT COUNT(*) FROM certificados WHERE tenant_id = ? AND estado_operativo NOT IN ('archivado', 'sustituido')", (tenant_id,)).fetchone()[0]
            con_c = conn.execute("SELECT COUNT(*) FROM certificados WHERE tenant_id = ? AND estado_operativo NOT IN ('archivado', 'sustituido') AND custodio_id IS NOT NULL", (tenant_id,)).fetchone()[0]
            indicadores["certificados"] = {"n": tot, "con_custodio": con_c}
    finally:
        conn.close()
    return {
        "generado_en": datetime.now().isoformat(timespec="minutes"), "hoy": hoy_s, "ambito": "todo" if visibles is None else "parcial", "dias_proximos": DIAS_PROXIMOS,
        "hoy_lista": {"vencidas": vencidas[:LIMITE_LISTA], "proximas": proximas[:LIMITE_LISTA], "para_revisar": en_revision[:LIMITE_LISTA]},
        "totales": {"vencidas": len(vencidas), "proximas": len(proximas), "bloqueadas": len(bloqueadas), "para_revisar": len(en_revision), "traspasos": len(tr), "riesgos_certificados": len(riesgos_cert)},
        "bloqueadas": bloqueadas[:LIMITE_LISTA], "traspasos": tr, "riesgos_certificados": riesgos_cert[:LIMITE_LISTA], "certificados": cert_resumen,
        "carga_por_responsable": por_responsable, "carga_por_oficina": por_oficina, "indicadores": indicadores,
    }
