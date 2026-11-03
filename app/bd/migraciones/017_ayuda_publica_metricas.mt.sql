-- tablas de plataforma (sin despacho): solo permisos para los roles de la app y del backoffice
GRANT SELECT, INSERT, UPDATE, DELETE ON ayuda_valoraciones TO guilda_app, guilda_plataforma;
GRANT SELECT, INSERT, UPDATE, DELETE ON ayuda_busquedas_vacias TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
