"""Puesta en marcha guiada de un despacho (tenant): pasos que se calculan en caliente a partir de los datos
(nunca se registran aparte, así no pueden desincronizarse). Lo usan la tarjeta del inicio de la app y el
backoffice (ficha del tenant y Customer Journey)."""
from __future__ import annotations

from . import db

# (clave, etiqueta en español para el backoffice, endpoint de la app al que lleva el paso)
PASOS = (
    ("clientes", "Crear el primer cliente fiscal", "fiscal.clientes"),
    ("vencimientos", "Generar los vencimientos fiscales", "fiscal.generar_vencimientos_masivo"),
    ("correo", "Conectar una cuenta de correo", "correo.cuentas"),
    ("recordatorios", "Revisar los recordatorios al cliente", "fiscal.recordatorios"),
    ("portal", "Dar acceso al portal a un cliente", "fiscal.clientes"),
    ("presentado", "Marcar un vencimiento como presentado", "fiscal.vencimientos"),
)


def estado(tenant_id: int) -> dict[str, bool]:
    conn = db.get_connection()
    try:
        f = conn.execute(
            """SELECT
                 EXISTS(SELECT 1 FROM clientes_fiscales WHERE tenant_id = :t AND papelera_en IS NULL) AS clientes,
                 EXISTS(SELECT 1 FROM vencimientos_fiscales WHERE tenant_id = :t AND papelera_en IS NULL) AS vencimientos,
                 EXISTS(SELECT 1 FROM correo_cuentas c JOIN usuarios u ON u.id = c.usuario_id WHERE u.tenant_id = :t) AS correo,
                 EXISTS(SELECT 1 FROM portal_recordatorios_config WHERE tenant_id = :t) AS recordatorios,
                 EXISTS(SELECT 1 FROM clientes_fiscales_accesos a JOIN clientes_fiscales c ON c.id = a.cliente_fiscal_id WHERE c.tenant_id = :t) AS portal,
                 EXISTS(SELECT 1 FROM vencimientos_fiscales WHERE tenant_id = :t AND estado = 'presentado' AND papelera_en IS NULL) AS presentado""",
            {"t": tenant_id},
        ).fetchone()
    finally:
        conn.close()
    return {clave: bool(f[clave]) for clave, _e, _u in PASOS}


def resumen(tenant_id: int) -> dict:
    hechos_por_clave = estado(tenant_id)
    pasos = [{"clave": c, "etiqueta": e, "endpoint": u, "hecho": hechos_por_clave[c]} for c, e, u in PASOS]
    hechos = sum(1 for p in pasos if p["hecho"])
    pendiente = next((p for p in pasos if not p["hecho"]), None)
    return {
        "pasos": pasos, "hechos": hechos, "total": len(pasos), "pct": hechos * 100 // len(pasos),
        "completo": hechos == len(pasos), "siguiente": pendiente["etiqueta"] if pendiente else None,
    }
