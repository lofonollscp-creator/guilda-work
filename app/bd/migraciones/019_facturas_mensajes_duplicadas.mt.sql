-- (despacho: tenant_id con su valor por defecto, clave primaria con tenant_id, clave foránea, RLS y permisos). Idempotente también sobre tablas ya distribuidas (una base nueva nace con ellas)
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'facturas_contables_mensajes' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN
    ALTER TABLE facturas_contables_mensajes ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
  END IF;
  IF COALESCE((SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'facturas_contables_mensajes'::regclass AND contype = 'p'), '') NOT LIKE '%tenant_id%' THEN
    ALTER TABLE facturas_contables_mensajes DROP CONSTRAINT IF EXISTS facturas_contables_mensajes_pkey;
    ALTER TABLE facturas_contables_mensajes ADD CONSTRAINT facturas_contables_mensajes_pkey PRIMARY KEY (tenant_id, id);
  END IF;
END $$;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE facturas_contables_mensajes DROP CONSTRAINT IF EXISTS fk_facturas_contables_mensajes_tenant_id$q$;
    EXECUTE $q$ALTER TABLE facturas_contables_mensajes ADD CONSTRAINT fk_facturas_contables_mensajes_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS) y permisos
ALTER TABLE facturas_contables_mensajes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON facturas_contables_mensajes;
CREATE POLICY aislamiento ON facturas_contables_mensajes USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON facturas_contables_mensajes TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
