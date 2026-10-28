-- Declaración fiscal: IBAN de la devolución (o de la cuenta que pide el diseño en una rectificativa con casilla 111)
ALTER TABLE fiscal_declaraciones ADD COLUMN IF NOT EXISTS iban text;
