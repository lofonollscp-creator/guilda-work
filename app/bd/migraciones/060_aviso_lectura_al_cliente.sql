-- Aviso opcional al cliente cuando una factura que subió él mismo desde el portal queda leída (solo en los clientes en los que el despacho lo active)
ALTER TABLE contabilidad_clientes ADD COLUMN IF NOT EXISTS avisar_lectura bigint NOT NULL DEFAULT 0;
