-- IA: «voz del despacho», el tono que la IA imita al redactar respuestas de correo (ajustes de IA de la dirección).
ALTER TABLE ia_config_despacho ADD COLUMN IF NOT EXISTS voz text NOT NULL DEFAULT '';
