-- Lectura de facturas: confianza de la lectura, de dónde sale (XML, texto del PDF o imagen) y si la dio por revisada la IA
ALTER TABLE facturas_contables ADD COLUMN IF NOT EXISTS lectura_confianza bigint;
ALTER TABLE facturas_contables ADD COLUMN IF NOT EXISTS lectura_fuente text;
ALTER TABLE facturas_contables ADD COLUMN IF NOT EXISTS revision_auto bigint NOT NULL DEFAULT 0;
