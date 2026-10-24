# F0 · Informe: el diseño oficial del 303 leído (24-oct-2026)

> Hito F0 de `plan-modulo-fiscal-alquileres.md`. **Sin esquema ni producción.** Entregado: fuentes oficiales descargadas y verificadas, extractor reproducible, 183 casillas mapeadas a campos del fichero y la matriz de cobertura inicial. Lo que falta para cerrar F0 está en §6.

## 1. Qué se ha descargado (con tu permiso)

| Fichero | Tamaño | sha256 (16 primeros) | Origen |
|---|---:|---|---|
| `DR303e26v101.xlsx` — diseño de registro del 303, ejercicio 2026 y siguientes, **versión 1.01** (act. 28/01/2026) | 386.926 B | `0be8b156da2250c6` | `sede.agenciatributaria.gob.es/static_files/Sede/Disenyo_registro/DR_300_399/archivos_26/` |
| `303_instrucciones_2026.html` — instrucciones 2026 (01 y 1T) | 109.982 B | `e4e5204da9d05911` | `…/modelo-303-iva-autoliquidacion_/instrucciones-2026.html` |
| `303_ayuda_tecnica.html` — importar/validar/exportar en el formulario | 38.091 B | `1bb9e3e7e3e40c3d` | `…/presentacion-declaraciones-ayuda-tecnica/modelo-303.html` |
| `disenos_300_399.html` — página de diseños 300–399 (para vigilar revisiones) | 15.813 B | `7df7813fc7fea0d0` | `…/ayuda/disenos-registro/modelos-300-399.html` |
| `CALCULO_CASILLAS_IVA_PRE303-LSI.xlsx` — **especificación oficial de cómo se calculan las casillas a partir de los libros** (3 hojas: IVA devengado, deducible, información adicional; act. 01-01-2026) | 46.524 B | `700a42a33259eef8` | `…/Libros_registro/CALCULO_CASILLAS_IVA_PRE303-LSI.xlsx` |
| `LSI.xlsx` / `LSIJ.xlsx` — diseños de registro normalizados de los libros (personas físicas / personas jurídicas no SII; 01-01-2026) | 58.337 / 58.515 B | `d35e92f2ebcdfba9` / `963e653c2f2ffca8` | `sede…/static_files/AEAT/` |
| `Formato_Electronico_Comun_Libros_Registro_IVA_IRPF.pdf` — formato común (requerimientos, Renda WEB, Pre303, modelo 130) | 738.001 B | `071bdaabc3736e2e` | `…/Libros_registro/` |

Guardados en `docs/fuentes-oficiales/aeat/` con `manifest.json`. No se pudo obtener el PDF técnico de entidades desarrolladoras (`IVA303-CoordColabora_7.02.pdf`, el servidor no respondió): no hace falta para el diseño, pero **la codificación de caracteres y los saltos de línea del fichero no figuran en el xlsx ni en la ayuda técnica** (§5).

## 2. Cómo es el fichero `.303` (según el diseño oficial, no de memoria)

El fichero es una **envoltura** con páginas dentro. `DP30300` (envoltura): `<T3030` + ejercicio(4) + periodo(2: `01`…`12` o `1T`…`4T`) + `0000>` + bloque auxiliar `<AUX>…</AUX>` de 323 posiciones (versión del programa y NIF de la entidad desarrolladora; el resto, en blanco) + el contenido (páginas) + `</T3030EEEEPP0000>`. Nombre del fichero (ayuda técnica): **NIF del declarante + ejercicio + periodo + extensión `.303`**.

| Hoja / página | Campos | Posiciones | Qué lleva |
|---|---:|---:|---|
| `DP30300` envoltura | 15 | variable | Constantes, ejercicio, periodo, versión del programa, NIF de la entidad desarrolladora |
| `DP30301` **página 1** | 89 | 1.581 | **Identificación** (NIF, nombre; 17 indicadores), **devengo**, **liquidación**: IVA devengado y deducible del régimen general, resultado (casillas 150…46) |
| `DP30302` página 2 | 166 | 1.900 | Régimen simplificado (actividades, módulos, cuotas) |
| `DP30303` página 3 | 38 | 1.017 | Información adicional (entregas intracomunitarias…), **resultado** de la autoliquidación, rectificativa, «sin actividad» |
| `DP30304` página 4 | 43 | 998 | Solo el último periodo de exonerados del 390 |
| `DP30305` página 5 | 68 | 1.528 | Prorratas y regularizaciones (deducciones diferidas) |
| `DP303DID` | 13 | 823 | Domiciliación / devolución: IBAN, SWIFT, banco… |

**Totales:** 7 hojas, **432 campos**. **183 casillas** identificadas (la descripción de cada campo acaba en «[nnn]»: p. ej. `[150]` base imponible del IVA devengado, en la posición 131, 17 posiciones, «15 enteros y 2 decimales»). Cada casilla corresponde a **un único campo** (se comprueba en `tests/test_fiscal_diseno_303.py`); las referencias entre corchetes dentro de una fórmula no cuentan.

Reglas de formato del diseño (Nota 2 de cada hoja): `An` alfanumérico alineado a la izquierda con blancos; `Num` numérico sin signo alineado a la derecha con ceros; **`N` numérico con signo** (los negativos llevan una `N` en la primera posición); importes «15 enteros y 2 decimales» (17 posiciones **sin separador decimal**); porcentajes «3 enteros y 2 decimales».

## 3. Lo que el diseño pide del titular (cambia el esquema propuesto de F1)

Los 17 indicadores de «Identificación (1)» y los de «Devengo (2)» de la página 1 son **datos del perfil o de la declaración** que **no se pueden deducir de las facturas** (lo advertía la especificación). Cotejados con `fiscal-f1-esquema-propuesto.md`:

| Campo del diseño | Naturaleza | ¿Está en el perfil propuesto? |
|---|---|---|
| Tributación exclusivamente foral | perfil | **Falta** → `tributacion_foral` |
| Inscrito en el Registro de devolución mensual (REDEME) | perfil | ✅ `redeme` |
| Tributa solo en régimen simplificado (1 sí solo RS · 2 RG+RS · 3 solo RG) | perfil | ≈ `regimen_iva` (ampliar valores) |
| Autoliquidación conjunta | perfil/declaración | **Falta** → `autoliquidacion_conjunta` |
| Régimen especial del criterio de caja | perfil | ✅ `criterio_caja` |
| Destinatario de operaciones en criterio de caja | declaración (por periodo) | no (va en la declaración) |
| Opción / revocación de prorrata especial | perfil | ≈ `prorrata_centesimas` → **separar** `prorrata_especial` (opción) |
| Declarado en concurso (fecha, preconcursal/postconcursal) | declaración | no (va en la declaración) |
| Acogido al SII | perfil | ✅ `sii` |
| Exonerado de la declaración-resumen anual (390) | perfil/declaración | **Falta** → `exonerado_390` |
| Volumen anual de operaciones distinto de cero (art. 121) | declaración | no (va en la declaración) |
| Derecho a deducir pago a cuenta de gasolinas/gasóleos/biocarburantes | perfil | **Falta** → `deduce_pago_cuenta_carburantes` |
| IBAN / banco (domiciliación o devolución) | dato bancario | **no se infiere de facturas**; campo propio, cifrable |

**Conclusión:** el perfil de F1 queda con **4 columnas más** (`tributacion_foral`, `autoliquidacion_conjunta`, `exonerado_390`, `deduce_pago_cuenta_carburantes`), `prorrata_especial` separada, y los datos *por periodo* (concurso, destinatario de criterio de caja, volumen de operaciones, tipo de declaración, IBAN) van en `fiscal_declaraciones`, no en el perfil. **Se actualiza `fiscal-f1-esquema-propuesto.md` antes de aplicar nada** (§6).

## 4. Matriz de cobertura inicial del 303 (propuesta; se confirma con los casos de referencia)

| Bloque | Casillas (campos) | v1 |
|---|---|:-:|
| Identificación, devengo, tipo de declaración | página 1 | ✅ con datos del perfil |
| IVA devengado, régimen general: tipos general / reducido / superreducido | 150-152, 165-167, 01-03, 153-155, 04-06, 07-09 | ✅ (la **exención** del alquiler turístico no genera devengo: se trata en F3) |
| Adquisiciones intracomunitarias | 10-11 | 🚫 bloquea |
| Inversión del sujeto pasivo (otras) | 12-13 | 🚫 bloquea |
| Modificación de bases y cuotas (rectificativas) | 14-15 | ✅ simple (vinculada a la factura original) |
| Recargo de equivalencia | 156-26 | 🚫 bloquea |
| **Total cuota devengada** | 27 | ✅ |
| IVA deducible: operaciones interiores corrientes | 28-29 | ✅ **solo con cuota deducible aprobada** (≠ soportada) |
| Bienes de inversión, importaciones, intracomunitarias deducibles | 30-39 | 🚫 bloquea |
| Rectificación de deducciones | 40-41 | ✅ simple |
| Compensaciones agrícolas, regularización de inversiones y por prorrata | 42-44 | 🚫 bloquea |
| **Total a deducir / resultado régimen general** | 45-46 | ✅ |
| Régimen simplificado (página 2) | — | 🚫 bloquea |
| Información adicional y **resultado** (página 3) | — | ✅ lo que se derive de lo anterior; **compensación de cuotas anteriores y resultado final** a validar con tus casos |
| Exonerados 390 (página 4), prorratas (página 5) | — | 🚫 bloquea |
| Domiciliación/devolución (DID) | IBAN etc. | ✅ solo con datos que **introduzca una persona** |

«Bloquea» = el motor se niega a exportar y dice por qué y a quién pasar el caso; **nunca se aproxima** (plan §5).

## 5. Lo que NO sé todavía y no voy a inventar

1. **Codificación de caracteres y saltos de línea** del fichero (una fuente antigua habla de ISO-8859-15 y de no llevar CRLF, pero es de 2019 y no la he podido contrastar). **Se verifica con un fichero real exportado por el formulario oficial** (§6.3).
2. **Redondeo de las casillas calculadas** y reglas de signo de las casillas `N`: salen de las **instrucciones** (HTML descargado) y de tus casos de referencia; aún no los he leído a fondo.
3. **Compensación de cuotas de periodos anteriores** y la casilla de resultado final (página 3): requieren las instrucciones del periodo y un caso tuyo.
4. **Periodos 2T–4T:** la especificación indica instrucciones separadas (`02–12/2T–4T`); solo he descargado las de 01/1T. Cuando llegue la hora de 2T–4T se descargan y se versionan igual.

> La vía de subida a la AEAT, las condiciones de cada una y cómo se prueba están en [`fiscal-vias-aeat.md`](fiscal-vias-aeat.md).

## 6. Qué falta para cerrar F0 (y qué necesito de ti)

1. ✅ Diseño leído y verificado (hecho). 🔜 **Actualizar** `fiscal-f1-esquema-propuesto.md` con las columnas de §3 (lo hago ahora, es papel).
2. 🙋 **Diez casos de referencia del 303** con el resultado que esperas (casillas 27, 45, 46 y las de la página 3), y las **diez muestras** anonimizadas (facturas, una liquidación de plataforma, un contrato de gestión).
3. 🙋 **2–3 ficheros `.303` exportados por el formulario oficial** con NIF y datos de prueba (el botón «Exportar» del formulario del 303), para fijar byte a byte la codificación, los saltos de línea y el bloque auxiliar, y comparar contra mi exportador en F5.
4. 🙋 Tu visto bueno al esquema F1 revisado (no se aplica antes del 26-oct 12:34).
