-- Contadores de salud del portal desde el navegador (opcional)
CREATE TABLE IF NOT EXISTS portal_telemetria_diaria (
    tenant_id bigint,
    dia text,
    ruta text,
    tipo text,
    detalle text DEFAULT '',
    n bigint NOT NULL DEFAULT 0,
    suma_ms bigint NOT NULL DEFAULT 0,
    max_ms bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, dia, ruta, tipo, detalle),
    CHECK (tipo IN ('carga', 'error'))
);
