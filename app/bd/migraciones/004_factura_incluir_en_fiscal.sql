-- Factura contable: elegir si cuenta para Guilda Fiscal (los modelos de impuestos)
ALTER TABLE facturas_contables ADD COLUMN IF NOT EXISTS incluir_en_fiscal bigint NOT NULL DEFAULT 1;
