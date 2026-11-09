-- Idempotente: una base nueva ya nace con las tablas distribuidas (esquema base generado); una existente las distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_ventas_clientes'::regclass) THEN
    PERFORM create_distributed_table('portal_ventas_clientes', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE portal_ventas_clientes DROP CONSTRAINT IF EXISTS fk_portal_ventas_clientes_tenant_id;
ALTER TABLE portal_ventas_clientes ADD CONSTRAINT fk_portal_ventas_clientes_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_ventas_facturas'::regclass) THEN
    PERFORM create_distributed_table('portal_ventas_facturas', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE portal_ventas_facturas DROP CONSTRAINT IF EXISTS fk_portal_ventas_facturas_tenant_id;
ALTER TABLE portal_ventas_facturas ADD CONSTRAINT fk_portal_ventas_facturas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
