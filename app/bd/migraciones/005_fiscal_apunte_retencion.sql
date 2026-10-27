-- Apunte fiscal: retención de IRPF que practica el cliente (modelos 111 y 115)
ALTER TABLE fiscal_apuntes ADD COLUMN IF NOT EXISTS retencion_modelo text NOT NULL DEFAULT '';
ALTER TABLE fiscal_apuntes ADD COLUMN IF NOT EXISTS retencion_clave text NOT NULL DEFAULT '';
ALTER TABLE fiscal_apuntes ADD COLUMN IF NOT EXISTS retencion_base_centimos bigint;
ALTER TABLE fiscal_apuntes ADD COLUMN IF NOT EXISTS retencion_pct_centesimas bigint;
ALTER TABLE fiscal_apuntes ADD COLUMN IF NOT EXISTS retencion_centimos bigint;
