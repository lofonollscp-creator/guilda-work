-- Idempotente: una base nueva ya nace con estas tablas distribuidas (esquema base generado); una existente las distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'honorarios_reglas'::regclass) THEN
    PERFORM create_distributed_table('honorarios_reglas', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'honorarios_aplicados'::regclass) THEN
    PERFORM create_distributed_table('honorarios_aplicados', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'fiscal_acciones_masivas'::regclass) THEN
    PERFORM create_distributed_table('fiscal_acciones_masivas', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- claves foráneas, ya con las tablas distribuidas (en mt llano las puso 015….mt.sql)
ALTER TABLE fiscal_acciones_masivas DROP CONSTRAINT IF EXISTS fk_fiscal_acciones_masivas_tenant_id;
ALTER TABLE fiscal_acciones_masivas ADD CONSTRAINT fk_fiscal_acciones_masivas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
ALTER TABLE fiscal_acciones_masivas DROP CONSTRAINT IF EXISTS fk_fiscal_acciones_masivas_usuario_id;
ALTER TABLE fiscal_acciones_masivas ADD CONSTRAINT fk_fiscal_acciones_masivas_usuario_id FOREIGN KEY (usuario_id) REFERENCES usuarios (id);
ALTER TABLE honorarios_aplicados DROP CONSTRAINT IF EXISTS fk_honorarios_aplicados_tenant_id;
ALTER TABLE honorarios_aplicados ADD CONSTRAINT fk_honorarios_aplicados_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
ALTER TABLE honorarios_reglas DROP CONSTRAINT IF EXISTS fk_honorarios_reglas_tenant_id;
ALTER TABLE honorarios_reglas ADD CONSTRAINT fk_honorarios_reglas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
