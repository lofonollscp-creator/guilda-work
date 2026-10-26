-- GENERADO por scripts/migracion/generar_esquema_pg.py a partir del esquema de SQLite. No editar a mano.
-- ON DELETE SET NULL entre tablas distribuidas, como triggers (Citus no lo admite en claves foráneas que incluyen tenant_id). Generado.

CREATE OR REPLACE FUNCTION fk_set_null_clientes() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE contactos SET cliente_id = NULL WHERE tenant_id = OLD.tenant_id AND cliente_id = OLD.id;
    UPDATE crm_actividades SET cliente_id = NULL WHERE tenant_id = OLD.tenant_id AND cliente_id = OLD.id;
    UPDATE crm_oportunidades SET cliente_id = NULL WHERE tenant_id = OLD.tenant_id AND cliente_id = OLD.id;
    UPDATE crm_reuniones SET cliente_id = NULL WHERE tenant_id = OLD.tenant_id AND cliente_id = OLD.id;
    UPDATE jur_adjuntos SET cliente_id = NULL WHERE tenant_id = OLD.tenant_id AND cliente_id = OLD.id;
    UPDATE jur_conversaciones SET cliente_id = NULL WHERE tenant_id = OLD.tenant_id AND cliente_id = OLD.id;
    UPDATE jur_informes SET cliente_id = NULL WHERE tenant_id = OLD.tenant_id AND cliente_id = OLD.id;
    RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS fk_set_null ON clientes;
CREATE TRIGGER fk_set_null BEFORE DELETE ON clientes FOR EACH ROW EXECUTE FUNCTION fk_set_null_clientes();

CREATE OR REPLACE FUNCTION fk_set_null_correo_categorias() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE correo_mensajes SET categoria_id = NULL WHERE tenant_id = OLD.tenant_id AND categoria_id = OLD.id;
    UPDATE correo_reglas SET categoria_id = NULL WHERE tenant_id = OLD.tenant_id AND categoria_id = OLD.id;
    RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS fk_set_null ON correo_categorias;
CREATE TRIGGER fk_set_null BEFORE DELETE ON correo_categorias FOR EACH ROW EXECUTE FUNCTION fk_set_null_correo_categorias();

CREATE OR REPLACE FUNCTION fk_set_null_crm_oportunidades() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE crm_reuniones SET oportunidad_id = NULL WHERE tenant_id = OLD.tenant_id AND oportunidad_id = OLD.id;
    RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS fk_set_null ON crm_oportunidades;
CREATE TRIGGER fk_set_null BEFORE DELETE ON crm_oportunidades FOR EACH ROW EXECUTE FUNCTION fk_set_null_crm_oportunidades();

CREATE OR REPLACE FUNCTION fk_set_null_expedientes() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE abogados_minutas SET expediente_id = NULL WHERE tenant_id = OLD.tenant_id AND expediente_id = OLD.id;
    UPDATE partes_tiempo SET expediente_id = NULL WHERE tenant_id = OLD.tenant_id AND expediente_id = OLD.id;
    RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS fk_set_null ON expedientes;
CREATE TRIGGER fk_set_null BEFORE DELETE ON expedientes FOR EACH ROW EXECUTE FUNCTION fk_set_null_expedientes();

CREATE OR REPLACE FUNCTION fk_set_null_facturas_contables() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE fiscal_apuntes SET factura_id = NULL WHERE tenant_id = OLD.tenant_id AND factura_id = OLD.id;
    RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS fk_set_null ON facturas_contables;
CREATE TRIGGER fk_set_null BEFORE DELETE ON facturas_contables FOR EACH ROW EXECUTE FUNCTION fk_set_null_facturas_contables();

CREATE OR REPLACE FUNCTION fk_set_null_inmobiliaria_demandas() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE inmobiliaria_ofertas SET demanda_id = NULL WHERE tenant_id = OLD.tenant_id AND demanda_id = OLD.id;
    UPDATE inmobiliaria_visitas SET demanda_id = NULL WHERE tenant_id = OLD.tenant_id AND demanda_id = OLD.id;
    RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS fk_set_null ON inmobiliaria_demandas;
CREATE TRIGGER fk_set_null BEFORE DELETE ON inmobiliaria_demandas FOR EACH ROW EXECUTE FUNCTION fk_set_null_inmobiliaria_demandas();

CREATE OR REPLACE FUNCTION fk_set_null_vencimientos_fiscales() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE fiscal_declaraciones SET vencimiento_id = NULL WHERE tenant_id = OLD.tenant_id AND vencimiento_id = OLD.id;
    RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS fk_set_null ON vencimientos_fiscales;
CREATE TRIGGER fk_set_null BEFORE DELETE ON vencimientos_fiscales FOR EACH ROW EXECUTE FUNCTION fk_set_null_vencimientos_fiscales();

