# Plan: tareas iguales en la web y en la app, y rediseño de las pantallas de la app

Fecha: 2026-10-26. Contexto: la API (`/api/v1/tareas-outlook…`) ya cubre casi todo lo que hace la web; lo que falta está en la **interfaz de la app**.
El modelo de datos es el mismo (`tareas_outlook`), así que «corresponderse» es sobre todo una cuestión de **mismas vistas, mismos filtros, mismas acciones y mismas palabras**.

## 1. Qué tiene la web y qué tiene la app hoy

| Área | Web | App hoy | Hueco |
|---|---|---|---|
| Vistas | Mi día · Lista · Tablero · Calendario · Carga · Informes | Lista + «Hoy» (bandeja general, no es «Mi día») + calendario antiguo | **Mi día** (vencidas / hoy / en progreso / asignadas / compartidas), **Tablero**, calendario nuevo |
| Filtros de la lista | ámbito (mías, asignadas, compartidas, todas), estado, prioridad, categoría, proyecto, cliente, asignada a, texto, «ver completadas», **vistas guardadas** | ámbito, estado, texto | prioridad, categoría, proyecto, cliente, persona, completadas, vistas guardadas |
| Alta | texto libre: «viernes 10h pedir extractos @luis !alta #IVA» (`app/quickadd.py`) + formulario completo | asunto + fecha | **mismo texto libre**; formulario con prioridad, proyecto, cliente, asignar |
| Fila de tarea | estado, prioridad, vencimiento, cliente, proyecto, subtareas, comentarios, cronómetro, «espera a…», solo lectura, compartida | asunto, fecha, estado | indicadores y cronómetro |
| Ficha | descripción, subtareas, checklist, comentarios, adjuntos, **dependencias, recordatorios, compartir/asignar, tiempo y cronómetro, revisión, clientes vinculados, visible para el cliente, conversaciones con el cliente, actividad, proyecto/sección, estimación** | subtareas, checklist, comentarios, adjuntos, bloqueo | todo lo resaltado |
| Acciones masivas | marcar varias → completar, estado, prioridad, vencimiento, asignar, proyecto, sección (`/tareas-outlook/lote`) | no hay | selección múltiple |
| Papelera | eliminar → papelera → restaurar → eliminar definitivamente | no hay | eliminar y restaurar |
| Plantillas, recurrentes, reglas de vencimiento, automatizaciones | sí | no | solo consulta y activar/desactivar (no editor completo) |
| Sin conexión | — | cola de escrituras + caché de lectura (hecho) | ampliar a las nuevas acciones |
| «Deshacer» | solo «restaurar» de la papelera | no | **esta fase** |

## 2. Reglas para que se correspondan (se cumplen en cada fase)

1. **Mismos nombres**: «Mi día», «Lista», «Tablero», «Calendario», «Carga», «Vencidas», «Vencen hoy», «En progreso», «Asignadas a mí», «Compartidas conmigo». Los textos salen de las mismas cadenas (ARB ↔ `messages.pot`).
2. **Mismas reglas**: la app no replica reglas de negocio; las aplica el servidor (bloqueo por dependencias, subtareas abiertas, revisión pendiente, permisos). La app muestra el motivo que devuelve la API.
3. **Un endpoint por vista**: si la web calcula algo en el servidor (Mi día, tablero, carga), la app lo pide a la API en una llamada — no lo reconstruye. Falta `GET /tareas-outlook/mi-dia` (hoy solo existe `db.tareas_para_hoy` en la web) → se añade a la API.
4. **Una prueba de paridad**: `tests/test_paridad_tareas_app.py` compara, para un mismo usuario con datos sembrados, lo que devuelven la pantalla web y el endpoint de la API (mismas tareas, mismo orden, mismas secciones). Si alguien cambia la web y no la API, falla.
5. **Cada acción nueva** nace con: operación en el SDK generado, cola sin conexión si procede, «Deshacer» si es reversible, y test.

## 3. Fases

**Fase 0 — «Deshacer» (en curso).**
Completar / cambiar de estado, desde la lista y desde la ficha: aviso «Tarea completada · Deshacer» (6 s). Si el cambio aún estaba en la cola sin enviar, se retira de la cola; si ya se envió, se vuelve al estado anterior con la versión actual (si alguien más la tocó, se avisa en vez de pisar).
Después: eliminar (papelera) con «Deshacer» = `POST /tareas-outlook/{id}/restaurar`.

**Fase 1 — La lista igual que la web.**
Filtros completos (prioridad, categoría, proyecto, cliente, persona, completadas), vistas guardadas (`/tareas-outlook/vistas`), alta con texto libre (el servidor interpreta el texto: se añade `texto_libre` a `POST /tareas-outlook` reutilizando `quickadd.py`), filas con los mismos indicadores, selección múltiple con acciones masivas (`/lote`).

**Fase 2 — Mi día y Tablero.**
Pantalla «Mi día» (endpoint nuevo `GET /tareas-outlook/mi-dia`, mismas 5 secciones que la web), y «Tablero» por estado (`/tareas-outlook/tablero`) con mover entre columnas. «Hoy» pasa a ser el resumen de todos los módulos y enlaza a «Mi día».

**Fase 3 — La ficha completa.**
Asignar y compartir, dependencias, recordatorios, cronómetro y tiempo, proyecto/sección/estimación, clientes vinculados, revisión (pedir/resolver), actividad. Cada bloque plegable.

**Fase 4 — Calendario y Carga.**
Calendario de tareas con vencimientos (mes/semana), y «Carga» para quien dirige el despacho (`/tareas-outlook/carga`).

**Fase 5 — Rediseño visual de toda la app** (en paralelo a las fases 1–4, pantalla por pantalla):
- Navegación inferior: Inicio · Tareas · Correo · Fichaje · Más (ya existe); dentro de Tareas, pestañas superiores Mi día · Lista · Tablero · Calendario (como el subnav de la web).
- Tarjetas con jerarquía clara (título, metadatos en chips, acción principal a un toque), espaciado de 8/12/16, tipografía y colores de los tokens generados desde `style.css` (ya hechos) — y **el color de acento elegido por la persona** (hoy solo en la web) llevado a la app.
- Estados vacíos, esqueletos de carga y errores con el mismo componente en todas las pantallas.
- Gestos: deslizar para completar / posponer (con «Deshacer»), mantener pulsado para seleccionar.
- Modo oscuro y accesibilidad (tamaños de letra grandes, contraste ≥ 4,5:1, lector de pantalla).
- Revisión pantalla por pantalla de Correo, Fichaje, Asistente y Ajustes con el mismo criterio (fase posterior, ya listada en el plan de la app).

## 4. Orden y criterio de «hecho»

Cada fase se entrega con tests (Dart y, si toca la API, Python), commit y push. Una fase está hecha cuando la prueba de paridad correspondiente pasa y la pantalla se ha mirado en iPhone.
Dependencias de servidor: `GET /tareas-outlook/mi-dia` y `texto_libre` en el alta (los dos son aditivos y no tocan el esquema; el esquema sigue congelado hasta el 2026-10-26 12:34).
