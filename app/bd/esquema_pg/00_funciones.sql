-- Extensiones y funciones que el SQL de la aplicación da por existentes. Escrito a mano.
-- La base de datos debe usar timezone 'Europe/Madrid' (ALTER DATABASE ... SET timezone TO 'Europe/Madrid'):
-- el único DEFAULT con hora local (datetime('now','localtime') en SQLite) se traduce a localtimestamp.
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

-- unaccent() no es IMMUTABLE; este envoltorio sí lo declara, y así puede usarse en índices y columnas generadas.
CREATE OR REPLACE FUNCTION f_unaccent(text) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$;

-- Equivalente de app.nucleo.plano(): minúsculas y sin acentos, para buscar «maria» y encontrar «María».
CREATE OR REPLACE FUNCTION plano(text) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$ SELECT lower(f_unaccent(coalesce($1, ''))) $$;
