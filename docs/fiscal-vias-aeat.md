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

## 5. Lo que sigue sin saberse (y cómo se resuelve)

| Duda | Cómo se cierra |
|---|---|
| **Codificación de caracteres y saltos de línea** del `.303` (no figuran en el diseño ni en la ayuda; una fuente antigua habla de ISO-8859-15 sin CRLF) | Comparar con 2–3 ficheros **exportados por el formulario oficial** (datos de prueba) |
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
