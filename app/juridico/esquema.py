"""Esquema SQLite del asistente jurídico (tablas `jur_*`). Aditivo e idempotente: se aplica cada vez que arranca la base.

Corpus compartido (sin `tenant_id`): fuentes, políticas, documentos, versiones, fragmentos, relaciones, registros de ingesta. Lo privado de cada despacho (adjuntos, conversaciones, ejecuciones,
citas, informes, auditoría) lleva `tenant_id` y sus consultas empiezan siempre por él."""
from __future__ import annotations

ESQUEMA = """
CREATE TABLE IF NOT EXISTS jur_fuentes (
    id TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    url TEXT,
    conector TEXT NOT NULL,
    coleccion TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'activo', 'incidencia', 'demo')),
    habilitada INTEGER NOT NULL DEFAULT 0 CHECK (habilitada IN (0, 1)),
    acceso TEXT NOT NULL DEFAULT 'explicito' CHECK (acceso IN ('todos', 'explicito')),
    cobertura TEXT,
    ultimo_exito_en TEXT,
    creada_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jur_politicas (
    id INTEGER PRIMARY KEY,
    fuente_id TEXT NOT NULL REFERENCES jur_fuentes(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    evidencia TEXT NOT NULL,
    vigente_desde TEXT NOT NULL,
    permite_almacenar INTEGER NOT NULL DEFAULT 0,
    permite_indexar INTEGER NOT NULL DEFAULT 0,
    permite_enviar_llm INTEGER NOT NULL DEFAULT 0,
    permite_citar INTEGER NOT NULL DEFAULT 0,
    permite_exportar INTEGER NOT NULL DEFAULT 0,
    atribucion TEXT,
    restricciones TEXT,
    registrada_por INTEGER,
    registrada_en TEXT NOT NULL,
    UNIQUE (fuente_id, version)
);
CREATE TABLE IF NOT EXISTS jur_fuente_despacho (
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    fuente_id TEXT NOT NULL REFERENCES jur_fuentes(id) ON DELETE CASCADE,
    habilitada INTEGER NOT NULL DEFAULT 1 CHECK (habilitada IN (0, 1)),
    PRIMARY KEY (tenant_id, fuente_id)
);
CREATE TABLE IF NOT EXISTS jur_documentos (
    id INTEGER PRIMARY KEY,
    fuente_id TEXT NOT NULL REFERENCES jur_fuentes(id) ON DELETE CASCADE,
    id_externo TEXT NOT NULL,
    coleccion TEXT NOT NULL,
    titulo TEXT NOT NULL,
    materia TEXT,
    emisor TEXT,
    territorio TEXT,
    rango TEXT,
    tipo TEXT,
    url_canonica TEXT,
    ecli TEXT,
    roj TEXT,
    eli TEXT,
    celex TEXT,
    estado_normativo TEXT,
    fecha_publicacion TEXT,
    fecha_resolucion TEXT,
    idioma TEXT NOT NULL DEFAULT 'es',
    creado_en TEXT NOT NULL,
    UNIQUE (fuente_id, id_externo)
);
CREATE INDEX IF NOT EXISTS jur_documentos_coleccion ON jur_documentos (coleccion, fecha_publicacion);
CREATE INDEX IF NOT EXISTS jur_documentos_ecli ON jur_documentos (ecli);
CREATE INDEX IF NOT EXISTS jur_documentos_eli ON jur_documentos (eli);
CREATE TABLE IF NOT EXISTS jur_originales (
    hash TEXT PRIMARY KEY,
    fuente_id TEXT NOT NULL,
    url TEXT,
    tipo_mime TEXT,
    contenido BLOB NOT NULL,
    capturado_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jur_versiones (
    id INTEGER PRIMARY KEY,
    documento_id INTEGER NOT NULL REFERENCES jur_documentos(id) ON DELETE CASCADE,
    hash_texto TEXT NOT NULL,
    hash_original TEXT,
    fecha_publicacion TEXT,
    fecha_resolucion TEXT,
    capturada_en TEXT NOT NULL,
    calidad TEXT NOT NULL DEFAULT 'ok',
    politica_version INTEGER,
    activa INTEGER NOT NULL DEFAULT 0 CHECK (activa IN (0, 1)),
    bloqueada INTEGER NOT NULL DEFAULT 0 CHECK (bloqueada IN (0, 1)),
    motivo_bloqueo TEXT,
    UNIQUE (documento_id, hash_texto)
);
CREATE INDEX IF NOT EXISTS jur_versiones_activa ON jur_versiones (documento_id, activa);
CREATE TABLE IF NOT EXISTS jur_fragmentos (
    id INTEGER PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES jur_versiones(id) ON DELETE CASCADE,
    orden INTEGER NOT NULL,
    bloque_id TEXT,
    localizador TEXT NOT NULL,
    texto TEXT NOT NULL,
    hash TEXT NOT NULL,
    vigente_desde TEXT,
    vigente_hasta TEXT,
    vigencia_origen TEXT,
    embedding BLOB,
    embedding_modelo TEXT
);
CREATE INDEX IF NOT EXISTS jur_fragmentos_version ON jur_fragmentos (version_id, orden);
CREATE VIRTUAL TABLE IF NOT EXISTS jur_fragmentos_fts USING fts5(
    texto, localizador, content='jur_fragmentos', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS jur_fragmentos_ai AFTER INSERT ON jur_fragmentos BEGIN
    INSERT INTO jur_fragmentos_fts (rowid, texto, localizador) VALUES (new.id, new.texto, new.localizador);
END;
CREATE TRIGGER IF NOT EXISTS jur_fragmentos_ad AFTER DELETE ON jur_fragmentos BEGIN
    INSERT INTO jur_fragmentos_fts (jur_fragmentos_fts, rowid, texto, localizador) VALUES ('delete', old.id, old.texto, old.localizador);
END;
CREATE TABLE IF NOT EXISTS jur_relaciones (
    id INTEGER PRIMARY KEY,
    documento_id INTEGER NOT NULL REFERENCES jur_documentos(id) ON DELETE CASCADE,
    destino_externo TEXT NOT NULL,
    destino_documento_id INTEGER REFERENCES jur_documentos(id) ON DELETE SET NULL,
    tipo TEXT NOT NULL,
    evidencia TEXT,
    verificada INTEGER NOT NULL DEFAULT 0,
    UNIQUE (documento_id, destino_externo, tipo)
);
CREATE TABLE IF NOT EXISTS jur_registros_fuente (
    id INTEGER PRIMARY KEY,
    fuente_id TEXT NOT NULL REFERENCES jur_fuentes(id) ON DELETE CASCADE,
    id_externo TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'DISCOVERED' CHECK (estado IN ('DISCOVERED', 'FETCH_PENDING', 'FETCHED', 'PARSED', 'VALIDATED', 'INDEX_PENDING', 'INDEXED', 'PUBLISHED',
                                                                   'RETRYABLE_ERROR', 'QUARANTINED', 'BLOCKED_POLICY', 'WITHDRAWN')),
    revision_origen TEXT,
    localizador TEXT,
    documento_id INTEGER REFERENCES jur_documentos(id) ON DELETE SET NULL,
    intentos INTEGER NOT NULL DEFAULT 0,
    ultimo_error TEXT,
    descubierto_en TEXT NOT NULL,
    actualizado_en TEXT NOT NULL,
    UNIQUE (fuente_id, id_externo)
);
CREATE INDEX IF NOT EXISTS jur_registros_estado ON jur_registros_fuente (fuente_id, estado);
CREATE TABLE IF NOT EXISTS jur_sync_runs (
    id INTEGER PRIMARY KEY,
    fuente_id TEXT NOT NULL REFERENCES jur_fuentes(id) ON DELETE CASCADE,
    desde TEXT,
    hasta TEXT,
    estado TEXT NOT NULL DEFAULT 'en_curso' CHECK (estado IN ('en_curso', 'completa', 'parcial', 'fallida', 'bloqueada')),
    cursor TEXT,
    contadores TEXT,
    error TEXT,
    iniciada_en TEXT NOT NULL,
    terminada_en TEXT
);
CREATE TABLE IF NOT EXISTS jur_outbox (
    id INTEGER PRIMARY KEY,
    sync_run_id INTEGER REFERENCES jur_sync_runs(id) ON DELETE SET NULL,
    fuente_id TEXT NOT NULL,
    id_externo TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'procesar',
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'hecho')),
    creada_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jur_outbox_pendiente ON jur_outbox (estado, id);
CREATE TABLE IF NOT EXISTS jur_cobertura (
    id INTEGER PRIMARY KEY,
    fuente_id TEXT NOT NULL REFERENCES jur_fuentes(id) ON DELETE CASCADE,
    capturada_en TEXT NOT NULL,
    datos TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jur_auditoria (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER,
    actor_id INTEGER,
    accion TEXT NOT NULL,
    recurso TEXT,
    detalle TEXT,
    creada_en TEXT NOT NULL
);
"""

# Colecciones del módulo (el tipo de documento); materia, órgano y territorio son campos distintos.
COLECCIONES = {
    "legislacion": "Legislación",
    "jurisprudencia": "Jurisprudencia",
    "doctrina": "Doctrina administrativa",
}


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)
    from . import privado
    privado.crear_esquema(conn)
