"""Comercial (CRM nativo de Guilda Work): oportunidades con embudo, actividades y seguimiento, y conversión de prospecto en cliente. Es un módulo («vertical») que cada despacho activa; se apoya en
el núcleo común (clientes, personas, tareas, oficinas, auditoría), así que no duplica datos ni permisos. Ver `docs/hoja-de-ruta.md`.

Reglas, explícitas:
- **Oportunidad**: lo que se quiere vender a un prospecto o a un cliente existente (`cliente_id`). Mientras no es cliente guarda sus datos de contacto; **convertirla** crea la ficha de cliente (con gestión fiscal si
  el despacho la lleva) y la enlaza. Una oportunidad sin cliente es visible para todo el despacho; una con cliente solo para quien puede ver a ese cliente (oficinas).
- **Etapas por despacho** (se crean la primera vez con unas habituales y se pueden renombrar, reordenar y cambiar de probabilidad): hay siempre exactamente una de «ganada» y una de «perdida». Perder exige un motivo.
  La probabilidad de una oportunidad es la de su etapa (la ganada 100 %, la perdida 0 %); la previsión ponderada multiplica importe por probabilidad.
- **Actividades**: llamada, reunión, visita, correo o nota, con fecha; pueden crear una **próxima acción** (una tarea con fecha, asignada a quien lleva la oportunidad). Cada cambio de etapa queda anotado solo.
- **Quién escribe**: cualquier persona del despacho salvo quien solo audita (solo lectura). Todo cambio importante queda en la auditoría.
- Nada se borra de golpe: una oportunidad va a la papelera."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from . import acceso, alta_cliente, auditoria, db, nucleo

ESQUEMA = """
CREATE TABLE IF NOT EXISTS crm_etapas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    clave TEXT NOT NULL,
    nombre TEXT NOT NULL,
    orden INTEGER NOT NULL,
    probabilidad INTEGER NOT NULL DEFAULT 0 CHECK (probabilidad BETWEEN 0 AND 100),
    tipo TEXT NOT NULL DEFAULT 'abierta' CHECK (tipo IN ('abierta', 'ganada', 'perdida')),
    UNIQUE (tenant_id, clave)
);
CREATE TABLE IF NOT EXISTS crm_oportunidades (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    titulo TEXT NOT NULL,
    cliente_id INTEGER REFERENCES clientes(id) ON DELETE SET NULL,
    contacto_nombre TEXT,
    contacto_email TEXT,
    contacto_telefono TEXT,
    empresa TEXT,
    etapa TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'ganada', 'perdida')),
    importe_centimos INTEGER NOT NULL DEFAULT 0,
    probabilidad INTEGER NOT NULL DEFAULT 0,
    cierre_previsto TEXT,
    responsable_id INTEGER REFERENCES usuarios(id),
    origen TEXT,
    notas TEXT,
    motivo_perdida TEXT,
    creada_por INTEGER REFERENCES usuarios(id),
    creada_en TEXT NOT NULL,
    actualizada_en TEXT,
    cerrada_en TEXT,
    ultima_actividad_en TEXT,
    papelera_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_crm_oport_tenant ON crm_oportunidades(tenant_id, estado, etapa);
CREATE INDEX IF NOT EXISTS idx_crm_oport_cliente ON crm_oportunidades(cliente_id);
CREATE TABLE IF NOT EXISTS crm_actividades (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    oportunidad_id INTEGER REFERENCES crm_oportunidades(id) ON DELETE CASCADE,
    cliente_id INTEGER REFERENCES clientes(id) ON DELETE SET NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('llamada', 'reunion', 'visita', 'correo', 'nota', 'etapa')),
    asunto TEXT NOT NULL,
    texto TEXT,
    fecha TEXT NOT NULL,
    tarea_id INTEGER,
    creada_por INTEGER REFERENCES usuarios(id),
    creada_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crm_act_oport ON crm_actividades(oportunidad_id, fecha);
CREATE INDEX IF NOT EXISTS idx_crm_act_cliente ON crm_actividades(cliente_id, fecha);
"""

ETAPAS_INICIALES = (
    ("nuevo", "Nuevo", 10, "abierta"), ("contactado", "Contactado", 25, "abierta"), ("reunion", "Reunión", 40, "abierta"),
    ("propuesta", "Propuesta enviada", 60, "abierta"), ("negociacion", "Negociación", 80, "abierta"),
    ("ganada", "Ganada", 100, "ganada"), ("perdida", "Perdida", 0, "perdida"),
)
TIPOS_ACTIVIDAD = {"llamada": "Llamada", "reunion": "Reunión", "visita": "Visita", "correo": "Correo", "nota": "Nota"}
MAX_ETAPAS = 12
MAX_OPORTUNIDADES_POR_LISTA = 500
DIAS_ESTANCADA = 14


class ErrorComercial(ValueError):
    """Un error de negocio con un mensaje apto para enseñárselo a la persona."""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)
    from . import reuniones
    reuniones.crear_esquema(conn)


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    from . import reuniones
    reuniones.borrar_datos_de_tenant(conn, tenant_id)
    conn.execute("DELETE FROM crm_actividades WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM crm_oportunidades WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM crm_etapas WHERE tenant_id = ?", (tenant_id,))


# --- Permisos -------------------------------------------------------------------------------------------------------------

def _exigir_escritura(tenant_id: int, usuario_id: int) -> None:
    if acceso.es_solo_auditor(tenant_id, usuario_id):
        raise ErrorComercial("Tu rol solo permite consultar.")


def _exigir_direccion(usuario_id: int) -> None:
    if not acceso.es_directivo(usuario_id):
        raise ErrorComercial("Solo la dirección del despacho cambia las etapas del embudo.")


def _visible_sql(tenant_id: int, usuario_id: int, columna: str = "o.cliente_id") -> tuple[str, list]:
    """Una oportunidad sin cliente la ve todo el despacho; con cliente, quien puede ver a ese cliente."""
    cond, params = acceso.condicion_nucleo(tenant_id, usuario_id, columna)
    if not cond:
        return "", []
    return f" AND ({columna} IS NULL OR {cond})", params


def _tenant_de(conn, usuario_id: int) -> int | None:
    f = conn.execute("SELECT tenant_id FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    return f["tenant_id"] if f else None


def _limpio(valor, largo: int) -> str | None:
    if valor is None:
        return None
    return str(valor).strip()[:largo] or None


def _persona_del_despacho(conn, tenant_id: int, persona_id) -> int | None:
    if persona_id in (None, ""):
        return None
    try:
        persona_id = int(persona_id)
    except (TypeError, ValueError):
        raise ErrorComercial("La persona elegida no es válida.") from None
    if conn.execute("SELECT 1 FROM usuarios WHERE id = ? AND tenant_id = ?", (persona_id, tenant_id)).fetchone() is None:
        raise ErrorComercial("La persona elegida no es de tu despacho.")
    return persona_id


def _cliente_del_despacho(conn, tenant_id: int, usuario_id: int, cliente_id) -> int | None:
    if cliente_id in (None, ""):
        return None
    try:
        cliente_id = int(cliente_id)
    except (TypeError, ValueError):
        raise ErrorComercial("El cliente elegido no es válido.") from None
    if conn.execute("SELECT 1 FROM clientes WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (cliente_id, tenant_id)).fetchone() is None or \
            not acceso.puede_ver_cliente_nucleo(tenant_id, usuario_id, cliente_id):
        raise ErrorComercial("El cliente elegido no existe o no lo puedes ver.")
    return cliente_id


def _fecha(valor, campo: str) -> str | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10]).isoformat()
    except ValueError:
        raise ErrorComercial(f"{campo}: la fecha tiene que ser AAAA-MM-DD.") from None


def _importe(valor) -> int:
    if valor in (None, ""):
        return 0
    try:
        centimos = nucleo.importe_a_centimos(valor)
    except ValueError:
        raise ErrorComercial("El importe no es válido.") from None
    if not 0 <= centimos <= 10**12:
        raise ErrorComercial("El importe tiene que estar entre 0 y 10.000.000.000 €.")
    return centimos


# --- Etapas ---------------------------------------------------------------------------------------------------------------

def asegurar_etapas(tenant_id: int) -> None:
    """Crea las etapas habituales la primera vez que el despacho usa el módulo."""
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM crm_etapas WHERE tenant_id = ? LIMIT 1", (tenant_id,)).fetchone() is None:
            for orden, (clave, nombre, prob, tipo) in enumerate(ETAPAS_INICIALES, start=1):
                conn.execute("INSERT INTO crm_etapas (tenant_id, clave, nombre, orden, probabilidad, tipo) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING", (tenant_id, clave, nombre, orden, prob, tipo))
            conn.commit()
    finally:
        conn.close()


def listar_etapas(tenant_id: int) -> list[dict]:
    """Abiertas por su orden y, al final, ganada y perdida."""
    asegurar_etapas(tenant_id)
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            "SELECT * FROM crm_etapas WHERE tenant_id = ? ORDER BY CASE tipo WHEN 'abierta' THEN 0 WHEN 'ganada' THEN 1 ELSE 2 END, orden, id", (tenant_id,))]
    finally:
        conn.close()


def _etapa(conn, tenant_id: int, clave: str):
    f = conn.execute("SELECT * FROM crm_etapas WHERE tenant_id = ? AND clave = ?", (tenant_id, clave)).fetchone()
    if f is None:
        raise ErrorComercial("Esa etapa no existe.")
    return f


def renombrar_etapa(tenant_id: int, usuario_id: int, clave: str, nombre: str, probabilidad=None) -> None:
    _exigir_direccion(usuario_id)
    nombre = _limpio(nombre, 60)
    if not nombre:
        raise ErrorComercial("La etapa necesita un nombre.")
    asegurar_etapas(tenant_id)
    conn = db.get_connection()
    try:
        e = _etapa(conn, tenant_id, clave)
        if conn.execute("SELECT 1 FROM crm_etapas WHERE tenant_id = ? AND clave != ? AND lower(nombre) = lower(?)", (tenant_id, clave, nombre)).fetchone():
            raise ErrorComercial("Ya hay otra etapa con ese nombre.")
        prob = e["probabilidad"]
        if probabilidad not in (None, "") and e["tipo"] == "abierta":
            try:
                prob = int(probabilidad)
            except (TypeError, ValueError):
                raise ErrorComercial("La probabilidad tiene que ser un número entre 0 y 100.") from None
            if not 0 <= prob <= 100:
                raise ErrorComercial("La probabilidad tiene que estar entre 0 y 100.")
        conn.execute("UPDATE crm_etapas SET nombre = ?, probabilidad = ? WHERE id = ?", (nombre, prob, e["id"]))
        if prob != e["probabilidad"]:                                           # las oportunidades abiertas de esa etapa toman la probabilidad nueva
            conn.execute("UPDATE crm_oportunidades SET probabilidad = ? WHERE tenant_id = ? AND etapa = ? AND estado = 'abierta'", (prob, tenant_id, clave))
        auditoria.registrar(tenant_id, usuario_id, "crm.etapa.cambiar", "crm_etapa", e["id"], {"clave": clave, "nombre": nombre, "probabilidad": prob}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def mover_etapa(tenant_id: int, usuario_id: int, clave: str, delta: int) -> None:
    """Sube (-1) o baja (+1) una etapa abierta entre las abiertas."""
    _exigir_direccion(usuario_id)
    abiertas = [e for e in listar_etapas(tenant_id) if e["tipo"] == "abierta"]
    claves = [e["clave"] for e in abiertas]
    if clave not in claves:
        raise ErrorComercial("Solo se pueden reordenar las etapas abiertas.")
    i, j = claves.index(clave), claves.index(clave) + (1 if delta > 0 else -1)
    if not 0 <= j < len(claves):
        return
    claves[i], claves[j] = claves[j], claves[i]
    conn = db.get_connection()
    try:
        for orden, c in enumerate(claves, start=1):
            conn.execute("UPDATE crm_etapas SET orden = ? WHERE tenant_id = ? AND clave = ?", (orden, tenant_id, c))
        conn.commit()
    finally:
        conn.close()


def crear_etapa(tenant_id: int, usuario_id: int, nombre: str, probabilidad=50) -> str:
    _exigir_direccion(usuario_id)
    nombre = _limpio(nombre, 60)
    if not nombre:
        raise ErrorComercial("La etapa necesita un nombre.")
    etapas = listar_etapas(tenant_id)
    if len(etapas) >= MAX_ETAPAS:
        raise ErrorComercial(f"Un embudo admite hasta {MAX_ETAPAS} etapas.")
    if any(e["nombre"].lower() == nombre.lower() for e in etapas):
        raise ErrorComercial("Ya hay otra etapa con ese nombre.")
    try:
        prob = int(probabilidad)
    except (TypeError, ValueError):
        raise ErrorComercial("La probabilidad tiene que ser un número entre 0 y 100.") from None
    if not 0 <= prob <= 100:
        raise ErrorComercial("La probabilidad tiene que estar entre 0 y 100.")
    base = "".join(c for c in nombre.lower().replace(" ", "_") if c.isalnum() or c == "_")[:30] or "etapa"
    claves = {e["clave"] for e in etapas}
    clave, n = base, 2
    while clave in claves:
        clave, n = f"{base}_{n}", n + 1
    conn = db.get_connection()
    try:
        orden = max((e["orden"] for e in etapas if e["tipo"] == "abierta"), default=0) + 1
        conn.execute("INSERT INTO crm_etapas (tenant_id, clave, nombre, orden, probabilidad, tipo) VALUES (?, ?, ?, ?, ?, 'abierta')", (tenant_id, clave, nombre, orden, prob))
        auditoria.registrar(tenant_id, usuario_id, "crm.etapa.crear", "crm_etapa", None, {"clave": clave, "nombre": nombre}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return clave


def borrar_etapa(tenant_id: int, usuario_id: int, clave: str) -> None:
    _exigir_direccion(usuario_id)
    asegurar_etapas(tenant_id)
    conn = db.get_connection()
    try:
        e = _etapa(conn, tenant_id, clave)
        if e["tipo"] != "abierta":
            raise ErrorComercial("Las etapas «ganada» y «perdida» no se pueden borrar.")
        if conn.execute("SELECT 1 FROM crm_oportunidades WHERE tenant_id = ? AND etapa = ? AND papelera_en IS NULL LIMIT 1", (tenant_id, clave)).fetchone():
            raise ErrorComercial("Esa etapa tiene oportunidades: muévelas antes a otra.")
        if conn.execute("SELECT COUNT(*) FROM crm_etapas WHERE tenant_id = ? AND tipo = 'abierta'", (tenant_id,)).fetchone()[0] <= 1:
            raise ErrorComercial("El embudo necesita al menos una etapa abierta.")
        conn.execute("DELETE FROM crm_etapas WHERE id = ?", (e["id"],))
        auditoria.registrar(tenant_id, usuario_id, "crm.etapa.borrar", "crm_etapa", e["id"], {"clave": clave}, conn=conn)
        conn.commit()
    finally:
        conn.close()


# --- Oportunidades --------------------------------------------------------------------------------------------------------

def _automatizar(tenant_id: int, evento: str, payload: dict) -> None:
    try:
        from . import automatizaciones
        automatizaciones.registrar_evento(tenant_id, evento, payload)
    except Exception:  # noqa: BLE001 -- un fallo de las automatizaciones nunca afecta al cambio ya guardado
        pass


def crear_oportunidad(tenant_id: int, usuario_id: int, titulo: str, *, cliente_id=None, contacto_nombre=None, contacto_email=None, contacto_telefono=None, empresa=None, importe=None,
                      cierre_previsto=None, responsable_id=None, origen=None, notas=None, etapa: str | None = None) -> int:
    _exigir_escritura(tenant_id, usuario_id)
    titulo = _limpio(titulo, 200)
    if not titulo:
        raise ErrorComercial("Indica de qué es la oportunidad.")
    etapas = listar_etapas(tenant_id)
    abiertas = [e for e in etapas if e["tipo"] == "abierta"]
    elegida = next((e for e in abiertas if e["clave"] == (etapa or abiertas[0]["clave"])), None)
    if elegida is None:
        raise ErrorComercial("Esa etapa no existe o no es una etapa abierta.")
    conn = db.get_connection()
    try:
        cliente_id = _cliente_del_despacho(conn, tenant_id, usuario_id, cliente_id)
        responsable_id = _persona_del_despacho(conn, tenant_id, responsable_id) or usuario_id
        if cliente_id is None and not (_limpio(contacto_nombre, 200) or _limpio(empresa, 200)):
            raise ErrorComercial("Indica quién es el prospecto (nombre o empresa) o elige un cliente.")
        ahora = db.now_iso()
        cur = conn.execute(
            """INSERT INTO crm_oportunidades (tenant_id, titulo, cliente_id, contacto_nombre, contacto_email, contacto_telefono, empresa, etapa, estado, importe_centimos, probabilidad, cierre_previsto,
                                              responsable_id, origen, notas, creada_por, creada_en, ultima_actividad_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'abierta', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tenant_id, titulo, cliente_id, _limpio(contacto_nombre, 200), _limpio(contacto_email, 200), _limpio(contacto_telefono, 40), _limpio(empresa, 200), elegida["clave"], _importe(importe),
             elegida["probabilidad"], _fecha(cierre_previsto, "Cierre previsto"), responsable_id, _limpio(origen, 100), _limpio(notas, 4000), usuario_id, ahora, ahora))
        oid = cur.lastrowid
        auditoria.registrar(tenant_id, usuario_id, "crm.oportunidad.crear", "crm_oportunidad", oid, {"titulo": titulo}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    _automatizar(tenant_id, "oportunidad.creada", {"oportunidad_id": oid})
    return oid


def obtener_oportunidad(tenant_id: int, usuario_id: int, oportunidad_id: int, incluir_papelera: bool = False) -> dict | None:
    visible, params = _visible_sql(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        f = conn.execute(
            f"""SELECT o.*, e.nombre AS etapa_nombre, e.tipo AS etapa_tipo, c.nombre AS cliente_nombre, c.email AS cliente_email,
                       (SELECT id FROM clientes_fiscales WHERE cliente_id = o.cliente_id LIMIT 1) AS cliente_fiscal_id
                FROM crm_oportunidades o LEFT JOIN crm_etapas e ON e.tenant_id = o.tenant_id AND e.clave = o.etapa LEFT JOIN clientes c ON c.id = o.cliente_id
                WHERE o.id = ? AND o.tenant_id = ?{'' if incluir_papelera else ' AND o.papelera_en IS NULL'}{visible}""", (oportunidad_id, tenant_id, *params)).fetchone()
        return _con_nombres(dict(f)) if f else None
    finally:
        conn.close()


def _con_nombres(o: dict) -> dict:
    o["responsable"] = db.nombre_mostrado_usuario(o["responsable_id"]) if o.get("responsable_id") else None
    o["importe"] = o["importe_centimos"] / 100
    o["ponderado"] = round(o["importe_centimos"] * o["probabilidad"] / 100) / 100
    o["contacto"] = o.get("cliente_nombre") or o.get("empresa") or o.get("contacto_nombre") or ""
    return o


def listar_oportunidades(tenant_id: int, usuario_id: int, *, estado: str | None = "abierta", etapa: str | None = None, responsable_id: int | None = None, cliente_id: int | None = None,
                         q: str | None = None, limite: int = 200) -> list[dict]:
    """Las que la persona puede ver. `estado`: abierta (por defecto), ganada, perdida o None (todas)."""
    visible, params = _visible_sql(tenant_id, usuario_id)
    donde, p = ["o.tenant_id = ?", "o.papelera_en IS NULL"], [tenant_id]
    for cond, valor in (("o.estado = ?", estado), ("o.etapa = ?", etapa), ("o.responsable_id = ?", responsable_id), ("o.cliente_id = ?", cliente_id)):
        if valor not in (None, ""):
            donde.append(cond)
            p.append(valor)
    if q and q.strip():
        like = f"%{nucleo.plano(q.strip())}%"
        donde.append("(plano(o.titulo) LIKE ? OR plano(o.contacto_nombre) LIKE ? OR plano(o.empresa) LIKE ? OR plano(c.nombre) LIKE ?)")
        p += [like] * 4
    conn = nucleo._conn_con_busqueda()
    try:
        filas = conn.execute(
            f"""SELECT o.*, e.nombre AS etapa_nombre, e.tipo AS etapa_tipo, c.nombre AS cliente_nombre
                FROM crm_oportunidades o LEFT JOIN crm_etapas e ON e.tenant_id = o.tenant_id AND e.clave = o.etapa LEFT JOIN clientes c ON c.id = o.cliente_id
                WHERE {' AND '.join(donde)}{visible} ORDER BY o.cierre_previsto IS NULL, o.cierre_previsto, o.id DESC LIMIT ?""",
            [*p, *params, max(1, min(int(limite), MAX_OPORTUNIDADES_POR_LISTA))]).fetchall()
    finally:
        conn.close()
    return [_con_nombres(dict(f)) for f in filas]


def editar_oportunidad(tenant_id: int, usuario_id: int, oportunidad_id: int, **campos) -> dict:
    _exigir_escritura(tenant_id, usuario_id)
    actual = obtener_oportunidad(tenant_id, usuario_id, oportunidad_id)
    if actual is None:
        raise ErrorComercial("Oportunidad no encontrada.")
    sets: dict = {}
    conn = db.get_connection()
    try:
        if "titulo" in campos:
            sets["titulo"] = _limpio(campos["titulo"], 200)
            if not sets["titulo"]:
                raise ErrorComercial("Indica de qué es la oportunidad.")
        for c, largo in (("contacto_nombre", 200), ("contacto_email", 200), ("contacto_telefono", 40), ("empresa", 200), ("origen", 100), ("notas", 4000)):
            if c in campos:
                sets[c] = _limpio(campos[c], largo)
        if "importe" in campos:
            sets["importe_centimos"] = _importe(campos["importe"])
        if "cierre_previsto" in campos:
            sets["cierre_previsto"] = _fecha(campos["cierre_previsto"], "Cierre previsto")
        if "responsable_id" in campos:
            sets["responsable_id"] = _persona_del_despacho(conn, tenant_id, campos["responsable_id"]) or usuario_id
        if "cliente_id" in campos:
            sets["cliente_id"] = _cliente_del_despacho(conn, tenant_id, usuario_id, campos["cliente_id"])
        nuevo_cliente = sets.get("cliente_id", actual["cliente_id"])
        if nuevo_cliente is None and not (sets.get("contacto_nombre", actual["contacto_nombre"]) or sets.get("empresa", actual["empresa"])):
            raise ErrorComercial("Indica quién es el prospecto (nombre o empresa) o elige un cliente.")
        if sets:
            asign = ", ".join(f"{c} = ?" for c in sets)
            conn.execute(f"UPDATE crm_oportunidades SET {asign}, actualizada_en = ? WHERE id = ? AND tenant_id = ?", [*sets.values(), db.now_iso(), oportunidad_id, tenant_id])
            auditoria.registrar(tenant_id, usuario_id, "crm.oportunidad.editar", "crm_oportunidad", oportunidad_id, {"campos": sorted(sets)}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return obtener_oportunidad(tenant_id, usuario_id, oportunidad_id)


def mover_oportunidad(tenant_id: int, usuario_id: int, oportunidad_id: int, etapa: str, motivo: str | None = None) -> dict:
    """Cambia de etapa. Pasar a la perdida exige un motivo; a la ganada o la perdida la cierra; salir de ellas la reabre. Anota el cambio en la cronología."""
    _exigir_escritura(tenant_id, usuario_id)
    o = obtener_oportunidad(tenant_id, usuario_id, oportunidad_id)
    if o is None:
        raise ErrorComercial("Oportunidad no encontrada.")
    listar_etapas(tenant_id)
    conn = db.get_connection()
    try:
        destino = _etapa(conn, tenant_id, etapa)
        if destino["clave"] == o["etapa"]:
            return o
        motivo = _limpio(motivo, 500)
        if destino["tipo"] == "perdida" and not motivo:
            raise ErrorComercial("Indica por qué se ha perdido la oportunidad.")
        ahora = db.now_iso()
        estado = {"abierta": "abierta", "ganada": "ganada", "perdida": "perdida"}[destino["tipo"]]
        conn.execute(
            "UPDATE crm_oportunidades SET etapa = ?, estado = ?, probabilidad = ?, motivo_perdida = ?, cerrada_en = ?, actualizada_en = ?, ultima_actividad_en = ? WHERE id = ? AND tenant_id = ?",
            (destino["clave"], estado, destino["probabilidad"], motivo if estado == "perdida" else None, ahora if estado != "abierta" else None, ahora, ahora, oportunidad_id, tenant_id))
        anterior = conn.execute("SELECT nombre FROM crm_etapas WHERE tenant_id = ? AND clave = ?", (tenant_id, o["etapa"])).fetchone()
        texto = f"{anterior['nombre'] if anterior else o['etapa']} → {destino['nombre']}" + (f". Motivo: {motivo}" if estado == "perdida" else "")
        conn.execute(
            "INSERT INTO crm_actividades (tenant_id, oportunidad_id, cliente_id, tipo, asunto, texto, fecha, creada_por, creada_en) VALUES (?, ?, ?, 'etapa', ?, NULL, ?, ?, ?)",
            (tenant_id, oportunidad_id, o["cliente_id"], texto[:300], ahora[:10], usuario_id, ahora))
        auditoria.registrar(tenant_id, usuario_id, "crm.oportunidad.etapa", "crm_oportunidad", oportunidad_id, {"de": o["etapa"], "a": destino["clave"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    _automatizar(tenant_id, "oportunidad.etapa_cambiada", {"oportunidad_id": oportunidad_id, "de": o["etapa"], "a": destino["clave"]})
    return obtener_oportunidad(tenant_id, usuario_id, oportunidad_id)


def papelera_oportunidad(tenant_id: int, usuario_id: int, oportunidad_id: int) -> None:
    _exigir_escritura(tenant_id, usuario_id)
    if obtener_oportunidad(tenant_id, usuario_id, oportunidad_id) is None:
        raise ErrorComercial("Oportunidad no encontrada.")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE crm_oportunidades SET papelera_en = ? WHERE id = ? AND tenant_id = ?", (db.now_iso(), oportunidad_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "crm.oportunidad.papelera", "crm_oportunidad", oportunidad_id, conn=conn)
        conn.commit()
    finally:
        conn.close()


def convertir_en_cliente(tenant_id: int, usuario_id: int, oportunidad_id: int, *, gestion_fiscal: bool = False, nif: str | None = None, ganar: bool = True) -> dict:
    """Crea la ficha de cliente del prospecto con sus datos de contacto y la enlaza a la oportunidad. Con `ganar` (por defecto) la oportunidad pasa a la etapa ganada. Con `gestion_fiscal`
    también se crea su ficha fiscal (solo si el despacho lleva la gestoría). Devuelve {cliente_id, cliente_fiscal_id}."""
    _exigir_escritura(tenant_id, usuario_id)
    o = obtener_oportunidad(tenant_id, usuario_id, oportunidad_id)
    if o is None:
        raise ErrorComercial("Oportunidad no encontrada.")
    if o["cliente_id"]:
        raise ErrorComercial("Esta oportunidad ya es de un cliente.")
    nombre = o["empresa"] or o["contacto_nombre"]
    if not nombre:
        raise ErrorComercial("Falta el nombre del prospecto.")
    if gestion_fiscal and not alta_cliente.gestion_fiscal_disponible(tenant_id):
        raise ErrorComercial("Tu despacho no lleva la gestión fiscal.")
    try:
        res = alta_cliente.crear_cliente_completo(
            tenant_id, nombre, gestion_fiscal=gestion_fiscal, nif=nif, email=o["contacto_email"], telefono=o["contacto_telefono"], origen=o["origen"] or "Comercial",
            responsable_id=o["responsable_id"], usuario_id=usuario_id)
    except ValueError as e:
        raise ErrorComercial(str(e)) from e
    conn = db.get_connection()
    try:
        conn.execute("UPDATE crm_oportunidades SET cliente_id = ?, actualizada_en = ? WHERE id = ? AND tenant_id = ?", (res["cliente_id"], db.now_iso(), oportunidad_id, tenant_id))
        conn.execute("UPDATE crm_actividades SET cliente_id = ? WHERE oportunidad_id = ?", (res["cliente_id"], oportunidad_id))
        auditoria.registrar(tenant_id, usuario_id, "crm.oportunidad.convertir", "crm_oportunidad", oportunidad_id, {"cliente_id": res["cliente_id"], "fiscal": bool(res.get("cliente_fiscal_id"))}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    if ganar and o["estado"] != "ganada":
        ganada = next(e for e in listar_etapas(tenant_id) if e["tipo"] == "ganada")
        mover_oportunidad(tenant_id, usuario_id, oportunidad_id, ganada["clave"])
    return {"cliente_id": res["cliente_id"], "cliente_fiscal_id": res.get("cliente_fiscal_id")}


# --- Actividades y seguimiento --------------------------------------------------------------------------------------------

def registrar_actividad(tenant_id: int, usuario_id: int, *, tipo: str, asunto: str, oportunidad_id: int | None = None, cliente_id: int | None = None, texto: str | None = None,
                        fecha: str | None = None, proxima_accion: str | None = None, proxima_fecha: str | None = None) -> int:
    """Anota una llamada, reunión, visita, correo o nota en la oportunidad (y en su cliente). Con `proxima_accion` crea además una tarea con fecha para quien lleva la oportunidad."""
    _exigir_escritura(tenant_id, usuario_id)
    if tipo not in TIPOS_ACTIVIDAD:
        raise ErrorComercial("El tipo de actividad no es válido.")
    asunto = _limpio(asunto, 300)
    if not asunto:
        raise ErrorComercial("Indica de qué trata.")
    o = None
    if oportunidad_id is not None:
        o = obtener_oportunidad(tenant_id, usuario_id, oportunidad_id)
        if o is None:
            raise ErrorComercial("Oportunidad no encontrada.")
        cliente_id = o["cliente_id"]
    fecha = _fecha(fecha, "Fecha") or date.today().isoformat()
    proxima_fecha = _fecha(proxima_fecha, "Fecha de la próxima acción")
    if proxima_accion and not proxima_fecha:
        raise ErrorComercial("Indica para cuándo es la próxima acción.")
    conn = db.get_connection()
    try:
        cliente_id = _cliente_del_despacho(conn, tenant_id, usuario_id, cliente_id) if o is None else cliente_id
        if o is None and cliente_id is None:
            raise ErrorComercial("La actividad tiene que ser de una oportunidad o de un cliente.")
        cur = conn.execute("INSERT INTO crm_actividades (tenant_id, oportunidad_id, cliente_id, tipo, asunto, texto, fecha, creada_por, creada_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, oportunidad_id, cliente_id, tipo, asunto, _limpio(texto, 4000), fecha, usuario_id, db.now_iso()))
        aid = cur.lastrowid
        if oportunidad_id is not None:
            conn.execute("UPDATE crm_oportunidades SET ultima_actividad_en = ? WHERE id = ? AND tenant_id = ?", (db.now_iso(), oportunidad_id, tenant_id))
        conn.commit()
    finally:
        conn.close()
    if proxima_accion:
        responsable = o["responsable_id"] if o and o["responsable_id"] else usuario_id
        ficha_fiscal = o["cliente_fiscal_id"] if o else _fiscal_de(cliente_id)
        tarea_id = db.crear_tarea_outlook(usuario_id, _limpio(proxima_accion, 300), fecha_vencimiento=proxima_fecha, asignada_a=None if responsable == usuario_id else responsable,
                                          cliente_fiscal_id=ficha_fiscal, cuerpo=f"Seguimiento comercial: {o['titulo']}" if o else None)
        conn = db.get_connection()
        try:
            conn.execute("UPDATE crm_actividades SET tarea_id = ? WHERE id = ?", (tarea_id, aid))
            conn.commit()
        finally:
            conn.close()
    return aid


def _fiscal_de(cliente_id: int | None) -> int | None:
    if not cliente_id:
        return None
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT id FROM clientes_fiscales WHERE cliente_id = ? LIMIT 1", (cliente_id,)).fetchone()
        return f["id"] if f else None
    finally:
        conn.close()


def cronologia(tenant_id: int, usuario_id: int, *, oportunidad_id: int | None = None, cliente_id: int | None = None, limite: int = 100) -> list[dict]:
    """Actividades (y reuniones) más recientes primero. De una oportunidad, o de un cliente (todas las suyas)."""
    if oportunidad_id is not None and obtener_oportunidad(tenant_id, usuario_id, oportunidad_id) is None:
        return []
    if oportunidad_id is None and (cliente_id is None or not acceso.puede_ver_cliente_nucleo(tenant_id, usuario_id, cliente_id)):
        return []
    donde, p = ["a.tenant_id = ?"], [tenant_id]
    if oportunidad_id is not None:
        donde.append("a.oportunidad_id = ?")
        p.append(oportunidad_id)
    else:
        donde.append("a.cliente_id = ?")
        p.append(cliente_id)
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute(f"SELECT a.*, t.estado AS tarea_estado, t.fecha_vencimiento AS tarea_fecha FROM crm_actividades a LEFT JOIN tareas_outlook t ON t.id = a.tarea_id "
                                               f"WHERE {' AND '.join(donde)} ORDER BY a.fecha DESC, a.id DESC LIMIT ?", [*p, max(1, min(limite, 500))])]
    finally:
        conn.close()
    for f in filas:
        f["autor"] = db.nombre_mostrado_usuario(f["creada_por"]) if f["creada_por"] else None
        f["tipo_texto"] = TIPOS_ACTIVIDAD.get(f["tipo"], "Etapa")
    from . import reuniones
    return sorted(filas + reuniones.entradas_de_cronologia(tenant_id, usuario_id, oportunidad_id=oportunidad_id, cliente_id=cliente_id), key=lambda x: (x["fecha"], x.get("id") or 0), reverse=True)[:limite]


def estancadas(tenant_id: int, usuario_id: int, dias: int = DIAS_ESTANCADA) -> list[dict]:
    """Oportunidades abiertas sin actividad desde hace `dias` días."""
    limite = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
    return [o for o in listar_oportunidades(tenant_id, usuario_id, estado="abierta", limite=MAX_OPORTUNIDADES_POR_LISTA) if (o.get("ultima_actividad_en") or o["creada_en"]) < limite]


# --- Embudo e informes ----------------------------------------------------------------------------------------------------

def embudo(tenant_id: int, usuario_id: int, desde: str | None = None, hasta: str | None = None) -> dict:
    """Lo abierto por etapa (número, importe y previsión ponderada) y, en el periodo (por defecto, 90 días), lo ganado y perdido con la tasa de éxito y el ciclo medio. Solo lo que la persona puede ver."""
    hoy = date.today()
    hasta_d = date.fromisoformat(_fecha(hasta, "Hasta") or hoy.isoformat())
    desde_d = date.fromisoformat(_fecha(desde, "Desde") or (hasta_d - timedelta(days=89)).isoformat())
    if desde_d > hasta_d:
        raise ErrorComercial("La fecha de inicio no puede ser posterior a la final.")
    etapas = listar_etapas(tenant_id)
    todas = listar_oportunidades(tenant_id, usuario_id, estado=None, limite=MAX_OPORTUNIDADES_POR_LISTA)
    por_etapa = []
    for e in (x for x in etapas if x["tipo"] == "abierta"):
        grupo = [o for o in todas if o["estado"] == "abierta" and o["etapa"] == e["clave"]]
        por_etapa.append({"clave": e["clave"], "nombre": e["nombre"], "probabilidad": e["probabilidad"], "n": len(grupo), "importe": sum(o["importe_centimos"] for o in grupo) / 100,
                          "ponderado": sum(round(o["importe_centimos"] * o["probabilidad"] / 100) for o in grupo) / 100})
    cerradas = [o for o in todas if o["estado"] != "abierta" and o["cerrada_en"] and desde_d.isoformat() <= o["cerrada_en"][:10] <= hasta_d.isoformat()]
    ganadas, perdidas = [o for o in cerradas if o["estado"] == "ganada"], [o for o in cerradas if o["estado"] == "perdida"]
    ciclos = [(date.fromisoformat(o["cerrada_en"][:10]) - date.fromisoformat(o["creada_en"][:10])).days for o in ganadas]
    por_responsable: dict = {}
    for o in cerradas:
        r = por_responsable.setdefault(o["responsable_id"], {"responsable": o["responsable"], "ganadas": 0, "perdidas": 0, "importe_ganado": 0.0})
        r["ganadas" if o["estado"] == "ganada" else "perdidas"] += 1
        if o["estado"] == "ganada":
            r["importe_ganado"] += o["importe"]
    abiertas = [o for o in todas if o["estado"] == "abierta"]
    return {
        "periodo": {"desde": desde_d.isoformat(), "hasta": hasta_d.isoformat()}, "etapas": por_etapa,
        "abiertas": {"n": len(abiertas), "importe": sum(o["importe_centimos"] for o in abiertas) / 100, "ponderado": sum(round(o["importe_centimos"] * o["probabilidad"] / 100) for o in abiertas) / 100},
        "ganadas": {"n": len(ganadas), "importe": sum(o["importe_centimos"] for o in ganadas) / 100}, "perdidas": {"n": len(perdidas), "importe": sum(o["importe_centimos"] for o in perdidas) / 100},
        "tasa_exito": round(100 * len(ganadas) / len(cerradas), 1) if cerradas else None,          # sin cerradas no hay tasa (nunca un 0 % inventado)
        "ciclo_medio_dias": round(sum(ciclos) / len(ciclos), 1) if ciclos else None,
        "motivos_perdida": _contar([o["motivo_perdida"] for o in perdidas if o["motivo_perdida"]]),
        "por_responsable": sorted(por_responsable.values(), key=lambda r: -r["importe_ganado"]),
        "estancadas": len(estancadas(tenant_id, usuario_id)),
    }


def _contar(motivos: list[str]) -> list[dict]:
    cuenta: dict[str, int] = {}
    for m in motivos:
        cuenta[m.strip().lower()] = cuenta.get(m.strip().lower(), 0) + 1
    return [{"motivo": m, "n": n} for m, n in sorted(cuenta.items(), key=lambda kv: -kv[1])[:10]]


def uso_del_mes(tenant_id: int) -> dict:
    mes = date.today().strftime("%Y-%m")
    conn = db.get_connection()
    try:
        o = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(estado = 'ganada'), 0) AS ganadas FROM crm_oportunidades WHERE tenant_id = ? AND substr(creada_en, 1, 7) = ?", (tenant_id, mes)).fetchone()
        a = conn.execute("SELECT COUNT(*) FROM crm_actividades WHERE tenant_id = ? AND substr(creada_en, 1, 7) = ? AND tipo != 'etapa'", (tenant_id, mes)).fetchone()[0]
        r = conn.execute("SELECT COUNT(*), COALESCE(SUM(acta_generada_en IS NOT NULL), 0) FROM crm_reuniones WHERE tenant_id = ? AND substr(creada_en, 1, 7) = ?", (tenant_id, mes)).fetchone()
    finally:
        conn.close()
    return {"mes": mes, "oportunidades": o["n"], "ganadas": o["ganadas"], "actividades": a, "reuniones": r[0], "actas": r[1]}


def _uso_para_backoffice(tenant_id: int) -> list[tuple[str, str]]:
    u = uso_del_mes(tenant_id)
    return [("Mes", u["mes"]), ("Oportunidades creadas", f"{u['oportunidades']} ({u['ganadas']} ganadas)"), ("Actividades anotadas", str(u["actividades"])),
            ("Reuniones", f"{u['reuniones']} ({u['actas']} con acta de IA)")]


def _registrar() -> None:
    from flask_babel import lazy_gettext as _l

    from . import verticales
    verticales.registrar(verticales.Vertical(
        "comercial", _l("Comercial"), _l("Oportunidades y embudo, seguimiento de prospectos, informes de ventas y notas de reunión con acta de IA."), "bar-chart-3",
        entradas_menu=(verticales.EntradaMenu("comercial", _l("Comercial"), "comercial.tablero", "bar-chart-3"), verticales.EntradaMenu("reuniones", _l("Reuniones"), "comercial.reuniones_lista", "users")),
        esquema=crear_esquema, borrar_datos=borrar_datos_de_tenant, uso=_uso_para_backoffice))


_registrar()
