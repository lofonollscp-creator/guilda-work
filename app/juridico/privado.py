"""Lo privado de cada despacho en el asistente jurídico: adjuntos y sus fragmentos, conversaciones, ejecuciones de consulta, afirmaciones, citas e informes.
Todas estas tablas llevan `tenant_id` y toda consulta empieza por él. Los adjuntos **nunca** entran en el corpus común."""
from __future__ import annotations

ESQUEMA = """
CREATE TABLE IF NOT EXISTS jur_adjuntos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    subido_por INTEGER NOT NULL,
    cliente_id INTEGER REFERENCES clientes(id) ON DELETE SET NULL,
    expediente_id INTEGER,
    nombre TEXT NOT NULL,
    tipo_mime TEXT,
    tamano INTEGER NOT NULL,
    hash TEXT NOT NULL,
    contenido BLOB,
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'lista', 'fallida')),
    error TEXT,
    retener_hasta TEXT,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jur_adjuntos_tenant ON jur_adjuntos (tenant_id, cliente_id);
CREATE TABLE IF NOT EXISTS jur_fragmentos_privados (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    adjunto_id INTEGER NOT NULL REFERENCES jur_adjuntos(id) ON DELETE CASCADE,
    orden INTEGER NOT NULL,
    localizador TEXT NOT NULL,
    texto TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jur_fragmentos_privados_adjunto ON jur_fragmentos_privados (tenant_id, adjunto_id, orden);
CREATE VIRTUAL TABLE IF NOT EXISTS jur_fragmentos_privados_fts USING fts5(
    texto, content='jur_fragmentos_privados', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS jur_fragmentos_privados_ai AFTER INSERT ON jur_fragmentos_privados BEGIN
    INSERT INTO jur_fragmentos_privados_fts (rowid, texto) VALUES (new.id, new.texto);
END;
CREATE TRIGGER IF NOT EXISTS jur_fragmentos_privados_ad AFTER DELETE ON jur_fragmentos_privados BEGIN
    INSERT INTO jur_fragmentos_privados_fts (jur_fragmentos_privados_fts, rowid, texto) VALUES ('delete', old.id, old.texto);
END;
CREATE TABLE IF NOT EXISTS jur_conversaciones (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    propietario_id INTEGER NOT NULL,
    cliente_id INTEGER REFERENCES clientes(id) ON DELETE SET NULL,
    expediente_id INTEGER,
    titulo TEXT,
    creada_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jur_conversaciones_tenant ON jur_conversaciones (tenant_id, propietario_id);
CREATE TABLE IF NOT EXISTS jur_ejecuciones (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversacion_id INTEGER NOT NULL REFERENCES jur_conversaciones(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL,
    clave_idempotencia TEXT,
    pregunta TEXT NOT NULL,
    filtros TEXT,
    fecha_juridica TEXT,
    objetivo TEXT NOT NULL DEFAULT 'consulta',
    estado TEXT NOT NULL DEFAULT 'en_curso' CHECK (estado IN ('en_curso', 'answered', 'needs_context', 'insufficient_evidence', 'failed', 'cancelada')),
    respuesta TEXT,
    modelo TEXT,
    prompt_version TEXT,
    latencia_ms INTEGER,
    traza TEXT,
    error TEXT,
    creada_en TEXT NOT NULL,
    terminada_en TEXT,
    UNIQUE (tenant_id, usuario_id, clave_idempotencia)
);
CREATE TABLE IF NOT EXISTS jur_afirmaciones (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    ejecucion_id INTEGER NOT NULL REFERENCES jur_ejecuciones(id) ON DELETE CASCADE,
    texto TEXT NOT NULL,
    evaluacion TEXT NOT NULL DEFAULT 'sin_evaluar'
);
CREATE TABLE IF NOT EXISTS jur_citas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    ejecucion_id INTEGER NOT NULL REFERENCES jur_ejecuciones(id) ON DELETE CASCADE,
    afirmacion_id INTEGER REFERENCES jur_afirmaciones(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL CHECK (tipo IN ('legal_source', 'private_attachment')),
    fragmento_id INTEGER,
    fragmento_privado_id INTEGER,
    version_id INTEGER,
    documento_id INTEGER,
    adjunto_id INTEGER,
    localizador TEXT NOT NULL,
    extracto TEXT NOT NULL,
    url_canonica TEXT,
    CHECK ((tipo = 'legal_source' AND fragmento_id IS NOT NULL AND fragmento_privado_id IS NULL)
           OR (tipo = 'private_attachment' AND fragmento_privado_id IS NOT NULL AND fragmento_id IS NULL))
);
CREATE TABLE IF NOT EXISTS jur_informes (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    ejecucion_id INTEGER NOT NULL REFERENCES jur_ejecuciones(id) ON DELETE CASCADE,
    cliente_id INTEGER REFERENCES clientes(id) ON DELETE SET NULL,
    expediente_id INTEGER,
    titulo TEXT NOT NULL,
    instantanea TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador', 'revisado', 'archivado')),
    creado_por INTEGER NOT NULL,
    revisado_por INTEGER,
    revisado_en TEXT,
    creado_en TEXT NOT NULL,
    aviso_fuente TEXT
);
CREATE INDEX IF NOT EXISTS jur_informes_tenant ON jur_informes (tenant_id, expediente_id);
"""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


TABLAS_DEL_DESPACHO = ("jur_citas", "jur_afirmaciones", "jur_informes", "jur_ejecuciones", "jur_conversaciones", "jur_fragmentos_privados", "jur_adjuntos")


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    """Borra todo lo privado del despacho (orden por dependencias). El corpus común no se toca."""
    for tabla in TABLAS_DEL_DESPACHO:
        conn.execute(f"DELETE FROM {tabla} WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM jur_fuente_despacho WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM jur_auditoria WHERE tenant_id = ?", (tenant_id,))
