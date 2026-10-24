ALTER TABLE fiscal_perfiles   ADD COLUMN IF NOT EXISTS tenant_id bigint NOT NULL DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
ALTER TABLE fiscal_relaciones ADD COLUMN IF NOT EXISTS tenant_id bigint NOT NULL DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
-- clave primaria con tenant_id (obligatoria para poder mover fragmentos entre nodos)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fiscal_perfiles_pkey')   THEN ALTER TABLE fiscal_perfiles   ADD CONSTRAINT fiscal_perfiles_pkey   PRIMARY KEY (tenant_id, id); END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fiscal_relaciones_pkey') THEN ALTER TABLE fiscal_relaciones ADD CONSTRAINT fiscal_relaciones_pkey PRIMARY KEY (tenant_id, id); END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS idx_fiscal_perfiles_vigencia  ON fiscal_perfiles (tenant_id, cliente_fiscal_id, vigente_desde);
CREATE INDEX        IF NOT EXISTS idx_fiscal_perfiles_cliente   ON fiscal_perfiles (tenant_id, cliente_fiscal_id, vigente_hasta);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fiscal_relaciones_unica   ON fiscal_relaciones (tenant_id, desde_cliente_id, hasta_cliente_id, tipo, vigente_desde);
CREATE INDEX        IF NOT EXISTS idx_fiscal_relaciones_hasta   ON fiscal_relaciones (tenant_id, hasta_cliente_id);
-- sin solapamiento de vigencias del mismo titular (la base lo impone, no solo la aplicación)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fiscal_perfiles_sin_solape') THEN
    ALTER TABLE fiscal_perfiles ADD CONSTRAINT fiscal_perfiles_sin_solape EXCLUDE USING gist (
      tenant_id WITH =, cliente_fiscal_id WITH =,
      daterange(fiscal_dia(vigente_desde), COALESCE(fiscal_dia(vigente_hasta), 'infinity'::date), '[]') WITH &&);
  END IF;
END $$;
-- claves foráneas compuestas: no se puede apuntar a un titular de otro despacho.
-- En Citus se añaden DESPUÉS de distribuir (002….citus.sql): con la tabla aún local, Citus convierte todo el grafo de claves foráneas hacia la tabla de referencia `tenants` y agota los bloqueos.
DO $fk$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
    EXECUTE $q$ALTER TABLE fiscal_perfiles   DROP CONSTRAINT IF EXISTS fk_fiscal_perfiles_cliente;$q$;
    EXECUTE $q$ALTER TABLE fiscal_perfiles   ADD  CONSTRAINT fk_fiscal_perfiles_cliente   FOREIGN KEY (tenant_id, cliente_fiscal_id) REFERENCES clientes_fiscales (tenant_id, id) ON DELETE CASCADE;$q$;
    EXECUTE $q$ALTER TABLE fiscal_relaciones DROP CONSTRAINT IF EXISTS fk_fiscal_relaciones_desde;$q$;
    EXECUTE $q$ALTER TABLE fiscal_relaciones ADD  CONSTRAINT fk_fiscal_relaciones_desde   FOREIGN KEY (tenant_id, desde_cliente_id) REFERENCES clientes_fiscales (tenant_id, id) ON DELETE CASCADE;$q$;
    EXECUTE $q$ALTER TABLE fiscal_relaciones DROP CONSTRAINT IF EXISTS fk_fiscal_relaciones_hasta;$q$;
    EXECUTE $q$ALTER TABLE fiscal_relaciones ADD  CONSTRAINT fk_fiscal_relaciones_hasta   FOREIGN KEY (tenant_id, hasta_cliente_id) REFERENCES clientes_fiscales (tenant_id, id) ON DELETE CASCADE;$q$;
    EXECUTE $q$ALTER TABLE fiscal_perfiles   DROP CONSTRAINT IF EXISTS fk_fiscal_perfiles_tenant;$q$;
    EXECUTE $q$ALTER TABLE fiscal_perfiles   ADD  CONSTRAINT fk_fiscal_perfiles_tenant   FOREIGN KEY (tenant_id) REFERENCES tenants (id);$q$;
    EXECUTE $q$ALTER TABLE fiscal_relaciones DROP CONSTRAINT IF EXISTS fk_fiscal_relaciones_tenant;$q$;
    EXECUTE $q$ALTER TABLE fiscal_relaciones ADD  CONSTRAINT fk_fiscal_relaciones_tenant FOREIGN KEY (tenant_id) REFERENCES tenants (id);$q$;
    EXECUTE $q$ALTER TABLE fiscal_perfiles   DROP CONSTRAINT IF EXISTS fk_fiscal_perfiles_creado_por;$q$;
    EXECUTE $q$ALTER TABLE fiscal_perfiles   ADD  CONSTRAINT fk_fiscal_perfiles_creado_por   FOREIGN KEY (creado_por) REFERENCES usuarios (id);$q$;
    EXECUTE $q$ALTER TABLE fiscal_relaciones DROP CONSTRAINT IF EXISTS fk_fiscal_relaciones_creado_por;$q$;
    EXECUTE $q$ALTER TABLE fiscal_relaciones ADD  CONSTRAINT fk_fiscal_relaciones_creado_por FOREIGN KEY (creado_por) REFERENCES usuarios (id);$q$;
  END IF;
END $fk$;
-- aislamiento por despacho (RLS)
ALTER TABLE fiscal_perfiles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON fiscal_perfiles;
CREATE POLICY aislamiento ON fiscal_perfiles USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
ALTER TABLE fiscal_relaciones ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON fiscal_relaciones;
CREATE POLICY aislamiento ON fiscal_relaciones USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON fiscal_perfiles, fiscal_relaciones TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
