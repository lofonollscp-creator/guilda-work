-- (despacho: tenant_id con su valor por defecto, clave primaria con tenant_id, claves foráneas, disparadores de ON DELETE SET NULL, RLS y permisos). Idempotente también sobre tablas ya distribuidas (una base nueva nace con ellas)
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'honorarios_reglas' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE honorarios_reglas ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'honorarios_reglas'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE honorarios_reglas DROP CONSTRAINT IF EXISTS honorarios_reglas_pkey;
    ALTER TABLE honorarios_reglas ADD CONSTRAINT honorarios_reglas_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'honorarios_aplicados' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE honorarios_aplicados ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'honorarios_aplicados'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE honorarios_aplicados DROP CONSTRAINT IF EXISTS honorarios_aplicados_pkey;
    ALTER TABLE honorarios_aplicados ADD CONSTRAINT honorarios_aplicados_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'fiscal_acciones_masivas' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE fiscal_acciones_masivas ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'fiscal_acciones_masivas'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE fiscal_acciones_masivas DROP CONSTRAINT IF EXISTS fiscal_acciones_masivas_pkey;
    ALTER TABLE fiscal_acciones_masivas ADD CONSTRAINT fiscal_acciones_masivas_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
-- claves foráneas: las de despacho a despacho son compuestas. En Citus se añaden DESPUÉS de distribuir (015….citus.sql).
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE fiscal_acciones_masivas DROP CONSTRAINT IF EXISTS fk_fiscal_acciones_masivas_tenant_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_acciones_masivas ADD CONSTRAINT fk_fiscal_acciones_masivas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
    EXECUTE $q$ALTER TABLE fiscal_acciones_masivas DROP CONSTRAINT IF EXISTS fk_fiscal_acciones_masivas_usuario_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_acciones_masivas ADD CONSTRAINT fk_fiscal_acciones_masivas_usuario_id FOREIGN KEY (usuario_id) REFERENCES usuarios (id)$q$;
    EXECUTE $q$ALTER TABLE honorarios_aplicados DROP CONSTRAINT IF EXISTS fk_honorarios_aplicados_tenant_id$q$;
    EXECUTE $q$ALTER TABLE honorarios_aplicados ADD CONSTRAINT fk_honorarios_aplicados_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
    EXECUTE $q$ALTER TABLE honorarios_reglas DROP CONSTRAINT IF EXISTS fk_honorarios_reglas_tenant_id$q$;
    EXECUTE $q$ALTER TABLE honorarios_reglas ADD CONSTRAINT fk_honorarios_reglas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE honorarios_reglas ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON honorarios_reglas;
CREATE POLICY aislamiento ON honorarios_reglas USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON honorarios_reglas TO guilda_app, guilda_plataforma;
ALTER TABLE honorarios_aplicados ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON honorarios_aplicados;
CREATE POLICY aislamiento ON honorarios_aplicados USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON honorarios_aplicados TO guilda_app, guilda_plataforma;
ALTER TABLE fiscal_acciones_masivas ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON fiscal_acciones_masivas;
CREATE POLICY aislamiento ON fiscal_acciones_masivas USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON fiscal_acciones_masivas TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
