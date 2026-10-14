"""Traspaso de clientes entre personas y oficinas (especificación de control fiscal, RF-14).

Cada cliente tiene un **responsable** (`clientes_fiscales.responsable_id`) y una oficina. Para pasárselo a otra persona (y, si se quiere, a otra oficina) se **propone un traspaso**:
emisor, receptor, nota con el trabajo pendiente y fecha. Hasta que el receptor lo **acepta**, el responsable sigue siendo el anterior: nada cambia ni se pierde visibilidad. Al aceptar,
en una sola transacción, cambian responsable y oficina, el receptor recibe acceso si no lo tenía y todo queda en la auditoría. El receptor (o la dirección) puede rechazarlo con motivo;
quien lo propuso (o la dirección) cancelarlo. Si hay una obligación pendiente que vence en menos de `DIAS_ESCALADO` días y el traspaso sigue sin aceptar, se avisa a la dirección
(`escalar`, una vez por traspaso).

Concurrencia: solo puede haber un traspaso pendiente por cliente (índice único parcial), y resolverlo exige la `version` leída si se indica."""
from __future__ import annotations

from datetime import date, timedelta

from . import acceso, auditoria, db

DIAS_ESCALADO = 7
INTERVALO_SEGUNDOS = 3 * 3600
ESTADOS = ("pendiente", "aceptado", "rechazado", "cancelado")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS traspasos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id),
    de_usuario_id INTEGER REFERENCES usuarios(id),
    a_usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    de_oficina_id INTEGER REFERENCES oficinas(id),
    a_oficina_id INTEGER REFERENCES oficinas(id),
    nota TEXT,
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'aceptado', 'rechazado', 'cancelado')),
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    resuelto_por INTEGER REFERENCES usuarios(id),
    resuelto_en TEXT,
    motivo TEXT,
    escalado_en TEXT,
    version INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_traspasos_pendiente ON traspasos(cliente_fiscal_id) WHERE estado = 'pendiente';
CREATE INDEX IF NOT EXISTS idx_traspasos_tenant ON traspasos(tenant_id, estado);
"""


class ConflictoDeVersion(ValueError):
    """El traspaso ya lo resolvió otra persona."""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)
    db._asegurar_columna(conn, "clientes_fiscales", "responsable_id", "INTEGER REFERENCES usuarios(id)")


def _nombre(usuario_id) -> str | None:
    if not usuario_id:
        return None
    u = db.obtener_usuario(usuario_id)
    return db.nombre_mostrado_usuario(usuario_id) or (u["email"] if u else None)


def _avisar(usuario_id, titulo: str, cuerpo: str, url: str = "/fiscal/traspasos") -> None:
    try:
        from . import notificaciones
        if usuario_id:
            notificaciones.crear_y_enviar(usuario_id, "traspaso", titulo, cuerpo, url=url, datos={"tipo": "traspaso"})
    except Exception:  # noqa: BLE001  (un aviso que falla nunca deshace el traspaso)
        pass


def _enriquecer(conn, f) -> dict:
    t = dict(f)
    c = conn.execute("SELECT nombre FROM clientes_fiscales WHERE id = ?", (t["cliente_fiscal_id"],)).fetchone()
    t["cliente"] = c["nombre"] if c else "?"
    t["de_nombre"], t["a_nombre"] = _nombre(t["de_usuario_id"]), _nombre(t["a_usuario_id"])
    for k_id, k_n in (("de_oficina_id", "de_oficina"), ("a_oficina_id", "a_oficina")):
        o = conn.execute("SELECT nombre FROM oficinas WHERE id = ?", (t[k_id],)).fetchone() if t[k_id] else None
        t[k_n] = o["nombre"] if o else None
    prox = conn.execute("SELECT MIN(substr(fecha_limite, 1, 10)) AS f FROM vencimientos_fiscales WHERE cliente_fiscal_id = ? AND papelera_en IS NULL AND fase IN ('pendiente', 'en_preparacion', 'en_revision', 'aprobada')",
                        (t["cliente_fiscal_id"],)).fetchone()
    t["proximo_vencimiento"] = prox["f"] if prox else None
    t["dias_al_vencimiento"] = (date.fromisoformat(t["proximo_vencimiento"]) - date.today()).days if t["proximo_vencimiento"] else None
    return t


def proponer(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, a_usuario_id: int, *, a_oficina_id: int | None = None, nota: str | None = None) -> int:
    nota = (nota or "").strip()[:1000]
    conn = db.get_connection()
    try:
        c = conn.execute("SELECT id, nombre, oficina_id, responsable_id FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (cliente_fiscal_id, tenant_id)).fetchone()
        if c is None or not acceso.puede_modificar_cliente(tenant_id, usuario_id, cliente_fiscal_id):
            raise ValueError("No existe ese cliente.")
        if conn.execute("SELECT 1 FROM usuarios WHERE id = ? AND tenant_id = ?", (a_usuario_id, tenant_id)).fetchone() is None:
            raise ValueError("Esa persona no pertenece al despacho.")
        if a_usuario_id == c["responsable_id"]:
            raise ValueError("Esa persona ya es la responsable del cliente.")
        if a_oficina_id is not None and conn.execute("SELECT 1 FROM oficinas WHERE id = ? AND tenant_id = ? AND activa = 1", (a_oficina_id, tenant_id)).fetchone() is None:
            raise ValueError("No existe esa oficina.")
        if conn.execute("SELECT 1 FROM traspasos WHERE cliente_fiscal_id = ? AND estado = 'pendiente'", (cliente_fiscal_id,)).fetchone():
            raise ValueError("Ese cliente ya tiene un traspaso pendiente de aceptar.")
        cur = conn.execute("INSERT INTO traspasos (tenant_id, cliente_fiscal_id, de_usuario_id, a_usuario_id, de_oficina_id, a_oficina_id, nota, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, cliente_fiscal_id, c["responsable_id"], a_usuario_id, c["oficina_id"], a_oficina_id, nota or None, usuario_id, db.now_iso()))
        auditoria.registrar(tenant_id, usuario_id, "traspaso.proponer", "cliente_fiscal", cliente_fiscal_id, {"traspaso_id": cur.lastrowid, "a_usuario_id": a_usuario_id, "a_oficina_id": a_oficina_id}, conn=conn)
        conn.commit()
        nuevo, nombre = cur.lastrowid, c["nombre"]
    finally:
        conn.close()
    _avisar(a_usuario_id, "Te proponen un traspaso de cliente", f"{nombre}: {_nombre(usuario_id) or ''} te lo quiere pasar. Hasta que lo aceptes, sigue siendo de quien lo lleva.")
    return nuevo


def _cargar(conn, tenant_id: int, traspaso_id: int):
    t = conn.execute("SELECT * FROM traspasos WHERE id = ? AND tenant_id = ?", (traspaso_id, tenant_id)).fetchone()
    if t is None:
        raise ValueError("No existe ese traspaso.")
    return t


def _pendiente(t, version: int | None) -> None:
    if t["estado"] != "pendiente" or (version is not None and version != t["version"]):
        raise ConflictoDeVersion("Este traspaso ya se ha resuelto: recarga para verlo.")


def aceptar(tenant_id: int, usuario_id: int, traspaso_id: int, *, version: int | None = None) -> None:
    conn = db.get_connection()
    try:
        t = _cargar(conn, tenant_id, traspaso_id)
        if usuario_id != t["a_usuario_id"] and not acceso.es_directivo(usuario_id):
            raise ValueError("Solo quien lo recibe (o la dirección) puede aceptarlo.")
        _pendiente(t, version)
        sets, params = ["responsable_id = ?", "version = version + 1"], [t["a_usuario_id"]]
        if t["a_oficina_id"] is not None:
            sets.append("oficina_id = ?"); params.append(t["a_oficina_id"])
        conn.execute(f"UPDATE clientes_fiscales SET {', '.join(sets)} WHERE id = ? AND tenant_id = ?", [*params, t["cliente_fiscal_id"], tenant_id])
        # Quien recibe el cliente tiene que poder trabajarlo: si con su oficina o sus permisos no lo ve, se le concede acceso de gestión.
        sql, p = acceso._condicion(tenant_id, t["a_usuario_id"], "c.id")
        if sql and conn.execute(f"SELECT 1 FROM clientes_fiscales c WHERE c.id = ? AND {sql}", [t["cliente_fiscal_id"], *p]).fetchone() is None:
            conn.execute("INSERT INTO concesiones_cliente (tenant_id, cliente_fiscal_id, usuario_id, nivel, creado_por, creado_en) VALUES (?, ?, ?, 'gestion', ?, ?)",
                         (tenant_id, t["cliente_fiscal_id"], t["a_usuario_id"], usuario_id, db.now_iso()))
        conn.execute("UPDATE traspasos SET estado = 'aceptado', resuelto_por = ?, resuelto_en = ?, version = version + 1 WHERE id = ?", (usuario_id, db.now_iso(), traspaso_id))
        auditoria.registrar(tenant_id, usuario_id, "traspaso.aceptar", "cliente_fiscal", t["cliente_fiscal_id"], {"traspaso_id": traspaso_id, "de": t["de_usuario_id"], "a": t["a_usuario_id"], "oficina": t["a_oficina_id"]}, conn=conn)
        conn.commit()
        nombre = conn.execute("SELECT nombre FROM clientes_fiscales WHERE id = ?", (t["cliente_fiscal_id"],)).fetchone()["nombre"]
    finally:
        conn.close()
    acceso.invalidar(tenant_id)
    for u in {t["de_usuario_id"], t["creado_por"]} - {None, usuario_id}:
        _avisar(u, "Traspaso aceptado", f"{nombre} ya lo lleva {_nombre(t['a_usuario_id'])}.")


def _cerrar(tenant_id: int, usuario_id: int, traspaso_id: int, estado: str, motivo: str | None, version: int | None) -> None:
    motivo = (motivo or "").strip()[:500]
    conn = db.get_connection()
    try:
        t = _cargar(conn, tenant_id, traspaso_id)
        if estado == "rechazado":
            if usuario_id != t["a_usuario_id"] and not acceso.es_directivo(usuario_id):
                raise ValueError("Solo quien lo recibe (o la dirección) puede rechazarlo.")
            if not motivo:
                raise ValueError("Cuenta por qué se rechaza, para que quien lo propuso pueda resolverlo.")
        elif usuario_id not in (t["creado_por"], t["de_usuario_id"]) and not acceso.es_directivo(usuario_id):
            raise ValueError("Solo quien lo propuso (o la dirección) puede cancelarlo.")
        _pendiente(t, version)
        conn.execute("UPDATE traspasos SET estado = ?, resuelto_por = ?, resuelto_en = ?, motivo = ?, version = version + 1 WHERE id = ?", (estado, usuario_id, db.now_iso(), motivo or None, traspaso_id))
        auditoria.registrar(tenant_id, usuario_id, "traspaso.rechazar" if estado == "rechazado" else "traspaso.cancelar", "cliente_fiscal", t["cliente_fiscal_id"], {"traspaso_id": traspaso_id, "motivo": motivo or None}, conn=conn)
        conn.commit()
        nombre = conn.execute("SELECT nombre FROM clientes_fiscales WHERE id = ?", (t["cliente_fiscal_id"],)).fetchone()["nombre"]
    finally:
        conn.close()
    if estado == "rechazado":
        for u in {t["creado_por"], t["de_usuario_id"]} - {None, usuario_id}:
            _avisar(u, "Traspaso rechazado", f"{nombre}: {motivo}. Sigue siendo tuyo.")
    elif usuario_id != t["a_usuario_id"]:
        _avisar(t["a_usuario_id"], "Traspaso cancelado", f"{nombre}: ya no hace falta que lo aceptes.")


def rechazar(tenant_id: int, usuario_id: int, traspaso_id: int, motivo: str, *, version: int | None = None) -> None:
    _cerrar(tenant_id, usuario_id, traspaso_id, "rechazado", motivo, version)


def cancelar(tenant_id: int, usuario_id: int, traspaso_id: int, *, version: int | None = None) -> None:
    _cerrar(tenant_id, usuario_id, traspaso_id, "cancelado", None, version)


def asignar_responsable(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, responsable_id: int | None) -> None:
    """Fija quién lleva el cliente sin traspaso (alta inicial o corrección): dirección o coordinación de su oficina."""
    conn = db.get_connection()
    try:
        c = conn.execute("SELECT oficina_id, responsable_id FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (cliente_fiscal_id, tenant_id)).fetchone()
        if c is None:
            raise ValueError("No existe ese cliente.")
        if not acceso.es_directivo(usuario_id) and (c["oficina_id"] is None or c["oficina_id"] not in acceso._oficinas_que_coordina(tenant_id, usuario_id)):
            raise ValueError("Solo la dirección o quien coordina la oficina del cliente puede cambiar el responsable.")
        if responsable_id is not None and conn.execute("SELECT 1 FROM usuarios WHERE id = ? AND tenant_id = ?", (responsable_id, tenant_id)).fetchone() is None:
            raise ValueError("Esa persona no pertenece al despacho.")
        if conn.execute("SELECT 1 FROM traspasos WHERE cliente_fiscal_id = ? AND estado = 'pendiente'", (cliente_fiscal_id,)).fetchone():
            raise ValueError("Hay un traspaso pendiente de aceptar: resuélvelo antes.")
        conn.execute("UPDATE clientes_fiscales SET responsable_id = ?, version = version + 1 WHERE id = ?", (responsable_id, cliente_fiscal_id))
        auditoria.registrar(tenant_id, usuario_id, "cliente.responsable", "cliente_fiscal", cliente_fiscal_id, {"de": c["responsable_id"], "a": responsable_id}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def listar(tenant_id: int, usuario_id: int, *, estado: str | None = None, limite: int = 200) -> list[dict]:
    """Traspasos que la persona puede ver: los de clientes que ve, más los que ha enviado o recibido."""
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        cond, params = ["tenant_id = ?"], [tenant_id]
        if estado:
            cond.append("estado = ?"); params.append(estado)
        filas = conn.execute(f"SELECT * FROM traspasos WHERE {' AND '.join(cond)} ORDER BY (estado = 'pendiente') DESC, id DESC LIMIT ?", [*params, limite]).fetchall()
        return [_enriquecer(conn, f) for f in filas if visibles is None or f["cliente_fiscal_id"] in visibles or usuario_id in (f["a_usuario_id"], f["de_usuario_id"], f["creado_por"])]
    finally:
        conn.close()


def obtener(tenant_id: int, traspaso_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM traspasos WHERE id = ? AND tenant_id = ?", (traspaso_id, tenant_id)).fetchone()
        return _enriquecer(conn, f) if f else None
    finally:
        conn.close()


def escalar(hoy: date | None = None) -> int:
    """Avisa a la dirección de los traspasos sin aceptar con una obligación a punto de vencer (una vez por traspaso). Devuelve cuántos ha escalado."""
    hoy = hoy or date.today()
    limite = (hoy + timedelta(days=DIAS_ESCALADO)).isoformat()
    n = 0
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT t.* FROM traspasos t WHERE t.estado = 'pendiente' AND t.escalado_en IS NULL AND EXISTS (SELECT 1 FROM vencimientos_fiscales v WHERE v.cliente_fiscal_id = t.cliente_fiscal_id "
                             "AND v.papelera_en IS NULL AND v.fase IN ('pendiente', 'en_preparacion', 'en_revision', 'aprobada') AND substr(v.fecha_limite, 1, 10) <= ?)", (limite,)).fetchall()
        datos = [_enriquecer(conn, f) for f in filas]
        for t in datos:
            conn.execute("UPDATE traspasos SET escalado_en = ? WHERE id = ?", (db.now_iso(), t["id"]))
            auditoria.registrar(t["tenant_id"], None, "traspaso.escalar", "cliente_fiscal", t["cliente_fiscal_id"], {"traspaso_id": t["id"], "proximo_vencimiento": t["proximo_vencimiento"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    for t in datos:
        destinatarios = {u for u in db.usuarios_de_tenant(t["tenant_id"]) if acceso.es_directivo(u)} | {t["de_usuario_id"], t["a_usuario_id"]}
        for u in destinatarios - {None}:
            _avisar(u, "Traspaso sin aceptar y con plazo cerca", f"{t['cliente']}: vence algo el {t['proximo_vencimiento']} y {t['a_nombre']} aún no ha aceptado. Hasta entonces lo lleva {t['de_nombre'] or 'nadie'}.")
        n += 1
    return n


def bucle() -> None:
    import time
    from . import salud
    salud.registrar_ok("traspasos_escalado", INTERVALO_SEGUNDOS * 2, "arrancado")
    time.sleep(180)
    while True:
        try:
            salud.registrar_ok("traspasos_escalado", INTERVALO_SEGUNDOS * 2, f"{escalar()} traspasos escalados")
        except Exception as e:  # noqa: BLE001
            salud.registrar_error("traspasos_escalado", INTERVALO_SEGUNDOS * 2, f"{type(e).__name__}: {e}")
        time.sleep(INTERVALO_SEGUNDOS)


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    conn.execute("DELETE FROM traspasos WHERE tenant_id = ?", (tenant_id,))
