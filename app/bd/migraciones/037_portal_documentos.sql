-- «Mis documentos» del portal: qué documentos del expediente ve el cliente, en qué carpeta, quién los puso, cuándo caducan y el texto para buscar
ALTER TABLE cliente_documentos ADD COLUMN IF NOT EXISTS portal_visible bigint NOT NULL DEFAULT 0;
ALTER TABLE cliente_documentos ADD COLUMN IF NOT EXISTS portal_carpeta text;
ALTER TABLE cliente_documentos ADD COLUMN IF NOT EXISTS portal_origen text;
ALTER TABLE cliente_documentos ADD COLUMN IF NOT EXISTS portal_vence text;
ALTER TABLE cliente_documentos ADD COLUMN IF NOT EXISTS portal_texto text;
