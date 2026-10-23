-- Triggers portados a mano desde SQLite (RAISE(ABORT, ...) → RAISE EXCEPTION con SQLSTATE 23000, que psycopg
-- convierte en IntegrityError, igual que sqlite3). Los de FTS5 (correo_fts, jur_fragmentos*) llegan en la fase 5.

-- Historial de cambios para la sincronización de la API (api_cambios). Un trigger por tabla para INSERT/UPDATE/DELETE.
CREATE OR REPLACE FUNCTION trg_cambios_notas() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        INSERT INTO api_cambios (entidad, entidad_id, accion, usuario_id, usuario2_id) VALUES ('notas', OLD.id, 'delete', OLD.usuario_id, NULL);
        RETURN OLD;
    END IF;
    INSERT INTO api_cambios (entidad, entidad_id, accion, usuario_id, usuario2_id)
    VALUES ('notas', NEW.id, CASE WHEN NEW.papelera_en IS NOT NULL THEN 'delete' ELSE 'upsert' END, NEW.usuario_id, NULL);
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_cambios_notas ON notas;
CREATE TRIGGER trg_cambios_notas AFTER INSERT OR UPDATE OR DELETE ON notas FOR EACH ROW EXECUTE FUNCTION trg_cambios_notas();

CREATE OR REPLACE FUNCTION trg_cambios_categorias() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        INSERT INTO api_cambios (entidad, entidad_id, accion, usuario_id, usuario2_id) VALUES ('proyectos', OLD.id, 'delete', OLD.usuario_id, NULL);
        RETURN OLD;
    END IF;
    INSERT INTO api_cambios (entidad, entidad_id, accion, usuario_id, usuario2_id)
    VALUES ('proyectos', NEW.id, CASE WHEN NEW.papelera_en IS NOT NULL THEN 'delete' ELSE 'upsert' END, NEW.usuario_id, NULL);
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_cambios_categorias ON categorias;
CREATE TRIGGER trg_cambios_categorias AFTER INSERT OR UPDATE OR DELETE ON categorias FOR EACH ROW EXECUTE FUNCTION trg_cambios_categorias();

CREATE OR REPLACE FUNCTION trg_cambios_tareas() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        INSERT INTO api_cambios (entidad, entidad_id, accion, usuario_id, usuario2_id) VALUES ('tareas', OLD.id, 'delete', OLD.usuario_id, NULL);
        RETURN OLD;
    END IF;
    INSERT INTO api_cambios (entidad, entidad_id, accion, usuario_id, usuario2_id)
    VALUES ('tareas', NEW.id, CASE WHEN NEW.papelera_en IS NOT NULL THEN 'delete' ELSE 'upsert' END, NEW.usuario_id, NULL);
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_cambios_tareas ON tareas;
CREATE TRIGGER trg_cambios_tareas AFTER INSERT OR UPDATE OR DELETE ON tareas FOR EACH ROW EXECUTE FUNCTION trg_cambios_tareas();

CREATE OR REPLACE FUNCTION trg_cambios_tareas_outlook() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        INSERT INTO api_cambios (entidad, entidad_id, accion, usuario_id, usuario2_id) VALUES ('tareas_outlook', OLD.id, 'delete', OLD.usuario_id, OLD.asignada_a);
        RETURN OLD;
    END IF;
    INSERT INTO api_cambios (entidad, entidad_id, accion, usuario_id, usuario2_id)
    VALUES ('tareas_outlook', NEW.id, CASE WHEN NEW.papelera_en IS NOT NULL THEN 'delete' ELSE 'upsert' END, NEW.usuario_id, NEW.asignada_a);
    IF TG_OP = 'UPDATE' AND OLD.asignada_a IS NOT NULL AND OLD.asignada_a IS DISTINCT FROM NEW.asignada_a THEN
        -- quien deja de tener asignada la tarea la ve desaparecer
        INSERT INTO api_cambios (entidad, entidad_id, accion, usuario_id) VALUES ('tareas_outlook', NEW.id, 'delete', OLD.asignada_a);
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_cambios_tareas_outlook ON tareas_outlook;
CREATE TRIGGER trg_cambios_tareas_outlook AFTER INSERT OR UPDATE OR DELETE ON tareas_outlook FOR EACH ROW EXECUTE FUNCTION trg_cambios_tareas_outlook();

-- Auditoría de solo anexado.
CREATE OR REPLACE FUNCTION auditoria_sin_modificar() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'La auditoría es solo de anexado: no se puede modificar.' USING ERRCODE = 'integrity_constraint_violation';
END $$;
DROP TRIGGER IF EXISTS auditoria_sin_modificar ON auditoria_eventos;
CREATE TRIGGER auditoria_sin_modificar BEFORE UPDATE ON auditoria_eventos FOR EACH ROW EXECUTE FUNCTION auditoria_sin_modificar();

CREATE OR REPLACE FUNCTION auditoria_sin_borrar() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- (la condición no puede ir en WHEN: PostgreSQL no admite subconsultas ahí)
    IF COALESCE((SELECT valor FROM auditoria_control WHERE clave = 'permitir_borrado'), '0') <> '1' THEN
        RAISE EXCEPTION 'La auditoría es solo de anexado: no se puede borrar.' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS auditoria_sin_borrar ON auditoria_eventos;
CREATE TRIGGER auditoria_sin_borrar BEFORE DELETE ON auditoria_eventos FOR EACH ROW EXECUTE FUNCTION auditoria_sin_borrar();

-- tareas_outlook: versión (control de concurrencia optimista), cliente principal y estado «en revisión».
CREATE OR REPLACE FUNCTION tareas_outlook_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.version = OLD.version THEN
        NEW.version := OLD.version + 1;
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS tareas_outlook_version ON tareas_outlook;
CREATE TRIGGER tareas_outlook_version BEFORE UPDATE ON tareas_outlook FOR EACH ROW EXECUTE FUNCTION tareas_outlook_version();

CREATE OR REPLACE FUNCTION tareas_outlook_cliente_alta() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO tarea_clientes (tenant_id, tarea_id, cliente_fiscal_id, principal, creado_en)
    SELECT tenant_id, NEW.id, id, 1, NEW.creada_en FROM clientes_fiscales WHERE id = NEW.cliente_fiscal_id
    ON CONFLICT DO NOTHING;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS tareas_outlook_cliente_alta ON tareas_outlook;
CREATE TRIGGER tareas_outlook_cliente_alta AFTER INSERT ON tareas_outlook FOR EACH ROW WHEN (NEW.cliente_fiscal_id IS NOT NULL) EXECUTE FUNCTION tareas_outlook_cliente_alta();

CREATE OR REPLACE FUNCTION tareas_outlook_cliente_cambio() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM tarea_clientes WHERE tarea_id = NEW.id AND principal = 1 AND cliente_fiscal_id IS NOT DISTINCT FROM OLD.cliente_fiscal_id;
    UPDATE tarea_clientes SET principal = 0 WHERE tarea_id = NEW.id AND principal = 1 AND cliente_fiscal_id IS DISTINCT FROM NEW.cliente_fiscal_id;
    INSERT INTO tarea_clientes (tenant_id, tarea_id, cliente_fiscal_id, principal, creado_en)
    SELECT tenant_id, NEW.id, id, 0, COALESCE(NEW.actualizada_en, NEW.creada_en) FROM clientes_fiscales WHERE id = NEW.cliente_fiscal_id
    ON CONFLICT DO NOTHING;
    UPDATE tarea_clientes SET principal = 1 WHERE tarea_id = NEW.id AND cliente_fiscal_id = NEW.cliente_fiscal_id;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS tareas_outlook_cliente_cambio ON tareas_outlook;
CREATE TRIGGER tareas_outlook_cliente_cambio AFTER UPDATE OF cliente_fiscal_id ON tareas_outlook FOR EACH ROW
    WHEN (NEW.cliente_fiscal_id IS DISTINCT FROM OLD.cliente_fiscal_id) EXECUTE FUNCTION tareas_outlook_cliente_cambio();

CREATE OR REPLACE FUNCTION tareas_outlook_en_revision_entrada() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM tarea_revisiones r WHERE r.tarea_id = NEW.id AND r.estado = 'pendiente') THEN
        RAISE EXCEPTION 'solo_por_revision' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS tareas_outlook_en_revision_entrada ON tareas_outlook;
CREATE TRIGGER tareas_outlook_en_revision_entrada BEFORE UPDATE OF estado ON tareas_outlook FOR EACH ROW
    WHEN (NEW.estado = 'en_revision' AND OLD.estado <> 'en_revision') EXECUTE FUNCTION tareas_outlook_en_revision_entrada();

CREATE OR REPLACE FUNCTION tareas_outlook_en_revision_salida() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM tarea_revisiones r WHERE r.tarea_id = NEW.id AND r.estado = 'pendiente') THEN
        RAISE EXCEPTION 'revision_pendiente' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS tareas_outlook_en_revision_salida ON tareas_outlook;
CREATE TRIGGER tareas_outlook_en_revision_salida BEFORE UPDATE OF estado ON tareas_outlook FOR EACH ROW
    WHEN (OLD.estado = 'en_revision' AND NEW.estado <> 'en_revision') EXECUTE FUNCTION tareas_outlook_en_revision_salida();
