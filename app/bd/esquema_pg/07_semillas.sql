-- Datos que el esquema da por existentes. Escrito a mano.

-- «Plataforma»: despacho reservado (id 0) para lo que no pertenece a ningún despacho. No es un despacho de verdad (app/bd/tenant.py: TENANT_PLATAFORMA).
-- La identidad de tenants empieza en 1, así que ningún despacho nuevo puede tomar el 0.
INSERT INTO tenants (id, nombre, creado_en) VALUES (0, 'Plataforma', to_char(localtimestamp, 'YYYY-MM-DD"T"HH24:MI:SS')) ON CONFLICT DO NOTHING;
