-- Idempotente: una base nueva ya nace con esta tabla distribuida (esquema base generado); una existente la distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'justificantes_pendientes'::regclass) THEN
    PERFORM create_distributed_table('justificantes_pendientes', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 020….mt.sql)
ALTER TABLE justificantes_pendientes DROP CONSTRAINT IF EXISTS fk_justificantes_pendientes_tenant_id;
ALTER TABLE justificantes_pendientes ADD CONSTRAINT fk_justificantes_pendientes_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
