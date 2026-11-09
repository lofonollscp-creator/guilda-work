-- Salud del portal desde el navegador: activar por despacho (apagado por defecto)
ALTER TABLE portal_recordatorios_config ADD COLUMN IF NOT EXISTS telemetria bigint NOT NULL DEFAULT 0;
