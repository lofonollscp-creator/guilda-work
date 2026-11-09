-- Alta guiada: documentos que se piden al dar de alta con una plantilla y si se invita al portal
ALTER TABLE plantillas_cliente ADD COLUMN IF NOT EXISTS peticiones text NOT NULL DEFAULT '[]';
ALTER TABLE plantillas_cliente ADD COLUMN IF NOT EXISTS invitar_portal bigint NOT NULL DEFAULT 0;
