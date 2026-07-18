"""Acceso a la base de datos SQLite de Guilda Work.

Todos los timestamps se guardan en hora local (Europe/Madrid), formato
ISO 8601 sin zona horaria explícita, ej: 2026-07-10T14:32:05.

Multiusuario (Fase 1 de la app móvil): categorias, notas, tareas,
tareas_outlook, correo_cuentas, correo_categorias e ia_mensajes llevan
`usuario_id` directamente (denormalizado incluso en las que cuelgan de una
categoría, porque notas/tareas pueden no tener categoría). Las tablas que
cuelgan de una de esas con FK NOT NULL (pausas, plantillas,
correo_carpetas, correo_mensajes, correo_adjuntos) se aíslan a través de su
padre, sin columna propia. `correo_preferencias`/`ia_preferencias` pasan de
fila única global (`id=1`) a una fila por usuario (`usuario_id` como clave
primaria).

Limitación conocida de esta fase: `categorias.nombre` y
`correo_categorias.nombre` siguen siendo UNIQUE de forma global (no por
usuario) — cambiarlo exige reconstruir esas tablas igual que se hizo con
las de preferencias; se deja para una fase posterior si llega a ser un
problema real con más de un usuario.
"""
import hashlib
import secrets
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

if hasattr(sys, "_MEIPASS"):
    # Empaquetado con PyInstaller: sys._MEIPASS es una carpeta temporal que se
    # borra al cerrar, así que la base de datos vive junto al .exe, no ahí.
    RAIZ_PROYECTO = Path(sys.executable).resolve().parent
else:
    RAIZ_PROYECTO = Path(__file__).resolve().parent.parent

DB_PATH = RAIZ_PROYECTO / "data" / "registro.db"
BACKUPS_DIR = RAIZ_PROYECTO / "data" / "backups"

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    contrasena_hash TEXT NOT NULL,
    rol TEXT NOT NULL DEFAULT 'usuario' CHECK (rol IN ('usuario','admin')),
    es_local INTEGER NOT NULL DEFAULT 0,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tokens_api (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    token_hash TEXT NOT NULL UNIQUE,
    nombre_dispositivo TEXT,
    creado_en TEXT NOT NULL,
    ultimo_uso_en TEXT
);

CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER,
    nombre TEXT NOT NULL UNIQUE,
    color TEXT,
    creada_en TEXT NOT NULL,
    papelera_en TEXT,
    orden INTEGER
);

CREATE TABLE IF NOT EXISTS tareas (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER,
    nombre TEXT NOT NULL,
    categoria_id INTEGER NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('duracion','instantanea')) DEFAULT 'duracion',
    estado TEXT NOT NULL CHECK (estado IN ('pendiente','en_curso','pausada','finalizada')),
    inicio_en TEXT,
    fin_en TEXT,
    duracion_segundos INTEGER,
    papelera_en TEXT,
    FOREIGN KEY (categoria_id) REFERENCES categorias(id)
);

CREATE TABLE IF NOT EXISTS notas (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER,
    texto TEXT NOT NULL,
    categoria_id INTEGER,
    tarea_id INTEGER,
    creada_en TEXT NOT NULL,
    papelera_en TEXT,
    FOREIGN KEY (categoria_id) REFERENCES categorias(id),
    FOREIGN KEY (tarea_id) REFERENCES tareas(id)
);

CREATE TABLE IF NOT EXISTS pausas (
    id INTEGER PRIMARY KEY,
    tarea_id INTEGER NOT NULL,
    pausada_en TEXT NOT NULL,
    reanudada_en TEXT,
    FOREIGN KEY (tarea_id) REFERENCES tareas(id)
);

-- Frases favoritas (plantillas) para registrar notas en un clic
CREATE TABLE IF NOT EXISTS plantillas (
    id INTEGER PRIMARY KEY,
    categoria_id INTEGER NOT NULL,
    texto TEXT NOT NULL,
    creada_en TEXT NOT NULL,
    FOREIGN KEY (categoria_id) REFERENCES categorias(id)
);

-- Tareas al estilo Microsoft Outlook (lista + calendario): independientes
-- de los menús y de las tareas con duración de arriba. Los nombres de campo
-- calcan el modelo de objetos de Outlook (Subject, Status, PercentComplete,
-- Importance, StartDate, DueDate, DateCompleted, Categories, EntryID) y el
-- VTODO de iCalendar, para que el mapeo de importación/exportación sea 1:1.
CREATE TABLE IF NOT EXISTS tareas_outlook (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER,
    asunto TEXT NOT NULL,
    cuerpo TEXT,
    estado TEXT NOT NULL CHECK (estado IN
        ('no_iniciada','en_progreso','completada','esperando','aplazada'))
        DEFAULT 'no_iniciada',
    porcentaje_completado INTEGER NOT NULL DEFAULT 0,
    prioridad TEXT NOT NULL CHECK (prioridad IN ('baja','normal','alta'))
        DEFAULT 'normal',
    fecha_inicio TEXT,
    fecha_vencimiento TEXT,
    fecha_completada TEXT,
    categoria_outlook TEXT,
    outlook_entry_id TEXT UNIQUE,
    creada_en TEXT NOT NULL,
    actualizada_en TEXT,
    papelera_en TEXT
);

-- Cliente de correo IMAP/POP3. La contraseña de cada cuenta NO se guarda
-- aquí: vive en el almacén de credenciales del sistema (keyring), bajo la
-- clave "cuenta-<id>" — esta tabla solo tiene metadatos de conexión.
-- firma_html: firma enriquecida (HTML), propia de esta cuenta; los dos
-- interruptores controlan cuándo se antepone al redactar (ver
-- app/correo.py::preparar_cuerpo_inicial). Cualquier combinación es válida,
-- incluida ninguna de las dos.
CREATE TABLE IF NOT EXISTS correo_cuentas (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER,
    nombre TEXT NOT NULL,
    protocolo TEXT NOT NULL CHECK (protocolo IN ('imap','pop3')),
    host TEXT NOT NULL,
    puerto INTEGER NOT NULL,
    usa_tls INTEGER NOT NULL DEFAULT 1,
    usuario TEXT NOT NULL,
    smtp_host TEXT,
    smtp_puerto INTEGER,
    smtp_tls INTEGER NOT NULL DEFAULT 1,
    creada_en TEXT NOT NULL,
    ultima_sincronizacion TEXT,
    firma_html TEXT,
    firma_en_nuevos INTEGER NOT NULL DEFAULT 1,
    firma_en_respuestas INTEGER NOT NULL DEFAULT 1
);

-- Carpetas IMAP descubiertas al sincronizar (POP3 no tiene fila aquí: su
-- única carpeta "INBOX" se sintetiza en Python, nunca se guarda, porque
-- POP3 no tiene ningún concepto de carpetas a nivel de protocolo).
CREATE TABLE IF NOT EXISTS correo_carpetas (
    id INTEGER PRIMARY KEY,
    cuenta_id INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    nombre_visible TEXT NOT NULL,
    FOREIGN KEY (cuenta_id) REFERENCES correo_cuentas(id),
    UNIQUE (cuenta_id, nombre)
);

-- Categorías de color propias de Guilda Work (no existe un estándar real de
-- "categorías con color" en IMAP/POP3 genérico — es propietario de
-- Exchange/Outlook — así que estas nunca se sincronizan con el servidor).
CREATE TABLE IF NOT EXISTS correo_categorias (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER,
    nombre TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL,
    creada_en TEXT NOT NULL
);

-- Caché local de mensajes ya descargados (para no ir a red en cada
-- consulta). cc: cabecera Cc del mensaje recibido. Cco (Bcc) nunca se guarda
-- aquí porque, por diseño del propio correo electrónico, nadie salvo el
-- remitente original sabe quién iba en copia oculta — no es una limitación
-- nuestra, un mensaje recibido jamás trae esa información.
CREATE TABLE IF NOT EXISTS correo_mensajes (
    id INTEGER PRIMARY KEY,
    cuenta_id INTEGER NOT NULL,
    carpeta TEXT NOT NULL DEFAULT 'INBOX',
    uid TEXT NOT NULL,
    asunto TEXT,
    remitente TEXT,
    destinatarios TEXT,
    cc TEXT,
    fecha TEXT,
    cuerpo_texto TEXT,
    cuerpo_html TEXT,
    message_id TEXT,       -- cabecera Message-ID, para poder responder con hilo (In-Reply-To/References)
    leido INTEGER NOT NULL DEFAULT 0,
    categoria_id INTEGER,
    destacado INTEGER NOT NULL DEFAULT 0,
    fecha_aviso TEXT,      -- recordatorio opcional del destacado
    pospuesto_hasta TEXT,  -- mientras sea futuro, se oculta de la lista por defecto
    descargado_en TEXT NOT NULL,
    FOREIGN KEY (cuenta_id) REFERENCES correo_cuentas(id),
    FOREIGN KEY (categoria_id) REFERENCES correo_categorias(id) ON DELETE SET NULL,
    UNIQUE (cuenta_id, carpeta, uid)
);

-- Adjuntos reales de mensajes recibidos (Content-Disposition: attachment).
-- Los bytes viven en la propia SQLite, igual que el resto de la app: un
-- único archivo .db, sin carpeta aparte que sincronizar/hacer backup.
CREATE TABLE IF NOT EXISTS correo_adjuntos (
    id INTEGER PRIMARY KEY,
    mensaje_id INTEGER NOT NULL,
    nombre_archivo TEXT NOT NULL,
    tipo_mime TEXT NOT NULL,
    tamano_bytes INTEGER NOT NULL,
    contenido BLOB NOT NULL,
    creado_en TEXT NOT NULL,
    FOREIGN KEY (mensaje_id) REFERENCES correo_mensajes(id) ON DELETE CASCADE
);

-- Remitentes marcados como de confianza: sus imágenes remotas y adjuntos
-- no se bloquean/avisan antes de mostrarlos.
CREATE TABLE IF NOT EXISTS correo_remitentes_confiables (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    direccion TEXT NOT NULL,
    creada_en TEXT NOT NULL,
    UNIQUE (usuario_id, direccion)
);

-- Reglas de categorización automática: al llegar un mensaje nuevo cuyo
-- remitente coincide con remitente_patron (email exacto o "@dominio.com"),
-- se le asigna categoria_id sin intervención manual.
CREATE TABLE IF NOT EXISTS correo_reglas_categoria (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    remitente_patron TEXT NOT NULL,
    categoria_id INTEGER NOT NULL,
    creada_en TEXT NOT NULL,
    FOREIGN KEY (categoria_id) REFERENCES correo_categorias(id) ON DELETE CASCADE
);

-- Direcciones a las que ya se ha enviado correo, para sugerirlas al
-- redactar uno nuevo (autocompletar). veces_usado/ultima_vez_en permiten
-- ordenar las sugerencias por relevancia.
CREATE TABLE IF NOT EXISTS correo_destinatarios_recientes (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    direccion TEXT NOT NULL,
    nombre_mostrado TEXT,
    ultima_vez_en TEXT NOT NULL,
    veces_usado INTEGER NOT NULL DEFAULT 1,
    UNIQUE (usuario_id, direccion)
);

-- Historial de la conversación con el Asistente IA (un hilo por usuario).
CREATE TABLE IF NOT EXISTS ia_mensajes (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER,
    rol TEXT NOT NULL CHECK (rol IN ('user','assistant','tool')),
    contenido TEXT,
    tool_calls_json TEXT,
    tool_call_id TEXT,
    nombre_herramienta TEXT,
    creado_en TEXT NOT NULL
);

"""

# Índices: sin ellos, cualquier filtro por fecha/categoría/leído acaba en un
# escaneo completo de la tabla. A partir de unos pocos miles de filas (uso
# de empresa: 100+ tareas y 200+ correos al día) eso se nota en cada carga
# del Dashboard/Correo/Tareas. `CREATE INDEX IF NOT EXISTS` es idempotente,
# así que se ejecuta en cada init_db() sin coste real si ya existen. Va en
# un script APARTE de SCHEMA (no dentro) porque los índices sobre
# `usuario_id` referencian una columna que en bases de datos migradas se
# añade con `_asegurar_columna` DESPUÉS de crear las tablas — si viviera en
# el mismo `executescript(SCHEMA)`, fallaría en cualquier base de datos ya
# existente donde la tabla ya existe pero todavía no tiene esa columna.
INDICES = """
CREATE INDEX IF NOT EXISTS idx_notas_categoria_creada ON notas(categoria_id, creada_en);
CREATE INDEX IF NOT EXISTS idx_notas_papelera ON notas(papelera_en);
CREATE INDEX IF NOT EXISTS idx_notas_usuario ON notas(usuario_id);
CREATE INDEX IF NOT EXISTS idx_tareas_categoria_inicio ON tareas(categoria_id, inicio_en);
CREATE INDEX IF NOT EXISTS idx_tareas_papelera ON tareas(papelera_en);
CREATE INDEX IF NOT EXISTS idx_tareas_usuario ON tareas(usuario_id);
CREATE INDEX IF NOT EXISTS idx_categorias_papelera ON categorias(papelera_en);
CREATE INDEX IF NOT EXISTS idx_categorias_usuario ON categorias(usuario_id);
CREATE INDEX IF NOT EXISTS idx_tareas_outlook_papelera_vencimiento ON tareas_outlook(papelera_en, fecha_vencimiento);
CREATE INDEX IF NOT EXISTS idx_tareas_outlook_estado ON tareas_outlook(estado);
CREATE INDEX IF NOT EXISTS idx_tareas_outlook_usuario ON tareas_outlook(usuario_id);
CREATE INDEX IF NOT EXISTS idx_correo_cuentas_usuario ON correo_cuentas(usuario_id);
CREATE INDEX IF NOT EXISTS idx_correo_categorias_usuario ON correo_categorias(usuario_id);
CREATE INDEX IF NOT EXISTS idx_correo_mensajes_cuenta_carpeta_fecha ON correo_mensajes(cuenta_id, carpeta, fecha);
CREATE INDEX IF NOT EXISTS idx_correo_mensajes_leido ON correo_mensajes(leido);
CREATE INDEX IF NOT EXISTS idx_correo_adjuntos_mensaje ON correo_adjuntos(mensaje_id);
CREATE INDEX IF NOT EXISTS idx_ia_mensajes_usuario ON ia_mensajes(usuario_id);
CREATE INDEX IF NOT EXISTS idx_tokens_api_usuario ON tokens_api(usuario_id);
CREATE INDEX IF NOT EXISTS idx_correo_remitentes_confiables_usuario ON correo_remitentes_confiables(usuario_id);
CREATE INDEX IF NOT EXISTS idx_correo_reglas_categoria_usuario ON correo_reglas_categoria(usuario_id);
CREATE INDEX IF NOT EXISTS idx_correo_destinatarios_recientes_usuario ON correo_destinatarios_recientes(usuario_id);
"""


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _fecha_exclusiva(fecha: str) -> str:
    """`fecha` (YYYY-MM-DD, límite inclusive) -> el día siguiente (YYYY-MM-DD).

    Permite filtrar con `columna < _fecha_exclusiva(hasta)` en vez de
    `substr(columna,1,10) <= hasta`: envolver la columna en `substr()`
    impide a SQLite usar cualquier índice sobre ella (fuerza un escaneo
    completo de la tabla en cada consulta). Comparar el timestamp completo
    contra el día siguiente, sin tocar la columna, sí puede usar un índice
    — y da el mismo resultado porque los timestamps ISO 8601 ordenan bien
    como texto."""
    return (datetime.strptime(fecha, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")


def _marca_papelera() -> str:
    """Timestamp con precisión de microsegundos para `papelera_en`.

    A diferencia de now_iso() (precisión de segundos, pensada para que se
    lea bien), esto se usa para poder identificar qué se borró exactamente
    en la misma operación (p.ej. un menú y sus tareas/notas al mandarlo a la
    papelera) y restaurarlo junto — con precisión de segundos, dos borrados
    distintos en el mismo segundo compartirían marca por error.
    """
    return datetime.now().isoformat(timespec="microseconds")


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL permite que la app de escritorio (GuildaWork.exe) y un serve.py
    # expuesto a internet (Fase 3, app móvil) lean/escriban el mismo
    # registro.db a la vez sin bloquearse mutuamente; busy_timeout evita que
    # el choque puntual entre dos escrituras casi simultáneas falle al
    # instante con "database is locked" en vez de esperar un poco.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _asegurar_columna(conn: sqlite3.Connection, tabla: str, columna: str, tipo: str) -> None:
    """Añade `columna` a `tabla` si no existe ya (migración ligera para bases
    de datos creadas con una versión anterior del esquema)."""
    columnas = {fila["name"] for fila in conn.execute(f"PRAGMA table_info({tabla})")}
    if columna not in columnas:
        conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")


def _asegurar_orden_categorias(conn: sqlite3.Connection) -> None:
    """Rellena `orden` para categorías que no lo tengan (bases de datos
    migradas desde antes de que existiera esta columna), por nombre."""
    sin_orden = conn.execute("SELECT id FROM categorias WHERE orden IS NULL ORDER BY nombre").fetchall()
    if not sin_orden:
        return
    base = conn.execute("SELECT COALESCE(MAX(orden), -1) FROM categorias").fetchone()[0]
    for i, fila in enumerate(sin_orden, start=base + 1):
        conn.execute("UPDATE categorias SET orden = ? WHERE id = ?", (i, fila["id"]))


def _resolver_usuario_local(conn: sqlite3.Connection) -> int:
    """Usuario de confianza para procesos locales (cli.py, mcp_server.py,
    y para migrar datos de antes de que existiera el login) que no pasan
    por una sesión web. Si no existe todavía, se crea automáticamente con
    una contraseña aleatoria (nadie inicia sesión "como" este usuario desde
    fuera; es un ancla interna, no una cuenta pensada para usarse en la web)."""
    fila = conn.execute("SELECT id FROM usuarios WHERE es_local = 1 ORDER BY id LIMIT 1").fetchone()
    if fila:
        return fila["id"]
    cur = conn.execute(
        "INSERT INTO usuarios (email, contrasena_hash, es_local, creado_en) VALUES (?, ?, 1, ?)",
        ("local@guilda-work.local", generate_password_hash(secrets.token_urlsafe(16)), now_iso()),
    )
    return cur.lastrowid


def _migrar_datos_sin_usuario(conn: sqlite3.Connection, usuario_id: int) -> None:
    """Asigna al usuario local cualquier fila de las tablas "raíz" que
    todavía no tenga dueño — es decir, todo lo que se anotó antes de que
    existiera el login. No toca nada que ya pertenezca a un usuario."""
    for tabla in (
        "categorias", "notas", "tareas", "tareas_outlook",
        "correo_cuentas", "correo_categorias", "ia_mensajes",
    ):
        conn.execute(f"UPDATE {tabla} SET usuario_id = ? WHERE usuario_id IS NULL", (usuario_id,))


_ESPECIFICACION_PREFERENCIAS = {
    "correo_preferencias": (
        ["densidad", "marcar_leido_automatico", "limite_mensajes"],
        """CREATE TABLE correo_preferencias (
               usuario_id INTEGER PRIMARY KEY,
               densidad TEXT NOT NULL DEFAULT 'normal' CHECK (densidad IN ('normal','compacta')),
               marcar_leido_automatico INTEGER NOT NULL DEFAULT 1,
               limite_mensajes INTEGER NOT NULL DEFAULT 50
           )""",
    ),
    "ia_preferencias": (
        ["modelo", "modo_autonomo"],
        """CREATE TABLE ia_preferencias (
               usuario_id INTEGER PRIMARY KEY,
               modelo TEXT NOT NULL DEFAULT '',
               modo_autonomo INTEGER NOT NULL DEFAULT 0
           )""",
    ),
}


def _migrar_preferencias_singleton(conn: sqlite3.Connection, usuario_id_local: int) -> None:
    """`correo_preferencias`/`ia_preferencias` eran una única fila global
    (`id=1`). Multiusuario necesita una fila por usuario, con `usuario_id`
    como clave primaria — un cambio de clave primaria que SQLite no permite
    con `ALTER TABLE`, así que se reconstruye la tabla la primera vez que
    se detecta el esquema antiguo (o se crea directamente con el esquema
    nuevo si es una instalación nunca antes usada)."""
    for tabla, (columnas, ddl_nueva) in _ESPECIFICACION_PREFERENCIAS.items():
        cols_actuales = {r["name"] for r in conn.execute(f"PRAGMA table_info({tabla})")}
        if not cols_actuales:
            conn.execute(ddl_nueva)
            continue
        if "usuario_id" in cols_actuales:
            continue
        conn.execute(f"ALTER TABLE {tabla} RENAME TO {tabla}_viejo")
        conn.execute(ddl_nueva)
        fila = conn.execute(f"SELECT * FROM {tabla}_viejo WHERE id = 1").fetchone()
        if fila:
            marcadores = ", ".join("?" * len(columnas))
            conn.execute(
                f"INSERT INTO {tabla} (usuario_id, {', '.join(columnas)}) VALUES (?, {marcadores})",
                [usuario_id_local, *[fila[c] for c in columnas]],
            )
        conn.execute(f"DROP TABLE {tabla}_viejo")


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        _asegurar_columna(conn, "categorias", "papelera_en", "TEXT")
        _asegurar_columna(conn, "tareas", "papelera_en", "TEXT")
        _asegurar_columna(conn, "notas", "papelera_en", "TEXT")
        _asegurar_columna(conn, "categorias", "orden", "INTEGER")
        _asegurar_columna(conn, "categorias", "favorito", "INTEGER NOT NULL DEFAULT 0")
        _asegurar_columna(conn, "correo_mensajes", "message_id", "TEXT")
        _asegurar_columna(conn, "correo_mensajes", "cc", "TEXT")
        _asegurar_columna(conn, "correo_mensajes", "categoria_id", "INTEGER")
        _asegurar_columna(conn, "correo_cuentas", "firma_html", "TEXT")
        _asegurar_columna(conn, "correo_cuentas", "firma_en_nuevos", "INTEGER NOT NULL DEFAULT 1")
        _asegurar_columna(conn, "correo_cuentas", "firma_en_respuestas", "INTEGER NOT NULL DEFAULT 1")
        _asegurar_columna(conn, "correo_mensajes", "destacado", "INTEGER NOT NULL DEFAULT 0")
        _asegurar_columna(conn, "correo_mensajes", "fecha_aviso", "TEXT")
        _asegurar_columna(conn, "correo_mensajes", "pospuesto_hasta", "TEXT")
        _asegurar_columna(conn, "usuarios", "kratos_identity_id", "TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_kratos_identity_id "
            "ON usuarios(kratos_identity_id) WHERE kratos_identity_id IS NOT NULL"
        )
        # Tenants (Fase 7c.3): agrupar usuarios por organización. Opcional
        # (NULL = sin asignar) — no aísla datos entre tenants, solo
        # identifica de qué organización viene cada usuario para el
        # panel de administración y para integraciones externas (p.ej.
        # el widget de soporte de Chatwoot, que necesita saber a qué
        # tenant pertenece quien escribe).
        _asegurar_columna(conn, "usuarios", "tenant_id", "INTEGER REFERENCES tenants(id)")

        # Multiusuario: por si SCHEMA no llegó a crear la tabla con la
        # columna (bases de datos migradas desde una versión sin ella).
        for tabla in (
            "categorias", "notas", "tareas", "tareas_outlook",
            "correo_cuentas", "correo_categorias", "ia_mensajes",
        ):
            _asegurar_columna(conn, tabla, "usuario_id", "INTEGER")

        conn.executescript(INDICES)
        _asegurar_orden_categorias(conn)

        usuario_id_local = _resolver_usuario_local(conn)
        _migrar_datos_sin_usuario(conn, usuario_id_local)
        _migrar_preferencias_singleton(conn, usuario_id_local)

        # IA local (Ollama/LM Studio): columnas añadidas después de la
        # migración del singleton, ya que esta es la que crea/asegura la
        # propia tabla ia_preferencias en primer lugar.
        _asegurar_columna(conn, "ia_preferencias", "proveedor_local", "TEXT NOT NULL DEFAULT 'ollama'")
        _asegurar_columna(conn, "ia_preferencias", "modelo_local", "TEXT NOT NULL DEFAULT ''")

        conn.commit()
    finally:
        conn.close()


def hacer_backup_si_hace_falta(mantener_dias: int = 30) -> None:
    """Copia registro.db a data/backups/ una vez al día (idempotente si ya
    existe la copia de hoy) y borra copias más antiguas que `mantener_dias`.

    Usa la API de backup de sqlite3 en vez de una copia de archivo a pelo,
    para que sea segura aunque haya alguna conexión abierta en ese instante.
    """
    if not DB_PATH.exists():
        return
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    hoy = datetime.now().strftime("%Y-%m-%d")
    destino = BACKUPS_DIR / f"registro_{hoy}.db"
    if not destino.exists():
        origen = sqlite3.connect(DB_PATH)
        try:
            copia = sqlite3.connect(destino)
            try:
                origen.backup(copia)
            finally:
                copia.close()
        finally:
            origen.close()

    limite = datetime.now() - timedelta(days=mantener_dias)
    for f in BACKUPS_DIR.glob("registro_*.db"):
        try:
            fecha = datetime.strptime(f.stem.removeprefix("registro_"), "%Y-%m-%d")
        except ValueError:
            continue
        if fecha < limite:
            f.unlink(missing_ok=True)


# --- Usuarios / autenticación ------------------------------------------------

def crear_usuario(email: str, contrasena: str) -> int:
    """Crea una cuenta con la contraseña ya hasheada (nunca en texto plano).
    Lanza sqlite3.IntegrityError si el email ya existe (el email es UNIQUE)."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO usuarios (email, contrasena_hash, creado_en) VALUES (?, ?, ?)",
            (email.strip().lower(), generate_password_hash(contrasena), now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def obtener_usuario_por_email(email: str) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM usuarios WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
    finally:
        conn.close()


def obtener_usuario(usuario_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    finally:
        conn.close()


def listar_usuarios() -> list[sqlite3.Row]:
    """Todos los usuarios con el nombre de su tenant (si tiene), para el
    backoffice (Fase 7c) — no existe paginación porque el uso previsto es
    un puñado de usuarios, no miles."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT usuarios.*, tenants.nombre AS tenant_nombre "
            "FROM usuarios LEFT JOIN tenants ON tenants.id = usuarios.tenant_id "
            "ORDER BY usuarios.email"
        ).fetchall()
    finally:
        conn.close()


def es_admin(usuario_id: int) -> bool:
    usuario = obtener_usuario(usuario_id)
    return usuario is not None and usuario["rol"] == "admin"


def hacer_admin(email: str) -> None:
    """Lanza ValueError si no existe ningún usuario con ese email."""
    conn = get_connection()
    try:
        cur = conn.execute("UPDATE usuarios SET rol = 'admin' WHERE email = ?", (email.strip().lower(),))
        if cur.rowcount == 0:
            raise ValueError(f"No existe ningún usuario con el email '{email}'.")
        conn.commit()
    finally:
        conn.close()


def quitar_admin(email: str) -> None:
    """Lanza ValueError si no existe ningún usuario con ese email."""
    conn = get_connection()
    try:
        cur = conn.execute("UPDATE usuarios SET rol = 'usuario' WHERE email = ?", (email.strip().lower(),))
        if cur.rowcount == 0:
            raise ValueError(f"No existe ningún usuario con el email '{email}'.")
        conn.commit()
    finally:
        conn.close()


def verificar_credenciales(email: str, contrasena: str) -> sqlite3.Row | None:
    """Devuelve la fila del usuario si el email existe y la contraseña es
    correcta; None en cualquier otro caso (sin distinguir el motivo, para no
    filtrar si un email concreto existe o no).

    Solo queda en uso para el usuario "local" del modo escritorio (que
    nunca pasa por Kratos, ver `usuario_local_id`) — el login real
    (hospedado, web/API) verifica credenciales contra Kratos a partir de
    la Fase 7a; ver `app/kratos.py`."""
    usuario = obtener_usuario_por_email(email)
    if usuario is None or not check_password_hash(usuario["contrasena_hash"], contrasena):
        return None
    return usuario


# --- Vínculo con la identidad de Ory Kratos (Fase 7a) -------------------

def usuario_por_kratos_id(identity_id: str) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM usuarios WHERE kratos_identity_id = ?", (identity_id,)
        ).fetchone()
    finally:
        conn.close()


def vincular_kratos_id(usuario_id: int, identity_id: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE usuarios SET kratos_identity_id = ? WHERE id = ?", (identity_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


def crear_usuario_vinculado_a_kratos(email: str, identity_id: str) -> int:
    """Crea la fila local de `usuarios` para una identidad que YA existe en
    Kratos (login/registro real, a partir de la Fase 7a) — no guarda
    ninguna contraseña propia, Kratos es quien la custodia."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO usuarios (email, contrasena_hash, kratos_identity_id, creado_en) "
            "VALUES (?, ?, ?, ?)",
            (email.strip().lower(), "", identity_id, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# --- Tenants (Fase 7c.3) -------------------------------------------------

def crear_tenant(nombre: str) -> int:
    """Lanza sqlite3.IntegrityError si el nombre ya existe (UNIQUE)."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO tenants (nombre, creado_en) VALUES (?, ?)",
            (nombre.strip(), now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_tenants() -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM tenants ORDER BY nombre").fetchall()
    finally:
        conn.close()


def listar_tenants_con_conteo() -> list[sqlite3.Row]:
    """Como listar_tenants(), pero con el nº de usuarios asignados a cada
    uno (columna `n_usuarios`) — para la tabla del backoffice (Fase 7c)."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT tenants.*, COUNT(usuarios.id) AS n_usuarios "
            "FROM tenants LEFT JOIN usuarios ON usuarios.tenant_id = tenants.id "
            "GROUP BY tenants.id ORDER BY tenants.nombre"
        ).fetchall()
    finally:
        conn.close()


def renombrar_tenant(tenant_id: int, nuevo_nombre: str) -> None:
    """Lanza sqlite3.IntegrityError si el nombre ya existe (UNIQUE)."""
    conn = get_connection()
    try:
        conn.execute("UPDATE tenants SET nombre = ? WHERE id = ?", (nuevo_nombre.strip(), tenant_id))
        conn.commit()
    finally:
        conn.close()


def borrar_tenant(tenant_id: int) -> None:
    """Desasigna primero a los usuarios que lo tuvieran (quedan sin tenant,
    no se borran) y luego borra el tenant — no depende de ON DELETE
    CASCADE, que la tabla no declara."""
    conn = get_connection()
    try:
        conn.execute("UPDATE usuarios SET tenant_id = NULL WHERE tenant_id = ?", (tenant_id,))
        conn.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
        conn.commit()
    finally:
        conn.close()


def desasignar_tenant(usuario_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE usuarios SET tenant_id = NULL WHERE id = ?", (usuario_id,))
        conn.commit()
    finally:
        conn.close()


def obtener_tenant(tenant_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()


def obtener_tenant_por_nombre(nombre: str) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM tenants WHERE nombre = ?", (nombre.strip(),)).fetchone()
    finally:
        conn.close()


def asignar_tenant(usuario_id: int, tenant_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE usuarios SET tenant_id = ? WHERE id = ?", (tenant_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def tenant_de_usuario(usuario_id: int) -> sqlite3.Row | None:
    """El tenant del usuario, o None si no tiene ninguno asignado todavía."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT tenants.* FROM tenants "
            "JOIN usuarios ON usuarios.tenant_id = tenants.id "
            "WHERE usuarios.id = ?",
            (usuario_id,),
        ).fetchone()
    finally:
        conn.close()


def usuario_local_id() -> int:
    """Para procesos locales de confianza (cli.py, mcp_server.py) que no
    pasan por login web: resuelve (o crea la primera vez) el usuario local
    fijo, y lo usan siempre como su `usuario_id`."""
    conn = get_connection()
    try:
        uid = _resolver_usuario_local(conn)
        conn.commit()
        return uid
    finally:
        conn.close()


# --- Tokens de la API (Fase 2, app móvil) -------------------------------
# Tokens opacos (no JWT): el valor en claro se genera una vez y se devuelve
# al cliente; aquí solo se guarda su hash SHA-256 (no generate_password_hash
# — el token ya tiene alta entropía propia y hace falta una búsqueda exacta
# rápida por igualdad, no una comparación tipo contraseña).

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def crear_token_api(usuario_id: int, nombre_dispositivo: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO tokens_api (usuario_id, token_hash, nombre_dispositivo, creado_en) "
            "VALUES (?, ?, ?, ?)",
            (usuario_id, _hash_token(token), nombre_dispositivo, now_iso()),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def usuario_id_por_token(token: str) -> int | None:
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT usuario_id FROM tokens_api WHERE token_hash = ?", (_hash_token(token),)
        ).fetchone()
        if fila is None:
            return None
        conn.execute(
            "UPDATE tokens_api SET ultimo_uso_en = ? WHERE token_hash = ?",
            (now_iso(), _hash_token(token)),
        )
        conn.commit()
        return fila["usuario_id"]
    finally:
        conn.close()


def revocar_token_api(token: str) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM tokens_api WHERE token_hash = ?", (_hash_token(token),))
        conn.commit()
    finally:
        conn.close()


# --- Categorías --------------------------------------------------------

def crear_categoria(usuario_id: int, nombre: str, color: str | None = None) -> int:
    """Crea un menú, o reutiliza uno existente con el mismo nombre.

    `nombre` tiene una restricción UNIQUE en la tabla, y esa restricción no
    distingue entre menús activos y en la papelera — así que sin este
    chequeo, crear un menú con el mismo nombre que uno ya borrado (pero
    todavía en la papelera) reventaría con un IntegrityError. Si el que
    existe está en la papelera, se restaura en vez de fallar.
    """
    nombre = nombre.strip()
    conn = get_connection()
    try:
        existente = conn.execute(
            "SELECT id, papelera_en FROM categorias WHERE nombre = ?", (nombre,)
        ).fetchone()
        if existente is not None:
            if existente["papelera_en"] is not None:
                conn.execute(
                    "UPDATE categorias SET papelera_en = NULL WHERE id = ?", (existente["id"],)
                )
                conn.commit()
            return existente["id"]

        siguiente_orden = conn.execute(
            "SELECT COALESCE(MAX(orden), -1) + 1 FROM categorias WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO categorias (usuario_id, nombre, color, creada_en, orden) VALUES (?, ?, ?, ?, ?)",
            (usuario_id, nombre, color, now_iso(), siguiente_orden),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_categorias(usuario_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM categorias WHERE usuario_id = ? AND papelera_en IS NULL ORDER BY orden, nombre",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def mover_categoria(usuario_id: int, categoria_id: int, direccion: str) -> None:
    """Reordena un menú un puesto arriba o abajo (`direccion`: 'arriba'/'abajo')."""
    conn = get_connection()
    try:
        activas = conn.execute(
            "SELECT id, orden FROM categorias WHERE usuario_id = ? AND papelera_en IS NULL ORDER BY orden, nombre",
            (usuario_id,),
        ).fetchall()
        ids = [f["id"] for f in activas]
        if categoria_id not in ids:
            return
        idx = ids.index(categoria_id)
        vecino_idx = idx - 1 if direccion == "arriba" else idx + 1
        if vecino_idx < 0 or vecino_idx >= len(ids):
            return
        conn.execute(
            "UPDATE categorias SET orden = ? WHERE id = ?", (activas[vecino_idx]["orden"], categoria_id)
        )
        conn.execute(
            "UPDATE categorias SET orden = ? WHERE id = ?", (activas[idx]["orden"], ids[vecino_idx])
        )
        conn.commit()
    finally:
        conn.close()


def reordenar_categorias(usuario_id: int, orden_ids: list[int]) -> None:
    """Reescribe `orden` según la lista completa recibida (0, 1, 2...), para
    el arrastrar-y-soltar de la barra lateral — a diferencia de
    `mover_categoria`, que mueve un solo puesto. Los ids que no existan (o no
    estén activos, o no sean del usuario) se ignoran sin fallar; los menús
    activos que falten en la lista conservan su `orden` actual, detrás de
    los que sí se han movido."""
    conn = get_connection()
    try:
        activos = {
            f["id"] for f in conn.execute(
                "SELECT id FROM categorias WHERE usuario_id = ? AND papelera_en IS NULL", (usuario_id,)
            )
        }
        siguiente = 0
        for categoria_id in orden_ids:
            if categoria_id in activos:
                conn.execute("UPDATE categorias SET orden = ? WHERE id = ?", (siguiente, categoria_id))
                siguiente += 1
        conn.commit()
    finally:
        conn.close()


def alternar_favorito_categoria(usuario_id: int, categoria_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE categorias SET favorito = 1 - favorito WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL",
            (categoria_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def obtener_categoria(usuario_id: int, categoria_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM categorias WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL",
            (categoria_id, usuario_id),
        ).fetchone()
    finally:
        conn.close()


def renombrar_categoria(usuario_id: int, categoria_id: int, nombre: str, color: str | None = None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE categorias SET nombre = ?, color = ? WHERE id = ? AND usuario_id = ?",
            (nombre.strip(), color, categoria_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_categoria(usuario_id: int, categoria_id: int) -> None:
    """Manda un menú (y todo lo que contiene) a la papelera. No borra nada de
    verdad — se puede restaurar, o purgar definitivamente desde la papelera."""
    conn = get_connection()
    try:
        ahora = _marca_papelera()
        conn.execute(
            "UPDATE categorias SET papelera_en = ? WHERE id = ? AND usuario_id = ?",
            (ahora, categoria_id, usuario_id),
        )
        conn.execute(
            "UPDATE tareas SET papelera_en = ? WHERE categoria_id = ? AND usuario_id = ? AND papelera_en IS NULL",
            (ahora, categoria_id, usuario_id),
        )
        conn.execute(
            "UPDATE notas SET papelera_en = ? WHERE categoria_id = ? AND usuario_id = ? AND papelera_en IS NULL",
            (ahora, categoria_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def restaurar_categoria(usuario_id: int, categoria_id: int) -> None:
    """Saca un menú de la papelera, junto con lo que se mandó a la papelera
    a la vez que él (no restaura notas/tareas que ya estaban en la papelera
    por separado antes de borrar el menú)."""
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT papelera_en FROM categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id)
        ).fetchone()
        if fila is None or fila["papelera_en"] is None:
            return
        marca = fila["papelera_en"]
        conn.execute("UPDATE categorias SET papelera_en = NULL WHERE id = ?", (categoria_id,))
        conn.execute(
            "UPDATE tareas SET papelera_en = NULL WHERE categoria_id = ? AND papelera_en = ?",
            (categoria_id, marca),
        )
        conn.execute(
            "UPDATE notas SET papelera_en = NULL WHERE categoria_id = ? AND papelera_en = ?",
            (categoria_id, marca),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_categoria_definitivamente(usuario_id: int, categoria_id: int) -> None:
    """Borra un menú y todo lo que contiene de verdad (sin pasar por la
    papelera). Lo usa el botón "Eliminar definitivamente" y la purga
    automática de la papelera."""
    conn = get_connection()
    try:
        tarea_ids = [
            row["id"] for row in conn.execute(
                "SELECT id FROM tareas WHERE categoria_id = ? AND usuario_id = ?", (categoria_id, usuario_id)
            ).fetchall()
        ]
        if tarea_ids:
            marcas = ",".join("?" * len(tarea_ids))
            conn.execute(f"DELETE FROM pausas WHERE tarea_id IN ({marcas})", tarea_ids)
            conn.execute(f"DELETE FROM notas WHERE tarea_id IN ({marcas})", tarea_ids)
        conn.execute("DELETE FROM notas WHERE categoria_id = ? AND usuario_id = ?", (categoria_id, usuario_id))
        conn.execute("DELETE FROM tareas WHERE categoria_id = ? AND usuario_id = ?", (categoria_id, usuario_id))
        conn.execute("DELETE FROM plantillas WHERE categoria_id = ?", (categoria_id,))
        conn.execute("DELETE FROM categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def contar_entradas_hoy(usuario_id: int, categoria_id: int) -> int:
    conn = get_connection()
    try:
        hoy = datetime.now().strftime("%Y-%m-%d")
        manana = _fecha_exclusiva(hoy)
        n = conn.execute(
            "SELECT COUNT(*) FROM notas WHERE categoria_id = ? AND usuario_id = ? AND papelera_en IS NULL AND creada_en >= ? AND creada_en < ?",
            (categoria_id, usuario_id, hoy, manana),
        ).fetchone()[0]
        t = conn.execute(
            "SELECT COUNT(*) FROM tareas WHERE categoria_id = ? AND usuario_id = ? AND papelera_en IS NULL AND inicio_en >= ? AND inicio_en < ?",
            (categoria_id, usuario_id, hoy, manana),
        ).fetchone()[0]
        return n + t
    finally:
        conn.close()


# --- Tareas / eventos ---------------------------------------------------

def crear_tarea(usuario_id: int, nombre: str, categoria_id: int, tipo: str) -> int:
    conn = get_connection()
    try:
        ahora = now_iso()
        if tipo == "instantanea":
            cur = conn.execute(
                """INSERT INTO tareas
                   (usuario_id, nombre, categoria_id, tipo, estado, inicio_en, fin_en, duracion_segundos)
                   VALUES (?, ?, ?, 'instantanea', 'finalizada', ?, NULL, NULL)""",
                (usuario_id, nombre.strip(), categoria_id, ahora),
            )
        else:
            cur = conn.execute(
                """INSERT INTO tareas
                   (usuario_id, nombre, categoria_id, tipo, estado, inicio_en, fin_en, duracion_segundos)
                   VALUES (?, ?, ?, 'duracion', 'en_curso', ?, NULL, NULL)""",
                (usuario_id, nombre.strip(), categoria_id, ahora),
            )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def importar_tarea(
    usuario_id: int,
    nombre: str,
    categoria_id: int,
    tipo: str,
    inicio_en: str,
    fin_en: str | None,
    duracion_segundos: int | None,
) -> int:
    """Inserta una tarea/evento ya finalizado con timestamps explícitos
    (usado por la importación de datos exportados previamente). A
    diferencia de crear_tarea(), no usa la hora actual ni deja la tarea en
    curso — todo lo que se importa entra como histórico ya cerrado."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO tareas
               (usuario_id, nombre, categoria_id, tipo, estado, inicio_en, fin_en, duracion_segundos)
               VALUES (?, ?, ?, ?, 'finalizada', ?, ?, ?)""",
            (usuario_id, nombre.strip(), categoria_id, tipo, inicio_en, fin_en, duracion_segundos),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def hubo_actividad_reciente(usuario_id: int, minutos: int) -> bool:
    """True si se ha creado alguna nota o tarea en los últimos `minutos`."""
    conn = get_connection()
    try:
        limite = (datetime.now() - timedelta(minutes=minutos)).isoformat(timespec="seconds")
        n = conn.execute(
            "SELECT COUNT(*) FROM notas WHERE usuario_id = ? AND creada_en >= ?", (usuario_id, limite)
        ).fetchone()[0]
        t = conn.execute(
            "SELECT COUNT(*) FROM tareas WHERE usuario_id = ? AND inicio_en >= ?", (usuario_id, limite)
        ).fetchone()[0]
        return (n + t) > 0
    finally:
        conn.close()


def _segundos_pausados_cerrados(conn: sqlite3.Connection, tarea_id: int) -> int:
    """Suma la duración de las pausas ya cerradas (reanudadas) de una tarea."""
    total = 0
    for r in conn.execute(
        "SELECT pausada_en, reanudada_en FROM pausas WHERE tarea_id = ? AND reanudada_en IS NOT NULL",
        (tarea_id,),
    ):
        total += int(
            (datetime.fromisoformat(r["reanudada_en"]) - datetime.fromisoformat(r["pausada_en"])).total_seconds()
        )
    return total


def pausar_tarea(usuario_id: int, tarea_id: int) -> None:
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE tareas SET estado = 'pausada' WHERE id = ? AND usuario_id = ? AND tipo = 'duracion' AND estado = 'en_curso'",
            (tarea_id, usuario_id),
        )
        if cur.rowcount:
            conn.execute(
                "INSERT INTO pausas (tarea_id, pausada_en) VALUES (?, ?)",
                (tarea_id, now_iso()),
            )
        conn.commit()
    finally:
        conn.close()


def reanudar_tarea(usuario_id: int, tarea_id: int) -> None:
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE tareas SET estado = 'en_curso' WHERE id = ? AND usuario_id = ? AND estado = 'pausada'",
            (tarea_id, usuario_id),
        )
        if cur.rowcount:
            conn.execute(
                """UPDATE pausas SET reanudada_en = ?
                   WHERE tarea_id = ? AND reanudada_en IS NULL""",
                (now_iso(), tarea_id),
            )
        conn.commit()
    finally:
        conn.close()


def finalizar_tarea(usuario_id: int, tarea_id: int) -> None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT inicio_en, estado FROM tareas WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)
        ).fetchone()
        if row is None:
            return
        fin = now_iso()
        if row["estado"] == "pausada":
            conn.execute(
                "UPDATE pausas SET reanudada_en = ? WHERE tarea_id = ? AND reanudada_en IS NULL",
                (fin, tarea_id),
            )
        inicio = datetime.fromisoformat(row["inicio_en"])
        segundos_pausados = _segundos_pausados_cerrados(conn, tarea_id)
        duracion = int((datetime.fromisoformat(fin) - inicio).total_seconds()) - segundos_pausados
        conn.execute(
            "UPDATE tareas SET estado = 'finalizada', fin_en = ?, duracion_segundos = ? WHERE id = ?",
            (fin, max(duracion, 0), tarea_id),
        )
        conn.commit()
    finally:
        conn.close()


def tareas_activas(usuario_id: int) -> list[dict]:
    """Tareas con duración en curso o en pausa, con el tiempo ya pausado calculado."""
    conn = get_connection()
    try:
        filas = conn.execute(
            """SELECT t.*, c.nombre AS categoria_nombre, c.color AS categoria_color
               FROM tareas t JOIN categorias c ON c.id = t.categoria_id
               WHERE t.usuario_id = ? AND t.tipo = 'duracion' AND t.estado IN ('en_curso', 'pausada')
                 AND t.papelera_en IS NULL
               ORDER BY t.inicio_en""",
            (usuario_id,),
        ).fetchall()
        resultado = []
        for f in filas:
            d = dict(f)
            d["segundos_pausados"] = _segundos_pausados_cerrados(conn, f["id"])
            if f["estado"] == "pausada":
                pausa_abierta = conn.execute(
                    "SELECT pausada_en FROM pausas WHERE tarea_id = ? AND reanudada_en IS NULL",
                    (f["id"],),
                ).fetchone()
                inicio = datetime.fromisoformat(f["inicio_en"])
                pausada_en = datetime.fromisoformat(pausa_abierta["pausada_en"])
                d["segundos_trabajados_congelado"] = max(
                    int((pausada_en - inicio).total_seconds()) - d["segundos_pausados"], 0
                )
            resultado.append(d)
        return resultado
    finally:
        conn.close()


def obtener_tarea(usuario_id: int, tarea_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT t.*, c.nombre AS categoria_nombre
               FROM tareas t JOIN categorias c ON c.id = t.categoria_id
               WHERE t.id = ? AND t.usuario_id = ? AND t.papelera_en IS NULL""",
            (tarea_id, usuario_id),
        ).fetchone()
    finally:
        conn.close()


def editar_tarea(usuario_id: int, tarea_id: int, nombre: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tareas SET nombre = ? WHERE id = ? AND usuario_id = ?",
            (nombre.strip(), tarea_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def editar_tiempos_tarea(usuario_id: int, tarea_id: int, inicio_en: str, fin_en: str | None = None) -> str | None:
    """Ajusta manualmente el inicio (y el fin, si la tarea ya está finalizada).

    Devuelve un mensaje de error legible si la entrada no es válida, o None si todo fue bien.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT tipo, estado, fin_en FROM tareas WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)
        ).fetchone()
        if row is None:
            return "La tarea ya no existe."
        try:
            inicio = datetime.fromisoformat(inicio_en)
        except ValueError:
            return "La fecha/hora de inicio no es válida."

        if row["estado"] == "finalizada" and row["tipo"] == "duracion":
            if not fin_en:
                return "Falta la fecha/hora de fin."
            try:
                fin = datetime.fromisoformat(fin_en)
            except ValueError:
                return "La fecha/hora de fin no es válida."
            if fin <= inicio:
                return "El fin debe ser posterior al inicio."
            segundos_pausados = _segundos_pausados_cerrados(conn, tarea_id)
            duracion = max(int((fin - inicio).total_seconds()) - segundos_pausados, 0)
            conn.execute(
                "UPDATE tareas SET inicio_en = ?, fin_en = ?, duracion_segundos = ? WHERE id = ?",
                (inicio.isoformat(timespec="seconds"), fin.isoformat(timespec="seconds"), duracion, tarea_id),
            )
        else:
            if inicio > datetime.now():
                return "El inicio no puede ser en el futuro."
            conn.execute(
                "UPDATE tareas SET inicio_en = ? WHERE id = ?",
                (inicio.isoformat(timespec="seconds"), tarea_id),
            )
        conn.commit()
        return None
    finally:
        conn.close()


def eliminar_tarea(usuario_id: int, tarea_id: int) -> None:
    """Manda una tarea/evento a la papelera (no la borra de verdad)."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tareas SET papelera_en = ? WHERE id = ? AND usuario_id = ?",
            (_marca_papelera(), tarea_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def restaurar_tarea(usuario_id: int, tarea_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tareas SET papelera_en = NULL WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_tarea_definitivamente(usuario_id: int, tarea_id: int) -> None:
    """Borra una tarea/evento y sus pausas y notas asociadas de verdad."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM pausas WHERE tarea_id = ?", (tarea_id,))
        conn.execute("DELETE FROM notas WHERE tarea_id = ?", (tarea_id,))
        conn.execute("DELETE FROM tareas WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


# --- Notas ---------------------------------------------------------------

def crear_nota(usuario_id: int, texto: str, categoria_id: int | None = None, tarea_id: int | None = None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO notas (usuario_id, texto, categoria_id, tarea_id, creada_en) VALUES (?, ?, ?, ?, ?)",
            (usuario_id, texto.strip(), categoria_id, tarea_id, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def importar_nota(usuario_id: int, texto: str, categoria_id: int | None, creada_en: str) -> int:
    """Inserta una nota con un timestamp explícito (importación de datos exportados)."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO notas (usuario_id, texto, categoria_id, tarea_id, creada_en) VALUES (?, ?, ?, NULL, ?)",
            (usuario_id, texto.strip(), categoria_id, creada_en),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def obtener_nota(usuario_id: int, nota_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM notas WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL", (nota_id, usuario_id)
        ).fetchone()
    finally:
        conn.close()


def editar_nota(usuario_id: int, nota_id: int, texto: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE notas SET texto = ? WHERE id = ? AND usuario_id = ?", (texto.strip(), nota_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_nota(usuario_id: int, nota_id: int) -> None:
    """Manda una nota a la papelera (no la borra de verdad)."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE notas SET papelera_en = ? WHERE id = ? AND usuario_id = ?",
            (_marca_papelera(), nota_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def restaurar_nota(usuario_id: int, nota_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE notas SET papelera_en = NULL WHERE id = ? AND usuario_id = ?", (nota_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_nota_definitivamente(usuario_id: int, nota_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM notas WHERE id = ? AND usuario_id = ?", (nota_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


# --- Histórico combinado ---------------------------------------------------

def historial(
    usuario_id: int,
    desde: str | None = None,
    hasta: str | None = None,
    categoria_id: int | None = None,
    texto: str | None = None,
):
    """Devuelve notas y tareas combinadas, ordenadas cronológicamente descendente.

    desde/hasta: fechas 'YYYY-MM-DD' (inclusive).
    texto: si se indica, filtra por coincidencia parcial (insensible a mayúsculas).
    """
    conn = get_connection()
    try:
        # El filtro de fecha se aplica DENTRO de cada rama (sobre la columna
        # de timestamp real, notas.creada_en / tareas.inicio_en) en vez de
        # sobre un alias calculado en la consulta exterior — así SQLite
        # puede usar los índices idx_notas_categoria_creada /
        # idx_tareas_categoria_inicio en vez de escanear ambas tablas
        # enteras antes de filtrar.
        hasta_excl = _fecha_exclusiva(hasta) if hasta else None

        cond_n = ["n.usuario_id = ?", "n.papelera_en IS NULL"]
        cond_t = ["t.usuario_id = ?", "t.papelera_en IS NULL"]
        params_n: list = [usuario_id]
        params_t: list = [usuario_id]
        if desde:
            cond_n.append("n.creada_en >= ?"); params_n.append(desde)
            cond_t.append("t.inicio_en >= ?"); params_t.append(desde)
        if hasta_excl:
            cond_n.append("n.creada_en < ?"); params_n.append(hasta_excl)
            cond_t.append("t.inicio_en < ?"); params_t.append(hasta_excl)
        if categoria_id:
            cond_n.append("n.categoria_id = ?"); params_n.append(categoria_id)
            cond_t.append("t.categoria_id = ?"); params_t.append(categoria_id)
        if texto:
            cond_n.append("n.texto LIKE ?"); params_n.append(f"%{texto}%")
            cond_t.append("t.nombre LIKE ?"); params_t.append(f"%{texto}%")

        query = f"""
            SELECT * FROM (
                SELECT
                    'nota' AS origen,
                    n.id AS id,
                    n.texto AS texto,
                    NULL AS tipo,
                    NULL AS estado,
                    n.creada_en AS timestamp,
                    NULL AS fin_en,
                    NULL AS duracion_segundos,
                    n.categoria_id AS categoria_id,
                    c.nombre AS categoria_nombre,
                    c.color AS categoria_color
                FROM notas n LEFT JOIN categorias c ON c.id = n.categoria_id
                WHERE {' AND '.join(cond_n)}

                UNION ALL

                SELECT
                    'tarea' AS origen,
                    t.id AS id,
                    t.nombre AS texto,
                    t.tipo AS tipo,
                    t.estado AS estado,
                    t.inicio_en AS timestamp,
                    t.fin_en AS fin_en,
                    t.duracion_segundos AS duracion_segundos,
                    t.categoria_id AS categoria_id,
                    c.nombre AS categoria_nombre,
                    c.color AS categoria_color
                FROM tareas t JOIN categorias c ON c.id = t.categoria_id
                WHERE {' AND '.join(cond_t)}
            )
            ORDER BY timestamp DESC
        """
        return conn.execute(query, [*params_n, *params_t]).fetchall()
    finally:
        conn.close()


# --- Estadísticas ----------------------------------------------------------

def estadisticas_por_categoria(usuario_id: int, desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Tiempo total (tareas finalizadas) y nº de entradas por categoría."""
    conn = get_connection()
    try:
        cond_t = ["t.usuario_id = ?", "t.tipo = 'duracion'", "t.estado = 'finalizada'", "t.papelera_en IS NULL"]
        cond_ev = ["tt.usuario_id = ?", "tt.tipo = 'instantanea'", "tt.papelera_en IS NULL"]
        cond_n = ["n.usuario_id = ?", "n.papelera_en IS NULL"]
        params_t: list = [usuario_id]
        params_ev: list = [usuario_id]
        params_n: list = [usuario_id]
        hasta_excl = _fecha_exclusiva(hasta) if hasta else None
        if desde:
            cond_t.append("t.inicio_en >= ?"); params_t.append(desde)
            cond_ev.append("tt.inicio_en >= ?"); params_ev.append(desde)
            cond_n.append("n.creada_en >= ?"); params_n.append(desde)
        if hasta_excl:
            cond_t.append("t.inicio_en < ?"); params_t.append(hasta_excl)
            cond_ev.append("tt.inicio_en < ?"); params_ev.append(hasta_excl)
            cond_n.append("n.creada_en < ?"); params_n.append(hasta_excl)

        filas = conn.execute(
            f"""SELECT c.id, c.nombre, c.color,
                   COALESCE((SELECT SUM(t.duracion_segundos) FROM tareas t
                             WHERE t.categoria_id = c.id AND {' AND '.join(cond_t)}), 0) AS segundos_totales,
                   COALESCE((SELECT COUNT(*) FROM tareas t
                             WHERE t.categoria_id = c.id AND {' AND '.join(cond_t)}), 0) AS num_tareas,
                   COALESCE((SELECT COUNT(*) FROM tareas tt
                             WHERE tt.categoria_id = c.id AND {' AND '.join(cond_ev)}), 0) AS num_eventos,
                   COALESCE((SELECT COUNT(*) FROM notas n
                             WHERE n.categoria_id = c.id AND {' AND '.join(cond_n)}), 0) AS num_notas
               FROM categorias c
               WHERE c.usuario_id = ?
               ORDER BY segundos_totales DESC, c.nombre""",
            [*params_t, *params_t, *params_ev, *params_n, usuario_id],
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def estadisticas_por_dia(usuario_id: int, desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Tiempo total en tareas con duración finalizadas, agrupado por día y categoría."""
    conn = get_connection()
    try:
        cond = ["t.usuario_id = ?", "t.tipo = 'duracion'", "t.estado = 'finalizada'", "t.papelera_en IS NULL"]
        params: list = [usuario_id]
        if desde:
            cond.append("t.inicio_en >= ?"); params.append(desde)
        if hasta:
            cond.append("t.inicio_en < ?"); params.append(_fecha_exclusiva(hasta))
        where = " AND ".join(cond)
        filas = conn.execute(
            f"""SELECT substr(t.inicio_en,1,10) AS fecha, c.nombre AS categoria, c.color AS categoria_color,
                       SUM(t.duracion_segundos) AS segundos
                FROM tareas t JOIN categorias c ON c.id = t.categoria_id
                WHERE {where}
                GROUP BY fecha, c.id
                ORDER BY fecha DESC, segundos DESC""",
            params,
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


# --- Frases favoritas (plantillas) ------------------------------------------
# Se aíslan a través de categoria_id (NOT NULL, siempre de un usuario ya
# validado por la ruta antes de llamar aquí) — no llevan usuario_id propio.

def crear_plantilla(categoria_id: int, texto: str) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO plantillas (categoria_id, texto, creada_en) VALUES (?, ?, ?)",
            (categoria_id, texto.strip(), now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_plantillas(categoria_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM plantillas WHERE categoria_id = ? ORDER BY id", (categoria_id,)
        ).fetchall()
    finally:
        conn.close()


def eliminar_plantilla(plantilla_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM plantillas WHERE id = ?", (plantilla_id,))
        conn.commit()
    finally:
        conn.close()


# --- Tareas al estilo Outlook (lista + calendario) --------------------------
# Independientes de los menús y de las tareas con duración de más arriba.
# Los campos calcan el modelo de objetos de Outlook / VTODO de iCalendar
# para que importar y exportar sea un mapeo directo, campo a campo.

CAMPOS_TAREA_OUTLOOK = (
    "asunto", "cuerpo", "estado", "porcentaje_completado", "prioridad",
    "fecha_inicio", "fecha_vencimiento", "fecha_completada",
    "categoria_outlook", "outlook_entry_id",
)


def crear_tarea_outlook(
    usuario_id: int,
    asunto: str,
    cuerpo: str | None = None,
    estado: str = "no_iniciada",
    porcentaje_completado: int = 0,
    prioridad: str = "normal",
    fecha_inicio: str | None = None,
    fecha_vencimiento: str | None = None,
    categoria_outlook: str | None = None,
    outlook_entry_id: str | None = None,
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO tareas_outlook
               (usuario_id, asunto, cuerpo, estado, porcentaje_completado, prioridad,
                fecha_inicio, fecha_vencimiento, categoria_outlook,
                outlook_entry_id, creada_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                usuario_id, asunto.strip(), (cuerpo or "").strip() or None, estado,
                porcentaje_completado, prioridad, fecha_inicio, fecha_vencimiento,
                (categoria_outlook or "").strip() or None, outlook_entry_id, now_iso(),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_tareas_outlook(
    usuario_id: int,
    estado: str | None = None,
    prioridad: str | None = None,
    categoria_outlook: str | None = None,
    texto: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
) -> list[sqlite3.Row]:
    """Tareas activas (no en la papelera), filtradas opcionalmente.

    `desde`/`hasta` filtran por fecha_vencimiento (YYYY-MM-DD, inclusive) —
    los usa la vista calendario para pedir solo las de un rango de días.
    """
    conn = get_connection()
    try:
        cond = ["usuario_id = ?", "papelera_en IS NULL"]
        params: list = [usuario_id]
        if estado:
            cond.append("estado = ?"); params.append(estado)
        if prioridad:
            cond.append("prioridad = ?"); params.append(prioridad)
        if categoria_outlook:
            cond.append("categoria_outlook = ?"); params.append(categoria_outlook)
        if texto:
            cond.append("(asunto LIKE ? OR cuerpo LIKE ?)")
            params.extend([f"%{texto}%", f"%{texto}%"])
        if desde:
            cond.append("fecha_vencimiento >= ?"); params.append(desde)
        if hasta:
            cond.append("fecha_vencimiento < ?"); params.append(_fecha_exclusiva(hasta))
        where = " AND ".join(cond)
        return conn.execute(
            f"""SELECT * FROM tareas_outlook WHERE {where}
                ORDER BY (fecha_vencimiento IS NULL), fecha_vencimiento, prioridad DESC""",
            params,
        ).fetchall()
    finally:
        conn.close()


def obtener_tarea_outlook(usuario_id: int, tarea_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM tareas_outlook WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL",
            (tarea_id, usuario_id),
        ).fetchone()
    finally:
        conn.close()


def obtener_tarea_outlook_por_entry_id(usuario_id: int, entry_id: str) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM tareas_outlook WHERE outlook_entry_id = ? AND usuario_id = ?", (entry_id, usuario_id)
        ).fetchone()
    finally:
        conn.close()


def upsert_tarea_outlook_por_entry_id(usuario_id: int, outlook_entry_id: str | None, **campos) -> tuple[int, bool]:
    """Crea la tarea, o actualiza la ya existente con ese `outlook_entry_id`.

    Devuelve (id, creada) — creada=True si no existía y se ha creado nueva.
    Pensado para sincronizar desde una fuente externa (.ics, .csv, o más
    adelante COM) sin duplicar tareas ya importadas en una sincronización anterior.
    """
    existente = obtener_tarea_outlook_por_entry_id(usuario_id, outlook_entry_id) if outlook_entry_id else None
    if existente:
        campos_validos = {c: v for c, v in campos.items() if c in CAMPOS_TAREA_OUTLOOK}
        editar_tarea_outlook(usuario_id, existente["id"], **campos_validos)
        return existente["id"], False

    # crear_tarea_outlook no acepta fecha_completada como argumento de creación
    # (una tarea recién creada no puede nacer ya completada por diseño del
    # formulario normal) — si el origen externo trae una, se aplica aparte.
    fecha_completada = campos.get("fecha_completada")
    campos_creacion = {
        c: v for c, v in campos.items()
        if c in CAMPOS_TAREA_OUTLOOK and c not in ("fecha_completada", "outlook_entry_id")
    }
    tid = crear_tarea_outlook(usuario_id, outlook_entry_id=outlook_entry_id, **campos_creacion)
    if fecha_completada:
        editar_tarea_outlook(usuario_id, tid, fecha_completada=fecha_completada)
    return tid, True


def editar_tarea_outlook(usuario_id: int, tarea_id: int, **campos) -> None:
    """Actualiza los campos indicados (cualquiera de CAMPOS_TAREA_OUTLOOK)."""
    columnas = [c for c in campos if c in CAMPOS_TAREA_OUTLOOK]
    if not columnas:
        return
    conn = get_connection()
    try:
        asignaciones = ", ".join(f"{c} = ?" for c in columnas)
        valores = [campos[c] for c in columnas]
        conn.execute(
            f"UPDATE tareas_outlook SET {asignaciones}, actualizada_en = ? WHERE id = ? AND usuario_id = ?",
            [*valores, now_iso(), tarea_id, usuario_id],
        )
        conn.commit()
    finally:
        conn.close()


def completar_tarea_outlook(usuario_id: int, tarea_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE tareas_outlook
               SET estado = 'completada', porcentaje_completado = 100,
                   fecha_completada = ?, actualizada_en = ?
               WHERE id = ? AND usuario_id = ?""",
            (now_iso(), now_iso(), tarea_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_tarea_outlook(usuario_id: int, tarea_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tareas_outlook SET papelera_en = ? WHERE id = ? AND usuario_id = ?",
            (_marca_papelera(), tarea_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def restaurar_tarea_outlook(usuario_id: int, tarea_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tareas_outlook SET papelera_en = NULL WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_tarea_outlook_definitivamente(usuario_id: int, tarea_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM tareas_outlook WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def listar_categorias_outlook(usuario_id: int) -> list[str]:
    """Nombres de categoría (estilo "Categories" de Outlook) usados hasta ahora."""
    conn = get_connection()
    try:
        filas = conn.execute(
            """SELECT DISTINCT categoria_outlook FROM tareas_outlook
               WHERE usuario_id = ? AND categoria_outlook IS NOT NULL AND papelera_en IS NULL
               ORDER BY categoria_outlook""",
            (usuario_id,),
        ).fetchall()
        return [f["categoria_outlook"] for f in filas]
    finally:
        conn.close()


# --- Correo (cuentas IMAP/POP3 + caché de mensajes) ---------------------------
# La lógica de red (conectar, sincronizar, enviar) vive en app/correo.py; aquí
# solo hay persistencia. La contraseña de cada cuenta NO se guarda en esta
# tabla — la gestiona app/correo.py directamente contra keyring.
# correo_carpetas/correo_mensajes/correo_adjuntos cuelgan de correo_cuentas
# (cuenta_id NOT NULL) y se aíslan por JOIN — no llevan usuario_id propio.

def crear_cuenta_correo(
    usuario_id: int,
    nombre: str, protocolo: str, host: str, puerto: int, usuario: str,
    usa_tls: bool = True, smtp_host: str | None = None,
    smtp_puerto: int | None = None, smtp_tls: bool = True,
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO correo_cuentas
               (usuario_id, nombre, protocolo, host, puerto, usa_tls, usuario,
                smtp_host, smtp_puerto, smtp_tls, creada_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (usuario_id, nombre.strip(), protocolo, host.strip(), puerto, int(usa_tls),
             usuario.strip(), (smtp_host or "").strip() or None, smtp_puerto,
             int(smtp_tls), now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_cuentas_correo(usuario_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_cuentas WHERE usuario_id = ? ORDER BY nombre", (usuario_id,)
        ).fetchall()
    finally:
        conn.close()


def obtener_cuenta_correo(usuario_id: int, cuenta_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_cuentas WHERE id = ? AND usuario_id = ?", (cuenta_id, usuario_id)
        ).fetchone()
    finally:
        conn.close()


def eliminar_cuenta_correo(usuario_id: int, cuenta_id: int) -> None:
    """Borra la cuenta y sus mensajes/carpetas cacheados. Sin papelera: la
    credencial en keyring se borra aparte, desde app/correo.py, antes de
    llamar aquí."""
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM correo_mensajes WHERE cuenta_id IN (SELECT id FROM correo_cuentas WHERE id = ? AND usuario_id = ?)",
            (cuenta_id, usuario_id),
        )
        conn.execute(
            "DELETE FROM correo_carpetas WHERE cuenta_id IN (SELECT id FROM correo_cuentas WHERE id = ? AND usuario_id = ?)",
            (cuenta_id, usuario_id),
        )
        conn.execute("DELETE FROM correo_cuentas WHERE id = ? AND usuario_id = ?", (cuenta_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def guardar_firma_correo(usuario_id: int, cuenta_id: int, firma_html: str | None, firma_en_nuevos: bool, firma_en_respuestas: bool) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE correo_cuentas SET firma_html = ?, firma_en_nuevos = ?, firma_en_respuestas = ?
               WHERE id = ? AND usuario_id = ?""",
            (firma_html, int(firma_en_nuevos), int(firma_en_respuestas), cuenta_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


# --- Carpetas IMAP (POP3 no tiene fila aquí, ver comentario del esquema) ------

def guardar_carpetas_correo(cuenta_id: int, carpetas: list[tuple[str, str]]) -> None:
    """`carpetas`: lista de (nombre, nombre_visible). Upsert — no borra
    carpetas que ya no aparezcan en el servidor, para no perder sus mensajes
    cacheados si es un fallo puntual de listado."""
    conn = get_connection()
    try:
        for nombre, nombre_visible in carpetas:
            conn.execute(
                """INSERT INTO correo_carpetas (cuenta_id, nombre, nombre_visible) VALUES (?, ?, ?)
                   ON CONFLICT (cuenta_id, nombre) DO UPDATE SET nombre_visible = excluded.nombre_visible""",
                (cuenta_id, nombre, nombre_visible),
            )
        conn.commit()
    finally:
        conn.close()


def listar_carpetas_correo(cuenta_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_carpetas WHERE cuenta_id = ? ORDER BY nombre_visible", (cuenta_id,)
        ).fetchall()
    finally:
        conn.close()


# --- Categorías de correo (propias de Guilda Work, no se sincronizan) --------

def crear_categoria_correo(usuario_id: int, nombre: str, color: str) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO correo_categorias (usuario_id, nombre, color, creada_en) VALUES (?, ?, ?, ?)",
            (usuario_id, nombre.strip(), color, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_categorias_correo(usuario_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_categorias WHERE usuario_id = ? ORDER BY nombre", (usuario_id,)
        ).fetchall()
    finally:
        conn.close()


def eliminar_categoria_correo(usuario_id: int, categoria_id: int) -> None:
    """Los mensajes que la tuvieran asignada se quedan sin categoría
    (ON DELETE SET NULL en el esquema)."""
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM correo_categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


def asignar_categoria_correo(mensaje_id: int, categoria_id: int | None) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE correo_mensajes SET categoria_id = ? WHERE id = ?", (categoria_id, mensaje_id))
        conn.commit()
    finally:
        conn.close()


# --- Remitentes de confianza (imágenes/adjuntos no se bloquean) --------------

def confiar_en_remitente(usuario_id: int, direccion: str) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO correo_remitentes_confiables (usuario_id, direccion, creada_en)
               VALUES (?, ?, ?)
               ON CONFLICT (usuario_id, direccion) DO NOTHING""",
            (usuario_id, direccion.strip().lower(), now_iso()),
        )
        conn.commit()
        fila = conn.execute(
            "SELECT id FROM correo_remitentes_confiables WHERE usuario_id = ? AND direccion = ?",
            (usuario_id, direccion.strip().lower()),
        ).fetchone()
        return fila["id"] if fila else cur.lastrowid
    finally:
        conn.close()


def listar_remitentes_confiables(usuario_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_remitentes_confiables WHERE usuario_id = ? ORDER BY direccion",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def eliminar_remitente_confiable(usuario_id: int, remitente_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM correo_remitentes_confiables WHERE id = ? AND usuario_id = ?",
            (remitente_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def es_remitente_confiable(usuario_id: int, direccion: str | None) -> bool:
    if not direccion:
        return False
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT 1 FROM correo_remitentes_confiables WHERE usuario_id = ? AND direccion = ?",
            (usuario_id, direccion.strip().lower()),
        ).fetchone()
        return fila is not None
    finally:
        conn.close()


# --- Reglas de categorización automática por remitente -----------------------

def crear_regla_categoria_correo(usuario_id: int, remitente_patron: str, categoria_id: int) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO correo_reglas_categoria (usuario_id, remitente_patron, categoria_id, creada_en)
               VALUES (?, ?, ?, ?)""",
            (usuario_id, remitente_patron.strip().lower(), categoria_id, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_reglas_categoria_correo(usuario_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT r.*, c.nombre AS categoria_nombre, c.color AS categoria_color
               FROM correo_reglas_categoria r
               JOIN correo_categorias c ON c.id = r.categoria_id
               WHERE r.usuario_id = ? ORDER BY r.remitente_patron""",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def eliminar_regla_categoria_correo(usuario_id: int, regla_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM correo_reglas_categoria WHERE id = ? AND usuario_id = ?", (regla_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


def categoria_id_por_remitente_correo(usuario_id: int, direccion: str | None) -> int | None:
    """Busca primero una regla de email exacto, luego una de dominio
    (`remitente_patron` empezando por "@")."""
    if not direccion:
        return None
    direccion = direccion.strip().lower()
    conn = get_connection()
    try:
        fila = conn.execute(
            """SELECT categoria_id FROM correo_reglas_categoria
               WHERE usuario_id = ? AND remitente_patron = ?""",
            (usuario_id, direccion),
        ).fetchone()
        if fila:
            return fila["categoria_id"]
        dominio = "@" + direccion.split("@", 1)[1] if "@" in direccion else None
        if dominio:
            fila = conn.execute(
                """SELECT categoria_id FROM correo_reglas_categoria
                   WHERE usuario_id = ? AND remitente_patron = ?""",
                (usuario_id, dominio),
            ).fetchone()
            if fila:
                return fila["categoria_id"]
        return None
    finally:
        conn.close()


# --- Destinatarios recientes (para autocompletar al redactar) ----------------

def registrar_destinatario_reciente(usuario_id: int, direccion: str, nombre_mostrado: str | None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO correo_destinatarios_recientes
               (usuario_id, direccion, nombre_mostrado, ultima_vez_en, veces_usado)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT (usuario_id, direccion) DO UPDATE SET
                   nombre_mostrado = excluded.nombre_mostrado,
                   ultima_vez_en = excluded.ultima_vez_en,
                   veces_usado = veces_usado + 1""",
            (usuario_id, direccion.strip().lower(), nombre_mostrado, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def buscar_destinatarios_recientes(usuario_id: int, q: str | None = None, limite: int = 8) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        if q:
            patron = f"%{q.strip().lower()}%"
            return conn.execute(
                """SELECT * FROM correo_destinatarios_recientes
                   WHERE usuario_id = ? AND (direccion LIKE ? OR LOWER(nombre_mostrado) LIKE ?)
                   ORDER BY veces_usado DESC, ultima_vez_en DESC LIMIT ?""",
                (usuario_id, patron, patron, limite),
            ).fetchall()
        return conn.execute(
            """SELECT * FROM correo_destinatarios_recientes WHERE usuario_id = ?
               ORDER BY veces_usado DESC, ultima_vez_en DESC LIMIT ?""",
            (usuario_id, limite),
        ).fetchall()
    finally:
        conn.close()


# --- Preferencias generales de Correo (una fila por usuario) ------------------

def obtener_preferencias_correo(usuario_id: int) -> sqlite3.Row:
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO correo_preferencias (usuario_id) VALUES (?)", (usuario_id,))
        conn.commit()
        return conn.execute(
            "SELECT * FROM correo_preferencias WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()
    finally:
        conn.close()


def guardar_preferencias_correo(usuario_id: int, densidad: str, marcar_leido_automatico: bool, limite_mensajes: int) -> None:
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO correo_preferencias (usuario_id) VALUES (?)", (usuario_id,))
        conn.execute(
            """UPDATE correo_preferencias
               SET densidad = ?, marcar_leido_automatico = ?, limite_mensajes = ? WHERE usuario_id = ?""",
            (densidad, int(marcar_leido_automatico), limite_mensajes, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def marcar_sincronizada_cuenta_correo(cuenta_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE correo_cuentas SET ultima_sincronizacion = ? WHERE id = ?",
            (now_iso(), cuenta_id),
        )
        conn.commit()
    finally:
        conn.close()


def uids_existentes_correo(cuenta_id: int, carpeta: str = "INBOX") -> set[str]:
    """UIDs ya descargados para esa cuenta/carpeta — usado por la
    sincronización para pedir al servidor solo los mensajes que faltan."""
    conn = get_connection()
    try:
        filas = conn.execute(
            "SELECT uid FROM correo_mensajes WHERE cuenta_id = ? AND carpeta = ?",
            (cuenta_id, carpeta),
        ).fetchall()
        return {f["uid"] for f in filas}
    finally:
        conn.close()


def guardar_mensaje_correo(
    cuenta_id: int, uid: str, asunto: str | None, remitente: str | None,
    destinatarios: str | None, fecha: str | None, cuerpo_texto: str | None,
    cuerpo_html: str | None, carpeta: str = "INBOX", message_id: str | None = None,
    cc: str | None = None,
) -> int | None:
    """Devuelve el id del mensaje (recién insertado, o el ya existente si
    `(cuenta_id, carpeta, uid)` ya estaba en caché) — para poder colgarle
    adjuntos justo después."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO correo_mensajes
               (cuenta_id, carpeta, uid, asunto, remitente, destinatarios,
                cc, fecha, cuerpo_texto, cuerpo_html, message_id, descargado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cuenta_id, carpeta, uid, asunto, remitente, destinatarios,
             cc, fecha, cuerpo_texto, cuerpo_html, message_id, now_iso()),
        )
        conn.commit()
        fila = conn.execute(
            "SELECT id FROM correo_mensajes WHERE cuenta_id = ? AND carpeta = ? AND uid = ?",
            (cuenta_id, carpeta, uid),
        ).fetchone()
        return fila["id"] if fila else None
    finally:
        conn.close()


def listar_mensajes_correo(
    cuenta_id: int, carpeta: str = "INBOX", solo_no_leidos: bool = False,
    texto: str | None = None, limite: int = 50, incluir_pospuestos: bool = False,
) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        cond = ["cuenta_id = ?", "carpeta = ?"]
        params: list = [cuenta_id, carpeta]
        if solo_no_leidos:
            cond.append("leido = 0")
        if texto:
            cond.append("(asunto LIKE ? OR remitente LIKE ?)")
            params.extend([f"%{texto}%", f"%{texto}%"])
        if not incluir_pospuestos:
            cond.append("(pospuesto_hasta IS NULL OR pospuesto_hasta <= ?)")
            params.append(now_iso())
        where = " AND ".join(cond)
        params.append(limite)
        return conn.execute(
            # "ORDER BY fecha DESC" basta: SQLite ya trata NULL como el valor
            # más pequeño, así que en DESC los mensajes sin fecha quedan al
            # final solos — no hace falta "(fecha IS NULL), fecha DESC" (esa
            # expresión extra impedía usar idx_correo_mensajes_cuenta_carpeta_fecha
            # para el propio ORDER BY, forzando un TEMP B-TREE en cada carga
            # de la bandeja).
            f"""SELECT * FROM correo_mensajes WHERE {where}
                ORDER BY fecha DESC LIMIT ?""",
            params,
        ).fetchall()
    finally:
        conn.close()


def obtener_mensaje_correo(mensaje_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM correo_mensajes WHERE id = ?", (mensaje_id,)).fetchone()
    finally:
        conn.close()


def mensaje_correo_pertenece_a_usuario(usuario_id: int, mensaje_id: int) -> bool:
    """Comprueba que un mensaje cuelga de una cuenta del usuario, antes de
    dejarle leer/modificar un `mensaje_id` que le podrían pasar por URL."""
    conn = get_connection()
    try:
        fila = conn.execute(
            """SELECT 1 FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id
               WHERE m.id = ? AND c.usuario_id = ?""",
            (mensaje_id, usuario_id),
        ).fetchone()
        return fila is not None
    finally:
        conn.close()


def guardar_adjuntos_correo(mensaje_id: int, adjuntos: list[dict]) -> None:
    """`adjuntos` es una lista de {"nombre", "tipo", "bytes"}, tal como los
    devuelve app.correo._cuerpos()."""
    conn = get_connection()
    try:
        for a in adjuntos:
            conn.execute(
                """INSERT INTO correo_adjuntos
                   (mensaje_id, nombre_archivo, tipo_mime, tamano_bytes, contenido, creado_en)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (mensaje_id, a["nombre"], a["tipo"], len(a["bytes"]), a["bytes"], now_iso()),
            )
        conn.commit()
    finally:
        conn.close()


def listar_adjuntos_correo(mensaje_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT id, mensaje_id, nombre_archivo, tipo_mime, tamano_bytes, creado_en "
            "FROM correo_adjuntos WHERE mensaje_id = ? ORDER BY id",
            (mensaje_id,),
        ).fetchall()
    finally:
        conn.close()


def obtener_adjunto_correo(adjunto_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM correo_adjuntos WHERE id = ?", (adjunto_id,)).fetchone()
    finally:
        conn.close()


def adjunto_correo_pertenece_a_usuario(usuario_id: int, adjunto_id: int) -> bool:
    conn = get_connection()
    try:
        fila = conn.execute(
            """SELECT 1 FROM correo_adjuntos a
               JOIN correo_mensajes m ON m.id = a.mensaje_id
               JOIN correo_cuentas c ON c.id = m.cuenta_id
               WHERE a.id = ? AND c.usuario_id = ?""",
            (adjunto_id, usuario_id),
        ).fetchone()
        return fila is not None
    finally:
        conn.close()


def marcar_leido_mensaje_correo(mensaje_id: int, leido: bool = True) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE correo_mensajes SET leido = ? WHERE id = ?", (int(leido), mensaje_id))
        conn.commit()
    finally:
        conn.close()


def destacar_mensaje_correo(mensaje_id: int, destacado: bool, fecha_aviso: str | None = None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE correo_mensajes SET destacado = ?, fecha_aviso = ? WHERE id = ?",
            (int(destacado), fecha_aviso if destacado else None, mensaje_id),
        )
        conn.commit()
    finally:
        conn.close()


def posponer_mensaje_correo(mensaje_id: int, hasta: str | None) -> None:
    """`hasta=None` quita el pospuesto (el mensaje vuelve a verse ya)."""
    conn = get_connection()
    try:
        conn.execute("UPDATE correo_mensajes SET pospuesto_hasta = ? WHERE id = ?", (hasta, mensaje_id))
        conn.commit()
    finally:
        conn.close()


def eliminar_mensaje_correo(mensaje_id: int) -> None:
    """Borra el mensaje de la caché local (no del servidor de correo). Si
    sigue en el buzón real, una futura sincronización volverá a descargarlo
    (su UID ya no está en la caché local) — borrarlo también en el servidor
    queda fuera de alcance de esta fase."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM correo_mensajes WHERE id = ?", (mensaje_id,))
        conn.commit()
    finally:
        conn.close()


def contar_no_leidos_correo(cuenta_id: int, carpeta: str = "INBOX") -> int:
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT COUNT(*) AS n FROM correo_mensajes WHERE cuenta_id = ? AND carpeta = ? AND leido = 0",
            (cuenta_id, carpeta),
        ).fetchone()
        return fila["n"]
    finally:
        conn.close()


def contar_no_leidos_total_correo(usuario_id: int) -> int:
    """Total de mensajes no leídos en TODAS las cuentas y carpetas de un
    usuario (para el badge de "correo nuevo" del rail de iconos)."""
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT COUNT(*) AS n FROM correo_mensajes m
               JOIN correo_cuentas c ON c.id = m.cuenta_id
               WHERE c.usuario_id = ? AND m.leido = 0""",
            (usuario_id,),
        ).fetchone()["n"]
    finally:
        conn.close()


# --- Papelera ----------------------------------------------------------------

def papelera(usuario_id: int) -> list[dict]:
    """Menús, tareas/eventos y notas que están en la papelera, más recientes primero."""
    conn = get_connection()
    try:
        filas = conn.execute(
            """
            SELECT * FROM (
                SELECT 'menu' AS origen, c.id AS id, c.nombre AS texto, NULL AS tipo,
                       NULL AS categoria_nombre, NULL AS categoria_color, c.papelera_en AS papelera_en
                FROM categorias c
                WHERE c.usuario_id = ? AND c.papelera_en IS NOT NULL

                UNION ALL

                SELECT 'tarea' AS origen, t.id AS id, t.nombre AS texto, t.tipo AS tipo,
                       c.nombre AS categoria_nombre, c.color AS categoria_color, t.papelera_en AS papelera_en
                FROM tareas t JOIN categorias c ON c.id = t.categoria_id
                WHERE t.usuario_id = ? AND t.papelera_en IS NOT NULL

                UNION ALL

                SELECT 'nota' AS origen, n.id AS id, n.texto AS texto, NULL AS tipo,
                       c.nombre AS categoria_nombre, c.color AS categoria_color, n.papelera_en AS papelera_en
                FROM notas n LEFT JOIN categorias c ON c.id = n.categoria_id
                WHERE n.usuario_id = ? AND n.papelera_en IS NOT NULL

                UNION ALL

                SELECT 'tarea_outlook' AS origen, tk.id AS id, tk.asunto AS texto, NULL AS tipo,
                       tk.categoria_outlook AS categoria_nombre, NULL AS categoria_color, tk.papelera_en AS papelera_en
                FROM tareas_outlook tk
                WHERE tk.usuario_id = ? AND tk.papelera_en IS NOT NULL
            )
            ORDER BY papelera_en DESC
            """,
            (usuario_id, usuario_id, usuario_id, usuario_id),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def vaciar_papelera_antigua(dias: int = 30) -> None:
    """Purga definitivamente (sin posibilidad de recuperar) lo que lleva en
    la papelera más de `dias` días, para TODOS los usuarios. Se llama al
    arrancar la app, igual que la copia de seguridad."""
    conn = get_connection()
    try:
        limite = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
        ids_categorias = [
            (r["id"], r["usuario_id"]) for r in conn.execute(
                "SELECT id, usuario_id FROM categorias WHERE papelera_en IS NOT NULL AND papelera_en < ?", (limite,)
            )
        ]
        ids_tareas = [
            (r["id"], r["usuario_id"]) for r in conn.execute(
                "SELECT id, usuario_id FROM tareas WHERE papelera_en IS NOT NULL AND papelera_en < ?", (limite,)
            )
        ]
        ids_notas = [
            (r["id"], r["usuario_id"]) for r in conn.execute(
                "SELECT id, usuario_id FROM notas WHERE papelera_en IS NOT NULL AND papelera_en < ?", (limite,)
            )
        ]
        ids_tareas_outlook = [
            (r["id"], r["usuario_id"]) for r in conn.execute(
                "SELECT id, usuario_id FROM tareas_outlook WHERE papelera_en IS NOT NULL AND papelera_en < ?", (limite,)
            )
        ]
    finally:
        conn.close()

    for nid, uid in ids_notas:
        eliminar_nota_definitivamente(uid, nid)
    for tid, uid in ids_tareas:
        eliminar_tarea_definitivamente(uid, tid)
    for cid, uid in ids_categorias:
        eliminar_categoria_definitivamente(uid, cid)
    for tid, uid in ids_tareas_outlook:
        eliminar_tarea_outlook_definitivamente(uid, tid)


# --- Asistente IA (OpenRouter): preferencias y conversación -------------------

def obtener_preferencias_ia(usuario_id: int) -> sqlite3.Row:
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO ia_preferencias (usuario_id) VALUES (?)", (usuario_id,))
        conn.commit()
        return conn.execute(
            "SELECT * FROM ia_preferencias WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()
    finally:
        conn.close()


def guardar_preferencias_ia(usuario_id: int, modelo: str, modo_autonomo: bool) -> None:
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO ia_preferencias (usuario_id) VALUES (?)", (usuario_id,))
        conn.execute(
            "UPDATE ia_preferencias SET modelo = ?, modo_autonomo = ? WHERE usuario_id = ?",
            (modelo, int(modo_autonomo), usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


# --- IA local (Ollama/LM Studio): recordar el último proveedor/modelo usado --

def obtener_preferencias_ia_local(usuario_id: int) -> sqlite3.Row:
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO ia_preferencias (usuario_id) VALUES (?)", (usuario_id,))
        conn.commit()
        return conn.execute(
            "SELECT * FROM ia_preferencias WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()
    finally:
        conn.close()


def guardar_preferencias_ia_local(usuario_id: int, proveedor: str, modelo: str) -> None:
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO ia_preferencias (usuario_id) VALUES (?)", (usuario_id,))
        conn.execute(
            "UPDATE ia_preferencias SET proveedor_local = ?, modelo_local = ? WHERE usuario_id = ?",
            (proveedor, modelo, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def listar_mensajes_ia(usuario_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM ia_mensajes WHERE usuario_id = ? ORDER BY id", (usuario_id,)
        ).fetchall()
    finally:
        conn.close()


def agregar_mensaje_ia(
    usuario_id: int,
    rol: str,
    contenido: str | None = None,
    tool_calls_json: str | None = None,
    tool_call_id: str | None = None,
    nombre_herramienta: str | None = None,
) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute(
            """INSERT INTO ia_mensajes
               (usuario_id, rol, contenido, tool_calls_json, tool_call_id, nombre_herramienta, creado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (usuario_id, rol, contenido, tool_calls_json, tool_call_id, nombre_herramienta, now_iso()),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def vaciar_mensajes_ia(usuario_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM ia_mensajes WHERE usuario_id = ?", (usuario_id,))
        conn.commit()
    finally:
        conn.close()
