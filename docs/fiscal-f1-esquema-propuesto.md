# F1 · Esquema propuesto (jerarquía fiscal y perfiles) — para tu visto bueno 🔒

> **Estado:** propuesta; **no aplicada** (ni en SQLite ni en PostgreSQL). Cumple el paso 3 de §13 de `plan-modulo-fiscal-alquileres.md`: «proponerte el esquema exacto de F1 antes de aplicar nada».
> **Cuándo se puede aplicar:** no antes del **lun 26-oct 12:34** (cierra la vuelta atrás B; hasta entonces no hay cambios de esquema). Es la **primera migración numerada real** de PostgreSQL (hoy `app/bd/migraciones/` solo tiene el `LEEME.md`).
> **Revisado tras F0** (`fiscal-f0-informe.md` §3): el diseño oficial del 303 pide cuatro indicadores que el perfil no tenía (`tributacion_foral`, `autoliquidacion_conjunta`, `exonerado_390`, `deduce_pago_cuenta_carburantes`), separa la opción de **prorrata especial** y distingue «solo régimen simplificado / general + simplificado / solo general» (`regimen_iva`). Los datos **por periodo** (concurso, destinatario de criterio de caja, volumen de operaciones, tipo de declaración, IBAN) **no** van en el perfil sino en `fiscal_declaraciones` (F4). Las instrucciones por periodo (2T–4T) pueden aún añadir algo; cualquier cambio se hace **antes** de aplicar.

## 1. Alcance de F1

| Tabla | Para qué | Tipo en Citus |
|---|---|---|
| `fiscal_perfiles` | Perfil fiscal **versionado** del titular (vigencias): forma jurídica, residencia, territorio de IVA, régimen, periodicidad, opciones y saldos | distribuida por `tenant_id` |
| `fiscal_relaciones` | Quién cuelga de quién (empresa gestora → titulares, grupos), con vigencia | distribuida por `tenant_id` |

Más, sin esquema: registrar los verticales `fiscal` («Guilda Fiscal») y `alquileres` («Guilda Fiscal Alquileres», reservado) en `app/verticales.py` con `disponible=False` hasta que tengan pantallas, y el alta de los dos extras en el backoffice.

**Reglas que fija el esquema** (se prueban): un titular **nunca** se fusiona con otro por compartir inmueble o gestora; las vigencias de un mismo titular **no se solapan**; todo dato lleva su despacho (`tenant_id`) y la clave foránea al cliente fiscal es **compuesta** `(tenant_id, cliente_fiscal_id)` para que no se pueda apuntar a un titular de otro despacho.

## 2. SQLite (`esquema(conn)` del vertical `fiscal`, en `app/fiscal_perfiles.py`)

```sql
CREATE TABLE IF NOT EXISTS fiscal_perfiles (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    vigente_desde TEXT NOT NULL,                       -- AAAA-MM-DD
    vigente_hasta TEXT,                                -- NULL = vigente
    forma_juridica TEXT NOT NULL CHECK (forma_juridica IN ('persona_fisica','sociedad','comunidad_bienes','otra')),
    residencia TEXT NOT NULL DEFAULT 'ES' CHECK (residencia IN ('ES','UE','otro')),
    pais TEXT,                                         -- ISO-3166 alfa-2 cuando no es ES
    territorio_iva TEXT NOT NULL DEFAULT 'peninsula_baleares' CHECK (territorio_iva IN ('peninsula_baleares','canarias','ceuta_melilla')),
    regimen_iva TEXT NOT NULL DEFAULT 'general' CHECK (regimen_iva IN ('general','simplificado','general_y_simplificado','recargo','exento','otro')),
    periodicidad TEXT NOT NULL DEFAULT 'trimestral' CHECK (periodicidad IN ('trimestral','mensual')),
    criterio_caja INTEGER NOT NULL DEFAULT 0,
    sii INTEGER NOT NULL DEFAULT 0,
    redeme INTEGER NOT NULL DEFAULT 0,
    tributacion_foral INTEGER NOT NULL DEFAULT 0,          -- tributa exclusivamente a una Administración foral (F0: lo pide el diseño oficial)
    autoliquidacion_conjunta INTEGER NOT NULL DEFAULT 0,
    exonerado_390 INTEGER NOT NULL DEFAULT 0,              -- exonerado de la declaración-resumen anual
    deduce_pago_cuenta_carburantes INTEGER NOT NULL DEFAULT 0,
    prorrata_especial INTEGER NOT NULL DEFAULT 0,          -- opción por la prorrata especial (art. 103.Dos.1º LIVA)
    prorrata_centesimas INTEGER,                       -- NULL = sin prorrata general; en centésimas de punto
    sectores_diferenciados INTEGER NOT NULL DEFAULT 0,
    saldo_a_compensar_centimos INTEGER NOT NULL DEFAULT 0,
    actividades TEXT,                                  -- JSON: [{epigrafe, descripcion}]
    opciones TEXT,                                     -- JSON: opciones fiscales que pida el diseño oficial (se concretan en F0)
    notas TEXT,
    version INTEGER NOT NULL DEFAULT 1,                -- control optimista (409/412 version_obsoleta)
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    actualizado_en TEXT,
    CHECK (vigente_hasta IS NULL OR vigente_hasta >= vigente_desde),
    CHECK (residencia = 'ES' OR pais IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fiscal_perfiles_vigencia ON fiscal_perfiles(tenant_id, cliente_fiscal_id, vigente_desde);
CREATE INDEX IF NOT EXISTS idx_fiscal_perfiles_cliente ON fiscal_perfiles(tenant_id, cliente_fiscal_id, vigente_hasta);

CREATE TABLE IF NOT EXISTS fiscal_relaciones (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    desde_cliente_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,   -- la gestora, la matriz…
    hasta_cliente_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,   -- el titular, la filial…
    tipo TEXT NOT NULL DEFAULT 'gestora_titular' CHECK (tipo IN ('gestora_titular','grupo','otro')),
    vigente_desde TEXT NOT NULL,
    vigente_hasta TEXT,
    notas TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    CHECK (desde_cliente_id <> hasta_cliente_id),
    CHECK (vigente_hasta IS NULL OR vigente_hasta >= vigente_desde)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fiscal_relaciones_unica ON fiscal_relaciones(tenant_id, desde_cliente_id, hasta_cliente_id, tipo, vigente_desde);
CREATE INDEX IF NOT EXISTS idx_fiscal_relaciones_hasta ON fiscal_relaciones(tenant_id, hasta_cliente_id);
```

**No solapamiento de vigencias** (SQLite no tiene restricciones de exclusión): lo impone la función de guardado (`guardar_perfil`) dentro de la misma transacción y lo cubre una prueba; en PostgreSQL además lo impone la base con una restricción de exclusión (§3).

## 3. PostgreSQL — migración numerada `002_fiscal_perfiles_y_relaciones`

Convención (`app/bd/migraciones/LEEME.md`): `NNN_x.sql` (todos los modos) · `NNN_x.mt.sql` (despachos: `tenant_id`, RLS, permisos) · `NNN_x.citus.sql` (distribución). Idempotentes. Primera línea = descripción.

**`002_fiscal_perfiles_y_relaciones.sql`**

```sql
-- Perfil fiscal versionado del titular y relaciones gestora↔titular (Guilda Fiscal, F1)
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE TABLE IF NOT EXISTS fiscal_perfiles (
    id bigint GENERATED BY DEFAULT AS IDENTITY,
    cliente_fiscal_id bigint NOT NULL,
    vigente_desde text NOT NULL,
    vigente_hasta text,
    forma_juridica text NOT NULL CHECK (forma_juridica IN ('persona_fisica','sociedad','comunidad_bienes','otra')),
    residencia text NOT NULL DEFAULT 'ES' CHECK (residencia IN ('ES','UE','otro')),
    pais text,
    territorio_iva text NOT NULL DEFAULT 'peninsula_baleares' CHECK (territorio_iva IN ('peninsula_baleares','canarias','ceuta_melilla')),
    regimen_iva text NOT NULL DEFAULT 'general' CHECK (regimen_iva IN ('general','simplificado','general_y_simplificado','recargo','exento','otro')),
    periodicidad text NOT NULL DEFAULT 'trimestral' CHECK (periodicidad IN ('trimestral','mensual')),
    criterio_caja bigint NOT NULL DEFAULT 0,
    sii bigint NOT NULL DEFAULT 0,
    redeme bigint NOT NULL DEFAULT 0,
    tributacion_foral bigint NOT NULL DEFAULT 0,
    autoliquidacion_conjunta bigint NOT NULL DEFAULT 0,
    exonerado_390 bigint NOT NULL DEFAULT 0,
    deduce_pago_cuenta_carburantes bigint NOT NULL DEFAULT 0,
    prorrata_especial bigint NOT NULL DEFAULT 0,
    prorrata_centesimas bigint,
    sectores_diferenciados bigint NOT NULL DEFAULT 0,
    saldo_a_compensar_centimos bigint NOT NULL DEFAULT 0,
    actividades text,
    opciones text,
    notas text,
    version bigint NOT NULL DEFAULT 1,
    creado_por bigint,
    creado_en text NOT NULL,
    actualizado_en text,
    CHECK (vigente_hasta IS NULL OR vigente_hasta >= vigente_desde),
    CHECK (residencia = 'ES' OR pais IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS fiscal_relaciones (
    id bigint GENERATED BY DEFAULT AS IDENTITY,
    desde_cliente_id bigint NOT NULL,
    hasta_cliente_id bigint NOT NULL,
    tipo text NOT NULL DEFAULT 'gestora_titular' CHECK (tipo IN ('gestora_titular','grupo','otro')),
    vigente_desde text NOT NULL,
    vigente_hasta text,
    notas text,
    creado_por bigint,
    creado_en text NOT NULL,
    CHECK (desde_cliente_id <> hasta_cliente_id),
    CHECK (vigente_hasta IS NULL OR vigente_hasta >= vigente_desde)
);
```

**`002_fiscal_perfiles_y_relaciones.mt.sql`** (despacho: columna, claves, FK compuestas, RLS)

```sql
ALTER TABLE fiscal_perfiles   ADD COLUMN IF NOT EXISTS tenant_id bigint NOT NULL DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
ALTER TABLE fiscal_relaciones ADD COLUMN IF NOT EXISTS tenant_id bigint NOT NULL DEFAULT nullif(current_setting('app.tenant_id', true), '')::bigint;
-- clave primaria con tenant_id (obligatoria para poder mover fragmentos entre nodos)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fiscal_perfiles_pkey')   THEN ALTER TABLE fiscal_perfiles   ADD CONSTRAINT fiscal_perfiles_pkey   PRIMARY KEY (tenant_id, id); END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fiscal_relaciones_pkey') THEN ALTER TABLE fiscal_relaciones ADD CONSTRAINT fiscal_relaciones_pkey PRIMARY KEY (tenant_id, id); END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS idx_fiscal_perfiles_vigencia  ON fiscal_perfiles (tenant_id, cliente_fiscal_id, vigente_desde);
CREATE INDEX        IF NOT EXISTS idx_fiscal_perfiles_cliente   ON fiscal_perfiles (tenant_id, cliente_fiscal_id, vigente_hasta);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fiscal_relaciones_unica   ON fiscal_relaciones (tenant_id, desde_cliente_id, hasta_cliente_id, tipo, vigente_desde);
CREATE INDEX        IF NOT EXISTS idx_fiscal_relaciones_hasta   ON fiscal_relaciones (tenant_id, hasta_cliente_id);
-- sin solapamiento de vigencias del mismo titular (la base lo impone, no solo la aplicación)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fiscal_perfiles_sin_solape') THEN
    ALTER TABLE fiscal_perfiles ADD CONSTRAINT fiscal_perfiles_sin_solape EXCLUDE USING gist (
      tenant_id WITH =, cliente_fiscal_id WITH =,
      daterange(vigente_desde::date, COALESCE(vigente_hasta::date, 'infinity'::date), '[]') WITH &&);
  END IF;
END $$;
-- claves foráneas compuestas: no se puede apuntar a un titular de otro despacho
ALTER TABLE fiscal_perfiles   DROP CONSTRAINT IF EXISTS fk_fiscal_perfiles_cliente;
ALTER TABLE fiscal_perfiles   ADD  CONSTRAINT fk_fiscal_perfiles_cliente   FOREIGN KEY (tenant_id, cliente_fiscal_id) REFERENCES clientes_fiscales (tenant_id, id) ON DELETE CASCADE;
ALTER TABLE fiscal_relaciones DROP CONSTRAINT IF EXISTS fk_fiscal_relaciones_desde;
ALTER TABLE fiscal_relaciones ADD  CONSTRAINT fk_fiscal_relaciones_desde   FOREIGN KEY (tenant_id, desde_cliente_id) REFERENCES clientes_fiscales (tenant_id, id) ON DELETE CASCADE;
ALTER TABLE fiscal_relaciones DROP CONSTRAINT IF EXISTS fk_fiscal_relaciones_hasta;
ALTER TABLE fiscal_relaciones ADD  CONSTRAINT fk_fiscal_relaciones_hasta   FOREIGN KEY (tenant_id, hasta_cliente_id) REFERENCES clientes_fiscales (tenant_id, id) ON DELETE CASCADE;
ALTER TABLE fiscal_perfiles   DROP CONSTRAINT IF EXISTS fk_fiscal_perfiles_tenant;
ALTER TABLE fiscal_perfiles   ADD  CONSTRAINT fk_fiscal_perfiles_tenant   FOREIGN KEY (tenant_id) REFERENCES tenants (id);
ALTER TABLE fiscal_relaciones DROP CONSTRAINT IF EXISTS fk_fiscal_relaciones_tenant;
ALTER TABLE fiscal_relaciones ADD  CONSTRAINT fk_fiscal_relaciones_tenant FOREIGN KEY (tenant_id) REFERENCES tenants (id);
-- aislamiento por despacho (RLS)
ALTER TABLE fiscal_perfiles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON fiscal_perfiles;
CREATE POLICY aislamiento ON fiscal_perfiles USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
ALTER TABLE fiscal_relaciones ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS aislamiento ON fiscal_relaciones;
CREATE POLICY aislamiento ON fiscal_relaciones USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON fiscal_perfiles, fiscal_relaciones TO guilda_app, guilda_plataforma;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO guilda_app, guilda_plataforma;
```

**`002_fiscal_perfiles_y_relaciones.citus.sql`** (una sentencia por vez; la distribución no es transaccional)

```sql
SELECT create_distributed_table('fiscal_perfiles',   'tenant_id', colocate_with => 'abogados_ajustes');
SELECT create_distributed_table('fiscal_relaciones', 'tenant_id', colocate_with => 'abogados_ajustes');
```

> **Puntos a verificar en el ensayo antes de proponerlo como definitivo** (los que ya mordieron en la migración a Citus, `docs/adr-postgresql-citus.md`): (1) una restricción `EXCLUDE … gist` **sobre una tabla distribuida** (Citus 14: los índices de exclusión están soportados si incluyen la columna de distribución, que aquí es la primera con `=`; si no, se deja solo la comprobación de la aplicación + prueba); (2) `GENERATED … AS IDENTITY` + clave foránea a tabla de referencia en el mismo `CREATE TABLE` (se evita creando las FK después, como arriba); (3) `btree_gist` instalada por el superusuario que aplica la migración; (4) el orden «`.sql` → `.mt.sql` → `.citus.sql`» con la tabla ya vacía.

## 4. Pruebas de F1 (antes del código, y en los dos motores)

| Prueba | Qué fija |
|---|---|
| `test_fiscal_perfiles_aislamiento` | Un despacho no ve ni escribe perfiles de otro (RLS); apuntar a un titular de otro despacho falla por la FK compuesta |
| `test_fiscal_perfiles_vigencias` | Dos perfiles del mismo titular no se solapan (aplicación y, en PostgreSQL, la base); `vigente_hasta ≥ vigente_desde`; el perfil vigente en una fecha se resuelve bien en los límites |
| `test_fiscal_relaciones` | Una gestora con 150 titulares; un titular en dos gestoras en fechas distintas; nunca se fusionan; `desde ≠ hasta` |
| `test_fiscal_version` | Editar con `version` vieja da `version_obsoleta` |
| `test_migracion_002` | La migración es **idempotente** (se aplica dos veces), está en `bd_esquema_version`, y el esquema resultante coincide con el generado desde SQLite salvo lo del despacho (`comparar_esquemas`) |
| `test_citus_fiscal` | Las dos tablas quedan **distribuidas y colocalizadas** con las demás; tienen clave primaria con `tenant_id` |
| Concurrencia | Altas simultáneas de perfiles de 12 clientes no dan interbloqueos (se añade al guion de `prueba_concurrencia_api.py`) |

## 5. Verificación y reversión

- **Ensayo**: migrar una copia de los datos reales al contenedor de ensayo, aplicar `002`, `verificar_migracion.py` (recuentos y sumas por columna: las tablas nuevas empiezan vacías), suites SQLite y PostgreSQL, y **simulacro de restauración** (`restaurar_postgres.sh`) con las tablas nuevas.
- **Producción**: copia base previa (`backup_postgres.sh`), `scripts/migrar_esquema_pg.py` por tu parte (superusuario), reinicio de los servicios y comprobación con `scripts/revision_postgres.py`.
- **Reversión**: las tablas son **nuevas y vacías**: `DROP TABLE fiscal_perfiles, fiscal_relaciones` las retira sin tocar nada existente; el código que las usa queda detrás de `verticales` (`disponible=False`), así que un despacho que no tenga el extra no las toca.
