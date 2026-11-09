-- No molestar de los avisos al móvil del portal
CREATE TABLE IF NOT EXISTS portal_silencios (
    tenant_id bigint,
    cliente_fiscal_id bigint,
    email text,
    desde text NOT NULL,
    hasta text NOT NULL,
    actualizado_en text NOT NULL,
    PRIMARY KEY (tenant_id, cliente_fiscal_id, email)
);
