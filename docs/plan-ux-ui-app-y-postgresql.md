# Plan de UX/UI de la app y de su uso de PostgreSQL

> **Estado:** borrador para decisión · **Fecha:** 2026-10-24 (segunda sesión de planificación) · **Complementa** a [`plan-app-movil.md`](plan-app-movil.md) (arquitectura, olas y contrato); aquí se profundiza en **experiencia de uso** (§A) y en **cómo la app se apoya en la base de datos PostgreSQL de toda la web** (§B).
> **Qué es nuevo respecto a la primera sesión:** (1) la app Flutter **se ha compilado y recorrido de verdad** (build web de una copia con una API de demostración aislada), así que los hallazgos de UX son de pantallas reales, no solo de código; (2) se **midió la API sobre PostgreSQL + Citus** con datos sintéticos y se comparó con SQLite; (3) se **reprodujo un fallo del cursor de sincronización** que afecta al modo sin conexión.
> **Solo planificación:** no se ha cambiado ningún código del producto. Los scripts de medida están en `docs/anexos-app-movil/`; capturas en `docs/ux-app-movil-real/`.

---

## Resumen en una página

**Lo que dicen las medidas**

| Hallazgo | Dato | Por qué importa a la experiencia |
|---|---|---|
| **🔴 Con peticiones concurrentes la API falla con «distributed deadlock» de Citus** (reproducido) | Cada petición escribe en **tablas de referencia** (`tokens_api`, `tokens_api_uso`; las POST, `api_idempotencia`; el MCP, `mcp_uso`). Con **4 clientes a la vez: 7 % de errores 500; con 8: 47 %; con 12: 65 %**, y el rendimiento cae de 68 a 16 peticiones/s. **Sin esas dos escrituras: 0 errores y 163–191 peticiones/s** | Es exactamente lo que hará la app: abrir «Hoy» lanza 3–6 llamadas en paralelo y habrá decenas de personas a la vez. **Hoy no ha ocurrido en producción** (0 interbloqueos en 6 h) porque casi nadie usa la API en paralelo; ocurrirá al lanzar la app o con varios clientes MCP simultáneos |
| **Cada petición a la API cuesta 7–9 sentencias SQL y ~15–18 ms en PostgreSQL** (en SQLite, ~1 ms) incluso la más trivial (`/auth/me`: 9 sentencias, 18 ms) | 25 endpoints medidos; **2 de las 7 sentencias de base son escrituras** (`UPDATE tokens_api…ultimo_uso`, `INSERT … tokens_api_uso`) y **3–4 son la misma lectura de `usuarios`** | Una pantalla «Hoy» con 6 llamadas gasta ~100 ms solo en sobrecarga. Cada milisegundo se nota en un móvil con 4G |
| **El cursor de `/sync` pierde cambios cuando hay transacciones concurrentes** (reproducido) | Transacción A empieza antes y confirma después que B: el cliente que ya leyó B **no vuelve a ver A** | Es la base del modo sin conexión: una tarea creada por un compañero puede **no llegar nunca** al móvil |
| **La primera sincronización hace 130 sentencias y tarda 750 ms** (`/sync?cursor=0`, 100 tareas + 20 notas) | N+1: una consulta por entidad | Primera apertura lenta y cara en datos |
| **Listados sin paginar con cargas enormes**: `fiscal/vencimientos` **524 KB**, `correo/mensajes` 174 KB, `tablero` 85 KB, `tareas` 42 KB (50 filas) | Medido con 60 clientes/3.000 vencimientos | En 4G, medio megabyte por pantalla es 1–3 s y batería |

**Lo que dicen las pantallas reales** (app Flutter compilada y recorrida; capturas en `docs/ux-app-movil-real/`)

- **No existe «Hoy»**: la pantalla inicial es la de *proyectos* antiguos («0 en curso», «Crea tu primer proyecto»). Lo que vence hoy no aparece en ninguna parte de la app.
- **El botón «+» flotante tapa contenido** (la última tarjeta de accesos, el chevron de «Nóminas»).
- **Tareas**: no se ve el estado (solo la prioridad), las vencidas no se distinguen, fechas ISO («Vence 2026-10-21»), la papelera por fila **borra sin confirmar ni deshacer**, las pestañas se cortan («T…»).
- **Correo**: el remitente sale como `Nombre <correo@…>` truncado, sin extracto, sin diferencia visible entre leído y no leído salvo el negrita, fechas ISO.
- **Asistente**: vacío sin sugerencias; micrófono y enviar son dos círculos verdes del mismo peso; tres iconos sin texto en la barra.
- **Tipografía y forma** son las de Material por defecto (Roboto, radio 8 px): la web usa Manrope y radio 12 px.

**Qué se propone** (detalle en §A y §B)

1. **UX:** una app «Hoy-primero» con barra inferior (Hoy · Tareas · Correo · Fichaje · Más), acciones que se resuelven en un toque (completar, «Lo llevo», aprobar), estados siempre visibles con icono + texto, fechas humanas, **deshacer en lugar de confirmar**, esqueletos en lugar de ruedas, y un sistema de diseño generado de la web. Objetivos de tiempo por tarea (fichar ≤ 3 s, completar tarea ≤ 2 toques, acusar un aviso en 1 toque desde la notificación).
2. **Datos (PostgreSQL):** **primero, quitar de la ruta caliente las escrituras en tablas de referencia que provocan interbloqueos (PG-00/PG-04)**; después bajar la sobrecarga de la API de 7 a ≤ 2 sentencias por petición; **un cursor de cambios seguro** (basado en transacciones, no en `id`); **`GET /hoy` en un solo viaje a la base**; **paginación por cursor (keyset)** con índices parciales; **búsqueda con `tsvector`+`pg_trgm`** en todo; **tiempo real** con `LISTEN/NOTIFY` hacia un canal SSE para la app en primer plano; todo medido con `pg_stat_statements` etiquetado por endpoint y un **panel «API móvil»** en Grafana.
3. **Esfuerzo:** §A ≈ 9 persona-semanas (se solapa con las olas del plan anterior, no se suma entera); §B ≈ 6 persona-semanas de servidor, **la mitad de las cuales debe hacerse antes de la Ola 1**.

---

## A. UX/UI de la app

### A.1 Lo que se ve hoy: pantallas reales

Recorrido hecho el 24-oct-2026 con la app compilada para web en un viewport de 390×844 y una API de demostración aislada con datos sintéticos (despacho «Gestoría Pla»). Capturas: [`docs/ux-app-movil-real/`](ux-app-movil-real/).

| ID | Pantalla | Sev. | Hallazgo (lo que se ve) | Consecuencia | Propuesta |
|---|---|:-:|---|---|---|
| **M-01** | Inicio | Alta | **No hay «Hoy».** El bloque principal son «Primeros pasos», contadores del cronómetro antiguo («0 en curso») y una nota rápida; las tareas, los vencimientos y los avisos no están | La persona abre la app y no sabe qué le toca | «Hoy» como primera pantalla (Ola 1) |
| **M-02** | Inicio | Media | El **botón «+» flotante tapa** la tarjeta «Asistente IA» y el chevron del último proyecto | Contenido inalcanzable o ilegible | Relleno inferior de la lista = alto del botón + margen; en «Hoy» el «+» pasa a la barra inferior |
| **M-03** | Inicio | Media | Los **proyectos** (con su color) aparecen **al final**, tras 8 accesos, y el botón «+» solo sirve para crear uno; «Primeros pasos» ocupa lo más alto aunque ya esté casi completo | Jerarquía invertida: lo secundario arriba | Mover a «Más»; onboarding como tarjeta descartable con progreso |
| **M-04** | Tareas | Alta | **No se ve el estado** (no iniciada, en curso, esperando, aplazada…): solo prioridad. La API tiene 6 estados y motivo de bloqueo | No se sabe qué está parado ni por qué | Icono + texto de estado en cada fila y motivo de bloqueo en una línea |
| **M-05** | Tareas | Alta | **Las vencidas no se distinguen** (hoy es 24; «Vence 2026-10-21» se ve igual que una futura) y las fechas son **ISO** | Lo urgente no salta a la vista | Fecha relativa («hace 3 d», «mañana», «vie 28 oct») y color + icono de alerta si venció |
| **M-06** | Tareas | Alta | **Papelera por fila sin confirmación ni deshacer** (icono de borrar en cada línea, a 8 px del círculo de completar) | Pérdida accidental de datos (toque equivocado) | Quitar de la fila; acción en menú «⋯» / gesto lateral con **«Deshacer»** durante 6 s |
| **M-07** | Tareas | Media | Pestañas **«Mías · Asignadas · Compartidas · T…»** cortadas; ámbito solo con pestañas; sin filtros por estado/cliente/fecha | No se llega a «Todas» | `SegmentedButton` + hoja de filtros con *chips*; vistas guardadas (la API ya las tiene) |
| **M-08** | Tareas | Media | Alta de tarea en línea («Nueva tarea… · Normal ▾ · + Añadir») sin cliente, fecha ni voz | Se crean tareas sin contexto y luego hay que editar | Alta de una línea + «Más opciones» (cliente, fecha, voz, adjunto) |
| **M-09** | Correo | Media | Remitente como **`Talleres Soler <info@soler.example…`** truncado; sin extracto; el icono de sobre es **igual** para leído y no leído; fechas ISO; dos desplegables + buscador + casilla = 200 px antes del primer mensaje | Lectura lenta, ruido | Nombre visible (no el correo), extracto de una línea, punto azul de no leído, fecha corta («14:05», «ayer», «21 oct»), cuenta/carpeta en un solo selector |
| **M-10** | Correo | Media | Sin gestos (archivar, marcar, posponer) ni lote | Cada acción es 3 toques | Deslizar: archivar/posponer; mantener pulsado: seleccionar |
| **M-11** | Fichaje | Media | Primer uso: pantalla casi vacía con «rellena tu nombre y DNI/NIE» y un botón que **lleva a otra pantalla**; en la barra, **tres iconos sin texto** (historial, vacaciones, ficha) | No se entiende qué hace cada icono | Formulario en la misma tarjeta; iconos con etiqueta o menú «⋯» |
| **M-12** | Asistente | Media | Vacío sin **sugerencias** (la web tiene atajos «Resumen de mi día», «¿Qué vence esta semana?»); **micrófono y enviar** son dos círculos del mismo color y peso; tres iconos de barra sin texto (voz en directo, ajustes, vaciar) | No se sabe qué pedir; riesgo de pulsar «vaciar» | Atajos como *chips*; un solo botón primario (enviar) y micrófono secundario; «vaciar» con confirmación en menú |
| **M-13** | Herramientas | Baja | Más de la mitad de las tarjetas dicen **«Aún no disponible»** en gris | Ruido, sensación de producto incompleto | Mostrar solo las disponibles; el resto, plegado en «Próximamente» o fuera |
| **M-14** | Global | Media | **Tipografía Roboto y radio 8 px** frente a Manrope y 12 px de la web; superficies planas; sin *skeleton*, sin transiciones | La app no «se parece» a Guilda | Tokens generados de la web (plan §4 ADR-M5) |
| **M-15** | Global | Alta | **Sin navegación persistente**: todo es *push*; para ir de Tareas a Correo hay que volver al inicio. Ajustes solo desde el engranaje del inicio | Muchos toques por cambio de contexto | Barra inferior (plan §4 ADR-M3) |
| **M-16** | Global | Media | **Errores en crudo** (`Error`, `Exception`…) en la consola y 80 sitios que muestran el texto de la excepción; sin estado «sin conexión» | Mensajes incomprensibles | Catálogo de errores por categoría (plan §4 ADR-M7) |

**Nota de método.** La compilación a web **no** es la app que se instala (hay diferencias de plataforma: sin cola sqflite, sin push, `flutter_secure_storage` simulado), pero el árbol de widgets, los textos, el espaciado y la jerarquía son los mismos. Los hallazgos de esta tabla son de composición, no de plataforma. Las tarjetas de «Herramientas» salen sin logos porque la demostración no sirve los estáticos de la web; no se cuenta como defecto.

### A.2 Principios de experiencia (para decidir cada pantalla)

1. **Lo urgente primero y sin buscarlo.** La primera pantalla responde a «¿qué me toca ahora?»; nada que dependa de entrar en un módulo.
2. **Un toque para lo frecuente.** Completar, acusar, aprobar, fichar, contestar: desde la lista o la notificación, sin abrir la ficha.
3. **Reversible antes que confirmable.** Confirmación solo para lo irreversible (enviar al cliente, borrar definitivamente); para lo demás, **deshacer** de 6 s. Cada diálogo evitado es un toque menos.
4. **Estado siempre legible.** Icono + texto + color (nunca solo color) para estado, prioridad y urgencia; los mismos tokens en web y móvil.
5. **Honesta sin conexión.** Se ve qué es local, qué está pendiente de enviar y qué falló; nunca un spinner infinito ni un error técnico.
6. **Tranquila por defecto.** Pocas notificaciones, agrupadas; el resto, en la bandeja. «No molestar» respetado.
7. **Una mano.** Acciones principales en el tercio inferior; objetivos ≥ 48 dp; nada esencial en la esquina superior.
8. **Lenguaje de despacho, no de software.** «Obligación», «cliente», «presentar», no «entidad», «registro», «payload» (ver A.7).
9. **Rápida de verdad.** Esqueleto en < 100 ms, datos de caché al instante, actualización en segundo plano; presupuestos en §B.

### A.3 Personas y trabajos a resolver

| Persona | Qué hace con el móvil (entre otras cosas) | Tareas clave y meta de tiempo |
|---|---|---|
| **Gestor/a fiscal** | Lleva clientes y obligaciones; recibe avisos; atiende al cliente en la calle | Ver qué vence hoy ≤ 1 toque desde abrir · Marcar presentado con justificante (foto) ≤ 30 s · Contestar un mensaje del cliente ≤ 20 s |
| **Dirección del despacho** | Supervisa, aprueba, decide | Aprobar ausencia desde la notificación = 1 toque · Ver el panel fiscal (vencidas, en riesgo) ≤ 2 toques · Aceptar/rechazar traspasos |
| **Personal administrativo/laboral** | Ficha, pide ausencias, nóminas, tareas | **Fichar ≤ 3 s** desde frío; ≤ 1 toque con el widget · Pedir ausencia ≤ 4 toques |
| **Abogado/a** | Vistas, plazos, expedientes, provisiones | Ver los señalamientos de los próximos 7 días ≤ 2 toques · Comprobar un conflicto ≤ 20 s |
| **Agente inmobiliario** | Visitas, demandas, propietarios | **Visitas de hoy con mapa y teléfono ≤ 1 toque** · Anotar resultado de visita ≤ 15 s · Foto de un inmueble a su ficha |
| **Cliente del despacho** | **No usa la app**: usa el portal web (enlace de un solo uso). Se menciona porque un portal instalable (PWA) sería la vía natural y se evalúa aparte | — |

### A.4 Arquitectura de la información y navegación

```
Barra inferior (5 destinos)           Barra superior (contextual)
 ┌───────┬────────┬────────┬─────────┬──────┐   [Despacho ▾]  [🔍]  [🔔 4]
 │  Hoy  │ Tareas │ Correo │ Fichaje │ Más  │   (el selector solo si hay >1 despacho)
 └───────┴────────┴────────┴─────────┴──────┘
```

- **Hoy** — secciones por urgencia (vencido → hoy → próximo), acción rápida por elemento, estado de fichaje arriba, «todo al día» si no hay nada.
- **Tareas** — Lista · Tablero · Calendario (selector superior); filtros en hoja; vistas guardadas.
- **Correo** — una cuenta/carpeta a la vez; buscador arriba; gestos.
- **Fichaje** — un gran botón de estado, jornada, resumen semanal, turnos y ausencias en pestañas.
- **Más** — cuadrícula **por módulos activos** (`/auth/me.modulos`): Clientes, Fiscal, Documentos, Certificados, Comercial, Contabilidad, Abogados, Inmobiliaria, Jurídico, Herramientas, Asistente de IA, Avisos, Papelera, Ajustes. Arriba, **«Tus accesos fijados»**: **reutiliza las preferencias de menú de la cuenta** (`usuario_perfil.menu_prefs`: hasta 6 fijados y los ocultos) que la persona ya configura en la web; hay que exponerlas por API (ampliar S-14).
- **Acción global «+»** (hoja, no botón flotante tapando contenido): Nueva tarea · Nota · Fichar · Foto → (tarea, expediente, factura) · Dictar. Se abre desde el centro de la barra superior en Hoy/Tareas y con pulsación larga en el icono de la app (*App Shortcuts*).
- **Asistente de IA** — accesible desde «Más» y como **botón contextual** («Preguntar sobre esto») en tarea, cliente y obligación; no ocupa un destino de la barra.
- **Búsqueda global** — icono superior en todas las pantallas; resultados agrupados (Tareas, Notas, Correo, Clientes) y recientes.

Reglas de navegación: la barra **no desaparece** al entrar en un detalle de su sección; cada destino conserva su pila (volver al destino no reinicia); el botón «atrás» de Android y el gesto de iOS hacen lo esperado; un enlace de notificación **reconstruye la pila** (Hoy → Tarea) para que «atrás» no cierre la app.

### A.5 Especificaciones de pantalla (las que más pesan)

#### Hoy

| Aspecto | Especificación |
|---|---|
| Objetivo | Responder «¿qué me toca?» en un vistazo y permitir resolver sin entrar |
| Estructura | Saludo corto + recuento («5 cosas · 2 urgentes») · tarjeta de **fichaje** (estado + botón) · secciones colapsables por urgencia, cada una con título, recuento y elementos (máx. 5 + «Ver todo») · pie «Actualizado hace 2 min» |
| Elemento | Casilla/acción rápida a la izquierda · título (1 línea) · detalle (1 línea, p. ej. cliente) · etiqueta de fecha relativa y color de urgencia · chevron |
| Acciones | Tocar = abrir · casilla = completar (tareas) · **deslizar derecha = completar/«Lo llevo»**, **izquierda = posponer** · mantener = menú |
| Estados | Cargando (esqueleto de 3 tarjetas) · vacío («Todo al día. Disfruta de la tarde», con acción «Ver mi semana») · sin conexión (datos de caché + franja «Sin conexión · actualizado a las 09:14») · error (franja con «Reintentar») |
| Datos | **Una** llamada `GET /hoy`; caché 2 min; refresco al volver a primer plano; evento en tiempo real (B.4) |
| Medida | Tiempo hasta contenido útil ≤ 1,5 s en frío con caché; ≤ 3 llamadas de red |

#### Lista de tareas

| Aspecto | Especificación |
|---|---|
| Estructura | Selector de ámbito (*segmented*: Mías · Asignadas · Todas) + botón de filtros con contador · **alta de una línea** fija abajo (asunto + «+» + «⋯» para cliente/fecha/voz) · lista paginada (infinita) |
| Fila | Casilla · asunto (2 líneas máx.) · **estado como icono + texto** · cliente · **fecha relativa** (roja si vencida) · prioridad solo si es alta · indicadores (subtareas 2/4, adjuntos, comentarios, bloqueada) |
| Gestos | Derecha: completar · Izquierda: posponer/más · Mantener: selección múltiple (lote) |
| Filtros (hoja) | Estado · prioridad · cliente · fecha · vistas guardadas (propias/compartidas) |
| Estados | Vacío filtrado («Nada con estos filtros» + «Quitar filtros») · vacío total («Sin tareas. Crea la primera») · cargando (esqueleto de 6 filas) |
| Medida | Completar una tarea ≤ 2 toques; scroll sin saltos con 500 tareas |

#### Detalle de tarea

Cabecera con **estado** (selector con motivo obligatorio para «Esperando»), título editable en el sitio, cliente(s), vencimiento, prioridad; **aviso amarillo de bloqueo** con el motivo; pestañas Detalle · Subtareas (n/m) · Comentarios · Adjuntos · Actividad; compositor fijo abajo (cámara, adjuntar, texto, voz); `409` → hoja «Alguien la ha editado: ver cambios · aplicar igualmente · descartar». Revisión: botones «Aprobar» / «Pedir cambios» solo para el revisor designado.

#### Correo

Lista con avatar de inicial, **nombre** (no el correo), asunto, extracto, hora corta, punto de no leído, marcadores (adjunto, destacado, posponer); buscador con filtros rápidos (*chips*: No leídos · Destacados · Con adjuntos · De clientes); selector único «Cuenta · Carpeta»; gestos (archivar, posponer); lectura con cabecera compacta, **contexto de cliente** (vencimientos y tareas abiertas) y acciones «Crear tarea», «Guardar nota»; redactar con autoguardado y plantillas con variables. Mensajes con cifrado activo y sin clave: estado «protegido» + desbloqueo (plan §13.4).

#### Fichaje

Un **botón central grande** que cambia según estado (Entrar · Pausa · Salir) con el tiempo transcurrido; debajo, jornada de hoy y resumen semanal (anillo de progreso); pestañas Hoy · Turnos · Ausencias · Bolsa. Confirmación **no** necesaria (se puede corregir). Sin conexión: se registra con la hora real y aparece «pendiente de enviar» con reloj. Widget de inicio y acción rápida del icono.

#### Avisos (bandeja) y notificaciones accionables

Agrupados por día; filtros por familia (Fiscal · Tareas · Correo · Equipo); cada aviso con **sus botones** («Lo llevo», «Aprobar/Rechazar», «Completar»); «Marcar todas»; insignia en la campana y en el icono de la app. Misma pieza visual dentro y fuera de la app (plan Apéndice B).

#### Obligación (vencimiento) y ficha de cliente

Obligación: cabecera con modelo, periodo, cliente, **fase** (barra de progreso de fases), indicadores (vencida, en riesgo, bloqueada), acciones primarias contextuales según fase («Marcar presentada», «Pedir documentación», «Adjuntar justificante»), documentos del cliente, conversación. Cliente: tarjeta con llamar/escribir/mapa, pestañas Datos · Obligaciones · Tareas · Documentos · Contactos, con el resumen (`/fiscal/clientes/{id}/resumen`) como primera vista.

#### Asistente de IA

Sugerencias como *chips* al abrir (atajos del usuario y de serie), conversaciones en un cajón lateral, respuesta en *streaming* con indicador, **tarjeta de confirmación** para acciones con campos legibles y «Aprobar/Rechazar» claros, fuentes citadas, micrófono secundario, «Vaciar» en el menú con confirmación, aviso «Puede contener errores» discreto y fijo.

### A.6 Sistema de diseño v2 (especificación)

| Capa | Especificación |
|---|---|
| **Tokens** | Generados desde `style.css` (plan ADR-M5): color (claro/oscuro), radio 12/10/22, sombras, espaciado en escala de 4 dp (4·8·12·16·24·32), tipografía **Manrope** (cuerpo 15–16 sp, títulos 20/24/28, números tabulares en cifras) con *fallback* Inter; densidad «compacta» de la cuenta = −2 dp de relleno vertical |
| **Color semántico** | Estado → color + icono + etiqueta: *No iniciada* (gris, círculo vacío) · *En curso* (azul, flecha) · *Esperando* (ámbar, reloj) · *Aplazada* (gris azulado, calendario) · *Completada* (verde, check) · *Vencida* (rojo, exclamación) · *En revisión* (violeta, ojo). Los tonos `*-text` de la web para texto sobre fondo claro (AA) |
| **Iconografía** | Un único set coherente con la web (la web usa *Lucide*: `list-checks`, `mail`, `clock`…): paquete Flutter de Lucide o SVG propios exportados de `iconos.svg`; 20/24 dp; trazo 1,75 |
| **Componentes** (≈ 30) | Barra superior/inferior · tarjeta · fila de lista (con deslizables) · *chip* de estado/filtro · botón (primario lima, secundario, texto, peligro, icono con zona de 48 dp) · campo de texto/fecha/selector con búsqueda · hoja inferior · diálogo · *snackbar* con deshacer · banner (info/aviso/error/sin conexión) · esqueleto · estado vacío/error · avatar · insignia · segmentado · pestañas · anillo/barra de progreso · selector de despacho · tarjeta de notificación accionable · compositor de comentarios · visor de adjuntos · cámara/escáner |
| **Movimiento** | 120 ms para microinteracciones, 200 ms para transiciones de elemento, 300 ms para cambios de pantalla; curva estándar *easeOutCubic*; **respeta «reducir movimiento»** del sistema; sin parpadeos al refrescar (cambios aplicados con *diff*) |
| **Hápticos** | Ligero al completar/fichar, medio al acusar/aprobar, de error al fallar; desactivables |
| **Superficies** | Claro: fondo `--bg`, tarjetas `--surface` con borde `--border`; «cristal» solo en barras y hojas (cuesta rendimiento); oscuro: fondo casi negro de la marca |
| **Modo oscuro y claro** | Sigue el sistema o la preferencia de la cuenta (`apariencia`), con tema en caliente |
| **Escalado de texto** | Probado a 100 %, 150 % y 200 %: ninguna fila corta información esencial; las filas crecen |
| **Tablet** | A partir de 600 dp: carril de navegación + lista-detalle; márgenes máximos de 720 dp para lectura |

### A.7 Contenido: voz, formatos y glosario

**Voz.** Tuteo, cálida y profesional, frases cortas, verbos de acción («Completar», «Lo llevo»), sin jerga técnica ni tecnicismos de base de datos. Mensajes de error con la fórmula **qué ha pasado + qué puede hacer** («No hemos podido guardar la tarea. Comprueba tu conexión; la guardaremos en cuanto vuelva»).

**Formatos** (una sola función de formato para toda la app, por idioma):

| Dato | Regla |
|---|---|
| Fecha | Relativa hasta 7 días («hoy», «ayer», «mañana», «hace 3 d», «vie 28 oct»); absoluta después («28 oct 2026»); nunca ISO en pantalla |
| Hora | 24 h en es/ca/fr, 12 h en en; «14:05» hoy, «ayer 14:05» |
| Importe | `1.234,56 €` (es), separadores según idioma; céntimos siempre visibles |
| Plurales | ICU en ARB («1 tarea / 3 tareas / ninguna tarea») |
| Longitud | Reservar +30 % para ca/fr; probar con *pseudo-locale* |

**Glosario único** (hoy hay términos mezclados entre web, API, MCP y móvil):

| Concepto | Término de pantalla | Hoy aparece también como | Decisión |
|---|---|---|---|
| Organización del cliente de Guilda | **Despacho** | tenant, gestoría, agencia, oficina | «Despacho» en toda la UI; «Oficina» solo para sucursales |
| Fecha límite fiscal | **Obligación** (y «vencimiento» para la fecha) | vencimiento, obligación, plazo, modelo | «Obligación» = el trabajo (modelo + periodo + cliente); «vence el…» = la fecha; «plazo» queda para plazos procesales/del núcleo |
| Agrupación de tareas | **Proyecto** | categoría, menú (legado) | «Proyecto»; borrar «menú» de textos y claves |
| Persona a la que se lleva el trabajo | **Cliente** | cliente fiscal, tercero | «Cliente» |
| Conversación con el cliente | **Mensajes** | portal, enlace, hilo | «Mensajes con el cliente» |
| Avisos | **Avisos** (bandeja) y «notificación» (del sistema) | alertas, notificaciones | «Avisos» en la app; «Aviso fiscal» solo para los de control fiscal |
| Entradas de «Hoy» | **Pendientes / Hoy** | bandeja única, destacados | «Hoy» |

### A.8 Accesibilidad (plan de cumplimiento WCAG 2.2 AA)

1. **Semántica**: cada control con etiqueta (iconos incluidos), orden de foco lógico, encabezados marcados, estados («seleccionada», «completada») anunciados; *live regions* para avisos de guardado y errores.
2. **Contraste**: ≥ 4,5:1 texto, 3:1 componentes; verificado con las guías de `flutter_test` y con una tabla de pares de tokens (generada en CI).
3. **Objetivos**: ≥ 48 dp con separación; en filas densas, la fila entera es el objetivo.
4. **Texto dinámico** hasta 200 % sin truncar lo esencial.
5. **Movimiento reducido**, **no solo color**, **sin parpadeos** > 3 Hz.
6. **Teclado/switch**: foco visible en tabletas/ChromeOS; acciones de lista accesibles por menú (los gestos nunca son la única vía).
7. **Pruebas**: automáticas por pantalla (3 guías) + guion manual de TalkBack/VoiceOver por ola (tareas: abrir app → Hoy → completar → comentar → adjuntar) + una revisión con una persona usuaria de lector de pantalla antes de publicar.

### A.9 Rendimiento percibido

| Técnica | Dónde | Efecto |
|---|---|---|
| **Caché y luego red** (*stale-while-revalidate*) | Hoy, Tareas, Correo, Avisos | Contenido en < 200 ms |
| **Actualización optimista** | Completar, marcar leído, fichar, acusar | La interfaz responde al instante; si falla, vuelve atrás con aviso |
| **Esqueletos** (no ruedas) | Toda carga > 300 ms | Menos sensación de espera |
| **Precarga** | Al abrir Hoy: detalle de las 3 primeras tareas; al ver un correo: el siguiente | Navegación sin esperas |
| **Imágenes y adjuntos** | Miniaturas del servidor, descarga bajo demanda, caché temporal | Menos datos y batería |
| **Paginación infinita** con 50 elementos por página | Listas | Menos memoria y red |

### A.10 Cómo validamos la experiencia (investigación y medidas)

- **Pruebas de uso** (5 personas por ola, 30 min, guion de tareas con tiempos y errores; **SUS ≥ 80** y **≥ 90 % de tareas completadas sin ayuda**). Reclutamiento: 2 gestores, 1 dirección, 1 persona administrativa, 1 persona de un vertical (abogados/inmobiliaria) de los despachos piloto.
- **Evaluación heurística** (las 10 de Nielsen) por el equipo al cerrar cada ola, con tabla de severidad y registro de **deuda de UX**.
- **Medidas en uso real, sin SDK de terceros** (se calculan en el servidor a partir de la API y de eventos mínimos y anónimos enviados por la propia app): tiempo hasta primera acción, % de acciones resueltas desde notificación, % de fichajes hechos en la app, tasa de error por pantalla, uso de «deshacer», abandono en el alta de tareas.
- **Bucle de comentarios**: botón «Enviar comentarios» (abre un tiquet con versión y pantalla) + revisión semanal en beta.
- **Criterio de salida de cada ola:** sin hallazgos de severidad alta abiertos; SUS y tiempos dentro de meta.

### A.11 Backlog de UX de la app (ordenado)

| ID | Tarea | Ola del plan | Tamaño | Depende de |
|---|---|:-:|:-:|---|
| UXA-01 | Barra inferior + «Hoy» + selector de despacho | 0/1 | L | S-01, S-02 |
| UXA-02 | Tokens, tipografía Manrope, radios y componentes base (estados, esqueletos, banners, hojas) | 0 | L | ADR-M5 |
| UXA-03 | Formato de fechas/horas/importes único y glosario aplicado en ARB (4 idiomas) | 0 | M | — |
| UXA-04 | Fila de tarea con estado, fecha relativa, indicadores y gestos; sin papelera por fila; «Deshacer» | 1 | M | UXA-02 |
| UXA-05 | Filtros en hoja y vistas guardadas; alta de una línea con «Más opciones» | 1 | M | — |
| UXA-06 | Detalle de tarea (estado con motivo, conflicto 409, subtareas, adjuntos, comentarios) | 1 | L | — |
| UXA-07 | Bandeja de avisos y notificaciones accionables | 1 | L | S-05 |
| UXA-08 | Correo: lista con nombre/extracto/no leído, gestos, contexto de cliente | 3 | L | — |
| UXA-09 | Fichaje: botón central, estados, sin conexión, widget y acción rápida | 3 | M | — |
| UXA-10 | Asistente: sugerencias, conversaciones, confirmación clara | 1 | M | — |
| UXA-11 | Cliente y obligación (fases, justificante con cámara) | 2 | L | S-04 |
| UXA-12 | Accesibilidad: pruebas automáticas + guion manual + revisión con usuaria | 0–5 | M | — |
| UXA-13 | Tablet y plegables | 5 | M | — |
| UXA-14 | Pruebas de uso por ola y panel de métricas de experiencia | 1–5 | M | — |
| UXA-15 | Preferencias de menú de la cuenta (accesos fijados/ocultos) en «Más» | 1 | S | S-14 ampliado |

**Esfuerzo UX/UI de la app: ≈ 9 persona-semanas** (diseño + implementación + pruebas), repartidas en las olas del plan anterior (la mayor parte ya está dentro de sus estimaciones; aquí se explicita el diseño y la validación que antes iban implícitos: ≈ 3 pw adicionales de diseño de producto y pruebas de uso).

### A.12 Flujos clave: cómo son hoy y a qué aspiramos

Conteo hecho sobre las pantallas reales recorridas y la lectura del código (toques desde la app ya abierta en el inicio; «—» = no se puede hacer hoy). Los valores «hoy» marcados con ~ son estimaciones; el resto, comprobados.

| Flujo | Hoy | Objetivo | Cómo |
|---|---|---|---|
| Saber qué me toca hoy | — (no existe) | **0 toques** (es la primera pantalla) | Hoy |
| Ver lo vencido de la gestoría | ~3 (Calendario fiscal → Vencimientos → filtrar) | 1 | Sección «Vencido» de Hoy |
| Fichar entrada | 2 (Fichaje → botón) + abrir la app | **1** (widget/acción del icono) o 2 | Botón de Hoy, widget, acceso rápido |
| Crear una tarea con cliente y fecha | ~6 (Tareas → escribir → Añadir → abrir → cliente → fecha → guardar) | 3 | Alta de una línea + «Más opciones» |
| Completar una tarea | 1 (círculo), pero **sin deshacer** y a 8 px del borrar | 1 + «Deshacer» | Gesto lateral o casilla; papelera fuera de la fila |
| Saber por qué una tarea está parada | — (no se ve el motivo) | 0–1 | Estado y motivo en la fila |
| Contestar un correo | ~5 (Correo → mensaje → responder → escribir → enviar) | 3 + respuesta rápida | Respuesta rápida, plantillas |
| Pasar un correo a tarea | — | 2 | Acción en el mensaje |
| Acusar un aviso fiscal | — (no hay avisos) | **1 desde la notificación** | Acción «Lo llevo» |
| Aprobar una ausencia | ~5 (Fichaje → Ausencias → equipo → fila → aprobar) y sin notificación accionable | **1 desde la notificación** | Aviso accionable |
| Presentar una obligación con justificante | ~4 (Calendario → vencimiento → editar → presentado), **sin foto del justificante** | 4 con foto | Obligación con fase y cámara |
| Foto de una factura → revisada | — | ≤ 2 min | Captura + lectura con IA (Ola 4) |
| Ver las visitas de hoy (inmobiliaria) | — | 1 | Hoy / módulo |
| Preguntar algo al asistente | 2 | 1 desde el contexto | «Preguntar sobre esto» |
| Cambiar de despacho | — (siempre el principal) | 2 | Selector superior |

### A.13 Victorias rápidas (cada una ≤ 2 días; se pueden hacer antes de la Ola 0 sin esperar a la arquitectura nueva)

Son **mejoras de la app actual** que quitan los fallos más visibles mientras se construye la base nueva; se planifican aquí para decidir si merece la pena adelantarlas (D20):

| # | Mejora | Resuelve | Esfuerzo |
|---|---|---|:-:|
| QW-1 | Relleno inferior de las listas para que el botón «+» no tape contenido | M-02 | 0,2 d |
| QW-2 | Quitar la papelera de cada fila de tarea; borrar desde la ficha con confirmación | M-06 | 0,5 d |
| QW-3 | Mostrar el estado (texto + icono) y marcar en rojo lo vencido en la lista de tareas | M-04, M-05 | 1 d |
| QW-4 | Función única de fecha relativa/hora corta en tareas, correo y fiscal | M-05, M-09 | 1 d |
| QW-5 | Correo: nombre del remitente en lugar de `Nombre <correo>`, y punto de no leído | M-09 | 1 d |
| QW-6 | Asistente: sugerencias como *chips* y un solo botón primario | M-12 | 1 d |
| QW-7 | Etiquetas en los iconos de la barra de Fichaje y del Asistente (menú «⋯») | M-11, M-12 | 0,5 d |
| QW-8 | Herramientas: ocultar las «Aún no disponible» o plegarlas | M-13 | 0,5 d |
| QW-9 | Pestañas de ámbito de Tareas como selector segmentado completo | M-07 | 0,5 d |
| QW-10 | Tipografía Manrope y radio 12 px en el tema actual | M-14 | 1 d |

**≈ 7 días en total.** Efecto: la app se ve y se siente claramente más cuidada **sin esperar** a la reestructuración (que son semanas). Riesgo: tocar pantallas que se reescribirán; se limita a cambios de presentación, sin cambiar APIs ni modelos.

### A.14 Primer uso y permisos (la primera impresión)

| Momento | Hoy | Propuesta |
|---|---|---|
| Entrada | Pantalla de acceso con correo y contraseña; registro público; URL del servidor visible en Ajustes; 2FA al fallar | Acceso con **gestor de contraseñas** (`autofillHints`), mostrar/ocultar contraseña, código 2FA en pantalla propia con autocompletado de SMS/app, **sin registro público** (D10), «¿Tu despacho te ha invitado?» con enlace de invitación, servidor propio oculto tras pulsación larga en el logotipo |
| Permisos | Se piden al usar la función (micrófono, ubicación) | Mantener **«en contexto»**: notificaciones tras la primera acción valiosa (p. ej. al crear la primera tarea con vencimiento, con una frase de por qué), cámara solo al fotografiar, ubicación solo si el despacho la exige y al fichar, micrófono al dictar; si se deniega, explicación y botón a Ajustes |
| Primera pantalla | «Primeros pasos» con tareas de configuración | «Hoy» con datos reales; si el despacho es nuevo, 3 tarjetas descartables («Conecta tu correo», «Completa tus datos de fichaje», «Instala el widget») |
| Seguridad | Sin bloqueo | Oferta de **bloqueo biométrico** tras el segundo inicio de sesión, no en el primero |
| Idioma | Sigue el del sistema si hay ARB; selector manual | Mantener; respetar el idioma de la cuenta (`apariencia.idioma`) |
| Ayuda | — | «?» contextual por pantalla enlazado a la ayuda de la web (`ayuda.py`) y «Enviar comentarios» |

### A.15 Más allá de los defectos: oportunidades de mejora en la web y el backoffice

El barrido de la web (§12 del plan principal) midió **defectos**; esto son **mejoras de experiencia** observadas en las mismas capturas, ordenadas por valor/esfuerzo. No son urgentes, pero conviene decidirlas mientras se rediseña la app para que web y móvil evolucionen juntas.

| ID | Oportunidad | Dónde | Valor | Esfuerzo |
|---|---|---|:-:|:-:|
| W-01 | **Paleta de comandos** (`Ctrl K` ya existe en el backoffice y como buscador en la app): acciones además de búsqueda («Nueva tarea para Soler», «Fichar», «Ir a vencimientos») | App web | Alto | M |
| W-02 | **Hoy en escritorio con acciones en línea** (completar, posponer, abrir sin salir) y panel de detalle a la derecha | `/hoy` | Alto | M |
| W-03 | **Edición en línea** de tareas (asunto, fecha, estado) en lista y tablero, sin abrir la ficha | Tareas | Alto | M |
| W-04 | **Vistas guardadas visibles** como pestañas de la lista (ya existen en la API) | Tareas, Fiscal | Medio | S |
| W-05 | **Atajos de teclado** documentados (`?`) y consistentes (`n` nueva, `e` editar, `j/k` navegar) | Toda la web | Medio | M |
| W-06 | **Estados vacíos con acción** y lenguaje llano (Correo sin cuenta, Fichaje sin datos…) | Varias | Medio | S |
| W-07 | **Densidad de tablas**: columnas fijas, orden y selección de columnas por persona | Fiscal, Tareas, Clientes | Medio | M |
| W-08 | **Onboarding por despacho** (lista de arranque con progreso que ya existe) unificado con el de la app | Inicio | Medio | S |
| W-09 | **Notificaciones web** accionables (las mismas que el móvil) y centro de avisos con filtros | Campana | Alto | M |
| W-10 | **Panel de «salud del despacho»** para dirección: vencidas por persona, cargas, ausencias, avisos sin acusar, en una sola pantalla | Fiscal, Equipo | Alto | M |
| B-01 | **Backoffice: lista de tenants con salud, plan y último uso** (hoy muchas columnas con «—» en despachos nuevos) con estados vacíos explicados | Backoffice | Medio | S |
| B-02 | **Backoffice: acciones masivas** (comunicar, activar módulo, exportar) con revisión previa | Backoffice | Medio | M |
| B-03 | **Backoffice: «ver como» y soporte con cabecera visible** de a quién se está viendo y registro | Backoffice | Alto | S |

**Principio de consistencia.** Cada vez que se rediseña un componente de la app (fila de tarea, aviso, estado) se rediseña **el mismo** en la web con los mismos tokens y términos (A.7): la persona que cambia de móvil a escritorio debe reconocerlo.

### A.16 Catálogo de errores: del código de la API a lo que ve la persona

La API ya devuelve un `codigo` estable (56 distintos hoy) y el texto en castellano. La app **decide por `codigo`** y traduce con su propio texto (los mensajes del servidor quedan como respaldo y para soporte). Familias y tratamiento:

| Familia | Códigos de la API | Cómo se presenta | Texto de ejemplo (es) | Acción |
|---|---|---|---|---|
| **Sin red** | (sin respuesta) | Franja «Sin conexión» + la acción queda **pendiente** (cola) | «Sin conexión. Lo guardamos y lo enviaremos en cuanto vuelva.» | Ninguna: es automático |
| **Sesión** | `token_invalido`, `token_caducado`, `credenciales_o_codigo_incorrectos`, `requiere_2fa` | Pantalla de acceso conservando la cola | «Tu sesión ha caducado. Vuelve a entrar; no se pierde nada.» | Entrar de nuevo |
| **Red/IP** | `ip_no_permitida` | Diálogo informativo | «Este acceso no está permitido desde esta red.» | Contactar con administración |
| **Permisos** | `prohibido`, `sin_permiso`, `permiso`, `expediente_sin_permiso`, `solo_lectura`, `token_solo_lectura`, `token_area_no_permitida` | Banner en la pantalla; el botón no se muestra si ya se sabe por `/auth/me` | «No tienes permiso para hacer esto. Pídeselo a quien dirige el despacho.» | Ver quién puede |
| **No existe** | `no_encontrado`, `no_encontrada`, `expediente_no_encontrado` | Pantalla «Ya no está disponible» | «Este elemento ya no existe o no es tuyo.» | Volver a Hoy |
| **Módulo inactivo** | `404` en rutas de módulo | Tarjeta explicativa | «Tu despacho no tiene activado este módulo.» | Contactar |
| **Despacho bloqueado** (cifrado) | `despacho_bloqueado` (423) | Hoja de desbloqueo | «Documentos protegidos. Introduce la frase de paso para verlos.» | Desbloquear |
| **Conflicto de edición** | `version_obsoleta` (409/412) | Hoja con tres opciones | «Alguien ha cambiado esto mientras lo editabas.» | Ver cambios · Aplicar igualmente · Descartar |
| **Reglas de negocio** | `tarea_bloqueada`, `solo_por_revision`, `revision_pendiente`, `dependencia_invalida`, `envio_no_cancelable`, `traspaso_no_valido` | Mensaje junto al control, con el motivo del servidor | «No se puede completar: espera a «Revisar el IVA».» | Ir a la tarea de la que depende |
| **Duplicado** | `conflicto`, `referencia_duplicada`, cliente con NIF repetido | Hoja con el elemento existente | «Ya existe un cliente con ese NIF: Talleres Soler SL.» | Abrir el existente |
| **Validación** | `peticion_invalida`, `*_invalido`, `*_vacio`, `email_invalido`, `idioma_invalido`… (≈ 25) | **En el campo** (`campo` de la respuesta), nunca como diálogo | «Indica un correo válido.» | Corregir el campo |
| **Límite** | `limite_excedido` (429) + `Retry-After` | La app espera sola y reintenta; si pasa de 10 s, franja | «Vamos muy deprisa. Reintentando en 8 s…» | Ninguna |
| **Idempotencia** | `idempotencia_en_curso`, `idempotencia_conflicto` | Silencioso (la cola reintenta) | — | — |
| **Servicio** | `servicio_no_disponible`, `almacen_no_disponible`, `ia_no_configurada` (503/409) | Tarjeta con reintento | «Este servicio no responde ahora. Inténtalo en unos minutos.» | Reintentar |
| **Interno** | `error_interno` (500) + `request_id` | Mensaje breve con «Enviar a soporte» | «Algo ha ido mal por nuestra parte. Código: f37c8c4a.» | Copiar código / enviar diagnóstico |

El catálogo vive en un único fichero (`errores.dart` + ARB) generado en parte del OpenAPI (los códigos de cada operación); una prueba comprueba que **todo código nuevo del servidor tiene texto** en los 4 idiomas.

### A.17 Matriz de estados: cada pantalla las resuelve igual

| Estado | Qué ve la persona | Componente común |
|---|---|---|
| Cargando (< 300 ms) | Nada (evita parpadeo) | — |
| Cargando (> 300 ms) | Esqueleto con la forma de la lista | `Esqueleto` |
| Con datos antiguos (caché) | Datos + sello «actualizado hace…» y actualización discreta | `SelloDeFrescura` |
| Vacío | Icono + una frase + **botón principal** | `EstadoVacio` |
| Vacío por filtros | «Nada con estos filtros» + «Quitar filtros» | `EstadoVacio` |
| Sin conexión | Franja fija + datos de caché; acciones se encolan | `FranjaSinConexion` |
| Error recuperable | Franja con «Reintentar»; la pantalla anterior no se pierde | `FranjaError` |
| Error de pantalla completa | Tarjeta centrada con reintento y código de soporte | `PantallaError` |
| Sin permiso / módulo inactivo | Tarjeta explicativa, sin reintentos | `PantallaSinAcceso` |
| Protegido (423) | Candado + «Desbloquear» | `PantallaProtegida` |
| Parcial (una sección falla) | Las demás se muestran; la fallida muestra «Reintentar» solo ella | `SeccionConError` |
| Guardando / pendiente | Elemento con reloj; al confirmar, desaparece | `IndicadorPendiente` |
| Conflicto | Hoja de resolución | `HojaDeConflicto` |

Regla de revisión: **ninguna pantalla se da por terminada** si no tiene una prueba de widget por cada fila aplicable de esta matriz.

### A.18 Guiones de prueba de uso (plantilla por ola)

Cada sesión: 30 min, 1 persona + 1 observadora, móvil real, datos del despacho piloto (con permiso), grabación de pantalla opcional con consentimiento, tareas dichas en lenguaje natural (sin nombrar botones). Métricas por tarea: **éxito sin ayuda**, **tiempo**, **errores/retrocesos**, **valoración 1–5 de facilidad**; al final, **SUS** (10 preguntas).

| Ola | Tareas del guion |
|---|---|
| **1** (Hoy, Tareas, Avisos) | 1) «Mira qué tienes que hacer hoy y di qué es lo más urgente» · 2) «Crea una tarea para el cliente Soler que venza el viernes» · 3) «Marca como hecha la de las nóminas» y «deshaz» · 4) «Averigua por qué la tarea del IVA está parada» · 5) «Comenta en esa tarea y adjunta una foto» · 6) «Llegó un aviso: respóndelo sin abrir la app» · 7) «Busca la nota donde apuntaste lo del certificado» |
| **2** (Gestoría) | 1) «Busca el cliente Pons y llámale» · 2) «Marca presentado el modelo 303 de Soler y adjunta el justificante» · 3) «Dile al cliente que falta un documento» · 4) «Acusa el aviso fiscal de esta semana» · 5) «Abre un documento de un cliente» (con y sin cifrado) |
| **3** (Personal, correo) | 1) «Ficha tu entrada» (en frío) · 2) «Pide tres días de vacaciones» · 3) «Aprueba la ausencia de María» · 4) «Contesta al correo de la clínica y crea una tarea desde él» · 5) «Programa un envío para mañana» |
| **4** (verticales) | Según módulo: foto de factura → revisada · visitas de hoy → llamar → anotar resultado · acta de reunión por dictado → crear tareas · comprobar conflicto de intereses |

**Criterios de paso:** ≥ 90 % de éxito sin ayuda, tiempo mediano dentro de los objetivos de A.12, SUS ≥ 80 y ningún problema de severidad alta repetido en ≥ 2 sesiones.

---

## B. La app sobre la base de datos PostgreSQL de toda la web

### B.1 El camino de un dato (qué significa «que use la BD de toda la web»)

La app **no habla con PostgreSQL**: habla con la API (`/api/v1`), que es la misma aplicación Flask que sirve la web y que usa las mismas funciones de dominio y la misma base. Eso da tres garantías que conviene conservar y vigilar:

```
 App Flutter ──HTTPS──▶ Caddy ──▶ Flask (API + web) ──▶ pool de conexiones ──▶ PostgreSQL 17 + Citus
   token Bearer          TLS       token_required        rol guilda_app            RLS por despacho
   X-Despacho            gzip      cupos, idempotencia   (sin privilegios)         app.tenant_id / app.usuario_id
                                   funciones de dominio  set_config por transacción tablas distribuidas por tenant_id
```

1. **Un único dato.** Lo que ve la web y lo que ve la app salen de las mismas tablas: no hay copia ni réplica «para móvil». El MCP y la IA también.
2. **Aislamiento por despacho aunque la aplicación falle.** El rol `guilda_app` no salta la RLS; cada transacción empieza con `set_config('app.tenant_id', …)` y `app.usuario_id`. Un fallo de código en un endpoint nuevo **no** puede leer otro despacho.
3. **Personas en varios despachos.** `X-Despacho` se valida contra `usuarios_tenants` y fija el contexto; la caché del móvil se clava a ese despacho.

Lo que **no** debe hacer la app (ni la API para ella): consultas pensadas para SQLite que en PostgreSQL+Citus salen caras (varias transacciones por petición, N+1, listados sin límite) ni nada que dependa del orden de `id` global entre transacciones concurrentes.

### B.2 Medidas (24-oct-2026, datos sintéticos, 3 despachos, 12 personas, 60 clientes/despacho, 3.000 vencimientos)

Entorno: contenedor de ensayo (`guilda-pg-ensayo`, PostgreSQL 17 + Citus con el coordinador como nodo de datos), esquema `citus` como producción, rol `guilda_app` con RLS, 36 peticiones por endpoint repartidas entre las 12 personas, en el mismo proceso que la app (sin red ni Caddy). Scripts: `docs/anexos-app-movil/medir_api_movil_prototipo.py`; cifras en `medida_api_*.json`.

| Endpoint | SQLite p50 | **PG p50 / p95** | Sentencias en el servidor* | Carga útil |
|---|---:|---:|---:|---:|
| `/auth/me` | 1,1 ms | **18 / 24 ms** | 14 | 0,1 KB |
| `/dashboard` | 1,4 | **27 / 30** | **34** | 0,5 KB |
| `/mi-dia` | 3,5 | 27 / 39 | 14 | 34 KB |
| `/tareas-outlook?limit=50` | 3,0 | 23 / 27 | 10 | 42 KB |
| `/tareas-outlook/tablero` | 4,2 | 31 / 38 | — | **85 KB** |
| `/notificaciones` | 1,3 | 18 / 21 | — | 5 KB |
| `/fiscal/clientes` | 2,0 | 18 / 20 | — | 29 KB |
| `/fiscal/vencimientos` | 19,3 | 37 / 46 | — | **524 KB** |
| `/fiscal/panel` | 8,1 | 46 / 53 | 20 (por la capa de datos) | 12 KB |
| `/correo/mensajes?cuenta_id=` | 2,8 | 22 / 31 | — | **174 KB** |
| `/buscar?q=factura` | 1,1 | 15 / 18 (*) | 6 | 0,02 KB |
| `/sync` (cursor actual) | 1,1 | 17 / 22 | — | 0,1 KB |
| **`/sync?cursor=0`** (primera descarga) | 7,1 | **752 / 795** | **130** | 87 KB |
| El resto (herramientas, compañeros, proyectos, perfil, IA…) | ~1,2 | 15–19 / 20–25 | 7–9 (hasta el cómputo de la app) | < 6 KB |

(*) **No representativo**: `/buscar` usa Meilisearch+Ollama, que no están en el entorno de ensayo, y devuelve vacío al instante; la búsqueda real no está medida (ver P-08).

\* «Sentencias en el servidor» = llamadas reales a PostgreSQL medidas con `pg_stat_statements` (incluyen `BEGIN`, `COMMIT` y el `set_config` del contexto de RLS); 10 repeticiones por endpoint.

**Qué dicen las cifras**

- **El tiempo no está en las consultas, está en los viajes.** El `SELECT * FROM usuarios WHERE id = $1` tarda ≈ 0,7 ms; el endpoint tarda 18. En `/auth/me` hay **3 transacciones** (cada función de datos abre y cierra la suya) y **9 de las 14 sentencias son `BEGIN`/`COMMIT`/`set_config`**. En `/dashboard` hay **8 transacciones y 34 sentencias**, de las que 24 son de ceremonia.
- **Cada petición escribe dos veces** aunque sea de lectura: `UPDATE tokens_api SET ultimo_uso_en…` y `INSERT INTO tokens_api_uso … ON CONFLICT DO UPDATE` (una fila «caliente» por token y día, que además serializa las peticiones paralelas de un mismo móvil).
- **La lectura repetida de `usuarios`** (3–4 veces por petición) y de `tenants` (2) no se reutiliza dentro de la petición.
- **La primera sincronización es N+1**: 100 sentencias para cargar 100 tareas una a una + 20 para 20 notas.
- **Las cargas útiles** de listados sin paginar son desproporcionadas para un móvil (medio megabyte en vencimientos).
- **Bajo concurrencia, las escrituras de uso rompen la API** (medido con 1, 4, 8 y 12 clientes simultáneos pidiendo `/auth/me`, cada uno con su token, ejecución en el mismo proceso):

| Clientes a la vez | **Con** las escrituras de uso: rps · p95 · errores | **Sin** ellas: rps · p95 · errores |
|---:|---|---|
| 1 | 68 · 16 ms · 0 | 100 · 12 ms · 0 |
| 4 | **34 · 402 ms · 17 de 240 (7 %)** | 191 · 25 ms · 0 |
| 8 | **22 · 802 ms · 224 de 480 (47 %)** | 180 · 56 ms · 0 |
| 12 | **16 · 1.796 ms · 466 de 720 (65 %)** | 163 · 91 ms · 0 |

  El error es `psycopg.errors.DeadlockDetected: canceling the transaction since it was involved in a distributed deadlock`: `tokens_api` y `tokens_api_uso` son **tablas de referencia** de Citus (replicadas) y, como ya advierte el ADR (§ «Escribir en tablas de referencia serializa a todos los escritores»), cada escritura toma un bloqueo exclusivo hasta confirmar; dos peticiones que toman los bloqueos en distinto orden se interbloquean. **Comprobado en el catálogo del PostgreSQL de producción (`pg_dist_partition`, solo lectura): las cuatro (`tokens_api`, `tokens_api_uso`, `api_idempotencia`, `mcp_uso`) son tablas de referencia (`partmethod = 'n'`).** Con un nodo de trabajo añadido, además, cada una sería una transacción en dos fases contra todos los nodos.**
- Los **cupos de la API** (600/min, 200 escrituras, 20 pesadas) viven **en memoria del proceso** (`_ventanas`): correctos con un solo proceso, **no compartidos** si algún día hay varios procesos o réplicas de la aplicación.

### B.3 Hallazgos

| ID | Sev. | Hallazgo | Evidencia | Efecto en la experiencia |
|---|:-:|---|---|---|
| **P-01** | **Crítica** | **El cursor de `/sync` pierde cambios con transacciones concurrentes** | Reproducido: A inserta una tarea (id menor) sin confirmar; B inserta otra y confirma; el cliente sincroniza (cursor ≥ id de B); A confirma → **el cliente no recibe A** hasta pedir otra vez desde el cursor inicial. `api_cambios.id` es un contador global y el orden de confirmación no es el de asignación (en SQLite, con un único escritor, no ocurría) | Una tarea asignada por un compañero puede no llegar nunca al móvil; sin conexión, datos incompletos sin que nadie lo note |
| **P-02** | Alta | **Una transacción por función de datos** (no por petición) | 3 transacciones en `/auth/me`, 8 en `/dashboard`; 60–70 % de las sentencias son `BEGIN`/`COMMIT`/`set_config` | Latencia de 15–30 ms por petición trivial; 6 llamadas de «Hoy» ≈ 150 ms de ceremonia |
| **P-03** | **Crítica** | **Dos escrituras en tablas de referencia por cada petición** (`UPDATE tokens_api…ultimo_uso`, `INSERT INTO tokens_api_uso…ON CONFLICT`); las POST con `Idempotency-Key` escriben además `api_idempotencia`, y cada llamada MCP, `mcp_uso` (con un `DELETE` de purga) | Reproducido: 4 clientes → 7 % de 500, 12 → 65 % (`DeadlockDetected` distribuido); sin esas escrituras, 0 errores y ×5–10 de rendimiento. Contradice la regla del ADR de no escribir en tablas de referencia en la ruta caliente | **Peticiones que fallan al azar** cuando varias personas (o varias pantallas de una persona) llaman a la vez |
| **P-04** | Media | **Lecturas repetidas** de usuario y despacho en una petición | 3–4 `SELECT * FROM usuarios`, 2 `tenants` | +4 viajes |
| **P-05** | Alta | **Sincronización inicial N+1** | 130 sentencias, 750 ms para 100+20 elementos | Primer arranque lento; con 2.000 tareas serían ≈ 15 s |
| **P-06** | Alta | **Listados sin paginar y sin proyección** | 524 KB, 174 KB, 85 KB, 42 KB | Datos móviles, memoria, batería y tiempo de render |
| **P-07** | Media | **Cupos en memoria** | `auth._ventanas` | Imprecisos si hay varios procesos; se pierden al reiniciar |
| **P-08** | Media | **La búsqueda de notas y tareas es `LOWER(texto) LIKE '%…%'`** (recorrido secuencial, sensible a acentos y sin tolerar erratas) y la «híbrida» depende de **Meilisearch + Ollama** (servicios externos que pueden faltar: entonces `/buscar` devuelve vacío) | `tsvector` generado solo en `correo_mensajes` y fragmentos jurídicos (`06_busqueda.sql`); `db_notas.py:331`, `db_tareas.py:1143` | Búsqueda lenta con volumen, sin acentos ni erratas y que desaparece si cae Meilisearch |
| **P-09** | Media | **Sin etiquetado de endpoint en la base** | `pg_stat_statements` agrupa por texto, no por pantalla/endpoint | No se puede responder «¿qué pantalla del móvil gasta más?» |
| **P-10** | Baja | **Sin tiempo real** | La app solo se entera al abrir o por push | Hoy desactualizado mientras se usa; el push no sirve para refrescar pantallas abiertas |
| **P-11** | Media | **Límite de despachos sin probar con la app** | Pruebas de carga previas simulan la web (cookies), no el perfil de tráfico de una app (muchas llamadas pequeñas en paralelo, reintentos, `ETag`) | Riesgo de sorpresas con 100+ móviles |
| **P-12** | Media | **El avatar (`bytea`) viaja en cada página y en `/perfil`**: `obtener_perfil_usuario` hace `SELECT * FROM usuario_perfil` (con `avatar_contenido`) desde el `context_processor` `inyectar_perfil_rail` (`app/main.py:716`), es decir, **en cada vista de la web**, y también en las rutas de perfil de la API; la tabla es de referencia (replicada) | Lectura de código (`db_plataforma.py:2472`); el tamaño real de los avatares **no se ha medido** (no se consultaron datos de producción) | Transferencia innecesaria PG→Flask en cada página; se acentúa si los avatares son fotos de móvil sin reducir |

### B.4 Diseño objetivo

#### B.4.1 Una conexión y una transacción por petición (P-02, P-04)

- Abrir **una** conexión al empezar la petición (`g.db`), fijar el contexto de RLS **una vez** (`set_config(...)` en el mismo viaje que `BEGIN`) y confirmar al final; las funciones de datos reciben la conexión existente en lugar de abrir otra (con un parámetro opcional `conn`, sin romper las llamadas actuales).
- Memorizar por petición la fila de `usuarios` y de `tenants` (`g.usuario`, `g.tenant`).
- **Modo canalización (*pipeline*) de psycopg 3** para los endpoints que lanzan varias lecturas independientes (`/hoy`, `/dashboard`, `/fiscal/panel`): todas las consultas viajan en un solo envío.
- Meta: **≤ 4 sentencias de ceremonia por petición y ≤ 6 viajes en `/hoy`**.

#### B.4.2 Autenticación y registro de uso baratos (P-03)

- Una sola consulta para token + usuario + despacho (`JOIN`) y una caché de **15 s** de tokens válidos (clave: hash del token → `usuario_id`, permisos, áreas, caducidad, IPs). **Revocar** un token (o cambiar su permiso) incrementa una versión global y vacía la caché de ese proceso: efecto inmediato en un proceso, ≤ 15 s con varios.
- `ultimo_uso_en` solo si han pasado > 60 s; `tokens_api_uso` y `mcp_uso` **agregados en memoria y volcados cada 30 s** en un único `INSERT … ON CONFLICT` por lote (una transacción corta, fuera de la ruta de la petición). Coste: perder como máximo 30 s de contadores si el proceso cae. Beneficio: **0 escrituras en tablas de referencia en la ruta caliente** (lo que exige el ADR) y fin de los interbloqueos medidos. Para `api_idempotencia`: reservar con `INSERT … ON CONFLICT DO NOTHING` solo cuando llega la cabecera `Idempotency-Key`, o mover la tabla a **distribuida por `tenant_id`**.
- **Alternativa de modelo**: convertir `tokens_api_uso`, `mcp_uso` y `api_idempotencia` de tablas de referencia a **distribuidas por `tenant_id`** (migración numerada `.citus.sql`; el uso del token lleva ya su despacho) para que un escritor solo bloquee los de su propio despacho. Se decide con la prueba PG-00.
- **Cupos compartidos** (P-07) si hay más de un proceso: contador en PostgreSQL `UNLOGGED` (tabla `api_cupos`) o Redis; hoy no hace falta, pero la interfaz de `auth` debe poder cambiarse.

#### B.4.3 `GET /hoy` en un viaje (P-02, P-06)

Las 11 secciones de `bandeja_hoy.reunir()` se ejecutan como **consultas independientes en una canalización** dentro de la **misma** transacción (misma instantánea, coherente), cada una con `LIMIT 25` y solo las columnas necesarias. Alternativa si no basta: una **función SQL** `hoy(p_usuario)` que devuelve `jsonb` (una sola sentencia; RLS se aplica porque corre con los privilegios de quien llama). Se decide con medida: objetivo **≤ 40 ms** en el servidor con 60 clientes y 3.000 obligaciones.

#### B.4.4 Paginación por cursor (*keyset*) e índices (P-06)

- Todos los listados que use la app aceptan `limit` (por defecto 50, máximo 200) y devuelven `X-Next-Cursor` (`(fecha, id)` codificado); nada de `OFFSET` (cuesta cada vez más en páginas profundas).
- **Proyección**: `?campos=` ya existe; los modelos «de lista» de la app piden solo lo que pintan.
- **Índices parciales** (a validar con `EXPLAIN` en datos reales; ejemplos): tareas abiertas por persona y vencimiento (`(usuario_id, fecha_vencimiento, id) WHERE papelera_en IS NULL AND estado <> 'completada'`), vencimientos pendientes por despacho y fecha (`(tenant_id, fecha_limite, id) WHERE estado = 'pendiente'`), notificaciones sin leer (`(usuario_id, creado_en DESC) WHERE leido_en IS NULL`), correo por cuenta/carpeta/fecha.
- **Compresión** (`gzip`/`br`) en Caddy para JSON y límite de tamaño de respuesta con alerta (> 200 KB).

#### B.4.5 Cambios seguros para el modo sin conexión (P-01, P-05)

Tres diseños posibles; la recomendación es A ahora y B como paso previo a añadir nodos de Citus.

| Diseño | Idea | Pros | Contras |
|---|---|---|---|
| **A. Cursor por transacción confirmada** | Añadir `txid xid8 DEFAULT pg_current_xact_id()` a `api_cambios`; el cursor es el `pg_snapshot_xmin(pg_current_snapshot())` observado al leer y la consulta pide `txid >= cursor AND txid < xmin_actual`. Solo se devuelve lo que ya **no puede aparecer** con un id anterior | Exacto; sin bloqueos; barato; sin nueva tabla | Los `xid8` son por nodo: **no comparables entre nodos** de Citus (hoy hay uno) |
| **B. Versión por despacho** | Tabla `despacho_version(tenant_id, v)`; los triggers incrementan `v` con un bloqueo de fila corto (ya existe `pg_advisory_xact_lock` por despacho para `BEGIN IMMEDIATE`); cada cambio guarda su `v` y el cursor es `(tenant, v)` | Seguro también con varios nodos; ordenado por despacho | Serializa a los escritores **del mismo despacho** en el último instante de la transacción |
| **C. Ventana de seguridad** (parche) | El servidor solo entrega cambios con más de 5 s de antigüedad y el cliente reenvía desde `cursor − 200` (las altas son idempotentes) | Trivial; sin cambio de esquema | Retrasa 5 s; no es una garantía formal si una transacción dura más |

**Plan:** (1) parche C **inmediato** (medio día) y **prueba de regresión** con el script de concurrencia que reprodujo el fallo; (2) A con migración numerada (`scripts/migrar_esquema_pg.py`) y retirada de C; (3) B cuando se añada un segundo nodo de datos. Aplica también a la entrega de **webhooks** y a cualquier otro consumidor de `api_cambios`.

**Primera descarga (P-05):** `/sync?cursor=0` pasa a **páginas de 200** con `hay_mas` y consultas por lote (`WHERE id = ANY(%s)`); objetivo ≤ 6 sentencias por página y ≤ 120 ms.

#### B.4.6 Tiempo real moderado (P-10)

- **`GET /api/v1/eventos`** (SSE) mientras la app está en primer plano: avisos nuevos, tarea asignada, cambio en lo que se ve. Se alimenta con **`LISTEN/NOTIFY`**: tras confirmar (gancho *after-commit* de la aplicación), `NOTIFY guilda_<despacho>` con `{entidad, id}`; el servidor retransmite solo a quien corresponde (misma regla de visibilidad que `cambios_desde`).
- **Por qué *after-commit* de aplicación y no un trigger**: con Citus, un `NOTIFY` dentro de un trigger sobre un fragmento solo llega a oyentes de ese nodo; con un solo nodo funcionaría, pero no escala. Además `LISTEN` no funciona detrás de un *pooler* en modo transacción (no se usa PgBouncer hoy; se mantiene esa restricción).
- En segundo plano, **push** (FCM/APNs) como hasta ahora. La app **nunca sondea**.
- Es una mejora de experiencia opcional (Ola 3+); el modo sin conexión **no depende** de ella.

#### B.4.7 Búsqueda (P-08)

Hoy la búsqueda de notas y tareas es un `LIKE '%…%'` y la semántica depende de Meilisearch/Ollama. El objetivo es que **la búsqueda básica viva en PostgreSQL** (siempre disponible, aislada por RLS, sin un índice externo que sincronizar) y que Meilisearch quede solo como mejora semántica opcional. Extender el patrón del correo (`tsvector` generado con configuración `es_simple`, GIN, consulta por prefijo) a **tareas** (asunto, cuerpo), **notas** (título, texto), **clientes** (nombre, NIF normalizado) y **contactos**; **`pg_trgm`** para nombres con erratas; `unaccent` ya está. `/buscar` devuelve hasta 5 por tipo con `ts_rank_cd`, y **la app busca mientras se escribe** (espera 250 ms, cancela la petición anterior, muestra recientes sin red). Meta: **p95 ≤ 150 ms** con 100.000 filas. Las búsquedas sobre correo cifrado (nivel *Estricto*) siguen su propio camino (índice en memoria).

#### B.4.8 Observabilidad por pantalla (P-09)

- Poner `application_name = 'api:<método> <ruta> app/<versión>'` en el **mismo** `set_config` que ya fija el contexto (cero viajes extra): `pg_stat_activity`, el registro de consultas lentas (`%a`) y `auto_explain` quedan etiquetados.
- Cabeceras de respuesta `Server-Timing: db;dur=…, sql;desc=n` en entornos de prueba y panel **«API móvil»** en Grafana (ya hay fuente de datos PostgreSQL y panel de salud): p50/p95 por endpoint, sentencias por petición, bytes, 4xx/5xx/423/429, caché de tokens, cola de eventos.
- **Guardia de regresión en CI**: una prueba que cuenta las sentencias de una lista de endpoints y falla si superan su presupuesto (tabla B.6). Es barata y evita que el problema vuelva.

#### B.4.9 Escritura e idempotencia

- `Idempotency-Key` ya existe; sustituir el `DELETE … WHERE creado_en < …` que se ejecuta **en cada reserva** por una limpieza periódica en lotes (tarea programada) y `INSERT … ON CONFLICT DO NOTHING RETURNING` para reservar.
- Para la cola de la app: ver plan principal §13.1. Los `409`/`412` devuelven el estado actual del recurso (`version_actual`) para decidir sin otra lectura.

#### B.4.10 Seguridad y despacho

- **Prueba por endpoint nuevo** de *cross-despacho*: el token de una persona del despacho 1 con `X-Despacho: 2` (donde no está) → `403/404`; con un id de otro despacho → `404`. Se añade al *fixture* de contrato.
- `X-Despacho` se valida en un solo punto (`tenant_activo`); la caché de tokens guarda los despachos permitidos para no consultar `usuarios_tenants` en cada petición.
- Sin contenido cifrado en respuestas cacheables compartidas (`Cache-Control: private, no-store` donde haya `cifrado`).

#### B.4.11 Capacidad (estimación a validar con la prueba de carga)

Con las medidas actuales una petición típica ocupa ≈ 18 ms de un hilo (≈ 55 peticiones/s por hilo en la capa de datos). Una persona con la app abierta genera ≈ 1 petición cada 4–5 s (Hoy, refrescos, acciones): **~100 personas activas a la vez ≈ 25 peticiones/s**, bien dentro de lo medido; los picos (apertura matinal con 6 llamadas por persona) son el caso a vigilar. Con las mejoras de B.4.1–B.4.3 se espera **×3 de capacidad** (de ≈ 18 a ≈ 6 ms). La prueba de carga (B.7) fija los números reales, con el perfil de tráfico de una app.

### B.5 Objetivos de nivel de servicio (SLO) de la API para la app

| Medida | Objetivo | Hoy |
|---|---|---|
| p95 de lectura simple (`/auth/me`, `/notificaciones`, `/perfil`) | ≤ 40 ms en servidor | 21–24 ms (cumple, pero con 14 sentencias) |
| p95 de listados paginados (50 filas) | ≤ 80 ms | 27–38 ms |
| `GET /hoy` | ≤ 60 ms, ≤ 6 viajes | no existe |
| `/sync` incremental | ≤ 30 ms, ≤ 3 sentencias | 22 ms |
| `/sync` primera descarga (hasta 1 MB) | ≤ 1,2 s en páginas | 795 ms para 87 KB sin paginar (**no escala**) |
| Búsqueda | ≤ 150 ms p95 | sin índice propio |
| Sobrecarga fija por petición | ≤ 4 sentencias, 0 escrituras en la ruta caliente | 14 sentencias, 2 escrituras |
| Carga útil primera página | ≤ 50 KB | hasta 524 KB |
| Errores 5xx | < 0,1 % | — |
| Pérdida de cambios en `/sync` | **0** | **reproducida** |

### B.6 Presupuesto por pantalla (contrato entre UX y datos)

| Pantalla | Endpoints | Sentencias máx. (servidor) | Carga máx. | Caché en la app |
|---|---|:-:|:-:|---|
| Hoy | `GET /hoy` | 12 (en 1 viaje) | 30 KB | 2 min + evento SSE |
| Tareas (lista) | `GET /tareas-outlook?limit=50&…` | 4 | 40 KB | `/sync` + 5 min |
| Tarea (detalle) | `GET /tareas-outlook/{id}` (+ `…/comentarios`, `…/subtareas` en la misma llamada con `incluir=`) | 8 | 20 KB | `ETag` |
| Avisos | `GET /notificaciones?desde=…` | 3 | 10 KB | evento SSE |
| Correo (lista) | `GET /correo/mensajes?cuenta_id=&limit=50&campos=…` | 4 | 40 KB | `ETag` + 2 min |
| Correo (lectura) | `GET /correo/mensajes/{id}` | 6 | 60 KB | no persiste si hay cifrado |
| Fichaje | `GET /fichaje/estado` (+ resumen en la misma llamada) | 4 | 3 KB | 30 s |
| Búsqueda | `GET /buscar?q=` | 6 | 10 KB | 5 min por consulta |
| Cliente (ficha) | `GET /clientes/{id}/resumen` (S-04) | 8 | 20 KB | `ETag` |
| Arranque | `GET /auth/me` + `GET /hoy` + `GET /notificaciones?limit=5` | 24 | 40 KB | — |

### B.7 Cómo se verifica

1. **Prueba de concurrencia del cursor** (el guion de `medir_api_movil_prototipo.py`, bloque «Seguridad del cursor»), convertida en test que **falla hoy** y debe pasar tras el parche C y con A.
2. **Guardia de sentencias** por endpoint (presupuesto de B.6) en CI sobre PostgreSQL.
3. **Prueba de carga con perfil de app**: extender `scripts/prueba_carga.py` con un perfil «móvil» (token Bearer, 6 llamadas en paralelo al abrir, refrescos cada 30 s, 15 % escrituras con `Idempotency-Key`, 5 % reintentos, `ETag`), 60 despachos y 200 personas; comparar SQLite/PG, con y sin mejoras.
4. **`EXPLAIN (ANALYZE, BUFFERS)`** de las 20 consultas más costosas del perfil móvil y revisión de índices con datos de volumen (la base real tiene un volumen mayor que la sintética).
5. **Pruebas de aislamiento** por despacho de cada endpoint nuevo.
6. **Medida de campo** tras la beta: panel «API móvil», `pg_stat_statements` por `application_name`, y revisión semanal junto a `scripts/revision_postgres.py`.

### B.8 Paquetes de trabajo de servidor (orden recomendado)

| ID | Paquete | Resuelve | Tamaño | Cuándo |
|---|---|---|:-:|---|
| **PG-01** | Parche del cursor (ventana de seguridad) + test de concurrencia | P-01 | S | **Ya** (antes de cualquier uso offline) |
| **PG-00** | **Prueba de concurrencia de la API** (4/8/12 clientes; 0 errores exigidos) convertida en test de CI sobre PostgreSQL+Citus, y revisión de **todas** las escrituras en tablas de referencia que ocurren por petición (`usuarios.ultimo_acceso`, `usuario_perfil`, `comunicados_cerrados`, `ver_como_tokens`…) | P-03 y vecinos | S | **Ya**, es la que habría detectado el problema |
| **PG-02** | Conexión/transacción por petición, `g.usuario`/`g.tenant` memorizados | P-02, P-04 | M | Ola 0 |
| **PG-03** | Token + usuario + despacho en una consulta; caché de tokens 15 s | P-03, P-04 | S | **Antes de lanzar la app** |
| **PG-04** | **Sacar de la ruta caliente las escrituras en tablas de referencia**: uso de token, `ultimo_uso_en`, `mcp_uso` y `api_idempotencia` (agregar en memoria y volcar cada 30 s en lote, o moverlas a tablas **distribuidas** por `tenant_id`/no replicadas) | **P-03** | S–M | **Urgente: antes de que haya más de un cliente de API/MCP activo** (hoy mismo si se autoriza) |
| **PG-05** | Guardia de sentencias en CI (presupuestos B.6) | P-02, P-09 | S | Ola 0 |
| **PG-06** | `application_name` por endpoint + `Server-Timing` + panel Grafana «API móvil» | P-09 | M | Ola 0 |
| **PG-07** | Cursor por transacción (diseño A) con migración numerada; retirar el parche | P-01 | M | Ola 1 |
| **PG-08** | `/sync` por páginas y por lotes | P-05 | M | Ola 1 |
| **PG-09** | `GET /hoy` con canalización (S-01) | P-02, P-06 | M | Ola 1 |
| **PG-10** | Paginación por cursor + proyección + índices parciales en los listados de la app | P-06 | L | Ola 1–2 |
| **PG-11** | Búsqueda unificada (`tsvector` + `pg_trgm`) en tareas, notas, clientes | P-08 | M | Ola 1–2 |
| **PG-12** | Cupos compartidos (si se escala a varios procesos) | P-07 | S | cuando haga falta |
| **PG-13** | Tiempo real SSE con `LISTEN/NOTIFY` | P-10 | M | Ola 3 |
| **PG-14** | Prueba de carga con perfil de app y revisión de planes | P-11 | M | Ola 1 (primera pasada) y Ola 2 |

**Esfuerzo de servidor para §B ≈ 6 persona-semanas** (PG-01…PG-06 ≈ 2,5 pw, imprescindibles **antes** de la beta; el resto se reparte en las olas 1–3). Se solapa con S-01, S-03, S-05, S-06 y S-17 del plan principal: PG-09 *es* S-01; PG-08 amplía S-06; PG-10 incluye S-17.

### B.9 Riesgos específicos

| # | Riesgo | Mitigación |
|---|---|---|
| RP-1 | Cambiar a una conexión por petición rompe la semántica de `BEGIN IMMEDIATE` (bloqueo por despacho) y los `SAVEPOINT` de escritura | Hacerlo solo en rutas de **lectura** primero; pruebas de la suite en los dos motores; escrituras al final |
| RP-2 | La caché de tokens retrasa una revocación | TTL de 15 s, invalidación explícita en el proceso, aviso en la ayuda de seguridad; opción de desactivar por token «sensible» |
| RP-3 | Diseño A del cursor depende de `xid8` de un solo nodo | Abstracción `cursor_cambios`; paso a B antes del segundo nodo de datos; prueba en el ensayo de Citus con *worker* |
| RP-4 | Los índices parciales no se usan con los parámetros reales | `EXPLAIN` en datos de volumen; revisión semanal con `pg_stat_statements`; retirar los que no se usen |
| RP-5 | El volcado diferido de contadores pierde uso al reiniciar | Aceptado (≤ 30 s); volcado al apagar con `SIGTERM` |
| RP-6 | SSE mantiene conexiones abiertas | Un hilo por conexión en el servidor actual (waitress): límite y *timeout*, o un proceso aparte para SSE; evaluar en la Ola 3 antes de comprometerse |
| RP-7 | La RLS añade coste en consultas de búsqueda | Medir con `EXPLAIN`; las funciones `usuario_visible()`/`token_visible()` ya se diseñaron para tablas de referencia |

---

## C. Qué cambia en el plan principal por esta sesión

| Dónde | Cambio |
|---|---|
| Plan principal §6 (servidor) | Añadir **PG-01…PG-14** como paquetes de servidor; **PG-01 pasa a ser requisito de la beta** (offline seguro) |
| Plan principal §7, Ola 0 | Incluir PG-02…PG-06 (sobrecarga de la API y observabilidad) junto a S-02/S-03 |
| Plan principal §7, Ola 1 | Incluir PG-07…PG-11 y PG-14; la tarea 1.11 (sin conexión) **depende de PG-01 y PG-07** |
| Plan principal §8 (calidad) | Añadir la **guardia de sentencias**, la prueba de concurrencia del cursor y la prueba de carga con perfil de app |
| Plan principal §12 (UX) | Sustituir la lista de hallazgos de la app por **A.1** de este documento (pantallas reales) y adoptar **A.2–A.10** |
| Plan principal §10 (esfuerzo) | +3 pw de diseño y pruebas de uso (A) y +3,5 pw de servidor no solapado (B): **total ≈ 42 persona-semanas** |

### Decisiones nuevas que necesito de ti

| # | Decisión | Mi recomendación |
|---|---|---|
| **D21** | 🔴 **Arreglo urgente de las escrituras de uso (PG-04) y del cursor (PG-01)**, aunque este trabajo sea de planificación: afectan a la API y al MCP **en producción hoy** (≈ 1 día de trabajo, con prueba de concurrencia) | **Sí, cuanto antes.** Dime «adelante» y lo preparo con pruebas en los dos motores; no toco nada sin tu visto bueno |
| **D13** | **Aplicar ya el parche del cursor de `/sync`** (PG-01) aunque la app aún no use el modo sin conexión (la web y la API pública también lo usan: integradores externos) | Sí, ahora; es medio día y elimina un riesgo silencioso |
| **D14** | **Una conexión por petición** (PG-02): ¿empezar solo por lecturas de la API móvil? | Sí; lo demás, tras medir |
| **D15** | **Diferir el registro de uso de tokens** (pérdida máxima de 30 s de contadores) | Sí |
| **D16** | **Caché de tokens de 15 s** (revocación con retraso máximo de 15 s con varios procesos) | Sí, con invalidación inmediata en el proceso |
| **D17** | **SSE con `LISTEN/NOTIFY`** (PG-13): ¿merece la pena en la Ola 3 o basta con push + refresco al volver a primer plano? | Dejarlo para después de medir; el push cubre el 90 % |
| **D18** | **Glosario único** (A.7): «obligación» vs «vencimiento», «despacho» en toda la UI | Aprobar el glosario y aplicarlo también a la web y a los textos de API |
| **D19** | **Reutilizar las preferencias de menú de la cuenta** en «Más» (accesos fijados) | Sí: una sola configuración para web y móvil |
| **D20** | **Victorias rápidas de UX (A.13)** antes de la Ola 0 (≈ 7 días) | Sí, si la app ya la usa alguien; mejora la percepción mientras se construye lo nuevo |

---

## D. Diseño listo para ejecutar de lo urgente (PG-00, PG-01, PG-04)

> **✅ Estado (24-oct-2026, noche): implementado y probado en el ensayo; pendiente de que reinicies `guilda-work` y `guilda-work-mcp`.**
> Código: `app/uso_diferido.py` (nuevo), `app/db_plataforma.py` (uso diferido, lectores que vuelcan antes de leer, idempotencia sin purga por petición, ventana del cursor), `mcp_server*.py` y `app/main.py` (volcado al parar), `scripts/prueba_concurrencia_api.py` y `tests/test_api_concurrencia_citus.py` (PG-00), `tests/test_uso_diferido.py`.
> **Medido con PostgreSQL + Citus real y roles sin privilegios** (`scripts/prueba_concurrencia_api.py --control`): con el arreglo, 4 clientes → 151 peticiones/s, 0 errores; 12 clientes → 164 peticiones/s, 0 errores. Con el volcado diferido apagado (comportamiento antiguo): 4 clientes → 14 peticiones/s y 9 de 160 con 500; 12 clientes → 25 peticiones/s y **304 de 480 con 500**.
> Variables nuevas (documentadas en `HOSTING.md`): `GUILDA_USO_DIFERIDO`, `GUILDA_USO_VOLCADO_SEG`, `GUILDA_USO_HILO`, `GUILDA_SYNC_VENTANA_SEG`. Sin cambio de esquema.
> **Lo que sigue pendiente de este bloque:** `api_idempotencia` sigue siendo una tabla de referencia (se escribe en cada POST con `Idempotency-Key`; ya sin la purga global por petición y con 6 clientes escribiendo a la vez no hay errores): pasarla a distribuida es DB-05 (migración, tras el 26-oct 12:34). El cursor definitivo (PG-07) y el resto de la sobrecarga por petición (PG-02/03) no se han tocado.



Se deja escrito para poder ejecutarlo en cuanto lo autorices (D21). **No se ha tocado código.** Todo cambio se prueba en los dos motores con la copia aislada (`scripts/probar.sh`) y se aplica sin migración de esquema (por eso puede hacerse durante la ventana de vuelta atrás, que prohíbe cambios de esquema hasta el 26-oct 12:34).

### D.1 PG-04 — sacar de la ruta caliente las escrituras en tablas de referencia

**Dónde se escribe hoy (por petición):**

| Escritura | Código | Tabla (referencia en Citus) |
|---|---|---|
| `UPDATE tokens_api SET ultimo_uso_en = ?, ultima_ip = …` | `app/db_plataforma.py:1371` (`autenticar_token_completo`) | `tokens_api` |
| `INSERT INTO tokens_api_uso … ON CONFLICT` | `app/db_plataforma.py:1399` (`registrar_uso_token`), llamada desde `app/rutas_api.py:113` (cada respuesta de la API) y `mcp_tools/__init__.py:883` (cada llamada MCP) | `tokens_api_uso` |
| `INSERT INTO mcp_uso … ON CONFLICT` y `DELETE FROM mcp_uso WHERE dia < ?` | `app/db_plataforma.py:1862–1869` | `mcp_uso` |
| `INSERT INTO api_idempotencia` + `DELETE … WHERE creado_en < ?` **en cada reserva** | `app/db_plataforma.py:1766–1773` | `api_idempotencia` |

**Diseño.** Un módulo pequeño, `app/uso_diferido.py`:

1. **Acumuladores en memoria** protegidos por un cerrojo: `{(token_id, día): [llamadas, errores]}`, `{(día, usuario_id, herramienta): [llamadas, errores]}` y `{token_id: (última_vez, ip)}`.
2. `registrar_uso_token()` y el registro de `mcp_uso` **solo suman en memoria** (microsegundos, sin base de datos).
3. **Un único hilo de volcado** (daemon) cada **30 s** (configurable, `GUILDA_USO_VOLCADO_SEG`) hace **una transacción corta** con `INSERT … ON CONFLICT DO UPDATE` por lote (`executemany`) y vacía lo volcado; y un volcado final en `atexit` y en `SIGTERM`.
4. `autenticar_token_completo`: **solo** escribe `ultimo_uso_en` si el valor leído tiene más de **60 s** (ya se lee en la consulta) y, aun así, lo encola en el acumulador en vez de escribirlo en línea. La purga de inactividad (`DELETE FROM tokens_api …`, por inactividad de 90 días) sigue en línea porque es rara.
5. `mcp_uso`: la purga `DELETE … WHERE dia < ?` pasa a la tarea diaria de mantenimiento (no en cada llamada).
6. `api_idempotencia`: la limpieza por antigüedad se saca de `idempotencia_reservar` a la misma tarea de mantenimiento; la reserva queda en un único `INSERT … ON CONFLICT DO NOTHING RETURNING`. Como solo se ejecuta cuando llega la cabecera `Idempotency-Key`, el coste en la ruta caliente de lecturas es cero. **Si aun así hubiese contención**, se pasa la tabla a distribuida por `tenant_id` (migración `.citus.sql`; fuera de la ventana de vuelta atrás).
7. **Lecturas de uso** (`uso_de_token`, panel del backoffice, `/tokens/{id}/uso`): suman además lo que aún está en memoria del proceso para no «perder» el último medio minuto; si hay varios procesos, se documenta el retraso de hasta 30 s.

**Pruebas:** (a) test unitario del acumulador (suma, volcado, volcado final, concurrencia con 50 hilos); (b) **test de concurrencia de la API** de PG-00 sobre PostgreSQL+Citus; (c) la suite completa en los dos motores; (d) comprobar que `GET /tokens/{id}/uso` y el panel de actividad MCP siguen cuadrando.

**Revierte:** una variable (`GUILDA_USO_DIFERIDO=0`) devuelve la escritura en línea. **Riesgos:** pérdida de ≤ 30 s de contadores en una caída; el uso del token deja de ser «en tiempo real» (irrelevante para su finalidad, que es estadística y detección de tokens inactivos).

### D.2 PG-00 — prueba de concurrencia de la API (y revisión de vecinos)

- Convertir `docs/anexos-app-movil/prueba_concurrencia_api_prototipo.py` en un test de `tests/` marcado para PostgreSQL: 3 despachos, 12 personas, 4/8/12 clientes simultáneos pidiendo `/auth/me`, `/mi-dia`, `/tareas-outlook`, `/notificaciones`, y **escrituras** (`POST /notas`, `POST /tareas-outlook` con `Idempotency-Key`, `POST …/completar`). **Exigir 0 respuestas 5xx** y un p95 razonable. Lo mismo con un cliente MCP.
- **Revisión de todas las escrituras por petición sobre tablas de referencia**: lista de las 18 tablas de referencia (`tenants`, `usuarios`, `usuarios_tenants`, `usuario_perfil`, `tokens_api`, `tokens_api_uso`, `api_idempotencia`, `mcp_uso`, `comunicados_cerrados`, `dispositivos_push`, `ver_como_tokens`, `auditoria_control`, …) y, para cada una, quién la escribe y con qué frecuencia (`usuarios.ultimo_acceso` ya está limitado por una condición de antigüedad). Resultado esperado: solo escrituras raras (alta de usuario, registro de dispositivo, cierre de un comunicado).
- Añadir a la **revisión semanal** (`scripts/revision_postgres.py`) un control que cuente interbloqueos (`pg_stat_database.deadlocks`) y falle con aviso si aumentan.

### D.3 PG-01 — parche del cursor de `/sync` (ventana de seguridad)

**Qué cambia** (solo `app/db_plataforma.py`, `cambios_desde` y `cursor_cambios_actual`; ni esquema ni cliente):

1. `cambios_desde` solo devuelve filas con `creado_en` anterior a *ahora − 5 s* (`GUILDA_SYNC_VENTANA_SEG`, por defecto 5) y el cursor nuevo es el mayor `id` **de esas filas** (nunca el máximo global).
2. `cursor_cambios_actual` (cursor inicial) aplica la misma ventana.
3. La app y los integradores ya tratan las altas como idempotentes (upsert por id); se recomienda reenviar desde `cursor − 0` sin solape porque la ventana ya cubre transacciones de hasta 5 s. **Límite honesto:** una transacción que dure más de 5 s puede seguir perdiéndose; por eso el diseño definitivo es PG-07.
4. **Prueba de regresión** con el guion de dos transacciones (A empieza antes y confirma después de B): hoy **falla**, con el parche **pasa**.

**Efecto:** los cambios llegan con ≤ 5 s de retraso (imperceptible para tareas/notas). **Revierte:** `GUILDA_SYNC_VENTANA_SEG=0`.

### D.4 Orden y esfuerzo

| Paso | Qué | Tiempo | Dependencia |
|---|---|---|---|
| 1 | PG-00: test de concurrencia (falla hoy) | 2 h | — |
| 2 | PG-04: acumulador de uso + hilo de volcado + purgas fuera de línea | 4–5 h | 1 |
| 3 | PG-01: ventana del cursor + test | 2 h | — |
| 4 | Suites completas en PostgreSQL y SQLite; medida antes/después con `medir_api_movil_prototipo.py` | 2 h | 2, 3 |
| 5 | Despliegue (reinicio de `guilda-work` y `guilda-work-mcp` por tu parte) y vigilancia 48 h con `pg_stat_database.deadlocks` | — | 4 |

**Total ≈ 1 día** y **ningún cambio de esquema**, así que cabe dentro de la ventana de vuelta atrás.


---

## E. Datos nuevos o ampliados que necesita la app (esquema PostgreSQL)

Todo esto son **migraciones numeradas** (`app/bd/migraciones/NNN_x[.mt|.citus].sql`; hoy **no hay ninguna** aplicada, así que la primera —que además sirve de criterio para retirar SQLite— puede ser una de estas) y **no pueden aplicarse antes del 26-oct 12:34** (ventana de vuelta atrás). Convenciones del proyecto: toda tabla distribuida lleva clave primaria que incluye `tenant_id`, política RLS `aislamiento` y distribución `colocate_with => 'abogados_ajustes'`; en las tablas de referencia **no se escribe en la ruta caliente** (ADR §340).

| ID | Cambio | Detalle | Distribución | Ola | Resuelve |
|---|---|---|---|:-:|---|
| **DB-01** | `dispositivos_push` → **`dispositivos_app`** | Añadir `idioma`, `app_version`, `plataforma_version`, `despacho_activo_id`, `notificaciones_on`, `ultimo_visto_en`. **Hoy** el alta/refresco es un `INSERT … ON CONFLICT DO UPDATE` en **cada arranque de la app** sobre una **tabla de referencia**: pasa a «**leer antes de escribir**» (solo se escribe si algún dato cambió o si `ultimo_visto_en` tiene > 24 h) | Referencia (es de la persona, no de un despacho) | 0 | P-03 (arranques matinales), S-13 |
| **DB-02** | Preferencias de aviso **por tipo** | Hoy son 5 columnas fijas en `usuario_perfil` (`notificar_push_vencimientos/tiquets/correo/portal_mensajes`, resumen semanal) frente a **30+ tipos de aviso**. Añadir `notif_prefs` (JSON `{tipo: {push, bandeja}}`) y mapear tipos antiguos a las columnas existentes; el servidor consulta antes de enviar | `usuario_perfil` (referencia, escritura rara) | 1 | S-05, §13.2 |
| **DB-03** | **`api_cambios` v2** (cursor seguro) | Columna `txid xid8 NOT NULL DEFAULT pg_current_xact_id()` + índice `(usuario_id, txid)` y `(usuario2_id, txid)`; consulta `txid >= cursor AND txid < pg_snapshot_xmin(pg_current_snapshot())` | Distribuida por `tenant_id` (como hoy) | 1 | P-01 |
| **DB-04** | `despacho_version` (solo si hay nodos de trabajo) | `(tenant_id, v)` con incremento bajo `pg_advisory_xact_lock` por despacho; `api_cambios.v` | Distribuida | 3+ | P-01 en multinodo |
| **DB-05** | **Uso de API/MCP e idempotencia fuera de las tablas de referencia** | Si la medida de PG-00 lo pide tras diferir el volcado: `tokens_api_uso`, `mcp_uso` y `api_idempotencia` pasan a **distribuidas por `tenant_id`** (el token lleva despacho; `PRIMARY KEY (tenant_id, token_id, dia)`) | Distribuida | 0–1 | P-03 |
| **DB-06** | Índices de búsqueda de texto | Columnas `busqueda tsvector GENERATED` (configuración `es_simple`) con GIN en `tareas_outlook` (asunto, cuerpo), `notas` (título, texto), `clientes_fiscales` (nombre, NIF normalizado), `contactos`; `pg_trgm` GIN sobre nombres | Las de cada tabla | 1–2 | P-08 |
| **DB-07** | Índices parciales de listados (a validar con `EXPLAIN` sobre datos de volumen) | Tareas abiertas por persona y vencimiento; vencimientos pendientes por despacho y fecha; notificaciones sin leer; correo por cuenta/carpeta/fecha | Las de cada tabla | 1–2 | P-06 |
| **DB-08** | Banderas de la app por despacho | `tenants.app_flags` (JSON) gestionado desde el backoffice; viaja en `/auth/me.app.flags` | `tenants` (referencia; escritura de backoffice, rara) | 1 | §13.5 |
| **DB-09** | Eventos de experiencia **agregados y anónimos** | `app_eventos_dia (tenant_id, dia, pantalla, evento, version_app, n, ms_p50, ms_p95)`; la app envía un lote cada vez que vuelve a primer plano (`POST /app/eventos`), **sin identificar a la persona** y **sin contenido** | Distribuida, `PRIMARY KEY (tenant_id, dia, pantalla, evento, version_app)` | 1 | A.10 (métricas de uso) |
| **DB-10** | Perfil sin el avatar en las lecturas habituales | `obtener_perfil_usuario` pasa a seleccionar columnas explícitas; `GET /avatar/{id}` con `ETag`/`Cache-Control`; reducir y recomprimir el avatar al subirlo (p. ej. 256 px, WebP/JPEG) | Sin cambio de esquema | 0 | P-12 |
| **DB-11** | **Sesiones de dispositivo con nombre** | `tokens_api.nombre_dispositivo` ya existe; añadir `plataforma`, `app_version`, `ultima_ip` visible en «Mis dispositivos» y revocación remota (token + concesión de cifrado) | `tokens_api` (referencia; el `ultimo_uso` se difiere por PG-04) | 5 | §13.4, S-13 |

**Datos que la app consume y ya existen** (sin cambio de esquema): `notificaciones`, `tareas_outlook` (con `version`), `vencimientos_fiscales`, `fichajes`, `ausencias`, `turnos`, `correo_mensajes`, `documentos`, `usuarios_tenants` (para el selector de despacho), `usuario_perfil.menu_prefs` (accesos fijados), `usuarios.tema/densidad/idioma`.

**Retención y privacidad:** `api_cambios` conserva 30 días (ya existe la purga); `app_eventos_dia` 13 meses; los avisos 90 días; nada de contenido de correo/documentos en eventos ni registros; las respuestas con datos de despachos con cifrado llevan `Cache-Control: private, no-store`.

**Verificación de cada migración:** `scripts/migrar_esquema_pg.py` en el ensayo con datos migrados, `verificar_migracion.py` (recuentos y sumas por columna), suites de los dos motores, y **ensayo de restauración** con `restaurar_postgres.sh` antes de aplicarla en producción.

---

## F. Calendario integrado desde hoy (24-oct-2026) y ventana de lanzamiento

**Restricciones fijas** (del plan de estabilización de PostgreSQL): vuelta atrás B abierta hasta el **lun 26-oct 12:34** (sin cambios de esquema hasta entonces) · primera revisión automática el 26-oct 07:30 · revisión manual con tráfico de entre semana el 27-oct · simulacro de restauración con configuración real el 31-oct · decisión sobre retirar SQLite **no antes del 7-nov** (uno de los criterios: una migración real aplicada en producción).

**Ventana de negocio.** Las gestorías tienen picos en **enero** (cierre del 4T y resúmenes anuales) y **abril–junio** (renta) y un valle en **noviembre–mediados de diciembre**: es el mejor momento para una **beta cerrada con despachos piloto**; conviene **no lanzar en enero**.

| Cuándo | Qué | Plan |
|---|---|---|
| **Sáb 24 – dom 25-oct** | Decidir D21; si hay visto bueno, **PG-00 + PG-04 + PG-01** (≈ 1 día, sin esquema) y reinicio de `guilda-work` y `guilda-work-mcp` (por tu parte; también activa el arreglo MCP `dcfade4`) | Este documento §D |
| **Lun 26-oct (12:34 en adelante)** | Se cierra la vuelta atrás B: se permiten migraciones. Vigilancia de `pg_stat_database.deadlocks` | Fase 12 |
| **26–30-oct** | Decisiones D1–D12 y D13–D21; abrir **cuentas de tienda y Firebase** (plazos largos); victorias rápidas de UX (A.13, ≈ 7 días de una persona, si D20) | Plan principal §9 |
| **Sem. 1–4 (26-oct → 20-nov)** | **Ola 0** (publicable, SDK generado, cliente v2, shell, tokens de diseño, i18n, cola) + PG-02/03/05/06 + **primera migración real** (DB-03 o DB-10/DB-06) | Plan principal §7 |
| **31-oct** | Simulacro de restauración (Fase 12) — incluir las tablas nuevas | Fase 12 |
| **≈ 7-nov** | Decisión sobre retirar SQLite (con la primera migración ya aplicada) | Fase 12 |
| **Sem. 4–9 (16-nov → 25-dic)** | **Ola 1** (Hoy, Tareas, Avisos, Notas, Búsqueda, IA) + PG-07…PG-11 + prueba de carga con perfil de app (PG-14) | Plan principal §7 + §B.8 |
| **≈ 1–5 dic** | **Beta interna** (tu equipo) con Ola 0 + primeras pantallas de la Ola 1 | §13.5 |
| **≈ 14–19 dic** | **Beta cerrada** con 3–5 despachos piloto: Hoy, Tareas, Avisos, Fichaje actual | §13.5 |
| **Navidad – 6 de enero** | Parada de cambios, solo correcciones; recogida de comentarios | — |
| **Enero** (pico fiscal) | Sin lanzamientos; Ola 2 (Gestoría) en desarrollo interno, con pruebas de uso en horas valle | Plan principal §7 |
| **Febrero – marzo** | Ola 2 y 3; **publicación en tiendas tras la Ola 2** (D1) antes de la campaña de renta | Plan principal §7 |
| **Abril – junio** | Campaña de renta: Ola 4 por bloques (según D4) sin tocar lo estable; Ola 5 a partir de julio | Plan principal §7 |

Este calendario **supone 1,5 personas dedicadas** y se desplaza semana a semana si no es así. Los hitos que **no** se negocian: PG-00/PG-04/PG-01 antes de cualquier uso intensivo de la API o del MCP por varias personas, y la beta solo después de PG-07 (cursor seguro) si se va a ofrecer modo sin conexión.
