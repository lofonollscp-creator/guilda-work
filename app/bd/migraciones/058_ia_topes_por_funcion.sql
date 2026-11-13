-- Topes de IA por función (lectura de facturas, asistente, correo…) y su consumo mensual, además del tope general del despacho (app/ia_consumo.py)
CREATE TABLE IF NOT EXISTS ia_consumo_funcion (
    tenant_id bigint NOT NULL,
    mes text NOT NULL,
    funcion text NOT NULL,
    usadas integer NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, mes, funcion)
);
CREATE TABLE IF NOT EXISTS ia_tope_funcion (
    tenant_id bigint NOT NULL,
    funcion text NOT NULL,
    limite_mensual integer NOT NULL,
    PRIMARY KEY (tenant_id, funcion)
);
