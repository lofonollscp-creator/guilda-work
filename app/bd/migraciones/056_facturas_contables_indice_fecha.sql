-- Índice para listar las facturas para contabilizar del despacho por fecha (la lista de todos los clientes ordenaba todas las filas).
CREATE INDEX IF NOT EXISTS idx_facturas_contables_fecha ON facturas_contables(tenant_id, fecha DESC, id DESC);
