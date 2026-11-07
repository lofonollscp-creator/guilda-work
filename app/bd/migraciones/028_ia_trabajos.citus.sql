-- Idempotente: una base nueva ya nace con esta tabla distribuida (esquema base generado); una existente la distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'ia_trabajos'::regclass) THEN
    PERFORM create_distributed_table('ia_trabajos', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE ia_trabajos DROP CONSTRAINT IF EXISTS fk_ia_trabajos_tenant_id;
ALTER TABLE ia_trabajos ADD CONSTRAINT fk_ia_trabajos_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
