-- (despacho: tenant_id con su valor por defecto, clave primaria con tenant_id, claves foráneas compuestas, RLS y permisos). Idempotente también sobre una tabla ya distribuida (una base nueva nace con ella)
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'fiscal_apuntes_recurrentes' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE fiscal_apuntes_recurrentes ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  -- clave primaria con tenant_id (obligatoria para poder mover fragmentos entre nodos): la de la tabla base es solo `id`
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'fiscal_apuntes_recurrentes'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE fiscal_apuntes_recurrentes DROP CONSTRAINT IF EXISTS fiscal_apuntes_recurrentes_pkey;
    ALTER TABLE fiscal_apuntes_recurrentes ADD CONSTRAINT fiscal_apuntes_recurrentes_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
-- claves foráneas: la del titular es compuesta (no se puede apuntar a un titular de otro despacho). En Citus se añaden DESPUÉS de distribuir (011….citus.sql).
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE fiscal_apuntes_recurrentes DROP CONSTRAINT IF EXISTS fk_fiscal_apuntes_recurrentes_cliente_fiscal_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_apuntes_recurrentes ADD CONSTRAINT fk_fiscal_apuntes_recurrentes_cliente_fiscal_id FOREIGN KEY (tenant_id, cliente_fiscal_id) REFERENCES clientes_fiscales (tenant_id, id) ON DELETE CASCADE$q$;
    EXECUTE $q$ALTER TABLE fiscal_apuntes_recurrentes DROP CONSTRAINT IF EXISTS fk_fiscal_apuntes_recurrentes_creado_por$q$;
    EXECUTE $q$ALTER TABLE fiscal_apuntes_recurrentes ADD CONSTRAINT fk_fiscal_apuntes_recurrentes_creado_por FOREIGN KEY (creado_por) REFERENCES usuarios (id)$q$;
    EXECUTE $q$ALTER TABLE fiscal_apuntes_recurrentes DROP CONSTRAINT IF EXISTS fk_fiscal_apuntes_recurrentes_tenant_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_apuntes_recurrentes ADD CONSTRAINT fk_fiscal_apuntes_recurrentes_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id)$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS)
ALTER TABLE fiscal_apuntes_recurrentes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON fiscal_apuntes_recurrentes;
CREATE POLICY aislamiento ON fiscal_apuntes_recurrentes USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON fiscal_apuntes_recurrentes TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
