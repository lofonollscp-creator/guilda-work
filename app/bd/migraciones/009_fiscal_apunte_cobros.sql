-- Apunte fiscal: cobros o pagos con su fecha (criterio de caja del IVA, clave 07)
ALTER TABLE fiscal_apuntes ADD COLUMN IF NOT EXISTS cobros_json text;
