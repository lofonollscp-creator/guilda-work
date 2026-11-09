-- Embudo de uso del portal para el despacho (opcional, apagado por defecto)
ALTER TABLE portal_recordatorios_config ADD COLUMN IF NOT EXISTS embudo_uso bigint NOT NULL DEFAULT 0;
