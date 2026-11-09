-- tenant_id con su valor por defecto, clave primaria con tenant_id, clave foránea, RLS y permisos (idempotente).
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'portal_telemetria_diaria' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE portal_telemetria_diaria ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'portal_telemetria_diaria'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE portal_telemetria_diaria DROP CONSTRAINT IF EXISTS portal_telemetria_diaria_pkey;
    ALTER TABLE portal_telemetria_diaria ADD CONSTRAINT portal_telemetria_diaria_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE portal_telemetria_diaria DROP CONSTRAINT IF EXISTS fk_portal_telemetria_diaria_tenant_id$q$;
    EXECUTE $q$ALTER TABLE portal_telemetria_diaria ADD CONSTRAINT fk_portal_telemetria_diaria_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE portal_telemetria_diaria ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON portal_telemetria_diaria;
CREATE POLICY aislamiento ON portal_telemetria_diaria USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON portal_telemetria_diaria TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
