# Plan de encaje: módulo «Guilda Fiscal» y «Guilda Fiscal Alquileres» en Guilda Work

> **Estado:** propuesta para tu aprobación · **Fecha:** 2026-10-24 · **Base:** `main` en `dcfade4`, PostgreSQL + Citus en producción, API 1.4.
> **Origen:** `GUILDA_WORK_MODULO_FISCAL.md` y `LEEME.md` (evaluación y especificación del 24-oct-2026).
> **Qué es este documento:** el análisis de huecos contra el código real y el plan de incorporación por hitos. **No se ha escrito código ni se ha tocado ningún dato.** Empiezo cuando lo apruebes y, aun entonces, **hito a hito**, con tu visto bueno en los puntos marcados 🔒.
> **Qué no tengo todavía:** el paquete de fuentes oficiales (los 53 ficheros, `FUENTES.md`, `manifest.json`, `fuentes/`) **no está entre los ficheros que me has pasado**: solo llegaron los dos `.md`. Es imprescindible para el hito 0 (ver §10).

> **Estado de ejecución (24-oct-2026, noche):** plan aprobado («hazlo, sobre todo con el PostgreSQL»).
> ✅ **Cimiento de PostgreSQL hecho** (sin esquema): sacadas de la ruta caliente las escrituras en tablas de referencia que provocaban `distributed deadlock` (+ prueba de concurrencia sobre Citus real) y ventana de seguridad del cursor de `/sync`; detalle y cifras en `plan-ux-ui-app-y-postgresql.md` §D. Esto desbloquea el volumen de lotes del módulo.
> ✅ **F1 preparado en papel:** [`fiscal-f1-esquema-propuesto.md`](fiscal-f1-esquema-propuesto.md) (SQL de SQLite y de PostgreSQL/Citus, RLS, restricción de vigencias, pruebas); **no aplicado** (espera al 26-oct 12:34 y a tu visto bueno 🔒).
> ⏸ **F0 detenido en un permiso:** localizado el diseño oficial del 303 — `DR303e26v101.xlsx` (xlsx, 378 KB, «ejercicio 2026 y siguientes», actualizado 28/01/2026) en `https://sede.agenciatributaria.gob.es/static_files/Sede/Disenyo_registro/DR_300_399/archivos_26/DR303e26v101.xlsx` — pero **no lo he descargado**: necesito tu «sí» a ese fichero (y a las instrucciones del periodo) o que me pases el paquete de fuentes.

> ✅ **Vía de entrada a la AEAT investigada** (`fiscal-vias-aeat.md`): el 303 de 2026 se sube con **«Importar» en el formulario web (Pre303)** con el diseño `DR303e26v101`; la presentación por fichero «clásica» es solo de 2022 y anteriores; existe además la **importación de libros LSI (XLSX)**, que usaremos como **segunda salida y oráculo de comprobación** (hito nuevo F5b). Pruebas en el Portal de Pruebas Externas (simulador OPEN) por una persona con certificado.

---

## 0. Resumen en una página

**La buena noticia: más de la mitad de la parte «documental» ya existe en Guilda Work.** La especificación se escribió sin ver el repositorio (lo dice ella misma, §1) y propone construir un portal de documentos, extracción por IA, revisión, registro de facturas y cierre por trimestre que **ya están hechos** en el módulo «Facturas para contabilizar» (19–20 oct). Lo que **no existe** y es el corazón del valor nuevo es: (1) la **jerarquía fiscal** (empresa gestora → titulares → inmuebles con titularidad y vigencia → reservas), (2) el **registro fiscal** con cuota deducible y trazabilidad, (3) el **motor del modelo 303** con casillas trazables, (4) el **exportador `.303`** validado contra el diseño oficial, (5) la **matriz de cobertura** por modelo/ejercicio/perfil y (6) el **panel de cartera** por NIF y trimestre sobre las obligaciones.

**Cómo encaja (la decisión central).**

| Pieza de la especificación | En Guilda Work | Acción |
|---|---|---|
| Titular fiscal / `taxpayer_entities` | `clientes_fiscales` (NIF, duplicados por NIF, oficinas, responsable, concesiones) | **Reutilizar**; añadir perfil fiscal versionado |
| Portal de subida, estados, factura original inmutable | `almacen_documentos` (hash SHA-256, cifrado por despacho, antivirus) + `facturas_contables` (+ portal del cliente) | **Reutilizar y ampliar** (lotes, duplicados, multi-factura) |
| Extracción por IA | `lectura_facturas.py` (JSON fijo, validado, siempre «pendiente») | **Ampliar** (evidencia por campo, versiones, cascada XML→texto→OCR) |
| Facturas y líneas fiscales | `facturas_contables` + `facturas_contables_lineas` (céntimos enteros, IVA por línea, rectificativas, criterio de caja) | **Reutilizar como único almacén de facturas**; **no** crear otra tabla `invoices` |
| Registro fiscal aprobado | no existe | **Nuevo**: `fiscal_apuntes` (cuota deducible, periodo, causa, aprobador) |
| Cierre por periodo | `contabilidad_cierres` (por trimestre) | **Ampliar** (instantáneas inmutables) |
| Declaración 303 + casillas | no existe (solo se «propone» el modelo en `perfil_fiscal`) | **Nuevo**: motor determinista, `fiscal_declaraciones`, `fiscal_casillas` |
| Obligación 303, fases, justificante, constancia, avisos | `vencimientos_fiscales` + flujo de obligaciones + justificante + constancia + panel fiscal | **Reutilizar**: la declaración 303 **cuelga de la obligación** |
| Salida A3 (`suEnlace.dat`) | `enlace_a3.py` (formato oficial de 512 bytes, rectificativas, pre-chequeo) | **Se conserva intacto**, como adaptador paralelo |
| Base normativa consultable con citas | Módulo jurídico: `jur_fuentes`, `jur_versiones`, `jur_fragmentos`, conector del BOE, citas verificadas | **Reutilizar**: nueva colección «Fiscal» |
| Reglas versionadas con aprobación | `reglas_fiscales` / `reglas_laborales` (versiones, aprobación por el propietario desde el backoffice) | **Reutilizar el patrón** para las reglas de IVA y los diseños |
| Rol del asesor que aprueba | rol `revisor_fiscal` (alcance de organización) | **Reutilizar** como aprobador de instantáneas |
| Cobro: base + titulares + documentos | extras/planes + `cobro_contabilidad` (tarifas por unidad, liquidación mensual) | **Ampliar** (nuevas unidades) |
| Inmuebles, propietarios, reservas, liquidaciones | Vertical «Inmobiliaria» = operaciones de **compraventa/alquiler de una agencia** (no propiedades gestionadas en alquiler vacacional) | **Nuevo** vertical «Alquileres» (otro dominio) |

**Propuesta de empaquetado:** **dos extras de pago**, igual que «Contabilización» es un extra de la Gestoría:
1. **Guilda Fiscal** (motor y modelos: 303 primero; libros después). Depende de Gestoría + Contabilización.
2. **Guilda Fiscal Alquileres** (inmuebles, titularidades, contratos de gestión, reservas, liquidaciones, tratamientos de alquiler). Depende de Guilda Fiscal.

**Esfuerzo:** **315–490 horas** frente a las 185–330 de la especificación. Mi cifra incluye ≈ 100–145 h de requisitos de plataforma que la especificación no podía conocer (cuatro idiomas, dos motores de base de datos, RLS/Citus, paridad API/MCP/IA, móvil, backoffice, accesibilidad); la reutilización de lo ya construido (portal, lectura con IA, facturas, cierre, A3, obligaciones, jurídico, cobro) evita rehacer el resto. Detalle en §8.

**Cinco decisiones que necesito de ti antes de empezar** (§11): dos extras o uno · una sola tabla de facturas (la existente) · quién aprueba reglas y instantáneas · proveedor de IA y condiciones de datos · permiso para descargar las fuentes oficiales o que me pases el paquete completo.

---

## 1. Qué hay ya, mirado de cerca

### 1.1 «Facturas para contabilizar» (`app/facturas_contables.py`, 1.436 líneas) — la base documental

- **Facturas** emitidas/recibidas por cliente fiscal; **importes en céntimos enteros** y porcentajes en centésimas (la aritmética decimal exacta que pide la especificación ya es la norma de la casa); hasta 8 líneas por factura, cada una con base, % IVA, cuota, recargo, retención, tipo de operación (`01`…`09`: interior, exenta, intracomunitaria, inversión del sujeto pasivo, no deducible…), `sujeta_iva`.
- **Estados** `pendiente → revisada → exportada | descartada`; `problemas()` impide revisar con cuota que no cuadra (tolerancia 2 céntimos), total que no cuadra, NIF ausente, abono sin factura rectificada…
- **Régimen de IVA por cliente** (`general`, `recargo`, `exento`), criterio de caja por factura, **reglas por proveedor/cliente** (aprendidas), **cierre y reapertura de trimestre**, plan de cuentas importado de a3, subcuentas automáticas.
- **Entrada**: despacho (a mano, foto o PDF), **portal del cliente** (con antivirus ClamAV), lectura con IA (`lectura_facturas.py`: el modelo del propio usuario vía OpenRouter, JSON fijo, cada valor validado «como si lo hubiera escrito una persona», siempre queda pendiente y marcada «leída por IA»).
- **Salida**: `enlace_a3.py` genera el `SUENLACE.DAT` oficial (registros de 512 bytes, versión 9.80, rectificativas) con pre-chequeo y lotes descargables.
- **Cobro por uso** (`cobro_contabilidad.py`): tarifas por plan/despacho, medición mensual, límite duro, liquidación.
- Ya publicado por **API REST, MCP e IA** y con ayuda contextual.

### 1.2 Control fiscal (`vencimientos_fiscales`, obligaciones, panel fiscal)

`vencimientos_fiscales` (modelo + periodo + cliente + fecha límite), **flujo de fases** de la obligación (preparación → revisión → aprobación → presentada, con `flujo_estricto` y «exigir justificante»), **justificante** y **constancia de presentación** en PDF, **avisos con acuse**, **panel** («qué mirar hoy»), **perfil fiscal** que propone modelos (`perfil_fiscal.py`, «sin validar»), **catálogo global de reglas fiscales** con versiones y aprobación del propietario (`reglas_fiscales.py`).

### 1.3 Lo que **no** existe

| Hueco | Evidencia |
|---|---|
| Cualquier cálculo del 303 o de otro modelo | `grep` de «303» solo encuentra textos de ayuda, el catálogo de fechas y la sugerencia de modelos; no hay casillas ni ficheros |
| Extracción con **evidencia por campo** (página/zona/texto original) y **versiones** de extracción | `lectura_facturas.py` devuelve un único JSON sin trazas |
| Detección de **duplicados** de factura (mismo emisor + número + fecha) | `problemas()` no la tiene; solo `almacen_documentos` evita el mismo archivo por hash |
| Registro fiscal con **cuota deducible ≠ cuota soportada**, periodo de deducción, causa y aprobador | no hay tabla |
| **Instantáneas inmutables** de periodo | `contabilidad_cierres` solo marca el trimestre cerrado |
| **Perfil fiscal versionado** del titular (forma jurídica, residencia, periodicidad, prorrata, REDEME/SII, criterio de caja, saldos a compensar) | existe `perfil_fiscal` (tipo + 4 atributos, sin vigencias) y `contabilidad_clientes.regimen_iva` |
| Inmuebles con **titulares, porcentajes y vigencias**, contratos de gestión, reservas, liquidaciones a propietarios | el vertical Inmobiliaria modela **operaciones de una agencia**, no activos gestionados |
| Matriz de **cobertura** por modelo/ejercicio/perfil | — |
| Duplicados de despacho/«taxpayer» por **gestora** (grupo) | `clientes_fiscales` no tiene relación entre clientes |

### 1.4 Restricciones técnicas de la plataforma que condicionan el diseño

1. **Dos motores.** SQLite sigue siendo el motor de las pruebas y el reverso hasta que se retire (decisión no antes del 7-nov). Todo módulo define su esquema en SQLite (`esquema(conn)` del vertical) **y** necesita su **migración numerada de PostgreSQL** (`app/bd/migraciones/NNN_x[.mt|.citus].sql`; hoy **no hay ninguna** aplicada). **No se pueden aplicar migraciones antes del 26-oct 12:34** (vuelta atrás B).
2. **Multitenant con RLS + Citus.** Toda tabla nueva de un despacho lleva `tenant_id`, clave primaria `(tenant_id, id)`, política RLS `aislamiento` y distribución por `tenant_id` (`colocate_with => 'abogados_ajustes'`). Los catálogos globales (reglas, diseños) son **tablas de referencia**, y **nunca se escribe en una tabla de referencia en la ruta caliente** (hallazgo de hoy: provoca *distributed deadlocks*; ver `plan-ux-ui-app-y-postgresql.md` §D).
3. **Paridad web / API / MCP / IA** y **cuatro idiomas** (es/ca/en/fr) en todo lo que se enseña.
4. **Cifrado por despacho**: un trabajo asíncrono que lea documentos cifrados necesita la **concesión de servicio** del despacho; sin ella, la extracción se queda «bloqueada», no falla en silencio.
5. **Reglas fiscales las valida Jorge** (decisión registrada en el control fiscal): el catálogo global se aprueba en el backoffice con versión y auditoría. Este módulo sigue ese mismo criterio.

---

## 2. Dónde ajusto o discrepo de la especificación (para que lo sepas)

| # | Punto | Mi propuesta | Motivo |
|---|---|---|---|
| 1 | Tablas `invoices`, `invoice_tax_lines`, `documents`, `document_versions`, `users`, `tenants` en inglés | **No duplicar**: se usan `facturas_contables(+_lineas)`, `documentos`, `usuarios`, `tenants`; las nuevas llevan prefijos `fiscal_` y `alq_` en castellano | Evitar dos fuentes de verdad y mantener el contrato A3 |
| 2 | «Despacho/suscriptor → empresa gestora → titulares» | El **despacho** es el `tenant`; la **gestora** y los **titulares** son `clientes_fiscales`, unidos por una relación explícita (`fiscal_relaciones`) | Es lo que ya hace RLS y permisos |
| 3 | Tipos de aprobador | Rol existente **`revisor_fiscal`** (más dirección) | Ya está en el control de acceso |
| 4 | Estimación 185–330 h | **315–490 h** | Requisitos de plataforma (§8) |
| 5 | `POST /documents/upload-intents`, `/tax-returns/...` (API orientativa) | Rutas `/api/v1/fiscal/…` y `/api/v1/alquileres/…`, con áreas de token propias y esquemas en el OpenAPI | Convención de la casa |
| 6 | «Presentación directa» | **Fuera de alcance**, como dice la especificación; solo fichero + validación + registro del justificante | Coincido |
| 7 | La IA «no activa reglas nuevas» | Además, la **IA no puede aprobar, exportar ni cerrar**: solo preparar borradores (las herramientas de IA/MCP que escriben piden confirmación humana) | Coherente con el resto de la plataforma |

---

## 3. Arquitectura propuesta

```
Documento (portal / despacho / móvil)  ─▶ almacen_documentos (hash, cifrado, antivirus)
        │
        ▼  cola de trabajos (idempotente, por despacho, con concesión de servicio)
 Extracción v2  ─▶ fiscal_extracciones + fiscal_campos (valor, texto original, página, zona, estado)
        │                     ▲ cascada: XML estructurado → texto nativo del PDF → OCR/visión
        ▼
 Revisión (pantalla dividida) ─▶ facturas_contables (+líneas)  ← única factura de la casa
        │                                   │
        │                                   └──▶ enlace_a3 (SUENLACE.DAT)  [intacto]
        ▼
 Registro fiscal  ─▶ fiscal_apuntes (cuota deducible, causa, periodo, aprobador) + fiscal_ajustes
        │
        ▼  cierre
 Instantánea inmutable (fiscal_instantaneas) ─▶ Motor de modelos (app/fiscal_modelos/)
                                                    ├─ m303: casillas + trazas (reglas versionadas)
                                                    └─ exportador .303 (diseño oficial versionado)
        │
        ▼
 fiscal_declaraciones (cuelga de vencimientos_fiscales: 303/ejercicio/periodo)
   estados: borrador → calculado → aprobado → exportado → importación verificada → presentado | rechazado | rectificado
        │
        ▼
 Obligación (fases, justificante, constancia, avisos, panel)  [reutilizado]
```

**Código** (convención de módulos de negocio, `verticales.registrar(...)`):

```
app/fiscal_modelos/            # Guilda Fiscal (núcleo del motor, sin Flask ni base de datos en el cálculo)
    __init__.py                #   registro del vertical «fiscal» + matriz de cobertura
    base.py                    #   contrato del adaptador: supports / validate / calculate / serialize / validate_local / evidence
    decimal.py                 #   aritmética en céntimos y redondeos oficiales (a confirmar con las instrucciones)
    m303.py                    #   reglas de las casillas (por ejercicio/periodo/revisión)
    disenos/303_2026_rev*.json #   diseño oficial extraído del fichero descargado (nunca escrito de memoria)
    exportadores/aeat_303.py   #   serialización del fichero importable
    libros/                    #   libros IVA/IRPF (fase posterior)
app/fiscal_registro.py         # apuntes, ajustes, instantáneas, cierre (usa facturas_contables)
app/fiscal_extraccion.py       # extracción v2 y revisión (amplía lectura_facturas.py)
app/fiscal_perfiles.py         # perfil fiscal versionado del titular + relaciones gestora↔titular
app/alquileres.py              # vertical «Guilda Fiscal Alquileres»: inmuebles, titularidades, contratos, reservas, liquidaciones
app/rutas_fiscal_modelos.py    # pantallas web
app/rutas_api_fiscal_modelos.py# REST (área de token «fiscal_modelos»)
mcp_tools/herramientas_fiscal_modelos.py
```

El **cálculo es puro** (funciones sin base de datos): se prueba con tablas de casos y se reproduce sin red ni IA, como exige la especificación.

---

## 4. Modelo de datos

Convenciones: SQLite en `esquema(conn)` de cada módulo + migración PostgreSQL numerada; **todas distribuidas por `tenant_id`** salvo las marcadas «ref»; importes en céntimos enteros; fechas ISO; `version` entero para control optimista; borrado lógico con `papelera_en` cuando proceda.

### 4.1 Guilda Fiscal (núcleo)

| Tabla | Para qué | Claves y notas |
|---|---|---|
| `fiscal_perfiles` | Perfil fiscal **versionado** del titular: forma jurídica, residencia, régimen de IVA, periodicidad, actividades, SII/REDEME, criterio de caja, prorrata, opciones y saldos a compensar | `(tenant_id, id)`; `cliente_fiscal_id`, `vigente_desde`, `vigente_hasta`; sustituye en la práctica a `perfil_fiscal` + `contabilidad_clientes.regimen_iva` (que se siguen leyendo) |
| `fiscal_relaciones` | Gestora ↔ titulares (y otras agrupaciones) | `desde_cliente_id`, `hasta_cliente_id`, `tipo`, vigencia. **Nunca fusiona titulares** |
| `fiscal_extracciones` | Cada pasada de extracción de un documento | `documento_id`, `factura_id?`, `version`, `metodo` (xml/texto/ocr/visión), `modelo_ia`, `estado`, `coste`, `error` |
| `fiscal_campos` | Campo extraído con evidencia | `extraccion_id`, `campo`, `valor`, `texto_original`, `pagina`, `zona`, `estado` (leído/revisado/rechazado), `revisado_por`. La revisión humana **nunca se borra** al reextraer |
| `fiscal_duplicados` | Pares de facturas sospechosas | emisor + número + fecha, o importe+fecha; resuelto por persona |
| `fiscal_apuntes` | **Registro fiscal aprobado** (uno por grupo fiscal de una factura) | `factura_id`, `linea_id`, `tipo_operacion`, `base`, `cuota_soportada`, `cuota_deducible`, `pct_deducible`, `causa`, `periodo_deduccion`, `aprobado_por`, `aprobado_en`, `version` |
| `fiscal_ajustes` | Ajustes manuales con motivo (regularizaciones, prorrata, bienes de inversión…) | aprobador obligatorio |
| `fiscal_instantaneas` | **Instantánea inmutable** del periodo de un titular | `cliente_fiscal_id`, `modelo`, `ejercicio`, `periodo`, `hash`, `aprobada_por`, `contenido` (JSON congelado: perfil, apuntes, ajustes, versión de reglas) |
| `fiscal_declaraciones` | La declaración (303…) de un titular y periodo | `vencimiento_id` (la obligación), `instantanea_id`, `estado`, `version_reglas`, `version_diseno`, `rectifica_a?` |
| `fiscal_casillas` | Valor de cada casilla | `declaracion_id`, `casilla`, `valor`, `regla`, `explicacion` |
| `fiscal_casilla_fuentes` | Trazabilidad: qué apuntes alimentan la casilla | `casilla_id`, `apunte_id/ajuste_id`, `importe` |
| `fiscal_artefactos` | Ficheros generados (fichero `.303`, resumen legible, libros) | `declaracion_id`, `tipo`, `hash`, `contenido` (cifrable), `diseno_version`, `informe_validacion` |
| `fiscal_justificantes` | Justificante/CSV/resultado de la presentación | enlaza con `vencimientos_fiscales_documentos` (ya existe); solo guarda los datos estructurados |
| `fiscal_eventos` | Auditoría específica (lectura/cambio/exportación) | además de `auditoria.registrar` general |
| `fiscal_reglas` **(ref)** | Reglas de cálculo versionadas (por modelo, ejercicio, periodo, revisión) con estado «borrador / aprobada» | patrón de `reglas_fiscales`; **aprobación solo del propietario en el backoffice**; escritura rara |
| `fiscal_disenos` **(ref)** | Metadatos de los diseños oficiales (URL, hash, fecha de descarga, vigencia, revisión) | el contenido del diseño va **en el repositorio** (`disenos/*.json`), no en la base |
| `fiscal_cobertura` **(ref)** | Matriz «modelo × ejercicio × perfil»: soportado / bloqueado / en pruebas, fuente, última prueba | alimenta la pantalla de cobertura |

### 4.2 Guilda Fiscal Alquileres

| Tabla | Para qué |
|---|---|
| `alq_inmuebles` | Inmueble: dirección, referencia catastral, ubicación/territorio (bloquea tratamientos fuera del territorio IVA), tipo de explotación |
| `alq_titularidades` | `inmueble_id`, `cliente_fiscal_id`, porcentaje, `vigente_desde/hasta` (versionada; la suma debe ser 100 % en cada fecha) |
| `alq_contratos_gestion` | Contrato entre la gestora y el titular: **modalidad** (intermediación en nombre del propietario / explotación en nombre propio / arrendamiento-subarrendamiento), comisión, vigencia, documento firmado |
| `alq_reservas` | Reserva: inmueble, plataforma, fechas, importes brutos, comisión de plataforma, servicios durante la estancia, estado de cobro |
| `alq_liquidaciones` | Liquidación al propietario: reservas incluidas, comisión de gestión (con IVA), gastos repercutidos, neto transferido; **enlaza** (no sustituye) a las facturas |
| `alq_tratamientos` | Tratamiento fiscal propuesto por inmueble/contrato (exento, 10 %, general…, con la regla y la fuente) **aprobado por una persona** |

**Reglas de integridad** que valen como pruebas: la factura emitida a un propietario **no** se reparte entre cotitulares automáticamente; un importe nunca se suma entre obligados tributarios; la asignación a un inmueble es **analítica**, la unidad de declaración es el titular fiscal.

---

## 5. El motor 303: cómo lo construyo sin inventar nada

1. **Fuente única de verdad: los ficheros oficiales.** Antes de escribir una línea del exportador leo el **diseño de registro oficial del 303 (ejercicio 2026 y siguientes, actualizado 28/01/2026)** y las instrucciones (01/1T y 02–12/2T–4T) del paquete. Un script (`scripts/fiscal/extraer_diseno.py`) **genera** `disenos/303_2026_rev*.json` a partir del fichero descargado; el repositorio guarda el hash del original. **No escribo posiciones, longitudes ni códigos de memoria.**
2. **Clave de versión** = modelo + ejercicio + periodo + revisión del diseño/instrucciones (como pide la especificación). El motor **se niega** a calcular con una combinación no registrada.
3. **Contrato del adaptador** (el de la especificación): `supports → validate_inputs → calculate → serialize → validate_local → export_evidence`. Se implementa como clase por modelo.
4. **Aritmética**: céntimos enteros y centésimas de punto; redondeo documentado por casilla según las instrucciones (lo confirmo en F0, no lo supongo).
5. **Cada casilla** guarda valor, regla versionada, registros que la alimentan, ajustes y explicación (`fiscal_casillas` + `fiscal_casilla_fuentes`); recalcular reproduce el mismo resultado sin IA.
6. **Datos que no salen de las facturas** (periodicidad, régimen, prorrata, saldos a compensar, REDEME/SII, modalidad de resultado) vienen de `fiscal_perfiles` y se **piden** si faltan; **IBAN/NRC nunca se infieren**.
7. **Primer subconjunto soportado, explícito en la matriz de cobertura**: régimen general, operaciones interiores ordinarias en territorio IVA, datos completos. Todo lo demás (prorrata, criterio de caja, intracomunitarias, régimen simplificado, territorios especiales, titular no residente) **bloquea la exportación** con el motivo y la vía de revisión especializada; **jamás se ignoran datos para forzar un resultado**.
8. **Exportar ≠ presentar.** Estados separados; una instantánea aprobada es inmutable; modificar una factura aprobada crea versión y exige nuevo cierre; una declaración presentada no se altera: se abre expediente de rectificación.
9. **Validación**: pruebas de bytes y posiciones, comparación con ficheros exportados por el formulario oficial, carga en el simulador/formulario 303 **por Jorge** (sin firmar ni enviar), y evidencia de importación guardada. *Un fichero bien formado no acredita aceptación AEAT* y no se anuncia compatibilidad antes de esa prueba.

---

## 6. Pantallas y experiencia

| Pantalla | Dónde vive | Notas |
|---|---|---|
| **Cartera fiscal** (por titular y trimestre: documentación pendiente, incidencias, resultado provisional, responsable) | Menú Fiscal (extiende el panel fiscal) | Prioriza **excepciones**, no listas interminables; filtros por gestora, titular, inmueble, estado; acciones en lote seguras |
| **Documentación** (subida individual y por lotes, arrastrar/cámara, estados) | Contabilización (ya existe) + portal del cliente | Estados nuevos: *en extracción, duplicado, no fiscal, pendiente de aclaración*; varias facturas en un PDF |
| **Revisión dividida** (documento a un lado, datos con evidencia resaltada al otro) | Se amplía `contabilidad_factura` | «Dato leído» / «clasificación propuesta» / «decisión aprobada» separados; nunca «aceptar todo» con incidencias críticas |
| **Titular · pestaña Fiscal** | Ficha única del cliente | Perfil versionado, inmuebles, titularidades, historial de declaraciones |
| **Declaración 303** | Cuelga de la obligación | Casillas con **trazas al clic**, bloqueos, aprobar, exportar, subir justificante; estados visibles |
| **Matriz de cobertura** | Fiscal → Cobertura (y backoffice) | Honesta: qué se soporta, qué no, cuándo se probó |
| **Inmuebles, titularidades, reservas, liquidaciones** | Menú Alquileres | Importación por CSV/Excel de reservas (reutiliza el importador de cartera) |
| **Reglas e importación de diseños** | **Backoffice** (solo propietario) | Versiones, aprobación, auditoría |
| **Móvil** | Plan principal Ola 4.1 | Captura con cámara + revisión + estado de cartera; **aprobar y exportar solo en web** al principio |

Accesibilidad, 4 idiomas, glosario (usar «obligación» y «titular»), estados vacío/error/offline y guiones de prueba de uso se aplican como en `plan-ux-ui-app-y-postgresql.md`.

---

## 7. API, MCP, IA, backoffice, seguridad

- **API REST** (área de token `fiscal_modelos`, añadida a `api_areas.py`; `alquileres` aparte): lectura de perfiles, cartera, extracciones, apuntes, declaraciones, casillas y fuentes; escritura de borradores, revisiones, aprobación (rol), exportación y justificantes; **idempotencia** en subidas/extracciones/exportaciones y **`version`** en ediciones (`409/412 version_obsoleta`). Esquemas con nombre en el OpenAPI y un caso de contrato por GET.
- **MCP/IA**: herramientas de **lectura** (cartera, preparación, casillas con fuentes, cobertura) y de **borrador** (lanzar extracción, proponer clasificación, preparar un 303) **con confirmación humana**; **ninguna** herramienta aprueba, cierra ni exporta. Un adjunto es **entrada no confiable**: sus instrucciones no cambian permisos ni llaman a herramientas (ya es la regla de `lectura_facturas.py`).
- **Backoffice** (`backoffice/`): alta de los dos extras (`extras_guilda.vertical_id`), reglas y diseños (versiones y aprobación del propietario), cobertura, uso por despacho (`uso` del vertical), liquidación por uso con nuevas unidades (`titulares_activos`, `documentos_extraidos`, `declaraciones_exportadas`).
- **Permisos**: `gestor` prepara; **`revisor_fiscal` y dirección aprueban**; `auditor` solo lee; alcance por oficina/cliente como en el resto del control fiscal; el cliente solo ve **sus** documentos en el portal.
- **Privacidad y cifrado**: documentos por `almacen_documentos` (cifrado por despacho, URLs temporales, antivirus); **la extracción asíncrona exige la concesión de servicio del despacho** (si no está, estado «bloqueada», nunca error mudo); datos anonimizados para desarrollo; **proveedor de IA con contrato de encargado** y condiciones de conservación/entrenamiento revisadas (hoy `lectura_facturas.py` usa el modelo y la clave del propio usuario en OpenRouter: **hay que decidir** si el módulo fiscal lo mantiene, usa una cuenta de la plataforma o un modelo local, §11).
- **Retención**: política definida con Jorge y asesoría; **no se borra nada automáticamente a los 4 años**.
- **PostgreSQL**: tablas por despacho distribuidas; catálogos como referencia **sin escrituras en la ruta caliente**; consultas con presupuesto de sentencias y paginación por cursor; trabajos de extracción y cierre en lotes idempotentes con contexto de despacho explícito (prueba de «trabajo con contexto erróneo» de la especificación).

---

## 8. Hitos, esfuerzo y criterios de aceptación

Esfuerzo orientativo en **horas de trabajo** (incluye pruebas, i18n, ayuda y paridad). Cada hito termina con una **versión usable**, sus pruebas en los dos motores, la actualización de `docs/` y **tu aprobación** antes de pasar al siguiente. 🔒 = pido tu visto bueno explícito antes (esquema, datos reales, IA externa, coste).

| Hito | Contenido | Horas | Aceptación |
|---|---|---:|---|
| **F0 · Cimientos y fuentes** (sin esquema) | Recibir/descargar las fuentes oficiales 🔒; **leer** el diseño 303 y las instrucciones del periodo; matriz de cobertura inicial; **10 muestras** de factura/liquidación y **10 casos de referencia** contigo; decisiones de §11; ADR corto; `scripts/fiscal/extraer_diseno.py` (genera el JSON del diseño) | 20–30 | Diseño 303 2026 extraído con hash y **test de ida y vuelta**; lista de casos de referencia firmada por ti |
| **F1 · Jerarquía y perfiles** 🔒 esquema | `fiscal_perfiles`, `fiscal_relaciones`; extensión de la ficha de cliente («Fiscal»); vertical «fiscal» registrado y extra en backoffice; **primera migración numerada real** | 35–55 | Gestora con titulares; perfiles con vigencia; aislamiento entre despachos y titulares probado en los dos motores |
| **F2 · Documentación y extracción v2** | Lotes, duplicados, multi-factura, estados nuevos, `fiscal_extracciones/campos` con **evidencia**, cascada XML→texto→OCR, validaciones (NIF, descuadre, receptor no coincidente), revisión dividida | 50–80 | Corpus de 100–200 documentos anonimizados medido **por campo** y **tiempo humano**; ninguna extracción se aprueba sola |
| **F3 · Registro fiscal y reglas** | `fiscal_apuntes/ajustes`, deducibilidad con causa, rectificativas, `fiscal_reglas` versionadas con aprobación en backoffice, clasificación explicable de alquiler (exento / 10 % / gestión / mixto → **bloquear** lo no soportado) | 45–70 | Casos de alquiler del §3 de la especificación reproducidos; «cuota soportada ≠ deducible» probado |
| **F4 · Motor 303 (cálculo)** | Instantáneas inmutables, `fiscal_declaraciones/casillas/fuentes`, `readiness`, matriz de soporte, trazas | 40–60 | Los **10 casos de referencia** coinciden casilla a casilla; recalcular da lo mismo; combinaciones no soportadas bloquean |
| **F5 · Exportador `.303` y validación** | Serializador según el diseño oficial, validación local, evidencia de importación | 30–50 | Pruebas de bytes; **importación correcta en el formulario oficial por ti** (sin firmar ni enviar); informe guardado |
| **F6 · Cartera y flujo de presentación** | Panel por titular/trimestre, integración con obligaciones 303 (fases, justificante, constancia, avisos), estados completos, rectificación | 30–45 | Un trimestre completo de 5 titulares de principio a fin dentro de la plataforma |
| **F7 · Base normativa consultable** | Colección «Fiscal» en el módulo jurídico (conector BOE + diseños/instrucciones AEAT), citas a artículo/página, ayuda en la revisión | 25–40 | Consultas con cita verificable; conflicto o falta de evidencia → pide revisión |
| **F8 · Alquileres, paridad, móvil, cobro y piloto** | Vertical Alquileres (F1 de datos ya hecha por hito), reservas/liquidaciones, API/MCP/IA, móvil (captura y revisión), cobro por uso, documentación, **piloto 5 → 20 → 150 titulares** | 40–60 | Piloto con diferencias frente a la elaboración habitual/A3 explicadas y resueltas |
| **Total** | | **315–490** | |

**Por qué más que la especificación (185–330 h)** — suma de ≈ 100–145 h: cuatro idiomas y ayuda (≈ 25–35 h), esquema en SQLite **y** PostgreSQL/Citus con RLS y migraciones numeradas (≈ 25–35 h), paridad API/MCP/IA y área de token (≈ 20–30 h), móvil (≈ 10–15 h), backoffice y cobro (≈ 10–15 h) y pruebas de accesibilidad/aislamiento/contrato (≈ 10–15 h). La reutilización de lo existente (portal, lectura IA, facturas, cierre, A3, obligaciones, jurídico, cobro) **ya está descontada** en las horas de cada hito; sin ella, F2, F6 y F7 costarían bastante más.

**Orden recomendado respecto al resto del trabajo pendiente:** primero el arreglo urgente de la API (`PG-00/PG-04/PG-01`, ≈ 1 día), porque este módulo añade carga de lotes y de trabajos en segundo plano; **F0 puede empezar ya** (no toca esquema ni producción); F1 en cuanto se cierre la ventana de vuelta atrás (26-oct 12:34) y haya tu aprobación del esquema.

---

## 9. Pruebas que habilitan la venta

Las del §10 de la especificación, más las de la casa:

- **Aislamiento** por despacho (RLS) y por titular: dos titulares con el mismo número de factura; el mismo archivo dos veces; usuario sin permiso; **trabajo asíncrono con contexto erróneo**; cuota de IA por despacho.
- **Cálculo**: tablas de casos de referencia con fechas y versiones de reglas; cuota soportada ≠ deducible; saldos anteriores; rectificativas; fuera de alcance → bloqueo.
- **Fichero**: bytes/posiciones por versión de diseño; comparación con exportaciones oficiales; importación en el formulario oficial (manual, tuya) con evidencia.
- **Contrato OpenAPI** y compatibilidad hacia atrás; **paridad web/API/MCP/IA**; **i18n** (4 idiomas); **accesibilidad** (axe en las pantallas nuevas); **dos motores** de base de datos; **concurrencia** de la API; guardia de sentencias por endpoint.
- **IA**: corpus anonimizado de 100–200 documentos, exactitud por campo, inyección de instrucciones en adjuntos, nunca autoaprobación.
- **Piloto**: 5 titulares y un periodo completo → 20 → 150, comparando con la elaboración habitual.

---

## 10. Qué necesito para empezar (F0)

1. 🔒 **El paquete de fuentes oficiales**, o **permiso para descargarlo** desde los dominios oficiales (AEAT y BOE) con el `descargar_fuentes.py` de tu paquete (también me falta ese script). Solo para lectura; los originales van a una carpeta de referencia, **no** al repositorio de producción salvo los diseños que extraiga (con su hash).
2. **Diez muestras** representativas (anonimizadas): facturas de proveedores, fotos, una rectificativa, una liquidación de plataforma, un contrato de gestión.
3. **Diez casos de referencia** del 303 con resultado esperado (los tuyos, que son los que validan las reglas).
4. Confirmar **quién declara** en el caso de los 150 clientes: cuántos titulares tienen obligación de 303, cuántos son sociedades/comunidades, cuántos con varios inmuebles y si hay titulares no residentes.
5. Tus respuestas a las **decisiones** de §11.

---

## 11. Decisiones que necesito de ti

| # | Decisión | Mi recomendación |
|---|---|---|
| **F-D1** | **¿Dos extras (Guilda Fiscal + Guilda Fiscal Alquileres) o uno?** | Dos: el motor se puede vender a otras actividades sin alquileres |
| **F-D2** | **Facturas**: usar `facturas_contables` como único almacén (extendida con tablas hermanas `fiscal_*`) | Sí; evita duplicar y conserva A3, portal y cobro |
| **F-D3** | **Quién aprueba** reglas/diseños (propietario en backoffice) y **instantáneas** (`revisor_fiscal`/dirección de cada despacho) | Tal cual |
| **F-D4** | **IA de extracción**: (a) modelo del propio despacho vía OpenRouter como hoy, (b) cuenta de la plataforma con contrato de encargado, (c) modelo local | (b) para fiscal, con consumo medido por despacho; (a) como opción; revisar subencargados y conservación |
| **F-D5** | **Nombre comercial**: «Guilda Fiscal» y «Guilda Fiscal Alquileres» | Aceptar; mantener el ID interno `fiscal` y `alquileres` |
| **F-D6** | **Alcance de la primera versión**: 303 régimen general en territorio IVA, sin presentación directa ni emisión de facturas | Sí |
| **F-D7** | **Precio de partida a probar**: base + titular activo + documentos (la especificación sugiere 99 € + 1 €/titular, «a validar») | Dejarlo configurable en el backoffice; fijar tras medir coste real en el piloto |
| **F-D8** | **¿Se venderá a otras gestorías?** (si sí, reglas y diseños son globales y el aislamiento por despacho pasa a ser crítico desde el primer día) | Diseñarlo como si sí |
| **F-D9** | **Datos de piloto**: ¿puedo trabajar con documentos reales de tus clientes en un despacho de prueba, o solo con anonimizados? | Anonimizados para desarrollo; reales solo en el piloto, con tu autorización y cifrado activo |
| **F-D10** | **Orden**: arreglo urgente de API (1 día) → F0 → F1… | Sí |

---

## 12. Riesgos y qué no se hace

| Riesgo | Mitigación |
|---|---|
| Que un fichero bien formado se tome por aceptado por la AEAT | Estados separados «exportado» / «importación verificada» / «presentado»; textos que no prometen más; prueba manual documentada |
| Cambios de diseño o instrucciones a mitad de año | Clave de versión; vigilancia semanal (reutiliza la revisión periódica); el motor se niega a calcular con combinaciones no registradas |
| Clasificación errónea del alquiler (exento / 10 % / general) | El sistema **propone y explica**; decide una persona con el contrato; lo no soportado bloquea |
| Datos personales en prompts o registros | Anonimizar; IA solo con contrato; nada de contenido en registros; adjuntos como entrada no confiable |
| Carga de la API con lotes (150 titulares × 20 documentos/mes) | Trabajos en cola con ritmo; diferido de escrituras de uso (PG-04); medición con perfil de carga |
| Dependencia de un único asesor para validar | Registro de casos de referencia versionado y firmado; aprobación con auditoría |

**Fuera de alcance** (como en la especificación): presentación servidor a servidor, emisión de facturas/VERI*FACTU, custodia de certificados, modelos distintos del 303 y los libros (se añaden de uno en uno, cada uno con su adaptador y su cobertura), contabilidad general, y cualquier afirmación de cobertura que no esté en la matriz.

---

## 13. Qué haré en cuanto lo apruebes

1. **F0 inmediato**, sin tocar producción: pedirte los ficheros (o tu permiso para descargarlos), leer el diseño y las instrucciones del 303 y devolverte la **matriz de cobertura inicial**, la lista de campos reales del diseño y mis dudas sobre redondeos y casillas.
2. Con tus 10 casos de referencia, escribir las **pruebas antes que el motor**.
3. Proponerte el **esquema exacto de F1** (SQL de SQLite y migración PostgreSQL, clasificación de tablas, RLS) para tu visto bueno 🔒 antes de aplicar nada.
4. Entregar cada hito con: código, pruebas verdes en SQLite y PostgreSQL, documentación en `docs/`, y un informe corto de lo hecho, lo que queda y lo que no se soporta.
