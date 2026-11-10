-- L4: releer con un segundo modelo las facturas dudosas (opcional, por despacho). J3: cuándo se comprobó con lo que devolvió a3 que una factura exportada está contabilizada.
ALTER TABLE ia_config_despacho ADD COLUMN IF NOT EXISTS segunda_lectura integer NOT NULL DEFAULT 0;
ALTER TABLE facturas_contables ADD COLUMN IF NOT EXISTS confirmada_en text;
ALTER TABLE contabilidad_lotes ADD COLUMN IF NOT EXISTS comprobado_en text;
ALTER TABLE contabilidad_lotes ADD COLUMN IF NOT EXISTS n_confirmadas integer;
