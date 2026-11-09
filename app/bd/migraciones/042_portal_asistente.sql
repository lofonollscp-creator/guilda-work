-- Asistente del portal para el cliente: activarlo por despacho (apagado por defecto)
ALTER TABLE portal_recordatorios_config ADD COLUMN IF NOT EXISTS asistente_cliente bigint NOT NULL DEFAULT 0;
