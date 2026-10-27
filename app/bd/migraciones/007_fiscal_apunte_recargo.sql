-- Apunte fiscal: recargo de equivalencia que el cliente repercute en sus facturas emitidas (casillas 16 a 26 del 303)
ALTER TABLE fiscal_apuntes ADD COLUMN IF NOT EXISTS recargo_pct_centesimas bigint NOT NULL DEFAULT 0;
ALTER TABLE fiscal_apuntes ADD COLUMN IF NOT EXISTS recargo_cuota_centimos bigint NOT NULL DEFAULT 0;
