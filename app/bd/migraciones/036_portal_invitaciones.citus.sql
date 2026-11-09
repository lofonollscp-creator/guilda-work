-- Idempotente: una base nueva ya nace con las tablas distribuidas (esquema base generado); una existente las distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_invitaciones_cola'::regclass) THEN
    PERFORM create_distributed_table('portal_invitaciones_cola', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE portal_invitaciones_cola DROP CONSTRAINT IF EXISTS fk_portal_invitaciones_cola_tenant_id;
ALTER TABLE portal_invitaciones_cola ADD CONSTRAINT fk_portal_invitaciones_cola_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
