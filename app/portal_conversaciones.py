"""Conversaciones libres entre el cliente y su gestoría (N3): hasta ahora el cliente solo podía escribir dentro de un modelo, una factura o un trabajo. Aquí cualquiera de los dos puede abrir un hilo
con su asunto —suelto o a propósito de una petición de documentos— y contestar en él mientras esté abierto. Los hilos salen en el buzón del portal junto a los demás y, para el equipo, en la ficha del
cliente. Cada mensaje lleva su marca de leído para cada lado (`leido_cliente` / `leido_equipo`), y el equipo puede cerrar el hilo cuando está resuelto (y reabrirlo, o lo reabre una respuesta nueva del cliente)."""
from __future__ import annotations

from datetime import datetime

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS portal_conversaciones (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    asunto TEXT NOT NULL,
    peticion_id INTEGER,
    estado TEXT NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'cerrada')),
    iniciada_por TEXT NOT NULL CHECK (iniciada_por IN ('cliente', 'despacho')),
    creado_en TEXT NOT NULL,
    actualizado_en TEXT NOT NULL,
    cerrada_en TEXT,
    cerrada_por INTEGER
);
CREATE INDEX IF NOT EXISTS idx_portal_conversaciones_cliente ON portal_conversaciones(tenant_id, cliente_fiscal_id, estado);

CREATE TABLE IF NOT EXISTS portal_conversaciones_mensajes (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversacion_id INTEGER NOT NULL,
    de TEXT NOT NULL CHECK (de IN ('cliente', 'despacho')),
    autor TEXT NOT NULL DEFAULT '',
    texto TEXT NOT NULL,
    creado_en TEXT NOT NULL,
    leido_cliente INTEGER NOT NULL DEFAULT 0,
    leido_equipo INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_portal_conversaciones_mensajes ON portal_conversaciones_mensajes(tenant_id, conversacion_id, id);

CREATE TABLE IF NOT EXISTS portal_conversaciones_adjuntos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    mensaje_id INTEGER NOT NULL,
    documento_id INTEGER NOT NULL,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_portal_conversaciones_adjuntos ON portal_conversaciones_adjuntos(tenant_id, mensaje_id);
"""

MAX_ASUNTO, MAX_TEXTO = 120, 2000
MAX_ABIERTAS = 20
MAX_ADJUNTOS = 3
MAX_BYTES = 8 * 1024 * 1024
MIME = ("application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "text/csv", "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
LADOS = ("cliente", "despacho")


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _limpio(texto: str | None, largo: int) -> str:
    return " ".join((texto or "").split())[:largo]


def _texto(texto: str | None) -> str:
    """El mensaje conserva los saltos de línea, sin pasarse de largo."""
    t = "\n".join(linea.rstrip() for linea in (texto or "").replace("\r\n", "\n").replace("\r", "\n").strip().split("\n"))
    return t[:MAX_TEXTO]


def iniciar(cliente, asunto: str, texto: str, de: str, autor: str = "", peticion_id: int | None = None, archivos: list | None = None, usuario_id: int | None = None) -> int:
    """Abre un hilo con su primer mensaje. `de`: «cliente» o «despacho»; `autor`: quien escribe (correo o nombre). `ValueError` con un mensaje legible si falta algo o hay demasiados hilos abiertos."""
    if de not in LADOS:
        raise ValueError("Quién escribe no es válido.")
    asunto = _limpio(asunto, MAX_ASUNTO)
    if len(asunto) < 3:
        raise ValueError("Escribe el asunto de la conversación (mínimo 3 caracteres).")
    texto = _texto(texto)
    if not texto:
        raise ValueError("Escribe el mensaje.")
    guardados = _guardar_archivos(cliente, archivos, de, usuario_id, asunto)
    ahora = _ahora()
    conn = db.get_connection()
    try:
        abiertas = conn.execute("SELECT COUNT(*) FROM portal_conversaciones WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado = 'abierta'", (cliente["tenant_id"], cliente["id"])).fetchone()[0]
        if abiertas >= MAX_ABIERTAS:
            raise ValueError("Hay demasiadas conversaciones abiertas: cierra o espera a que se resuelvan algunas.")
        if peticion_id is not None and not conn.execute("SELECT 1 FROM portal_peticiones WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ?", (peticion_id, cliente["tenant_id"], cliente["id"])).fetchone():
            peticion_id = None
        cur = conn.execute("INSERT INTO portal_conversaciones (tenant_id, cliente_fiscal_id, asunto, peticion_id, iniciada_por, creado_en, actualizado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (cliente["tenant_id"], cliente["id"], asunto, peticion_id, de, ahora, ahora))
        cid = cur.lastrowid
        mid = _insertar(conn, cliente["tenant_id"], cid, de, autor, texto, ahora)
        _enlazar(conn, cliente["tenant_id"], mid, guardados, ahora)
        conn.commit()
        return cid
    finally:
        conn.close()


def _insertar(conn, tenant_id: int, cid: int, de: str, autor: str, texto: str, ahora: str) -> int:
    cur = conn.execute("INSERT INTO portal_conversaciones_mensajes (tenant_id, conversacion_id, de, autor, texto, creado_en, leido_cliente, leido_equipo) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (tenant_id, cid, de, _limpio(autor, 120), texto, ahora, 1 if de == "cliente" else 0, 1 if de == "despacho" else 0))
    return cur.lastrowid


def _guardar_archivos(cliente, archivos, de: str, usuario_id: int | None, asunto: str) -> list[int]:
    """Valida y guarda en los documentos del cliente los archivos adjuntos a un mensaje (hasta 3 de 8 MB). Los del cliente pasan por el antivirus. Devuelve los ids de documento; `ValueError` si algo no vale
    (y no se ha guardado nada: se comprueban todos antes)."""
    validos = [a for a in (archivos or []) if a and a[2]]
    if not validos:
        return []
    from . import almacen_documentos, antivirus
    if len(validos) > MAX_ADJUNTOS:
        raise ValueError("Puedes adjuntar hasta 3 archivos por mensaje.")
    for nombre, mime, contenido in validos:
        if (mime or "").lower().split(";")[0] not in MIME or len(contenido) > MAX_BYTES:
            raise ValueError("Solo PDF, imágenes, hojas de cálculo o documentos de texto, de hasta 8 MB cada uno.")
    if de == "cliente":
        for nombre, mime, contenido in validos:
            antivirus.exigir_limpio(nombre, contenido, cliente["tenant_id"], cliente["id"])
    ids = []
    for nombre, mime, contenido in validos:
        mime = (mime or "").lower().split(";")[0]
        categoria = f"Conversación: {asunto}"[:80]
        if de == "cliente" or usuario_id is None:
            resultado, doc = almacen_documentos.guardar_de_cliente_fiscal_sin_usuario(cliente["tenant_id"], cliente["id"], nombre, mime, contenido, categoria)
        else:
            resultado, doc = almacen_documentos.guardar_de_cliente_fiscal(usuario_id, cliente["id"], nombre, mime, contenido, categoria=categoria)
        if resultado == "limite":
            raise ValueError("Se ha alcanzado el máximo de documentos de este cliente.")
        if resultado in ("ok", "duplicado") and doc is not None:
            ids.append(doc)
    if not ids:
        raise ValueError("No se ha podido guardar el archivo adjunto.")
    return ids


def _enlazar(conn, tenant_id: int, mensaje_id: int, documentos: list[int], ahora: str) -> None:
    for d in documentos:
        conn.execute("INSERT INTO portal_conversaciones_adjuntos (tenant_id, mensaje_id, documento_id, creado_en) VALUES (?, ?, ?, ?)", (tenant_id, mensaje_id, d, ahora))


def responder(cliente, cid: int, texto: str, de: str, autor: str = "", archivos: list | None = None, usuario_id: int | None = None) -> bool:
    """Añade un mensaje. Una respuesta del cliente reabre un hilo cerrado; el equipo no escribe en uno cerrado (primero lo reabre). False si el hilo no existe o no admite el mensaje."""
    if de not in LADOS:
        raise ValueError("Quién escribe no es válido.")
    texto = _texto(texto)
    if not texto:
        raise ValueError("Escribe el mensaje.")
    ahora = _ahora()
    conn = db.get_connection()
    try:
        c = conn.execute("SELECT estado, asunto FROM portal_conversaciones WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ?", (cid, cliente["tenant_id"], cliente["id"])).fetchone()
        if c is None or (c["estado"] == "cerrada" and de == "despacho"):
            return False
        guardados = _guardar_archivos(cliente, archivos, de, usuario_id, c["asunto"])
        mid = _insertar(conn, cliente["tenant_id"], cid, de, autor, texto, ahora)
        _enlazar(conn, cliente["tenant_id"], mid, guardados, ahora)
        conn.execute("UPDATE portal_conversaciones SET actualizado_en = ?, estado = 'abierta', cerrada_en = NULL, cerrada_por = NULL WHERE id = ? AND tenant_id = ?", (ahora, cid, cliente["tenant_id"]))
        conn.commit()
        return True
    finally:
        conn.close()


def obtener(cliente, cid: int) -> dict | None:
    """El hilo con todos sus mensajes (en orden), o None si no es de este cliente."""
    conn = db.get_connection()
    try:
        c = conn.execute("SELECT * FROM portal_conversaciones WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ?", (cid, cliente["tenant_id"], cliente["id"])).fetchone()
        if c is None:
            return None
        d = dict(c)
        d["mensajes"] = [dict(m) for m in conn.execute("SELECT id, de, autor, texto, creado_en, leido_cliente, leido_equipo FROM portal_conversaciones_mensajes WHERE tenant_id = ? AND conversacion_id = ? ORDER BY id",
                                                        (cliente["tenant_id"], cid))]
        for m in d["mensajes"]:
            m["adjuntos"] = [dict(a) for a in conn.execute(
                "SELECT a.documento_id, c.nombre_archivo AS nombre, c.nombre_cifrado, c.tipo_mime, c.tamano_bytes FROM portal_conversaciones_adjuntos a JOIN cliente_documentos c ON c.id = a.documento_id AND c.tenant_id = a.tenant_id "
                "WHERE a.tenant_id = ? AND a.mensaje_id = ? ORDER BY a.id", (cliente["tenant_id"], m["id"]))]
            for a in m["adjuntos"]:
                cifrado = a.pop("nombre_cifrado", None)
                if cifrado:
                    try:
                        from . import cifrado_despacho
                        a["nombre"] = cifrado_despacho.abrir_nombre(cliente["tenant_id"], cifrado) or a["nombre"]
                    except Exception:  # noqa: BLE001 -- con el despacho bloqueado se enseña el nombre genérico
                        pass
        return d
    finally:
        conn.close()


def listar(cliente, estado: str | None = None) -> list[dict]:
    """Los hilos del cliente (el de actividad más reciente primero) con el último mensaje y lo que cada lado tiene sin leer."""
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute(
            "SELECT c.id, c.asunto, c.peticion_id, c.estado, c.iniciada_por, c.creado_en, c.actualizado_en, "
            "(SELECT COUNT(*) FROM portal_conversaciones_mensajes m WHERE m.tenant_id = c.tenant_id AND m.conversacion_id = c.id) AS mensajes, "
            "(SELECT COUNT(*) FROM portal_conversaciones_mensajes m WHERE m.tenant_id = c.tenant_id AND m.conversacion_id = c.id AND m.de = 'despacho' AND m.leido_cliente = 0) AS sin_leer_cliente, "
            "(SELECT COUNT(*) FROM portal_conversaciones_mensajes m WHERE m.tenant_id = c.tenant_id AND m.conversacion_id = c.id AND m.de = 'cliente' AND m.leido_equipo = 0) AS sin_leer_equipo "
            "FROM portal_conversaciones c WHERE c.tenant_id = ? AND c.cliente_fiscal_id = ? " + ("AND c.estado = ? " if estado else "") + "ORDER BY c.actualizado_en DESC, c.id DESC",
            (cliente["tenant_id"], cliente["id"], *([estado] if estado else [])))]
        for f in filas:
            u = conn.execute("SELECT de, texto, creado_en FROM portal_conversaciones_mensajes WHERE tenant_id = ? AND conversacion_id = ? ORDER BY id DESC LIMIT 1", (cliente["tenant_id"], f["id"])).fetchone()
            f["ultimo_texto"], f["ultimo_de"], f["ultimo_en"] = u["texto"], u["de"], u["creado_en"]
        return filas
    finally:
        conn.close()


def marcar_leida(cliente, cid: int, lado: str) -> None:
    """Marca como leídos los mensajes que el otro lado le ha escrito a `lado` («cliente» o «equipo»)."""
    columna, de = ("leido_cliente", "despacho") if lado == "cliente" else ("leido_equipo", "cliente")
    conn = db.get_connection()
    try:
        conn.execute(f"UPDATE portal_conversaciones_mensajes SET {columna} = 1 WHERE tenant_id = ? AND conversacion_id = ? AND de = ? AND {columna} = 0", (cliente["tenant_id"], cid, de))
        conn.commit()
    finally:
        conn.close()


def cambiar_estado(cliente, cid: int, abierta: bool, por: int | None = None) -> bool:
    """Cierra (con quién lo cerró) o reabre un hilo. False si no existe o ya estaba así."""
    conn = db.get_connection()
    try:
        if abierta:
            n = conn.execute("UPDATE portal_conversaciones SET estado = 'abierta', cerrada_en = NULL, cerrada_por = NULL WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ? AND estado = 'cerrada'",
                             (cid, cliente["tenant_id"], cliente["id"])).rowcount
        else:
            n = conn.execute("UPDATE portal_conversaciones SET estado = 'cerrada', cerrada_en = ?, cerrada_por = ? WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ? AND estado = 'abierta'",
                             (_ahora(), por, cid, cliente["tenant_id"], cliente["id"])).rowcount
        conn.commit()
        return bool(n)
    finally:
        conn.close()


def sin_leer_cliente(cliente) -> int:
    """Mensajes de la gestoría que el cliente no ha leído en estos hilos (lo suma la insignia del buzón)."""
    conn = db.get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM portal_conversaciones_mensajes m JOIN portal_conversaciones c ON c.id = m.conversacion_id AND c.tenant_id = m.tenant_id "
                            "WHERE m.tenant_id = ? AND c.cliente_fiscal_id = ? AND m.de = 'despacho' AND m.leido_cliente = 0", (cliente["tenant_id"], cliente["id"])).fetchone()[0]
    finally:
        conn.close()


def sin_leer_equipo(tenant_id: int, cliente_fiscal_id: int | None = None) -> int:
    """Mensajes de clientes que el equipo no ha leído: de un cliente, o de todo el despacho."""
    conn = db.get_connection()
    try:
        sql = "SELECT COUNT(*) FROM portal_conversaciones_mensajes m JOIN portal_conversaciones c ON c.id = m.conversacion_id AND c.tenant_id = m.tenant_id WHERE m.tenant_id = ? AND m.de = 'cliente' AND m.leido_equipo = 0"
        args: list = [tenant_id]
        if cliente_fiscal_id is not None:
            sql += " AND c.cliente_fiscal_id = ?"
            args.append(cliente_fiscal_id)
        return conn.execute(sql, args).fetchone()[0]
    finally:
        conn.close()


def para_el_buzon(cliente) -> list[dict]:
    """Los hilos en el formato del buzón del portal (app/portal_buzon.py): tipo «conversacion», título, mensajes, sin leer y si espera la respuesta del cliente."""
    from flask import url_for
    return [{"tipo": "conversacion", "ref": h["id"], "titulo": h["asunto"], "url": url_for("portal_cliente.conversacion", conversacion_id=h["id"]), "mensajes": h["mensajes"], "sin_leer": h["sin_leer_cliente"],
             "ultimo_texto": h["ultimo_texto"], "ultimo_autor": "cliente" if h["ultimo_de"] == "cliente" else "gestoria", "ultimo_en": h["ultimo_en"], "cerrada": h["estado"] == "cerrada"} for h in listar(cliente)]


def adjunto_de(cliente, cid: int, documento_id: int) -> dict | None:
    """El documento adjunto a un mensaje de ESTA conversación de este cliente (con su contenido), o None. Es lo que descarga quien está en la conversación."""
    from . import almacen_documentos
    conn = db.get_connection()
    try:
        ok = conn.execute("SELECT 1 FROM portal_conversaciones_adjuntos a JOIN portal_conversaciones_mensajes m ON m.id = a.mensaje_id AND m.tenant_id = a.tenant_id "
                          "JOIN portal_conversaciones c ON c.id = m.conversacion_id AND c.tenant_id = m.tenant_id WHERE a.tenant_id = ? AND a.documento_id = ? AND c.id = ? AND c.cliente_fiscal_id = ?",
                          (cliente["tenant_id"], documento_id, cid, cliente["id"])).fetchone()
    finally:
        conn.close()
    return almacen_documentos.leer_de_cliente_fiscal(cliente["tenant_id"], cliente["id"], documento_id) if ok else None
