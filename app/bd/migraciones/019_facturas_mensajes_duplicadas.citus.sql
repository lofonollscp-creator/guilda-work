-- Idempotente: una base nueva ya nace con esta tabla distribuida (esquema base generado); una existente la distribuye aquí.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'facturas_contables_mensajes'::regclass) THEN
    PERFORM create_distributed_table('facturas_contables_mensajes', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
-- clave foránea, ya con la tabla distribuida (en mt llano la puso 019….mt.sql)
ALTER TABLE facturas_contables_mensajes DROP CONSTRAINT IF EXISTS fk_facturas_contables_mensajes_tenant_id;
ALTER TABLE facturas_contables_mensajes ADD CONSTRAINT fk_facturas_contables_mensajes_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
