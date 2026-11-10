-- a3: plan de cuentas completo de cada cliente (para avisar de cuentas que no existen), estado de cada fichero (lo que dice la persona tras importarlo), formato del fichero de enlace por cliente y por despacho (512 = SII, 256 = clásico), impreso de cada línea (110, 115, 347, 349…) y datos de ampliación de la factura (bien de inversión, DUA, clave del 340, 347…).
ALTER TABLE contabilidad_clientes ADD COLUMN IF NOT EXISTS formato_enlace text NOT NULL DEFAULT '512';
ALTER TABLE contabilidad_despacho ADD COLUMN IF NOT EXISTS formato_enlace text NOT NULL DEFAULT '512';
ALTER TABLE facturas_contables ADD COLUMN IF NOT EXISTS datos_a3 text;
ALTER TABLE facturas_contables_lineas ADD COLUMN IF NOT EXISTS impreso text;
ALTER TABLE contabilidad_lotes ADD COLUMN IF NOT EXISTS estado_a3 text;
ALTER TABLE contabilidad_lotes ADD COLUMN IF NOT EXISTS motivo_a3 text;
ALTER TABLE contabilidad_lotes ADD COLUMN IF NOT EXISTS estado_a3_en text;
ALTER TABLE contabilidad_clientes ADD COLUMN IF NOT EXISTS plan_cuentas text;
