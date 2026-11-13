"""Buzón de facturas por correo (AC6): el cliente reenvía sus facturas a una dirección suya y llegan como facturas por leer.

Solo funciona para los clientes que el despacho active uno a uno (por defecto ninguno ve ni usa esto). El despacho elige una cuenta de correo suya como buzón (p. ej. facturas@su-dominio) y a cada
cliente activado se le asigna un código: su dirección es `facturas+CODIGO@su-dominio` (direcciones con «+», que los servidores entregan en el mismo buzón). Al sincronizar esa cuenta se miran los
mensajes recientes dirigidos a una de esas direcciones y, si quien escribe es de confianza (el titular o un contacto del cliente, o alguien del equipo), sus PDF e imágenes pasan a ser facturas por leer
y se ponen en la cola de lectura. Lo demás (remitente desconocido, sin adjuntos válidos) se anota y no se hace nada: nunca se responde solo (sería un medio de enviar correo a nombre del despacho a terceros).
Sin tablas nuevas: las columnas `buzon_*` de los ajustes y la auditoría (`factura_contable.por_correo`) como registro y como marca de «ya procesado»."""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta
from email.utils import getaddresses, parseaddr

from . import acceso, auditoria, db, facturas_contables as fc, portal_personas

logger = logging.getLogger("guilda")

ACCION = "factura_contable.por_correo"
DIAS_A_MIRAR = 14
MAXIMO_POR_PASADA = 100
MIN_BYTES_IMAGEN = 15_000                       # una imagen más pequeña es casi seguro el logotipo de una firma, no una factura
MIME_VALIDOS = {"application/pdf", "image/png", "image/jpeg", "application/xml", "text/xml"}
_CODIGO = re.compile(r"\+([a-z0-9]{6,12})@", re.I)


# --- Ajustes ----------------------------------------------------------------------------------------------------------------------------------------

def config(tenant_id: int) -> dict:
    """{cuenta_id, direccion}: la cuenta de correo que hace de buzón y su dirección base (facturas@dominio). Vacío = sin configurar."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT buzon_cuenta_id, buzon_direccion FROM contabilidad_despacho WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    return {"cuenta_id": f["buzon_cuenta_id"] if f else None, "direccion": (f["buzon_direccion"] if f else None) or ""}


def guardar_config(tenant_id: int, usuario_id: int, cuenta_id: int | None, direccion: str) -> None:
    from . import db_correo
    direccion = parseaddr(direccion or "")[1].strip().lower()
    if cuenta_id:
        cuenta = db_correo.obtener_cuenta_correo(usuario_id, int(cuenta_id))
        if cuenta is None:
            raise ValueError("Esa cuenta de correo no es tuya.")
        if not direccion:
            raise ValueError("Indica la dirección del buzón (por ejemplo facturas@tudominio.com).")
        if "@" not in direccion or "+" in direccion.split("@")[0]:
            raise ValueError("La dirección del buzón debe ser de la forma facturas@tudominio.com, sin «+».")
    else:
        cuenta_id, direccion = None, ""
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO contabilidad_despacho (tenant_id) VALUES (?) ON CONFLICT (tenant_id) DO NOTHING", (tenant_id,))
        conn.execute("UPDATE contabilidad_despacho SET buzon_cuenta_id = ?, buzon_direccion = ? WHERE tenant_id = ?", (int(cuenta_id) if cuenta_id else None, direccion or None, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "factura_contable.buzon_configurado", "contabilidad_despacho", tenant_id, {"cuenta_id": cuenta_id, "direccion": direccion}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def configurado(tenant_id: int) -> bool:
    c = config(tenant_id)
    return bool(c["cuenta_id"] and c["direccion"])


# --- Por cliente ------------------------------------------------------------------------------------------------------------------------------------

def estado_del_cliente(tenant_id: int, cliente_fiscal_id: int) -> dict:
    """{activo, codigo, direccion}: la dirección solo existe si el despacho tiene buzón y el cliente lo tiene activado."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT buzon_activo, buzon_codigo FROM contabilidad_clientes WHERE tenant_id = ? AND cliente_fiscal_id = ?", (tenant_id, cliente_fiscal_id)).fetchone()
    finally:
        conn.close()
    activo, codigo = bool(f and f["buzon_activo"]), (f["buzon_codigo"] if f else None)
    c = config(tenant_id)
    direccion = None
    if activo and codigo and c["direccion"]:
        local, dominio = c["direccion"].split("@", 1)
        direccion = f"{local}+{codigo}@{dominio}"
    return {"activo": activo, "codigo": codigo, "direccion": direccion}


def activar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, activo: bool) -> dict:
    """Activa o desactiva el buzón de un cliente. El código no cambia al desactivar y reactivar (la dirección que el cliente ya tiene sigue valiendo)."""
    if not acceso.puede_ver_cliente(tenant_id, usuario_id, cliente_fiscal_id):
        raise ValueError("No tienes acceso a ese cliente.")
    if activo and not configurado(tenant_id):
        raise ValueError("Primero configura el buzón del despacho (cuenta de correo y dirección) en Ajustes de contabilidad.")
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO contabilidad_clientes (tenant_id, cliente_fiscal_id) VALUES (?, ?) ON CONFLICT DO NOTHING", (tenant_id, cliente_fiscal_id))
        actual = conn.execute("SELECT buzon_codigo FROM contabilidad_clientes WHERE tenant_id = ? AND cliente_fiscal_id = ?", (tenant_id, cliente_fiscal_id)).fetchone()
        codigo = actual["buzon_codigo"] or (secrets.token_hex(4) if activo else None)
        conn.execute("UPDATE contabilidad_clientes SET buzon_activo = ?, buzon_codigo = ? WHERE tenant_id = ? AND cliente_fiscal_id = ?", (1 if activo else 0, codigo, tenant_id, cliente_fiscal_id))
        auditoria.registrar(tenant_id, usuario_id, "factura_contable.buzon_cliente", "cliente_fiscal", cliente_fiscal_id, {"activo": bool(activo)}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return estado_del_cliente(tenant_id, cliente_fiscal_id)


def fijar_aviso_lectura(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, activo: bool) -> None:
    """Activa o desactiva el aviso al cliente cuando una factura suya del portal queda leída (por defecto, no)."""
    if not acceso.puede_ver_cliente(tenant_id, usuario_id, cliente_fiscal_id):
        raise ValueError("No tienes acceso a ese cliente.")
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO contabilidad_clientes (tenant_id, cliente_fiscal_id) VALUES (?, ?) ON CONFLICT DO NOTHING", (tenant_id, cliente_fiscal_id))
        conn.execute("UPDATE contabilidad_clientes SET avisar_lectura = ? WHERE tenant_id = ? AND cliente_fiscal_id = ?", (1 if activo else 0, tenant_id, cliente_fiscal_id))
        auditoria.registrar(tenant_id, usuario_id, "factura_contable.aviso_lectura_cliente", "cliente_fiscal", cliente_fiscal_id, {"activo": bool(activo)}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def activados(tenant_id: int) -> list[dict]:
    """Los clientes con el buzón activado (para el aviso de la pantalla de ajustes)."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT k.cliente_fiscal_id, c.nombre, k.buzon_codigo FROM contabilidad_clientes k JOIN clientes_fiscales c ON c.id = k.cliente_fiscal_id "
                             "WHERE k.tenant_id = ? AND k.buzon_activo = 1 AND c.papelera_en IS NULL ORDER BY c.nombre", (tenant_id,)).fetchall()
    finally:
        conn.close()
    return [{"cliente_fiscal_id": f["cliente_fiscal_id"], "nombre": f["nombre"], "codigo": f["buzon_codigo"]} for f in filas]


# --- Recepción --------------------------------------------------------------------------------------------------------------------------------------

def _autorizados(tenant_id: int, cliente_fiscal_id: int) -> set[str]:
    """Las direcciones de las que se aceptan facturas de ese cliente: su titular y sus contactos del portal, y las personas del equipo del despacho."""
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    emails = {p["email"].lower() for p in portal_personas.listar(cliente)} if cliente is not None else set()
    conn = db.get_connection()
    try:
        emails |= {r["email"].lower() for r in conn.execute("SELECT email FROM usuarios WHERE tenant_id = ?", (tenant_id,)).fetchall() if r["email"]}
    finally:
        conn.close()
    return emails


def _clientes_por_codigo(tenant_id: int) -> dict[str, int]:
    return {c["codigo"].lower(): c["cliente_fiscal_id"] for c in activados(tenant_id) if c["codigo"]}


def _ya_procesados(tenant_id: int) -> set[str]:
    desde = (datetime.now() - timedelta(days=DIAS_A_MIRAR + 2)).isoformat(timespec="seconds")[:10]
    return {e["entidad_id"] for e in auditoria.listar(tenant_id, accion=ACCION, desde=desde, limite=2000)}


def _anotar(tenant_id: int, usuario_id: int, mensaje_id: int, cliente_fiscal_id: int | None, resultado: str, **extra) -> None:
    auditoria.registrar(tenant_id, usuario_id, ACCION, "correo_mensaje", mensaje_id, {"cliente_fiscal_id": cliente_fiscal_id, "resultado": resultado, **extra})


def procesar_cuenta(cuenta_id: int) -> dict:
    """Mira los mensajes recientes de la cuenta de buzón de un despacho y convierte en facturas por leer los adjuntos de los dirigidos a un cliente activado. Nunca lanza.
    Devuelve {facturas, mensajes, rechazados}."""
    resumen = {"facturas": 0, "mensajes": 0, "rechazados": 0}
    try:
        from . import db_correo
        cuenta = db_correo.obtener_cuenta_correo_por_id(cuenta_id)
        if cuenta is None:
            return resumen
        usuario_id = cuenta["usuario_id"]
        tenant = db.tenant_de_usuario(usuario_id)
        if tenant is None:
            return resumen
        tenant_id = tenant["id"]
        from .bd import contexto
        with contexto.en_despacho(tenant_id):
            c = config(tenant_id)
            if c["cuenta_id"] != cuenta_id or not c["direccion"]:
                return resumen                                                   # esta cuenta no es el buzón de facturas del despacho
            por_codigo = _clientes_por_codigo(tenant_id)
            if not por_codigo:
                return resumen
            hechos = _ya_procesados(tenant_id)
            desde = (datetime.now() - timedelta(days=DIAS_A_MIRAR)).isoformat(timespec="seconds")
            mensajes = [m for m in db_correo.listar_mensajes_correo(cuenta_id, limite=MAXIMO_POR_PASADA * 3) if (m["fecha"] or "") >= desde or not m["fecha"]]
            for m in mensajes[:MAXIMO_POR_PASADA * 3]:
                if str(m["id"]) in hechos:
                    continue
                cliente_id = _cliente_del_mensaje(m, por_codigo)
                if cliente_id is None:
                    continue                                                     # no es para ningún cliente activado: no es asunto de este buzón
                r = _procesar_mensaje(tenant_id, usuario_id, cuenta_id, m, cliente_id)
                resumen["mensajes"] += 1
                resumen["facturas"] += r["facturas"]
                resumen["rechazados"] += 1 if r["rechazado"] else 0
    except Exception:  # noqa: BLE001 -- una pasada fallida nunca debe estropear la sincronización del correo
        logger.warning("No se pudo procesar el buzón de facturas de la cuenta %s", cuenta_id, exc_info=True)
    return resumen


def _cliente_del_mensaje(m, por_codigo: dict[str, int]) -> int | None:
    destinos = ", ".join(str(m[k] or "") for k in ("destinatarios", "cc") if k in m.keys())
    for _nombre, direccion in getaddresses([destinos]):
        hallado = _CODIGO.search(direccion or "")
        if hallado and hallado.group(1).lower() in por_codigo:
            return por_codigo[hallado.group(1).lower()]
    return None


def _procesar_mensaje(tenant_id: int, usuario_id: int, cuenta_id: int, m, cliente_id: int) -> dict:
    from . import db_correo, ia_trabajos, lectura_facturas
    remitente = parseaddr(m["remitente"] or "")[1].strip().lower()
    if remitente not in _autorizados(tenant_id, cliente_id):
        _anotar(tenant_id, usuario_id, m["id"], cliente_id, "remitente_no_autorizado", remitente=remitente[:120])
        return {"facturas": 0, "rechazado": True}
    archivos, descartados = [], 0
    for a in db_correo.listar_adjuntos_correo(m["id"]):
        mime = (a["tipo_mime"] or "").lower().split(";")[0]
        if mime not in MIME_VALIDOS or (mime.startswith("image/") and (a["tamano_bytes"] or 0) < MIN_BYTES_IMAGEN) or (a["tamano_bytes"] or 0) > fc.MAX_ADJUNTO_BYTES:
            descartados += 1
            continue
        completo = db_correo.obtener_adjunto_correo(a["id"])
        if completo is not None and completo["contenido"]:
            archivos.append((a["nombre_archivo"] or "factura", mime, bytes(completo["contenido"])))
    if not archivos:
        _anotar(tenant_id, usuario_id, m["id"], cliente_id, "sin_adjuntos_validos", descartados=descartados)
        return {"facturas": 0, "rechazado": False}
    try:
        f = fc._cliente(tenant_id, usuario_id, cliente_id)
        ids = fc._subir(tenant_id, usuario_id, f, "recibida", archivos[:fc.MAX_ARCHIVOS_POR_SUBIDA], "correo", f"Recibida por correo de {remitente}, pendiente de leer.")
    except ValueError as e:
        _anotar(tenant_id, usuario_id, m["id"], cliente_id, "no_se_pudo_anotar", motivo=str(e)[:200])
        return {"facturas": 0, "rechazado": False}
    if ids and lectura_facturas.configurada(usuario_id):
        try:
            ia_trabajos.encolar(tenant_id, usuario_id, "lectura", list(ids), datos={"proveedor": lectura_facturas.proveedor_de(usuario_id)})
        except Exception:  # noqa: BLE001 -- se quedan por leer y se pueden leer a mano
            logger.warning("No se pudo poner en cola la lectura de las facturas llegadas por correo", exc_info=True)
    _anotar(tenant_id, usuario_id, m["id"], cliente_id, "anotadas", facturas=len(ids), repetidas=getattr(ids, "repetidas", 0), descartados=descartados)
    return {"facturas": len(ids), "rechazado": False}


def registro(tenant_id: int, limite: int = 50) -> list[dict]:
    """Lo último que ha hecho el buzón (para la pantalla del despacho): [{fecha, cliente, resultado, detalle}]."""
    nombres = {c["cliente_fiscal_id"]: c["nombre"] for c in activados(tenant_id)}
    salida = []
    for e in auditoria.listar(tenant_id, accion=ACCION, limite=limite):
        d = e["detalle"] if isinstance(e["detalle"], dict) else {}
        salida.append({"fecha": e["creado_en"], "cliente": nombres.get(d.get("cliente_fiscal_id"), ""), "resultado": d.get("resultado", ""), "detalle": d})
    return salida


def metricas(tenant_id: int, dias: int = 30) -> dict:
    """Qué ha hecho el buzón en los últimos `dias` días y si la cuenta sigue sincronizando: {mensajes, facturas, rechazados, motivos, sin_adjuntos, fallos, ultima_sincronizacion, error, estado}.
    `estado`: sin_configurar, ok, atrasado (más de 2 horas sin sincronizar) o error (el último intento falló)."""
    from . import db_correo
    corte = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
    m = {"mensajes": 0, "facturas": 0, "rechazados": 0, "sin_adjuntos": 0, "fallos": 0, "motivos": {}}
    for e in auditoria.listar(tenant_id, accion=ACCION, limite=1000):
        if (e["creado_en"] or "") < corte:
            continue
        d = e["detalle"] if isinstance(e["detalle"], dict) else {}
        r = d.get("resultado", "")
        m["mensajes"] += 1
        if r == "anotadas":
            m["facturas"] += int(d.get("facturas") or 0)
        elif r == "remitente_no_autorizado":
            m["rechazados"] += 1
            m["motivos"]["remitente_no_autorizado"] = m["motivos"].get("remitente_no_autorizado", 0) + 1
        elif r == "sin_adjuntos_validos":
            m["sin_adjuntos"] += 1
        else:
            m["fallos"] += 1
    c = config(tenant_id)
    m.update({"ultima_sincronizacion": None, "error": None, "estado": "sin_configurar"})
    if c["cuenta_id"] and c["direccion"]:
        cuenta = db_correo.obtener_cuenta_correo_por_id(c["cuenta_id"])
        if cuenta is not None:
            ultima, error = cuenta["ultima_sincronizacion"], cuenta["ultimo_error_sincronizacion"]
            m.update({"ultima_sincronizacion": ultima, "error": error})
            atrasada = not ultima or datetime.fromisoformat(str(ultima)[:19]) < datetime.now() - timedelta(hours=2)
            m["estado"] = "error" if error else "atrasado" if atrasada else "ok"
    return m
