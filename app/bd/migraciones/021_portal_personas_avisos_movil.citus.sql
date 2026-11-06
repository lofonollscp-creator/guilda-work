-- Idempotente: una base nueva ya nace con estas tablas distribuidas (esquema base generado); una existente las distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_avisos_enviados'::regclass) THEN
    PERFORM create_distributed_table('portal_avisos_enviados', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_contactos'::regclass) THEN
    PERFORM create_distributed_table('portal_contactos', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_enlaces_subida'::regclass) THEN
    PERFORM create_distributed_table('portal_enlaces_subida', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_respuestas_rapidas'::regclass) THEN
    PERFORM create_distributed_table('portal_respuestas_rapidas', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_suscripciones_push'::regclass) THEN
    PERFORM create_distributed_table('portal_suscripciones_push', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- claves foráneas, ya con las tablas distribuidas (en mt llano las puso 021….mt.sql)
ALTER TABLE portal_avisos_enviados DROP CONSTRAINT IF EXISTS fk_portal_avisos_enviados_tenant_id;
ALTER TABLE portal_avisos_enviados ADD CONSTRAINT fk_portal_avisos_enviados_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
ALTER TABLE portal_contactos DROP CONSTRAINT IF EXISTS fk_portal_contactos_tenant_id;
ALTER TABLE portal_contactos ADD CONSTRAINT fk_portal_contactos_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
ALTER TABLE portal_enlaces_subida DROP CONSTRAINT IF EXISTS fk_portal_enlaces_subida_tenant_id;
ALTER TABLE portal_enlaces_subida ADD CONSTRAINT fk_portal_enlaces_subida_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
ALTER TABLE portal_respuestas_rapidas DROP CONSTRAINT IF EXISTS fk_portal_respuestas_rapidas_tenant_id;
ALTER TABLE portal_respuestas_rapidas ADD CONSTRAINT fk_portal_respuestas_rapidas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
ALTER TABLE portal_suscripciones_push DROP CONSTRAINT IF EXISTS fk_portal_suscripciones_push_tenant_id;
ALTER TABLE portal_suscripciones_push ADD CONSTRAINT fk_portal_suscripciones_push_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
