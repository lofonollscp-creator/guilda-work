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

-- Búsqueda de texto (fase 5), equivalente al tokenizador de SQLite `unicode61 remove_diacritics 2`: minúsculas, sin acentos (ñ→n),
-- sin raíces (no hay «stemming»: la recuperación jurídica se mide contra el comportamiento de SQLite) y cualquier carácter que no sea
-- letra o cifra separa palabras («1.101», «BOE-A-2023-1234», «acme.com» se parten igual que en SQLite).
-- Requiere una base de datos con LC_CTYPE UTF-8 (no «C»): con «C» las letras acentuadas no cuentan como letras.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'es_simple') THEN
        CREATE TEXT SEARCH CONFIGURATION es_simple (COPY = simple);
        ALTER TEXT SEARCH CONFIGURATION es_simple
            ALTER MAPPING FOR asciiword, word, numword, asciihword, hword, numhword, hword_asciipart, hword_part, hword_numpart
            WITH unaccent, simple;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION texto_buscable(text) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$ SELECT regexp_replace(coalesce($1, ''), '[\W_]+', ' ', 'g') $$;

CREATE OR REPLACE FUNCTION tsv_es(text) RETURNS tsvector LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$ SELECT to_tsvector('es_simple'::regconfig, texto_buscable($1)) $$;
