-- Avisos y adjuntos del portal: tenant_id con su valor por defecto, clave primaria con tenant_id, clave foránea, RLS y permisos (idempotente).
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'portal_novedades' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE portal_novedades ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'portal_novedades'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE portal_novedades DROP CONSTRAINT IF EXISTS portal_novedades_pkey;
    ALTER TABLE portal_novedades ADD CONSTRAINT portal_novedades_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE portal_novedades DROP CONSTRAINT IF EXISTS fk_portal_novedades_tenant_id$q$;
    EXECUTE $q$ALTER TABLE portal_novedades ADD CONSTRAINT fk_portal_novedades_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE portal_novedades ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON portal_novedades;
CREATE POLICY aislamiento ON portal_novedades USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON portal_novedades TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'portal_novedades_lectura' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE portal_novedades_lectura ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'portal_novedades_lectura'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE portal_novedades_lectura DROP CONSTRAINT IF EXISTS portal_novedades_lectura_pkey;
    ALTER TABLE portal_novedades_lectura ADD CONSTRAINT portal_novedades_lectura_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE portal_novedades_lectura DROP CONSTRAINT IF EXISTS fk_portal_novedades_lectura_tenant_id$q$;
    EXECUTE $q$ALTER TABLE portal_novedades_lectura ADD CONSTRAINT fk_portal_novedades_lectura_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE portal_novedades_lectura ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON portal_novedades_lectura;
CREATE POLICY aislamiento ON portal_novedades_lectura USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON portal_novedades_lectura TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'portal_conversaciones_adjuntos' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE portal_conversaciones_adjuntos ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'portal_conversaciones_adjuntos'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE portal_conversaciones_adjuntos DROP CONSTRAINT IF EXISTS portal_conversaciones_adjuntos_pkey;
    ALTER TABLE portal_conversaciones_adjuntos ADD CONSTRAINT portal_conversaciones_adjuntos_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE portal_conversaciones_adjuntos DROP CONSTRAINT IF EXISTS fk_portal_conversaciones_adjuntos_tenant_id$q$;
    EXECUTE $q$ALTER TABLE portal_conversaciones_adjuntos ADD CONSTRAINT fk_portal_conversaciones_adjuntos_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE portal_conversaciones_adjuntos ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON portal_conversaciones_adjuntos;
CREATE POLICY aislamiento ON portal_conversaciones_adjuntos USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON portal_conversaciones_adjuntos TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
