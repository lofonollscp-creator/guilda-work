-- Factura contable: de dónde sacó la IA cada dato leído (fragmento citado y recuadro sobre la imagen)
ALTER TABLE facturas_contables ADD COLUMN IF NOT EXISTS lectura_evidencia text;
