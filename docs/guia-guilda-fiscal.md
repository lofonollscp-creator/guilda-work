# Guilda Fiscal · guía de uso y de explotación (modelo 303)

> Estado (26-oct-2026): **funcional en la rama `modulo-fiscal`**, probado en SQLite, PostgreSQL y Citus de ensayo; **no desplegado**. Despliegue: ver §5.

## 1. Qué hace y qué no
Guilda Fiscal lleva, titular a titular, el camino **factura → apunte aprobado → periodo congelado → borrador del modelo 303 → fichero para la AEAT**. Calcula con un motor determinista contrastado con el simulador de la AEAT (23 escenarios idénticos, casilla a casilla y byte a byte). **No presenta** nada: el fichero se importa en la sede electrónica (el cliente con su certificado o un colaborador social) y aquí se anota que se presentó.

Lo que **no** soporta se **bloquea** (la declaración no se puede revisar y dice por qué) en lugar de dar un número dudoso: criterio de caja, recargo de equivalencia, prorrata, régimen simplificado/agrario, ventanilla única, tributación foral, autoliquidación conjunta, SII y territorios distintos de península y Baleares. El **4T/12** (con la información anual) aún no se exporta: se podrá contrastar con la AEAT cuando se abra el periodo (enero de 2027).

## 2. El flujo en la pantalla (menú «Guilda Fiscal»)
1. **Perfil fiscal** del titular (régimen, periodicidad, opciones, cuotas a compensar iniciales). Tiene vigencia: uno nuevo cierra el anterior el día antes.
2. **Apuntes**: cada línea de los libros registro (emitida o recibida). Se pueden preparar a partir de una factura ya anotada en «Facturas para contabilizar» (propuesta que se revisa). Un apunte con errores según las reglas de la AEAT **no se aprueba**.
3. **Calcular un periodo**: congela los apuntes aprobados (la «instantánea», con huella, no se puede cambiar) y calcula el borrador. Si luego se corrige un apunte, se vuelve a congelar: la nueva instantánea **sustituye** a la anterior, que queda en el historial.
4. **Revisar** (borrador → revisada), **Generar el fichero** (revisada → exportada: `.303`, libro `.xlsx` y resumen), **Anotar que se ha presentado** (exportada → presentada, con el CSV o justificante).
5. Lo exportado o presentado **no se modifica**: lo impide la base de datos, no solo la aplicación.

**Quién aprueba:** la dirección del despacho y el revisor fiscal. El resto de la gestoría ve; el rol auditor solo consulta. **La IA y la API no aprueban ni presentan.**

## 2b. Ayudas del día a día
- **Formulario de apunte:** la numeración de las emitidas sigue sola (A-0007 → A-0008); «Duplicar» copia un apunte con el número siguiente y la fecha un mes después; la fecha de recepción sigue a la de expedición y la de operación solo sale si se pide; base, cuota y total se completan entre sí.
- **Retención de IRPF:** en una factura recibida se puede indicar la retención que practica el cliente (modelo 111 para profesionales y trabajo, 115 para alquileres): porcentaje, base e importe, que debe cuadrar. Si la factura contable ya lleva retención, la propuesta la trae rellenada. Una emitida con retención no la lleva: la soporta el cliente. Es la base del cálculo del 111 y el 115, que aún no existe.
- **Vencimientos y carga de trabajo** (`/guilda-fiscal/vencimientos`, botón en la cartera): los vencimientos pendientes a 30, 60, 90 o 180 días, los vencidos primero, con la carga por semana y por responsable. La carga se mide en puntos de trabajo (1 por vencimiento, más cada factura sin revisar o sin registrar y lo que falta del 303), no en horas: sirve para repartir, no para facturar.
- **Al escribir el NIF** de la contraparte: se cargan su nombre, tipo de NIF, país y lo habitual con ella (tipo de IVA, clave, calificación); avisa si el dígito de control no es válido y si ya existe un apunte con ese número y contraparte.
- **Avisos en vivo:** cuota distinta de base × tipo y total distinto de base + cuota (solo en emitidas sujetas, que es donde la AEAT lo exige).
- **Calcular un periodo** propone el último trimestre ya terminado y avisa si hay facturas revisadas sin registrar.
- **Cartera:** semáforo por titular (sin perfil, por calcular, borrador, pendiente de presentar, presentada), filtros «Pendientes» y «Presentados», lo urgente arriba. Importación de varios `.xlsx` a la vez: el NIF del titular va en el nombre del fichero (`A12345674-2T.xlsx`).
- **Ficha del titular:** mensaje al cliente con lo que falta para cerrar el trimestre (se copia o se abre en el correo; no se envía solo).
- **Facturas:** en «Facturas para contabilizar», cada factura tiene la casilla «Incluir en Guilda Fiscal» (marcada por defecto): si se desmarca, queda solo en la contabilidad y no sale como pendiente. La ficha del titular avisa de las facturas que esperan revisión (con enlace) y lista las revisadas por registrar; la cartera lo resume por titular.
- **Declaración:** al recalcular un periodo se ve qué casillas han cambiado respecto al cálculo anterior, y hay un resumen en PDF para el cliente.

## 3. API, MCP y asistente de IA (solo consulta y simulación)
Área de token `guilda_fiscal` (`/api/v1/guilda-fiscal/…`): titulares, perfil, apuntes, comprobación con las reglas de la AEAT, simulación del 303 (no guarda nada), declaraciones y propuesta de apuntes de una factura. Las mismas ocho herramientas están en el MCP y en el asistente (`fiscal_*`).

## 4. Datos de prueba y contraste con la AEAT
`scripts/fiscal/grabar_oraculo.py` sube los libros de `tests/escenarios_303.py` al simulador público de la AEAT y graba su resultado en `tests/fixtures/aeat/oraculo_libros/`; la suite compara el motor con él sin red. Para ampliar: añade un escenario y grábalo.

## 4b. Cómo comprobarlo en producción (≈ 20 minutos, con datos inventados)
1. **Tras migrar y reiniciar**, ejecuta `scripts/fiscal/verificar_despliegue.py` (comandos en `docs/despliegue-guilda-fiscal.md`): comprueba, solo leyendo, que las siete tablas, el aislamiento por despacho, los triggers de inmutabilidad y la distribución en Citus están. Debe acabar en «TODO CORRECTO».
2. **Un despacho de prueba** (no uno real): backoffice → activar «Guilda Fiscal». Con una persona de la dirección: menú «Guilda Fiscal».
3. **Un titular de prueba**: «Empresa de prueba SL», NIF `A12345674`, en el calendario fiscal. En Guilda Fiscal: su **perfil** (sociedad, régimen general, trimestral, desde 2026-01-01).
4. **Importar un libro de muestra** (`docs/muestras-fiscal/basico.xlsx`) en su ficha → deben entrar 2 apuntes.
5. **Calcular un periodo** (2026, 2T) → borrador con resultado **10,50 €** y las casillas de `docs/muestras-fiscal/LEEME.md`. Pulsa sobre un apunte para ver de qué casilla forma parte.
6. **Revisar → Generar el fichero → descargar el `.303`**. Si quieres el contraste final con la AEAT: abre el simulador público del modelo 303 (2T 2026, NIF `A12345674`), «Importar» ese `.303` y comprueba que da el mismo resultado y ningún error.
7. **Anotar que se presentó** → el vencimiento del 303 de ese titular (si existe en el calendario) pasa a «presentado».
8. **Lo que NO debe poder hacerse**: aprobar con una cuenta que no sea dirección/revisor fiscal; modificar una instantánea o una declaración exportada (ni por pantalla ni por API); ver apuntes de otro despacho. Los tests lo cubren; el paso 2 con una cuenta de gestor lo confirma a mano.
9. Repite 3-6 con otras muestras (un titular de prueba por muestra: alquileres, intracomunitarias, rectificativas…): el resultado de cada una está en `LEEME.md`.

## 5. Despliegue (lo hace Jorge; nada se aplica solo)
1. No antes del lunes 26-oct 12:34 (cierre de la vuelta atrás B de PostgreSQL).
2. Mezclar `modulo-fiscal` en `main` (resolver contadores de herramientas y catálogo OpenAPI frente al trabajo de la app móvil).
3. `scripts/migrar_esquema_pg.py` con el superusuario: aplica **002** (perfiles y relaciones) y **003** (núcleo). Ambas crean tablas **nuevas y vacías**; revertir = `DROP TABLE` de ellas.
4. Reiniciar `guilda-work` y `guilda-work-mcp`.
5. Activar el vertical «Guilda Fiscal» por despacho (backoffice) y, si procede, crear su extra de pago.

## 6. Pendiente (otras fases)
Extracción de facturas con evidencia por campo (F2), vertical de alquileres con liquidaciones de plataformas, 4T/12 y rectificativas del 303, panel de cartera por vencimientos, captura desde el móvil y cobro por uso afinado.
