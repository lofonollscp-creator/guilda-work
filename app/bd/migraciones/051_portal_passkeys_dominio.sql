-- Passkeys del portal: el dominio en el que se creó cada una. Una passkey solo funciona en su dominio, y el portal pasa a servirse también desde clientes.guildawork.com: con esta columna se sabe cuáles se ofrecen en cada dirección. Las anteriores quedan con '' (se suponen de la dirección pública de siempre).
ALTER TABLE portal_passkeys ADD COLUMN IF NOT EXISTS rp_id text NOT NULL DEFAULT '';
