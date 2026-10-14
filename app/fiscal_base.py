"""Cimientos del control fiscal (fase A de la especificación): columnas y tablas nuevas sobre las de siempre, sin tocar lo existente.

- `clientes_fiscales`: identificación normalizada con índice único parcial (ver `fiscal_identidad`), `oficina_id` (oficina principal) y `version` (control de concurrencia).
- `vencimientos_fiscales`: `fase` (flujo de trabajo; el `estado` de siempre sigue siendo la proyección que leen pantallas, API y recordatorios), `presentada_tarde`,
  `bloqueada`, `version`, `rectifica_a` (una rectificación se vincula a su obligación original y no choca con la unicidad) e índice único por cliente + modelo + período.
- Tablas: oficinas, membresías (rol + alcance), concesiones de cliente, evidencias de presentación y configuración fiscal por despacho.

La migración es idempotente y **nunca falla por datos antiguos**: si ya hubiera duplicados, el más antiguo se queda como está y los demás se marcan (duplicado autorizado por
la migración / rectificación de la original) para poder crear el índice sin perder ni borrar nada."""
from __future__ import annotations

from . import db, fiscal_identidad

ESQUEMA = """
CREATE TABLE IF NOT EXISTS oficinas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    activa INTEGER NOT NULL DEFAULT 1,
    creado_en TEXT NOT NULL,
    UNIQUE (tenant_id, nombre)
);
CREATE TABLE IF NOT EXISTS membresias (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    rol TEXT NOT NULL CHECK (rol IN ('coordinador', 'gestor', 'revisor_fiscal', 'auditor')),
    alcance_tipo TEXT NOT NULL CHECK (alcance_tipo IN ('organizacion', 'oficina', 'cliente')),
    alcance_id INTEGER,
    vigente_desde TEXT NOT NULL,
    vigente_hasta TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    revocada_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_membresias_usuario ON membresias(tenant_id, usuario_id, revocada_en);
CREATE TABLE IF NOT EXISTS concesiones_cliente (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id),
    oficina_id INTEGER REFERENCES oficinas(id) ON DELETE CASCADE,
    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
    nivel TEXT NOT NULL DEFAULT 'gestion' CHECK (nivel IN ('lectura', 'gestion')),
    vigente_hasta TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    revocada_en TEXT,
    CHECK ((oficina_id IS NOT NULL) != (usuario_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_concesiones_cliente ON concesiones_cliente(cliente_fiscal_id, revocada_en);
CREATE TABLE IF NOT EXISTS obligaciones_evidencias (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    vencimiento_id INTEGER NOT NULL REFERENCES vencimientos_fiscales(id) ON DELETE CASCADE,
    presentado_en TEXT NOT NULL,
    organismo TEXT,
    referencia TEXT,
    documento_id INTEGER,
    procedencia TEXT NOT NULL DEFAULT 'declarada_por_gestor' CHECK (procedencia IN ('declarada_por_gestor', 'integracion')),
    declarada_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidencias_venc ON obligaciones_evidencias(vencimiento_id);
CREATE TABLE IF NOT EXISTS fiscal_config (
    tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    flujo_estricto INTEGER NOT NULL DEFAULT 0,
    exigir_justificante INTEGER NOT NULL DEFAULT 0
);
"""

NOTA_DUPLICADO_MIGRACION = "Duplicado anterior a la regla de unicidad (migración): revisar y, si procede, fusionar."


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)
    for col, tipo in (("nif_normalizado", "TEXT"), ("nif_duplicado_autorizado", "TEXT"), ("version", "INTEGER NOT NULL DEFAULT 1"), ("oficina_id", "INTEGER REFERENCES oficinas(id)")):
        db._asegurar_columna(conn, "clientes_fiscales", col, tipo)
    for col, tipo in (("fase", "TEXT NOT NULL DEFAULT 'pendiente'"), ("fase_motivo", "TEXT"), ("presentada_tarde", "INTEGER NOT NULL DEFAULT 0"), ("bloqueada", "INTEGER NOT NULL DEFAULT 0"),
                      ("bloqueo_motivo", "TEXT"), ("version", "INTEGER NOT NULL DEFAULT 1"), ("rectifica_a", "INTEGER REFERENCES vencimientos_fiscales(id)")):
        db._asegurar_columna(conn, "vencimientos_fiscales", col, tipo)
    conn.execute("UPDATE vencimientos_fiscales SET fase = 'presentada' WHERE estado = 'presentado' AND fase NOT IN ('presentada', 'cerrada')")
    _normalizar_identificaciones(conn)
    _resolver_duplicados_de_vencimientos(conn)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_clientes_fiscales_nif_unico ON clientes_fiscales(tenant_id, pais, nif_normalizado) "
                 "WHERE papelera_en IS NULL AND nif_normalizado IS NOT NULL AND nif_duplicado_autorizado IS NULL")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_vencimientos_unico ON vencimientos_fiscales(cliente_fiscal_id, modelo, periodo) WHERE papelera_en IS NULL AND rectifica_a IS NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_clientes_fiscales_oficina ON clientes_fiscales(tenant_id, oficina_id)")


def _normalizar_identificaciones(conn) -> None:
    for f in conn.execute("SELECT id, nif, pais FROM clientes_fiscales WHERE nif_normalizado IS NULL AND nif IS NOT NULL AND nif != ''").fetchall():
        clave = fiscal_identidad.clave_unica(f["nif"], f["pais"])
        if clave:
            conn.execute("UPDATE clientes_fiscales SET nif_normalizado = ? WHERE id = ?", (clave, f["id"]))
    duplicados = conn.execute("SELECT tenant_id, pais, nif_normalizado FROM clientes_fiscales WHERE papelera_en IS NULL AND nif_normalizado IS NOT NULL AND nif_duplicado_autorizado IS NULL "
                              "GROUP BY 1, 2, 3 HAVING COUNT(*) > 1").fetchall()
    for d in duplicados:
        ids = [f["id"] for f in conn.execute("SELECT id FROM clientes_fiscales WHERE tenant_id = ? AND pais = ? AND nif_normalizado = ? AND papelera_en IS NULL AND nif_duplicado_autorizado IS NULL ORDER BY id",
                                             (d["tenant_id"], d["pais"], d["nif_normalizado"]))]
        for extra in ids[1:]:
            conn.execute("UPDATE clientes_fiscales SET nif_duplicado_autorizado = ? WHERE id = ?", (NOTA_DUPLICADO_MIGRACION, extra))


def _resolver_duplicados_de_vencimientos(conn) -> None:
    for d in conn.execute("SELECT cliente_fiscal_id, modelo, periodo FROM vencimientos_fiscales WHERE papelera_en IS NULL AND rectifica_a IS NULL GROUP BY 1, 2, 3 HAVING COUNT(*) > 1").fetchall():
        ids = [f["id"] for f in conn.execute("SELECT id FROM vencimientos_fiscales WHERE cliente_fiscal_id = ? AND modelo = ? AND periodo = ? AND papelera_en IS NULL AND rectifica_a IS NULL ORDER BY id",
                                             (d["cliente_fiscal_id"], d["modelo"], d["periodo"]))]
        for extra in ids[1:]:
            conn.execute("UPDATE vencimientos_fiscales SET rectifica_a = ? WHERE id = ?", (ids[0], extra))
