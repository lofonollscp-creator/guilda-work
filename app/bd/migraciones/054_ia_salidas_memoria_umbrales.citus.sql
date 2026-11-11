-- Idempotente: una base nueva ya nace con las tablas distribuidas (esquema base generado); una existente las distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'ia_salidas_datos'::regclass) THEN
    PERFORM create_distributed_table('ia_salidas_datos', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE ia_salidas_datos DROP CONSTRAINT IF EXISTS fk_ia_salidas_datos_tenant_id;
ALTER TABLE ia_salidas_datos ADD CONSTRAINT fk_ia_salidas_datos_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'cliente_memoria'::regclass) THEN
    PERFORM create_distributed_table('cliente_memoria', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 022….mt.sql)
ALTER TABLE cliente_memoria DROP CONSTRAINT IF EXISTS fk_cliente_memoria_tenant_id;
ALTER TABLE cliente_memoria ADD CONSTRAINT fk_cliente_memoria_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
