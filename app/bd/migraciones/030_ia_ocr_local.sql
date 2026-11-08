-- OCR local por despacho: no usarlo, de respaldo (si el modelo no puede leer la imagen) o «nada sale del servidor».
-- En Citus la restricción va aparte y con nombre.
ALTER TABLE ia_config_despacho ADD COLUMN IF NOT EXISTS ocr_local text NOT NULL DEFAULT 'respaldo';
ALTER TABLE ia_config_despacho DROP CONSTRAINT IF EXISTS ia_config_despacho_ocr_local_chk;
ALTER TABLE ia_config_despacho ADD CONSTRAINT ia_config_despacho_ocr_local_chk CHECK (ocr_local IN ('no', 'respaldo', 'solo_local'));
