"""Núcleo común de Guilda Work: clientes (con contactos y etiquetas), expedientes, plazos, festivos y horas facturables. Lo comparten los tres módulos
de negocio (Gestoría, Gabinete de abogados, Inmobiliaria: `app/verticales.py`) y cada uno cuelga de aquí en vez de tener su propio «cliente».

Es **aditivo**: `clientes_fiscales` sigue existiendo y funcionando igual; cada cliente fiscal tiene además una ficha en `clientes` (`clientes_fiscales.cliente_id`)
y los datos comunes —nombre, NIF, email, idioma, papelera— se mantienen sincronizados en las dos direcciones. Todo está acotado por `tenant_id`.

Las pantallas viven en `app/rutas_nucleo.py`. Los cálculos de fechas, en `app/calendario_plazos.py` (puro)."""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, timedelta

from . import calendario_plazos as cp
from . import db, verticales

ESQUEMA = """
CREATE TABLE IF NOT EXISTS tenants_verticales (
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    vertical_id TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    activo_hasta TEXT,
    creado_en TEXT NOT NULL,
    PRIMARY KEY (tenant_id, vertical_id)
);

CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    tipo TEXT NOT NULL DEFAULT 'persona' CHECK (tipo IN ('persona', 'empresa')),
    nombre TEXT NOT NULL,
    nif TEXT,
    email TEXT,
    telefono TEXT,
    direccion TEXT,
    idioma TEXT,
    origen TEXT,
    responsable_id INTEGER REFERENCES usuarios(id),
    notas TEXT,
    creado_en TEXT NOT NULL,
    actualizado_en TEXT,
    papelera_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_clientes_tenant ON clientes(tenant_id, papelera_en, nombre);
CREATE INDEX IF NOT EXISTS idx_clientes_nif ON clientes(tenant_id, nif);

CREATE TABLE IF NOT EXISTS cliente_contactos (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    cargo TEXT,
    email TEXT,
    telefono TEXT,
    rol TEXT,
    principal INTEGER NOT NULL DEFAULT 0,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cliente_contactos_cliente ON cliente_contactos(cliente_id);

CREATE TABLE IF NOT EXISTS cliente_etiquetas (
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    etiqueta TEXT NOT NULL,
    PRIMARY KEY (cliente_id, etiqueta)
);

CREATE TABLE IF NOT EXISTS expedientes (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    vertical_id TEXT NOT NULL DEFAULT 'general',
    tipo TEXT NOT NULL DEFAULT 'general',
    referencia TEXT,
    titulo TEXT NOT NULL,
    descripcion TEXT,
    estado TEXT NOT NULL DEFAULT 'abierto',
    responsable_id INTEGER REFERENCES usuarios(id),
    confidencial INTEGER NOT NULL DEFAULT 0,
    datos TEXT,
    abierto_en TEXT NOT NULL,
    cerrado_en TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    actualizado_en TEXT,
    papelera_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_expedientes_tenant ON expedientes(tenant_id, papelera_en, estado);
CREATE INDEX IF NOT EXISTS idx_expedientes_cliente ON expedientes(cliente_id);

CREATE TABLE IF NOT EXISTS expediente_miembros (
    expediente_id INTEGER NOT NULL REFERENCES expedientes(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    PRIMARY KEY (expediente_id, usuario_id)
);

CREATE TABLE IF NOT EXISTS expediente_eventos (
    id INTEGER PRIMARY KEY,
    expediente_id INTEGER NOT NULL REFERENCES expedientes(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL,
    texto TEXT NOT NULL,
    usuario_id INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_expediente_eventos ON expediente_eventos(expediente_id, creado_en);

CREATE TABLE IF NOT EXISTS plazos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    expediente_id INTEGER REFERENCES expedientes(id) ON DELETE CASCADE,
    cliente_id INTEGER REFERENCES clientes(id),
    titulo TEXT NOT NULL,
    fecha_limite TEXT NOT NULL,
    origen TEXT NOT NULL DEFAULT 'manual',
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'cumplido')),
    critico INTEGER NOT NULL DEFAULT 0,
    avisos TEXT NOT NULL DEFAULT '7,3,1',
    responsable_id INTEGER REFERENCES usuarios(id),
    revisado_por INTEGER REFERENCES usuarios(id),
    revisado_en TEXT,
    notas TEXT,
    cumplido_en TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    papelera_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_plazos_tenant ON plazos(tenant_id, papelera_en, estado, fecha_limite);
CREATE INDEX IF NOT EXISTS idx_plazos_expediente ON plazos(expediente_id, estado, papelera_en, fecha_limite);

CREATE TABLE IF NOT EXISTS festivos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    fecha TEXT NOT NULL,
    nombre TEXT NOT NULL,
    UNIQUE (tenant_id, fecha)
);

CREATE TABLE IF NOT EXISTS partes_tiempo (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    cliente_id INTEGER REFERENCES clientes(id),
    expediente_id INTEGER REFERENCES expedientes(id) ON DELETE SET NULL,
    tarea_id INTEGER,
    descripcion TEXT NOT NULL,
    fecha TEXT NOT NULL,
    segundos INTEGER NOT NULL CHECK (segundos > 0),
    facturable INTEGER NOT NULL DEFAULT 1,
    tarifa_hora_centimos INTEGER,
    facturado_en TEXT,
    creado_en TEXT NOT NULL,
    papelera_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_partes_tenant ON partes_tiempo(tenant_id, papelera_en, fecha);
CREATE INDEX IF NOT EXISTS idx_partes_cliente ON partes_tiempo(cliente_id);
CREATE INDEX IF NOT EXISTS idx_partes_expediente ON partes_tiempo(expediente_id);
"""


def crear_esquema(conn) -> None:
    """Tablas del núcleo y sus enlaces con lo que ya existía. Se llama al final de `db.init_db()`; es idempotente."""
    conn.executescript(ESQUEMA)
    from . import almacen_documentos
    conn.executescript(almacen_documentos.ESQUEMA)
    db._asegurar_columna(conn, "cliente_documentos", "cifrado", "INTEGER NOT NULL DEFAULT 0")     # expediente documental fiscal: mismo cifrado que `documentos`
    db._asegurar_columna(conn, "cliente_documentos", "sobre", "TEXT")
    db._asegurar_columna(conn, "accesos_contenido", "tabla", "TEXT NOT NULL DEFAULT 'documentos'")
    # Correo cifrado (app/correo_cifrado.py): bloque cifrado por mensaje, su sobre y el nivel con el que se selló; adjuntos sellados; bandera por despacho.
    db._asegurar_columna(conn, "cifrado_despacho", "correo_activo", "INTEGER NOT NULL DEFAULT 0")
    db._asegurar_columna(conn, "cifrado_despacho", "correo_activado_en", "TEXT")
    db._asegurar_columna(conn, "correo_mensajes", "cifrado", "INTEGER NOT NULL DEFAULT 0")
    db._asegurar_columna(conn, "correo_mensajes", "cifrado_nivel", "TEXT")
    db._asegurar_columna(conn, "correo_mensajes", "sobre", "TEXT")
    db._asegurar_columna(conn, "correo_mensajes", "datos", "BLOB")
    db._asegurar_columna(conn, "correo_adjuntos", "cifrado", "INTEGER NOT NULL DEFAULT 0")
    db._asegurar_columna(conn, "correo_adjuntos", "sobre", "TEXT")
    db._asegurar_columna(conn, "correo_adjuntos", "nombre_cifrado", "TEXT")
    db._asegurar_columna(conn, "documentos", "compartido_cliente", "INTEGER NOT NULL DEFAULT 0")    # el despacho lo enseña al cliente (enlace de solo lectura)
    for v in verticales.VERTICALES.values():
        if v.esquema:
            v.esquema(conn)
    db._asegurar_columna(conn, "clientes_fiscales", "cliente_id", "INTEGER REFERENCES clientes(id)")
    db._asegurar_columna(conn, "extras_guilda", "vertical_id", "TEXT")           # qué módulo de negocio activa este extra (app/verticales.py)
    db._asegurar_columna(conn, "usuarios", "tarifa_hora_centimos", "INTEGER")    # tarifa por defecto de sus partes de horas
    conn.execute("CREATE INDEX IF NOT EXISTS idx_clientes_fiscales_cliente ON clientes_fiscales(cliente_id)")
    _rellenar_clientes_desde_fiscales(conn)


# --- Utilidades -----------------------------------------------------------------------------------------------------------------------------
_CIF = re.compile(r"^[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]$", re.I)


def inferir_tipo(nif: str | None) -> str:
    """«empresa» si el NIF tiene forma de CIF, «persona» en cualquier otro caso (DNI, NIE o sin dato). Es una sugerencia, se puede corregir."""
    return "empresa" if _CIF.match((nif or "").strip().replace("-", "").replace(" ", "")) else "persona"


def plano(texto) -> str:
    """Minúsculas y sin acentos, para buscar «maria» y encontrar «María»."""
    return "".join(c for c in unicodedata.normalize("NFD", str(texto or "").lower()) if unicodedata.category(c) != "Mn")


def _conn_con_busqueda():
    conn = db.get_connection()
    conn.create_function("plano", 1, plano, deterministic=True)
    return conn


_MILES = re.compile(r"^\d{1,3}(\.\d{3})+$")


def importe_a_centimos(valor) -> int:
    """Un importe escrito a la española («250.000», «1.234,56», «150,5», «12.5») → céntimos. El punto se lee como separador de miles si va seguido de grupos de tres cifras
    («250.000» son doscientos cincuenta mil) y como decimal en cualquier otro caso («12.5»); la coma siempre es decimal. Un entero ya son céntimos."""
    if isinstance(valor, int) and not isinstance(valor, bool):
        return valor
    texto = str(valor if valor is not None else "").replace("€", "").replace("\xa0", "").replace(" ", "")
    if not texto:
        raise ValueError("El importe no es válido.")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif _MILES.match(texto):
        texto = texto.replace(".", "")
    try:
        return int(round(float(texto) * 100))
    except ValueError:
        raise ValueError("El importe no es válido.") from None


def _limpio(v, largo: int = 200) -> str | None:
    return ((v or "").strip()[:largo]) or None


def _fecha_iso(valor, campo: str = "La fecha") -> str:
    try:
        return date.fromisoformat(str(valor)[:10]).isoformat()
    except (TypeError, ValueError):
        raise ValueError(f"{campo} no es válida (usa AAAA-MM-DD).") from None


def _de_tenant(conn, tabla: str, fila_id, tenant_id: int, mensaje: str):
    """Comprueba que la fila existe y es del despacho; devuelve la fila."""
    f = conn.execute(f"SELECT * FROM {tabla} WHERE id = ? AND tenant_id = ?", (fila_id, tenant_id)).fetchone()
    if f is None:
        raise ValueError(mensaje)
    return f


def _usuario_de_tenant(conn, usuario_id, tenant_id: int, campo: str = "La persona") -> None:
    if usuario_id is not None and conn.execute("SELECT 1 FROM usuarios WHERE id = ? AND tenant_id = ?", (usuario_id, tenant_id)).fetchone() is None:
        raise ValueError(f"{campo} no pertenece a este despacho.")


def equipo(tenant_id: int) -> list:
    """Personas del despacho (id, nombre) para los selectores de responsable."""
    conn = db.get_connection()
    try:
        return conn.execute("SELECT u.id, COALESCE(NULLIF(p.nombre_mostrado, ''), u.email) AS nombre FROM usuarios u LEFT JOIN usuario_perfil p ON p.usuario_id = u.id "
                            "WHERE u.tenant_id = ? ORDER BY lower(nombre)", (tenant_id,)).fetchall()
    finally:
        conn.close()


# --- Clientes ---------------------------------------------------------------------------------------------------------------------------------
CAMPOS_CLIENTE = ("tipo", "nombre", "nif", "email", "telefono", "direccion", "idioma", "origen", "responsable_id", "notas")
IDIOMAS = ("es", "ca", "en", "fr")


def _rellenar_clientes_desde_fiscales(conn) -> None:
    """Crea la ficha del núcleo de cada cliente fiscal que aún no la tiene (migración idempotente)."""
    for f in conn.execute("SELECT id, tenant_id, nombre, nif, email, notas, idioma, creado_en, papelera_en FROM clientes_fiscales WHERE cliente_id IS NULL").fetchall():
        cur = conn.execute(
            "INSERT INTO clientes (tenant_id, tipo, nombre, nif, email, idioma, notas, creado_en, papelera_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f["tenant_id"], inferir_tipo(f["nif"]), f["nombre"], f["nif"], f["email"], f["idioma"] if f["idioma"] in IDIOMAS else None, f["notas"], f["creado_en"], f["papelera_en"]),
        )
        conn.execute("UPDATE clientes_fiscales SET cliente_id = ? WHERE id = ?", (cur.lastrowid, f["id"]))


def vincular_cliente_fiscal(tenant_id: int, cliente_fiscal_id: int) -> int | None:
    """Garantiza la ficha del núcleo de un cliente fiscal (lo llama `db.crear_cliente_fiscal`). Devuelve el id de `clientes`."""
    conn = db.get_connection()
    try:
        _rellenar_clientes_desde_fiscales(conn)
        conn.commit()
        f = conn.execute("SELECT cliente_id FROM clientes_fiscales WHERE id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id)).fetchone()
        return f["cliente_id"] if f else None
    finally:
        conn.close()


def sincronizar_desde_fiscal(tenant_id: int, cliente_fiscal_id: int) -> None:
    """Copia nombre, NIF, email, idioma y papelera del cliente fiscal a su ficha del núcleo (lo llama `db` al editarlo, borrarlo o restaurarlo)."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT cliente_id, nombre, nif, email, idioma, papelera_en FROM clientes_fiscales WHERE id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id)).fetchone()
        if f is None:
            return
        if f["cliente_id"] is None:
            _rellenar_clientes_desde_fiscales(conn)
        else:
            conn.execute(
                "UPDATE clientes SET nombre = ?, nif = ?, email = ?, idioma = COALESCE(?, idioma), papelera_en = ?, actualizado_en = ? WHERE id = ? AND tenant_id = ?",
                (f["nombre"], f["nif"], f["email"], f["idioma"] if f["idioma"] in IDIOMAS else None, f["papelera_en"], db.now_iso(), f["cliente_id"], tenant_id),
            )
        conn.commit()
    finally:
        conn.close()


def crear_cliente(tenant_id: int, nombre: str, *, tipo: str | None = None, nif: str | None = None, email: str | None = None, telefono: str | None = None,
                  direccion: str | None = None, idioma: str | None = None, origen: str | None = None, responsable_id: int | None = None,
                  notas: str | None = None, etiquetas: list[str] | None = None) -> int:
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("Indica el nombre del cliente.")
    if len(nombre) > 200:
        raise ValueError("El nombre es demasiado largo (máx. 200 caracteres).")
    nif = _limpio(nif, 30)
    tipo = tipo or inferir_tipo(nif)
    if tipo not in ("persona", "empresa"):
        raise ValueError("El tipo de cliente debe ser «persona» o «empresa».")
    if idioma and idioma not in IDIOMAS:
        raise ValueError("Idioma no válido.")
    conn = db.get_connection()
    try:
        _usuario_de_tenant(conn, responsable_id, tenant_id, "El responsable")
        cur = conn.execute(
            "INSERT INTO clientes (tenant_id, tipo, nombre, nif, email, telefono, direccion, idioma, origen, responsable_id, notas, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, tipo, nombre, nif, _limpio(email, 200), _limpio(telefono, 40), _limpio(direccion, 300), idioma or None, _limpio(origen, 100), responsable_id, _limpio(notas, 4000), db.now_iso()),
        )
        cliente_id = cur.lastrowid
        _guardar_etiquetas(conn, cliente_id, etiquetas or [])
        conn.commit()
        return cliente_id
    finally:
        conn.close()


def obtener_cliente(tenant_id: int, cliente_id: int):
    conn = db.get_connection()
    try:
        return conn.execute(
            "SELECT c.*, cf.id AS cliente_fiscal_id, (SELECT nombre_mostrado FROM usuario_perfil WHERE usuario_id = c.responsable_id) AS responsable_nombre "
            "FROM clientes c LEFT JOIN clientes_fiscales cf ON cf.cliente_id = c.id WHERE c.id = ? AND c.tenant_id = ?", (cliente_id, tenant_id)).fetchone()
    finally:
        conn.close()


def editar_cliente(tenant_id: int, cliente_id: int, **campos) -> None:
    columnas = [c for c in campos if c in CAMPOS_CLIENTE]
    conn = db.get_connection()
    try:
        _de_tenant(conn, "clientes", cliente_id, tenant_id, "Cliente no encontrado.")
        valores = []
        for c in columnas:
            v = campos[c]
            if c == "nombre":
                v = (v or "").strip()
                if not v:
                    raise ValueError("El nombre no puede quedar vacío.")
            elif c == "tipo":
                if v not in ("persona", "empresa"):
                    raise ValueError("El tipo de cliente debe ser «persona» o «empresa».")
            elif c == "idioma":
                if v and v not in IDIOMAS:
                    raise ValueError("Idioma no válido.")
                v = v or None
            elif c == "responsable_id":
                _usuario_de_tenant(conn, v, tenant_id, "El responsable")
            else:
                v = _limpio(v, 4000 if c == "notas" else 300)
            valores.append(v)
        if columnas:
            conn.execute(f"UPDATE clientes SET {', '.join(c + ' = ?' for c in columnas)}, actualizado_en = ? WHERE id = ? AND tenant_id = ?", [*valores, db.now_iso(), cliente_id, tenant_id])
            # Los datos comunes viajan también a la ficha fiscal, si la tiene (el resto de la app de gestoría lee de ahí)
            comunes = {c: v for c, v in zip(columnas, valores) if c in ("nombre", "nif", "email", "idioma")}
            propagables = {c: v for c, v in comunes.items() if c != "idioma" or v}      # un idioma vacío no borra el de la ficha fiscal (allí es obligatorio)
            if propagables:
                conn.execute(f"UPDATE clientes_fiscales SET {', '.join(c + ' = ?' for c in propagables)} WHERE cliente_id = ? AND tenant_id = ?", [*propagables.values(), cliente_id, tenant_id])
        conn.commit()
    finally:
        conn.close()
    if "nombre" in columnas or "nif" in columnas or "email" in columnas:
        _reindexar_fiscal_de(tenant_id, cliente_id)


def _reindexar_fiscal_de(tenant_id: int, cliente_id: int) -> None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT id FROM clientes_fiscales WHERE cliente_id = ? AND tenant_id = ?", (cliente_id, tenant_id)).fetchone()
    finally:
        conn.close()
    if f:
        db._reindexar_cliente_fiscal(tenant_id, f["id"])


def papelera_cliente(tenant_id: int, cliente_id: int, en_papelera: bool = True) -> None:
    conn = db.get_connection()
    try:
        _de_tenant(conn, "clientes", cliente_id, tenant_id, "Cliente no encontrado.")
        marca = db._marca_papelera() if en_papelera else None
        conn.execute("UPDATE clientes SET papelera_en = ?, actualizado_en = ? WHERE id = ? AND tenant_id = ?", (marca, db.now_iso(), cliente_id, tenant_id))
        conn.execute("UPDATE clientes_fiscales SET papelera_en = ? WHERE cliente_id = ? AND tenant_id = ?", (marca, cliente_id, tenant_id))
        conn.commit()
    finally:
        conn.close()
    _reindexar_fiscal_de(tenant_id, cliente_id)


def listar_clientes(tenant_id: int, q: str | None = None, etiqueta: str | None = None, tipo: str | None = None, *, limite: int = 100, pagina: int = 1,
                    papelera: bool = False) -> tuple[list, int]:
    """(filas, total). Busca por nombre, NIF, email, teléfono o contacto, sin distinguir mayúsculas."""
    donde, p = ["c.tenant_id = ?", "c.papelera_en IS NOT NULL" if papelera else "c.papelera_en IS NULL"], [tenant_id]
    if q and q.strip():
        like = f"%{plano(q.strip())}%"
        donde.append("(plano(c.nombre) LIKE ? OR plano(c.nif) LIKE ? OR plano(c.email) LIKE ? OR plano(c.telefono) LIKE ? "
                     "OR EXISTS (SELECT 1 FROM cliente_contactos k WHERE k.cliente_id = c.id AND (plano(k.nombre) LIKE ? OR plano(k.email) LIKE ?)))")
        p += [like] * 6
    if etiqueta:
        donde.append("EXISTS (SELECT 1 FROM cliente_etiquetas e WHERE e.cliente_id = c.id AND e.etiqueta = ?)")
        p.append(etiqueta.strip().lower())
    if tipo in ("persona", "empresa"):
        donde.append("c.tipo = ?")
        p.append(tipo)
    cond = " AND ".join(donde)
    limite = max(1, min(int(limite), 500))
    conn = _conn_con_busqueda()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM clientes c WHERE {cond}", p).fetchone()[0]
        filas = conn.execute(
            f"SELECT c.*, (SELECT group_concat(etiqueta, ',') FROM cliente_etiquetas WHERE cliente_id = c.id) AS etiquetas, "
            f"(SELECT COUNT(*) FROM expedientes x WHERE x.cliente_id = c.id AND x.papelera_en IS NULL AND x.estado != 'cerrado') AS expedientes_abiertos "
            f"FROM clientes c WHERE {cond} ORDER BY lower(c.nombre) LIMIT ? OFFSET ?", [*p, limite, (max(1, pagina) - 1) * limite]).fetchall()
        return filas, total
    finally:
        conn.close()


# Contactos y etiquetas
def _guardar_etiquetas(conn, cliente_id: int, etiquetas: list[str]) -> None:
    limpias = sorted({e.strip().lower()[:40] for e in etiquetas if e and e.strip()})[:20]
    conn.execute("DELETE FROM cliente_etiquetas WHERE cliente_id = ?", (cliente_id,))
    conn.executemany("INSERT INTO cliente_etiquetas (cliente_id, etiqueta) VALUES (?, ?)", [(cliente_id, e) for e in limpias])


def poner_etiquetas(tenant_id: int, cliente_id: int, etiquetas: list[str]) -> list[str]:
    conn = db.get_connection()
    try:
        _de_tenant(conn, "clientes", cliente_id, tenant_id, "Cliente no encontrado.")
        _guardar_etiquetas(conn, cliente_id, etiquetas)
        conn.commit()
        return [f["etiqueta"] for f in conn.execute("SELECT etiqueta FROM cliente_etiquetas WHERE cliente_id = ? ORDER BY etiqueta", (cliente_id,))]
    finally:
        conn.close()


def etiquetas_de(cliente_id: int) -> list[str]:
    conn = db.get_connection()
    try:
        return [f["etiqueta"] for f in conn.execute("SELECT etiqueta FROM cliente_etiquetas WHERE cliente_id = ? ORDER BY etiqueta", (cliente_id,))]
    finally:
        conn.close()


def etiquetas_del_despacho(tenant_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            "SELECT e.etiqueta, COUNT(*) AS n FROM cliente_etiquetas e JOIN clientes c ON c.id = e.cliente_id WHERE c.tenant_id = ? AND c.papelera_en IS NULL "
            "GROUP BY e.etiqueta ORDER BY n DESC, e.etiqueta", (tenant_id,))]
    finally:
        conn.close()


def anadir_contacto(tenant_id: int, cliente_id: int, nombre: str, *, cargo=None, email=None, telefono=None, rol=None, principal: bool = False) -> int:
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("Indica el nombre de la persona de contacto.")
    conn = db.get_connection()
    try:
        _de_tenant(conn, "clientes", cliente_id, tenant_id, "Cliente no encontrado.")
        if principal:
            conn.execute("UPDATE cliente_contactos SET principal = 0 WHERE cliente_id = ?", (cliente_id,))
        cur = conn.execute(
            "INSERT INTO cliente_contactos (cliente_id, nombre, cargo, email, telefono, rol, principal, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (cliente_id, nombre[:200], _limpio(cargo, 100), _limpio(email, 200), _limpio(telefono, 40), _limpio(rol, 60), 1 if principal else 0, db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_contactos(tenant_id: int, cliente_id: int) -> list:
    conn = db.get_connection()
    try:
        return conn.execute(
            "SELECT k.* FROM cliente_contactos k JOIN clientes c ON c.id = k.cliente_id WHERE k.cliente_id = ? AND c.tenant_id = ? ORDER BY k.principal DESC, lower(k.nombre)",
            (cliente_id, tenant_id)).fetchall()
    finally:
        conn.close()


def eliminar_contacto(tenant_id: int, contacto_id: int) -> bool:
    conn = db.get_connection()
    try:
        cur = conn.execute("DELETE FROM cliente_contactos WHERE id = ? AND cliente_id IN (SELECT id FROM clientes WHERE tenant_id = ?)", (contacto_id, tenant_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def posibles_duplicados(tenant_id: int, nombre: str | None = None, nif: str | None = None, email: str | None = None, excluir_id: int | None = None) -> list:
    """Clientes del despacho que se parecen (mismo NIF, mismo email o nombre igual sin distinguir mayúsculas ni espacios). Para avisar antes de crear otro."""
    condiciones, p = [], [tenant_id]
    if _limpio(nif, 30):
        condiciones.append("upper(replace(replace(c.nif,'-',''),' ','')) = ?")
        p.append(nif.strip().upper().replace("-", "").replace(" ", ""))
    if _limpio(email, 200):
        condiciones.append("lower(c.email) = ?")
        p.append(email.strip().lower())
    if _limpio(nombre, 200):
        condiciones.append("lower(trim(c.nombre)) = ?")
        p.append(nombre.strip().lower())
    if not condiciones:
        return []
    extra = " AND c.id != ?" if excluir_id else ""
    if excluir_id:
        p.append(excluir_id)
    conn = db.get_connection()
    try:
        return conn.execute(f"SELECT c.* FROM clientes c WHERE c.tenant_id = ? AND c.papelera_en IS NULL AND ({' OR '.join(condiciones)}){extra} ORDER BY lower(c.nombre) LIMIT 10", p).fetchall()
    finally:
        conn.close()


def fusionar_clientes(tenant_id: int, destino_id: int, origen_id: int) -> None:
    """Pasa todo lo del cliente `origen` al `destino` y manda `origen` a la papelera. No borra nada: los contactos y etiquetas se copian, los
    expedientes, plazos, horas y la ficha fiscal se reasignan."""
    if destino_id == origen_id:
        raise ValueError("Elige dos clientes distintos.")
    conn = db.get_connection()
    try:
        _de_tenant(conn, "clientes", destino_id, tenant_id, "Cliente de destino no encontrado.")
        _de_tenant(conn, "clientes", origen_id, tenant_id, "Cliente de origen no encontrado.")
        for tabla in ("expedientes", "plazos", "partes_tiempo"):
            conn.execute(f"UPDATE {tabla} SET cliente_id = ? WHERE cliente_id = ? AND tenant_id = ?", (destino_id, origen_id, tenant_id))
        conn.execute("UPDATE cliente_contactos SET cliente_id = ?, principal = 0 WHERE cliente_id = ?", (destino_id, origen_id))
        conn.execute("INSERT OR IGNORE INTO cliente_etiquetas (cliente_id, etiqueta) SELECT ?, etiqueta FROM cliente_etiquetas WHERE cliente_id = ?", (destino_id, origen_id))
        ficha_destino = conn.execute("SELECT 1 FROM clientes_fiscales WHERE cliente_id = ?", (destino_id,)).fetchone()
        if ficha_destino is None:
            conn.execute("UPDATE clientes_fiscales SET cliente_id = ? WHERE cliente_id = ? AND tenant_id = ?", (destino_id, origen_id, tenant_id))
        # Si los dos tenían ficha fiscal no se mezclan (vencimientos, pagos y portal cuelgan de ella): la del origen se queda enlazada a su ficha en la papelera
        conn.execute("UPDATE clientes SET papelera_en = ?, actualizado_en = ?, notas = COALESCE(notas || char(10), '') || ? WHERE id = ?",
                     (db._marca_papelera(), db.now_iso(), f"Fusionado en el cliente #{destino_id}.", origen_id))
        conn.commit()
    finally:
        conn.close()


# --- Expedientes ----------------------------------------------------------------------------------------------------------------------------------
def _visible_sql(usuario_id: int, supervisor: bool, alias: str = "x") -> tuple[str, list]:
    """Condición SQL de los expedientes que una persona puede ver: los no confidenciales y, de los confidenciales, los suyos."""
    if supervisor:
        return "1=1", []
    return (f"({alias}.confidencial = 0 OR {alias}.responsable_id = ? OR {alias}.creado_por = ? OR EXISTS "
            f"(SELECT 1 FROM expediente_miembros m WHERE m.expediente_id = {alias}.id AND m.usuario_id = ?))"), [usuario_id] * 3


def puede_ver_expediente(exp, usuario_id: int, supervisor: bool = False) -> bool:
    if exp is None:
        return False
    if not exp["confidencial"] or supervisor or usuario_id in (exp["responsable_id"], exp["creado_por"]):
        return True
    conn = db.get_connection()
    try:
        return conn.execute("SELECT 1 FROM expediente_miembros WHERE expediente_id = ? AND usuario_id = ?", (exp["id"], usuario_id)).fetchone() is not None
    finally:
        conn.close()


def _evento(conn, expediente_id: int, tipo: str, texto: str, usuario_id: int | None) -> None:
    conn.execute("INSERT INTO expediente_eventos (expediente_id, tipo, texto, usuario_id, creado_en) VALUES (?, ?, ?, ?, ?)", (expediente_id, tipo, texto[:1000], usuario_id, db.now_iso()))


def crear_expediente(tenant_id: int, usuario_id: int, cliente_id: int, titulo: str, *, tipo: str = "general", referencia: str | None = None,
                     descripcion: str | None = None, responsable_id: int | None = None, confidencial: bool = False, datos: dict | None = None) -> int:
    titulo = (titulo or "").strip()
    if not titulo:
        raise ValueError("Indica el título del expediente.")
    tipos = verticales.tipos_expediente(tenant_id)
    if tipo not in tipos:
        raise ValueError("Ese tipo de expediente no está disponible para tu despacho.")
    t = tipos[tipo]
    vertical = next((v.id for v in verticales.VERTICALES.values() if any(x.id == tipo for x in v.tipos_expediente)), "general")
    conn = db.get_connection()
    try:
        _de_tenant(conn, "clientes", cliente_id, tenant_id, "Cliente no encontrado.")
        _usuario_de_tenant(conn, responsable_id, tenant_id, "El responsable")
        ahora = db.now_iso()
        cur = conn.execute(
            "INSERT INTO expedientes (tenant_id, cliente_id, vertical_id, tipo, referencia, titulo, descripcion, estado, responsable_id, confidencial, datos, abierto_en, creado_por, creado_en) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, cliente_id, vertical, tipo, _limpio(referencia, 80), titulo[:200], _limpio(descripcion, 8000), t.inicial, responsable_id or usuario_id, 1 if confidencial else 0,
             json.dumps(datos, ensure_ascii=False) if datos else None, ahora, usuario_id, ahora),
        )
        _evento(conn, cur.lastrowid, "creado", "Expediente abierto.", usuario_id)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def obtener_expediente(tenant_id: int, expediente_id: int, usuario_id: int, supervisor: bool = False):
    """El expediente si existe, es del despacho y la persona puede verlo; si no, None (no se distingue «no existe» de «no puedes verlo»)."""
    conn = db.get_connection()
    try:
        exp = conn.execute(
            "SELECT x.*, c.nombre AS cliente_nombre, (SELECT nombre_mostrado FROM usuario_perfil WHERE usuario_id = x.responsable_id) AS responsable_nombre "
            "FROM expedientes x JOIN clientes c ON c.id = x.cliente_id WHERE x.id = ? AND x.tenant_id = ?", (expediente_id, tenant_id)).fetchone()
    finally:
        conn.close()
    return exp if exp is not None and puede_ver_expediente(exp, usuario_id, supervisor) else None


def listar_expedientes(tenant_id: int, usuario_id: int, supervisor: bool = False, *, cliente_id: int | None = None, estado: str | None = None, tipo: str | None = None,
                       solo_abiertos: bool = False, q: str | None = None, responsable_id: int | None = None, limite: int = 100, pagina: int = 1, papelera: bool = False) -> tuple[list, int]:
    cond_vis, p_vis = _visible_sql(usuario_id, supervisor)
    donde, p = ["x.tenant_id = ?", "x.papelera_en IS NOT NULL" if papelera else "x.papelera_en IS NULL", cond_vis], [tenant_id, *p_vis]
    if cliente_id:
        donde.append("x.cliente_id = ?"); p.append(cliente_id)
    if estado:
        donde.append("x.estado = ?"); p.append(estado)
    if tipo:
        donde.append("x.tipo = ?"); p.append(tipo)
    if solo_abiertos:
        donde.append("x.estado != 'cerrado'")
    if responsable_id:
        donde.append("x.responsable_id = ?"); p.append(responsable_id)
    if q and q.strip():
        like = f"%{plano(q.strip())}%"
        donde.append("(plano(x.titulo) LIKE ? OR plano(x.referencia) LIKE ? OR plano(c.nombre) LIKE ?)")
        p += [like] * 3
    cond = " AND ".join(donde)
    limite = max(1, min(int(limite), 500))
    conn = _conn_con_busqueda()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM expedientes x JOIN clientes c ON c.id = x.cliente_id WHERE {cond}", p).fetchone()[0]
        filas = conn.execute(
            f"SELECT x.*, c.nombre AS cliente_nombre, (SELECT MIN(fecha_limite) FROM plazos z WHERE z.expediente_id = x.id AND z.estado = 'pendiente' AND z.papelera_en IS NULL) AS proximo_plazo "
            f"FROM expedientes x JOIN clientes c ON c.id = x.cliente_id WHERE {cond} ORDER BY (x.estado = 'cerrado'), x.actualizado_en DESC, x.creado_en DESC LIMIT ? OFFSET ?",
            [*p, limite, (max(1, pagina) - 1) * limite]).fetchall()
        return filas, total
    finally:
        conn.close()


def cambiar_estado_expediente(tenant_id: int, usuario_id: int, expediente_id: int, estado: str, supervisor: bool = False) -> None:
    exp = obtener_expediente(tenant_id, expediente_id, usuario_id, supervisor)
    if exp is None:
        raise ValueError("Expediente no encontrado.")
    tipo = verticales.tipo_de(exp["tipo"])
    nuevo = tipo.estado(estado)
    if nuevo is None:
        raise ValueError("Ese estado no existe para este tipo de expediente.")
    if exp["estado"] == estado:
        return
    anterior = tipo.estado(exp["estado"])
    conn = db.get_connection()
    try:
        conn.execute("UPDATE expedientes SET estado = ?, cerrado_en = ?, actualizado_en = ? WHERE id = ?", (estado, db.now_iso() if nuevo.cerrado else None, db.now_iso(), expediente_id))
        _evento(conn, expediente_id, "estado", f"Estado: {anterior.nombre if anterior else exp['estado']} → {nuevo.nombre}", usuario_id)
        conn.commit()
    finally:
        conn.close()


def asignar_expediente(tenant_id: int, usuario_id: int, expediente_id: int, responsable_id: int, supervisor: bool = False) -> None:
    if obtener_expediente(tenant_id, expediente_id, usuario_id, supervisor) is None:
        raise ValueError("Expediente no encontrado.")
    conn = db.get_connection()
    try:
        _usuario_de_tenant(conn, responsable_id, tenant_id, "El responsable")
        conn.execute("UPDATE expedientes SET responsable_id = ?, actualizado_en = ? WHERE id = ?", (responsable_id, db.now_iso(), expediente_id))
        _evento(conn, expediente_id, "responsable", "Cambio de responsable.", usuario_id)
        conn.commit()
    finally:
        conn.close()


def editar_expediente(tenant_id: int, usuario_id: int, expediente_id: int, supervisor: bool = False, **campos) -> None:
    exp = obtener_expediente(tenant_id, expediente_id, usuario_id, supervisor)
    if exp is None:
        raise ValueError("Expediente no encontrado.")
    permitidos = {"titulo": 200, "referencia": 80, "descripcion": 8000}
    sets, vals = [], []
    for c, largo in permitidos.items():
        if c in campos:
            v = _limpio(campos[c], largo)
            if c == "titulo" and not v:
                raise ValueError("El título no puede quedar vacío.")
            sets.append(f"{c} = ?"); vals.append(v)
    if "confidencial" in campos:
        sets.append("confidencial = ?"); vals.append(1 if campos["confidencial"] else 0)
    if "datos" in campos:
        sets.append("datos = ?"); vals.append(json.dumps(campos["datos"], ensure_ascii=False) if campos["datos"] else None)
    if not sets:
        return
    conn = db.get_connection()
    try:
        conn.execute(f"UPDATE expedientes SET {', '.join(sets)}, actualizado_en = ? WHERE id = ?", [*vals, db.now_iso(), expediente_id])
        _evento(conn, expediente_id, "editado", "Datos del expediente editados.", usuario_id)
        conn.commit()
    finally:
        conn.close()


def papelera_expediente(tenant_id: int, usuario_id: int, expediente_id: int, supervisor: bool = False) -> None:
    if obtener_expediente(tenant_id, expediente_id, usuario_id, supervisor) is None:
        raise ValueError("Expediente no encontrado.")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE expedientes SET papelera_en = ?, actualizado_en = ? WHERE id = ?", (db._marca_papelera(), db.now_iso(), expediente_id))
        conn.commit()
    finally:
        conn.close()


def anadir_miembro(tenant_id: int, usuario_id: int, expediente_id: int, miembro_id: int, supervisor: bool = False) -> None:
    exp = obtener_expediente(tenant_id, expediente_id, usuario_id, supervisor)
    if exp is None:
        raise ValueError("Expediente no encontrado.")
    conn = db.get_connection()
    try:
        _usuario_de_tenant(conn, miembro_id, tenant_id, "La persona")
        conn.execute("INSERT OR IGNORE INTO expediente_miembros (expediente_id, usuario_id) VALUES (?, ?)", (expediente_id, miembro_id))
        _evento(conn, expediente_id, "miembro", "Se ha añadido una persona al expediente.", usuario_id)
        conn.commit()
    finally:
        conn.close()


def quitar_miembro(tenant_id: int, usuario_id: int, expediente_id: int, miembro_id: int, supervisor: bool = False) -> None:
    if obtener_expediente(tenant_id, expediente_id, usuario_id, supervisor) is None:
        raise ValueError("Expediente no encontrado.")
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM expediente_miembros WHERE expediente_id = ? AND usuario_id = ?", (expediente_id, miembro_id))
        conn.commit()
    finally:
        conn.close()


def miembros_de(expediente_id: int) -> list:
    conn = db.get_connection()
    try:
        return conn.execute("SELECT u.id, COALESCE(p.nombre_mostrado, u.email) AS nombre FROM expediente_miembros m JOIN usuarios u ON u.id = m.usuario_id "
                            "LEFT JOIN usuario_perfil p ON p.usuario_id = u.id WHERE m.expediente_id = ? ORDER BY nombre", (expediente_id,)).fetchall()
    finally:
        conn.close()


def anotar_expediente(tenant_id: int, usuario_id: int, expediente_id: int, texto: str, supervisor: bool = False) -> None:
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("Escribe la nota.")
    if obtener_expediente(tenant_id, expediente_id, usuario_id, supervisor) is None:
        raise ValueError("Expediente no encontrado.")
    conn = db.get_connection()
    try:
        _evento(conn, expediente_id, "nota", texto, usuario_id)
        conn.execute("UPDATE expedientes SET actualizado_en = ? WHERE id = ?", (db.now_iso(), expediente_id))
        conn.commit()
    finally:
        conn.close()


def linea_de_tiempo(tenant_id: int, usuario_id: int, expediente_id: int, supervisor: bool = False, limite: int = 200) -> list:
    if obtener_expediente(tenant_id, expediente_id, usuario_id, supervisor) is None:
        return []
    conn = db.get_connection()
    try:
        return conn.execute(
            "SELECT e.*, COALESCE(p.nombre_mostrado, u.email) AS autor FROM expediente_eventos e LEFT JOIN usuarios u ON u.id = e.usuario_id "
            "LEFT JOIN usuario_perfil p ON p.usuario_id = e.usuario_id WHERE e.expediente_id = ? ORDER BY e.creado_en DESC, e.id DESC LIMIT ?", (expediente_id, limite)).fetchall()
    finally:
        conn.close()


# --- Festivos y calendario de plazos ------------------------------------------------------------------------------------------------------------
def anadir_festivo(tenant_id: int, fecha: str, nombre: str) -> None:
    fecha = _fecha_iso(fecha, "La fecha del festivo")
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("Indica el nombre del festivo.")
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO festivos (tenant_id, fecha, nombre) VALUES (?, ?, ?) ON CONFLICT(tenant_id, fecha) DO UPDATE SET nombre = excluded.nombre", (tenant_id, fecha, nombre[:100]))
        conn.commit()
    finally:
        conn.close()


def listar_festivos(tenant_id: int, anio: int | None = None) -> list:
    conn = db.get_connection()
    try:
        if anio:
            return conn.execute("SELECT * FROM festivos WHERE tenant_id = ? AND fecha LIKE ? ORDER BY fecha", (tenant_id, f"{anio}-%")).fetchall()
        return conn.execute("SELECT * FROM festivos WHERE tenant_id = ? ORDER BY fecha", (tenant_id,)).fetchall()
    finally:
        conn.close()


def eliminar_festivo(tenant_id: int, festivo_id: int) -> bool:
    conn = db.get_connection()
    try:
        cur = conn.execute("DELETE FROM festivos WHERE id = ? AND tenant_id = ?", (festivo_id, tenant_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def calendario_del_despacho(tenant_id: int, tipo: str = "general", anios: tuple[int, ...] | None = None) -> cp.Calendario:
    """Calendario de plazos del despacho: festivos nacionales de ejemplo (sin validar) + los que haya añadido el despacho."""
    hoy = date.today().year
    anios = anios or (hoy - 1, hoy, hoy + 1)
    propios = [date.fromisoformat(f["fecha"]) for f in listar_festivos(tenant_id)]
    return cp.calendario_procesal(anios, propios) if tipo == "procesal" else cp.calendario_general(anios, propios)


def propuestas_vencimientos_ajustadas(tenant_id: int, modelos: list[str], anio: int, pais: str = "ES") -> list[dict]:
    """Propuestas del calendario fiscal con la fecha desplazada al siguiente día hábil (fines de semana, festivos nacionales y los del despacho).
    Las desplazadas llevan `fecha_original`. Es el único sitio que calcula propuestas para guardar: pantallas, API y generación automática."""
    from . import perfil_fiscal
    from .vencimientos_fiscales import generar_vencimientos_propuestos
    return perfil_fiscal.ajustar_a_calendario(generar_vencimientos_propuestos(modelos, anio, pais=pais), calendario_del_despacho(tenant_id, anios=(anio, anio + 1)))


# --- Plazos --------------------------------------------------------------------------------------------------------------------------------------------
def _parse_avisos(avisos) -> str:
    if isinstance(avisos, str):
        avisos = [a for a in avisos.split(",") if a.strip()]
    try:
        vals = sorted({int(a) for a in avisos if 0 <= int(a) <= 365}, reverse=True)
    except (TypeError, ValueError):
        raise ValueError("Los avisos son números de días separados por comas (por ejemplo 7,3,1).") from None
    return ",".join(str(v) for v in vals[:6])


def crear_plazo(tenant_id: int, usuario_id: int, titulo: str, fecha_limite: str, *, expediente_id: int | None = None, cliente_id: int | None = None,
                origen: str = "manual", critico: bool = False, avisos=(7, 3, 1), responsable_id: int | None = None, notas: str | None = None,
                supervisor: bool = False) -> int:
    titulo = (titulo or "").strip()
    if not titulo:
        raise ValueError("Indica qué plazo es.")
    fecha_limite = _fecha_iso(fecha_limite, "La fecha límite")
    conn = db.get_connection()
    try:
        if expediente_id:
            exp = _de_tenant(conn, "expedientes", expediente_id, tenant_id, "Expediente no encontrado.")
            if not puede_ver_expediente(exp, usuario_id, supervisor):
                raise ValueError("Expediente no encontrado.")
            cliente_id = cliente_id or exp["cliente_id"]
        if cliente_id:
            _de_tenant(conn, "clientes", cliente_id, tenant_id, "Cliente no encontrado.")
        _usuario_de_tenant(conn, responsable_id, tenant_id, "El responsable")
        cur = conn.execute(
            "INSERT INTO plazos (tenant_id, expediente_id, cliente_id, titulo, fecha_limite, origen, critico, avisos, responsable_id, notas, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, expediente_id, cliente_id, titulo[:200], fecha_limite, (origen or "manual")[:40], 1 if critico else 0, _parse_avisos(avisos), responsable_id or usuario_id,
             _limpio(notas, 2000), usuario_id, db.now_iso()),
        )
        if expediente_id:
            _evento(conn, expediente_id, "plazo", f"Plazo añadido: {titulo} ({fecha_limite}).", usuario_id)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _plazo_dict(f, hoy: date, cal: cp.Calendario) -> dict:
    d = dict(f)
    limite = date.fromisoformat(f["fecha_limite"])
    d["estado_calculado"] = cp.estado_del_plazo(limite, hoy, f["estado"] == "cumplido", cal=cal)
    d["dias_restantes"] = (limite - hoy).days
    d["dias_habiles_restantes"] = cp.dias_habiles_entre(hoy, limite, cal) if limite >= hoy else None
    d["avisos_fechas"] = [x.isoformat() for x in cp.fechas_de_aviso(limite, [int(a) for a in (f["avisos"] or "").split(",") if a.strip()], cal)]
    d["revisado"] = f["revisado_por"] is not None
    return d


def listar_plazos(tenant_id: int, usuario_id: int, supervisor: bool = False, *, estado: str | None = None, expediente_id: int | None = None, cliente_id: int | None = None,
                  responsable_id: int | None = None, hasta: str | None = None, hoy: date | None = None, limite: int = 300) -> list[dict]:
    """Plazos del despacho con su estado calculado (cumplido, vencido, hoy, próximo, en plazo), el más urgente primero.
    `estado` filtra por el estado calculado, o «abiertos» para todos los no cumplidos."""
    hoy = hoy or date.today()
    cond_vis, p_vis = _visible_sql(usuario_id, supervisor, "x")
    donde, p = ["z.tenant_id = ?", "z.papelera_en IS NULL", f"(z.expediente_id IS NULL OR EXISTS (SELECT 1 FROM expedientes x WHERE x.id = z.expediente_id AND {cond_vis}))"], [tenant_id, *p_vis]
    if expediente_id:
        donde.append("z.expediente_id = ?"); p.append(expediente_id)
    if cliente_id:
        donde.append("z.cliente_id = ?"); p.append(cliente_id)
    if responsable_id:
        donde.append("z.responsable_id = ?"); p.append(responsable_id)
    if hasta:
        donde.append("z.fecha_limite <= ?"); p.append(_fecha_iso(hasta, "La fecha"))
    conn = db.get_connection()
    try:
        filas = conn.execute(
            "SELECT z.*, c.nombre AS cliente_nombre, x.titulo AS expediente_titulo, x.tipo AS expediente_tipo, COALESCE(pr.nombre_mostrado, u.email) AS responsable_nombre "
            "FROM plazos z LEFT JOIN clientes c ON c.id = z.cliente_id LEFT JOIN expedientes x ON x.id = z.expediente_id "
            "LEFT JOIN usuarios u ON u.id = z.responsable_id LEFT JOIN usuario_perfil pr ON pr.usuario_id = z.responsable_id "
            f"WHERE {' AND '.join(donde)} ORDER BY (z.estado = 'cumplido'), z.fecha_limite, z.id LIMIT ?", [*p, max(1, min(limite, 1000))]).fetchall()
    finally:
        conn.close()
    calendarios: dict[str, cp.Calendario] = {}
    res = []
    for f in filas:
        tipo_cal = verticales.tipo_de(f["expediente_tipo"]).calendario if f["expediente_tipo"] else "general"
        if tipo_cal not in calendarios:        # (no `setdefault`: evaluaría el calendario entero, con su consulta de festivos, en cada fila)
            calendarios[tipo_cal] = calendario_del_despacho(tenant_id, tipo_cal)
        cal = calendarios[tipo_cal]
        d = _plazo_dict(f, hoy, cal)
        if estado == "abiertos" and d["estado_calculado"] == "cumplido":
            continue
        if estado and estado != "abiertos" and d["estado_calculado"] != estado:
            continue
        res.append(d)
    return res


def _plazo_de(conn, tenant_id: int, plazo_id: int):
    return _de_tenant(conn, "plazos", plazo_id, tenant_id, "Plazo no encontrado.")


def marcar_cumplido(tenant_id: int, usuario_id: int, plazo_id: int, cumplido: bool = True) -> None:
    conn = db.get_connection()
    try:
        z = _plazo_de(conn, tenant_id, plazo_id)
        conn.execute("UPDATE plazos SET estado = ?, cumplido_en = ? WHERE id = ?", ("cumplido" if cumplido else "pendiente", db.now_iso() if cumplido else None, plazo_id))
        if z["expediente_id"]:
            _evento(conn, z["expediente_id"], "plazo", f"Plazo {'cumplido' if cumplido else 'reabierto'}: {z['titulo']}.", usuario_id)
        conn.commit()
    finally:
        conn.close()


def revisar_plazo(tenant_id: int, usuario_id: int, plazo_id: int) -> None:
    """Segunda revisión de un plazo por una persona distinta de quien lo creó (los plazos con consecuencias legales se contrastan siempre dos veces)."""
    conn = db.get_connection()
    try:
        z = _plazo_de(conn, tenant_id, plazo_id)
        if z["creado_por"] == usuario_id:
            raise ValueError("La revisión tiene que hacerla otra persona distinta de quien creó el plazo.")
        conn.execute("UPDATE plazos SET revisado_por = ?, revisado_en = ? WHERE id = ?", (usuario_id, db.now_iso(), plazo_id))
        if z["expediente_id"]:
            _evento(conn, z["expediente_id"], "plazo", f"Plazo revisado: {z['titulo']}.", usuario_id)
        conn.commit()
    finally:
        conn.close()


def mover_plazo(tenant_id: int, usuario_id: int, plazo_id: int, fecha_limite: str) -> None:
    fecha_limite = _fecha_iso(fecha_limite, "La fecha límite")
    conn = db.get_connection()
    try:
        z = _plazo_de(conn, tenant_id, plazo_id)
        conn.execute("UPDATE plazos SET fecha_limite = ?, revisado_por = NULL, revisado_en = NULL WHERE id = ?", (fecha_limite, plazo_id))   # una fecha nueva vuelve a pedir revisión
        if z["expediente_id"]:
            _evento(conn, z["expediente_id"], "plazo", f"Plazo movido: {z['titulo']} ({z['fecha_limite']} → {fecha_limite}).", usuario_id)
        conn.commit()
    finally:
        conn.close()


def eliminar_plazo(tenant_id: int, usuario_id: int, plazo_id: int) -> None:
    conn = db.get_connection()
    try:
        z = _plazo_de(conn, tenant_id, plazo_id)
        conn.execute("UPDATE plazos SET papelera_en = ? WHERE id = ?", (db._marca_papelera(), plazo_id))
        if z["expediente_id"]:
            _evento(conn, z["expediente_id"], "plazo", f"Plazo eliminado: {z['titulo']}.", usuario_id)
        conn.commit()
    finally:
        conn.close()


# --- Horas facturables --------------------------------------------------------------------------------------------------------------------------
def importe_centimos(segundos: int, tarifa_hora_centimos: int | None, bloque_minutos: int = 0) -> int:
    """Importe de un tiempo a una tarifa por hora, en céntimos. Con `bloque_minutos` > 0 el tiempo se redondea hacia arriba a bloques (p. ej. 6 min,
    habitual en despachos de abogados); sin él se cobra el tiempo exacto, redondeando el céntimo."""
    if not tarifa_hora_centimos or segundos <= 0:
        return 0
    if bloque_minutos > 0:
        bloque = bloque_minutos * 60
        segundos = -(-segundos // bloque) * bloque
    return int((segundos * tarifa_hora_centimos + 1800) // 3600)


def fijar_tarifa_usuario(tenant_id: int, usuario_id: int, tarifa_hora_centimos: int | None) -> None:
    if tarifa_hora_centimos is not None and not (0 <= int(tarifa_hora_centimos) <= 10_000_000):
        raise ValueError("La tarifa no es válida.")
    conn = db.get_connection()
    try:
        _usuario_de_tenant(conn, usuario_id, tenant_id)
        conn.execute("UPDATE usuarios SET tarifa_hora_centimos = ? WHERE id = ?", (tarifa_hora_centimos, usuario_id))
        conn.commit()
    finally:
        conn.close()


def tarifa_de(usuario_id: int) -> int | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT tarifa_hora_centimos FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        return f["tarifa_hora_centimos"] if f else None
    finally:
        conn.close()


def registrar_parte(tenant_id: int, usuario_id: int, descripcion: str, *, minutos: float | None = None, segundos: int | None = None, fecha: str | None = None,
                    cliente_id: int | None = None, expediente_id: int | None = None, tarea_id: int | None = None, facturable: bool = True,
                    tarifa_hora_centimos: int | None = None, supervisor: bool = False) -> int:
    descripcion = (descripcion or "").strip()
    if not descripcion:
        raise ValueError("Describe en qué se ha empleado el tiempo.")
    seg = int(segundos if segundos is not None else round((minutos or 0) * 60))
    if seg <= 0 or seg > 24 * 3600:
        raise ValueError("El tiempo debe ser mayor que cero y de menos de 24 horas.")
    fecha = _fecha_iso(fecha, "La fecha") if fecha else date.today().isoformat()
    if fecha > (date.today() + timedelta(days=1)).isoformat():
        raise ValueError("No se puede registrar tiempo de una fecha futura.")
    conn = db.get_connection()
    try:
        if expediente_id:
            exp = _de_tenant(conn, "expedientes", expediente_id, tenant_id, "Expediente no encontrado.")
            if not puede_ver_expediente(exp, usuario_id, supervisor):
                raise ValueError("Expediente no encontrado.")
            cliente_id = cliente_id or exp["cliente_id"]
        if cliente_id:
            _de_tenant(conn, "clientes", cliente_id, tenant_id, "Cliente no encontrado.")
        if tarifa_hora_centimos is None:
            f = conn.execute("SELECT tarifa_hora_centimos FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
            tarifa_hora_centimos = f["tarifa_hora_centimos"] if f else None
        cur = conn.execute(
            "INSERT INTO partes_tiempo (tenant_id, usuario_id, cliente_id, expediente_id, tarea_id, descripcion, fecha, segundos, facturable, tarifa_hora_centimos, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, usuario_id, cliente_id, expediente_id, tarea_id, descripcion[:500], fecha, seg, 1 if facturable else 0, tarifa_hora_centimos, db.now_iso()),
        )
        if expediente_id:
            _evento(conn, expediente_id, "tiempo", f"Tiempo registrado: {seg // 3600} h {seg % 3600 // 60:02d} min — {descripcion[:80]}", usuario_id)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _filtro_partes(tenant_id: int, usuario_id: int, ver_todo: bool, supervisor: bool, **f) -> tuple[str, list]:
    cond_vis, p_vis = _visible_sql(usuario_id, supervisor, "x")
    donde = ["t.tenant_id = ?", "t.papelera_en IS NULL", f"(t.expediente_id IS NULL OR EXISTS (SELECT 1 FROM expedientes x WHERE x.id = t.expediente_id AND {cond_vis}))"]
    p: list = [tenant_id, *p_vis]
    if not ver_todo:
        donde.append("t.usuario_id = ?"); p.append(usuario_id)
    elif f.get("persona_id"):
        donde.append("t.usuario_id = ?"); p.append(f["persona_id"])
    for col in ("cliente_id", "expediente_id"):
        if f.get(col):
            donde.append(f"t.{col} = ?"); p.append(f[col])
    if f.get("desde"):
        donde.append("t.fecha >= ?"); p.append(_fecha_iso(f["desde"]))
    if f.get("hasta"):
        donde.append("t.fecha <= ?"); p.append(_fecha_iso(f["hasta"]))
    if f.get("facturable") is not None:
        donde.append("t.facturable = ?"); p.append(1 if f["facturable"] else 0)
    if f.get("pendiente_de_facturar"):
        donde.append("t.facturable = 1 AND t.facturado_en IS NULL")
    return " AND ".join(donde), p


def listar_partes(tenant_id: int, usuario_id: int, supervisor: bool = False, *, ver_todo: bool = False, limite: int = 500, **filtros) -> list[dict]:
    """Partes de horas. Sin `ver_todo` solo los propios; con él (responsables del despacho) los de todo el equipo."""
    cond, p = _filtro_partes(tenant_id, usuario_id, ver_todo, supervisor, **filtros)
    conn = db.get_connection()
    try:
        filas = conn.execute(
            "SELECT t.*, c.nombre AS cliente_nombre, x.titulo AS expediente_titulo, COALESCE(pr.nombre_mostrado, u.email) AS usuario_nombre "
            "FROM partes_tiempo t LEFT JOIN clientes c ON c.id = t.cliente_id LEFT JOIN expedientes x ON x.id = t.expediente_id "
            "JOIN usuarios u ON u.id = t.usuario_id LEFT JOIN usuario_perfil pr ON pr.usuario_id = t.usuario_id "
            f"WHERE {cond} ORDER BY t.fecha DESC, t.id DESC LIMIT ?", [*p, max(1, min(limite, 2000))]).fetchall()
    finally:
        conn.close()
    res = []
    for f in filas:
        d = dict(f)
        d["importe_centimos"] = importe_centimos(f["segundos"], f["tarifa_hora_centimos"]) if f["facturable"] else 0
        res.append(d)
    return res


def resumen_horas(tenant_id: int, usuario_id: int, supervisor: bool = False, *, ver_todo: bool = False, agrupar: str = "cliente", bloque_minutos: int = 0, **filtros) -> list[dict]:
    """Totales de horas e importe por persona, cliente o expediente (hoja de horas). Los importes son los de cada parte con su tarifa."""
    if agrupar not in ("usuario", "cliente", "expediente"):
        raise ValueError("Agrupa por usuario, cliente o expediente.")
    grupos: dict = {}
    for d in listar_partes(tenant_id, usuario_id, supervisor, ver_todo=ver_todo, limite=2000, **filtros):
        if agrupar == "usuario":
            clave, nombre = d["usuario_id"], d["usuario_nombre"]
        elif agrupar == "cliente":
            clave, nombre = d["cliente_id"], d["cliente_nombre"] or "Sin cliente"
        else:
            clave, nombre = d["expediente_id"], d["expediente_titulo"] or "Sin expediente"
        g = grupos.setdefault(clave, {"id": clave, "nombre": nombre, "segundos": 0, "segundos_facturables": 0, "importe_centimos": 0, "partes": 0})
        g["segundos"] += d["segundos"]
        g["partes"] += 1
        if d["facturable"]:
            g["segundos_facturables"] += d["segundos"]
            g["importe_centimos"] += importe_centimos(d["segundos"], d["tarifa_hora_centimos"], bloque_minutos)
    return sorted(grupos.values(), key=lambda g: (-g["segundos"], str(g["nombre"]).lower()))


def marcar_facturado(tenant_id: int, parte_ids: list[int], fecha: str | None = None) -> int:
    ids = [int(i) for i in parte_ids][:2000]
    if not ids:
        return 0
    fecha = _fecha_iso(fecha) if fecha else date.today().isoformat()
    conn = db.get_connection()
    try:
        cur = conn.execute(f"UPDATE partes_tiempo SET facturado_en = ? WHERE tenant_id = ? AND facturable = 1 AND id IN ({','.join('?' * len(ids))})", [fecha, tenant_id, *ids])
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def eliminar_parte(tenant_id: int, usuario_id: int, parte_id: int, supervisor: bool = False) -> bool:
    """Un parte solo lo borra quien lo creó (o un responsable del despacho) y mientras no esté facturado."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM partes_tiempo WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (parte_id, tenant_id)).fetchone()
        if f is None or f["facturado_en"] or (f["usuario_id"] != usuario_id and not supervisor):
            return False
        conn.execute("UPDATE partes_tiempo SET papelera_en = ? WHERE id = ?", (db._marca_papelera(), parte_id))
        conn.commit()
        return True
    finally:
        conn.close()


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    """Borra todo lo del núcleo de un despacho (lo llama `db.borrar_tenant`, dentro de su transacción)."""
    for v in verticales.VERTICALES.values():
        if v.borrar_datos:
            v.borrar_datos(conn, tenant_id)
    from . import almacen_documentos
    almacen_documentos.borrar_datos_de_tenant(conn, tenant_id)
    for tabla in ("partes_tiempo", "plazos", "festivos"):
        conn.execute(f"DELETE FROM {tabla} WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM expediente_eventos WHERE expediente_id IN (SELECT id FROM expedientes WHERE tenant_id = ?)", (tenant_id,))
    conn.execute("DELETE FROM expediente_miembros WHERE expediente_id IN (SELECT id FROM expedientes WHERE tenant_id = ?)", (tenant_id,))
    conn.execute("DELETE FROM expedientes WHERE tenant_id = ?", (tenant_id,))
    conn.execute("UPDATE clientes_fiscales SET cliente_id = NULL WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM cliente_contactos WHERE cliente_id IN (SELECT id FROM clientes WHERE tenant_id = ?)", (tenant_id,))
    conn.execute("DELETE FROM cliente_etiquetas WHERE cliente_id IN (SELECT id FROM clientes WHERE tenant_id = ?)", (tenant_id,))
    conn.execute("DELETE FROM clientes WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM tenants_verticales WHERE tenant_id = ?", (tenant_id,))
