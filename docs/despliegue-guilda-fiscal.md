# Despliegue de Guilda Fiscal a producción (migraciones 002 y 003)

**Quién:** Jorge (hace falta superusuario de PostgreSQL y reinicio de servicios). **Cuándo:** desde el lunes 26-oct 12:34 (cierre de la vuelta atrás B). **Qué cambia en la base:** SOLO se crean tablas nuevas y vacías
(`fiscal_perfiles`, `fiscal_relaciones` y `fiscal_apuntes`, `fiscal_instantaneas`, `fiscal_declaraciones`, `fiscal_casillas`, `fiscal_artefactos`), una función (`fiscal_dia`), la extensión `btree_gist` y sus triggers;
no se toca ninguna tabla ni dato existente. El código nuevo no se usa hasta que se active «Guilda Fiscal» en un despacho concreto desde el backoffice.

## Orden
1. **El código** ya mezclado en `main` (lo hago yo; no cambia nada en marcha hasta reiniciar).
2. **Copia de seguridad** (por si acaso):
   ```bash
   sudo scripts/backup_postgres.sh base
   ```
3. **Estado de las migraciones** (no cambia nada: debe decir «el código espera: 3 · pendientes: 2, 3»):
   ```bash
   sudo bash -c 'set -a; source /etc/guilda-pg-admin.env; set +a; cd /home/guilda/guilda-work && runuser -u guilda --preserve-environment -- .venv/bin/python scripts/migrar_esquema_pg.py --estado'
   ```
4. **Aplicar** (superusuario; es idempotente: se puede repetir):
   ```bash
   sudo bash -c 'set -a; source /etc/guilda-pg-admin.env; set +a; cd /home/guilda/guilda-work && runuser -u guilda --preserve-environment -- .venv/bin/python scripts/migrar_esquema_pg.py'
   ```
5. **Reiniciar** y comprobar:
   ```bash
   sudo systemctl restart guilda-work guilda-work-mcp
   systemctl is-active guilda-work guilda-work-mcp && curl -s http://127.0.0.1:8000/api/v1/health
   journalctl -u guilda-work -u guilda-work-mcp --since "-3min" -p warning --no-pager
   ```
6. **Verificar** (solo lee el catálogo; debe acabar en «TODO CORRECTO»):
   ```bash
   sudo bash -c 'set -a; source /etc/guilda-work.env; set +a; runuser -u guilda --preserve-environment -- /home/guilda/guilda-work/.venv/bin/python /home/guilda/guilda-work/scripts/fiscal/verificar_despliegue.py'
   ```
7. **Probar con datos inventados**: sigue `docs/guia-guilda-fiscal.md` §4b y los libros de `docs/muestras-fiscal/`. Antes, en el backoffice: un despacho de prueba → activar el módulo «Guilda Fiscal» → menú «Guilda Fiscal» (`/guilda-fiscal/`). Guía: `docs/guia-guilda-fiscal.md`.

## Marcha atrás
Mientras las tablas estén vacías (no se ha usado el módulo), se vuelve al estado anterior sin pérdida:
```sql
DROP TABLE fiscal_artefactos, fiscal_casillas, fiscal_declaraciones, fiscal_apuntes, fiscal_instantaneas, fiscal_relaciones, fiscal_perfiles CASCADE;
DELETE FROM bd_esquema_version WHERE version IN (2, 3);
```
y volver al commit anterior de `main` antes de reiniciar. Si ya hay datos fiscales reales, NO se borra: se restaura desde la copia (`docs/runbooks-postgresql.md`).


## Actualización: migración 004 (factura → «Incluir en Guilda Fiscal»)
Añade la columna `facturas_contables.incluir_en_fiscal` (por defecto 1: todo lo existente sigue contando). Es una sola sentencia, idempotente y rápida. **Orden: primero la migración, luego el reinicio** (con el código nuevo y la base en la versión 3 los servicios no arrancan, por diseño). Revertir: `ALTER TABLE facturas_contables DROP COLUMN incluir_en_fiscal` (y volver al código anterior).
