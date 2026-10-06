"""Backoffice de Guilda Work: aplicación independiente (otro proceso, otro
subdominio, otra sesión y otras credenciales) que administra tenants y
usuarios de la plataforma. Comparte únicamente la base de datos de la
plataforma (registro.db, vía app.db); no usa la sesión ni el login de la app."""
