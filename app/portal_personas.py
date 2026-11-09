"""Las personas que entran al portal de un cliente: el titular (el email de su ficha) y los contactos que el propio cliente o la gestoría dan de alta (su administrativa, su asesor externo…).

Cada contacto tiene un **perfil** y entra con su propio email:
- `completo`: todo, incluido firmar, pagar, dar su conformidad y gestionar a las demás personas (el titular siempre lo es);
- `administracion`: subir documentos y facturas y escribir, pero no firmar, ni pagar, ni dar la conformidad de un modelo;
- `consulta`: solo mirar.

También guarda **cuánto quiere saber cada persona** (`avisos`): `todo` (un correo por cada novedad), `resumen` (solo el resumen de los lunes) o `urgente` (solo lo que corre prisa).
Una persona que entra con un email que figura en varias fichas (varias sociedades) ve a todas y puede cambiar de una a otra: la lista se calcula siempre desde la base, nunca se fía de la sesión."""
from __future__ import annotations

import re
from datetime import datetime

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS portal_contactos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    nombre TEXT NOT NULL DEFAULT '',
    rol TEXT NOT NULL DEFAULT 'administracion' CHECK (rol IN ('completo', 'administracion', 'consulta')),
    avisos TEXT NOT NULL DEFAULT 'todo' CHECK (avisos IN ('todo', 'resumen', 'urgente')),
    bienvenida_en TEXT,
    ultimo_acceso_en TEXT,
    creado_por INTEGER,
    creado_en TEXT NOT NULL,
    baja_en TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_contactos_email ON portal_contactos(tenant_id, cliente_fiscal_id, email);
CREATE INDEX IF NOT EXISTS idx_portal_contactos_buscar ON portal_contactos(email);
CREATE TABLE IF NOT EXISTS portal_avisos_enviados (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    destinatario TEXT NOT NULL,
    tipo TEXT NOT NULL,
    referencia TEXT NOT NULL,
    enviado_en TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_avisos_unico ON portal_avisos_enviados(tenant_id, cliente_fiscal_id, destinatario, tipo, referencia);
CREATE TABLE IF NOT EXISTS portal_suscripciones_push (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    suscripcion TEXT NOT NULL,
    creado_en TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_push_endpoint ON portal_suscripciones_push(tenant_id, cliente_fiscal_id, endpoint);
CREATE TABLE IF NOT EXISTS portal_enlaces_subida (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    token TEXT NOT NULL,
    creado_en TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_enlaces_cliente ON portal_enlaces_subida(tenant_id, cliente_fiscal_id);
CREATE INDEX IF NOT EXISTS idx_portal_enlaces_token ON portal_enlaces_subida(token);
CREATE TABLE IF NOT EXISTS portal_respuestas_rapidas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    titulo TEXT NOT NULL,
    texto TEXT NOT NULL,
    creado_por INTEGER,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_portal_respuestas_tenant ON portal_respuestas_rapidas(tenant_id, titulo);
"""

ROLES = ("completo", "administracion", "consulta")
NIVELES_AVISO = ("todo", "resumen", "urgente")
MAX_CONTACTOS = 10
_EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)
    db._asegurar_columna(conn, "clientes_fiscales", "portal_avisos", "TEXT NOT NULL DEFAULT 'todo'")
    db._asegurar_columna(conn, "clientes_fiscales", "portal_bienvenida_en", "TEXT")
    db._asegurar_columna(conn, "clientes_fiscales_accesos", "email", "TEXT")
    db._asegurar_columna(conn, "portal_recordatorios_config", "correo_facturas", "TEXT")
    db._asegurar_columna(conn, "portal_recordatorios_config", "lectura_previa", "INTEGER NOT NULL DEFAULT 0")
    db._asegurar_columna(conn, "portal_recordatorios_config", "embudo_uso", "INTEGER NOT NULL DEFAULT 0")     # embudo de uso del portal para el despacho (app/portal_adopcion.py)
    db._asegurar_columna(conn, "portal_recordatorios_config", "telemetria", "INTEGER NOT NULL DEFAULT 0")     # salud del portal desde el navegador de los clientes (app/portal_telemetria.py)
    db._asegurar_columna(conn, "portal_recordatorios_config", "asistente_cliente", "INTEGER NOT NULL DEFAULT 0")     # asistente del portal para el cliente (app/portal_asistente.py)


def limpio(email: str | None) -> str:
    return (email or "").strip().lower()


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --- Quién es quién -------------------------------------------------------------------------------------------------------------------------------------

def listar(cliente) -> list[dict]:
    """El titular primero y después los contactos dados de alta: [{id, email, nombre, rol, avisos, es_titular}]. El titular no tiene `id` (es la propia ficha)."""
    personas = []
    if limpio(cliente["email"]):
        personas.append({"id": None, "email": limpio(cliente["email"]), "nombre": cliente["nombre"], "rol": "completo", "avisos": cliente["portal_avisos"] or "todo", "es_titular": True})
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT id, email, nombre, rol, avisos FROM portal_contactos WHERE cliente_fiscal_id = ? AND baja_en IS NULL ORDER BY nombre, email", (cliente["id"],)).fetchall()
    finally:
        conn.close()
    personas += [{"id": f["id"], "email": f["email"], "nombre": f["nombre"], "rol": f["rol"], "avisos": f["avisos"], "es_titular": False} for f in filas]
    return personas


def clientes_de(email: str | None) -> list:
    """Las fichas a las que da acceso este email: aquellas de las que es titular y aquellas en que es contacto. Ordenadas por nombre."""
    e = limpio(email)
    if not e or "@" not in e:
        return []
    conn = db.get_connection()
    try:
        titular = conn.execute("SELECT * FROM clientes_fiscales WHERE LOWER(email) = ? AND papelera_en IS NULL", (e,)).fetchall()
        como_contacto = conn.execute(
            "SELECT c.* FROM clientes_fiscales c JOIN portal_contactos p ON p.cliente_fiscal_id = c.id AND p.tenant_id = c.tenant_id WHERE p.email = ? AND p.baja_en IS NULL AND c.papelera_en IS NULL", (e,)).fetchall()
    finally:
        conn.close()
    vistos, todos = set(), []
    for c in [*titular, *como_contacto]:
        if c["id"] not in vistos:
            vistos.add(c["id"])
            todos.append(c)
    return sorted(todos, key=lambda c: (c["nombre"] or "").lower())


def rol_de(cliente, email: str | None) -> str | None:
    """El perfil de `email` en esta ficha, o None si ya no tiene acceso. Sin email (sesiones anteriores a los contactos, o la vista previa del equipo) es el del titular."""
    if not email:
        return "completo"
    e = limpio(email)
    if e == limpio(cliente["email"]):
        return "completo"
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT rol FROM portal_contactos WHERE cliente_fiscal_id = ? AND email = ? AND baja_en IS NULL", (cliente["id"], e)).fetchone()
    finally:
        conn.close()
    return f["rol"] if f else None


def _comprobar(email: str, rol: str, cliente) -> str:
    e = limpio(email)
    if not _EMAIL.match(e) or len(e) > 200:
        raise ValueError("Escribe un email válido.")
    if rol not in ROLES:
        raise ValueError("Perfil no válido.")
    if e == limpio(cliente["email"]):
        raise ValueError("Ese email ya es el del titular.")
    return e


def anadir(cliente, email: str, nombre: str, rol: str, por: int | None = None) -> int:
    e = _comprobar(email, rol, cliente)
    nombre = re.sub(r"\s+", " ", nombre or "").strip()[:120]
    conn = db.get_connection()
    try:
        previa = conn.execute("SELECT id, baja_en FROM portal_contactos WHERE tenant_id = ? AND cliente_fiscal_id = ? AND email = ?", (cliente["tenant_id"], cliente["id"], e)).fetchone()
        if previa is not None and previa["baja_en"] is None:
            raise ValueError("Esa persona ya tiene acceso.")
        activos = conn.execute("SELECT COUNT(*) FROM portal_contactos WHERE cliente_fiscal_id = ? AND baja_en IS NULL", (cliente["id"],)).fetchone()[0]
        if activos >= MAX_CONTACTOS:
            raise ValueError(f"Cada cliente puede tener hasta {MAX_CONTACTOS} personas más con acceso.")
        if previa is not None:
            conn.execute("UPDATE portal_contactos SET baja_en = NULL, nombre = ?, rol = ?, creado_por = ?, creado_en = ? WHERE id = ?", (nombre, rol, por, _ahora(), previa["id"]))
            nuevo = previa["id"]
        else:
            nuevo = conn.execute("INSERT INTO portal_contactos (tenant_id, cliente_fiscal_id, email, nombre, rol, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                 (cliente["tenant_id"], cliente["id"], e, nombre, rol, por, _ahora())).lastrowid
        conn.commit()
        return nuevo
    finally:
        conn.close()


def cambiar_rol(cliente, contacto_id: int, rol: str) -> None:
    if rol not in ROLES:
        raise ValueError("Perfil no válido.")
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_contactos SET rol = ? WHERE id = ? AND cliente_fiscal_id = ? AND baja_en IS NULL", (rol, contacto_id, cliente["id"])).rowcount
        conn.commit()
    finally:
        conn.close()
    if not n:
        raise ValueError("Esa persona no existe.")


def quitar(cliente, contacto_id: int) -> str:
    """Da de baja a un contacto (pierde el acceso al instante: la sesión se comprueba contra la base en cada petición). Devuelve su email."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT email FROM portal_contactos WHERE id = ? AND cliente_fiscal_id = ? AND baja_en IS NULL", (contacto_id, cliente["id"])).fetchone()
        if f is None:
            raise ValueError("Esa persona no existe.")
        conn.execute("UPDATE portal_contactos SET baja_en = ? WHERE id = ?", (_ahora(), contacto_id))
        conn.execute("DELETE FROM portal_suscripciones_push WHERE cliente_fiscal_id = ? AND email = ?", (cliente["id"], f["email"]))
        conn.commit()
        from . import portal_seguridad
        portal_seguridad.quitar_a(cliente, f["email"])
        from . import portal_passkeys
        portal_passkeys.quitar_de_persona(cliente, f["email"])
        return f["email"]
    finally:
        conn.close()


def registrar_acceso(cliente, email: str | None) -> None:
    if not email or limpio(email) == limpio(cliente["email"]):
        return
    conn = db.get_connection()
    try:
        conn.execute("UPDATE portal_contactos SET ultimo_acceso_en = ? WHERE cliente_fiscal_id = ? AND email = ?", (_ahora(), cliente["id"], limpio(email)))
        conn.commit()
    finally:
        conn.close()


# --- Cuánto quiere saber cada persona -------------------------------------------------------------------------------------------------------------------

def avisos_de(cliente, email: str | None) -> str:
    e = limpio(email) or limpio(cliente["email"])
    if e == limpio(cliente["email"]):
        return cliente["portal_avisos"] or "todo"
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT avisos FROM portal_contactos WHERE cliente_fiscal_id = ? AND email = ? AND baja_en IS NULL", (cliente["id"], e)).fetchone()
    finally:
        conn.close()
    return f["avisos"] if f else "todo"


def fijar_avisos(cliente, email: str | None, nivel: str) -> None:
    if nivel not in NIVELES_AVISO:
        raise ValueError("Elige una de las opciones.")
    e = limpio(email) or limpio(cliente["email"])
    conn = db.get_connection()
    try:
        if e == limpio(cliente["email"]):
            conn.execute("UPDATE clientes_fiscales SET portal_avisos = ? WHERE id = ?", (nivel, cliente["id"]))
        else:
            n = conn.execute("UPDATE portal_contactos SET avisos = ? WHERE cliente_fiscal_id = ? AND email = ? AND baja_en IS NULL", (nivel, cliente["id"], e)).rowcount
            if not n:
                raise ValueError("Esa persona no tiene acceso.")
        conn.commit()
    finally:
        conn.close()


PERFILES_QUE_PUEDEN = {"decidir": ("completo",), "subir": ("completo", "administracion"), None: ROLES}


def destinatarios(cliente, urgente: bool = False, accion: str | None = None) -> list[str]:
    """A quién se le manda YA un correo de novedad: a quien tiene el aviso en `todo` y, si es urgente, también a quien lo tiene en `urgente`. `accion` limita por perfil: «decidir» (firmar, pagar, dar su conformidad)
    solo llega a quien puede hacerlo; «subir» (pedir documentos) a quien puede subirlos."""
    permitidos = PERFILES_QUE_PUEDEN[accion]
    return [p["email"] for p in listar(cliente) if p["rol"] in permitidos and (p["avisos"] == "todo" or (urgente and p["avisos"] == "urgente"))]


def para_resumen(cliente) -> list[dict]:
    """Quién recibe el resumen semanal: quien lo eligió como su forma de enterarse."""
    return [p for p in listar(cliente) if p["avisos"] == "resumen"]


# --- Enlace de preferencias desde el correo (sin iniciar sesión) -------------------------------------------------------------------------------------------

def _serializador():
    from itsdangerous import URLSafeTimedSerializer
    try:
        from flask import current_app
        secreto = current_app.secret_key
    except RuntimeError:
        import os
        secreto = os.environ.get("GUILDA_SECRET_KEY")
    if not secreto:
        raise RuntimeError("Sin clave secreta no se pueden firmar enlaces.")
    return URLSafeTimedSerializer(secreto, salt="portal-preferencias")


def token_preferencias(cliente_id: int, email: str) -> str:
    return _serializador().dumps([int(cliente_id), limpio(email)])


def leer_token_preferencias(token: str):
    """(cliente, email) si el enlace es de verdad, vigente (un año) y la persona sigue teniendo acceso; si no, None."""
    from itsdangerous import BadSignature
    try:
        cliente_id, email = _serializador().loads(token, max_age=365 * 24 * 3600)
    except (BadSignature, ValueError, TypeError):
        return None
    cliente = db.obtener_cliente_fiscal_por_id(int(cliente_id))
    if cliente is None or rol_de(cliente, email) is None or not email:
        return None
    return cliente, email


# --- Primera visita -----------------------------------------------------------------------------------------------------------------------------------------

def bienvenida_vista(cliente, email: str | None) -> bool:
    e = limpio(email) or limpio(cliente["email"])
    if e == limpio(cliente["email"]):
        return bool(cliente["portal_bienvenida_en"])
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT bienvenida_en FROM portal_contactos WHERE cliente_fiscal_id = ? AND email = ?", (cliente["id"], e)).fetchone()
    finally:
        conn.close()
    return bool(f and f["bienvenida_en"])


def marcar_bienvenida(cliente, email: str | None) -> None:
    e = limpio(email) or limpio(cliente["email"])
    conn = db.get_connection()
    try:
        if e == limpio(cliente["email"]):
            conn.execute("UPDATE clientes_fiscales SET portal_bienvenida_en = ? WHERE id = ?", (_ahora(), cliente["id"]))
        else:
            conn.execute("UPDATE portal_contactos SET bienvenida_en = ? WHERE cliente_fiscal_id = ? AND email = ?", (_ahora(), cliente["id"], e))
        conn.commit()
    finally:
        conn.close()
