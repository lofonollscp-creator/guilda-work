# ADR · Asistente jurídico (módulo «juridico»)

Fecha: 23-oct-2026. Estado: aceptada. Especificaciones de origen: `Guilda_Work_IA_Juridica_Especificacion.md` y `Guilda_Work_Flujo_Datos_Juridicos_APIs.md` (documentos del propietario, hitos 0-4; el hito 5, piloto con profesionales, queda preparado pero lo ejecuta una persona).

## Contexto verificado en el repositorio (hito 0)

| Pieza | Realidad de Guilda Work | Decisión |
|---|---|---|
| Stack | Flask + SQLite (`data/registro.db`), sin PostgreSQL ni pgvector, sin cola externa | Se reutiliza. Nada de microservicios ni de migrar de base de datos |
| Módulos de negocio | «Verticales» (`app/verticales.py`) activables por despacho, con esquema aditivo e idempotente | Nuevo vertical `juridico`, desactivado por defecto |
| Identidad y permisos | `app/acceso.py` (oficinas, auditor solo lectura, visibilidad de clientes), tenant en la sesión | Se reutiliza; el `tenant_id` nunca viene del cuerpo de una petición |
| IA | `app/ia_asistente.py`: clave de OpenRouter **de cada persona**, modelo elegido por ella; ya hay contabilización de uso | Adaptador `generar_estructurado` sobre `completar_texto`; el proveedor no se codifica en la lógica |
| Embeddings | `app/embeddings.py`: Ollama local, opcional, degrada a `None` | Búsqueda híbrida = FTS5 + vectores **si hay embeddings**; sin ellos, solo texto (y se dice) |
| Búsqueda de texto | SQLite FTS5 ya en uso (correo) | FTS5 en español (`unicode61 remove_diacritics`) sobre los fragmentos |
| Hilos periódicos | Hilos demonio en `app/main.py` (recordatorios, correo…) | Un hilo de sincronización jurídica, apagado salvo `LEGAL_AI_SYNC=1` |
| Documentos del despacho | `app/almacen_documentos.py` (cifrado por despacho, visibilidad por cliente/expediente) | Los adjuntos privados del asistente se guardan aparte y por despacho; **no** entran en el corpus común |
| Extracción PDF | Sin librería de PDF instalada (`python-docx` sí) | TXT y DOCX en el MVP; PDF exige `pypdf` (la instala una persona) y, si falta, se rechaza con un mensaje claro; sin OCR se rechaza el PDF escaneado |
| Antivirus | `app/antivirus.py` (ClamAV opcional) | Se aplica a los adjuntos si está activo |
| Documentación de API | OpenAPI generado del código (`app/openapi_catalogo.py`) | La API del asistente se documenta ahí |

## Decisiones

1. **Dos circuitos** (ingesta y consulta) separados, como pide el anexo: la consulta nunca llama a los portales oficiales; busca en la biblioteca local autorizada.
2. **Tablas `jur_*`**. El corpus compartido (`jur_fuentes`, `jur_politicas`, `jur_documentos`, `jur_versiones`, `jur_fragmentos`…) no lleva `tenant_id`; lo privado (adjuntos, conversaciones, ejecuciones, citas, informes, auditoría) lo lleva siempre y todas sus consultas empiezan por él. Una fuente se **habilita por despacho** (`jur_fuente_despacho`): que exista código o que el corpus lo tenga no la habilita.
3. **Política antes de cada operación**: `jur_politicas` (por fuente, versionada) dice si se puede almacenar, indexar, enviar al modelo, citar y exportar. Sin política vigente, la fuente no sincroniza, no se busca y no llega al modelo. La capacidad técnica (`fetchContent`) no equivale a derecho de uso.
4. **Honestidad de cobertura**: cada colección enseña lo realmente indexado (documentos, fechas, última carga correcta). «Última carga correcta» no significa «actualizado»: hay retraso por fuente. Las colecciones sin conector habilitado se ven como «pendiente de habilitación»; nunca se rellenan con respuestas del conocimiento del modelo.
5. **Identidad documental separada del origen**: `jur_documentos` por `(fuente, id externo)` con identificadores (ECLI, ROJ, ELI, CELEX) solo si constan; la agrupación entre fuentes se propone, no se fusiona sin identificador verificado.
6. **Versiones inmutables y publicación atómica**: una versión nueva se prepara (texto, fragmentos, índice) y se activa en **una transacción** SQLite; una consulta nunca mezcla texto de dos versiones. En legislación, cada fragmento es una versión de un bloque (artículo) con su vigencia **tal como la publica la fuente**; si no consta, queda `NULL` y se explica («desconocida»), nunca se infiere de la fecha de publicación.
7. **Ingesta durable**: estados `DISCOVERED → FETCH_PENDING → FETCHED → PARSED → VALIDATED → INDEX_PENDING → INDEXED → PUBLISHED` más `RETRYABLE_ERROR`, `QUARANTINED`, `BLOCKED_POLICY`, `WITHDRAWN`; `outbox` en la misma transacción que el cursor; consumidores idempotentes; el cursor significa «inventario registrado», no «publicado».
8. **Conectores**: contrato común (`app/juridico/conectores/base.py`). Reales y verificados contra el servicio en vivo el 23-oct-2026: **BOE legislación consolidada** y **BOE sumarios** (formato inspeccionado, ver `tests/fixtures_juridico/README.md`). **CENDOJ**: solo la interfaz, sin endpoint inventado, deshabilitado. **EUR-Lex/Cellar** y los internacionales: interfaz y capacidades declaradas, desactivados.
9. **Fixtures**: solo sintéticos, marcados como tales, y solo en pruebas/desarrollo; nunca aparecen en producción.
10. **Seguridad**: cliente HTTP con lista blanca de dominios por conector (SSRF), tamaño máximo, tiempo máximo, reintentos con espera exponencial y `Retry-After`; extracción en el mismo proceso solo de formatos acotados (TXT, DOCX con límite de expansión); el texto recuperado y los adjuntos son datos, nunca instrucciones.
11. **Feature flags**: `LEGAL_AI_ENABLED` (el módulo existe), vertical activo por despacho (lo ve), fuente habilitada por despacho y con política (la usa). Sin los tres, no hay efecto.

## Fuera de alcance de estos hitos
Convenios, subvenciones, formularios, prácticos, estadísticas, predicción, cálculo de plazos, audio/vídeo, TEDH/ONU/CIJ (se reservan conectores desactivados). El hito 5 (piloto) queda como conjunto de evaluación y guion, sin umbrales logrados.

## Qué no se ha verificado ni se promete
Derechos de reutilización de CENDOJ, DGT, TEAC y EUR-Lex; alta en EUR-Lex; calidad jurídica de las respuestas (exige revisión profesional); latencias con corpus real. Cada conector registra lo verificado frente al proveedor y lo probado solo con fixtures.
