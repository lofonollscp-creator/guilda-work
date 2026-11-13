-- Idempotente: una base nueva ya nace con esta tabla distribuida (esquema base generado); una existente la distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'banco_movimientos'::regclass) THEN
    PERFORM create_distributed_table('banco_movimientos', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE banco_movimientos DROP CONSTRAINT IF EXISTS fk_banco_movimientos_tenant_id;
ALTER TABLE banco_movimientos ADD CONSTRAINT fk_banco_movimientos_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
