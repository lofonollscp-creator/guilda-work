-- Roles de la aplicación (escrito a mano). Los CREA SIN CONTRASEÑA: quien despliega fija la contraseña fuera del repositorio
-- (ALTER ROLE guilda_app PASSWORD '…'). Citus abre conexiones internas con el MISMO rol de la sesión, así que ambos son LOGIN.
--
--   guilda_app         la aplicación web / API / MCP. NO se salta la RLS: cada conexión ve y escribe solo su despacho (app.tenant_id).
--   guilda_plataforma  backoffice, trabajadores en segundo plano y borrado de despachos. SE SALTA la RLS: trabaja entre despachos.
-- El propietario de las tablas (el rol de las migraciones) tampoco está sujeto a la RLS salvo que se fuerce.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'guilda_app') THEN
        CREATE ROLE guilda_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'guilda_plataforma') THEN
        CREATE ROLE guilda_plataforma LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO guilda_app, guilda_plataforma;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO guilda_app, guilda_plataforma;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO guilda_app, guilda_plataforma;

-- Auditoría de solo anexado (D7): además del trigger, la aplicación no puede modificar ni borrar. Solo la plataforma borra (al eliminar un despacho).
REVOKE UPDATE, DELETE, TRUNCATE ON auditoria_eventos, jur_auditoria FROM guilda_app;
REVOKE UPDATE, TRUNCATE ON auditoria_eventos, jur_auditoria FROM guilda_plataforma;
-- La configuración global y el catálogo de despachos no los toca la aplicación de un despacho.
REVOKE INSERT, UPDATE, DELETE ON tenants, planes_guilda, extras_guilda, reglas_fiscales, reglas_laborales, auditoria_control FROM guilda_app;
