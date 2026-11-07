-- IA por despacho: tenant_id con su valor por defecto, clave foránea, RLS y permisos (idempotente).
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'ia_proveedores_despacho' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE ia_proveedores_despacho ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'ia_proveedores_despacho'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE ia_proveedores_despacho DROP CONSTRAINT IF EXISTS ia_proveedores_despacho_pkey;
    ALTER TABLE ia_proveedores_despacho ADD CONSTRAINT ia_proveedores_despacho_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE ia_proveedores_despacho DROP CONSTRAINT IF EXISTS fk_ia_proveedores_despacho_tenant_id$q$;
    EXECUTE $q$ALTER TABLE ia_proveedores_despacho ADD CONSTRAINT fk_ia_proveedores_despacho_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE ia_proveedores_despacho ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON ia_proveedores_despacho;
CREATE POLICY aislamiento ON ia_proveedores_despacho USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON ia_proveedores_despacho TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'ia_config_despacho' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE ia_config_despacho ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'ia_config_despacho'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE ia_config_despacho DROP CONSTRAINT IF EXISTS ia_config_despacho_pkey;
    ALTER TABLE ia_config_despacho ADD CONSTRAINT ia_config_despacho_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE ia_config_despacho DROP CONSTRAINT IF EXISTS fk_ia_config_despacho_tenant_id$q$;
    EXECUTE $q$ALTER TABLE ia_config_despacho ADD CONSTRAINT fk_ia_config_despacho_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE ia_config_despacho ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON ia_config_despacho;
CREATE POLICY aislamiento ON ia_config_despacho USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON ia_config_despacho TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'ia_uso_proveedor' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE ia_uso_proveedor ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'ia_uso_proveedor'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE ia_uso_proveedor DROP CONSTRAINT IF EXISTS ia_uso_proveedor_pkey;
    ALTER TABLE ia_uso_proveedor ADD CONSTRAINT ia_uso_proveedor_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE ia_uso_proveedor DROP CONSTRAINT IF EXISTS fk_ia_uso_proveedor_tenant_id$q$;
    EXECUTE $q$ALTER TABLE ia_uso_proveedor ADD CONSTRAINT fk_ia_uso_proveedor_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE ia_uso_proveedor ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON ia_uso_proveedor;
CREATE POLICY aislamiento ON ia_uso_proveedor USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON ia_uso_proveedor TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
