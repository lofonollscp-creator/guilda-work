ALTER TABLE ia_consumo_funcion ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE ia_consumo_funcion DROP CONSTRAINT IF EXISTS fk_ia_consumo_funcion_tenant_id$q$;
    EXECUTE $q$ALTER TABLE ia_consumo_funcion ADD CONSTRAINT fk_ia_consumo_funcion_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
ALTER TABLE ia_consumo_funcion ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON ia_consumo_funcion;
CREATE POLICY aislamiento ON ia_consumo_funcion USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON ia_consumo_funcion TO guilda_app, guilda_plataforma;
ALTER TABLE ia_tope_funcion ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE ia_tope_funcion DROP CONSTRAINT IF EXISTS fk_ia_tope_funcion_tenant_id$q$;
    EXECUTE $q$ALTER TABLE ia_tope_funcion ADD CONSTRAINT fk_ia_tope_funcion_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE$q$;
  END IF;
END $fk$;
ALTER TABLE ia_tope_funcion ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON ia_tope_funcion;
CREATE POLICY aislamiento ON ia_tope_funcion USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON ia_tope_funcion TO guilda_app, guilda_plataforma;
