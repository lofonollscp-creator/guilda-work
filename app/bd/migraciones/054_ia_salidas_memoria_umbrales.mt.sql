-- tenant_id con su valor por defecto, clave primaria con tenant_id, clave foránea, RLS y permisos (idempotente).
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'ia_salidas_datos' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE ia_salidas_datos ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'ia_salidas_datos'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE ia_salidas_datos DROP CONSTRAINT IF EXISTS ia_salidas_datos_pkey;
    ALTER TABLE ia_salidas_datos ADD CONSTRAINT ia_salidas_datos_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE ia_salidas_datos DROP CONSTRAINT IF EXISTS fk_ia_salidas_datos_tenant_id$q$;
    EXECUTE $q$ALTER TABLE ia_salidas_datos ADD CONSTRAINT fk_ia_salidas_datos_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE ia_salidas_datos ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON ia_salidas_datos;
CREATE POLICY aislamiento ON ia_salidas_datos USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON ia_salidas_datos TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'cliente_memoria' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE cliente_memoria ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'cliente_memoria'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE cliente_memoria DROP CONSTRAINT IF EXISTS cliente_memoria_pkey;
    ALTER TABLE cliente_memoria ADD CONSTRAINT cliente_memoria_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE cliente_memoria DROP CONSTRAINT IF EXISTS fk_cliente_memoria_tenant_id$q$;
    EXECUTE $q$ALTER TABLE cliente_memoria ADD CONSTRAINT fk_cliente_memoria_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE cliente_memoria ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON cliente_memoria;
CREATE POLICY aislamiento ON cliente_memoria USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON cliente_memoria TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
