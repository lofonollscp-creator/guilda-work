"""Derechos de las personas y retención (RGPD): exportar todo lo que el despacho guarda de un cliente y vaciar la papelera con constancia.
Lo gestionan los responsables del despacho. Cada exportación y cada vaciado quedan anotados en `registro_rgpd` (quién, cuándo, cuánto), sin copiar el contenido.

Lo que NO hace: borrar definitivamente un cliente o un expediente. Eso arrastra datos de los módulos de negocio y tiene plazos legales de conservación
(obligaciones fiscales, secreto profesional) que decide cada despacho; hoy se retira a la papelera y se vacía solo lo que cuelga de ella (documentos, plazos y horas)."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import db, nucleo

DIAS_PERMITIDOS = (0, 30, 90, 365)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS registro_rgpd (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    usuario_id INTEGER,
    tipo TEXT NOT NULL,
    detalle TEXT NOT NULL,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_registro_rgpd_tenant ON registro_rgpd(tenant_id, id DESC);
"""


def _anotar(conn, tenant_id: int, usuario_id: int | None, tipo: str, detalle: str) -> None:
    conn.execute("INSERT INTO registro_rgpd (tenant_id, usuario_id, tipo, detalle, creado_en) VALUES (?, ?, ?, ?, ?)", (tenant_id, usuario_id, tipo, detalle[:300], db.now_iso()))


def exportar_cliente(tenant_id: int, usuario_id: int, supervisor: bool, cliente_id: int) -> dict | None:
    """Todo lo que el despacho guarda de un cliente, en un diccionario listo para JSON. Respeta la visibilidad (un expediente confidencial al que quien exporta no
    tiene acceso no aparece). Los documentos van con sus datos, no con el contenido. None si el cliente no existe en este despacho."""
    from . import almacen_documentos        # tardío: el almacén importa este módulo para su esquema
    c = nucleo.obtener_cliente(tenant_id, cliente_id)
    if c is None:
        return None
    exps, _ = nucleo.listar_expedientes(tenant_id, usuario_id, supervisor, cliente_id=cliente_id, limite=500)
    datos = {
        "generado_en": db.now_iso(),
        "cliente": {k: c[k] for k in c.keys() if k not in ("tenant_id",)},
        "etiquetas": nucleo.etiquetas_de(cliente_id),
        "contactos": [dict(x) for x in nucleo.listar_contactos(tenant_id, cliente_id)],
        "expedientes": [{k: x[k] for k in ("id", "titulo", "tipo", "estado", "referencia", "creado_en", "actualizado_en") if k in x.keys()} for x in exps],
        "plazos": [{k: p.get(k) for k in ("id", "titulo", "fecha_limite", "estado", "expediente_id", "notas")} for p in nucleo.listar_plazos(tenant_id, usuario_id, supervisor, cliente_id=cliente_id, limite=1000)],
        "horas": [dict(p) for p in nucleo.listar_partes(tenant_id, usuario_id, supervisor, ver_todo=supervisor, cliente_id=cliente_id, limite=1000)],
        "documentos": [{k: d.get(k) for k in ("id", "nombre_archivo", "tipo_mime", "tamano_bytes", "categoria", "origen", "creado_en")} for d in almacen_documentos.listar(tenant_id, usuario_id, cliente_id=cliente_id, limite=1000)],
        "nota": "Los documentos se listan sin su contenido; se entregan por separado.",
    }
    if c["cliente_fiscal_id"]:
        from . import laboral
        datos["trabajadores"] = [{k: v for k, v in t.items() if k not in ("tenant_id", "nif_normalizado", "papelera_en")} for t in laboral.listar(tenant_id, c["cliente_fiscal_id"])]
    conn = db.get_connection()
    try:
        _anotar(conn, tenant_id, usuario_id, "exportacion", f"cliente #{cliente_id}")
        conn.commit()
    finally:
        conn.close()
    return datos


def vaciar_papelera(tenant_id: int, usuario_id: int, dias: int) -> dict:
    """Borra DEFINITIVAMENTE lo que lleva en la papelera más de `dias` días (0 = todo lo que haya): documentos, plazos y partes de horas. Anota cuántos.
    Los documentos se sobrescriben en el fichero de la base de datos (no quedan restos en claro)."""
    if dias not in DIAS_PERMITIDOS:
        raise ValueError("Elige un plazo válido.")
    corte = (datetime.now() - timedelta(days=dias)).isoformat(timespec="microseconds") if dias else "9999"
    conn = db.get_connection()
    try:
        conn.execute("PRAGMA secure_delete = ON")
        cuenta = {}
        for tabla in ("documentos", "plazos", "partes_tiempo", "trabajadores_cliente"):
            cur = conn.execute(f"DELETE FROM {tabla} WHERE tenant_id = ? AND papelera_en IS NOT NULL AND papelera_en < ?", (tenant_id, corte))
            cuenta[tabla] = cur.rowcount
        _anotar(conn, tenant_id, usuario_id, "vaciado", f"papelera de más de {dias} días: " + ", ".join(f"{k}={v}" for k, v in cuenta.items()))
        conn.commit()
        if cuenta["documentos"]:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        return cuenta
    finally:
        conn.close()


def registro(tenant_id: int, limite: int = 50) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute(
            "SELECT r.*, COALESCE(NULLIF(p.nombre_mostrado, ''), u.email) AS persona FROM registro_rgpd r LEFT JOIN usuarios u ON u.id = r.usuario_id "
            "LEFT JOIN usuario_perfil p ON p.usuario_id = r.usuario_id WHERE r.tenant_id = ? ORDER BY r.id DESC LIMIT ?", (tenant_id, max(1, min(limite, 500)))).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    conn.execute("DELETE FROM registro_rgpd WHERE tenant_id = ?", (tenant_id,))
