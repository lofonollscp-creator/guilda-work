-- Índices de búsqueda de texto: columnas tsvector GENERADAS (sustituyen a las tablas FTS5 y sus triggers) con índice GIN. Escrito a mano.

-- Correo: el cuerpo de un mensaje «entrando, por sellar» (cifrado = 2) NO se indexa hasta que se sella (app/correo_cifrado.py).
ALTER TABLE correo_mensajes ADD COLUMN IF NOT EXISTS busqueda tsvector GENERATED ALWAYS AS (
    CASE WHEN cifrado = 2 THEN NULL
         ELSE tsv_es(coalesce(asunto, '') || ' ' || coalesce(remitente, '') || ' ' || coalesce(destinatarios, '') || ' ' || coalesce(cuerpo_texto, '')) END
) STORED;
CREATE INDEX IF NOT EXISTS idx_correo_busqueda ON correo_mensajes USING gin (busqueda);

-- Corpus jurídico compartido y fragmentos privados de los adjuntos.
ALTER TABLE jur_fragmentos ADD COLUMN IF NOT EXISTS busqueda tsvector GENERATED ALWAYS AS (
    tsv_es(coalesce(texto, '') || ' ' || coalesce(localizador, ''))
) STORED;
CREATE INDEX IF NOT EXISTS idx_jur_fragmentos_busqueda ON jur_fragmentos USING gin (busqueda);

ALTER TABLE jur_fragmentos_privados ADD COLUMN IF NOT EXISTS busqueda tsvector GENERATED ALWAYS AS (tsv_es(texto)) STORED;
CREATE INDEX IF NOT EXISTS idx_jur_fragmentos_privados_busqueda ON jur_fragmentos_privados USING gin (busqueda);
