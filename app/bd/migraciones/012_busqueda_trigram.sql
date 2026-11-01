-- Índices trigram para la búsqueda de clientes y expedientes (plano() cualificada para poder indexarse)
CREATE OR REPLACE FUNCTION plano(text) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$ SELECT lower(public.f_unaccent(coalesce($1, ''))) $$;

CREATE INDEX IF NOT EXISTS idx_trgm_clientes_nombre ON clientes USING gin (plano(nombre) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_trgm_clientes_nif ON clientes USING gin (plano(nif) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_trgm_clientes_email ON clientes USING gin (plano(email) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_trgm_clientes_telefono ON clientes USING gin (plano(telefono) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_trgm_contactos_nombre ON cliente_contactos USING gin (plano(nombre) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_trgm_contactos_email ON cliente_contactos USING gin (plano(email) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_trgm_expedientes_titulo ON expedientes USING gin (plano(titulo) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_trgm_expedientes_referencia ON expedientes USING gin (plano(referencia) gin_trgm_ops);
