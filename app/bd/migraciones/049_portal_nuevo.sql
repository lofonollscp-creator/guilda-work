-- Portal de clientes con la navegación nueva: interruptor por despacho (apagado por defecto).
ALTER TABLE portal_recordatorios_config ADD COLUMN IF NOT EXISTS portal_nuevo integer NOT NULL DEFAULT 0;
