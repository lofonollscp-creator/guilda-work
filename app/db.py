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
import json
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

-- Herramientas del catálogo (app/herramientas.py, por su `id` de texto)
-- ocultas para un tenant concreto. Ausencia de fila = visible (así una
-- herramienta nueva, o un tenant sin ninguna fila aquí, no pierde acceso
-- por accidente al desplegar esto) — nunca se guarda "visible=1" a
-- propósito, solo las excepciones.
CREATE TABLE IF NOT EXISTS tenants_herramientas_ocultas (
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    herramienta_id TEXT NOT NULL,
    UNIQUE (tenant_id, herramienta_id)
);

CREATE TABLE IF NOT EXISTS tokens_api (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    token_hash TEXT NOT NULL UNIQUE,
    nombre_dispositivo TEXT,
    creado_en TEXT NOT NULL,
    ultimo_uso_en TEXT
);

-- Solicitudes de contacto desde la landing pública (guildawork.com) — no
-- crea tenant ni usuario por sí sola: el alta sigue siendo manual desde el
-- backoffice (ver app/rutas_backoffice.py:crear_tenant/crear_usuario), esto
-- solo guarda el interés para que un admin lo procese.
CREATE TABLE IF NOT EXISTS leads_contacto (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    empresa TEXT,
    email TEXT NOT NULL,
    telefono TEXT,
    mensaje TEXT,
    creado_en TEXT NOT NULL,
    atendido INTEGER NOT NULL DEFAULT 0
);

-- Webhooks salientes (ver app/eventos.py). tenant_id NULL = modo
-- escritorio/usuario sin tenant (mismo criterio que otras tablas ya
-- nullable de este archivo) — se asocia al usuario que lo dio de alta
-- en ese caso. `secreto` se guarda en claro (no un hash, a diferencia
-- de tokens_api): hace falta releerlo para firmar cada entrega HMAC,
-- no solo compararlo una vez.
CREATE TABLE IF NOT EXISTS webhooks (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER REFERENCES tenants(id),
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    url TEXT NOT NULL,
    eventos TEXT NOT NULL,
    secreto TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    creado_en TEXT NOT NULL
);

-- Log de entregas — para que el admin pueda ver por qué un webhook
-- está fallando desde el backoffice, sin tener que mirar logs del
-- servidor. Se poda a las últimas N entradas por webhook (ver
-- app/eventos.py), no crece sin límite.
CREATE TABLE IF NOT EXISTS webhooks_entregas (
    id INTEGER PRIMARY KEY,
    webhook_id INTEGER NOT NULL REFERENCES webhooks(id),
    evento TEXT NOT NULL,
    estado_http INTEGER,
    intento_num INTEGER NOT NULL,
    entregado_en TEXT NOT NULL,
    error TEXT
);

-- UNIQUE por (usuario_id, nombre), NO solo por nombre -- antes era
-- "nombre TEXT NOT NULL UNIQUE" a secas (global, entre TODOS los
-- usuarios), así que dos usuarios que le pusieran el mismo nombre a un
-- menú acababan compartiendo la misma fila sin saberlo (encontrado y
-- reproducido en producción, revisión de lógica -- ver
-- _migrar_categorias_unique_por_usuario para instalaciones ya
-- existentes con el esquema viejo).
CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER,
    nombre TEXT NOT NULL,
    color TEXT,
    creada_en TEXT NOT NULL,
    papelera_en TEXT,
    orden INTEGER,
    UNIQUE (usuario_id, nombre)
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
-- UNIQUE por (usuario_id, nombre), no solo por nombre -- mismo bug que
-- categorias (revisión de lógica), aquí incluso peor: sin ninguna lógica
-- de "reutilizar si ya existe", así que el segundo usuario con el mismo
-- nombre de etiqueta de correo directamente reventaba con un
-- IntegrityError sin capturar (500 en crudo, reproducido en vivo).
CREATE TABLE IF NOT EXISTS correo_categorias (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER,
    nombre TEXT NOT NULL,
    color TEXT NOT NULL,
    creada_en TEXT NOT NULL,
    UNIQUE (usuario_id, nombre)
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

-- Tiquets de soporte interno (errores/sugerencias sobre la propia Guilda
-- Work) — a diferencia de notas/tareas/correo, es un tablero COMPARTIDO
-- entre todos los usuarios, no privado por usuario_id (ver app/rutas_tiquets.py).
-- AUTOINCREMENT para que el número mostrado (el propio id, "#N") nunca se
-- repita ni siquiera tras borrar un tiquet -- sin esto SQLite podría
-- reutilizar el id más alto libre.
CREATE TABLE IF NOT EXISTS tiquets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('error', 'sugerencia')),
    titulo TEXT NOT NULL,
    descripcion TEXT,
    estado TEXT NOT NULL CHECK (estado IN ('sin_revisar', 'en_revision', 'finalizado')) DEFAULT 'sin_revisar',
    creado_en TEXT NOT NULL,
    actualizado_en TEXT,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
);

-- Adjuntos de un tiquet (capturas de pantalla, PDF...) -- mismo diseño que
-- correo_adjuntos (BLOB en la propia base de datos, sin filesystem aparte
-- que gestionar). ON DELETE CASCADE: al borrar un tiquet desaparecen sus
-- adjuntos solos (get_connection() ya activa "PRAGMA foreign_keys = ON").
CREATE TABLE IF NOT EXISTS tiquets_adjuntos (
    id INTEGER PRIMARY KEY,
    tiquet_id INTEGER NOT NULL,
    nombre_archivo TEXT NOT NULL,
    tipo_mime TEXT NOT NULL,
    tamano_bytes INTEGER NOT NULL,
    contenido BLOB NOT NULL,
    creado_en TEXT NOT NULL,
    FOREIGN KEY (tiquet_id) REFERENCES tiquets(id) ON DELETE CASCADE
);

-- Fichaje de trabajadores (registro horario, art. 34.9 ET / RD-ley 8/2019).
-- Datos personales del trabajador que exige la normativa para identificarlo
-- ante una inspección -- fila única por usuario, igual que correo_preferencias.
CREATE TABLE IF NOT EXISTS fichaje_datos (
    usuario_id INTEGER PRIMARY KEY REFERENCES usuarios(id),
    nombre_completo TEXT,
    dni_nie TEXT,
    numero_afiliacion_ss TEXT,
    categoria_profesional TEXT,
    tipo_contrato TEXT,
    fecha_alta TEXT,
    jornada_semanal_horas REAL,
    convenio_colectivo TEXT,
    actualizado_en TEXT
);

-- El registro horario en sí. INSERT-only a propósito -- nunca hay UPDATE
-- ni DELETE sobre esta tabla (ni siquiera vía papelera): la norma exige
-- conservar el registro 4 años y que no se pueda manipular a posteriori
-- sin dejar rastro. Una corrección se hace con una fila NUEVA que
-- referencia a la original en `corrige_a`, nunca sobrescribiendo.
-- `tenant_id` se duplica aquí (no solo en usuarios) porque debe reflejar
-- el tenant al que pertenecía el trabajador EN EL MOMENTO del fichaje
-- -- un registro legal histórico no debe cambiar si más adelante se
-- reasigna a alguien de tenant.
CREATE TABLE IF NOT EXISTS fichajes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    tenant_id INTEGER REFERENCES tenants(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('entrada','pausa_inicio','pausa_fin','salida')),
    marca_tiempo TEXT NOT NULL,
    origen TEXT NOT NULL DEFAULT 'web',
    nota TEXT,
    corrige_a INTEGER REFERENCES fichajes(id),
    creado_por INTEGER NOT NULL REFERENCES usuarios(id),
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
CREATE INDEX IF NOT EXISTS idx_fichajes_usuario_marca ON fichajes(usuario_id, marca_tiempo);
CREATE INDEX IF NOT EXISTS idx_fichajes_tenant_marca ON fichajes(tenant_id, marca_tiempo);
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


def _migrar_categorias_unique_por_usuario(conn_ignorada: sqlite3.Connection) -> None:
    """`categorias.nombre` tenía UNIQUE global (sin usuario_id) -- dos
    usuarios con un menú del mismo nombre acababan compartiendo la
    misma fila sin saberlo (bug real, reproducido en producción: el
    segundo en crearlo recibía el id del primero en vez de uno propio,
    y ese menú no le aparecía ni en su propio listado). SQLite no deja
    tocar una UNIQUE con ALTER TABLE, así que se reconstruye la tabla
    la primera vez que se detecta el esquema antiguo -- se comprueba
    leyendo su propio SQL en sqlite_master, sin ninguna bandera aparte.
    Llamar DESPUÉS de que existan papelera_en/orden/favorito (ver
    llamadas a _asegurar_columna justo antes), para no perderlas al
    reconstruir. Sin duplicados posibles que choquen con la nueva
    UNIQUE(usuario_id, nombre): la UNIQUE(nombre) vieja ya impedía que
    hubiera dos filas con el mismo nombre, así que a fortiori tampoco
    hay dos con el mismo (usuario_id, nombre).

    Usa su PROPIA conexión (ignora la que recibe) con
    `PRAGMA foreign_keys = OFF`, siguiendo el procedimiento de 12 pasos
    documentado por SQLite para tablas con FOREIGN KEY entrantes desde
    otras tablas (notas/tareas/tareas_outlook referencian categorias) --
    con las claves foráneas activas (lo normal en get_connection()),
    renombrar la tabla vieja fuera y crear una nueva con el mismo nombre
    hace que SQLite reescriba las FK de las tablas hijas para que sigan
    apuntando al nombre viejo (¡no al nuevo!), y el DROP final de la
    tabla vieja revienta con FOREIGN KEY constraint failed -- exactamente
    lo que pasó la primera vez que se escribió esta función, detectado
    y corregido a mano en el propio despliegue antes de arreglarla aquí.
    El orden correcto es crear la tabla nueva bajo un nombre aparte,
    copiar los datos, BORRAR la vieja (con foreign_keys=OFF esto no
    reescribe nada en las hijas) y solo entonces renombrar la nueva al
    nombre definitivo -- así las hijas, que nunca dejan de decir
    "REFERENCES categorias(...)", vuelven a apuntar a una tabla real en
    cuanto esta reaparece con ese nombre, sin necesidad de tocarlas."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        definicion = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='categorias'"
        ).fetchone()
        if definicion is None or "UNIQUE (usuario_id, nombre)" in definicion["sql"]:
            return
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """CREATE TABLE categorias_nueva (
                   id INTEGER PRIMARY KEY,
                   usuario_id INTEGER,
                   nombre TEXT NOT NULL,
                   color TEXT,
                   creada_en TEXT NOT NULL,
                   papelera_en TEXT,
                   orden INTEGER,
                   favorito INTEGER NOT NULL DEFAULT 0,
                   UNIQUE (usuario_id, nombre)
               )"""
        )
        conn.execute(
            """INSERT INTO categorias_nueva (id, usuario_id, nombre, color, creada_en, papelera_en, orden, favorito)
               SELECT id, usuario_id, nombre, color, creada_en, papelera_en, orden, favorito
               FROM categorias"""
        )
        conn.execute("DROP TABLE categorias")
        conn.execute("ALTER TABLE categorias_nueva RENAME TO categorias")
        violaciones = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violaciones:
            conn.rollback()
            raise RuntimeError(f"Migración de categorias abortada: foreign_key_check encontró {violaciones}")
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()


def _migrar_correo_categorias_unique_por_usuario(conn_ignorada: sqlite3.Connection) -> None:
    """Mismo bug, mismo arreglo que _migrar_categorias_unique_por_usuario
    (ver su docstring para el porqué del procedimiento exacto) -- aquí
    con correo_mensajes.categoria_id (ON DELETE SET NULL) y
    correo_reglas_categoria.categoria_id (ON DELETE CASCADE) como tablas
    hijas en vez de notas/tareas/tareas_outlook."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        definicion = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='correo_categorias'"
        ).fetchone()
        if definicion is None or "UNIQUE (usuario_id, nombre)" in definicion["sql"]:
            return
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """CREATE TABLE correo_categorias_nueva (
                   id INTEGER PRIMARY KEY,
                   usuario_id INTEGER,
                   nombre TEXT NOT NULL,
                   color TEXT NOT NULL,
                   creada_en TEXT NOT NULL,
                   UNIQUE (usuario_id, nombre)
               )"""
        )
        conn.execute(
            """INSERT INTO correo_categorias_nueva (id, usuario_id, nombre, color, creada_en)
               SELECT id, usuario_id, nombre, color, creada_en FROM correo_categorias"""
        )
        conn.execute("DROP TABLE correo_categorias")
        conn.execute("ALTER TABLE correo_categorias_nueva RENAME TO correo_categorias")
        violaciones = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violaciones:
            conn.rollback()
            raise RuntimeError(f"Migración de correo_categorias abortada: foreign_key_check encontró {violaciones}")
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        _asegurar_columna(conn, "categorias", "papelera_en", "TEXT")
        _asegurar_columna(conn, "tareas", "papelera_en", "TEXT")
        _asegurar_columna(conn, "notas", "papelera_en", "TEXT")
        _asegurar_columna(conn, "categorias", "orden", "INTEGER")
        _asegurar_columna(conn, "categorias", "favorito", "INTEGER NOT NULL DEFAULT 0")
        _migrar_categorias_unique_por_usuario(conn)
        _migrar_correo_categorias_unique_por_usuario(conn)
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

        # Fichaje (registro horario): quien tiene este flag administra el
        # fichaje SOLO de su propio tenant (usuarios.tenant_id) -- distinto
        # de rol='admin' (superadmin global de todo el backoffice, ver
        # app/auth.py:admin_required). Lo asigna un superadmin desde el
        # backoffice, igual que hacer_admin/quitar_admin.
        _asegurar_columna(conn, "usuarios", "gestor_fichajes", "INTEGER NOT NULL DEFAULT 0")

        # Identificación de empresa (CIF/dirección fiscal), exigida junto a
        # la del trabajador en cualquier registro horario que se presente
        # a una inspección -- aparece en la cabecera de los export CSV/PDF.
        _asegurar_columna(conn, "tenants", "cif", "TEXT")
        _asegurar_columna(conn, "tenants", "direccion_fiscal", "TEXT")

        # FacturaScripts (Fase facturación): a diferencia de EspoCRM/
        # Nextcloud (una instancia compartida), cada tenant tiene su
        # propia instancia física — estas columnas guardan cómo llegar a
        # la suya. Nulas hasta que app/facturascripts.py:aprovisionar_tenant()
        # las rellena; facturascripts_api_key queda nula más tiempo
        # todavía, es un paso manual aparte (ver HOSTING.md 8.21).
        _asegurar_columna(conn, "tenants", "facturascripts_url", "TEXT")
        _asegurar_columna(conn, "tenants", "facturascripts_admin_user", "TEXT")
        _asegurar_columna(conn, "tenants", "facturascripts_admin_pass", "TEXT")
        _asegurar_columna(conn, "tenants", "facturascripts_api_key", "TEXT")

        # Documenso (firma electrónica): a diferencia de FacturaScripts,
        # aquí la instancia SÍ es compartida (una URL global, ver
        # HERRAMIENTA_DOCUMENSO_URL) — no hace falta guardar URL/usuario
        # por tenant, solo el token de API generado a mano dentro del
        # Equipo de ese tenant (verificado en vivo que no hay API para
        # crear Equipos/invitar miembros, ver HOSTING.md). Ese token es
        # lo único que hace falta para que el aislamiento entre tenants
        # funcione de verdad al llamar a la API de documentos.
        _asegurar_columna(conn, "tenants", "documenso_api_key", "TEXT")

        # Paperless-ngx (gestión documental/OCR): instancia compartida,
        # igual que Documenso, pero aquí SÍ hay API real de Usuarios y
        # Grupos (verificado en el código fuente, ver app/paperless.py)
        # — el aprovisionamiento es 100% automático, sin ningún paso
        # manual. Guarda el Grupo y el usuario de servicio creados para
        # ese tenant, y su token de API ya generado.
        _asegurar_columna(conn, "tenants", "paperless_group_id", "INTEGER")
        _asegurar_columna(conn, "tenants", "paperless_user_id", "INTEGER")
        _asegurar_columna(conn, "tenants", "paperless_api_key", "TEXT")

        # Baserow (hojas de cálculo tipo base de datos): instancia
        # compartida. A diferencia de Paperless-ngx, aquí NO hay un
        # usuario de servicio propio — el token de base de datos de
        # Baserow queda ligado directamente al Workspace, no a ningún
        # usuario (ver app/baserow.py) — solo hace falta guardar el
        # Workspace y su token.
        _asegurar_columna(conn, "tenants", "baserow_workspace_id", "INTEGER")
        _asegurar_columna(conn, "tenants", "baserow_api_key", "TEXT")

        # Cal.diy (reserva de citas): instancia compartida, igual que
        # Documenso/Paperless-ngx/Baserow (no una física por tenant como
        # FacturaScripts — Cal.diy es una app Next.js con la URL pública
        # fijada en tiempo de compilación, no de ejecución, así que un
        # contenedor por tenant no es viable). El aislamiento aquí es a
        # nivel de usuario individual (Cal.diy no tiene Equipos/SSO en su
        # edición libre, ver app/calcom.py) — un usuario de servicio de
        # Cal.diy por tenant, con su propio API Key generado a mano desde
        # su cuenta (paso manual, igual que facturascripts_api_key).
        # calcom_email guarda el identificador real (el endpoint de alta
        # de Cal.diy no devuelve un id numérico, solo confirma la
        # creación — verificado leyendo su código fuente real, ver
        # app/calcom.py).
        _asegurar_columna(conn, "tenants", "calcom_email", "TEXT")
        _asegurar_columna(conn, "tenants", "calcom_admin_pass", "TEXT")
        _asegurar_columna(conn, "tenants", "calcom_api_key", "TEXT")

        # Listmonk (newsletter/envíos masivos): instancia compartida.
        # Verificado en vivo (contenedor real) que el aislamiento por
        # lista es real, aplicado en el propio backend, no una
        # convención de UI (ver app/listmonk.py) — cada tenant tiene su
        # propia Lista + Rol de lista + usuario de servicio tipo "api",
        # y el token viaja en la propia respuesta de creación: sin
        # ningún paso manual, a diferencia de FacturaScripts/Documenso/
        # Cal.diy.
        _asegurar_columna(conn, "tenants", "listmonk_list_id", "INTEGER")
        _asegurar_columna(conn, "tenants", "listmonk_list_role_id", "INTEGER")
        _asegurar_columna(conn, "tenants", "listmonk_api_key", "TEXT")

        # Stalwart (correo propio, backend alternativo con mejor API para
        # MCP que el cliente IMAP genérico de app/correo.py): instancia
        # compartida. Verificado en vivo (contenedor real, sin licencia
        # Enterprise) que el aislamiento por Tenant/Domain/Account es
        # real y aplicado por el propio servidor a nivel de accountId
        # JMAP (una llamada con el accountId de otro tenant devuelve un
        # 403 "forbidden" real, no un filtro de cliente) — ver
        # app/stalwart.py. Los ids de Stalwart son cadenas cortas
        # (base32), no numéricas, de ahí TEXT. Cada tenant usa su propio
        # dominio real (decisión del usuario, no un subdominio de
        # guilda.cat), por eso stalwart_domain_name se guarda tal cual se
        # introduce al aprovisionar, no se deriva de ningún otro campo.
        # El API Key se genera 100% automático (x:ApiKey/set devuelve el
        # secreto en la propia respuesta), sin ningún paso manual — igual
        # que Listmonk/Paperless-ngx/Baserow.
        _asegurar_columna(conn, "tenants", "stalwart_tenant_id", "TEXT")
        _asegurar_columna(conn, "tenants", "stalwart_domain_id", "TEXT")
        _asegurar_columna(conn, "tenants", "stalwart_domain_name", "TEXT")
        _asegurar_columna(conn, "tenants", "stalwart_account_id", "TEXT")
        _asegurar_columna(conn, "tenants", "stalwart_api_key", "TEXT")

        # ntfy (notificaciones push): topic + token generados por
        # app/ntfy.py:aprovisionar_tenant() — el token no se puede volver
        # a leer una vez generado (mismo criterio que stalwart_api_key).
        _asegurar_columna(conn, "tenants", "ntfy_topic", "TEXT")
        _asegurar_columna(conn, "tenants", "ntfy_token", "TEXT")

        # Umami (analítica web, MIT): Team + sitio (website) creados por
        # app/umami.py:aprovisionar_tenant() — 100% automático. Los ids
        # de Umami son UUID (cadenas), no numéricos, de ahí TEXT — mismo
        # criterio que los ids de Stalwart.
        _asegurar_columna(conn, "tenants", "umami_team_id", "TEXT")
        _asegurar_columna(conn, "tenants", "umami_website_id", "TEXT")

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

        # Relación opcional con un menú (categorias) para las Tareas Outlook
        # — mismo patrón ya usado en correo_mensajes.categoria_id más arriba.
        _asegurar_columna(conn, "tareas_outlook", "categoria_id", "INTEGER REFERENCES categorias(id)")

        # Idempotencia para la cola offline de la app móvil (fichaje y notas
        # creados sin cobertura, sincronizados al recuperar conexión): un
        # cliente_uuid repetido en un reintento no debe duplicar la fila.
        # ALTER TABLE de SQLite no admite añadir UNIQUE directamente, así que
        # la columna se añade normal y la unicidad se fuerza con un índice
        # parcial aparte (ignora NULL, o sea el resto de orígenes que no
        # mandan cliente_uuid).
        _asegurar_columna(conn, "fichajes", "cliente_uuid", "TEXT")
        _asegurar_columna(conn, "notas", "cliente_uuid", "TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_fichajes_cliente_uuid ON fichajes(cliente_uuid) WHERE cliente_uuid IS NOT NULL")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_notas_cliente_uuid ON notas(cliente_uuid) WHERE cliente_uuid IS NOT NULL")

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


def es_gestor_fichajes(usuario_id: int) -> bool:
    usuario = obtener_usuario(usuario_id)
    return usuario is not None and bool(usuario["gestor_fichajes"])


def asignar_gestor_fichajes(usuario_id: int, valor: bool) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE usuarios SET gestor_fichajes = ? WHERE id = ?", (int(valor), usuario_id))
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
        conn.execute("DELETE FROM tenants_herramientas_ocultas WHERE tenant_id = ?", (tenant_id,))
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


# --- Visibilidad de herramientas por tenant ----------------------------------

def ocultar_herramienta(tenant_id: int, herramienta_id: str) -> None:
    """Idempotente: ocultar dos veces la misma herramienta no falla."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO tenants_herramientas_ocultas (tenant_id, herramienta_id) VALUES (?, ?)",
            (tenant_id, herramienta_id),
        )
        conn.commit()
    finally:
        conn.close()


def mostrar_herramienta(tenant_id: int, herramienta_id: str) -> None:
    """Idempotente: quitar la ocultación de una herramienta ya visible no falla."""
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM tenants_herramientas_ocultas WHERE tenant_id = ? AND herramienta_id = ?",
            (tenant_id, herramienta_id),
        )
        conn.commit()
    finally:
        conn.close()


def herramientas_ocultas_de_tenant(tenant_id: int) -> set[str]:
    conn = get_connection()
    try:
        filas = conn.execute(
            "SELECT herramienta_id FROM tenants_herramientas_ocultas WHERE tenant_id = ?",
            (tenant_id,),
        ).fetchall()
        return {f["herramienta_id"] for f in filas}
    finally:
        conn.close()


def guardar_facturascripts(tenant_id: int, url: str, admin_user: str, admin_pass: str) -> None:
    """Guarda cómo llegar a la instancia de FacturaScripts recién
    aprovisionada de un tenant — ver app/facturascripts.py:aprovisionar_tenant."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET facturascripts_url = ?, facturascripts_admin_user = ?, "
            "facturascripts_admin_pass = ? WHERE id = ?",
            (url, admin_user, admin_pass, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_facturascripts_api_key(tenant_id: int, api_key: str) -> None:
    """La API Key se genera a mano dentro de cada instancia (paso manual,
    ver HOSTING.md 8.21) — esto solo la guarda una vez que el admin la
    pega en el backoffice."""
    conn = get_connection()
    try:
        conn.execute("UPDATE tenants SET facturascripts_api_key = ? WHERE id = ?", (api_key, tenant_id))
        conn.commit()
    finally:
        conn.close()


def guardar_documenso_api_key(tenant_id: int, api_key: str) -> None:
    """El token se genera a mano dentro del Equipo de Documenso de ese
    tenant (paso manual, ver HOSTING.md) — esto solo lo guarda una vez
    que el admin lo pega en el backoffice."""
    conn = get_connection()
    try:
        conn.execute("UPDATE tenants SET documenso_api_key = ? WHERE id = ?", (api_key, tenant_id))
        conn.commit()
    finally:
        conn.close()


def guardar_paperless(tenant_id: int, group_id: int, user_id: int, api_key: str) -> None:
    """A diferencia de facturascripts/documenso, aquí no hay ningún paso
    manual: app/paperless.py:aprovisionar_tenant() crea el Grupo, el
    usuario de servicio y su token por API, esto solo los guarda."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET paperless_group_id = ?, paperless_user_id = ?, paperless_api_key = ? WHERE id = ?",
            (group_id, user_id, api_key, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_baserow(tenant_id: int, workspace_id: int, api_key: str) -> None:
    """Igual que guardar_paperless: sin pasos manuales,
    app/baserow.py:aprovisionar_tenant() crea el Workspace y su token
    por API, esto solo los guarda."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET baserow_workspace_id = ?, baserow_api_key = ? WHERE id = ?",
            (workspace_id, api_key, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_calcom(tenant_id: int, email: str, admin_pass: str) -> None:
    """Guarda el usuario de servicio de Cal.diy recién creado para un
    tenant — ver app/calcom.py:aprovisionar_tenant. admin_pass se enseña
    una sola vez en el backoffice, igual que facturascripts_admin_pass."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET calcom_email = ?, calcom_admin_pass = ? WHERE id = ?",
            (email, admin_pass, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_calcom_api_key(tenant_id: int, api_key: str) -> None:
    """La API Key se genera a mano desde la propia cuenta de servicio
    (paso manual, ver HOSTING.md 8.25) — esto solo la guarda una vez que
    el admin la pega en el backoffice."""
    conn = get_connection()
    try:
        conn.execute("UPDATE tenants SET calcom_api_key = ? WHERE id = ?", (api_key, tenant_id))
        conn.commit()
    finally:
        conn.close()


def guardar_listmonk(tenant_id: int, list_id: int, list_role_id: int, api_key: str) -> None:
    """Igual que guardar_paperless: sin pasos manuales,
    app/listmonk.py:aprovisionar_tenant() crea la Lista, el Rol de lista
    y el usuario de servicio por API, esto solo los guarda."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET listmonk_list_id = ?, listmonk_list_role_id = ?, listmonk_api_key = ? WHERE id = ?",
            (list_id, list_role_id, api_key, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_stalwart(
    tenant_id: int,
    stalwart_tenant_id: str,
    domain_id: str,
    domain_name: str,
    account_id: str,
    api_key: str,
) -> None:
    """Igual que guardar_listmonk: sin pasos manuales,
    app/stalwart.py:aprovisionar_tenant() crea el Tenant, el Domain
    (con el dominio propio real del cliente), la Account y el ApiKey por
    API, esto solo los guarda."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET stalwart_tenant_id = ?, stalwart_domain_id = ?, "
            "stalwart_domain_name = ?, stalwart_account_id = ?, stalwart_api_key = ? "
            "WHERE id = ?",
            (stalwart_tenant_id, domain_id, domain_name, account_id, api_key, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_ntfy(tenant_id: int, topic: str, token: str) -> None:
    """Igual que guardar_stalwart: sin pasos manuales,
    app/ntfy.py:aprovisionar_tenant() crea el usuario+ACL+token, esto
    solo los guarda."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET ntfy_topic = ?, ntfy_token = ? WHERE id = ?",
            (topic, token, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_umami(tenant_id: int, team_id: str, website_id: str) -> None:
    """Igual que guardar_ntfy: sin pasos manuales,
    app/umami.py:aprovisionar_tenant() crea el Team+sitio, esto solo los
    guarda."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET umami_team_id = ?, umami_website_id = ? WHERE id = ?",
            (team_id, website_id, tenant_id),
        )
        conn.commit()
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


def guardar_datos_tenant(tenant_id: int, cif: str | None, direccion_fiscal: str | None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET cif = ?, direccion_fiscal = ? WHERE id = ?",
            (cif or None, direccion_fiscal or None, tenant_id),
        )
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


TOKEN_API_DIAS_INACTIVIDAD = 90


def usuario_id_por_token(token: str) -> int | None:
    """None si el token no existe, o si lleva TOKEN_API_DIAS_INACTIVIDAD días
    sin usarse (se borra en el momento, no hace falta una tarea periódica
    aparte: con que se compruebe en cada uso es suficiente para un catálogo
    de tokens que no es previsible que crezca mucho)."""
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT usuario_id, creado_en, ultimo_uso_en FROM tokens_api WHERE token_hash = ?",
            (_hash_token(token),),
        ).fetchone()
        if fila is None:
            return None
        ultima_actividad = fila["ultimo_uso_en"] or fila["creado_en"]
        limite = (datetime.now() - timedelta(days=TOKEN_API_DIAS_INACTIVIDAD)).isoformat(timespec="seconds")
        if ultima_actividad < limite:
            conn.execute("DELETE FROM tokens_api WHERE token_hash = ?", (_hash_token(token),))
            conn.commit()
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


def listar_tokens_api(usuario_id: int):
    """Dispositivos móviles con sesión activa de este usuario (para la
    pantalla "Mis dispositivos" y, con verificación de tenant en la propia
    ruta, para que un admin revoque los de un compañero de tenant) — nunca
    expone el token ni su hash, solo lo necesario para reconocerlo y
    decidir si revocarlo."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT id, nombre_dispositivo, creado_en, ultimo_uso_en FROM tokens_api "
            "WHERE usuario_id = ? ORDER BY COALESCE(ultimo_uso_en, creado_en) DESC",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def revocar_token_api_por_id(usuario_id: int, token_id: int) -> bool:
    """Revoca por id en vez de por token (la web nunca tiene el token en
    claro, solo el móvil lo guarda). Exige usuario_id para que un usuario
    no pueda revocar el token de otro solo adivinando su id — quien llame
    a esto con el id de un compañero de tenant debe haber verificado antes
    que puede administrar sus dispositivos (ver backoffice)."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM tokens_api WHERE id = ? AND usuario_id = ?", (token_id, usuario_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def crear_lead_contacto(
    nombre: str, email: str, empresa: str | None = None,
    telefono: str | None = None, mensaje: str | None = None,
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO leads_contacto (nombre, empresa, email, telefono, mensaje, creado_en) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (nombre, empresa, email, telefono, mensaje, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_leads_contacto():
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM leads_contacto ORDER BY atendido ASC, creado_en DESC"
        ).fetchall()
    finally:
        conn.close()


def marcar_lead_atendido(lead_id: int, atendido: bool) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE leads_contacto SET atendido = ? WHERE id = ?", (1 if atendido else 0, lead_id))
        conn.commit()
    finally:
        conn.close()


# --- Webhooks (ver app/eventos.py) --------------------------------------

_MAX_ENTREGAS_POR_WEBHOOK = 50


def crear_webhook(usuario_id: int, tenant_id: int | None, url: str, eventos: list[str]) -> dict:
    """`eventos` es una lista de nombres (ver app/eventos.py:EVENTOS) —
    se guarda como JSON, no una tabla aparte: no hace falta consultarlos
    por separado, siempre se leen todos juntos para un webhook dado."""
    secreto = secrets.token_urlsafe(32)
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO webhooks (tenant_id, usuario_id, url, eventos, secreto, creado_en) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tenant_id, usuario_id, url, json.dumps(eventos), secreto, now_iso()),
        )
        conn.commit()
        return dict(obtener_webhook(cursor.lastrowid))
    finally:
        conn.close()


def obtener_webhook(webhook_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM webhooks WHERE id = ?", (webhook_id,)).fetchone()
    finally:
        conn.close()


def listar_webhooks(tenant_id: int | None) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        if tenant_id is None:
            return conn.execute(
                "SELECT * FROM webhooks WHERE tenant_id IS NULL ORDER BY creado_en DESC"
            ).fetchall()
        return conn.execute(
            "SELECT * FROM webhooks WHERE tenant_id = ? ORDER BY creado_en DESC", (tenant_id,)
        ).fetchall()
    finally:
        conn.close()


def borrar_webhook(webhook_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM webhooks_entregas WHERE webhook_id = ?", (webhook_id,))
        conn.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
        conn.commit()
    finally:
        conn.close()


def webhooks_para_evento(evento: str, tenant_id: int | None) -> list[sqlite3.Row]:
    """Webhooks activos de este tenant (o del ámbito local si `tenant_id`
    es None) suscritos a `evento` — el filtro por evento se hace en
    Python (sobre `eventos` como JSON), no en SQL: la tabla no está
    pensada para volúmenes altos de webhooks por tenant."""
    candidatos = listar_webhooks(tenant_id)
    return [w for w in candidatos if w["activo"] and evento in json.loads(w["eventos"])]


def registrar_entrega_webhook(
    webhook_id: int, evento: str, estado_http: int | None, intento_num: int, error: str | None = None
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO webhooks_entregas (webhook_id, evento, estado_http, intento_num, entregado_en, error) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (webhook_id, evento, estado_http, intento_num, now_iso(), error),
        )
        # Poda: solo las últimas _MAX_ENTREGAS_POR_WEBHOOK por webhook —
        # el log de entregas es para depurar, no un histórico permanente.
        conn.execute(
            "DELETE FROM webhooks_entregas WHERE webhook_id = ? AND id NOT IN ("
            "  SELECT id FROM webhooks_entregas WHERE webhook_id = ? "
            "  ORDER BY id DESC LIMIT ?"
            ")",
            (webhook_id, webhook_id, _MAX_ENTREGAS_POR_WEBHOOK),
        )
        conn.commit()
    finally:
        conn.close()


def entregas_de_webhook(webhook_id: int, limite: int = 20) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM webhooks_entregas WHERE webhook_id = ? ORDER BY id DESC LIMIT ?",
            (webhook_id, limite),
        ).fetchall()
    finally:
        conn.close()


# --- Categorías --------------------------------------------------------

def crear_categoria(usuario_id: int, nombre: str, color: str | None = None) -> int:
    """Crea un menú, o reutiliza uno existente del MISMO usuario con el
    mismo nombre.

    `nombre` tiene una restricción UNIQUE por (usuario_id, nombre) en la
    tabla, y esa restricción no distingue entre menús activos y en la
    papelera — así que sin este chequeo, crear un menú con el mismo
    nombre que uno propio ya borrado (pero todavía en la papelera)
    reventaría con un IntegrityError. Si el que existe está en la
    papelera, se restaura en vez de fallar.

    El filtro `usuario_id = ?` de aquí abajo es imprescindible: sin él,
    dos usuarios distintos con un menú de igual nombre acababan
    compartiendo la misma fila sin saberlo (bug real, corregido en la
    revisión de lógica — ver también _migrar_categorias_unique_por_usuario).
    """
    nombre = nombre.strip()
    conn = get_connection()
    try:
        existente = conn.execute(
            "SELECT id, papelera_en FROM categorias WHERE nombre = ? AND usuario_id = ?", (nombre, usuario_id)
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


def _categoria_id_propio(conn: sqlite3.Connection, usuario_id: int, categoria_id: int | None) -> int | None:
    """Defensa en profundidad: ningún punto que recibe un categoria_id ya
    numérico (formulario manipulado a mano, o la tool de MCP cuando se le
    pasa el id directamente en vez del nombre) comprobaba que esa
    categoría fuera de verdad del usuario que la usa -- con la UNIQUE
    global de antes eso ya no hacía falta que colisionara por nombre
    para pasar desapercibido (revisión de lógica). Si no es suya, se
    trata como si no se hubiera indicado ninguna (mismo criterio
    permisivo que el resto de validaciones de esta app: se degrada en
    silencio, no revienta la petición entera)."""
    if categoria_id is None:
        return None
    fila = conn.execute(
        "SELECT 1 FROM categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id)
    ).fetchone()
    return categoria_id if fila is not None else None


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
        # categoria_id es NOT NULL en esta tabla (a diferencia de notas/
        # tareas_outlook, aquí el menú es obligatorio) -- así que si no es
        # del usuario no se puede degradar a None como en el resto, hay
        # que rechazar la petición entera (defensa en profundidad: en uso
        # normal el <select> del formulario ya solo ofrece menús propios).
        if _categoria_id_propio(conn, usuario_id, categoria_id) is None:
            raise ValueError(f"La categoría/menú {categoria_id} no existe o no es tuya.")
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
        tarea_id = cur.lastrowid
    finally:
        conn.close()
    _reindexar_tarea(usuario_id, tarea_id)
    return tarea_id


def _reindexar_tarea(usuario_id: int, tarea_id: int) -> None:
    """Mismo criterio que _reindexar_nota (ver más arriba) — falla en
    silencio, es una mejora de UX, no debe romper el registro de
    actividad en sí."""
    from . import busqueda
    try:
        tarea = obtener_tarea(usuario_id, tarea_id)
        if tarea is not None:
            busqueda.indexar_tarea(dict(tarea))
    except busqueda.ErrorBusqueda:
        pass


def _quitar_tarea_del_indice(tarea_id: int) -> None:
    from . import busqueda
    try:
        busqueda.eliminar_del_indice("tarea", tarea_id)
    except busqueda.ErrorBusqueda:
        pass


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
            "SELECT inicio_en, estado, nombre FROM tareas WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)
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
        duracion = max(int((datetime.fromisoformat(fin) - inicio).total_seconds()) - segundos_pausados, 0)
        conn.execute(
            "UPDATE tareas SET estado = 'finalizada', fin_en = ?, duracion_segundos = ? WHERE id = ?",
            (fin, duracion, tarea_id),
        )
        conn.commit()
    finally:
        conn.close()
    _emitir_evento_tarea_finalizada(usuario_id, tarea_id, row["nombre"], duracion)


def _emitir_evento_tarea_finalizada(usuario_id: int, tarea_id: int, nombre: str, duracion_segundos: int) -> None:
    """Segunda excepción documentada (junto a busqueda) a "db.py no
    depende de otros app/*.py": un webhook es, por naturaleza, un
    efecto secundario de la escritura, no una operación de negocio más
    — mismo criterio ya aplicado a la indexación de búsqueda. Import
    perezoso para evitar cualquier ciclo, aunque hoy app/eventos.py
    solo importa db.py, no al revés."""
    from . import eventos
    try:
        tenant = tenant_de_usuario(usuario_id)
        eventos.emitir(
            "tarea.finalizada", tenant["id"] if tenant else None,
            {"tarea_id": tarea_id, "nombre": nombre, "duracion_segundos": duracion_segundos},
        )
    except Exception:
        pass  # un fallo al emitir el evento no debe afectar a la tarea ya finalizada


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
    _reindexar_tarea(usuario_id, tarea_id)


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
    _quitar_tarea_del_indice(tarea_id)


def restaurar_tarea(usuario_id: int, tarea_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tareas SET papelera_en = NULL WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()
    _reindexar_tarea(usuario_id, tarea_id)


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
    _quitar_tarea_del_indice(tarea_id)


# --- Notas ---------------------------------------------------------------

def crear_nota(
    usuario_id: int, texto: str, categoria_id: int | None = None, tarea_id: int | None = None,
    creada_en: str | None = None, cliente_uuid: str | None = None,
) -> int:
    """`creada_en`/`cliente_uuid`: igual que en `fichar()`, para la cola
    offline de la app móvil -- conservan la hora real de creación y evitan
    duplicar la nota si se reintenta la sincronización."""
    conn = get_connection()
    try:
        if cliente_uuid is not None:
            existente = conn.execute("SELECT id FROM notas WHERE cliente_uuid = ?", (cliente_uuid,)).fetchone()
            if existente is not None:
                return existente["id"]
        # Aquí categoria_id sí es opcional -- si no es del usuario, se
        # degrada a "sin menú" en vez de rechazar la nota entera (ver
        # _categoria_id_propio).
        categoria_id = _categoria_id_propio(conn, usuario_id, categoria_id)
        ahora = now_iso()
        if creada_en is not None and creada_en > ahora:
            raise ValueError("La fecha de creación de la nota no puede ser futura.")
        cur = conn.execute(
            "INSERT INTO notas (usuario_id, texto, categoria_id, tarea_id, creada_en, cliente_uuid) VALUES (?, ?, ?, ?, ?, ?)",
            (usuario_id, texto.strip(), categoria_id, tarea_id, creada_en or ahora, cliente_uuid),
        )
        conn.commit()
        nota_id = cur.lastrowid
    finally:
        conn.close()
    _reindexar_nota(usuario_id, nota_id)
    _emitir_evento_nota_creada(usuario_id, nota_id, texto.strip())
    return nota_id


def _emitir_evento_nota_creada(usuario_id: int, nota_id: int, texto: str) -> None:
    """Solo al CREAR — editar una nota no vuelve a emitir el evento
    (ver _reindexar_nota, compartido entre crear/editar, que sí se
    ejecuta en ambos casos). Mismo criterio de import perezoso que
    _emitir_evento_tarea_finalizada."""
    from . import eventos
    try:
        tenant = tenant_de_usuario(usuario_id)
        eventos.emitir("nota.creada", tenant["id"] if tenant else None, {"nota_id": nota_id, "texto": texto})
    except Exception:
        pass


def _reindexar_nota(usuario_id: int, nota_id: int) -> None:
    """Reindexa una nota en el buscador unificado (ver app/busqueda.py)
    tras crearla/editarla — falla en silencio si el buscador no está
    configurado/caído, es una mejora de UX, no debe romper el registro
    de actividad en sí. Import perezoso a propósito: db.py no depende
    de ningún otro módulo de app/ como regla general, esta es la única
    excepción (indexar es, por naturaleza, un efecto secundario de cada
    escritura, no una operación de negocio más)."""
    from . import busqueda
    try:
        nota = obtener_nota(usuario_id, nota_id)
        if nota is not None:
            busqueda.indexar_nota(dict(nota))
    except busqueda.ErrorBusqueda:
        pass


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
            """SELECT n.*, c.nombre AS categoria_nombre
               FROM notas n LEFT JOIN categorias c ON c.id = n.categoria_id
               WHERE n.id = ? AND n.usuario_id = ? AND n.papelera_en IS NULL""",
            (nota_id, usuario_id),
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
    _reindexar_nota(usuario_id, nota_id)


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
    _quitar_nota_del_indice(nota_id)


def _quitar_nota_del_indice(nota_id: int) -> None:
    from . import busqueda
    try:
        busqueda.eliminar_del_indice("nota", nota_id)
    except busqueda.ErrorBusqueda:
        pass


def restaurar_nota(usuario_id: int, nota_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE notas SET papelera_en = NULL WHERE id = ? AND usuario_id = ?", (nota_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()
    _reindexar_nota(usuario_id, nota_id)


def eliminar_nota_definitivamente(usuario_id: int, nota_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM notas WHERE id = ? AND usuario_id = ?", (nota_id, usuario_id))
        conn.commit()
    finally:
        conn.close()
    _quitar_nota_del_indice(nota_id)


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
# Independientes de las tareas con duración de más arriba (ese sistema es un
# cronómetro en vivo, no un horario planificado de antemano). SÍ admiten un
# menú opcional (categoria_id, relación real con la tabla categorias, mismo
# patrón que correo_mensajes.categoria_id) además de categoria_outlook (texto
# libre, para importar/exportar con Outlook real — son dos campos
# independientes a propósito, no hay que confundirlos). Los campos calcan el
# modelo de objetos de Outlook / VTODO de iCalendar para que importar y
# exportar sea un mapeo directo, campo a campo.

CAMPOS_TAREA_OUTLOOK = (
    "asunto", "cuerpo", "estado", "porcentaje_completado", "prioridad",
    "fecha_inicio", "fecha_vencimiento", "fecha_completada",
    "categoria_outlook", "categoria_id", "outlook_entry_id",
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
    categoria_id: int | None = None,
    outlook_entry_id: str | None = None,
) -> int:
    conn = get_connection()
    try:
        categoria_id = _categoria_id_propio(conn, usuario_id, categoria_id)
        cur = conn.execute(
            """INSERT INTO tareas_outlook
               (usuario_id, asunto, cuerpo, estado, porcentaje_completado, prioridad,
                fecha_inicio, fecha_vencimiento, categoria_outlook, categoria_id,
                outlook_entry_id, creada_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                usuario_id, asunto.strip(), (cuerpo or "").strip() or None, estado,
                porcentaje_completado, prioridad, fecha_inicio, fecha_vencimiento,
                (categoria_outlook or "").strip() or None, categoria_id, outlook_entry_id, now_iso(),
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
        # t.usuario_id/t.papelera_en llevan el prefijo de tabla porque
        # categorias también tiene esas dos columnas (JOIN ambiguo si no);
        # el resto de condiciones no lo necesitan, son propias de tareas_outlook.
        cond = ["t.usuario_id = ?", "t.papelera_en IS NULL"]
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
            f"""SELECT t.*, c.nombre AS categoria_nombre, c.color AS categoria_color
                FROM tareas_outlook t LEFT JOIN categorias c ON c.id = t.categoria_id
                WHERE {where}
                ORDER BY (t.fecha_vencimiento IS NULL), t.fecha_vencimiento, t.prioridad DESC""",
            params,
        ).fetchall()
    finally:
        conn.close()


def obtener_tarea_outlook(usuario_id: int, tarea_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT t.*, c.nombre AS categoria_nombre, c.color AS categoria_color
               FROM tareas_outlook t LEFT JOIN categorias c ON c.id = t.categoria_id
               WHERE t.id = ? AND t.usuario_id = ? AND t.papelera_en IS NULL""",
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
        if "categoria_id" in campos:
            campos["categoria_id"] = _categoria_id_propio(conn, usuario_id, campos["categoria_id"])
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
    """Lanza ValueError (mensaje legible, lo traduce app/correo.py a
    ErrorCorreo) si ya tienes una categoría de correo con ese nombre --
    antes era un IntegrityError sin capturar, 500 en crudo (revisión de
    lógica; la UNIQUE ahora es por (usuario_id, nombre), así que esto ya
    NUNCA salta por culpa de OTRO usuario, solo por repetir un nombre
    propio)."""
    conn = get_connection()
    try:
        try:
            cur = conn.execute(
                "INSERT INTO correo_categorias (usuario_id, nombre, color, creada_en) VALUES (?, ?, ?, ?)",
                (usuario_id, nombre.strip(), color, now_iso()),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"Ya tienes una categoría de correo llamada '{nombre.strip()}'.") from None
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


def asignar_categoria_correo(usuario_id: int, mensaje_id: int, categoria_id: int | None) -> None:
    """`usuario_id` solo para comprobar que `categoria_id` es suya --
    quien llama ya tiene que haber comprobado por su cuenta que
    `mensaje_id` es del usuario (ver _mensaje_de_usuario_o_404 en
    rutas_correo.py), esta función no repite esa parte."""
    conn = get_connection()
    try:
        if categoria_id is not None:
            fila = conn.execute(
                "SELECT 1 FROM correo_categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id)
            ).fetchone()
            if fila is None:
                categoria_id = None
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
        fila = conn.execute(
            "SELECT 1 FROM correo_categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id)
        ).fetchone()
        if fila is None:
            raise ValueError(f"La categoría de correo {categoria_id} no existe o no es tuya.")
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
               JOIN correo_categorias c ON c.id = r.categoria_id AND c.usuario_id = r.usuario_id
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
                       COALESCE(ck.nombre, tk.categoria_outlook) AS categoria_nombre, ck.color AS categoria_color, tk.papelera_en AS papelera_en
                FROM tareas_outlook tk LEFT JOIN categorias ck ON ck.id = tk.categoria_id
                WHERE tk.usuario_id = ? AND tk.papelera_en IS NOT NULL
            )
            ORDER BY papelera_en DESC
            """,
            (usuario_id, usuario_id, usuario_id, usuario_id),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def vaciar_papelera_antigua(dias: int = 30, usuario_id: int | None = None) -> None:
    """Purga definitivamente (sin posibilidad de recuperar) lo que lleva en
    la papelera más de `dias` días. Sin `usuario_id`, purga de TODOS los
    usuarios (uso interno: se llama al arrancar la app, igual que la copia
    de seguridad); con `usuario_id`, solo la papelera de ese usuario (uso
    desde la ruta web "Vaciar papelera", que actúa en nombre de quien la
    pulsa, no de todo el tenant)."""
    conn = get_connection()
    try:
        limite = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
        filtro_usuario = " AND usuario_id = ?" if usuario_id is not None else ""
        params = (limite, usuario_id) if usuario_id is not None else (limite,)
        ids_categorias = [
            (r["id"], r["usuario_id"]) for r in conn.execute(
                f"SELECT id, usuario_id FROM categorias WHERE papelera_en IS NOT NULL AND papelera_en < ?{filtro_usuario}", params
            )
        ]
        ids_tareas = [
            (r["id"], r["usuario_id"]) for r in conn.execute(
                f"SELECT id, usuario_id FROM tareas WHERE papelera_en IS NOT NULL AND papelera_en < ?{filtro_usuario}", params
            )
        ]
        ids_notas = [
            (r["id"], r["usuario_id"]) for r in conn.execute(
                f"SELECT id, usuario_id FROM notas WHERE papelera_en IS NOT NULL AND papelera_en < ?{filtro_usuario}", params
            )
        ]
        ids_tareas_outlook = [
            (r["id"], r["usuario_id"]) for r in conn.execute(
                f"SELECT id, usuario_id FROM tareas_outlook WHERE papelera_en IS NOT NULL AND papelera_en < ?{filtro_usuario}", params
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


# ---- Tiquets (soporte interno: errores/sugerencias, tablero compartido) ----

def crear_tiquet(usuario_id: int, tipo: str, titulo: str, descripcion: str | None = None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO tiquets (usuario_id, tipo, titulo, descripcion, creado_en)
               VALUES (?, ?, ?, ?, ?)""",
            (usuario_id, tipo, titulo.strip(), (descripcion or "").strip() or None, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_tiquets(estado: str | None = None, tipo: str | None = None) -> list[sqlite3.Row]:
    """Todos los tiquets, de cualquier usuario -- tablero compartido, a
    diferencia de notas/tareas/correo que siempre filtran por
    usuario_id. Ordenados por id (orden de inclusión)."""
    conn = get_connection()
    try:
        cond = []
        params: list = []
        if estado:
            cond.append("t.estado = ?"); params.append(estado)
        if tipo:
            cond.append("t.tipo = ?"); params.append(tipo)
        where = f"WHERE {' AND '.join(cond)}" if cond else ""
        return conn.execute(
            f"""SELECT t.*, u.email AS autor_email
                FROM tiquets t LEFT JOIN usuarios u ON u.id = t.usuario_id
                {where}
                ORDER BY t.id""",
            params,
        ).fetchall()
    finally:
        conn.close()


def obtener_tiquet(tiquet_id: int) -> sqlite3.Row | None:
    """Sin filtrar por usuario_id -- hay dos roles con distinto alcance
    (dueño / admin) y quien llama (rutas_tiquets.py, mcp_tools.py) es
    quien decide si el usuario actual puede verlo/tocarlo."""
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT t.*, u.email AS autor_email
               FROM tiquets t LEFT JOIN usuarios u ON u.id = t.usuario_id
               WHERE t.id = ?""",
            (tiquet_id,),
        ).fetchone()
    finally:
        conn.close()


def editar_tiquet(usuario_id: int, tiquet_id: int, titulo: str, descripcion: str | None, tipo: str) -> bool:
    """Solo actualiza si `usuario_id` es el dueño Y el tiquet sigue en
    'sin_revisar' -- devuelve False sin tocar nada si no se cumple
    alguna de las dos condiciones (quien llama decide qué error mostrar)."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """UPDATE tiquets SET titulo = ?, descripcion = ?, tipo = ?, actualizado_en = ?
               WHERE id = ? AND usuario_id = ? AND estado = 'sin_revisar'""",
            (titulo.strip(), (descripcion or "").strip() or None, tipo, now_iso(), tiquet_id, usuario_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def cambiar_estado_tiquet(tiquet_id: int, estado: str) -> None:
    """Sin chequeo de permisos aquí -- quien llama (ruta con
    @admin_required, o la tool de MCP tras comprobar db.es_admin) ya
    decidió que puede hacerlo."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tiquets SET estado = ?, actualizado_en = ? WHERE id = ?", (estado, now_iso(), tiquet_id)
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_tiquet(tiquet_id: int) -> None:
    """Sin chequeo de permisos aquí tampoco -- ver cambiar_estado_tiquet."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM tiquets WHERE id = ?", (tiquet_id,))
        conn.commit()
    finally:
        conn.close()


def guardar_adjunto_tiquet(tiquet_id: int, nombre_archivo: str, tipo_mime: str, contenido: bytes) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO tiquets_adjuntos (tiquet_id, nombre_archivo, tipo_mime, tamano_bytes, contenido, creado_en)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tiquet_id, nombre_archivo, tipo_mime, len(contenido), contenido, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_adjuntos_tiquet(tiquet_id: int) -> list[sqlite3.Row]:
    """Sin el BLOB `contenido` -- para listar en tarjetas/edición no hace
    falta traer los bytes enteros de cada adjunto, solo al descargar uno
    en concreto (ver obtener_adjunto_tiquet)."""
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT id, tiquet_id, nombre_archivo, tipo_mime, tamano_bytes, creado_en
               FROM tiquets_adjuntos WHERE tiquet_id = ? ORDER BY id""",
            (tiquet_id,),
        ).fetchall()
    finally:
        conn.close()


def obtener_adjunto_tiquet(adjunto_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM tiquets_adjuntos WHERE id = ?", (adjunto_id,)).fetchone()
    finally:
        conn.close()


def eliminar_adjunto_tiquet(adjunto_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM tiquets_adjuntos WHERE id = ?", (adjunto_id,))
        conn.commit()
    finally:
        conn.close()


# --- Fichaje de trabajadores (registro horario, art. 34.9 ET) -------------

def obtener_fichaje_datos(usuario_id: int) -> sqlite3.Row:
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO fichaje_datos (usuario_id) VALUES (?)", (usuario_id,))
        conn.commit()
        return conn.execute("SELECT * FROM fichaje_datos WHERE usuario_id = ?", (usuario_id,)).fetchone()
    finally:
        conn.close()


def guardar_fichaje_datos(
    usuario_id: int, nombre_completo: str, dni_nie: str, numero_afiliacion_ss: str | None = None,
    categoria_profesional: str | None = None, tipo_contrato: str | None = None,
    fecha_alta: str | None = None, jornada_semanal_horas: float | None = None,
    convenio_colectivo: str | None = None,
) -> None:
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO fichaje_datos (usuario_id) VALUES (?)", (usuario_id,))
        conn.execute(
            """UPDATE fichaje_datos SET nombre_completo = ?, dni_nie = ?, numero_afiliacion_ss = ?,
               categoria_profesional = ?, tipo_contrato = ?, fecha_alta = ?, jornada_semanal_horas = ?,
               convenio_colectivo = ?, actualizado_en = ? WHERE usuario_id = ?""",
            (
                nombre_completo.strip() or None, dni_nie.strip().upper() or None, numero_afiliacion_ss or None,
                categoria_profesional or None, tipo_contrato or None, fecha_alta or None,
                jornada_semanal_horas, convenio_colectivo or None, now_iso(), usuario_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def fichaje_datos_completos(usuario_id: int) -> bool:
    """True si el trabajador ya rellenó lo mínimo exigible (nombre + DNI/
    NIE) para identificarse ante una inspección -- se exige antes de dejar
    fichar por primera vez (ver app/rutas_fichaje.py)."""
    datos = obtener_fichaje_datos(usuario_id)
    return bool(datos["nombre_completo"]) and bool(datos["dni_nie"])


_FICHAJE_TRANSICIONES_VALIDAS = {
    "salida": {"entrada"},
    "entrada": {"pausa_inicio", "salida"},
    "pausa_inicio": {"pausa_fin", "salida"},
    "pausa_fin": {"pausa_inicio", "salida"},
}


def fichar(
    usuario_id: int, tenant_id: int | None, tipo: str, origen: str = "web", creado_por: int | None = None,
    corrige_a: int | None = None, nota: str | None = None,
    marca_tiempo: str | None = None, cliente_uuid: str | None = None,
) -> int:
    """Inserta un evento de fichaje, validando que la secuencia sea
    coherente (no se puede fichar salida sin una entrada abierta, ni una
    segunda entrada sin haber salido antes) -- lanza ValueError si no
    cuadra, mismo estilo que ErrorCorreo/ErrorBusqueda. `corrige_a` es
    para que un admin corrija un olvido sin tocar la fila original (ver
    comentario de la tabla `fichajes`).

    `marca_tiempo`/`cliente_uuid` son para la cola offline de la app móvil:
    si el evento se pulsó sin cobertura y se sincroniza más tarde,
    `marca_tiempo` conserva la hora real de la pulsación (si no se manda, se
    usa la hora del servidor como siempre) y `cliente_uuid` evita duplicar
    la fila si la sincronización se reintenta. Nota: la validación de
    secuencia sigue mirando el último evento por orden de inserción, no por
    `marca_tiempo` -- un evento offline que llega después de que ya se haya
    fichado algo más reciente puede quedar fuera de secuencia y rechazarse,
    algo inherente a fichar con retraso, no un bug de esta función."""
    if tipo not in ("entrada", "pausa_inicio", "pausa_fin", "salida"):
        raise ValueError(f"Tipo de fichaje no válido: {tipo!r}.")
    conn = get_connection()
    try:
        if cliente_uuid is not None:
            existente = conn.execute("SELECT id FROM fichajes WHERE cliente_uuid = ?", (cliente_uuid,)).fetchone()
            if existente is not None:
                return existente["id"]
        ahora = now_iso()
        if marca_tiempo is not None:
            limite_pasado = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
            if marca_tiempo > ahora or marca_tiempo < limite_pasado:
                raise ValueError("La hora del fichaje enviado no es válida (demasiado futura o de hace más de 7 días).")
        if corrige_a is not None:
            original = conn.execute("SELECT id FROM fichajes WHERE id = ? AND usuario_id = ?", (corrige_a, usuario_id)).fetchone()
            if original is None:
                raise ValueError(f"El fichaje {corrige_a} a corregir no existe o no es de este trabajador.")
        else:
            ultimo = conn.execute(
                "SELECT tipo FROM fichajes WHERE usuario_id = ? ORDER BY id DESC LIMIT 1", (usuario_id,)
            ).fetchone()
            ultimo_tipo = ultimo["tipo"] if ultimo else "salida"  # sin fichajes previos = como si estuviera fuera
            if tipo not in _FICHAJE_TRANSICIONES_VALIDAS.get(ultimo_tipo, set()):
                raise ValueError(f"No se puede fichar '{tipo}' viniendo de '{ultimo_tipo}' — revisa tu último fichaje.")
        cur = conn.execute(
            """INSERT INTO fichajes (usuario_id, tenant_id, tipo, marca_tiempo, origen, nota, corrige_a, creado_por, creado_en, cliente_uuid)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (usuario_id, tenant_id, tipo, marca_tiempo or ahora, origen, nota, corrige_a, creado_por or usuario_id, ahora, cliente_uuid),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def estado_actual_fichaje(usuario_id: int) -> str:
    """'fuera' | 'dentro' | 'en_pausa', según el último evento real (no
    cuenta si esa fila es en sí una corrección de otra anterior — el
    último evento cronológico manda igual)."""
    conn = get_connection()
    try:
        ultimo = conn.execute(
            "SELECT tipo FROM fichajes WHERE usuario_id = ? ORDER BY id DESC LIMIT 1", (usuario_id,)
        ).fetchone()
        if ultimo is None or ultimo["tipo"] == "salida":
            return "fuera"
        if ultimo["tipo"] == "pausa_inicio":
            return "en_pausa"
        return "dentro"
    finally:
        conn.close()


def listar_fichajes(usuario_id: int, desde: str | None = None, hasta: str | None = None) -> list[sqlite3.Row]:
    """Historial de un trabajador -- se usa tanto para su propio
    historial como para el detalle que ve un admin de un trabajador
    concreto (mismos datos, distinto quién pregunta; el control de acceso
    vive en la ruta, no aquí)."""
    conn = get_connection()
    try:
        sql = "SELECT * FROM fichajes WHERE usuario_id = ?"
        params: list = [usuario_id]
        if desde:
            sql += " AND marca_tiempo >= ?"
            params.append(desde)
        if hasta:
            sql += " AND marca_tiempo < ?"
            params.append(_fecha_exclusiva(hasta))
        sql += " ORDER BY marca_tiempo DESC"
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def fichajes_tenant_crudos(
    tenant_id: int | None, desde: str | None = None, hasta: str | None = None, usuario_id: int | None = None,
) -> list[sqlite3.Row]:
    """Eventos de fichaje en bruto de un tenant (con email/nombre/DNI del
    trabajador ya unidos), para que app/fichaje_export.py construya el
    CSV/PDF -- misma idea que db.historial() alimentando a export.py, la
    tabla en sí no sabe nada de formatos de salida."""
    conn = get_connection()
    try:
        sql = (
            "SELECT f.*, u.email, fd.nombre_completo, fd.dni_nie "
            "FROM fichajes f "
            "JOIN usuarios u ON u.id = f.usuario_id "
            "LEFT JOIN fichaje_datos fd ON fd.usuario_id = f.usuario_id "
            "WHERE (f.tenant_id = ? OR (? IS NULL AND f.tenant_id IS NULL))"
        )
        params: list = [tenant_id, tenant_id]
        if usuario_id:
            sql += " AND f.usuario_id = ?"
            params.append(usuario_id)
        if desde:
            sql += " AND f.marca_tiempo >= ?"
            params.append(desde)
        if hasta:
            sql += " AND f.marca_tiempo < ?"
            params.append(_fecha_exclusiva(hasta))
        sql += " ORDER BY f.usuario_id, f.marca_tiempo"
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def resumen_fichajes_tenant(tenant_id: int | None, desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Horas trabajadas por cada trabajador del tenant en el periodo, para
    el panel de admin. Empareja entrada/salida y resta las pausas
    recorriendo el log en Python (no es un problema que encaje bien en
    SQL puro: es "diferencia entre eventos consecutivos de una serie")."""
    conn = get_connection()
    try:
        sql = (
            "SELECT f.*, u.email, fd.nombre_completo, fd.jornada_semanal_horas "
            "FROM fichajes f "
            "JOIN usuarios u ON u.id = f.usuario_id "
            "LEFT JOIN fichaje_datos fd ON fd.usuario_id = f.usuario_id "
            "WHERE (f.tenant_id = ? OR (? IS NULL AND f.tenant_id IS NULL))"
        )
        params: list = [tenant_id, tenant_id]
        if desde:
            sql += " AND f.marca_tiempo >= ?"
            params.append(desde)
        if hasta:
            sql += " AND f.marca_tiempo < ?"
            params.append(_fecha_exclusiva(hasta))
        sql += " ORDER BY f.usuario_id, f.marca_tiempo"
        filas = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    por_usuario: dict[int, dict] = {}
    for f in filas:
        uid = f["usuario_id"]
        info = por_usuario.setdefault(uid, {
            "usuario_id": uid, "email": f["email"], "nombre_completo": f["nombre_completo"],
            "jornada_semanal_horas": f["jornada_semanal_horas"],
            "segundos_trabajados": 0, "segundos_pausa": 0, "num_fichajes": 0,
            "entrada_abierta": None, "pausa_abierta": None,
        })
        info["num_fichajes"] += 1
        marca = datetime.fromisoformat(f["marca_tiempo"])
        if f["tipo"] == "entrada":
            info["entrada_abierta"] = marca
        elif f["tipo"] == "pausa_inicio":
            info["pausa_abierta"] = marca
        elif f["tipo"] == "pausa_fin" and info["pausa_abierta"]:
            info["segundos_pausa"] += (marca - info["pausa_abierta"]).total_seconds()
            info["pausa_abierta"] = None
        elif f["tipo"] == "salida" and info["entrada_abierta"]:
            info["segundos_trabajados"] += (marca - info["entrada_abierta"]).total_seconds()
            info["entrada_abierta"] = None

    resultado = [
        {
            "usuario_id": info["usuario_id"],
            "email": info["email"],
            "nombre_completo": info["nombre_completo"],
            "horas_trabajadas": round(info["segundos_trabajados"] / 3600, 2),
            "horas_pausa": round(info["segundos_pausa"] / 3600, 2),
            "jornada_semanal_horas": info["jornada_semanal_horas"],
            "num_fichajes": info["num_fichajes"],
            "jornada_abierta": info["entrada_abierta"] is not None,
        }
        for info in por_usuario.values()
    ]
    return sorted(resultado, key=lambda r: r["nombre_completo"] or r["email"])
