-- (despacho: tenant_id con su valor por defecto, clave primaria con tenant_id, claves foráneas, disparadores de ON DELETE SET NULL, RLS y permisos). Idempotente también sobre tablas ya distribuidas (una base nueva nace con ellas)
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'marketing_rebotes' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE marketing_rebotes ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'marketing_rebotes'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE marketing_rebotes DROP CONSTRAINT IF EXISTS marketing_rebotes_pkey;
    ALTER TABLE marketing_rebotes ADD CONSTRAINT marketing_rebotes_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'marketing_proveedores' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE marketing_proveedores ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'marketing_proveedores'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE marketing_proveedores DROP CONSTRAINT IF EXISTS marketing_proveedores_pkey;
    ALTER TABLE marketing_proveedores ADD CONSTRAINT marketing_proveedores_pkey PRIMARY KEY (tenant_id, proveedor);
  END IF;
END $$;
-- claves foráneas: las de despacho a despacho son compuestas. En Citus se añaden DESPUÉS de distribuir (013….citus.sql).
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE marketing_proveedores DROP CONSTRAINT IF EXISTS fk_marketing_proveedores_actualizado_por$q$;
    EXECUTE $q$ALTER TABLE marketing_proveedores ADD CONSTRAINT fk_marketing_proveedores_actualizado_por FOREIGN KEY (actualizado_por) REFERENCES usuarios (id)$q$;
    EXECUTE $q$ALTER TABLE marketing_proveedores DROP CONSTRAINT IF EXISTS fk_marketing_proveedores_tenant_id$q$;
    EXECUTE $q$ALTER TABLE marketing_proveedores ADD CONSTRAINT fk_marketing_proveedores_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
    EXECUTE $q$ALTER TABLE marketing_rebotes DROP CONSTRAINT IF EXISTS fk_marketing_rebotes_tenant_id$q$;
    EXECUTE $q$ALTER TABLE marketing_rebotes ADD CONSTRAINT fk_marketing_rebotes_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE marketing_rebotes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON marketing_rebotes;
CREATE POLICY aislamiento ON marketing_rebotes USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON marketing_rebotes TO guilda_app, guilda_plataforma;
ALTER TABLE marketing_proveedores ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON marketing_proveedores;
CREATE POLICY aislamiento ON marketing_proveedores USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON marketing_proveedores TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
