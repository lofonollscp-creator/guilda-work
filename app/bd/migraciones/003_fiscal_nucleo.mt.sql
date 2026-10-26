-- (despacho: tenant_id, clave primaria con tenant_id, índices, claves foráneas compuestas, RLS y SET NULL)
DO $$ BEGIN
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'fiscal_apuntes' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN ALTER TABLE fiscal_apuntes ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint; END IF;
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'fiscal_instantaneas' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN ALTER TABLE fiscal_instantaneas ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint; END IF;
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'fiscal_declaraciones' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN ALTER TABLE fiscal_declaraciones ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint; END IF;
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'fiscal_casillas' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN ALTER TABLE fiscal_casillas ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint; END IF;
  IF (SELECT column_default FROM information_schema.columns WHERE table_name = 'fiscal_artefactos' AND column_name = 'tenant_id' AND table_schema = current_schema()) IS NULL THEN ALTER TABLE fiscal_artefactos ALTER COLUMN tenant_id SET DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fiscal_apuntes_pkey') THEN ALTER TABLE fiscal_apuntes ADD CONSTRAINT fiscal_apuntes_pkey PRIMARY KEY (tenant_id, id); END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fiscal_instantaneas_pkey') THEN ALTER TABLE fiscal_instantaneas ADD CONSTRAINT fiscal_instantaneas_pkey PRIMARY KEY (tenant_id, id); END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fiscal_declaraciones_pkey') THEN ALTER TABLE fiscal_declaraciones ADD CONSTRAINT fiscal_declaraciones_pkey PRIMARY KEY (tenant_id, id); END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fiscal_casillas_pkey') THEN ALTER TABLE fiscal_casillas ADD CONSTRAINT fiscal_casillas_pkey PRIMARY KEY (tenant_id, id); END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fiscal_artefactos_pkey') THEN ALTER TABLE fiscal_artefactos ADD CONSTRAINT fiscal_artefactos_pkey PRIMARY KEY (tenant_id, id); END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_fiscal_apuntes_factura ON fiscal_apuntes (tenant_id, factura_id);
CREATE INDEX IF NOT EXISTS idx_fiscal_apuntes_periodo ON fiscal_apuntes (tenant_id, cliente_fiscal_id, libro, fecha_expedicion);
CREATE INDEX IF NOT EXISTS idx_fiscal_instantaneas ON fiscal_instantaneas (tenant_id, cliente_fiscal_id, modelo, ejercicio, periodo);
CREATE INDEX IF NOT EXISTS idx_fiscal_declaraciones ON fiscal_declaraciones (tenant_id, cliente_fiscal_id, modelo, ejercicio, periodo);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fiscal_casillas ON fiscal_casillas (tenant_id, declaracion_id, casilla);
CREATE INDEX IF NOT EXISTS idx_fiscal_artefactos ON fiscal_artefactos (tenant_id, declaracion_id, tipo);
-- Claves foráneas. En Citus se añaden DESPUÉS de distribuir (003….citus.sql): con la tabla aún local, Citus convierte el grafo de claves hacia `tenants` y agota los bloqueos.
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE fiscal_instantaneas DROP CONSTRAINT IF EXISTS fk_fiscal_instantaneas_aprobada_por$q$;
    EXECUTE $q$ALTER TABLE fiscal_instantaneas ADD CONSTRAINT fk_fiscal_instantaneas_aprobada_por FOREIGN KEY (aprobada_por) REFERENCES usuarios (id)$q$;
    EXECUTE $q$ALTER TABLE fiscal_instantaneas DROP CONSTRAINT IF EXISTS fk_fiscal_instantaneas_cliente_fiscal_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_instantaneas ADD CONSTRAINT fk_fiscal_instantaneas_cliente_fiscal_id FOREIGN KEY (tenant_id, cliente_fiscal_id) REFERENCES clientes_fiscales (tenant_id, id) ON DELETE CASCADE$q$;
    EXECUTE $q$ALTER TABLE fiscal_instantaneas DROP CONSTRAINT IF EXISTS fk_fiscal_instantaneas_sustituye_a_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_instantaneas ADD CONSTRAINT fk_fiscal_instantaneas_sustituye_a_id FOREIGN KEY (tenant_id, sustituye_a_id) REFERENCES fiscal_instantaneas (tenant_id, id)$q$;
    EXECUTE $q$ALTER TABLE fiscal_instantaneas DROP CONSTRAINT IF EXISTS fk_fiscal_instantaneas_tenant_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_instantaneas ADD CONSTRAINT fk_fiscal_instantaneas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id)$q$;
    EXECUTE $q$ALTER TABLE fiscal_apuntes DROP CONSTRAINT IF EXISTS fk_fiscal_apuntes_aprobado_por$q$;
    EXECUTE $q$ALTER TABLE fiscal_apuntes ADD CONSTRAINT fk_fiscal_apuntes_aprobado_por FOREIGN KEY (aprobado_por) REFERENCES usuarios (id)$q$;
    EXECUTE $q$ALTER TABLE fiscal_apuntes DROP CONSTRAINT IF EXISTS fk_fiscal_apuntes_cliente_fiscal_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_apuntes ADD CONSTRAINT fk_fiscal_apuntes_cliente_fiscal_id FOREIGN KEY (tenant_id, cliente_fiscal_id) REFERENCES clientes_fiscales (tenant_id, id) ON DELETE CASCADE$q$;
    EXECUTE $q$ALTER TABLE fiscal_apuntes DROP CONSTRAINT IF EXISTS fk_fiscal_apuntes_factura_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_apuntes ADD CONSTRAINT fk_fiscal_apuntes_factura_id FOREIGN KEY (tenant_id, factura_id) REFERENCES facturas_contables (tenant_id, id)$q$;
    EXECUTE $q$ALTER TABLE fiscal_apuntes DROP CONSTRAINT IF EXISTS fk_fiscal_apuntes_tenant_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_apuntes ADD CONSTRAINT fk_fiscal_apuntes_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id)$q$;
    EXECUTE $q$ALTER TABLE fiscal_declaraciones DROP CONSTRAINT IF EXISTS fk_fiscal_declaraciones_cliente_fiscal_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_declaraciones ADD CONSTRAINT fk_fiscal_declaraciones_cliente_fiscal_id FOREIGN KEY (tenant_id, cliente_fiscal_id) REFERENCES clientes_fiscales (tenant_id, id) ON DELETE CASCADE$q$;
    EXECUTE $q$ALTER TABLE fiscal_declaraciones DROP CONSTRAINT IF EXISTS fk_fiscal_declaraciones_creado_por$q$;
    EXECUTE $q$ALTER TABLE fiscal_declaraciones ADD CONSTRAINT fk_fiscal_declaraciones_creado_por FOREIGN KEY (creado_por) REFERENCES usuarios (id)$q$;
    EXECUTE $q$ALTER TABLE fiscal_declaraciones DROP CONSTRAINT IF EXISTS fk_fiscal_declaraciones_instantanea_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_declaraciones ADD CONSTRAINT fk_fiscal_declaraciones_instantanea_id FOREIGN KEY (tenant_id, instantanea_id) REFERENCES fiscal_instantaneas (tenant_id, id)$q$;
    EXECUTE $q$ALTER TABLE fiscal_declaraciones DROP CONSTRAINT IF EXISTS fk_fiscal_declaraciones_rectifica_a_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_declaraciones ADD CONSTRAINT fk_fiscal_declaraciones_rectifica_a_id FOREIGN KEY (tenant_id, rectifica_a_id) REFERENCES fiscal_declaraciones (tenant_id, id)$q$;
    EXECUTE $q$ALTER TABLE fiscal_declaraciones DROP CONSTRAINT IF EXISTS fk_fiscal_declaraciones_revisada_por$q$;
    EXECUTE $q$ALTER TABLE fiscal_declaraciones ADD CONSTRAINT fk_fiscal_declaraciones_revisada_por FOREIGN KEY (revisada_por) REFERENCES usuarios (id)$q$;
    EXECUTE $q$ALTER TABLE fiscal_declaraciones DROP CONSTRAINT IF EXISTS fk_fiscal_declaraciones_tenant_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_declaraciones ADD CONSTRAINT fk_fiscal_declaraciones_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id)$q$;
    EXECUTE $q$ALTER TABLE fiscal_declaraciones DROP CONSTRAINT IF EXISTS fk_fiscal_declaraciones_vencimiento_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_declaraciones ADD CONSTRAINT fk_fiscal_declaraciones_vencimiento_id FOREIGN KEY (tenant_id, vencimiento_id) REFERENCES vencimientos_fiscales (tenant_id, id)$q$;
    EXECUTE $q$ALTER TABLE fiscal_casillas DROP CONSTRAINT IF EXISTS fk_fiscal_casillas_declaracion_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_casillas ADD CONSTRAINT fk_fiscal_casillas_declaracion_id FOREIGN KEY (tenant_id, declaracion_id) REFERENCES fiscal_declaraciones (tenant_id, id) ON DELETE CASCADE$q$;
    EXECUTE $q$ALTER TABLE fiscal_casillas DROP CONSTRAINT IF EXISTS fk_fiscal_casillas_tenant_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_casillas ADD CONSTRAINT fk_fiscal_casillas_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id)$q$;
    EXECUTE $q$ALTER TABLE fiscal_artefactos DROP CONSTRAINT IF EXISTS fk_fiscal_artefactos_creado_por$q$;
    EXECUTE $q$ALTER TABLE fiscal_artefactos ADD CONSTRAINT fk_fiscal_artefactos_creado_por FOREIGN KEY (creado_por) REFERENCES usuarios (id)$q$;
    EXECUTE $q$ALTER TABLE fiscal_artefactos DROP CONSTRAINT IF EXISTS fk_fiscal_artefactos_declaracion_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_artefactos ADD CONSTRAINT fk_fiscal_artefactos_declaracion_id FOREIGN KEY (tenant_id, declaracion_id) REFERENCES fiscal_declaraciones (tenant_id, id) ON DELETE CASCADE$q$;
    EXECUTE $q$ALTER TABLE fiscal_artefactos DROP CONSTRAINT IF EXISTS fk_fiscal_artefactos_tenant_id$q$;
    EXECUTE $q$ALTER TABLE fiscal_artefactos ADD CONSTRAINT fk_fiscal_artefactos_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id)$q$;
  END IF;
END $fk$;
ALTER TABLE fiscal_apuntes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON fiscal_apuntes;
CREATE POLICY aislamiento ON fiscal_apuntes USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
ALTER TABLE fiscal_instantaneas ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON fiscal_instantaneas;
CREATE POLICY aislamiento ON fiscal_instantaneas USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
ALTER TABLE fiscal_declaraciones ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON fiscal_declaraciones;
CREATE POLICY aislamiento ON fiscal_declaraciones USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
ALTER TABLE fiscal_casillas ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON fiscal_casillas;
CREATE POLICY aislamiento ON fiscal_casillas USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
ALTER TABLE fiscal_artefactos ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON fiscal_artefactos;
CREATE POLICY aislamiento ON fiscal_artefactos USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON fiscal_apuntes, fiscal_instantaneas, fiscal_declaraciones, fiscal_casillas, fiscal_artefactos TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
CREATE OR REPLACE FUNCTION fk_set_null_facturas_contables() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE fiscal_apuntes SET factura_id = NULL WHERE tenant_id = OLD.tenant_id AND factura_id = OLD.id;
    RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS fk_set_null ON facturas_contables;
CREATE TRIGGER fk_set_null BEFORE DELETE ON facturas_contables FOR EACH ROW EXECUTE FUNCTION fk_set_null_facturas_contables();
CREATE OR REPLACE FUNCTION fk_set_null_vencimientos_fiscales() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE fiscal_declaraciones SET vencimiento_id = NULL WHERE tenant_id = OLD.tenant_id AND vencimiento_id = OLD.id;
    RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS fk_set_null ON vencimientos_fiscales;
CREATE TRIGGER fk_set_null BEFORE DELETE ON vencimientos_fiscales FOR EACH ROW EXECUTE FUNCTION fk_set_null_vencimientos_fiscales();
