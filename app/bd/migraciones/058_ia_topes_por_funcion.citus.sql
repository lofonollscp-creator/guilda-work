DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'ia_consumo_funcion'::regclass) THEN
    PERFORM create_distributed_table('ia_consumo_funcion', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
ALTER TABLE ia_consumo_funcion DROP CONSTRAINT IF EXISTS fk_ia_consumo_funcion_tenant_id;
ALTER TABLE ia_consumo_funcion ADD CONSTRAINT fk_ia_consumo_funcion_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'ia_tope_funcion'::regclass) THEN
    PERFORM create_distributed_table('ia_tope_funcion', 'tenant_id', colocate_with => 'abogados_ajustes');
  END IF;
END $$;
ALTER TABLE ia_tope_funcion DROP CONSTRAINT IF EXISTS fk_ia_tope_funcion_tenant_id;
ALTER TABLE ia_tope_funcion ADD CONSTRAINT fk_ia_tope_funcion_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE;
