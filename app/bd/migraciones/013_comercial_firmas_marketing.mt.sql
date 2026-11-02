-- (despacho: tenant_id con su valor por defecto, clave primaria con tenant_id, claves foráneas, disparadores de ON DELETE SET NULL, RLS y permisos). Idempotente también sobre tablas ya distribuidas (una base nueva nace con ellas)
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'documentos_plantillas' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE documentos_plantillas ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'documentos_plantillas'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE documentos_plantillas DROP CONSTRAINT IF EXISTS documentos_plantillas_pkey;
    ALTER TABLE documentos_plantillas ADD CONSTRAINT documentos_plantillas_pkey PRIMARY KEY (tenant_id, clave);
  END IF;
END $$;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'documentos_firma' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE documentos_firma ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'documentos_firma'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE documentos_firma DROP CONSTRAINT IF EXISTS documentos_firma_pkey;
    ALTER TABLE documentos_firma ADD CONSTRAINT documentos_firma_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'crm_acciones_masivas' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE crm_acciones_masivas ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'crm_acciones_masivas'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE crm_acciones_masivas DROP CONSTRAINT IF EXISTS crm_acciones_masivas_pkey;
    ALTER TABLE crm_acciones_masivas ADD CONSTRAINT crm_acciones_masivas_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'marketing_contactos' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE marketing_contactos ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'marketing_contactos'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE marketing_contactos DROP CONSTRAINT IF EXISTS marketing_contactos_pkey;
    ALTER TABLE marketing_contactos ADD CONSTRAINT marketing_contactos_pkey PRIMARY KEY (tenant_id, email);
  END IF;
END $$;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'marketing_grupos' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE marketing_grupos ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'marketing_grupos'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE marketing_grupos DROP CONSTRAINT IF EXISTS marketing_grupos_pkey;
    ALTER TABLE marketing_grupos ADD CONSTRAINT marketing_grupos_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'marketing_plantillas' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE marketing_plantillas ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'marketing_plantillas'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE marketing_plantillas DROP CONSTRAINT IF EXISTS marketing_plantillas_pkey;
    ALTER TABLE marketing_plantillas ADD CONSTRAINT marketing_plantillas_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'marketing_envios' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE marketing_envios ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'marketing_envios'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE marketing_envios DROP CONSTRAINT IF EXISTS marketing_envios_pkey;
    ALTER TABLE marketing_envios ADD CONSTRAINT marketing_envios_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'marketing_envio_destinatarios' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE marketing_envio_destinatarios ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'marketing_envio_destinatarios'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE marketing_envio_destinatarios DROP CONSTRAINT IF EXISTS marketing_envio_destinatarios_pkey;
    ALTER TABLE marketing_envio_destinatarios ADD CONSTRAINT marketing_envio_destinatarios_pkey PRIMARY KEY (tenant_id, envio_id, email);
  END IF;
END $$;
-- claves foráneas: las de despacho a despacho son compuestas. En Citus se añaden DESPUÉS de distribuir (013….citus.sql).
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE crm_acciones_masivas DROP CONSTRAINT IF EXISTS fk_crm_acciones_masivas_tenant_id$q$;
    EXECUTE $q$ALTER TABLE crm_acciones_masivas ADD CONSTRAINT fk_crm_acciones_masivas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
    EXECUTE $q$ALTER TABLE crm_acciones_masivas DROP CONSTRAINT IF EXISTS fk_crm_acciones_masivas_usuario_id$q$;
    EXECUTE $q$ALTER TABLE crm_acciones_masivas ADD CONSTRAINT fk_crm_acciones_masivas_usuario_id FOREIGN KEY (usuario_id) REFERENCES usuarios (id)$q$;
    EXECUTE $q$ALTER TABLE documentos_firma DROP CONSTRAINT IF EXISTS fk_documentos_firma_cliente_id$q$;
    EXECUTE $q$ALTER TABLE documentos_firma ADD CONSTRAINT fk_documentos_firma_cliente_id FOREIGN KEY (tenant_id, cliente_id) REFERENCES clientes (tenant_id, id) ON DELETE CASCADE$q$;
    EXECUTE $q$ALTER TABLE documentos_firma DROP CONSTRAINT IF EXISTS fk_documentos_firma_creado_por$q$;
    EXECUTE $q$ALTER TABLE documentos_firma ADD CONSTRAINT fk_documentos_firma_creado_por FOREIGN KEY (creado_por) REFERENCES usuarios (id)$q$;
    EXECUTE $q$ALTER TABLE documentos_firma DROP CONSTRAINT IF EXISTS fk_documentos_firma_tenant_id$q$;
    EXECUTE $q$ALTER TABLE documentos_firma ADD CONSTRAINT fk_documentos_firma_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
    EXECUTE $q$ALTER TABLE documentos_plantillas DROP CONSTRAINT IF EXISTS fk_documentos_plantillas_actualizado_por$q$;
    EXECUTE $q$ALTER TABLE documentos_plantillas ADD CONSTRAINT fk_documentos_plantillas_actualizado_por FOREIGN KEY (actualizado_por) REFERENCES usuarios (id)$q$;
    EXECUTE $q$ALTER TABLE documentos_plantillas DROP CONSTRAINT IF EXISTS fk_documentos_plantillas_tenant_id$q$;
    EXECUTE $q$ALTER TABLE documentos_plantillas ADD CONSTRAINT fk_documentos_plantillas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
    EXECUTE $q$ALTER TABLE marketing_contactos DROP CONSTRAINT IF EXISTS fk_marketing_contactos_cliente_id$q$;
    EXECUTE $q$ALTER TABLE marketing_contactos ADD CONSTRAINT fk_marketing_contactos_cliente_id FOREIGN KEY (tenant_id, cliente_id) REFERENCES clientes (tenant_id, id)$q$;
    EXECUTE $q$ALTER TABLE marketing_contactos DROP CONSTRAINT IF EXISTS fk_marketing_contactos_registrado_por$q$;
    EXECUTE $q$ALTER TABLE marketing_contactos ADD CONSTRAINT fk_marketing_contactos_registrado_por FOREIGN KEY (registrado_por) REFERENCES usuarios (id)$q$;
    EXECUTE $q$ALTER TABLE marketing_contactos DROP CONSTRAINT IF EXISTS fk_marketing_contactos_tenant_id$q$;
    EXECUTE $q$ALTER TABLE marketing_contactos ADD CONSTRAINT fk_marketing_contactos_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
    EXECUTE $q$ALTER TABLE marketing_envio_destinatarios DROP CONSTRAINT IF EXISTS fk_marketing_envio_destinatarios_envio_id$q$;
    EXECUTE $q$ALTER TABLE marketing_envio_destinatarios ADD CONSTRAINT fk_marketing_envio_destinatarios_envio_id FOREIGN KEY (tenant_id, envio_id) REFERENCES marketing_envios (tenant_id, id) ON DELETE CASCADE$q$;
    EXECUTE $q$ALTER TABLE marketing_envio_destinatarios DROP CONSTRAINT IF EXISTS fk_marketing_envio_destinatarios_tenant_id$q$;
    EXECUTE $q$ALTER TABLE marketing_envio_destinatarios ADD CONSTRAINT fk_marketing_envio_destinatarios_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
    EXECUTE $q$ALTER TABLE marketing_envios DROP CONSTRAINT IF EXISTS fk_marketing_envios_creado_por$q$;
    EXECUTE $q$ALTER TABLE marketing_envios ADD CONSTRAINT fk_marketing_envios_creado_por FOREIGN KEY (creado_por) REFERENCES usuarios (id)$q$;
    EXECUTE $q$ALTER TABLE marketing_envios DROP CONSTRAINT IF EXISTS fk_marketing_envios_grupo_id$q$;
    EXECUTE $q$ALTER TABLE marketing_envios ADD CONSTRAINT fk_marketing_envios_grupo_id FOREIGN KEY (tenant_id, grupo_id) REFERENCES marketing_grupos (tenant_id, id)$q$;
    EXECUTE $q$ALTER TABLE marketing_envios DROP CONSTRAINT IF EXISTS fk_marketing_envios_programado_por$q$;
    EXECUTE $q$ALTER TABLE marketing_envios ADD CONSTRAINT fk_marketing_envios_programado_por FOREIGN KEY (programado_por) REFERENCES usuarios (id)$q$;
    EXECUTE $q$ALTER TABLE marketing_envios DROP CONSTRAINT IF EXISTS fk_marketing_envios_tenant_id$q$;
    EXECUTE $q$ALTER TABLE marketing_envios ADD CONSTRAINT fk_marketing_envios_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
    EXECUTE $q$ALTER TABLE marketing_grupos DROP CONSTRAINT IF EXISTS fk_marketing_grupos_creado_por$q$;
    EXECUTE $q$ALTER TABLE marketing_grupos ADD CONSTRAINT fk_marketing_grupos_creado_por FOREIGN KEY (creado_por) REFERENCES usuarios (id)$q$;
    EXECUTE $q$ALTER TABLE marketing_grupos DROP CONSTRAINT IF EXISTS fk_marketing_grupos_tenant_id$q$;
    EXECUTE $q$ALTER TABLE marketing_grupos ADD CONSTRAINT fk_marketing_grupos_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
    EXECUTE $q$ALTER TABLE marketing_plantillas DROP CONSTRAINT IF EXISTS fk_marketing_plantillas_creado_por$q$;
    EXECUTE $q$ALTER TABLE marketing_plantillas ADD CONSTRAINT fk_marketing_plantillas_creado_por FOREIGN KEY (creado_por) REFERENCES usuarios (id)$q$;
    EXECUTE $q$ALTER TABLE marketing_plantillas DROP CONSTRAINT IF EXISTS fk_marketing_plantillas_tenant_id$q$;
    EXECUTE $q$ALTER TABLE marketing_plantillas ADD CONSTRAINT fk_marketing_plantillas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- ON DELETE SET NULL entre tablas de despacho, como disparadores (Citus no lo admite en claves foráneas con tenant_id). En Citus se crean DESPUÉS de distribuir (013….citus.sql).
DO $tg$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$CREATE OR REPLACE FUNCTION fk_set_null_clientes() RETURNS trigger LANGUAGE plpgsql AS $$
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
END $$;$q$;
    EXECUTE $q$CREATE OR REPLACE FUNCTION fk_set_null_marketing_grupos() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE marketing_envios SET grupo_id = NULL WHERE tenant_id = OLD.tenant_id AND grupo_id = OLD.id;
    RETURN OLD;
END $$;$q$;
    EXECUTE $q$DROP TRIGGER IF EXISTS fk_set_null ON marketing_grupos$q$;
    EXECUTE $q$CREATE TRIGGER fk_set_null BEFORE DELETE ON marketing_grupos FOR EACH ROW EXECUTE FUNCTION fk_set_null_marketing_grupos()$q$;
  END IF;
END $tg$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE documentos_plantillas ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON documentos_plantillas;
CREATE POLICY aislamiento ON documentos_plantillas USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON documentos_plantillas TO guilda_app, guilda_plataforma;
ALTER TABLE documentos_firma ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON documentos_firma;
CREATE POLICY aislamiento ON documentos_firma USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON documentos_firma TO guilda_app, guilda_plataforma;
ALTER TABLE crm_acciones_masivas ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON crm_acciones_masivas;
CREATE POLICY aislamiento ON crm_acciones_masivas USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON crm_acciones_masivas TO guilda_app, guilda_plataforma;
ALTER TABLE marketing_contactos ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON marketing_contactos;
CREATE POLICY aislamiento ON marketing_contactos USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON marketing_contactos TO guilda_app, guilda_plataforma;
ALTER TABLE marketing_grupos ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON marketing_grupos;
CREATE POLICY aislamiento ON marketing_grupos USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON marketing_grupos TO guilda_app, guilda_plataforma;
ALTER TABLE marketing_plantillas ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON marketing_plantillas;
CREATE POLICY aislamiento ON marketing_plantillas USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON marketing_plantillas TO guilda_app, guilda_plataforma;
ALTER TABLE marketing_envios ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON marketing_envios;
CREATE POLICY aislamiento ON marketing_envios USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON marketing_envios TO guilda_app, guilda_plataforma;
ALTER TABLE marketing_envio_destinatarios ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON marketing_envio_destinatarios;
CREATE POLICY aislamiento ON marketing_envio_destinatarios USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON marketing_envio_destinatarios TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
