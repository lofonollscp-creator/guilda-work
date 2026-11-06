"""Justificantes de movimientos del banco: el despacho tiene un movimiento del extracto sin factura y le pregunta al cliente qué es; el cliente contesta desde su portal con la factura, «es un tiquet», «es personal» o «no sé».

**Solo se guarda lo que el despacho decide preguntar**: la conciliación (`fiscal_conciliacion`) no guarda extractos y aquí tampoco; al pedir justificantes se guardan únicamente fecha, importe y concepto de los movimientos elegidos, que es lo mínimo
para que el cliente sepa de qué le hablan. El mismo registro sirve para los tiquets que el cliente anota por su cuenta (`origen = cliente`).

Ciclo: `pendiente` (esperando al cliente) → `con_factura` · `tiquet` · `personal` · `no_se` (contestado) → `resuelto` (lo cierra el despacho); `descartado` si se pidió por error. El despacho puede volver a pedirlo.
Importes en céntimos con signo, como en el extracto: un pago es negativo."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date

from . import antivirus, auditoria, db, facturas_contables as fc

ACCIONES_CLIENTE = ("factura", "tiquet", "personal", "no_se")
ESTADO_DE_ACCION = {"factura": "con_factura", "tiquet": "tiquet", "personal": "personal", "no_se": "no_se"}
CONTESTADOS = ("con_factura", "tiquet", "personal", "no_se")
MAX_POR_PEDIDO = 200
MAX_CONCEPTO = 140
MAX_COMENTARIO = 500
MAX_ABIERTOS_DEL_CLIENTE = 100                    # tiquets sin cerrar que un cliente puede acumular


def _plano(texto: str) -> str:
    s = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def huella(fecha: str, importe: int, concepto: str) -> str:
    return hashlib.sha256(f"{fecha}|{importe}|{_plano(concepto)}".encode()).hexdigest()


def _movimiento_valido(m: dict) -> tuple[str, int, str]:
    try:
        fecha = date.fromisoformat(str(m.get("fecha") or "")[:10]).isoformat()
        importe = int(m.get("importe"))
    except (TypeError, ValueError):
        raise ValueError("Un movimiento no tiene fecha o importe válidos.") from None
    concepto = re.sub(r"\s+", " ", str(m.get("concepto") or "")).strip()[:MAX_CONCEPTO]
    if importe == 0 or abs(importe) > 10**11:
        raise ValueError("Un movimiento tiene un importe no válido.")
    if not concepto:
        concepto = "(sin concepto)"
    return fecha, importe, concepto


# --- El despacho pregunta ---------------------------------------------------------------------------------------------------------------------------

def pedir(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, movimientos: list[dict]) -> dict:
    """Pide al cliente que explique estos movimientos (`{fecha, importe, concepto}`). Los que ya se le preguntaron no se repiten. Avisa por correo si hay algo nuevo. `{nuevos, repetidos, avisado}`."""
    fc._cliente(tenant_id, usuario_id, cliente_fiscal_id)
    if not movimientos:
        raise ValueError("Elige al menos un movimiento.")
    if len(movimientos) > MAX_POR_PEDIDO:
        raise ValueError(f"Pide como máximo {MAX_POR_PEDIDO} movimientos de una vez.")
    validos = [_movimiento_valido(m) for m in movimientos]
    nuevos = repetidos = 0
    ahora = db.now_iso()
    conn = db.get_connection()
    try:
        for fecha, importe, concepto in dict.fromkeys(validos):
            h = huella(fecha, importe, concepto)
            if conn.execute("SELECT 1 FROM justificantes_pendientes WHERE tenant_id = ? AND cliente_fiscal_id = ? AND huella = ?", (tenant_id, cliente_fiscal_id, h)).fetchone():
                repetidos += 1
                continue
            conn.execute("INSERT INTO justificantes_pendientes (tenant_id, cliente_fiscal_id, origen, fecha, importe_centimos, concepto, huella, pedido_por, creado_en) VALUES (?, ?, 'extracto', ?, ?, ?, ?, ?, ?)",
                         (tenant_id, cliente_fiscal_id, fecha, importe, concepto, h, usuario_id, ahora))
            nuevos += 1
        auditoria.registrar(tenant_id, usuario_id, "justificantes.pedir", "cliente_fiscal", cliente_fiscal_id, {"nuevos": nuevos, "repetidos": repetidos}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return {"nuevos": nuevos, "repetidos": repetidos, "avisado": _avisar_al_cliente(tenant_id, cliente_fiscal_id, nuevos) if nuevos else False}


def _avisar_al_cliente(tenant_id: int, cliente_fiscal_id: int, cuantos: int) -> bool:
    from . import notificaciones_email as ne, portal_recordatorios
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    url = portal_recordatorios.url_portal("/portal/justificantes")
    if cliente is None or not cliente["email"] or not url or not ne.configurado():
        return False
    _ = portal_recordatorios._
    try:
        with portal_recordatorios._en_idioma(cliente["idioma"] if "idioma" in cliente.keys() else "es"):
            ne.enviar_aviso_portal(cliente["email"], _("Tu gestoría necesita que le expliques unos movimientos del banco"),
                                   [_("Hola, %(nombre)s.", nombre=cliente["nombre"]),
                                    _("Al preparar tus impuestos hay movimientos de tu banco para los que tu gestoría no tiene factura o justificante."),
                                    _("Entra y cuéntanos qué son: puedes subir la factura, indicar que es un tiquet o que es algo personal.")],
                                   _("Ver los movimientos"), url, tenant_id=tenant_id)
        return True
    except ne.ErrorNotificacionesEmail:
        return False


def listar(tenant_id: int, usuario_id: int, *, cliente_fiscal_id: int | None = None, estado: str | None = None, limite: int = 500) -> list[dict]:
    """Lo que ve el despacho (solo los clientes que la persona puede ver), lo contestado sin cerrar primero."""
    from . import acceso
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    donde, p = ["j.tenant_id = ?"], [tenant_id]
    if cliente_fiscal_id:
        donde.append("j.cliente_fiscal_id = ?"); p.append(cliente_fiscal_id)
    if estado:
        donde.append("j.estado = ?"); p.append(estado)
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute(
            "SELECT j.*, c.nombre AS cliente_nombre FROM justificantes_pendientes j JOIN clientes_fiscales c ON c.id = j.cliente_fiscal_id WHERE " + " AND ".join(donde) +
            " ORDER BY CASE j.estado WHEN 'pendiente' THEN 1 WHEN 'resuelto' THEN 3 WHEN 'descartado' THEN 4 ELSE 0 END, j.fecha DESC, j.id DESC LIMIT ?", (*p, limite))]
    finally:
        conn.close()
    return [f for f in filas if visibles is None or f["cliente_fiscal_id"] in visibles]


def cambiar_estado(tenant_id: int, usuario_id: int, justificante_id: int, nuevo: str) -> None:
    """`resuelto` y `descartado` cierran; `pendiente` vuelve a pedírselo al cliente (borra su respuesta)."""
    if nuevo not in ("resuelto", "descartado", "pendiente"):
        raise ValueError("Estado no válido.")
    conn = db.get_connection()
    try:
        j = conn.execute("SELECT id, cliente_fiscal_id, estado FROM justificantes_pendientes WHERE id = ? AND tenant_id = ?", (justificante_id, tenant_id)).fetchone()
        if j is None:
            raise ValueError("No encontrado.")
        fc._cliente(tenant_id, usuario_id, j["cliente_fiscal_id"])
        if nuevo == "pendiente":
            conn.execute("UPDATE justificantes_pendientes SET estado = 'pendiente', respondido_en = NULL, resuelto_por = NULL, resuelto_en = NULL, comentario = NULL, factura_id = NULL, documento_id = NULL WHERE id = ? AND tenant_id = ?",
                         (justificante_id, tenant_id))
        else:
            conn.execute("UPDATE justificantes_pendientes SET estado = ?, resuelto_por = ?, resuelto_en = ? WHERE id = ? AND tenant_id = ?", (nuevo, usuario_id, db.now_iso(), justificante_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, f"justificantes.{nuevo}", "justificante", justificante_id, {"antes": j["estado"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def para_el_cierre(tenant_id: int, cliente_fiscal_id: int, desde: str, hasta: str) -> dict:
    """Para el cierre del trimestre: cuántos están sin contestar y cuántos contestados sin cerrar (por la fecha del movimiento)."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT estado, COUNT(*) AS n FROM justificantes_pendientes WHERE tenant_id = ? AND cliente_fiscal_id = ? AND fecha >= ? AND fecha <= ? GROUP BY estado", (tenant_id, cliente_fiscal_id, desde, hasta)).fetchall()
    finally:
        conn.close()
    n = {f["estado"]: f["n"] for f in filas}
    return {"sin_contestar": n.get("pendiente", 0), "por_cerrar": sum(n.get(e, 0) for e in CONTESTADOS)}


def contar_abiertos(tenant_id: int, usuario_id: int) -> int:
    """Para la insignia del despacho: justificantes contestados por los clientes y aún sin cerrar."""
    return sum(1 for j in listar(tenant_id, usuario_id) if j["estado"] in CONTESTADOS)


def documento_de(tenant_id: int, usuario_id: int, justificante_id: int):
    """El archivo de un tiquet (para el despacho): `(nombre, tipo, bytes)` o None."""
    from . import almacen_documentos
    conn = db.get_connection()
    try:
        j = conn.execute("SELECT cliente_fiscal_id, documento_id FROM justificantes_pendientes WHERE id = ? AND tenant_id = ?", (justificante_id, tenant_id)).fetchone()
    finally:
        conn.close()
    if j is None or not j["documento_id"] or not fc.acceso.puede_ver_cliente(tenant_id, usuario_id, j["cliente_fiscal_id"]):
        return None
    d = almacen_documentos.leer_de_cliente_fiscal(tenant_id, j["cliente_fiscal_id"], j["documento_id"], usuario_id)
    return (d["nombre_archivo"], d.get("tipo_mime") or "application/octet-stream", d["contenido"]) if d else None


# --- El cliente contesta --------------------------------------------------------------------------------------------------------------------------------

def del_cliente(cliente_fiscal_id: int) -> list[dict]:
    """Todo lo suyo, lo pendiente primero."""
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    if cliente is None:
        return []
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT id, origen, fecha, importe_centimos, concepto, estado, factura_id, comentario, creado_en, respondido_en FROM justificantes_pendientes "
                                              "WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado != 'descartado' ORDER BY CASE estado WHEN 'pendiente' THEN 0 ELSE 1 END, fecha DESC, id DESC LIMIT 300",
                                              (cliente["tenant_id"], cliente_fiscal_id))]
    finally:
        conn.close()


def pendientes_del_cliente(cliente_fiscal_id: int) -> list[dict]:
    return [j for j in del_cliente(cliente_fiscal_id) if j["estado"] == "pendiente"]


def _guardar_archivo(cliente: dict, archivo) -> int:
    nombre, mime, contenido = archivo
    antivirus.exigir_limpio(nombre, contenido, cliente["tenant_id"], cliente["id"])
    return fc.adjuntar(cliente["tenant_id"], cliente["id"], None, nombre, mime, contenido)


def responder(cliente_fiscal_id: int, justificante_id: int, accion: str, comentario: str = "", archivos: list | None = None) -> None:
    """El cliente explica un movimiento. `factura` exige el archivo (entra como factura por leer, como cualquier otra que suba); `tiquet` admite foto; `personal` y `no_se` no necesitan nada."""
    if accion not in ACCIONES_CLIENTE:
        raise ValueError("Elige una opción.")
    comentario = re.sub(r"[ \t]+", " ", comentario or "").strip()
    if len(comentario) > MAX_COMENTARIO:
        raise ValueError(f"El comentario no puede pasar de {MAX_COMENTARIO} caracteres.")
    archivos = [a for a in (archivos or []) if a and a[2]]
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    if cliente is None:
        raise ValueError("Cliente no encontrado.")
    conn = db.get_connection()
    try:
        j = conn.execute("SELECT * FROM justificantes_pendientes WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ?", (justificante_id, cliente["tenant_id"], cliente_fiscal_id)).fetchone()
    finally:
        conn.close()
    if j is None or j["estado"] != "pendiente":
        raise ValueError("Ese movimiento ya no está pendiente.")
    factura_id = documento_id = None
    if accion == "factura":
        if not archivos:
            raise ValueError("Sube la factura (foto o PDF).")
        tipo = "recibida" if j["importe_centimos"] < 0 else "emitida"
        ids = fc.subir_desde_portal(cliente_fiscal_id, tipo, archivos[:fc.MAX_ARCHIVOS_POR_SUBIDA], nota=f"Justificante del movimiento del {j['fecha']} ({j['importe_centimos'] / 100:.2f} €): {j['concepto']}"[:300])
        factura_id = ids[0] if ids else None
    elif accion == "tiquet" and archivos:
        documento_id = _guardar_archivo(cliente, archivos[0])
    ahora = db.now_iso()
    conn = db.get_connection()
    try:
        conn.execute("UPDATE justificantes_pendientes SET estado = ?, comentario = ?, factura_id = ?, documento_id = ?, respondido_en = ? WHERE id = ? AND tenant_id = ?",
                     (ESTADO_DE_ACCION[accion], comentario or None, factura_id, documento_id, ahora, justificante_id, cliente["tenant_id"]))
        auditoria.registrar(cliente["tenant_id"], None, "justificantes.contestado", "justificante", justificante_id, {"accion": accion}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    fc.avisar_al_equipo(cliente, f"{cliente['nombre']} ha explicado un movimiento del banco", f"{j['concepto']} · {j['importe_centimos'] / 100:.2f} €", f"/contabilidad/justificantes?cliente_id={cliente_fiscal_id}",
                        {"justificante_id": justificante_id})


def anotar_tiquet(cliente_fiscal_id: int, fecha: str, importe, concepto: str, archivo=None) -> int:
    """El cliente anota por su cuenta un gasto del que no tiene factura (un tiquet): queda como `tiquet` para que el despacho lo vea. `importe` es positivo (lo que gastó)."""
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    if cliente is None:
        raise ValueError("Cliente no encontrado.")
    try:
        fecha_iso = date.fromisoformat(str(fecha or "")[:10])
    except ValueError:
        raise ValueError("Indica la fecha del gasto.") from None
    if fecha_iso > date.today():
        raise ValueError("La fecha del gasto no puede ser futura.")
    centimos = fc.importe_a_centimos(importe, permitir_cero=False)
    if centimos <= 0:
        raise ValueError("Indica el importe del gasto.")
    concepto = re.sub(r"\s+", " ", concepto or "").strip()[:MAX_CONCEPTO]
    if not concepto:
        raise ValueError("Indica en qué fue el gasto.")
    h = huella(fecha_iso.isoformat(), -centimos, concepto)
    conn = db.get_connection()
    try:
        if conn.execute("SELECT COUNT(*) FROM justificantes_pendientes WHERE tenant_id = ? AND cliente_fiscal_id = ? AND origen = 'cliente' AND estado = 'tiquet'", (cliente["tenant_id"], cliente_fiscal_id)).fetchone()[0] >= MAX_ABIERTOS_DEL_CLIENTE:
            raise ValueError("Tienes muchos tiquets pendientes de revisar: espera a que tu gestoría los procese.")
        if conn.execute("SELECT 1 FROM justificantes_pendientes WHERE tenant_id = ? AND cliente_fiscal_id = ? AND huella = ?", (cliente["tenant_id"], cliente_fiscal_id, h)).fetchone():
            raise ValueError("Ya anotaste ese gasto.")
    finally:
        conn.close()
    documento_id = _guardar_archivo(cliente, archivo) if archivo and archivo[2] else None
    ahora = db.now_iso()
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO justificantes_pendientes (tenant_id, cliente_fiscal_id, origen, fecha, importe_centimos, concepto, estado, documento_id, huella, creado_en, respondido_en) VALUES (?, ?, 'cliente', ?, ?, ?, 'tiquet', ?, ?, ?, ?)",
                           (cliente["tenant_id"], cliente_fiscal_id, fecha_iso.isoformat(), -centimos, concepto, documento_id, h, ahora, ahora))
        auditoria.registrar(cliente["tenant_id"], None, "justificantes.tiquet", "justificante", cur.lastrowid, {}, conn=conn)
        conn.commit()
        nuevo = cur.lastrowid
    finally:
        conn.close()
    fc.avisar_al_equipo(cliente, f"{cliente['nombre']} ha anotado un tiquet", f"{concepto} · {centimos / 100:.2f} €", f"/contabilidad/justificantes?cliente_id={cliente_fiscal_id}", {"justificante_id": nuevo})
    return nuevo
