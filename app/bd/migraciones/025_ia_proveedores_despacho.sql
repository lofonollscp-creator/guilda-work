-- IA: proveedores con clave del despacho (OpenAI, Claude…), normas del despacho, uso y coste por proveedor, y el proveedor elegido por cada persona
ALTER TABLE ia_preferencias ADD COLUMN IF NOT EXISTS proveedor_ia text NOT NULL DEFAULT 'openrouter';
CREATE TABLE IF NOT EXISTS ia_proveedores_despacho (
    tenant_id bigint,
    proveedor text,
    activo bigint NOT NULL DEFAULT 0,
    orden bigint NOT NULL DEFAULT 0,
    modelo_asistente text NOT NULL DEFAULT '',
    modelo_facturas text NOT NULL DEFAULT '',
    url_base text NOT NULL DEFAULT '',
    claves_resumen text NOT NULL DEFAULT '[]',
    actualizado_por bigint,
    actualizado_en text NOT NULL,
    PRIMARY KEY (tenant_id, proveedor)
);
CREATE TABLE IF NOT EXISTS ia_config_despacho (
    tenant_id bigint,
    solo_ue bigint NOT NULL DEFAULT 0,
    claves_personales bigint NOT NULL DEFAULT 1,
    facturas_modo text NOT NULL DEFAULT 'compartida',
    umbral_confianza bigint NOT NULL DEFAULT 90,
    actualizado_por bigint,
    actualizado_en text NOT NULL,
    PRIMARY KEY (tenant_id),
    CHECK (facturas_modo IN ('compartida', 'auto'))
);
CREATE TABLE IF NOT EXISTS ia_uso_proveedor (
    tenant_id bigint,
    mes text,
    proveedor text,
    tarea text,
    origen text,
    llamadas bigint NOT NULL DEFAULT 0,
    tokens_entrada bigint NOT NULL DEFAULT 0,
    tokens_salida bigint NOT NULL DEFAULT 0,
    coste_usd double precision NOT NULL DEFAULT 0,
    llamadas_sin_tarifa bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, mes, proveedor, tarea, origen)
);
