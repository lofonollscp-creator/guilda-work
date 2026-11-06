"""Peticiones de documentos: la gestoría le pide a un cliente algo concreto («extracto del 3T», «escritura de la oficina») con una fecha límite, el cliente lo sube desde su portal y la gestoría da la
petición por revisada o la reabre con una nota. Lo subido se guarda en los documentos del cliente como cualquier otro (con su categoría «Petición: …»); la petición solo lleva la cuenta.

Estados: `pendiente` (espera al cliente), `enviada` (el cliente ha subido algo y espera revisión), `revisada` (cerrada) y `cancelada`. Mientras esté `pendiente` el cliente recibe los recordatorios escalonados
de siempre (portal_avisos) y la ve en «Lo que tienes que hacer» de su inicio."""
from __future__ import annotations

from datetime import date, datetime

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS portal_peticiones (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    titulo TEXT NOT NULL,
    descripcion TEXT NOT NULL DEFAULT '',
    fecha_limite TEXT,
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'enviada', 'revisada', 'cancelada')),
    nota TEXT NOT NULL DEFAULT '',
    creado_por INTEGER,
    creado_en TEXT NOT NULL,
    enviada_en TEXT,
    revisada_en TEXT,
    revisada_por INTEGER
);
CREATE INDEX IF NOT EXISTS idx_portal_peticiones_cliente ON portal_peticiones(tenant_id, cliente_fiscal_id, estado);

CREATE TABLE IF NOT EXISTS portal_peticiones_documentos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    peticion_id INTEGER NOT NULL,
    documento_id INTEGER NOT NULL,
    subido_por TEXT NOT NULL DEFAULT '',
    creado_en TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_peticiones_documentos ON portal_peticiones_documentos(tenant_id, peticion_id, documento_id);
"""

ESTADOS = ("pendiente", "enviada", "revisada", "cancelada")
MAX_TITULO, MAX_DESCRIPCION, MAX_NOTA = 120, 600, 300
MAX_ABIERTAS = 25
MAX_ARCHIVOS = 10
MIME = ("application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "text/csv", "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
MAX_BYTES = 8 * 1024 * 1024


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _limpio(texto: str | None, largo: int) -> str:
    return " ".join((texto or "").split())[:largo]


def _fila(f) -> dict:
    d = dict(f)
    limite = d.get("fecha_limite")
    d["dias"] = (date.fromisoformat(limite) - date.today()).days if limite else None
    d["vencida"] = bool(d["estado"] == "pendiente" and d["dias"] is not None and d["dias"] < 0)
    return d


def crear(cliente, titulo: str, descripcion: str = "", fecha_limite: str | None = None, por: int | None = None) -> int:
    """Abre una petición para ese cliente. `ValueError` con un mensaje legible si falta el título, la fecha no vale o ya hay demasiadas abiertas."""
    titulo = _limpio(titulo, MAX_TITULO)
    if len(titulo) < 3:
        raise ValueError("Escribe qué documento necesitas (mínimo 3 caracteres).")
    limite = None
    if (fecha_limite or "").strip():
        try:
            limite = date.fromisoformat(fecha_limite.strip()[:10]).isoformat()
        except ValueError:
            raise ValueError("La fecha límite no es válida.") from None
    conn = db.get_connection()
    try:
        if conn.execute("SELECT COUNT(*) FROM portal_peticiones WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado IN ('pendiente', 'enviada')", (cliente["tenant_id"], cliente["id"])).fetchone()[0] >= MAX_ABIERTAS:
            raise ValueError("Este cliente ya tiene demasiadas peticiones abiertas: cierra alguna antes de pedir más.")
        cur = conn.execute("INSERT INTO portal_peticiones (tenant_id, cliente_fiscal_id, titulo, descripcion, fecha_limite, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (cliente["tenant_id"], cliente["id"], titulo, _limpio(descripcion, MAX_DESCRIPCION), limite, por, _ahora()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar(cliente, solo_abiertas: bool = False) -> list[dict]:
    """Las peticiones de ese cliente: primero lo que espera al cliente (por fecha límite), luego lo enviado y lo cerrado."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT p.*, (SELECT COUNT(*) FROM portal_peticiones_documentos d WHERE d.tenant_id = p.tenant_id AND d.peticion_id = p.id) AS archivos FROM portal_peticiones p "
                             "WHERE p.tenant_id = ? AND p.cliente_fiscal_id = ?" + (" AND p.estado IN ('pendiente', 'enviada')" if solo_abiertas else "") + " ORDER BY p.id DESC",
                             (cliente["tenant_id"], cliente["id"])).fetchall()
    finally:
        conn.close()
    orden = {"pendiente": 0, "enviada": 1, "revisada": 2, "cancelada": 3}
    return sorted((_fila(f) for f in filas), key=lambda p: (orden[p["estado"]], p["fecha_limite"] or "9999", -p["id"]))


def obtener(cliente, peticion_id: int) -> dict | None:
    return next((p for p in listar(cliente) if p["id"] == peticion_id), None)


def archivos(cliente, peticion_id: int) -> list[dict]:
    """[{documento_id, nombre, tipo_mime, tamano_bytes, subido_por, creado_en}] de lo que se ha subido para esa petición."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT d.documento_id, d.subido_por, d.creado_en, c.nombre_archivo AS nombre, c.nombre_cifrado, c.tipo_mime, c.tamano_bytes FROM portal_peticiones_documentos d "
                             "JOIN cliente_documentos c ON c.id = d.documento_id AND c.tenant_id = d.tenant_id WHERE d.tenant_id = ? AND d.peticion_id = ? ORDER BY d.id",
                             (cliente["tenant_id"], peticion_id)).fetchall()
    finally:
        conn.close()
    salida = []
    for f in filas:
        nombre = f["nombre"]
        if f["nombre_cifrado"]:
            try:
                from . import cifrado_despacho
                nombre = cifrado_despacho.abrir_nombre(cliente["tenant_id"], f["nombre_cifrado"]) or nombre
            except Exception:  # noqa: BLE001 -- con el despacho bloqueado se enseña el nombre genérico
                pass
        salida.append({"documento_id": f["documento_id"], "nombre": nombre, "tipo_mime": f["tipo_mime"], "tamano_bytes": f["tamano_bytes"], "subido_por": f["subido_por"], "creado_en": f["creado_en"]})
    return salida


def subir(cliente, peticion_id: int, ficheros: list[tuple[str, str | None, bytes]], quien: str) -> int:
    """El cliente sube uno o varios archivos para una petición suya que sigue abierta. La petición pasa a `enviada`. Devuelve cuántos se guardaron. `ValueError` con un mensaje legible si no se puede."""
    from . import almacen_documentos, antivirus
    p = obtener(cliente, peticion_id)
    if p is None or p["estado"] not in ("pendiente", "enviada"):
        raise ValueError("Esta petición ya no está abierta.")
    validos = [f for f in ficheros if f and f[2]]
    if not validos:
        raise ValueError("Elige al menos un archivo.")
    if len(validos) > MAX_ARCHIVOS:
        raise ValueError("Demasiados archivos de una vez: sube menos y repite.")
    for nombre, mime, contenido in validos:
        if (mime or "").lower().split(";")[0] not in MIME or len(contenido) > MAX_BYTES:
            raise ValueError("Solo PDF, imágenes, hojas de cálculo o documentos de texto, de hasta 8 MB cada uno.")
    for nombre, mime, contenido in validos:
        antivirus.exigir_limpio(nombre, contenido, cliente["tenant_id"], cliente["id"])           # antes de guardar nada: si uno falla, no se guarda ninguno
    guardados = 0
    conn = db.get_connection()
    try:
        for nombre, mime, contenido in validos:
            resultado, doc_id = almacen_documentos.guardar_de_cliente_fiscal_sin_usuario(cliente["tenant_id"], cliente["id"], nombre, (mime or "").lower().split(";")[0], contenido, f"Petición: {p['titulo']}"[:60])
            if resultado not in ("ok", "duplicado") or doc_id is None:
                if resultado == "limite":
                    raise ValueError("Se ha alcanzado el máximo de documentos de este cliente: avisa a tu gestoría.")
                continue
            try:
                conn.execute("INSERT INTO portal_peticiones_documentos (tenant_id, peticion_id, documento_id, subido_por, creado_en) VALUES (?, ?, ?, ?, ?)", (cliente["tenant_id"], peticion_id, doc_id, quien[:120], _ahora()))
                guardados += 1
            except Exception:  # noqa: BLE001 -- el mismo archivo ya estaba enlazado a esta petición
                conn.rollback()
        if guardados:
            conn.execute("UPDATE portal_peticiones SET estado = 'enviada', enviada_en = ?, nota = '' WHERE id = ? AND tenant_id = ?", (_ahora(), peticion_id, cliente["tenant_id"]))
        conn.commit()
    finally:
        conn.close()
    if not guardados:
        raise ValueError("No se ha podido guardar ningún archivo (¿ya estaban enviados?).")
    return guardados


def _cambiar(cliente, peticion_id: int, desde: tuple[str, ...], estado: str, por: int | None, nota: str = "") -> bool:
    conn = db.get_connection()
    try:
        marcadores = ",".join("?" * len(desde))
        n = conn.execute(f"UPDATE portal_peticiones SET estado = ?, nota = ?, revisada_en = ?, revisada_por = ? WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ? AND estado IN ({marcadores})",
                         (estado, _limpio(nota, MAX_NOTA), _ahora() if estado in ("revisada", "cancelada") else None, por if estado in ("revisada", "cancelada") else None, peticion_id, cliente["tenant_id"], cliente["id"], *desde)).rowcount
        conn.commit()
    finally:
        conn.close()
    return bool(n)


def revisar(cliente, peticion_id: int, por: int | None, nota: str = "") -> bool:
    """Da la petición por buena y la cierra."""
    return _cambiar(cliente, peticion_id, ("enviada", "pendiente"), "revisada", por, nota)


def reabrir(cliente, peticion_id: int, por: int | None, nota: str) -> bool:
    """Lo enviado no vale: vuelve a esperar al cliente con una nota de qué falta. `ValueError` si no se explica."""
    if len(_limpio(nota, MAX_NOTA)) < 5:
        raise ValueError("Explica qué falta (mínimo 5 caracteres): lo verá el cliente.")
    return _cambiar(cliente, peticion_id, ("enviada", "revisada"), "pendiente", por, nota)


def cancelar(cliente, peticion_id: int, por: int | None) -> bool:
    return _cambiar(cliente, peticion_id, ("pendiente", "enviada"), "cancelada", por)


def pendientes_del_cliente(cliente_id: int) -> list[dict]:
    """Las peticiones que esperan al cliente (para los recordatorios y para «lo que tienes que hacer»). Sin filtrar por despacho: el id del cliente ya lo es."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT * FROM portal_peticiones WHERE cliente_fiscal_id = ? AND estado = 'pendiente' ORDER BY COALESCE(fecha_limite, '9999'), id", (cliente_id,)).fetchall()
    finally:
        conn.close()
    return [_fila(f) for f in filas]


def documento_es_de_la_peticion(cliente, peticion_id: int, documento_id: int) -> bool:
    conn = db.get_connection()
    try:
        return conn.execute("SELECT 1 FROM portal_peticiones_documentos WHERE tenant_id = ? AND peticion_id = ? AND documento_id = ?", (cliente["tenant_id"], peticion_id, documento_id)).fetchone() is not None
    finally:
        conn.close()
