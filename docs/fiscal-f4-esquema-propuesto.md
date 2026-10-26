# F4 · Esquema propuesto (apuntes, instantáneas, declaraciones y casillas) — para tu visto bueno 🔒

> **Estado:** propuesta; **no aplicada** (ni en SQLite ni en PostgreSQL). Misma disciplina que F1: antes de escribir una sola tabla, te enseño el esquema exacto y espero tu «sí».
> **Qué ya existe y no hace falta guardar:** el motor del 303 (`motor_303.py`), el escritor de libros (`libros_lsi.py`), el generador del `.303` (`fichero_303.py`), el validador (`validacion_apuntes.py`) y `preparar_303.py` son **funciones puras**, contrastadas con la AEAT en 20 escenarios. Lo que falta es **dónde viven los datos** que esas funciones consumen y producen.
> **Cuándo se puede aplicar:** después de F1 (migración 002) y de tu aprobación; sería la migración **003**. Reversible con `DROP TABLE` de tablas nuevas y vacías (mientras estén vacías).

## 1. Principios (los que fija el plan, §4 y §8)

1. **Una sola tabla de facturas** (`facturas_contables`); lo fiscal cuelga de ella, no la duplica.
2. **El registro fiscal aprobado (`fiscal_apuntes`) es lo único que calcula.** La extracción por IA nunca llega al cálculo sin que una persona apruebe el apunte.
3. **Instantánea inmutable:** al aprobar un periodo se congela (perfil, apuntes, ajustes, versión de reglas y del diseño) con un hash. Una declaración se calcula **sobre la instantánea**, nunca sobre datos vivos; recalcular da lo mismo.
4. **Exportar ≠ presentar.** La declaración tiene estados separados; lo presentado no se altera (se abre una rectificativa).
5. **Todo dato lleva su despacho** (`tenant_id`, RLS, claves foráneas compuestas) y se prueba en SQLite, PostgreSQL y Citus, como F1.

## 2. Tablas

| Tabla | Para qué | Notas |
|---|---|---|
| `fiscal_apuntes` | Una línea del libro registro **aprobada**: es exactamente un `Apunte` del motor | `factura_id` opcional (los hay manuales o importados de un libro); `version` y borrado lógico (`anulado_en`); `aprobado_por/en` obligatorios |
| `fiscal_instantaneas` | Foto inmutable de un titular + modelo + ejercicio + periodo | `contenido` JSON congelado + `hash` SHA-256; **sin UPDATE ni DELETE** (triggers, como `auditoria_eventos`) |
| `fiscal_declaraciones` | Una declaración (303…) calculada sobre una instantánea | `estado`: `borrador → revisada → exportada → presentada`; `rectifica_a_id`; `version_motor`, `version_diseno` |
| `fiscal_casillas` | Valor de cada casilla de la declaración | `casilla`, `valor` (céntimos o centésimas), `explicacion`; las trazas (`origen` del motor) en JSON |
| `fiscal_artefactos` | Ficheros generados (`.303`, libro `.xlsx`, resumen legible) | `tipo`, `hash`, `contenido` (cifrable por el almacén ya existente) |

Quedan **fuera** de esta propuesta (otras fases, otras aprobaciones): `fiscal_extracciones/campos` (F2, lectura IA con evidencia), `fiscal_ajustes`, `fiscal_reglas/disenos/cobertura` (referencia), `fiscal_justificantes`, y el vertical de alquileres (`alq_*`).

## 3. SQLite

```sql
CREATE TABLE IF NOT EXISTS fiscal_apuntes (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    factura_id INTEGER REFERENCES facturas_contables(id) ON DELETE SET NULL,
    libro TEXT NOT NULL CHECK (libro IN ('E','R')),
    tipo_factura TEXT NOT NULL,                       -- F1…F6, R1…R5, AJ, SF, DV, LC
    clave TEXT NOT NULL DEFAULT '01',
    calificacion TEXT NOT NULL DEFAULT 'S1',
    exenta TEXT NOT NULL DEFAULT '',
    serie TEXT NOT NULL DEFAULT '',
    numero TEXT NOT NULL,
    fecha_expedicion TEXT NOT NULL,
    fecha_operacion TEXT,
    fecha_recepcion TEXT,
    base_centimos INTEGER NOT NULL,
    tipo_iva_centesimas INTEGER NOT NULL DEFAULT 0,
    cuota_centimos INTEGER NOT NULL DEFAULT 0,
    total_centimos INTEGER,
    cuota_deducible_centimos INTEGER,                 -- NULL = toda la cuota soportada
    isp INTEGER NOT NULL DEFAULT 0,
    bien_inversion INTEGER NOT NULL DEFAULT 0,
    deducible_periodo_posterior INTEGER NOT NULL DEFAULT 0,
    periodo_deduccion TEXT,                           -- 'AAAA-2T'
    contraparte_nombre TEXT NOT NULL,
    contraparte_nif TEXT,
    contraparte_nif_tipo TEXT NOT NULL DEFAULT '',
    contraparte_pais TEXT NOT NULL DEFAULT '',
    causa TEXT,                                       -- por qué la cuota deducible es la que es (si no es toda)
    version INTEGER NOT NULL DEFAULT 1,
    aprobado_por INTEGER NOT NULL REFERENCES usuarios(id),
    aprobado_en TEXT NOT NULL,
    anulado_en TEXT,
    creado_en TEXT NOT NULL,
    actualizado_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_fiscal_apuntes_periodo ON fiscal_apuntes(tenant_id, cliente_fiscal_id, libro, fecha_expedicion);
CREATE INDEX IF NOT EXISTS idx_fiscal_apuntes_factura ON fiscal_apuntes(tenant_id, factura_id);

CREATE TABLE IF NOT EXISTS fiscal_instantaneas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    modelo TEXT NOT NULL,                             -- '303'
    ejercicio INTEGER NOT NULL,
    periodo TEXT NOT NULL,                            -- '1T'…'4T', '01'…'12'
    hash TEXT NOT NULL,
    contenido TEXT NOT NULL,                          -- JSON congelado: perfil, apuntes, ajustes, versión del motor y del diseño
    aprobada_por INTEGER NOT NULL REFERENCES usuarios(id),
    aprobada_en TEXT NOT NULL,
    sustituye_a_id INTEGER REFERENCES fiscal_instantaneas(id),   -- una instantánea nueva no borra la anterior: la sustituye
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fiscal_instantaneas ON fiscal_instantaneas(tenant_id, cliente_fiscal_id, modelo, ejercicio, periodo);

CREATE TABLE IF NOT EXISTS fiscal_declaraciones (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    instantanea_id INTEGER NOT NULL REFERENCES fiscal_instantaneas(id),
    vencimiento_id INTEGER REFERENCES vencimientos_fiscales(id) ON DELETE SET NULL,
    modelo TEXT NOT NULL,
    ejercicio INTEGER NOT NULL,
    periodo TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador','revisada','exportada','presentada','anulada')),
    tipo_declaracion TEXT NOT NULL DEFAULT 'N',       -- I, N, C, D… (página 1, campo 6)
    resultado_centimos INTEGER NOT NULL DEFAULT 0,    -- casilla 71
    version_motor TEXT NOT NULL,
    version_diseno TEXT NOT NULL,
    rectifica_a_id INTEGER REFERENCES fiscal_declaraciones(id),
    bloqueos TEXT,                                    -- JSON: por qué no se pudo calcular (si no se pudo)
    revisada_por INTEGER REFERENCES usuarios(id),
    revisada_en TEXT,
    exportada_en TEXT,
    presentada_en TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fiscal_declaraciones ON fiscal_declaraciones(tenant_id, cliente_fiscal_id, modelo, ejercicio, periodo);

CREATE TABLE IF NOT EXISTS fiscal_casillas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    declaracion_id INTEGER NOT NULL REFERENCES fiscal_declaraciones(id) ON DELETE CASCADE,
    casilla TEXT NOT NULL,
    valor INTEGER NOT NULL,                           -- céntimos (o centésimas en porcentajes)
    origen TEXT                                       -- JSON: índices de los apuntes de la instantánea que la forman
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fiscal_casillas ON fiscal_casillas(tenant_id, declaracion_id, casilla);

CREATE TABLE IF NOT EXISTS fiscal_artefactos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    declaracion_id INTEGER NOT NULL REFERENCES fiscal_declaraciones(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL CHECK (tipo IN ('303','libro_xlsx','resumen')),
    hash TEXT NOT NULL,
    contenido BLOB NOT NULL,
    informe_validacion TEXT,                          -- JSON: problemas que se vieron al generarlo
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fiscal_artefactos ON fiscal_artefactos(tenant_id, declaracion_id, tipo);
```

**Inmutabilidad** (SQLite y PostgreSQL): triggers que rechazan `UPDATE` y `DELETE` en `fiscal_instantaneas`, y `UPDATE` de `valor` en `fiscal_casillas`/`contenido` en `fiscal_artefactos` cuando la declaración está `exportada` o `presentada`. Se prueban en los tres motores (el patrón es el de `auditoria_eventos`, ya probado en Citus).

## 4. PostgreSQL / Citus — migración 003

Mismo molde que la 002 (ya probada): `003_fiscal_nucleo.sql` (tablas), `.mt.sql` (`tenant_id`, clave primaria `(tenant_id, id)`, RLS `aislamiento`, permisos) y `.citus.sql` (distribución idempotente, `colocate_with => 'abogados_ajustes'`, **claves foráneas después de distribuir**). Lo aprendido con F1 se aplica de entrada: nada de funciones no inmutables en restricciones, claves foráneas compuestas `(tenant_id, …)` y tablas hijas distribuidas con el mismo `tenant_id`.

## 5. Pruebas (antes del código, en los dos motores)

| Prueba | Qué fija |
|---|---|
| `test_fiscal_nucleo_aislamiento` | Un despacho no ve ni toca apuntes/declaraciones de otro (RLS y FK compuestas) |
| `test_fiscal_apunte_ida_y_vuelta` | `Apunte` → fila → `Apunte` idéntico (todos los campos, céntimos exactos) |
| `test_fiscal_instantanea_inmutable` | No se puede modificar ni borrar; el hash coincide con el contenido; una nueva **sustituye**, no pisa |
| `test_fiscal_declaracion_reproducible` | Recalcular desde la instantánea da las mismas casillas, byte a byte el mismo `.303` |
| `test_fiscal_estados` | `borrador → revisada → exportada → presentada`; no se salta pasos ni se retrocede; lo presentado no se altera |
| `test_fiscal_sin_aprobacion_no_calcula` | Un apunte sin aprobador no entra en ninguna instantánea; la IA/API nunca aprueba |
| `test_migracion_003` | Idempotente, en `bd_esquema_version`, esquema = el de SQLite salvo lo del despacho |
| `test_citus_fiscal_nucleo` | Tablas distribuidas y colocalizadas; claves primarias con `tenant_id`; concurrencia sin interbloqueos |

## 6. Lo que necesito de ti

1. **Tu «sí» a este esquema** (o los cambios que quieras). Sin él no escribo código de persistencia.
2. **Quién aprueba apuntes e instantáneas:** propongo `revisor_fiscal` o dirección del despacho (decisión F-D3 del plan); la IA, nunca.
3. **Si los importes de las casillas van en céntimos enteros** (como hasta ahora) — lo asumo.
