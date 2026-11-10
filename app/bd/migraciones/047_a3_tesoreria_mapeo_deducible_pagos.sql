-- a3: cuenta de tesorería por cliente y por despacho (asientos de cobro y pago), mapeo de columnas del retorno recordado por cliente, IVA parcialmente deducible en la regla del proveedor y marca de factura ya pagada en un fichero.
ALTER TABLE contabilidad_clientes ADD COLUMN IF NOT EXISTS cuenta_tesoreria text NOT NULL DEFAULT '57200000';
ALTER TABLE contabilidad_clientes ADD COLUMN IF NOT EXISTS columnas_retorno text;
ALTER TABLE contabilidad_despacho ADD COLUMN IF NOT EXISTS cuenta_tesoreria text NOT NULL DEFAULT '57200000';
ALTER TABLE facturas_contables ADD COLUMN IF NOT EXISTS pago_exportado_en text;
ALTER TABLE contabilidad_reglas ADD COLUMN IF NOT EXISTS pct_deducible integer;
ALTER TABLE contabilidad_lotes ADD COLUMN IF NOT EXISTS clase text;
