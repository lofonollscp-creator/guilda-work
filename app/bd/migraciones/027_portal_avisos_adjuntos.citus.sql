-- Idempotente: una base nueva ya nace con estas tablas distribuidas (esquema base generado); una existente las distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_novedades'::regclass) THEN
    PERFORM create_distributed_table('portal_novedades', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE portal_novedades DROP CONSTRAINT IF EXISTS fk_portal_novedades_tenant_id;
ALTER TABLE portal_novedades ADD CONSTRAINT fk_portal_novedades_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_novedades_lectura'::regclass) THEN
    PERFORM create_distributed_table('portal_novedades_lectura', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE portal_novedades_lectura DROP CONSTRAINT IF EXISTS fk_portal_novedades_lectura_tenant_id;
ALTER TABLE portal_novedades_lectura ADD CONSTRAINT fk_portal_novedades_lectura_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_conversaciones_adjuntos'::regclass) THEN
    PERFORM create_distributed_table('portal_conversaciones_adjuntos', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE portal_conversaciones_adjuntos DROP CONSTRAINT IF EXISTS fk_portal_conversaciones_adjuntos_tenant_id;
ALTER TABLE portal_conversaciones_adjuntos ADD CONSTRAINT fk_portal_conversaciones_adjuntos_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
