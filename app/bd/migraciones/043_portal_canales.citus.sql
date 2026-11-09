-- Idempotente: una base nueva ya nace con las tablas distribuidas (esquema base generado); una existente las distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_canales_config'::regclass) THEN
    PERFORM create_distributed_table('portal_canales_config', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE portal_canales_config DROP CONSTRAINT IF EXISTS fk_portal_canales_config_tenant_id;
ALTER TABLE portal_canales_config ADD CONSTRAINT fk_portal_canales_config_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_canales_personas'::regclass) THEN
    PERFORM create_distributed_table('portal_canales_personas', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE portal_canales_personas DROP CONSTRAINT IF EXISTS fk_portal_canales_personas_tenant_id;
ALTER TABLE portal_canales_personas ADD CONSTRAINT fk_portal_canales_personas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_canales_envios'::regclass) THEN
    PERFORM create_distributed_table('portal_canales_envios', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE portal_canales_envios DROP CONSTRAINT IF EXISTS fk_portal_canales_envios_tenant_id;
ALTER TABLE portal_canales_envios ADD CONSTRAINT fk_portal_canales_envios_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
