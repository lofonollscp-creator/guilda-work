-- Idempotente: una base nueva ya nace con estas tablas distribuidas (esquema base generado); una existente las distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_conversaciones'::regclass) THEN
    PERFORM create_distributed_table('portal_conversaciones', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE portal_conversaciones DROP CONSTRAINT IF EXISTS fk_portal_conversaciones_tenant_id;
ALTER TABLE portal_conversaciones ADD CONSTRAINT fk_portal_conversaciones_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_conversaciones_mensajes'::regclass) THEN
    PERFORM create_distributed_table('portal_conversaciones_mensajes', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE portal_conversaciones_mensajes DROP CONSTRAINT IF EXISTS fk_portal_conversaciones_mensajes_tenant_id;
ALTER TABLE portal_conversaciones_mensajes ADD CONSTRAINT fk_portal_conversaciones_mensajes_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
