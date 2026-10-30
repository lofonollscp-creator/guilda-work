-- Idempotente: una base nueva ya nace con esta tabla distribuida (esquema base generado); una existente la distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'fiscal_apuntes_recurrentes'::regclass) THEN
    PERFORM create_distributed_table('fiscal_apuntes_recurrentes', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea del titular, ya con la tabla distribuida (en mt llano la puso 011….mt.sql)
ALTER TABLE fiscal_apuntes_recurrentes DROP CONSTRAINT IF EXISTS fk_fiscal_apuntes_recurrentes_cliente_fiscal_id;
ALTER TABLE fiscal_apuntes_recurrentes ADD CONSTRAINT fk_fiscal_apuntes_recurrentes_cliente_fiscal_id FOREIGN KEY (tenant_id, cliente_fiscal_id) REFERENCES clientes_fiscales (tenant_id, id) ON DELETE CASCADE;
ALTER TABLE fiscal_apuntes_recurrentes DROP CONSTRAINT IF EXISTS fk_fiscal_apuntes_recurrentes_creado_por;
ALTER TABLE fiscal_apuntes_recurrentes ADD CONSTRAINT fk_fiscal_apuntes_recurrentes_creado_por FOREIGN KEY (creado_por) REFERENCES usuarios (id);
ALTER TABLE fiscal_apuntes_recurrentes DROP CONSTRAINT IF EXISTS fk_fiscal_apuntes_recurrentes_tenant_id;
ALTER TABLE fiscal_apuntes_recurrentes ADD CONSTRAINT fk_fiscal_apuntes_recurrentes_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id);
