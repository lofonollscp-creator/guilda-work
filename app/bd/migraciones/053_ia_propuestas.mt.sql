-- tenant_id con su valor por defecto, clave primaria con tenant_id, clave foránea, RLS y permisos (idempotente).
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'ia_propuestas' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE ia_propuestas ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'ia_propuestas'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE ia_propuestas DROP CONSTRAINT IF EXISTS ia_propuestas_pkey;
    ALTER TABLE ia_propuestas ADD CONSTRAINT ia_propuestas_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE ia_propuestas DROP CONSTRAINT IF EXISTS fk_ia_propuestas_tenant_id$q$;
    EXECUTE $q$ALTER TABLE ia_propuestas ADD CONSTRAINT fk_ia_propuestas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE ia_propuestas ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON ia_propuestas;
CREATE POLICY aislamiento ON ia_propuestas USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON ia_propuestas TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
