-- (despacho: tenant_id con su valor por defecto, clave primaria con tenant_id, clave foránea, RLS y permisos). Idempotente también sobre tablas ya distribuidas (una base nueva nace con ellas)
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'portal_avisos_enviados' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE portal_avisos_enviados ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'portal_avisos_enviados'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE portal_avisos_enviados DROP CONSTRAINT IF EXISTS portal_avisos_enviados_pkey;
    ALTER TABLE portal_avisos_enviados ADD CONSTRAINT portal_avisos_enviados_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE portal_avisos_enviados DROP CONSTRAINT IF EXISTS fk_portal_avisos_enviados_tenant_id$q$;
    EXECUTE $q$ALTER TABLE portal_avisos_enviados ADD CONSTRAINT fk_portal_avisos_enviados_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE portal_avisos_enviados ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON portal_avisos_enviados;
CREATE POLICY aislamiento ON portal_avisos_enviados USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON portal_avisos_enviados TO guilda_app, guilda_plataforma;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'portal_contactos' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE portal_contactos ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'portal_contactos'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE portal_contactos DROP CONSTRAINT IF EXISTS portal_contactos_pkey;
    ALTER TABLE portal_contactos ADD CONSTRAINT portal_contactos_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE portal_contactos DROP CONSTRAINT IF EXISTS fk_portal_contactos_tenant_id$q$;
    EXECUTE $q$ALTER TABLE portal_contactos ADD CONSTRAINT fk_portal_contactos_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE portal_contactos ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON portal_contactos;
CREATE POLICY aislamiento ON portal_contactos USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON portal_contactos TO guilda_app, guilda_plataforma;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'portal_enlaces_subida' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE portal_enlaces_subida ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'portal_enlaces_subida'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE portal_enlaces_subida DROP CONSTRAINT IF EXISTS portal_enlaces_subida_pkey;
    ALTER TABLE portal_enlaces_subida ADD CONSTRAINT portal_enlaces_subida_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE portal_enlaces_subida DROP CONSTRAINT IF EXISTS fk_portal_enlaces_subida_tenant_id$q$;
    EXECUTE $q$ALTER TABLE portal_enlaces_subida ADD CONSTRAINT fk_portal_enlaces_subida_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE portal_enlaces_subida ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON portal_enlaces_subida;
CREATE POLICY aislamiento ON portal_enlaces_subida USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON portal_enlaces_subida TO guilda_app, guilda_plataforma;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'portal_respuestas_rapidas' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE portal_respuestas_rapidas ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'portal_respuestas_rapidas'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE portal_respuestas_rapidas DROP CONSTRAINT IF EXISTS portal_respuestas_rapidas_pkey;
    ALTER TABLE portal_respuestas_rapidas ADD CONSTRAINT portal_respuestas_rapidas_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE portal_respuestas_rapidas DROP CONSTRAINT IF EXISTS fk_portal_respuestas_rapidas_tenant_id$q$;
    EXECUTE $q$ALTER TABLE portal_respuestas_rapidas ADD CONSTRAINT fk_portal_respuestas_rapidas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE portal_respuestas_rapidas ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON portal_respuestas_rapidas;
CREATE POLICY aislamiento ON portal_respuestas_rapidas USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON portal_respuestas_rapidas TO guilda_app, guilda_plataforma;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'portal_suscripciones_push' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE portal_suscripciones_push ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'portal_suscripciones_push'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE portal_suscripciones_push DROP CONSTRAINT IF EXISTS portal_suscripciones_push_pkey;
    ALTER TABLE portal_suscripciones_push ADD CONSTRAINT portal_suscripciones_push_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE portal_suscripciones_push DROP CONSTRAINT IF EXISTS fk_portal_suscripciones_push_tenant_id$q$;
    EXECUTE $q$ALTER TABLE portal_suscripciones_push ADD CONSTRAINT fk_portal_suscripciones_push_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE portal_suscripciones_push ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON portal_suscripciones_push;
CREATE POLICY aislamiento ON portal_suscripciones_push USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON portal_suscripciones_push TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
