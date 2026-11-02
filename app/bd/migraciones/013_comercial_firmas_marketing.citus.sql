-- Idempotente: una base nueva ya nace con estas tablas distribuidas (esquema base generado); una existente las distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'documentos_plantillas'::regclass) THEN
    PERFORM create_distributed_table('documentos_plantillas', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'documentos_firma'::regclass) THEN
    PERFORM create_distributed_table('documentos_firma', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'crm_acciones_masivas'::regclass) THEN
    PERFORM create_distributed_table('crm_acciones_masivas', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'marketing_contactos'::regclass) THEN
    PERFORM create_distributed_table('marketing_contactos', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'marketing_grupos'::regclass) THEN
    PERFORM create_distributed_table('marketing_grupos', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'marketing_plantillas'::regclass) THEN
    PERFORM create_distributed_table('marketing_plantillas', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'marketing_envios'::regclass) THEN
    PERFORM create_distributed_table('marketing_envios', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'marketing_envio_destinatarios'::regclass) THEN
    PERFORM create_distributed_table('marketing_envio_destinatarios', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- claves foráneas, ya con las tablas distribuidas (en mt llano las puso 013….mt.sql)
ALTER TABLE crm_acciones_masivas DROP CONSTRAINT IF EXISTS fk_crm_acciones_masivas_tenant_id;
ALTER TABLE crm_acciones_masivas ADD CONSTRAINT fk_crm_acciones_masivas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
ALTER TABLE crm_acciones_masivas DROP CONSTRAINT IF EXISTS fk_crm_acciones_masivas_usuario_id;
ALTER TABLE crm_acciones_masivas ADD CONSTRAINT fk_crm_acciones_masivas_usuario_id FOREIGN KEY (usuario_id) REFERENCES usuarios (id);
ALTER TABLE documentos_firma DROP CONSTRAINT IF EXISTS fk_documentos_firma_cliente_id;
ALTER TABLE documentos_firma ADD CONSTRAINT fk_documentos_firma_cliente_id FOREIGN KEY (tenant_id, cliente_id) REFERENCES clientes (tenant_id, id) ON DELETE CASCADE;
ALTER TABLE documentos_firma DROP CONSTRAINT IF EXISTS fk_documentos_firma_creado_por;
ALTER TABLE documentos_firma ADD CONSTRAINT fk_documentos_firma_creado_por FOREIGN KEY (creado_por) REFERENCES usuarios (id);
ALTER TABLE documentos_firma DROP CONSTRAINT IF EXISTS fk_documentos_firma_tenant_id;
ALTER TABLE documentos_firma ADD CONSTRAINT fk_documentos_firma_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
ALTER TABLE documentos_plantillas DROP CONSTRAINT IF EXISTS fk_documentos_plantillas_actualizado_por;
ALTER TABLE documentos_plantillas ADD CONSTRAINT fk_documentos_plantillas_actualizado_por FOREIGN KEY (actualizado_por) REFERENCES usuarios (id);
ALTER TABLE documentos_plantillas DROP CONSTRAINT IF EXISTS fk_documentos_plantillas_tenant_id;
ALTER TABLE documentos_plantillas ADD CONSTRAINT fk_documentos_plantillas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
ALTER TABLE marketing_contactos DROP CONSTRAINT IF EXISTS fk_marketing_contactos_cliente_id;
ALTER TABLE marketing_contactos ADD CONSTRAINT fk_marketing_contactos_cliente_id FOREIGN KEY (tenant_id, cliente_id) REFERENCES clientes (tenant_id, id);
ALTER TABLE marketing_contactos DROP CONSTRAINT IF EXISTS fk_marketing_contactos_registrado_por;
ALTER TABLE marketing_contactos ADD CONSTRAINT fk_marketing_contactos_registrado_por FOREIGN KEY (registrado_por) REFERENCES usuarios (id);
ALTER TABLE marketing_contactos DROP CONSTRAINT IF EXISTS fk_marketing_contactos_tenant_id;
ALTER TABLE marketing_contactos ADD CONSTRAINT fk_marketing_contactos_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
ALTER TABLE marketing_envio_destinatarios DROP CONSTRAINT IF EXISTS fk_marketing_envio_destinatarios_envio_id;
ALTER TABLE marketing_envio_destinatarios ADD CONSTRAINT fk_marketing_envio_destinatarios_envio_id FOREIGN KEY (tenant_id, envio_id) REFERENCES marketing_envios (tenant_id, id) ON DELETE CASCADE;
ALTER TABLE marketing_envio_destinatarios DROP CONSTRAINT IF EXISTS fk_marketing_envio_destinatarios_tenant_id;
ALTER TABLE marketing_envio_destinatarios ADD CONSTRAINT fk_marketing_envio_destinatarios_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
ALTER TABLE marketing_envios DROP CONSTRAINT IF EXISTS fk_marketing_envios_creado_por;
ALTER TABLE marketing_envios ADD CONSTRAINT fk_marketing_envios_creado_por FOREIGN KEY (creado_por) REFERENCES usuarios (id);
ALTER TABLE marketing_envios DROP CONSTRAINT IF EXISTS fk_marketing_envios_grupo_id;
ALTER TABLE marketing_envios ADD CONSTRAINT fk_marketing_envios_grupo_id FOREIGN KEY (tenant_id, grupo_id) REFERENCES marketing_grupos (tenant_id, id);
ALTER TABLE marketing_envios DROP CONSTRAINT IF EXISTS fk_marketing_envios_programado_por;
ALTER TABLE marketing_envios ADD CONSTRAINT fk_marketing_envios_programado_por FOREIGN KEY (programado_por) REFERENCES usuarios (id);
ALTER TABLE marketing_envios DROP CONSTRAINT IF EXISTS fk_marketing_envios_tenant_id;
ALTER TABLE marketing_envios ADD CONSTRAINT fk_marketing_envios_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
ALTER TABLE marketing_grupos DROP CONSTRAINT IF EXISTS fk_marketing_grupos_creado_por;
ALTER TABLE marketing_grupos ADD CONSTRAINT fk_marketing_grupos_creado_por FOREIGN KEY (creado_por) REFERENCES usuarios (id);
ALTER TABLE marketing_grupos DROP CONSTRAINT IF EXISTS fk_marketing_grupos_tenant_id;
ALTER TABLE marketing_grupos ADD CONSTRAINT fk_marketing_grupos_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
ALTER TABLE marketing_plantillas DROP CONSTRAINT IF EXISTS fk_marketing_plantillas_creado_por;
ALTER TABLE marketing_plantillas ADD CONSTRAINT fk_marketing_plantillas_creado_por FOREIGN KEY (creado_por) REFERENCES usuarios (id);
ALTER TABLE marketing_plantillas DROP CONSTRAINT IF EXISTS fk_marketing_plantillas_tenant_id;
ALTER TABLE marketing_plantillas ADD CONSTRAINT fk_marketing_plantillas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
-- disparadores de ON DELETE SET NULL, ya con las tablas distribuidas (en mt llano los puso 013….mt.sql)
SET citus.enable_unsafe_triggers = on;
CREATE OR REPLACE FUNCTION fk_set_null_clientes() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE contactos SET cliente_id = NULL WHERE tenant_id = OLD.tenant_id AND cliente_id = OLD.id;
    UPDATE crm_actividades SET cliente_id = NULL WHERE tenant_id = OLD.tenant_id AND cliente_id = OLD.id;
    UPDATE crm_oportunidades SET cliente_id = NULL WHERE tenant_id = OLD.tenant_id AND cliente_id = OLD.id;
    UPDATE crm_reuniones SET cliente_id = NULL WHERE tenant_id = OLD.tenant_id AND cliente_id = OLD.id;
    UPDATE jur_adjuntos SET cliente_id = NULL WHERE tenant_id = OLD.tenant_id AND cliente_id = OLD.id;
    UPDATE jur_conversaciones SET cliente_id = NULL WHERE tenant_id = OLD.tenant_id AND cliente_id = OLD.id;
    UPDATE jur_informes SET cliente_id = NULL WHERE tenant_id = OLD.tenant_id AND cliente_id = OLD.id;
    UPDATE marketing_contactos SET cliente_id = NULL WHERE tenant_id = OLD.tenant_id AND cliente_id = OLD.id;
    RETURN OLD;
END $$;
CREATE OR REPLACE FUNCTION fk_set_null_marketing_grupos() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE marketing_envios SET grupo_id = NULL WHERE tenant_id = OLD.tenant_id AND grupo_id = OLD.id;
    RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS fk_set_null ON marketing_grupos;
CREATE TRIGGER fk_set_null BEFORE DELETE ON marketing_grupos FOR EACH ROW EXECUTE FUNCTION fk_set_null_marketing_grupos();
