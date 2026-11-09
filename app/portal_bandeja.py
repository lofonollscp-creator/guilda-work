"""La bandeja del portal para el equipo: todo lo que los clientes están esperando que alguien del despacho atienda, en una sola lista y por orden de espera (lo que lleva más tiempo esperando, primero).

Recoge lo que hoy está repartido por varias pantallas: mensajes y solicitudes de gestiones nuevos, documentos que un cliente ha enviado para una petición, cuestionarios respondidos por revisar, citas por confirmar y dossiers por validar.
Cada línea lleva a donde se atiende. No guarda nada: se calcula al abrirla, y cada persona ve solo los clientes que puede ver (las oficinas). Se puede filtrar por «mis clientes»."""
from __future__ import annotations

from datetime import datetime

from flask import url_for

from . import acceso, db

TIPOS = ("mensaje", "solicitud", "documentos", "cuestionario", "cita", "dossier")
PREFIJO_SOLICITUD = "Solicitud: "


def _dias(desde: str | None, ahora: datetime) -> int:
    try:
        return max(0, (ahora - datetime.fromisoformat((desde or "")[:19])).days)
    except ValueError:
        return 0


def listar(tenant_id: int, usuario_id: int, solo_mios: bool = False, tipo: str | None = None, ahora: datetime | None = None) -> list[dict]:
    """[{tipo, titulo, cliente_id, cliente, desde, dias, responsable, url}] de lo pendiente, lo más antiguo primero."""
    ahora = ahora or datetime.now()
    conn = db.get_connection()
    try:
        clientes = {f["id"]: dict(f) for f in conn.execute("SELECT c.id, c.nombre, c.responsable_id, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS responsable FROM clientes_fiscales c "
                                                           "LEFT JOIN usuarios u ON u.id = c.responsable_id LEFT JOIN usuario_perfil pf ON pf.usuario_id = c.responsable_id WHERE c.tenant_id = ? AND c.papelera_en IS NULL", (tenant_id,)).fetchall()}
        items: list[dict] = []
        for f in conn.execute("SELECT c.id, c.asunto, c.cliente_fiscal_id, MIN(m.creado_en) AS desde FROM portal_conversaciones c JOIN portal_conversaciones_mensajes m ON m.conversacion_id = c.id AND m.tenant_id = c.tenant_id "
                              "WHERE c.tenant_id = ? AND c.estado = 'abierta' AND m.de = 'cliente' AND m.leido_equipo = 0 GROUP BY c.id, c.asunto, c.cliente_fiscal_id", (tenant_id,)).fetchall():
            es_solicitud = str(f["asunto"]).startswith(PREFIJO_SOLICITUD)
            items.append({"tipo": "solicitud" if es_solicitud else "mensaje", "titulo": str(f["asunto"])[len(PREFIJO_SOLICITUD):] if es_solicitud else f["asunto"], "cliente_id": f["cliente_fiscal_id"], "desde": f["desde"],
                          "url": url_for("fiscal.editar_cliente", cliente_id=f["cliente_fiscal_id"]) + f"#conversacion-{f['id']}"})
        for f in conn.execute("SELECT id, titulo, cliente_fiscal_id, COALESCE(enviada_en, creado_en) AS desde FROM portal_peticiones WHERE tenant_id = ? AND estado = 'enviada'", (tenant_id,)).fetchall():
            items.append({"tipo": "documentos", "titulo": f["titulo"], "cliente_id": f["cliente_fiscal_id"], "desde": f["desde"], "url": url_for("fiscal.editar_cliente", cliente_id=f["cliente_fiscal_id"]) + "#peticiones"})
        for f in conn.execute("SELECT id, titulo, cliente_fiscal_id, COALESCE(respondido_en, creado_en) AS desde FROM portal_cuestionarios WHERE tenant_id = ? AND estado = 'respondido'", (tenant_id,)).fetchall():
            items.append({"tipo": "cuestionario", "titulo": f["titulo"], "cliente_id": f["cliente_fiscal_id"], "desde": f["desde"], "url": url_for("fiscal.editar_cliente", cliente_id=f["cliente_fiscal_id"]) + "#cuestionarios"})
        for f in conn.execute("SELECT id, cliente_fiscal_id, motivo, creado_en AS desde FROM portal_citas WHERE tenant_id = ? AND estado = 'solicitada'", (tenant_id,)).fetchall():
            items.append({"tipo": "cita", "titulo": f["motivo"], "cliente_id": f["cliente_fiscal_id"], "desde": f["desde"], "url": url_for("fiscal.citas_portal")})
        for f in conn.execute("SELECT id, cliente_fiscal_id, desde, hasta, COALESCE(pedido_en, creado_en) AS espera FROM portal_dossiers WHERE tenant_id = ? AND estado = 'pendiente'", (tenant_id,)).fetchall():
            items.append({"tipo": "dossier", "titulo": f"{f['desde']} – {f['hasta']}", "cliente_id": f["cliente_fiscal_id"], "desde": f["espera"], "url": url_for("fiscal.dossiers_pendientes")})
    finally:
        conn.close()
    visibles: dict[int, bool] = {}
    salida = []
    for it in items:
        c = clientes.get(it["cliente_id"])
        if c is None or (tipo and it["tipo"] != tipo) or (solo_mios and c["responsable_id"] != usuario_id):
            continue
        if it["cliente_id"] not in visibles:
            visibles[it["cliente_id"]] = acceso.puede_ver_cliente(tenant_id, usuario_id, it["cliente_id"])
        if not visibles[it["cliente_id"]]:
            continue
        salida.append({**it, "cliente": c["nombre"], "responsable": c["responsable"] or "", "dias": _dias(it["desde"], ahora)})
    return sorted(salida, key=lambda x: x["desde"] or "")


def cuentas(items: list[dict]) -> dict[str, int]:
    c = {t: 0 for t in TIPOS}
    for i in items:
        c[i["tipo"]] += 1
    return c
