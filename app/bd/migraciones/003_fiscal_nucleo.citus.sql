SET citus.enable_unsafe_triggers = on;
-- Idempotente: una base nueva ya nace con estas tablas distribuidas (esquema base generado); una existente las distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'fiscal_instantaneas'::regclass) THEN
    PERFORM create_distributed_table('fiscal_instantaneas', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'fiscal_apuntes'::regclass) THEN
    PERFORM create_distributed_table('fiscal_apuntes', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'fiscal_declaraciones'::regclass) THEN
    PERFORM create_distributed_table('fiscal_declaraciones', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'fiscal_casillas'::regclass) THEN
    PERFORM create_distributed_table('fiscal_casillas', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'fiscal_artefactos'::regclass) THEN
    PERFORM create_distributed_table('fiscal_artefactos', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- claves foráneas, ya con las tablas distribuidas (en mt llano las puso 003….mt.sql)
ALTER TABLE fiscal_instantaneas DROP CONSTRAINT IF EXISTS fk_fiscal_instantaneas_aprobada_por;
ALTER TABLE fiscal_instantaneas ADD CONSTRAINT fk_fiscal_instantaneas_aprobada_por FOREIGN KEY (aprobada_por) REFERENCES usuarios (id);
ALTER TABLE fiscal_instantaneas DROP CONSTRAINT IF EXISTS fk_fiscal_instantaneas_cliente_fiscal_id;
ALTER TABLE fiscal_instantaneas ADD CONSTRAINT fk_fiscal_instantaneas_cliente_fiscal_id FOREIGN KEY (tenant_id, cliente_fiscal_id) REFERENCES clientes_fiscales (tenant_id, id) ON DELETE CASCADE;
ALTER TABLE fiscal_instantaneas DROP CONSTRAINT IF EXISTS fk_fiscal_instantaneas_sustituye_a_id;
ALTER TABLE fiscal_instantaneas ADD CONSTRAINT fk_fiscal_instantaneas_sustituye_a_id FOREIGN KEY (tenant_id, sustituye_a_id) REFERENCES fiscal_instantaneas (tenant_id, id);
ALTER TABLE fiscal_instantaneas DROP CONSTRAINT IF EXISTS fk_fiscal_instantaneas_tenant_id;
ALTER TABLE fiscal_instantaneas ADD CONSTRAINT fk_fiscal_instantaneas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id);
ALTER TABLE fiscal_apuntes DROP CONSTRAINT IF EXISTS fk_fiscal_apuntes_aprobado_por;
ALTER TABLE fiscal_apuntes ADD CONSTRAINT fk_fiscal_apuntes_aprobado_por FOREIGN KEY (aprobado_por) REFERENCES usuarios (id);
ALTER TABLE fiscal_apuntes DROP CONSTRAINT IF EXISTS fk_fiscal_apuntes_cliente_fiscal_id;
ALTER TABLE fiscal_apuntes ADD CONSTRAINT fk_fiscal_apuntes_cliente_fiscal_id FOREIGN KEY (tenant_id, cliente_fiscal_id) REFERENCES clientes_fiscales (tenant_id, id) ON DELETE CASCADE;
ALTER TABLE fiscal_apuntes DROP CONSTRAINT IF EXISTS fk_fiscal_apuntes_factura_id;
ALTER TABLE fiscal_apuntes ADD CONSTRAINT fk_fiscal_apuntes_factura_id FOREIGN KEY (tenant_id, factura_id) REFERENCES facturas_contables (tenant_id, id);
ALTER TABLE fiscal_apuntes DROP CONSTRAINT IF EXISTS fk_fiscal_apuntes_tenant_id;
ALTER TABLE fiscal_apuntes ADD CONSTRAINT fk_fiscal_apuntes_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id);
ALTER TABLE fiscal_declaraciones DROP CONSTRAINT IF EXISTS fk_fiscal_declaraciones_cliente_fiscal_id;
ALTER TABLE fiscal_declaraciones ADD CONSTRAINT fk_fiscal_declaraciones_cliente_fiscal_id FOREIGN KEY (tenant_id, cliente_fiscal_id) REFERENCES clientes_fiscales (tenant_id, id) ON DELETE CASCADE;
ALTER TABLE fiscal_declaraciones DROP CONSTRAINT IF EXISTS fk_fiscal_declaraciones_creado_por;
ALTER TABLE fiscal_declaraciones ADD CONSTRAINT fk_fiscal_declaraciones_creado_por FOREIGN KEY (creado_por) REFERENCES usuarios (id);
ALTER TABLE fiscal_declaraciones DROP CONSTRAINT IF EXISTS fk_fiscal_declaraciones_instantanea_id;
ALTER TABLE fiscal_declaraciones ADD CONSTRAINT fk_fiscal_declaraciones_instantanea_id FOREIGN KEY (tenant_id, instantanea_id) REFERENCES fiscal_instantaneas (tenant_id, id);
ALTER TABLE fiscal_declaraciones DROP CONSTRAINT IF EXISTS fk_fiscal_declaraciones_rectifica_a_id;
ALTER TABLE fiscal_declaraciones ADD CONSTRAINT fk_fiscal_declaraciones_rectifica_a_id FOREIGN KEY (tenant_id, rectifica_a_id) REFERENCES fiscal_declaraciones (tenant_id, id);
ALTER TABLE fiscal_declaraciones DROP CONSTRAINT IF EXISTS fk_fiscal_declaraciones_revisada_por;
ALTER TABLE fiscal_declaraciones ADD CONSTRAINT fk_fiscal_declaraciones_revisada_por FOREIGN KEY (revisada_por) REFERENCES usuarios (id);
ALTER TABLE fiscal_declaraciones DROP CONSTRAINT IF EXISTS fk_fiscal_declaraciones_tenant_id;
ALTER TABLE fiscal_declaraciones ADD CONSTRAINT fk_fiscal_declaraciones_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id);
ALTER TABLE fiscal_declaraciones DROP CONSTRAINT IF EXISTS fk_fiscal_declaraciones_vencimiento_id;
ALTER TABLE fiscal_declaraciones ADD CONSTRAINT fk_fiscal_declaraciones_vencimiento_id FOREIGN KEY (tenant_id, vencimiento_id) REFERENCES vencimientos_fiscales (tenant_id, id);
ALTER TABLE fiscal_casillas DROP CONSTRAINT IF EXISTS fk_fiscal_casillas_declaracion_id;
ALTER TABLE fiscal_casillas ADD CONSTRAINT fk_fiscal_casillas_declaracion_id FOREIGN KEY (tenant_id, declaracion_id) REFERENCES fiscal_declaraciones (tenant_id, id) ON DELETE CASCADE;
ALTER TABLE fiscal_casillas DROP CONSTRAINT IF EXISTS fk_fiscal_casillas_tenant_id;
ALTER TABLE fiscal_casillas ADD CONSTRAINT fk_fiscal_casillas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id);
ALTER TABLE fiscal_artefactos DROP CONSTRAINT IF EXISTS fk_fiscal_artefactos_creado_por;
ALTER TABLE fiscal_artefactos ADD CONSTRAINT fk_fiscal_artefactos_creado_por FOREIGN KEY (creado_por) REFERENCES usuarios (id);
ALTER TABLE fiscal_artefactos DROP CONSTRAINT IF EXISTS fk_fiscal_artefactos_declaracion_id;
ALTER TABLE fiscal_artefactos ADD CONSTRAINT fk_fiscal_artefactos_declaracion_id FOREIGN KEY (tenant_id, declaracion_id) REFERENCES fiscal_declaraciones (tenant_id, id) ON DELETE CASCADE;
ALTER TABLE fiscal_artefactos DROP CONSTRAINT IF EXISTS fk_fiscal_artefactos_tenant_id;
ALTER TABLE fiscal_artefactos ADD CONSTRAINT fk_fiscal_artefactos_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id);
