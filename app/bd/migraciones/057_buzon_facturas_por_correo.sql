-- Buzón de facturas por correo: cuenta y dirección del despacho, y por cliente si está activado y su código (solo los clientes que el despacho active).
ALTER TABLE contabilidad_clientes ADD COLUMN IF NOT EXISTS buzon_activo bigint NOT NULL DEFAULT 0;
ALTER TABLE contabilidad_clientes ADD COLUMN IF NOT EXISTS buzon_codigo text;
ALTER TABLE contabilidad_despacho ADD COLUMN IF NOT EXISTS buzon_cuenta_id bigint;
ALTER TABLE contabilidad_despacho ADD COLUMN IF NOT EXISTS buzon_direccion text;
