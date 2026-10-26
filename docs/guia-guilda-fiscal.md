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

## 3. API, MCP y asistente de IA (solo consulta y simulación)
Área de token `guilda_fiscal` (`/api/v1/guilda-fiscal/…`): titulares, perfil, apuntes, comprobación con las reglas de la AEAT, simulación del 303 (no guarda nada), declaraciones y propuesta de apuntes de una factura. Las mismas ocho herramientas están en el MCP y en el asistente (`fiscal_*`).

## 4. Datos de prueba y contraste con la AEAT
`scripts/fiscal/grabar_oraculo.py` sube los libros de `tests/escenarios_303.py` al simulador público de la AEAT y graba su resultado en `tests/fixtures/aeat/oraculo_libros/`; la suite compara el motor con él sin red. Para ampliar: añade un escenario y grábalo.

## 5. Despliegue (lo hace Jorge; nada se aplica solo)
1. No antes del lunes 26-oct 12:34 (cierre de la vuelta atrás B de PostgreSQL).
2. Mezclar `modulo-fiscal` en `main` (resolver contadores de herramientas y catálogo OpenAPI frente al trabajo de la app móvil).
3. `scripts/migrar_esquema_pg.py` con el superusuario: aplica **002** (perfiles y relaciones) y **003** (núcleo). Ambas crean tablas **nuevas y vacías**; revertir = `DROP TABLE` de ellas.
4. Reiniciar `guilda-work` y `guilda-work-mcp`.
5. Activar el vertical «Guilda Fiscal» por despacho (backoffice) y, si procede, crear su extra de pago.

## 6. Pendiente (otras fases)
Extracción de facturas con evidencia por campo (F2), vertical de alquileres con liquidaciones de plataformas, 4T/12 y rectificativas del 303, panel de cartera por vencimientos, captura desde el móvil y cobro por uso afinado.
