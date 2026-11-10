"""Lectura previa de la factura en el portal: al elegir una foto o un PDF, el cliente puede ver qué datos lee la IA (quién la emite, número, fecha, total) antes de enviarla y
darse cuenta de una foto cortada o ilegible. Es opcional y está **apagada** por defecto: la enciende el despacho, porque la lectura se hace con el modelo y la clave de la persona
responsable del cliente (cuenta como una consulta de IA del despacho) y la factura sale hacia ese modelo antes de que nadie del despacho la haya visto. No guarda nada: si el cliente
la envía, entra como siempre, pendiente de que el despacho la lea y la revise."""
from __future__ import annotations

from . import db, lectura_facturas, verticales

TIPOS_XML = ("application/xml", "text/xml")                                # la factura electrónica (Facturae, UBL): se lee sin IA
TIPOS = ("image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf") + TIPOS_XML
MAX_BYTES = 8 * 1024 * 1024


def activa(tenant_id: int) -> bool:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT lectura_previa FROM portal_recordatorios_config WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    return bool(f and f["lectura_previa"])


def fijar(tenant_id: int, activar: bool) -> None:
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_recordatorios_config SET lectura_previa = ? WHERE tenant_id = ?", (1 if activar else 0, tenant_id)).rowcount
        if not n:
            cfg = db.CONFIG_RECORDATORIOS_DEFECTO
            conn.execute("INSERT INTO portal_recordatorios_config (tenant_id, dias_antes, dias_despues, avisar_equipo, asunto, cuerpo, actualizado_en, lectura_previa) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (tenant_id, ",".join(str(x) for x in cfg["dias_antes"]), "", int(cfg["avisar_equipo"]), "", "", db.now_iso(), 1 if activar else 0))
        conn.commit()
    finally:
        conn.close()


def lector_de(cliente) -> int | None:
    """La persona del despacho cuya IA hace la lectura: quien lleva al cliente y, si no tiene IA preparada, la primera de coordinación o dirección que sí."""
    candidatos = [cliente["responsable_id"]] if cliente["responsable_id"] else []
    conn = db.get_connection()
    try:
        candidatos += [r["id"] for r in conn.execute("SELECT u.id FROM usuarios u WHERE " + db.sql_supervisor() + " ORDER BY u.id", (cliente["tenant_id"], cliente["tenant_id"])).fetchall()]
    finally:
        conn.close()
    return next((u for u in candidatos if lectura_facturas.configurada(u)), None)


def disponible(cliente) -> bool:
    return bool(cliente is not None and verticales.esta_activo(cliente["tenant_id"], "contabilizacion") and activa(cliente["tenant_id"]) and lector_de(cliente) is not None)


def con_avisos_del_cliente(cliente, r: dict) -> dict:
    """Añade a lo leído lo que el cliente debe saber antes de enviar: no se ve el número, el NIF no supera su dígito de control, la factura parece de otra empresa o la gestoría ya la tiene (`avisos`:
    numero · nif_dudoso · otra_empresa · repetida). Solo avisa: enviarla sigue siendo posible."""
    from . import facturas_contables as fc
    from .fiscal_modelos.validacion_apuntes import nif_espanol_valido
    avisos = set(r.get("avisos") or [])
    nif, receptor, propio = fc._nif(r.get("nif")), fc._nif(r.get("receptor_nif")), fc._nif(cliente["nif"])
    if r.get("fuente") not in ("xml", "qr") and not r.get("numero"):
        avisos.add("numero")
    if nif and nif_espanol_valido(nif) is False:
        avisos.add("nif_dudoso")
    if propio and (nif or receptor) and propio not in (nif, receptor) and r.get("fuente") not in ("xml", "qr"):
        avisos.add("otra_empresa")
    if nif and r.get("numero") and fc.factura_igual(cliente["id"], nif, r["numero"]):
        avisos.add("repetida")
    return {**r, "avisos": sorted(avisos)}


def leer_gratis(cliente, contenido: bytes, tipo_mime: str) -> dict | None:
    """Lo que trae el propio archivo (factura electrónica o QR), sin IA: lo ve cualquier cliente con facturas, tenga o no activada la lectura previa. None si no trae nada de eso."""
    if cliente is None or not verticales.esta_activo(cliente["tenant_id"], "contabilizacion") or tipo_mime not in TIPOS or not contenido or len(contenido) > MAX_BYTES:
        return None
    r = lectura_facturas.previsualizar_gratis(contenido, tipo_mime)
    return con_avisos_del_cliente(cliente, r) if r else None


def leer(cliente, contenido: bytes, tipo_mime: str) -> dict:
    """Lo que se lee de ese archivo: primero lo exacto (XML, QR) y, si no hay, lo que lee la IA. `ValueError` con un mensaje apto para el cliente si no se puede."""
    if not disponible(cliente):
        raise ValueError("La lectura previa no está disponible.")
    if tipo_mime not in TIPOS or not contenido or len(contenido) > MAX_BYTES:
        raise ValueError("Ese archivo no se puede leer aquí.")
    exacta = lectura_facturas.previsualizar_gratis(contenido, tipo_mime)
    if exacta:
        return con_avisos_del_cliente(cliente, exacta)
    if tipo_mime in TIPOS_XML:
        raise ValueError("Ese archivo no es una factura electrónica que podamos leer aquí. Puedes enviarlo igualmente: tu gestoría lo mirará.")
    return con_avisos_del_cliente(cliente, lectura_facturas.previsualizar(lector_de(cliente), contenido, tipo_mime))
