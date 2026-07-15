"""Acceso a la base de datos SQLite de Guilda Work.

Todos los timestamps se guardan en hora local (Europe/Madrid), formato
ISO 8601 sin zona horaria explícita, ej: 2026-07-10T14:32:05.
"""
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

if hasattr(sys, "_MEIPASS"):
    # Empaquetado con PyInstaller: sys._MEIPASS es una carpeta temporal que se
    # borra al cerrar, así que la base de datos vive junto al .exe, no ahí.
    RAIZ_PROYECTO = Path(sys.executable).resolve().parent
else:
    RAIZ_PROYECTO = Path(__file__).resolve().parent.parent

DB_PATH = RAIZ_PROYECTO / "data" / "registro.db"
BACKUPS_DIR = RAIZ_PROYECTO / "data" / "backups"

SCHEMA = """
CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    color TEXT,
    creada_en TEXT NOT NULL,
    papelera_en TEXT,
    orden INTEGER
);

CREATE TABLE IF NOT EXISTS tareas (
    id INTEGER PRIMARY KEY,
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
    nombre TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL,
    creada_en TEXT NOT NULL
);

-- Preferencias generales de Correo: una sola fila (id=1 siempre).
CREATE TABLE IF NOT EXISTS correo_preferencias (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    densidad TEXT NOT NULL DEFAULT 'normal' CHECK (densidad IN ('normal','compacta')),
    marcar_leido_automatico INTEGER NOT NULL DEFAULT 1,
    limite_mensajes INTEGER NOT NULL DEFAULT 50
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

-- Preferencias del Asistente IA (OpenRouter): una sola fila (id=1 siempre).
-- La clave de API NUNCA se guarda aquí: vive en el almacén de credenciales
-- del sistema (keyring), gestionada por app/ia_asistente.py, igual que las
-- contraseñas de correo en app/correo.py.
CREATE TABLE IF NOT EXISTS ia_preferencias (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    modelo TEXT NOT NULL DEFAULT '',
    modo_autonomo INTEGER NOT NULL DEFAULT 0
);

-- Historial de la conversación con el Asistente IA (un único hilo).
CREATE TABLE IF NOT EXISTS ia_mensajes (
    id INTEGER PRIMARY KEY,
    rol TEXT NOT NULL CHECK (rol IN ('user','assistant','tool')),
    contenido TEXT,
    tool_calls_json TEXT,
    tool_call_id TEXT,
    nombre_herramienta TEXT,
    creado_en TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


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
        conn.execute("INSERT OR IGNORE INTO correo_preferencias (id) VALUES (1)")
        conn.execute("INSERT OR IGNORE INTO ia_preferencias (id) VALUES (1)")
        _asegurar_orden_categorias(conn)
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


# --- Categorías --------------------------------------------------------

def crear_categoria(nombre: str, color: str | None = None) -> int:
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

        siguiente_orden = conn.execute("SELECT COALESCE(MAX(orden), -1) + 1 FROM categorias").fetchone()[0]
        cur = conn.execute(
            "INSERT INTO categorias (nombre, color, creada_en, orden) VALUES (?, ?, ?, ?)",
            (nombre, color, now_iso(), siguiente_orden),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_categorias() -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM categorias WHERE papelera_en IS NULL ORDER BY orden, nombre"
        ).fetchall()
    finally:
        conn.close()


def mover_categoria(categoria_id: int, direccion: str) -> None:
    """Reordena un menú un puesto arriba o abajo (`direccion`: 'arriba'/'abajo')."""
    conn = get_connection()
    try:
        activas = conn.execute(
            "SELECT id, orden FROM categorias WHERE papelera_en IS NULL ORDER BY orden, nombre"
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


def reordenar_categorias(orden_ids: list[int]) -> None:
    """Reescribe `orden` según la lista completa recibida (0, 1, 2...), para
    el arrastrar-y-soltar de la barra lateral — a diferencia de
    `mover_categoria`, que mueve un solo puesto. Los ids que no existan (o no
    estén activos) se ignoran sin fallar; los menús activos que falten en la
    lista conservan su `orden` actual, detrás de los que sí se han movido."""
    conn = get_connection()
    try:
        activos = {f["id"] for f in conn.execute("SELECT id FROM categorias WHERE papelera_en IS NULL")}
        siguiente = 0
        for categoria_id in orden_ids:
            if categoria_id in activos:
                conn.execute("UPDATE categorias SET orden = ? WHERE id = ?", (siguiente, categoria_id))
                siguiente += 1
        conn.commit()
    finally:
        conn.close()


def alternar_favorito_categoria(categoria_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE categorias SET favorito = 1 - favorito WHERE id = ? AND papelera_en IS NULL",
            (categoria_id,),
        )
        conn.commit()
    finally:
        conn.close()


def obtener_categoria(categoria_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM categorias WHERE id = ? AND papelera_en IS NULL", (categoria_id,)
        ).fetchone()
    finally:
        conn.close()


def renombrar_categoria(categoria_id: int, nombre: str, color: str | None = None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE categorias SET nombre = ?, color = ? WHERE id = ?",
            (nombre.strip(), color, categoria_id),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_categoria(categoria_id: int) -> None:
    """Manda un menú (y todo lo que contiene) a la papelera. No borra nada de
    verdad — se puede restaurar, o purgar definitivamente desde la papelera."""
    conn = get_connection()
    try:
        ahora = _marca_papelera()
        conn.execute("UPDATE categorias SET papelera_en = ? WHERE id = ?", (ahora, categoria_id))
        conn.execute(
            "UPDATE tareas SET papelera_en = ? WHERE categoria_id = ? AND papelera_en IS NULL",
            (ahora, categoria_id),
        )
        conn.execute(
            "UPDATE notas SET papelera_en = ? WHERE categoria_id = ? AND papelera_en IS NULL",
            (ahora, categoria_id),
        )
        conn.commit()
    finally:
        conn.close()


def restaurar_categoria(categoria_id: int) -> None:
    """Saca un menú de la papelera, junto con lo que se mandó a la papelera
    a la vez que él (no restaura notas/tareas que ya estaban en la papelera
    por separado antes de borrar el menú)."""
    conn = get_connection()
    try:
        fila = conn.execute("SELECT papelera_en FROM categorias WHERE id = ?", (categoria_id,)).fetchone()
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


def eliminar_categoria_definitivamente(categoria_id: int) -> None:
    """Borra un menú y todo lo que contiene de verdad (sin pasar por la
    papelera). Lo usa el botón "Eliminar definitivamente" y la purga
    automática de la papelera."""
    conn = get_connection()
    try:
        tarea_ids = [
            row["id"]
            for row in conn.execute("SELECT id FROM tareas WHERE categoria_id = ?", (categoria_id,)).fetchall()
        ]
        if tarea_ids:
            marcas = ",".join("?" * len(tarea_ids))
            conn.execute(f"DELETE FROM pausas WHERE tarea_id IN ({marcas})", tarea_ids)
            conn.execute(f"DELETE FROM notas WHERE tarea_id IN ({marcas})", tarea_ids)
        conn.execute("DELETE FROM notas WHERE categoria_id = ?", (categoria_id,))
        conn.execute("DELETE FROM tareas WHERE categoria_id = ?", (categoria_id,))
        conn.execute("DELETE FROM plantillas WHERE categoria_id = ?", (categoria_id,))
        conn.execute("DELETE FROM categorias WHERE id = ?", (categoria_id,))
        conn.commit()
    finally:
        conn.close()


def contar_entradas_hoy(categoria_id: int) -> int:
    conn = get_connection()
    try:
        hoy = datetime.now().strftime("%Y-%m-%d")
        n = conn.execute(
            "SELECT COUNT(*) FROM notas WHERE categoria_id = ? AND papelera_en IS NULL AND substr(creada_en,1,10) = ?",
            (categoria_id, hoy),
        ).fetchone()[0]
        t = conn.execute(
            "SELECT COUNT(*) FROM tareas WHERE categoria_id = ? AND papelera_en IS NULL AND substr(inicio_en,1,10) = ?",
            (categoria_id, hoy),
        ).fetchone()[0]
        return n + t
    finally:
        conn.close()


# --- Tareas / eventos ---------------------------------------------------

def crear_tarea(nombre: str, categoria_id: int, tipo: str) -> int:
    conn = get_connection()
    try:
        ahora = now_iso()
        if tipo == "instantanea":
            cur = conn.execute(
                """INSERT INTO tareas
                   (nombre, categoria_id, tipo, estado, inicio_en, fin_en, duracion_segundos)
                   VALUES (?, ?, 'instantanea', 'finalizada', ?, NULL, NULL)""",
                (nombre.strip(), categoria_id, ahora),
            )
        else:
            cur = conn.execute(
                """INSERT INTO tareas
                   (nombre, categoria_id, tipo, estado, inicio_en, fin_en, duracion_segundos)
                   VALUES (?, ?, 'duracion', 'en_curso', ?, NULL, NULL)""",
                (nombre.strip(), categoria_id, ahora),
            )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def importar_tarea(
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
               (nombre, categoria_id, tipo, estado, inicio_en, fin_en, duracion_segundos)
               VALUES (?, ?, ?, 'finalizada', ?, ?, ?)""",
            (nombre.strip(), categoria_id, tipo, inicio_en, fin_en, duracion_segundos),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def hubo_actividad_reciente(minutos: int) -> bool:
    """True si se ha creado alguna nota o tarea en los últimos `minutos`."""
    conn = get_connection()
    try:
        limite = (datetime.now() - timedelta(minutes=minutos)).isoformat(timespec="seconds")
        n = conn.execute("SELECT COUNT(*) FROM notas WHERE creada_en >= ?", (limite,)).fetchone()[0]
        t = conn.execute("SELECT COUNT(*) FROM tareas WHERE inicio_en >= ?", (limite,)).fetchone()[0]
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


def pausar_tarea(tarea_id: int) -> None:
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE tareas SET estado = 'pausada' WHERE id = ? AND tipo = 'duracion' AND estado = 'en_curso'",
            (tarea_id,),
        )
        if cur.rowcount:
            conn.execute(
                "INSERT INTO pausas (tarea_id, pausada_en) VALUES (?, ?)",
                (tarea_id, now_iso()),
            )
        conn.commit()
    finally:
        conn.close()


def reanudar_tarea(tarea_id: int) -> None:
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE tareas SET estado = 'en_curso' WHERE id = ? AND estado = 'pausada'",
            (tarea_id,),
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


def finalizar_tarea(tarea_id: int) -> None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT inicio_en, estado FROM tareas WHERE id = ?", (tarea_id,)).fetchone()
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


def tareas_activas() -> list[dict]:
    """Tareas con duración en curso o en pausa, con el tiempo ya pausado calculado."""
    conn = get_connection()
    try:
        filas = conn.execute(
            """SELECT t.*, c.nombre AS categoria_nombre, c.color AS categoria_color
               FROM tareas t JOIN categorias c ON c.id = t.categoria_id
               WHERE t.tipo = 'duracion' AND t.estado IN ('en_curso', 'pausada')
                 AND t.papelera_en IS NULL
               ORDER BY t.inicio_en"""
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


def obtener_tarea(tarea_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT t.*, c.nombre AS categoria_nombre
               FROM tareas t JOIN categorias c ON c.id = t.categoria_id
               WHERE t.id = ? AND t.papelera_en IS NULL""",
            (tarea_id,),
        ).fetchone()
    finally:
        conn.close()


def editar_tarea(tarea_id: int, nombre: str) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE tareas SET nombre = ? WHERE id = ?", (nombre.strip(), tarea_id))
        conn.commit()
    finally:
        conn.close()


def editar_tiempos_tarea(tarea_id: int, inicio_en: str, fin_en: str | None = None) -> str | None:
    """Ajusta manualmente el inicio (y el fin, si la tarea ya está finalizada).

    Devuelve un mensaje de error legible si la entrada no es válida, o None si todo fue bien.
    """
    conn = get_connection()
    try:
        row = conn.execute("SELECT tipo, estado, fin_en FROM tareas WHERE id = ?", (tarea_id,)).fetchone()
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


def eliminar_tarea(tarea_id: int) -> None:
    """Manda una tarea/evento a la papelera (no la borra de verdad)."""
    conn = get_connection()
    try:
        conn.execute("UPDATE tareas SET papelera_en = ? WHERE id = ?", (_marca_papelera(), tarea_id))
        conn.commit()
    finally:
        conn.close()


def restaurar_tarea(tarea_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE tareas SET papelera_en = NULL WHERE id = ?", (tarea_id,))
        conn.commit()
    finally:
        conn.close()


def eliminar_tarea_definitivamente(tarea_id: int) -> None:
    """Borra una tarea/evento y sus pausas y notas asociadas de verdad."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM pausas WHERE tarea_id = ?", (tarea_id,))
        conn.execute("DELETE FROM notas WHERE tarea_id = ?", (tarea_id,))
        conn.execute("DELETE FROM tareas WHERE id = ?", (tarea_id,))
        conn.commit()
    finally:
        conn.close()


# --- Notas ---------------------------------------------------------------

def crear_nota(texto: str, categoria_id: int | None = None, tarea_id: int | None = None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO notas (texto, categoria_id, tarea_id, creada_en) VALUES (?, ?, ?, ?)",
            (texto.strip(), categoria_id, tarea_id, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def importar_nota(texto: str, categoria_id: int | None, creada_en: str) -> int:
    """Inserta una nota con un timestamp explícito (importación de datos exportados)."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO notas (texto, categoria_id, tarea_id, creada_en) VALUES (?, ?, NULL, ?)",
            (texto.strip(), categoria_id, creada_en),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def obtener_nota(nota_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM notas WHERE id = ? AND papelera_en IS NULL", (nota_id,)
        ).fetchone()
    finally:
        conn.close()


def editar_nota(nota_id: int, texto: str) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE notas SET texto = ? WHERE id = ?", (texto.strip(), nota_id))
        conn.commit()
    finally:
        conn.close()


def eliminar_nota(nota_id: int) -> None:
    """Manda una nota a la papelera (no la borra de verdad)."""
    conn = get_connection()
    try:
        conn.execute("UPDATE notas SET papelera_en = ? WHERE id = ?", (_marca_papelera(), nota_id))
        conn.commit()
    finally:
        conn.close()


def restaurar_nota(nota_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE notas SET papelera_en = NULL WHERE id = ?", (nota_id,))
        conn.commit()
    finally:
        conn.close()


def eliminar_nota_definitivamente(nota_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM notas WHERE id = ?", (nota_id,))
        conn.commit()
    finally:
        conn.close()


# --- Histórico combinado ---------------------------------------------------

def historial(
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
        cond = []
        params: list = []
        if desde:
            cond.append("fecha >= ?")
            params.append(desde)
        if hasta:
            cond.append("fecha <= ?")
            params.append(hasta)
        if categoria_id:
            cond.append("categoria_id = ?")
            params.append(categoria_id)
        if texto:
            cond.append("texto LIKE ?")
            params.append(f"%{texto}%")
        where = ("WHERE " + " AND ".join(cond)) if cond else ""

        query = f"""
            SELECT * FROM (
                SELECT
                    'nota' AS origen,
                    n.id AS id,
                    n.texto AS texto,
                    NULL AS tipo,
                    NULL AS estado,
                    n.creada_en AS timestamp,
                    substr(n.creada_en, 1, 10) AS fecha,
                    NULL AS fin_en,
                    NULL AS duracion_segundos,
                    n.categoria_id AS categoria_id,
                    c.nombre AS categoria_nombre,
                    c.color AS categoria_color
                FROM notas n LEFT JOIN categorias c ON c.id = n.categoria_id
                WHERE n.papelera_en IS NULL

                UNION ALL

                SELECT
                    'tarea' AS origen,
                    t.id AS id,
                    t.nombre AS texto,
                    t.tipo AS tipo,
                    t.estado AS estado,
                    t.inicio_en AS timestamp,
                    substr(t.inicio_en, 1, 10) AS fecha,
                    t.fin_en AS fin_en,
                    t.duracion_segundos AS duracion_segundos,
                    t.categoria_id AS categoria_id,
                    c.nombre AS categoria_nombre,
                    c.color AS categoria_color
                FROM tareas t JOIN categorias c ON c.id = t.categoria_id
                WHERE t.papelera_en IS NULL
            )
            {where}
            ORDER BY timestamp DESC
        """
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


# --- Estadísticas ----------------------------------------------------------

def estadisticas_por_categoria(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Tiempo total (tareas finalizadas) y nº de entradas por categoría."""
    conn = get_connection()
    try:
        cond_t = ["t.tipo = 'duracion'", "t.estado = 'finalizada'", "t.papelera_en IS NULL"]
        cond_ev = ["tt.tipo = 'instantanea'", "tt.papelera_en IS NULL"]
        cond_n = ["n.papelera_en IS NULL"]
        params_t: list = []
        params_ev: list = []
        params_n: list = []
        if desde:
            cond_t.append("substr(t.inicio_en,1,10) >= ?"); params_t.append(desde)
            cond_ev.append("substr(tt.inicio_en,1,10) >= ?"); params_ev.append(desde)
            cond_n.append("substr(n.creada_en,1,10) >= ?"); params_n.append(desde)
        if hasta:
            cond_t.append("substr(t.inicio_en,1,10) <= ?"); params_t.append(hasta)
            cond_ev.append("substr(tt.inicio_en,1,10) <= ?"); params_ev.append(hasta)
            cond_n.append("substr(n.creada_en,1,10) <= ?"); params_n.append(hasta)

        filas = conn.execute(
            f"""SELECT c.id, c.nombre, c.color,
                   COALESCE((SELECT SUM(t.duracion_segundos) FROM tareas t
                             WHERE t.categoria_id = c.id AND {' AND '.join(cond_t)}), 0) AS segundos_totales,
                   COALESCE((SELECT COUNT(*) FROM tareas t
                             WHERE t.categoria_id = c.id AND {' AND '.join(cond_t)}), 0) AS num_tareas,
                   COALESCE((SELECT COUNT(*) FROM tareas tt
                             WHERE tt.categoria_id = c.id AND {' AND '.join(cond_ev)}), 0) AS num_eventos,
                   COALESCE((SELECT COUNT(*) FROM notas n
                             WHERE n.categoria_id = c.id {(' AND ' + ' AND '.join(cond_n)) if cond_n else ''}), 0) AS num_notas
               FROM categorias c
               ORDER BY segundos_totales DESC, c.nombre""",
            [*params_t, *params_t, *params_ev, *params_n],
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def estadisticas_por_dia(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Tiempo total en tareas con duración finalizadas, agrupado por día y categoría."""
    conn = get_connection()
    try:
        cond = ["t.tipo = 'duracion'", "t.estado = 'finalizada'", "t.papelera_en IS NULL"]
        params: list = []
        if desde:
            cond.append("substr(t.inicio_en,1,10) >= ?"); params.append(desde)
        if hasta:
            cond.append("substr(t.inicio_en,1,10) <= ?"); params.append(hasta)
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
               (asunto, cuerpo, estado, porcentaje_completado, prioridad,
                fecha_inicio, fecha_vencimiento, categoria_outlook,
                outlook_entry_id, creada_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                asunto.strip(), (cuerpo or "").strip() or None, estado,
                porcentaje_completado, prioridad, fecha_inicio, fecha_vencimiento,
                (categoria_outlook or "").strip() or None, outlook_entry_id, now_iso(),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_tareas_outlook(
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
        cond = ["papelera_en IS NULL"]
        params: list = []
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
            cond.append("substr(fecha_vencimiento,1,10) >= ?"); params.append(desde)
        if hasta:
            cond.append("substr(fecha_vencimiento,1,10) <= ?"); params.append(hasta)
        where = " AND ".join(cond)
        return conn.execute(
            f"""SELECT * FROM tareas_outlook WHERE {where}
                ORDER BY (fecha_vencimiento IS NULL), fecha_vencimiento, prioridad DESC""",
            params,
        ).fetchall()
    finally:
        conn.close()


def obtener_tarea_outlook(tarea_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM tareas_outlook WHERE id = ? AND papelera_en IS NULL", (tarea_id,)
        ).fetchone()
    finally:
        conn.close()


def obtener_tarea_outlook_por_entry_id(entry_id: str) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM tareas_outlook WHERE outlook_entry_id = ?", (entry_id,)
        ).fetchone()
    finally:
        conn.close()


def upsert_tarea_outlook_por_entry_id(outlook_entry_id: str | None, **campos) -> tuple[int, bool]:
    """Crea la tarea, o actualiza la ya existente con ese `outlook_entry_id`.

    Devuelve (id, creada) — creada=True si no existía y se ha creado nueva.
    Pensado para sincronizar desde una fuente externa (.ics, .csv, o más
    adelante COM) sin duplicar tareas ya importadas en una sincronización anterior.
    """
    existente = obtener_tarea_outlook_por_entry_id(outlook_entry_id) if outlook_entry_id else None
    if existente:
        campos_validos = {c: v for c, v in campos.items() if c in CAMPOS_TAREA_OUTLOOK}
        editar_tarea_outlook(existente["id"], **campos_validos)
        return existente["id"], False

    # crear_tarea_outlook no acepta fecha_completada como argumento de creación
    # (una tarea recién creada no puede nacer ya completada por diseño del
    # formulario normal) — si el origen externo trae una, se aplica aparte.
    fecha_completada = campos.get("fecha_completada")
    campos_creacion = {
        c: v for c, v in campos.items()
        if c in CAMPOS_TAREA_OUTLOOK and c not in ("fecha_completada", "outlook_entry_id")
    }
    tid = crear_tarea_outlook(outlook_entry_id=outlook_entry_id, **campos_creacion)
    if fecha_completada:
        editar_tarea_outlook(tid, fecha_completada=fecha_completada)
    return tid, True


def editar_tarea_outlook(tarea_id: int, **campos) -> None:
    """Actualiza los campos indicados (cualquiera de CAMPOS_TAREA_OUTLOOK)."""
    columnas = [c for c in campos if c in CAMPOS_TAREA_OUTLOOK]
    if not columnas:
        return
    conn = get_connection()
    try:
        asignaciones = ", ".join(f"{c} = ?" for c in columnas)
        valores = [campos[c] for c in columnas]
        conn.execute(
            f"UPDATE tareas_outlook SET {asignaciones}, actualizada_en = ? WHERE id = ?",
            [*valores, now_iso(), tarea_id],
        )
        conn.commit()
    finally:
        conn.close()


def completar_tarea_outlook(tarea_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE tareas_outlook
               SET estado = 'completada', porcentaje_completado = 100,
                   fecha_completada = ?, actualizada_en = ?
               WHERE id = ?""",
            (now_iso(), now_iso(), tarea_id),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_tarea_outlook(tarea_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE tareas_outlook SET papelera_en = ? WHERE id = ?", (_marca_papelera(), tarea_id))
        conn.commit()
    finally:
        conn.close()


def restaurar_tarea_outlook(tarea_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE tareas_outlook SET papelera_en = NULL WHERE id = ?", (tarea_id,))
        conn.commit()
    finally:
        conn.close()


def eliminar_tarea_outlook_definitivamente(tarea_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM tareas_outlook WHERE id = ?", (tarea_id,))
        conn.commit()
    finally:
        conn.close()


def listar_categorias_outlook() -> list[str]:
    """Nombres de categoría (estilo "Categories" de Outlook) usados hasta ahora."""
    conn = get_connection()
    try:
        filas = conn.execute(
            """SELECT DISTINCT categoria_outlook FROM tareas_outlook
               WHERE categoria_outlook IS NOT NULL AND papelera_en IS NULL
               ORDER BY categoria_outlook"""
        ).fetchall()
        return [f["categoria_outlook"] for f in filas]
    finally:
        conn.close()


# --- Correo (cuentas IMAP/POP3 + caché de mensajes) ---------------------------
# La lógica de red (conectar, sincronizar, enviar) vive en app/correo.py; aquí
# solo hay persistencia. La contraseña de cada cuenta NO se guarda en esta
# tabla — la gestiona app/correo.py directamente contra keyring.

def crear_cuenta_correo(
    nombre: str, protocolo: str, host: str, puerto: int, usuario: str,
    usa_tls: bool = True, smtp_host: str | None = None,
    smtp_puerto: int | None = None, smtp_tls: bool = True,
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO correo_cuentas
               (nombre, protocolo, host, puerto, usa_tls, usuario,
                smtp_host, smtp_puerto, smtp_tls, creada_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (nombre.strip(), protocolo, host.strip(), puerto, int(usa_tls),
             usuario.strip(), (smtp_host or "").strip() or None, smtp_puerto,
             int(smtp_tls), now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_cuentas_correo() -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM correo_cuentas ORDER BY nombre").fetchall()
    finally:
        conn.close()


def obtener_cuenta_correo(cuenta_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM correo_cuentas WHERE id = ?", (cuenta_id,)).fetchone()
    finally:
        conn.close()


def eliminar_cuenta_correo(cuenta_id: int) -> None:
    """Borra la cuenta y sus mensajes/carpetas cacheados. Sin papelera: la
    credencial en keyring se borra aparte, desde app/correo.py, antes de
    llamar aquí."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM correo_mensajes WHERE cuenta_id = ?", (cuenta_id,))
        conn.execute("DELETE FROM correo_carpetas WHERE cuenta_id = ?", (cuenta_id,))
        conn.execute("DELETE FROM correo_cuentas WHERE id = ?", (cuenta_id,))
        conn.commit()
    finally:
        conn.close()


def guardar_firma_correo(cuenta_id: int, firma_html: str | None, firma_en_nuevos: bool, firma_en_respuestas: bool) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE correo_cuentas SET firma_html = ?, firma_en_nuevos = ?, firma_en_respuestas = ?
               WHERE id = ?""",
            (firma_html, int(firma_en_nuevos), int(firma_en_respuestas), cuenta_id),
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

def crear_categoria_correo(nombre: str, color: str) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO correo_categorias (nombre, color, creada_en) VALUES (?, ?, ?)",
            (nombre.strip(), color, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_categorias_correo() -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM correo_categorias ORDER BY nombre").fetchall()
    finally:
        conn.close()


def eliminar_categoria_correo(categoria_id: int) -> None:
    """Los mensajes que la tuvieran asignada se quedan sin categoría
    (ON DELETE SET NULL en el esquema)."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM correo_categorias WHERE id = ?", (categoria_id,))
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


# --- Preferencias generales de Correo (una sola fila) -------------------------

def obtener_preferencias_correo() -> sqlite3.Row:
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO correo_preferencias (id) VALUES (1)")
        conn.commit()
        return conn.execute("SELECT * FROM correo_preferencias WHERE id = 1").fetchone()
    finally:
        conn.close()


def guardar_preferencias_correo(densidad: str, marcar_leido_automatico: bool, limite_mensajes: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE correo_preferencias
               SET densidad = ?, marcar_leido_automatico = ?, limite_mensajes = ? WHERE id = 1""",
            (densidad, int(marcar_leido_automatico), limite_mensajes),
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
) -> None:
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
            f"""SELECT * FROM correo_mensajes WHERE {where}
                ORDER BY (fecha IS NULL), fecha DESC LIMIT ?""",
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


# --- Papelera ----------------------------------------------------------------

def papelera() -> list[dict]:
    """Menús, tareas/eventos y notas que están en la papelera, más recientes primero."""
    conn = get_connection()
    try:
        filas = conn.execute(
            """
            SELECT * FROM (
                SELECT 'menu' AS origen, c.id AS id, c.nombre AS texto, NULL AS tipo,
                       NULL AS categoria_nombre, NULL AS categoria_color, c.papelera_en AS papelera_en
                FROM categorias c
                WHERE c.papelera_en IS NOT NULL

                UNION ALL

                SELECT 'tarea' AS origen, t.id AS id, t.nombre AS texto, t.tipo AS tipo,
                       c.nombre AS categoria_nombre, c.color AS categoria_color, t.papelera_en AS papelera_en
                FROM tareas t JOIN categorias c ON c.id = t.categoria_id
                WHERE t.papelera_en IS NOT NULL

                UNION ALL

                SELECT 'nota' AS origen, n.id AS id, n.texto AS texto, NULL AS tipo,
                       c.nombre AS categoria_nombre, c.color AS categoria_color, n.papelera_en AS papelera_en
                FROM notas n LEFT JOIN categorias c ON c.id = n.categoria_id
                WHERE n.papelera_en IS NOT NULL

                UNION ALL

                SELECT 'tarea_outlook' AS origen, tk.id AS id, tk.asunto AS texto, NULL AS tipo,
                       tk.categoria_outlook AS categoria_nombre, NULL AS categoria_color, tk.papelera_en AS papelera_en
                FROM tareas_outlook tk
                WHERE tk.papelera_en IS NOT NULL
            )
            ORDER BY papelera_en DESC
            """
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def vaciar_papelera_antigua(dias: int = 30) -> None:
    """Purga definitivamente (sin posibilidad de recuperar) lo que lleva en
    la papelera más de `dias` días. Se llama al arrancar la app, igual que
    la copia de seguridad."""
    conn = get_connection()
    try:
        limite = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
        ids_categorias = [
            r["id"] for r in conn.execute(
                "SELECT id FROM categorias WHERE papelera_en IS NOT NULL AND papelera_en < ?", (limite,)
            )
        ]
        ids_tareas = [
            r["id"] for r in conn.execute(
                "SELECT id FROM tareas WHERE papelera_en IS NOT NULL AND papelera_en < ?", (limite,)
            )
        ]
        ids_notas = [
            r["id"] for r in conn.execute(
                "SELECT id FROM notas WHERE papelera_en IS NOT NULL AND papelera_en < ?", (limite,)
            )
        ]
        ids_tareas_outlook = [
            r["id"] for r in conn.execute(
                "SELECT id FROM tareas_outlook WHERE papelera_en IS NOT NULL AND papelera_en < ?", (limite,)
            )
        ]
    finally:
        conn.close()

    for nid in ids_notas:
        eliminar_nota_definitivamente(nid)
    for tid in ids_tareas:
        eliminar_tarea_definitivamente(tid)
    for cid in ids_categorias:
        eliminar_categoria_definitivamente(cid)
    for tid in ids_tareas_outlook:
        eliminar_tarea_outlook_definitivamente(tid)


# --- Asistente IA (OpenRouter): preferencias y conversación -------------------

def obtener_preferencias_ia() -> sqlite3.Row:
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO ia_preferencias (id) VALUES (1)")
        conn.commit()
        return conn.execute("SELECT * FROM ia_preferencias WHERE id = 1").fetchone()
    finally:
        conn.close()


def guardar_preferencias_ia(modelo: str, modo_autonomo: bool) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE ia_preferencias SET modelo = ?, modo_autonomo = ? WHERE id = 1",
            (modelo, int(modo_autonomo)),
        )
        conn.commit()
    finally:
        conn.close()


def listar_mensajes_ia() -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM ia_mensajes ORDER BY id").fetchall()
    finally:
        conn.close()


def agregar_mensaje_ia(
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
               (rol, contenido, tool_calls_json, tool_call_id, nombre_herramienta, creado_en)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (rol, contenido, tool_calls_json, tool_call_id, nombre_herramienta, now_iso()),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def vaciar_mensajes_ia() -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM ia_mensajes")
        conn.commit()
    finally:
        conn.close()
