-- Idempotente: una base nueva ya nace con estas tablas distribuidas (esquema base generado); una existente las distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'fiscal_perfiles'::regclass) THEN
    PERFORM create_distributed_table('fiscal_perfiles', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'fiscal_relaciones'::regclass) THEN
    PERFORM create_distributed_table('fiscal_relaciones', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- claves foráneas, ya con las tablas distribuidas (en mt llano las puso 002….mt.sql)
ALTER TABLE fiscal_perfiles   DROP CONSTRAINT IF EXISTS fk_fiscal_perfiles_cliente;
ALTER TABLE fiscal_perfiles   ADD  CONSTRAINT fk_fiscal_perfiles_cliente   FOREIGN KEY (tenant_id, cliente_fiscal_id) REFERENCES clientes_fiscales (tenant_id, id) ON DELETE CASCADE;
ALTER TABLE fiscal_relaciones DROP CONSTRAINT IF EXISTS fk_fiscal_relaciones_desde;
ALTER TABLE fiscal_relaciones ADD  CONSTRAINT fk_fiscal_relaciones_desde   FOREIGN KEY (tenant_id, desde_cliente_id) REFERENCES clientes_fiscales (tenant_id, id) ON DELETE CASCADE;
ALTER TABLE fiscal_relaciones DROP CONSTRAINT IF EXISTS fk_fiscal_relaciones_hasta;
ALTER TABLE fiscal_relaciones ADD  CONSTRAINT fk_fiscal_relaciones_hasta   FOREIGN KEY (tenant_id, hasta_cliente_id) REFERENCES clientes_fiscales (tenant_id, id) ON DELETE CASCADE;
ALTER TABLE fiscal_perfiles   DROP CONSTRAINT IF EXISTS fk_fiscal_perfiles_tenant;
ALTER TABLE fiscal_perfiles   ADD  CONSTRAINT fk_fiscal_perfiles_tenant   FOREIGN KEY (tenant_id) REFERENCES tenants (id);
ALTER TABLE fiscal_relaciones DROP CONSTRAINT IF EXISTS fk_fiscal_relaciones_tenant;
ALTER TABLE fiscal_relaciones ADD  CONSTRAINT fk_fiscal_relaciones_tenant FOREIGN KEY (tenant_id) REFERENCES tenants (id);
ALTER TABLE fiscal_perfiles   DROP CONSTRAINT IF EXISTS fk_fiscal_perfiles_creado_por;
ALTER TABLE fiscal_perfiles   ADD  CONSTRAINT fk_fiscal_perfiles_creado_por   FOREIGN KEY (creado_por) REFERENCES usuarios (id);
ALTER TABLE fiscal_relaciones DROP CONSTRAINT IF EXISTS fk_fiscal_relaciones_creado_por;
ALTER TABLE fiscal_relaciones ADD  CONSTRAINT fk_fiscal_relaciones_creado_por FOREIGN KEY (creado_por) REFERENCES usuarios (id);
