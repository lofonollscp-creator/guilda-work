# Guilda Work — Plan de implementación CRM + tareas (Fase 0)

Documento de la Fase 0 de `GUILDA_WORK_IMPLEMENTATION_SPEC.md`. Resume lo que **ya existe**, lo que **falta de verdad**, las decisiones de arquitectura y el reparto por fases. No hay cambios de producción en esta fase.

Fecha de la auditoría: 20 de octubre de 2026. Fuente: código de `/home/guilda/guilda-work` (Flask + SQLite, un solo fichero `data/registro.db`) y esquema real de la base leído en solo lectura.

## 1. Conclusión en breve

La especificación describe un producto que Guilda Work **ya cubre en su mayor parte**. No hay que construir un CRM ni un gestor de tareas nuevos: hay que **cerrar huecos concretos** sobre los que existen. Reconstruir sería duplicar conceptos, que es justo lo que la especificación prohíbe (§0.2 y §0.7).

Huecos reales del P0 (el resto del documento los desarrolla):

1. **Concurrencia optimista en tareas** (`version` y respuesta 409): no existe. Sí existe en `clientes_fiscales.version`.
2. **Bloqueo con motivo**: el estado `esperando` existe, pero no guarda por qué está bloqueada la tarea.
3. **Estado «en revisión»**: no existe, y añadirlo obliga a reconstruir `tareas_outlook` por su `CHECK` (migración destructiva → requiere aprobación).
4. **Varios clientes por tarea con uno principal**: la tarea solo guarda un `cliente_fiscal_id`.
5. **Pestaña Tareas del cliente sin contadores** de abiertas/vencidas/completadas ni filtros.
6. **Tareas sin cliente ni cuenta de «vencida» derivada de forma única**: el cálculo de vencidas está repartido por varias consultas.
7. **Sin `GET /api/v1/clients/{id}/tasks`** ni `POST /api/v1/tasks/{id}/transitions` con la convención de la especificación (existe la API en `/api/v1/tareas*` y `/tareas-outlook*`).

## 2. Arquitectura actual (lo que hay que respetar)

| Capa | Realidad |
|---|---|
| Servidor | Flask, blueprints por área (`app/rutas_*.py`), lógica en `app/db_*.py` y módulos propios. Servicios `guilda-work`, `guilda-backoffice` y MCP. |
| Base de datos | SQLite, pool de conexiones por hilo (`db.get_connection()`), migraciones **aditivas** en el arranque (`CREATE TABLE IF NOT EXISTS` y `ALTER TABLE ... ADD COLUMN`). Sin motor de migraciones externo. |
| Tenancy | Columna `tenant_id` en las tablas de despacho. **`tareas_outlook` no tiene `tenant_id`**: el aislamiento va por `usuario_id` → tenant del usuario (`_companero_del_tenant`, `rol_en_tarea`). |
| Roles | Dueño y colaborador/observador por tarea (`tareas_participantes`); roles de despacho en `usuarios`; backoffice aparte. Permisos en `db_tareas.puede_editar_tarea`. |
| Auditoría | `app/auditoria.py` (`auditoria_eventos`, solo de anexado, con disparadores) y `tarea_actividad` para el historial de la tarea. |
| API | `/api/v1/*` con tokens por área, catálogo OpenAPI en `app/openapi_catalogo.py`, herramientas MCP y del asistente de IA en `mcp_tools/` y `app/ia_herramientas.py`. |
| Interfaz | Plantillas Jinja con sistema de diseño en `app/templates/_ds/componentes.html`, i18n con Babel (es/ca/en/fr). Un test vigila que no haya HTML «de fábrica». |
| Pruebas | 239 ficheros en `tests/`, pytest, siempre sobre copia aislada del repositorio. |

## 3. Correspondencia con la especificación

| Especificación | Equivalente existente | Estado |
|---|---|---|
| `clients` (§3.1) | `clientes` (núcleo) + `clientes_fiscales` (gestión fiscal), unidos por `clientes_fiscales.cliente_id`; NIF normalizado y duplicados con autorización (`nif_normalizado`, `nif_duplicado_autorizado`) | **Existe** |
| `contacts` | `cliente_contactos` (principal, rol, email, teléfono) y `contactos` | **Existe** |
| `services`, `client_services` | `concesiones_cliente`, `concesion_servicio`, modelos fiscales por cliente | Parcial; fuera de P0 |
| `projects` | Proyectos (`app/db_proyectos.py`, secciones, miembros, plantillas, tablero, calendario) | **Existe** |
| `case_files` | `expedientes` (+ `expediente_control`, checklist, eventos, miembros) | **Existe** |
| `tasks` | `tareas_outlook` (asunto, cuerpo, estado, prioridad, fechas, asignada_a, cliente_fiscal_id, seccion_id, tarea_recurrente_id…) | **Existe**, con huecos 1-4 |
| `task_client_links` | Solo `cliente_fiscal_id` (un cliente) | **Falta** (hueco 4) |
| `task_dependencies` | `tareas_dependencias` (PK compuesta, con comprobación de ciclos en la ruta) | **Existe** |
| `task_comments` | `tarea_comentarios` (con menciones) | **Existe** |
| `task_attachments` | Adjuntos de notas y documentos de despacho; sin adjuntos propios de tarea | Fase 3 |
| `task_time_entries` | `partes_tiempo` + cronómetro de tarea | **Existe** |
| `task_activity` | `tarea_actividad` + `auditoria_eventos` | **Existe** |
| Plantillas y recurrencia | `plantillas_tareas`, `tareas_recurrentes`, `tareas_por_vencimiento` | **Existe** |
| Vistas guardadas | `tareas_vistas` | **Existe** |
| Notificaciones | `notificaciones` + recordatorios (`tarea_recordatorios`) + correo | **Existe** |
| Certificados | `certificados` + avisos, evaluaciones, renovaciones y vínculos | **Existe** |
| Panel personal y de equipo | Hoy, Mi día, carga de equipo, tablero, calendario | **Existe** |
| Reglas de automatización | `tareas_por_vencimiento` (tareas desde vencimientos) y ejecución de flujos externos por MCP; sin motor propio de reglas | Parcial; Fase 4 |
| Informes y analítica | Panel fiscal, estadísticas, Metabase | Parcial; Fase 5 |

## 4. Decisiones de arquitectura

1. **Se extiende `tareas_outlook`; no se crea una tabla `tasks` paralela.** Los nombres en español y las rutas existentes se conservan; la API de la especificación se ofrece como alias bajo `/api/v1/` solo donde aporta algo (transiciones, tareas de un cliente).
2. **Migraciones solo aditivas** en P0: columnas nuevas con valor por defecto y tablas nuevas. Nada de reconstruir tablas sin aprobación (§0.4).
3. **Aislamiento**: la tabla nueva de vínculos lleva `tenant_id`, y cada alta valida que tarea y cliente pertenecen al mismo despacho. Para `tareas_outlook` se mantiene el criterio actual (por usuario → tenant) y se añade un test de aislamiento cruzado.
4. **Concurrencia optimista** con `tareas_outlook.version` (entero, +1 en cada escritura). Los endpoints aceptan `version` (o `If-Match`); si no coincide, 409 con el estado actual. **Compatibilidad**: si el cliente no manda versión, se comporta como hasta ahora (la app móvil y las integraciones existentes no se rompen).
5. **«Vencida» sigue siendo derivada**, nunca un estado guardado. Se centraliza en una función pura con tests.
6. **Bloqueo**: `esperando` se presenta como «Bloqueada» solo si lleva motivo; el motivo se guarda en la columna nueva `motivo_bloqueo`.
7. **Reutilización de interfaz**: componentes `_ds`, pestaña Tareas de la ficha del cliente, listados y tableros actuales. Sin pantallas nuevas salvo lo imprescindible.
8. **Cada paso es desplegable**: tests en verde, `HOSTING.md`, ayuda y traducciones al día.

## 5. Fases

**Fase 1 — Dominio y API del P0 (ahora)**

- 1a. `version` + 409 en tareas (columna aditiva, `UPDATE ... WHERE version = ?`), tests de concurrencia.
- 1b. `motivo_bloqueo` obligatorio al poner `esperando` desde la API de transiciones; se limpia al salir.
- 1c. `tarea_clientes` (tenant_id, tarea_id, cliente_fiscal_id, principal; único por par; **un solo principal por tarea** con índice parcial). Sincronizada con `cliente_fiscal_id` para no romper lo existente.
- 1d. Función pura `esta_vencida()` y contadores abiertas/vencidas/completadas por cliente.
- 1e. API: `GET /api/v1/fiscal/clientes/<id>/tareas`, `POST /api/v1/tareas-outlook/<id>/transiciones`, `GET/PUT /api/v1/tareas-outlook/<id>/clientes` y entrada en OpenAPI. **Hecho.** Las herramientas MCP y del asistente de IA equivalentes se aplazan al siguiente incremento: obligan a tocar `mcp_tools/__init__.py`, `herramientas_grupos.py` e `ia_herramientas.py`, que tienen cambios sin commitear de la otra sesión.

**Fase 2 — Interfaz**

- Contadores y filtros en la pestaña Tareas del cliente; selector de varios clientes en el formulario de tarea; aviso de conflicto 409 con recarga segura; accesibilidad y móvil.

**Fase 3 — Trabajo avanzado**: adjuntos de tarea, subtareas con reglas de cierre explícitas, calendario unificado con filtros compartidos, plantillas y recurrencia con ocurrencias deterministas (ya hay base).

**Fase 4 — Cumplimiento**: reglas de automatización con cola, idempotencia y reintentos; avisos de caducidad de certificados con tareas de renovación idempotentes (sobre `certificados_avisos`/`renovaciones`).

**Fase 5 — Analítica y portal**: informes con ventanas y denominadores explícitos; aprobaciones; colaboración del cliente.

## 6. Migraciones y reversión

| Cambio | Tipo | Reversión |
|---|---|---|
| `tareas_outlook.version INTEGER NOT NULL DEFAULT 1` | `ADD COLUMN`, aditiva | La columna se ignora; no hace falta quitarla |
| `tareas_outlook.motivo_bloqueo TEXT` | `ADD COLUMN`, aditiva | Ídem |
| `tarea_clientes` | Tabla e índices nuevos | `DROP TABLE tarea_clientes` (sin dependientes) |
| Estado `en_revision` | **Reconstrucción de `tareas_outlook`** por el `CHECK` | **Pendiente de aprobación**; ver §7 |

Antes de arrancar con cambios de esquema en producción: copia de `data/registro.db` (ya hay copias con Restic). Las migraciones se aplican al reiniciar el servicio y son idempotentes.

## 7. Riesgos e incertidumbres

- **Estado «en revisión»**: SQLite no permite modificar un `CHECK`; hay que recrear la tabla con sus claves foráneas (comentarios, checklist, dependencias, participantes, recordatorios, actividad). Es factible y se hace en una transacción, pero es una migración destructiva si sale mal. Alternativa sin riesgo: reutilizar `esperando` + `motivo_bloqueo` y modelar la revisión con el `revisor_id` de `expediente_control`, sin estado nuevo en la tarea.
- **Árbol de trabajo compartido**: hay cambios sin commitear de otra sesión en `db.py`, `main.py`, `certificados.py`, `panel_fiscal.py`, etc. Los cambios de este plan van en módulos nuevos y en `db_tareas.py` (sin cambios pendientes), y no tocan esos ficheros sin avisar.
- `tareas_outlook` sin `tenant_id`: un día convendría añadirlo y rellenarlo (copia desde el usuario), pero no es necesario para el P0 y ampliaría el alcance.
- La especificación habla de UUID y `organization_id`; aquí se mantienen enteros y `tenant_id` (la propia especificación da prioridad a las convenciones existentes).

## 8. Criterio de «P0 terminado» aplicado a este repositorio

Se da por cumplido cuando: (a) se gestionan clientes y contactos (ya), (b) se crean y asignan tareas vinculadas a uno o varios clientes (Fase 1c), (c) la ficha del cliente y las listas muestran lo mismo (Fase 2), (d) vencidas y abiertas cuadran en todas las vistas (1d), (e) hay 409 ante ediciones simultáneas (1a), y (f) los tests de aislamiento entre despachos y de permisos pasan, sin romper ningún flujo existente.
