-- Idempotente: una base nueva ya nace con estas tablas distribuidas (esquema base generado); una existente las distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'tenants_verticales_historial'::regclass) THEN
    PERFORM create_distributed_table('tenants_verticales_historial', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- claves foráneas, ya con las tablas distribuidas (en mt llano las puso 016….mt.sql)
ALTER TABLE tenants_verticales_historial DROP CONSTRAINT IF EXISTS fk_tenants_verticales_historial_tenant_id;
ALTER TABLE tenants_verticales_historial ADD CONSTRAINT fk_tenants_verticales_historial_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
