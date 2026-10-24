# Migraciones del esquema de PostgreSQL

Cada cambio de esquema posterior al esquema base (versión 1) es un fichero `NNN_descripcion.sql` con `NNN` > 1, **idempotente** (`IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`…).
Se aplican en orden con `scripts/migrar_esquema_pg.py` (superusuario) **antes de reiniciar los servicios**; el arranque solo comprueba que la base esté en la versión que espera el código.

* `NNN_x.sql` — todos los modos.
* `NNN_x.mt.sql` — además, solo si el esquema es multitenant o Citus (columnas `tenant_id`, políticas RLS, permisos de los roles…).
* `NNN_x.citus.sql` — además, solo en Citus (`create_distributed_table`, `create_reference_table`…).

Primera línea del fichero base: `-- Descripción corta` (se guarda en `bd_esquema_version`). En Citus las sentencias se ejecutan una a una (la distribución no es transaccional); en los demás modos, todas en una transacción.
Una tabla nueva de un despacho necesita las tres cosas: `CREATE TABLE` con `tenant_id`, sus políticas RLS y su distribución; mira `app/bd/esquema_pg/mt/` para el patrón.
