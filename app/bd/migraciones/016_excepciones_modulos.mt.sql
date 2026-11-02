-- (despacho: tenant_id con su valor por defecto, clave primaria con tenant_id, claves foráneas, disparadores de ON DELETE SET NULL, RLS y permisos). Idempotente también sobre tablas ya distribuidas (una base nueva nace con ellas)
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'tenants_verticales_historial' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE tenants_verticales_historial ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'tenants_verticales_historial'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE tenants_verticales_historial DROP CONSTRAINT IF EXISTS tenants_verticales_historial_pkey;
    ALTER TABLE tenants_verticales_historial ADD CONSTRAINT tenants_verticales_historial_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
-- claves foráneas: las de despacho a despacho son compuestas. En Citus se añaden DESPUÉS de distribuir (016….citus.sql).
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE tenants_verticales_historial DROP CONSTRAINT IF EXISTS fk_tenants_verticales_historial_tenant_id$q$;
    EXECUTE $q$ALTER TABLE tenants_verticales_historial ADD CONSTRAINT fk_tenants_verticales_historial_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE tenants_verticales_historial ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON tenants_verticales_historial;
CREATE POLICY aislamiento ON tenants_verticales_historial USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON tenants_verticales_historial TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
