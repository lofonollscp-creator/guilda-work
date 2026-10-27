-- Declaración fiscal: número de justificante (13 cifras) de la autoliquidación que rectifica
ALTER TABLE fiscal_declaraciones ADD COLUMN IF NOT EXISTS justificante_anterior text;
