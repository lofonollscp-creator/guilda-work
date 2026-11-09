-- tenant_id con su valor por defecto, clave primaria con tenant_id, clave foránea, RLS y permisos (idempotente).
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'portal_canales_config' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE portal_canales_config ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'portal_canales_config'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE portal_canales_config DROP CONSTRAINT IF EXISTS portal_canales_config_pkey;
    ALTER TABLE portal_canales_config ADD CONSTRAINT portal_canales_config_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE portal_canales_config DROP CONSTRAINT IF EXISTS fk_portal_canales_config_tenant_id$q$;
    EXECUTE $q$ALTER TABLE portal_canales_config ADD CONSTRAINT fk_portal_canales_config_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE portal_canales_config ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON portal_canales_config;
CREATE POLICY aislamiento ON portal_canales_config USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON portal_canales_config TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'portal_canales_personas' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE portal_canales_personas ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'portal_canales_personas'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE portal_canales_personas DROP CONSTRAINT IF EXISTS portal_canales_personas_pkey;
    ALTER TABLE portal_canales_personas ADD CONSTRAINT portal_canales_personas_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE portal_canales_personas DROP CONSTRAINT IF EXISTS fk_portal_canales_personas_tenant_id$q$;
    EXECUTE $q$ALTER TABLE portal_canales_personas ADD CONSTRAINT fk_portal_canales_personas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE portal_canales_personas ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON portal_canales_personas;
CREATE POLICY aislamiento ON portal_canales_personas USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON portal_canales_personas TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'portal_canales_envios' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE portal_canales_envios ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'portal_canales_envios'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE portal_canales_envios DROP CONSTRAINT IF EXISTS portal_canales_envios_pkey;
    ALTER TABLE portal_canales_envios ADD CONSTRAINT portal_canales_envios_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE portal_canales_envios DROP CONSTRAINT IF EXISTS fk_portal_canales_envios_tenant_id$q$;
    EXECUTE $q$ALTER TABLE portal_canales_envios ADD CONSTRAINT fk_portal_canales_envios_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE portal_canales_envios ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON portal_canales_envios;
CREATE POLICY aislamiento ON portal_canales_envios USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON portal_canales_envios TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
