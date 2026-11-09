-- Idempotente: una base nueva ya nace con las tablas distribuidas (esquema base generado); una existente las distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_enlaces_compartidos'::regclass) THEN
    PERFORM create_distributed_table('portal_enlaces_compartidos', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE portal_enlaces_compartidos DROP CONSTRAINT IF EXISTS fk_portal_enlaces_compartidos_tenant_id;
ALTER TABLE portal_enlaces_compartidos ADD CONSTRAINT fk_portal_enlaces_compartidos_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
