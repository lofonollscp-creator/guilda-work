-- Política de acceso del despacho: exigir segundo factor o passkey a todo el equipo hasta una fecha límite.
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS exigir_segundo_factor integer NOT NULL DEFAULT 0;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS segundo_factor_limite text;
