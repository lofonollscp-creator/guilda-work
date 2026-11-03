-- Avisos push genéricos (sin datos personales en la pantalla de bloqueo ni en los servicios de push)
ALTER TABLE usuario_perfil ADD COLUMN IF NOT EXISTS avisos_genericos bigint NOT NULL DEFAULT 0;
