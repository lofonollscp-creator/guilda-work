# Asistente jurídico · preparación del piloto con profesionales (hito 5)

Estado: **preparado, no ejecutado.** El piloto lo hace un profesional jurídico sobre un corpus real autorizado; este documento deja el guion y las herramientas. Nada de lo que sigue son resultados.

## Antes de empezar
1. Registrar la política de uso del BOE (evidencia: aviso legal del BOE y su atribución) y habilitar `boe-consolidada` y `boe-diario-tc` (Asistente jurídico → Fuentes).
2. Sincronizar la ventana que cubra las consultas del piloto (los textos consolidados son de la fecha de actualización; las sentencias del TC, por días de publicación).
3. Confirmar la cobertura real en «Fuentes» (documentos, fechas, cuarentena) y apuntarla en el informe del piloto. La jurisprudencia ordinaria (CENDOJ) **no está** y no se puede evaluar.
4. Configurar el modelo de IA de la persona evaluadora (Ajustes del Asistente IA).

## Conjunto de casos
Unos 50 casos de fiscal y laboral, anotados por el profesional, en JSON (formato en `app/juridico/evaluacion.py`; plantilla sintética en `tests/datos/juridico_evaluacion_plantilla.json`): pregunta, fecha jurídica, colecciones, fuentes esperadas (`id_externo` + localizador) y los supuestos que deben quedar **sin base suficiente**. Los casos con `sintetico: true` prueban el software y no cuentan.

## Medición
- Recuperación (automática): `.venv/bin/python scripts/evaluar_juridico.py conjunto.json --despacho <id>` → % de casos con una fuente necesaria entre los 10 primeros resultados y los «insuficientes» que no recuperan nada. Informar siempre con el tamaño del corpus y el modo (`texto` o `hibrido`).
- Respuestas (manual): `--revision salida.json --usuario <id>` (gasta consultas de IA) genera cada respuesta con su hoja de puntuación en blanco: ¿es correcta?, ¿las citas sostienen la afirmación?, ¿hay citas inventadas?, ¿la aplicabilidad temporal es correcta?, ¿es útil?, minutos de revisión.
- Aislamiento: dos despachos y dos clientes con IDs adivinados (cubierto por `tests/test_juridico_aislamiento.py`; repetir a mano con datos reales de prueba).

## Objetivos propuestos (a validar, no logrados)
Cero filtraciones entre organizaciones; cero citas inventadas aceptadas en el conjunto evaluado; al menos 90 % de citas que sostienen su afirmación; al menos 85 % de consultas que recuperan una fuente necesaria entre los 10 primeros. La revisión jurídica puede exigir umbrales superiores. Búsqueda p95 < 2 s sobre el corpus del piloto: medir y registrar tamaño del corpus, proveedor y concurrencia.

## Qué decide el piloto
Si la validación léxica/numérica basta o hace falta evaluación semántica; si el tope de 10 fragmentos y el reparto entre colecciones recuperan lo necesario; si hay que priorizar doctrina (DGT/TEAC) o jurisprudencia ordinaria antes de ampliar; y si el coste por consulta es asumible (medir con `consumo_ia`).
