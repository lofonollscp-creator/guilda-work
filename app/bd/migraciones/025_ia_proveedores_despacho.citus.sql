-- Idempotente: una base nueva ya nace con estas tablas distribuidas (esquema base generado); una existente las distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'ia_proveedores_despacho'::regclass) THEN
    PERFORM create_distributed_table('ia_proveedores_despacho', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE ia_proveedores_despacho DROP CONSTRAINT IF EXISTS fk_ia_proveedores_despacho_tenant_id;
ALTER TABLE ia_proveedores_despacho ADD CONSTRAINT fk_ia_proveedores_despacho_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'ia_config_despacho'::regclass) THEN
    PERFORM create_distributed_table('ia_config_despacho', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE ia_config_despacho DROP CONSTRAINT IF EXISTS fk_ia_config_despacho_tenant_id;
ALTER TABLE ia_config_despacho ADD CONSTRAINT fk_ia_config_despacho_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'ia_uso_proveedor'::regclass) THEN
    PERFORM create_distributed_table('ia_uso_proveedor', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE ia_uso_proveedor DROP CONSTRAINT IF EXISTS fk_ia_uso_proveedor_tenant_id;
ALTER TABLE ia_uso_proveedor ADD CONSTRAINT fk_ia_uso_proveedor_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
