# Con qué «modelo» y por qué vía se sube a la AEAT lo que genera Guilda Fiscal

> Investigado el 24-oct-2026 en las páginas oficiales de la AEAT (enlaces abajo). Respuesta corta: **el modelo es el 303, ejercicio 2026 y siguientes, con el diseño de registro `DR303e26v101` (versión 1.01, 28/01/2026); se sube con el botón «Importar» del formulario web del 303 (servicio Pre303)**, y hay una **segunda vía, independiente, que lee las facturas en lugar de las casillas: importar los «Libros Registro» (Excel LSI)**. No hay presentación directa por fichero para 2026.

## 1. Las vías que existen para 2026

| | **A · Fichero `.303`** (lo que genera nuestro motor) | **B · Libros Registro LSI (XLSX)** | C · Presentación por fichero «clásica» |
|---|---|---|---|
| **Qué lee la AEAT** | Las **casillas ya calculadas** (identificación, devengo, régimen general, información adicional, resultado, IBAN) tal y como las define el diseño oficial | Las **facturas** (libros de expedidas y recibidas); **la AEAT calcula las casillas** | — |
| **Dónde** | Formulario web del 303 (Pre303) → ventana inicial → **«Importar»** «un fichero confeccionado con un programa ajeno cuyo diseño se ajuste al publicado» | Formulario del 303, página de liquidación → botón **«Libros Registro»** → indicar el fichero | «Leer declaración» en «Presentación del modelo 303 por fichero» |
| **Para 2026** | ✅ Sí | ✅ Sí, con condiciones (abajo) | ❌ La página oficial es de «**2022 y ejercicios anteriores**» |
| **Formato** | Texto «formato BOE», nombre `NIF + ejercicio + periodo + .303`; diseño `DR303e26v101.xlsx` (ya leído y verificado en el repositorio) | **XLSX** ≤ 4 MB, hojas con nombres publicados (expedidas / recibidas en hojas distintas), **sin fórmulas ni celdas combinadas**; diseños de registro normalizados «actualizados a 01-01-2026» y plantilla de la AEAT | Mismo diseño que A (histórico) |
| **Quién puede** | Cl@ve, certificado o DNIe del declarante; o quien presenta con **alta de colaborador social o apoderamiento**; para usar Pre303 en nombre de un tercero hace falta **apoderamiento al trámite PRE303** (si no, el sistema da un enlace para que el titular lo conceda) | Igual, **y además**: periodicidad **trimestral**, **no** SII, **no** régimen simplificado, **no** criterio de caja ni régimen especial del oro; desde el 1T de 2022 | — |
| **Control que nos da** | Total: nuestro motor decide cada casilla y deja la traza | Parcial: la AEAT decide; los datos económicos del formulario **no se pueden editar**, se corrige el libro y se reimporta (la importación **borra** lo que hubiera en el formulario) | — |
| **Qué hace nuestro módulo** | **Adaptador principal** (F4–F5) | **Adaptador secundario** y **oráculo de comprobación** (F5b, §3) | No se implementa |

Fuentes: [Ayuda técnica · presentación mediante formulario web](https://sede.agenciatributaria.gob.es/Sede/ayuda/consultas-informaticas/presentacion-declaraciones-ayuda-tecnica/modelo-303.html) · [Ayuda técnica · presentación por fichero (2022 y anteriores)](https://sede.agenciatributaria.gob.es/Sede/ayuda/consultas-informaticas/presentacion-declaraciones-ayuda-tecnica/modelo-303/presentacion-electronica-modelo-303-fichero.html) · [Formas de presentación del modelo 303](https://sede.agenciatributaria.gob.es/Sede/iva/presentar-declaracion-iva-modelo-303/formas-presentacion-modelo-303.html) · [FAQ Pre303/LSI](https://sede.agenciatributaria.gob.es/Sede/iva/facturacion-registro/preguntas-frecuentes.html?faqId=b4888b52e84ef710VgnVCM100000dc381e0aRCRD) · [Plantilla de libros en soporte electrónico](https://sede.agenciatributaria.gob.es/Sede/iva/pre-303/nuevo-servicio-pre303-importacion-libros-electronico/plantilla-libros-soporte-electronico.html) · [Diseños de registro normalizados de libros](https://sede.agenciatributaria.gob.es/Sede/iva/pre-303/nuevo-servicio-pre303-importacion-libros-electronico/disenos-registro-normalizados-libros-registro.html).

## 2. Qué lee exactamente la vía A y qué NO viene en el fichero

El fichero lleva **identificación y 17 indicadores**, **devengo** (ejercicio y periodo), **liquidación** del régimen general (casillas 150…46), **información adicional y resultado** (página 3), y el bloque de **domiciliación/devolución** (IBAN). Pero el formulario **muestra además datos censales** («Ventana Censal IVA», «Mis datos censales IVA») y pide «asegúrate de que la información mostrada es correcta»: **la identificación del fichero y los datos censales deben coincidir**. Si el perfil del titular en Guilda (forma jurídica, régimen, periodicidad, criterio de caja…) no coincide con el censo, el formulario avisará o no dejará continuar: por eso el perfil de F1 se contrasta con la **Ventana Censal** en el piloto, no se da por bueno. El **NRC** (justificante de pago) **no sale de las facturas**: se obtiene al pagar en el propio formulario.

Pasos reales de la persona que sube el fichero (de la ayuda oficial): identificarse → NIF, nombre/razón social, ejercicio y periodo → **Confirmar** → Ventana Censal → «Continuar con la presentación» → **«Importar»** → *Validar declaración* (los avisos no impiden presentar; los errores sí) → *Guardar* (opcional, en servidores de la AEAT) → **Presentar** → «Conforme» → **Firmar y enviar** → pagar (NRC) o domiciliar. **Exportar** en el formulario genera un `.303` válido para presentar: es **nuestro fichero de referencia** (§4).

## 3. Cómo se usan las dos vías juntas (idea para el piloto)

1. **Producción:** vía A (nuestro motor calcula y exporta).
2. **Comprobación independiente:** con los **mismos datos**, generar el **libro LSI** (adaptador B) y **dejar que la AEAT calcule las casillas**; comparar **casilla a casilla** con las de nuestro motor. Dos cálculos independientes que coinciden son la mejor evidencia de que el motor es correcto, y una discrepancia señala si falla nuestra regla o nuestro dato. Solo aplica a titulares que cumplan las condiciones de B (trimestral, no SII, no simplificado, no criterio de caja).
3. **Datos mínimos que exige B** (y que conviene exigir ya a nuestras facturas): NIF o identificador extranjero con **código de país y tipo de identificación**, **fecha de operación** cuando difiera de la de expedición, **una línea por tipo impositivo** con su «total factura», rectificativas por el método elegido (sustitución o diferencias) y, si se lleva IRPF, las retenciones. `facturas_contables` ya guarda líneas por tipo y fecha de operación; **faltan** tipo/código de identificación de terceros extranjeros y el método de rectificación (se añaden en F2).

## 4. Cómo se prueba sin presentar nada

| Entorno | Qué es | Estado |
|---|---|---|
| **Portal de Pruebas Externas** de la AEAT, [formularios del 303](https://preportal.aeat.es/PRE-Exteriores/Inicio/_menu_/IVA/Modelo_303/Modelo_303.html) | Pre-producción: «Presentación y servicio de ayuda Pre303» (2026), **«Simulador» (OPEN) 2026**, y (solo Administración Foral) presentación; **el aviso del 14-10-26 indica que ya están los formularios del último periodo (12/4T) de 2026** | Los enlaces piden certificado; **no he podido abrir el simulador (es una aplicación interactiva) ni saber si admite «Importar»**. **Lo prueba una persona con certificado** |
| Formulario **real**, con «Validar declaración» y **sin** pulsar «Presentar» | Valida el fichero con las reglas reales; «Guardar» no presenta | Disponible cuando quieras, con certificado/Cl@ve de un titular real |
| **Exportar** del formulario | Genera un `.303` válido: sirve de **muestra byte a byte** | Necesito 2–3 de ellos (§5) |

**Regla de la casa (de la especificación y del plan):** un fichero bien formado **no** acredita aceptación AEAT. No se anuncia compatibilidad hasta que un fichero nuestro se importe y valide en el formulario (simulador o real) con la evidencia guardada.

## 4b. Lo que Jorge ha comprobado en el simulador (24-oct, noche)

- El **simulador del 303 2026** (Portal de Pruebas Externas) **permite importar y cargar** y trabaja con un fichero **`.SES`** (Jorge supone que es el que habría que generar). **Mi lectura:** `.ses` es, casi seguro, la **sesión guardada** del formulario (la ayuda oficial habla de «Guardar» la sesión y de recuperarla), un formato **propio de la AEAT** que **no está documentado**; el formato **documentado y estable** para programas externos es el **`.303`** (diseño publicado). Por eso **seguimos generando `.303`**; el `.ses` solo se tocaría si el simulador no aceptara el `.303`, y para eso hace falta ver uno real.
- **Presentación preferente como colaborador social** (también cabe que presente el propio cliente) → respuesta a F-D11. Consecuencias: la gestoría presenta con su **certificado de colaborador**; la ayuda oficial indica que ciertas utilidades (p. ej. recuperar el NRC de un pago previo) **no están disponibles para colaboradores sociales**; y para usar el **servicio Pre303** en nombre de un tercero hace falta el **apoderamiento al trámite PRE303** o que el titular lo conceda con el enlace que el sistema muestra.
- Datos de prueba del simulador visibles en su pantalla: **NIF `J21938519` (LO FONOLL SCP), ejercicio 2026, periodo 2T**; el formulario tiene 5 apartados («Identificació», «Règim general», «règim simplificat», «Informació addicional», «Resultat») y botones «Llibres de registre», «Vista prèvia», «Validar» e importar/cargar: **confirma el flujo de §2** y la vía B («Libros de registro») también en el simulador.

## 4c. Ficheros de prueba ya generados (fuera del repositorio)

`/home/guilda/muestras-303/` (NIF y nombre de la pantalla de Jorge; **no se versionan**):

| Carpeta | Contenido | Para qué |
|---|---|---|
| `A_cero/J2193851920262T.303` | Declaración de **tipo N** (sin actividad / resultado cero): identificación, indicadores del periodo y todas las casillas a 0 | Comprobar que el simulador **abre** el fichero y qué errores de estructura da |
| `B_ejemplo_21pc/J2193851920262T.303` | Una venta de **100,00 €** al 21 % (casillas 07, 09, 27, 45, 46 y 64–71), **tipo I** (ingreso 21,00 €) | Comprobar que la **cadena de casillas** que calculamos es la que la AEAT valida |

Se generan con `app/fiscal_modelos/exportador_303.py` (diseño oficial + reglas de formato de la Nota 2). **La codificación y los saltos de línea son suposiciones** (ISO-8859-15, sin saltos de línea) hasta ver un `.303` exportado por el formulario. Lo que diga el simulador (errores y avisos) se pega aquí y se corrige el exportador **antes** de seguir.

## 4d. Probado contra el simulador público desde Linux (24-oct-2026, noche)

El simulador es público y **no pide certificado**: `https://www2.agenciatributaria.gob.es/wlpl/A303-FWME/E2026/OPEN/index.zul` («Datos identificativos OPEN», versión 1.06; botones **Cargar** = sesión guardada, **Importar** = fichero `.303`, **Aceptar** = nueva). Se maneja con un navegador automatizado: `scripts/fiscal/simulador_aeat.py` importa un `.303`, recoge los errores y avisos de la importación y de «Validar», lee el resultado que calcula la AEAT y, con `--exportar`, descarga lo que el propio simulador exporta de vuelta.

| Intento | Respuesta del simulador | Qué se corrigió en el exportador |
|---|---|---|
| 1.º | **Fichero rechazado** (`FRECH`): `E010170`/`E010180` «Caracteres no válidos» en *Opción/Revocación de la prorrata especial* y `E060010` «Contenido incorrecto en 'Pagina DID'» | La Nota 6 del diseño dice «blanco» pero el valor que acepta es **`2`**; la **página DID va siempre**, aunque vacía |
| 2.º | Importa; `E0103x1…E010631` «La casilla *Tipo %* sólo admite valor 4 / 10 / 21 / 1,75 / 0,5 / 1,4 / 5,2» y `E030171` «% Atribuible a la Administración del Estado [65] obligatoria» | Constantes con «Nota» a continuación (`Constante "00400". Nota 7`, `"00050". Nota 7.`) no se leían; la casilla **65 = 100,00** es obligatoria |
| 3.º | **Fichero A (a cero)**: importa; validación `303M030` «NO tributa exclusivamente en régimen simplificado y no hay contenido en la liquidación del régimen general» (lógico: no hay actividad) | — |
| 3.º | **Fichero B (100,00 € al 21 %)**: importa **sin errores** («No existen errores.» + aviso `31190` «Revise… Información adicional»); **la AEAT calcula resultado 21,00 €** | — |
| Control | **Fichero C** (casilla 27 mal a propósito): `E010671` «Total cuota devengada [27] debe ser igual que la suma de…» y `E010861` «Resultado [46] debe ser igual que la 27 menos la 45» | El validador **sí detecta incoherencias**: el «sin errores» del fichero B es una validación real |

**Exportado de vuelta por la AEAT.** Al elegir «Seleccionar Ingreso/Devolución → A ingresar → **Exportar**» el simulador entrega `A12345674_2026_2T.303` (nombre **NIF_ejercicio_periodo.303**, con guiones bajos). Comparado con nuestro fichero: **mismo tamaño (3.767 bytes) y solo 4 campos distintos**, todos de la AEAT o de la entidad desarrolladora: *Reservado para la Administración* (campo 8 de la envoltura), *Versión del programa* (la AEAT escribe `1.06`), *NIF de la entidad desarrolladora* (la AEAT escribe el suyo) y el *Reservado para la AEAT* de la página 3. Además confirma **tres dudas que eran suposiciones**: **ASCII, sin CR ni LF** (una sola línea) y la **fecha del auto de concurso va a ceros** cuando no hay concurso (corregido). Ambos ficheros (con un NIF de prueba) están en `tests/fixtures/aeat/` y `tests/test_fiscal_exportador_303.py` exige la coincidencia.

**Lo que esto cambia:** el simulador es un **oráculo automático** de formato, de coherencia entre casillas y del resultado, accesible desde Linux sin certificado ni intervención humana. La prueba en línea (`GUILDA_FISCAL_SIMULADOR=1`) es opcional y no corre en la suite normal. **Sigue sin acreditar** la aceptación en producción: el simulador y el formulario real comparten reglas, pero la presentación, el censo (Ventana Censal) y la firma solo existen en el servicio real.

## 4e. La vía B (libros registro) funciona en el simulador y es nuestro oráculo (25-oct-2026)

El formulario trae el botón **«Libros de registro»** (solo en periodos TRIMESTRALES; en mensual no existe) → «Importar libro de registro» → un `.xlsx`. La AEAT valida el libro, calcula las casillas con sus propias reglas y deja exportar el `.303` resultante. Así, **el mismo libro se calcula con nuestro motor y con la AEAT y se comparan las casillas** (`scripts/fiscal/simulador_libros.py`, `grabar_oraculo.py`, `tests/escenarios_303.py`).

Formato del `.xlsx` (descubierto por prueba y error contra el simulador; el fichero «LSI.xlsx» de la AEAT es solo documentación):
- Hojas `EXPEDIDAS_INGRESOS`, `RECIBIDAS_GASTOS` y `BIENES-INVERSIÓN`; **datos desde la fila 1, sin cabeceras** (con cabeceras, el simulador las lee como registros erróneos). Columnas = las de las plantillas oficiales.
- Fechas como fecha de Excel; importes con dos decimales; una fila por factura; el libro es el del ejercicio completo hasta el periodo (desde 2023).
- Actividad: código `B` + tipo `01` (el par que no pide inmueble ni epígrafe del IAE). `A01` y `D` exigen situación y referencia catastral.
- Tras importar hay que contestar las preguntas de «Identificación» (autoliquidación conjunta, criterio de caja, destinatario de caja, concurso, SII); si no, error PAR018.

Reglas de validación que el simulador aplica al libro (y que nuestro validador de entrada debe replicar): la fecha de expedición no puede ser posterior a hoy; el IVA al 0 % y al 5 % solo se aceptan en periodos concretos; con inversión del sujeto pasivo o clave 09 el total de la factura es la base; el NIF-IVA intracomunitario se valida con el algoritmo de su Estado miembro (formato `FR40303265045` con el prefijo, tipo `02` y país); S2 exige tipo y cuota a cero (no vacíos); F5 (DUA) lleva como expedidor el NIF del propio titular y un nº de DUA español (`26ES…`), y si no es español la cuota deducible debe ser cero; «deducible en periodo posterior» exige un periodo de deducción posterior al de la fila.

**Resultado:** 23 escenarios (también simplificadas y resumen, rectificativas de intracomunitarias y de inversión del sujeto pasivo, abonos en otro periodo y tres de alquileres: local comercial al 21 % con referencia catastral, vivienda exenta y alquiler turístico al 10 %) más los 16 de abajo (ventas por tipo, otros trimestres, fecha de operación, rectificativas y abonos, bien de inversión, importación, adquisición intracomunitaria, inversión del sujeto pasivo en recibidas y en expedidas, exentas y no sujetas, recepción posterior, deducción diferida, resultado negativo, céntimos con decimales) dan **exactamente las mismas casillas** en nuestro `motor_303` y en la AEAT, y el `.303` que generamos (`fichero_303`) coincide byte a byte con el que exporta la AEAT salvo identificación del programa.

Límites: el simulador no presenta; no cubre censo, firma ni presentación real. El último periodo (4T/12) lleva información anual (casillas 79-99) y no se genera todavía. Después se soportaron criterio de caja, recargo repercutido y prorrata general (§4f). No están soportados (se BLOQUEAN, no se calculan): prorrata especial, régimen simplificado/agrario, ventanilla única (OSS), tributación foral, compensaciones del régimen especial y regularización de inversiones.

## 4f. Rectificativa, recargo, caja y prorrata contra el simulador (28-oct-2026)

Se pasaron por el simulador público (el mismo procedimiento de §4d y §4e) los casos que se habían construido sin poder contrastarlos. Todo queda grabado y se comprueba sin red: `scripts/fiscal/grabar_oraculo.py` (libros: `ESCENARIOS_ESPECIALES`) y `scripts/fiscal/grabar_ficheros_303.py` (ficheros `.303` completos: `tests/escenarios_ficheros_303.py`), con `tests/test_fiscal_motor_303.py` y `tests/test_fiscal_ficheros_aeat.py`.

**Cálculo (libro → AEAT).** Recargo de equivalencia (tres escenarios: 21 %/5,2 %, varios tipos y con abono) y criterio de caja (cobro total, cobro parcial, cobro en un periodo posterior al de la factura, factura sin cobros y compra pagada en parte): `motor_303` da **exactamente las mismas casillas** que la AEAT.

**Ficheros `.303` (importar → validar → exportar de vuelta).** Once ficheros: rectificativa a ingresar, rectificativa con casilla 111 e IBAN, recargo, caja (acogido y destinatario), prorrata general, resultado a compensar, 1T, 3T y los meses 01 y 05. Los once se importan con «No existen errores» (solo avisos 30xxx/31xxx) y el fichero que **exporta la AEAT es idéntico al nuestro** salvo los cuatro campos que son suyos (§4d).

| Lo que dijo el simulador | Qué se corrigió |
|---|---|
| Línea de cobro con tipo de IVA: «Es incompatible rellenar el campo tipo de IVA con los campos de cobro»; «El periodo y ejercicio consignado deben coincidir con los de la Fecha de Cobro» | En el libro, la factura va una vez y cada cobro o pago en una línea propia **sin total, base, tipo ni cuota** y con el periodo del cobro (antes repetíamos la factura entera en cada cobro) |
| Rectificativa con casilla 111: `35066` «el código cuenta IBAN es obligatorio» y `EDID112` «Marca SEPA» | La página DID del fichero lleva el IBAN y la marca SEPA (1 España, 2 SEPA); se pide en la pantalla (Nota 3 del diseño) |
| Tipo «D» fuera del último periodo: `30260` «No se permite la devolución excepto en el último período» | Pedir la devolución fuera del 4T/12 bloquea el cálculo; se compensa |
| 4T de 2026: «El periodo seleccionado no está permitido» (ni en libro ni en fichero) | **No se puede probar todavía** (hasta que se abra el periodo): la casilla 44 de la prorrata, la página 4 y la devolución con IBAN quedan sin contrastar |

Tampoco se contrastaron en el simulador la casilla 44 (solo existe en el último periodo) ni el 390, 111, 115 y 130 (otros modelos, otro simulador).

## 5. Lo que sigue sin saberse (y cómo se resuelve)

| Duda | Cómo se cierra |
|---|---|
| ~~Codificación y saltos de línea del `.303`~~ | **Resuelto** (§4d): ASCII, una línea sin CR/LF. Solo emitimos ASCII (`limpiar_texto`); los nombres con tildes se transcriben sin ellas |
| Qué escribir en *Versión del programa* y *NIF de la entidad desarrolladora* (hoy en blanco; la AEAT pone los suyos al exportar) | Decisión: ¿se consigna a Guilda como entidad desarrolladora? (campos 9 y 11 de la envoltura) |
| ~~Si el simulador OPEN 2026 admite «Importar»~~ | **Sí** (Jorge, 24-oct): importa y carga, con `.SES`. Falta probar el `.303` (§4c) |
| Si existe **presentación por lotes / servicio web** del 303 para colaboradores en 2026 (la sede lista una gestión «Presentación por lotes» junto al 303, pero no he podido leer su contrato y el documento técnico de coordinación, v7.02, es antiguo y no se descargó) | Preguntarlo a la AEAT / revisar el portal de desarrolladores antes de prometer nada; **no se presupuesta** |
| Cómo reacciona el formulario si **identificación del fichero ≠ censo** | Prueba con un titular real en el piloto |
| Qué **plantilla/diseño de libros** corresponde a cada perfil (hay una plantilla «para personas jurídicas» y otra para físicas) | Descargarlas (permiso) y leerlas en F5b |

## 6. Cambios en el plan por este hallazgo

- **F5** («Exportador `.303` y validación»): la **validación oficial** pasa a ser «importar en el formulario/simulador **y pulsar Validar**», con evidencia (captura y fichero) guardada en `fiscal_artefactos`; y se añade la **comparación contra un `.303` exportado por el formulario**.
- **F5b (nuevo, ≈ 25–40 h):** **adaptador «Libros LSI (XLSX)»** como segunda salida y como **oráculo** de comparación; reutiliza el registro fiscal de F3.
- **F2:** añadir a las facturas los campos que exige B (identificador y país de terceros extranjeros, método de rectificación).
- **F6:** el flujo de presentación incluye la **comprobación del apoderamiento** (colaborador social o PRE303) y el cotejo con la **Ventana Censal**.
- **Decisión F-D11 (respondida):** presentar **preferentemente como colaborador social**; opcionalmente el propio cliente.
- **Esfuerzo total del plan:** 340–530 h (+25–40 h de F5b).
