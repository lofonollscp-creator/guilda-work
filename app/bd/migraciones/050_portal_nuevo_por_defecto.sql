-- El portal con la navegación nueva pasa a estar encendido por defecto: nueva base y despachos que no lo han tocado.
ALTER TABLE portal_recordatorios_config ALTER COLUMN portal_nuevo SET DEFAULT 1;
UPDATE portal_recordatorios_config SET portal_nuevo = 1 WHERE portal_nuevo = 0;
