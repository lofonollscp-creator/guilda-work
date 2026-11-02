-- Idempotente: una base nueva ya nace con estas tablas distribuidas (esquema base generado); una existente las distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'marketing_rebotes'::regclass) THEN
    PERFORM create_distributed_table('marketing_rebotes', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'marketing_proveedores'::regclass) THEN
    PERFORM create_distributed_table('marketing_proveedores', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- claves foráneas, ya con las tablas distribuidas (en mt llano las puso 013….mt.sql)
ALTER TABLE marketing_proveedores DROP CONSTRAINT IF EXISTS fk_marketing_proveedores_actualizado_por;
ALTER TABLE marketing_proveedores ADD CONSTRAINT fk_marketing_proveedores_actualizado_por FOREIGN KEY (actualizado_por) REFERENCES usuarios (id);
ALTER TABLE marketing_proveedores DROP CONSTRAINT IF EXISTS fk_marketing_proveedores_tenant_id;
ALTER TABLE marketing_proveedores ADD CONSTRAINT fk_marketing_proveedores_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
ALTER TABLE marketing_rebotes DROP CONSTRAINT IF EXISTS fk_marketing_rebotes_tenant_id;
ALTER TABLE marketing_rebotes ADD CONSTRAINT fk_marketing_rebotes_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
