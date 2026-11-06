-- Idempotente: una base nueva ya nace con esta tabla distribuida (esquema base generado); una existente la distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_segundo_factor'::regclass) THEN
    PERFORM create_distributed_table('portal_segundo_factor', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE portal_segundo_factor DROP CONSTRAINT IF EXISTS fk_portal_segundo_factor_tenant_id;
ALTER TABLE portal_segundo_factor ADD CONSTRAINT fk_portal_segundo_factor_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_sesiones'::regclass) THEN
    PERFORM create_distributed_table('portal_sesiones', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE portal_sesiones DROP CONSTRAINT IF EXISTS fk_portal_sesiones_tenant_id;
ALTER TABLE portal_sesiones ADD CONSTRAINT fk_portal_sesiones_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
