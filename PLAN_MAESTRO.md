# Plan maestro de Guilda Work — semana del 13 al 19 de octubre de 2026

Documento vivo: es la base de trabajo de la semana, no un contrato. Cada bloque dice **qué**, **por qué** (con la evidencia que hay hoy en el código) y **cuándo se da por hecho**. Tamaños: **S** (< 2 h), **M** (media jornada), **L** (jornada), **XL** (más de una jornada: hay que partirlo).

---

## 0. Resumen en un minuto

1. **Guilda Work ya es una plataforma de gestoría muy completa** (tareas, correo, fiscal, fichaje, portal de cliente, asistente de IA, MCP/API, backoffice, 2.331 tests). Lo que le falta no es amplitud sino **tres cosas**: una base de diseño uniforme, un núcleo de «cliente y expediente» que no esté atado a lo fiscal, y una forma limpia de **activar módulos** por despacho.
2. **El hallazgo clave para las expansiones**: hoy «cliente» significa `clientes_fiscales` (solo `nombre`, `nif`, `notas`) y «vencimiento» significa `vencimientos_fiscales` (modelo + periodo). Abogados e inmobiliarias no encajan ahí. Antes de crear módulos hay que **extraer un núcleo genérico** (clientes, expedientes, plazos, tiempo, documentos, portal) y colgar cada vertical de él. La gestoría pasa a ser un módulo más, sin romper nada.
3. **La infraestructura comercial ya existe**: `planes_guilda`, `extras_guilda`, `tenants_extras_activos` y `tenants_herramientas_ocultas`. Un módulo = un extra activable por despacho. No hay que inventar un sistema de licencias.
4. **Realismo**: una semana da para el diseño uniforme, el núcleo genérico y un **MVP utilizable de cada vertical**, no para dos productos completos. El plan de abajo está pensado así; lo que no cabe está en el §9.

---

## 1. Principios (para decidir cuando haya dudas)

1. **Núcleo + módulos independientes.** Un módulo no importa a otro; ambos hablan con el núcleo. Un despacho de abogados no ve la palabra «modelo 303», una inmobiliaria no ve «minuta».
2. **Lo ya hecho se reutiliza**: ayuda contextual, asistente de IA con herramientas por grupos, MCP, API, portal, PDF, notificaciones, auditoría. Cada módulo nuevo se «enchufa» a esas piezas, no las duplica.
3. **Ningún HTML «de fábrica».** Todo control sale de un componente del sistema de diseño (§3). Un test lo vigila (§3.3).
4. **Lógica comprobable.** Cualquier cálculo con consecuencias (plazos, fechas límite, importes, comisiones) vive en una función pura con tests, nunca en una plantilla ni en JavaScript.
5. **Datos sensibles de verdad.** Abogados (secreto profesional) e inmobiliarias (datos personales y bancarios de compradores) elevan el listón de seguridad y de RGPD (§8).
6. **Cada día termina desplegable**: tests en verde, documentado en `HOSTING.md`, ayuda y traducciones al día.

---

## 2. Estado actual (inventario honesto)

| Área | Qué hay | Huecos que se ven en el código |
|---|---|---|
| Trabajo diario | Tareas (lista/tablero/calendario/Mi día/carga de equipo/recurrentes/plantillas/dependencias/cronómetro), notas, proyectos, tiquets | Sin vista de **línea de tiempo/Gantt**; los informes de tiempo no se agrupan por cliente ni se pueden facturar |
| Correo | IMAP/SMTP, equipo, reglas, categorías, programados, IA | Los adjuntos de correo → expediente son manuales; sin **plantillas por tipo de trámite** con variables de cliente enriquecidas |
| Fiscal (gestoría) | Clientes fiscales, vencimientos, generación masiva, recordatorios, papelera, calendario, documentos, mensajes de portal, cobros Stripe | El **cliente solo tiene nombre/NIF/notas**: sin contactos, tipo de persona, régimen, actividad, representante, IBAN, tags |
| Fichaje | Registro horario con hash encadenado, geolocalización opcional, correcciones, PDF/CSV/JSON | Sin **vacaciones/ausencias/permisos**, sin cuadrante de turnos, sin bolsa de horas |
| Portal de cliente | Acceso por enlace, documentos, mensajes, pagos | El cliente no ve **su estado** (qué falta, qué está presentado); sin firma desde el portal |
| IA | Chat con ~100 herramientas por grupos, soporte de plataforma, informes | Sin contexto de **cliente/expediente abierto**; sin plantillas de prompt por módulo |
| Plataforma | Planes/extras, backoffice, MCP, API versionada, webhooks, CSP forzada, 2FA | El menú no es **dinámico por módulo**; `mcp_tools.py` (2.398 líneas) y `db.py` (13.396) son monolitos |
| Móvil (Flutter) | App con fichaje, tareas, notificaciones | Falta campo 2FA, tareas compartidas, resumen semanal de fichaje (requiere `flutter pub get`) |

Cifras de la auditoría de interfaz (hoy):

| Vestigio | Cantidad | Dónde se concentra |
|---|---|---|
| `<select>` nativos | 114 | correo_bandeja (11), tarea_outlook_editar (9), tareas_lista (8), tareas_recurrentes (7), proyecto_resumen (7) |
| `style="…"` en línea | 130 | mis_dispositivos (14), fiscal_cliente_detalle (8), inicio, estadisticas, correo_bandeja (7 c/u) |
| `<button>` sin clase | 32 | correo_redactar (8), correo_bandeja (7), correo_ajustes (6), _ajustes_apariencia (5) |
| checkbox/radio sin estilo propio | 19 | correo_ajustes (5), correo_cuentas (4), ia_ajustes (3), fiscal_cliente_editar (3) |
| `confirm()`/`alert()`/`prompt()` del navegador | 9 | correo_redactar, correo_editor.js, correo_seleccion.js, ia_asistente.js, csp_compat.js, toasts.js |
| `<input type="date">` nativos | 32 | correo_bandeja, historial, fichajes |

---

## 3. Uniformidad gráfica: un sistema de diseño de verdad (Días 1–2)

**Objetivo**: que no quede ningún control «de fábrica» y que una pantalla nueva se monte juntando piezas, no escribiendo CSS.

### 3.1 Componentes a crear o consolidar (`app/templates/_ds/*.html` + `app/static/ds.css`/`ds.js`)

| Componente | Sustituye a | Tamaño |
|---|---|---|
| **Diálogo de confirmación** (modal accesible, con foco atrapado y Esc) | `confirm()`/`prompt()`/`alert()` (9 usos) | M |
| **Toasts** unificados (ya hay `toasts.js`: extender a éxito/error/deshacer) | `alert()` y mensajes sueltos | S |
| **Selector** (ya existe buscador ≥ 6 opciones): estilarlo siempre, también con pocas opciones, con teclado y móvil | 114 `<select>` | L |
| **Selector de fecha y de rango** (calendario propio, atajos «hoy / esta semana / este trimestre») | 32 `<input type="date">` | L |
| **Interruptor (switch), casilla y radio** con el estilo del sistema | 19 sin estilo | S |
| **Botón** (primario / secundario / peligro / icono / cargando) como macro `boton()` | 32 sin clase | S |
| **Tabla de datos** (cabecera fija, orden, densidad, selección múltiple, acciones por fila, estado vacío, paginación) | tablas ad hoc | L |
| **Estados**: vacío con ilustración y acción, cargando (esqueletos), error con reintento | textos sueltos | M |
| **Cabecera de página + migas + acciones** (macro `pagina()`) | cabeceras repetidas | S |
| **Chips/etiquetas y avatares** | variantes locales | S |
| **Formulario por secciones** (etiqueta, ayuda, error en línea, obligatorio) | formularios a mano | M |

### 3.2 Migración de pantallas (por orden de impacto)
1. Correo (bandeja, redactar, ajustes, cuentas): es lo más usado y lo más «de fábrica».
2. Fiscal (cliente detalle/editar, vencimientos, generar, recordatorios).
3. Ajustes (IA, apariencia, dispositivos) y fichaje.
4. Tareas (lista, recurrentes, plantillas, Outlook).
5. Portal de cliente y backoffice (verificar que usan los mismos componentes, no copias).

### 3.3 Candado automático
Un test (`tests/test_sistema_diseno.py`) que **falla** si aparece un `confirm(`, `<select` sin componente, `<button>` sin clase, `style="` fuera de una lista permitida, o un color hexadecimal fuera de los tokens. Se arranca con la lista de excepciones actual y se va vaciando: así no se vuelve atrás.

### 3.4 Pulido transversal
- Tipografía y espaciado en una escala única (tokens ya iniciados en `superficies.css`); revisar 320 px, 768 px y 1440 px en cada pantalla migrada.
- Movimiento sobrio (150–200 ms) y `prefers-reduced-motion`.
- Atajos de teclado y paleta de comandos (`Ctrl+K`) que unifique buscar, ir a pantalla y acciones; reutiliza la búsqueda global que ya existe. **M**
- Tema claro/oscuro y densidad: pasar de «solo navegador» a **preferencia guardada en la cuenta** (hoy vive en `localStorage`; así el asistente también podrá cambiarla y se verá igual en el móvil). **S**

**Hecho cuando**: el test candado pasa con la lista de excepciones vacía para las pantallas migradas, y una persona nueva no distingue pantallas «antiguas» de «nuevas».

---

## 4. Núcleo genérico: clientes y expedientes (Día 3)

Sin esto no hay módulos independientes. Se hace **sin tocar lo fiscal existente** (migración aditiva, con vistas de compatibilidad).

### 4.1 Cliente completo (`contactos`)
- Tipo: persona física / jurídica; datos fiscales; representante legal; **varios contactos** por cliente (nombre, cargo, email, teléfono, rol); direcciones; IBAN opcional (cifrado); idioma preferido de comunicación; **etiquetas libres**; origen (cómo llegó); responsable interno.
- `clientes_fiscales` pasa a ser «cliente + ficha fiscal»; la ficha fiscal (régimen, actividad, modelos) cuelga del cliente en el módulo Gestoría.
- Fusión de duplicados y alta rápida desde el correo (ya existe «tarea desde correo»: añadir «cliente desde remitente»). **L**

### 4.2 Expediente (`expedientes`)
Contenedor genérico de trabajo para un cliente: título, tipo (lo define el módulo), estado con flujo configurable, responsable, equipo, fechas clave, **documentos, tareas, correos, notas, tiempos e importes** enlazados. Es el equivalente de «proyecto» pero orientado a cliente y con ciclo de vida.
- `tipos_expediente` (definidos por módulo): campos propios, estados, plazos que genera y plantillas de tareas.
- Línea de tiempo del expediente (todo lo que pasa, con quién y cuándo; ya existe `tarea_actividad` como patrón). **L**

### 4.3 Plazos (`plazos`)
Generaliza `vencimientos_fiscales`: fecha límite, origen, aviso escalonado (ya existe `vencimientos_escalados`), responsable y estado. **El cálculo de fechas va en un módulo puro** (`app/calendario_plazos.py`) con reglas de días hábiles inyectables por módulo (festivos estatales/autonómicos/locales; en abogados, días hábiles procesales). **M**

### 4.4 Tiempo y facturación (`tiempo_facturable`)
- El cronómetro de tareas ya existe: añadir **cliente/expediente, tarifa, facturable sí/no**.
- Hoja de horas por persona/cliente/expediente y exportación a PDF/CSV (reutiliza lo hecho esta semana).
- Propuesta de factura/minuta desde horas (conecta con FacturaScripts vía el proxy y el MCP que ya existen). **L**

### 4.5 Plataforma de módulos
- Registro de módulos (`app/modulos/__init__.py`): `id`, nombre, icono, rutas, entradas de menú, permisos, herramientas del asistente, artículos de ayuda, plantillas de expediente.
- Activación por **extra del despacho** (reutiliza `tenants_extras_activos`); el backoffice ya sabe asignarlos. Menú, ajustes, asistente (grupos de herramientas) y MCP se construyen a partir de los módulos activos.
- Permisos por módulo y por expediente (quién ve qué dentro del despacho). **L**

**Hecho cuando**: la gestoría actual sigue funcionando igual (tests existentes en verde) y se puede crear un cliente con contactos y un expediente con plazos y horas desde el módulo «Base».

---

## 5. Módulo Gabinete de abogados (Día 4, MVP)

> Alcance de dominio **a validar con una persona del sector** antes de darlo por bueno (§10). Lo marcado con (*) depende de normativa que hay que confirmar.

### 5.1 MVP
| Funcionalidad | Detalle | Tamaño |
|---|---|---|
| **Expedientes judiciales y extrajudiciales** | Número de procedimiento, juzgado, jurisdicción, procurador, partes (cliente, contraparte, letrados), fase, cuantía, estado | L |
| **Plazos procesales (*)** | Cálculo en días hábiles (agosto inhábil salvo excepciones, festivos del partido judicial), aviso 7/3/1 días, «plazo fatal» destacado, doble revisión por otra persona | L |
| **Notificaciones** | Alta rápida desde correo/PDF de una resolución: genera el plazo y la tarea (la IA propone la fecha; la persona confirma) | M |
| **Hoja de encargo y minutas** | Plantilla de encargo con firma electrónica (ya hay Documenso); minuta desde horas facturables | M |
| **Provisión de fondos y cuenta cliente** | Entradas/salidas por expediente, saldo, aviso de saldo bajo | M |
| **Conflicto de intereses** | Al dar de alta un cliente o contraparte, búsqueda de coincidencias en partes de otros expedientes | M |
| **Agenda de vistas** | Señalamientos con recordatorio, sala, desplazamiento; sincroniza con el calendario | S |
| **Portal del cliente** | Estado del asunto en lenguaje llano, documentos compartidos, mensajes seguros | M |
| **Asistente de IA** | Resumen del expediente, propuesta de escrito a partir de plantillas, **nunca** envía nada sin confirmación | M |

### 5.2 Después del MVP (semana 2+)
LexNET/Cl@ve (integración, no obligatoria al principio), turno de oficio y justicia gratuita, tarifas por tipo de asunto, estadísticas de rentabilidad por expediente, biblioteca de modelos de escritos, control de caducidad de poderes.

### 5.3 Riesgos específicos
Secreto profesional → cifrado de documentos del expediente y **registro de accesos** (ver §8); error de plazo con consecuencias legales → doble confirmación, pruebas de cálculo con casos reales aportados por una letrada y aviso visible de que «la herramienta ayuda, no sustituye la comprobación».

---

## 6. Módulo Inmobiliaria (Día 5, MVP)

> Igual que arriba: dominio a validar con una agencia real. (*) = normativa a confirmar (p. ej. fianzas de alquiler, certificado energético, obligaciones por comunidad autónoma).

### 6.1 MVP
| Funcionalidad | Detalle | Tamaño |
|---|---|---|
| **Inmuebles** | Ficha: tipo, dirección, referencia catastral, superficie, habitaciones, características, estado comercial (captación / en venta / en alquiler / reservado / vendido), propietario(s), precio y su histórico, fotos y documentos (nota simple, certificado energético (*), cédula) | L |
| **Captación y pipeline** | Tablero por fases (contacto → valoración → mandato firmado → publicado → visitas → oferta → arras → cierre) con el tablero que ya existe como patrón | L |
| **Demandas (compradores/inquilinos)** | Qué buscan (zona, presupuesto, requisitos) y **cruce automático** con los inmuebles disponibles, con puntuación explicable | L |
| **Visitas** | Agenda con enlace de reserva (ya existe el módulo de citas), recordatorios, valoración tras la visita, ruta del día | M |
| **Contratos desde plantilla** | Mandato de venta, arras, alquiler, reserva: variables del inmueble y de las partes, firma electrónica, versión archivada | M |
| **Honorarios y comisiones** | Cálculo por operación y por agente (función pura con tests), estado de cobro | M |
| **Portal del propietario** | Visitas realizadas, ofertas recibidas, documentos, informe mensual en PDF | M |
| **Publicación** | Exportar a un formato de feed estándar para portales (a decidir cuáles) | S (solo exportar) |
| **Asistente de IA** | Redacta el anuncio a partir de la ficha (en los cuatro idiomas), resume una visita, sugiere cruces | M |

### 6.2 Después del MVP
Integraciones directas con portales, tasación orientativa por comparables, gestión de alquileres (recibos, fianzas, revisiones de renta con IPC, incidencias), comunidad de propietarios, informes de mercado.

### 6.3 Riesgos específicos
RGPD (datos de compradores, DNI, solvencia) → mínimos, finalidades claras y caducidad; fotos pesadas → almacenamiento en MinIO (ya está), miniaturas y límites.

---

## 7. Mejoras de lo existente (transversal a la semana)

### 7.1 Gestoría — lógicas más certeras
1. **Vencimientos automáticos por perfil fiscal**: del régimen/actividad del cliente deducir qué modelos y periodos aplican (con revisión humana); hoy se generan por selección manual. **L**
2. **Calendario fiscal con festivos** (nacional, autonómico y local del cliente) y desplazamiento del vencimiento cuando cae en inhábil; función pura con tests. **M**
3. **Estado por cliente de un vistazo**: semáforo (al día / pendiente de documentación / atrasado) en la lista de clientes y en el portal. **M**
4. **Solicitud de documentación recurrente** con seguimiento: pedir → recordar → recibir → archivar en la carpeta correcta (cierra el ciclo que hoy son tres pantallas). **L**
5. **Plantillas de «alta de cliente»**: al crear un cliente con perfil X se generan sus tareas, vencimientos y solicitud de documentos. **M**
6. **Informe mensual al cliente** en PDF con su estilo (modelos presentados, pendientes, próximos vencimientos) y envío programado. **M**
7. **Cobros**: estado de cuotas por cliente, recordatorio de impago, conciliación con Stripe ya integrado. **M**

### 7.2 Tareas y proyectos
Vista de línea de tiempo; dependencias visibles en el tablero; **subtareas con porcentaje** y estimación acumulada; vistas guardadas compartibles; acciones masivas con deshacer (toast); «tareas bloqueadas» destacadas. **L**

### 7.3 Correo
Plantillas con variables del cliente/expediente; **vincular un correo a un expediente** con un clic (y archivar adjuntos donde toca); respuestas sugeridas por IA con revisión; búsqueda guardada; resumen de hilos largos. **L**

### 7.4 Fichaje
**Ausencias, vacaciones y permisos** con aprobación y saldo; cuadrante de turnos; bolsa de horas; avisos de jornada excedida; informe mensual por persona en PDF (parte de lo de esta semana). **L**

### 7.5 Portal de cliente
Panel de **estado** (qué hemos hecho, qué falta de tu parte), **firma desde el portal**, subida con tipos de documento guiados, notificaciones por correo con el diseño ya hecho, idioma por cliente. **L**

### 7.6 Asistente de IA
- **Contexto de cliente/expediente**: si estás en una ficha, «resume este cliente» no necesita que lo busques.
- Plantillas de prompt por módulo y por rol; atajos contextuales.
- **Evaluación continua**: ampliar `tests/datos/evaluacion_herramientas.py` con casos de cada módulo (el candado de calidad que ya tiene el asistente).
- **Cuadro de mandos de soporte**: qué preguntas no encuentran ayuda (los tiquets que crea el propio asistente) → artículos que faltan. **S**

### 7.7 Backoffice
Alta guiada de despacho **con elección de módulos**, facturación de planes/extras visible, métricas por módulo, y «ver como» ya existente con registro. **M**

### 7.8 Móvil
Campo de 2FA, tareas compartidas, resumen semanal de fichaje, ausencias, y notificaciones del módulo activo. `flutter pub get` autorizado. **L**

### 7.9 Informes y exportaciones
Una sola **capa de informes** (PDF/CSV/XLSX) con cabecera de despacho, logo y estilo común; hoy cada exportación pinta su PDF a su manera. Cabecera/pie, paginación y fuentes con soporte completo de catalán/francés. **M**

---

## 8. Seguridad, privacidad y calidad (todos los días, con cierre el Día 7)

| Tema | Acción | Tamaño |
|---|---|---|
| **Registro de accesos** a expedientes, clientes y documentos (quién abrió qué) | Tabla de auditoría consultable por el responsable del despacho; imprescindible para abogados | M |
| **Cifrado por despacho** (documentos y correos) | Ver §8.1–8.3: capa de almacenamiento el Día 3, documentos el Día 7, correo y concesiones MCP/API/Hydra en la semana 2 | XL |
| **Retención y borrado RGPD** | Política por tipo de dato, exportación del interesado, borrado con constancia | M |
| **Permisos por expediente** | Visibilidad restringida (asuntos confidenciales) | M |
| **Tope y rotación de secretos** | Rotar la contraseña de la base de Documenso (lo haces tú), revisar caducidad de tokens API | S |
| **Rendimiento** | Índices y paginación en listas grandes (200+ clientes ya es el caso real), medir con datos sintéticos de 5.000 clientes | M |
| **Partir los monolitos** | `db.py` (13.396 líneas) y `mcp_tools.py` (2.398) en paquetes por dominio, **sin cambiar comportamiento** (los tests son la red de seguridad) | L |
| **Accesibilidad** | Pasada con lector de pantalla y teclado por las pantallas migradas; contraste AA medido por test | M |
| **Observabilidad** | Monitor `/health` en Uptime Kuma (tuyo), alertas de errores de módulo | S |
| **Copias** | Prueba de **restauración** de Restic cada semana, con aviso si falla | S |

---

### 8.1 Cifrado por despacho: documentos **y correos**, con acceso de IA, MCP y API (diseño)

**Requisito (12 oct)**: todo el contenido de un despacho —documentos de clientes, expedientes, portal **y correos**— se cifra con la clave de **ese despacho**; y aun así la IA, los MCP y las API del propio despacho pueden leerlo todo. Hydra hace de «paso previo» para dar ese acceso.

**El problema que hay que resolver.** Si la clave solo vive en la sesión de una persona, nada puede leer sin ella: ni el correo que llega de madrugada, ni un MCP externo, ni un resumen programado. Hay que separar **escribir** (que no necesita desbloqueo) de **leer** (que sí).

**Diseño: cifrado de sobre con clave pública del despacho**
- Cada despacho tiene un **par de claves**. La **pública** se guarda en claro y la usa el servidor para cifrar **sin desbloqueo** (cada documento y cada correo recibido se cifran en el momento de entrar, con su clave de datos AES-256-GCM, que a su vez se cifra con la pública).
- La **privada** solo existe cifrada: protegida por la **frase de paso** (derivada con Argon2id) y por la **clave de recuperación** impresa. Para leer hay que desbloquearla.
- **Desbloqueo = presencia**: la privada descifrada vive solo en memoria, ligada a una sesión o a una concesión (abajo), con caducidad, y nunca en disco, en logs ni en copias.

**Quién puede leer y cómo (§8.2)**: sesión de una persona del despacho (con frase de paso), asistente de IA interno (hereda la sesión), **concesiones** para MCP/API/OAuth (clave envuelta con el secreto del token) y tareas programadas (solo si el despacho las autoriza).

**Tres niveles de reserva por despacho** (se elige al activar el cifrado y se puede cambiar después; el cambio re-cifra los metadatos en segundo plano y es reversible)

| Dato | **Laxo** | **Medio** | **Estricto** |
|---|---|---|---|
| Contenido de documentos y adjuntos | Cifrado | Cifrado | Cifrado |
| Cuerpo del correo | Cifrado | Cifrado | Cifrado |
| Asunto del correo | En claro | **Cifrado** | Cifrado |
| Remitente, destinatarios | En claro | En claro | **Cifrados** |
| Fecha, carpeta, estado leído, tamaño | En claro | En claro | En claro (orden y retención; sin ellos no se puede listar ni purgar) |
| Nombre de archivo y título de documentos/notas | En claro | **Cifrado** | Cifrado |
| Categoría y cliente/expediente asociados | En claro | En claro | **Cifrados** (solo identificadores internos opacos en claro) |
| Listados y búsqueda por cabecera | Sin desbloqueo | Remitente y fecha sin desbloqueo; asunto con desbloqueo | Todo con desbloqueo |
| Índices y *embeddings* | En memoria al desbloquear (no en claro) | Igual | Igual |
| Sugerencia de uso | Gestoría (volumen alto, poca sensibilidad por mensaje) | Inmobiliaria y despachos mixtos | Gabinete de abogados (secreto profesional) |

- Las **reglas y categorías automáticas** del correo se aplican al entrar, con el mensaje aún en claro en el servidor, y su resultado se guarda con el nivel que toque; por eso funcionan igual en los tres niveles.
- Las **notificaciones** («correo nuevo de…», vencimientos) se generan también al entrar, antes de cifrar.

**Consecuencias que hay que asumir**
- Con el despacho **bloqueado** (nadie con sesión y sin concesión activa) la IA, el MCP y las búsquedas **no ven** lo cifrado: es la garantía, no un fallo. Hay que mostrar el estado («Documentos protegidos: desbloquea para que el asistente los lea») en lugar de devolver vacío.
- Cifrar al entrar implica que el servidor **sí ve el contenido** un instante (inevitable: el correo llega en claro por IMAP). La garantía es de **reposo y de copias**, no de «el servidor nunca lo ve». Debe decirse así en la política de privacidad.
- La búsqueda semántica sobre miles de documentos en memoria cabe bien (decenas de miles de vectores); si algún despacho lo supera, se pasa a índice cifrado por bloques.
- Perder frase y clave de recuperación = datos irrecuperables (aviso explícito y confirmación de que se han guardado).
- Rotación de la clave del despacho: se re-envuelve la privada; solo si se sospecha compromiso se re-cifran las claves de datos (tarea larga en segundo plano).

### 8.2 Acceso de IA, MCP y API a lo cifrado (concesiones y Hydra)
1. **Asistente de IA interno**: lee con la sesión desbloqueada de quien pregunta, igual que hoy lee tareas o correo. Las herramientas devuelven un aviso claro si el despacho está bloqueado.
2. **Concesión** (`concesiones_clave`): al autorizar un acceso, una persona con el despacho desbloqueado **envuelve la clave privada con una clave derivada del secreto de ese acceso**. El servidor guarda solo la envoltura; cuando llega una petición con ese secreto, desenvuelve en memoria, lee y olvida. Revocar el acceso = borrar la envoltura (efecto inmediato).
3. **Hydra como paso previo (OAuth de MCP/ChatGPT/Claude)**: la pantalla de consentimiento que ya existe (`hydra_consentimiento.html`) gana un permiso nuevo, `guilda:documentos`. Al aceptarlo, pide la frase de paso (o usa la sesión ya desbloqueada) y crea la concesión ligada al token. Cada cliente OAuth ve **solo** lo que su alcance y su usuario permiten.
4. **Tokens de API personales** (`tokens_api`): al crear uno con el alcance de documentos, mismo paso; el token lleva la concesión.
5. **Tareas programadas** (resumen semanal, informe mensual, recordatorios con documentos): solo si el despacho activa una **concesión de servicio** con caducidad y alcance; por defecto no existe y esas tareas omiten lo cifrado.
6. **Auditoría**: cada lectura de contenido cifrado por IA/MCP/API queda en el registro de accesos (quién, qué, con qué token, cuándo). Tabla ya prevista en §8.
7. **Límites**: alcance por **módulo y por expediente** (un MCP puede leer «Inmobiliaria» y no «Abogados»), solo lectura por defecto, y topes por token (peticiones/día, tamaño).

### 8.2.1 Garantía: ningún nivel quita funciones a la IA, el MCP ni la API
Regla de diseño: **los niveles cambian qué hay en claro en reposo, no qué se puede hacer**. Para que sea verdad y no una intención:
1. **Una sola capa de lectura** (`almacen_seguro`): web, API, MCP, IA, exportaciones y portal piden los datos por ahí y reciben el mismo resultado en los tres niveles; nadie consulta las tablas «a pelo» para contenido protegido.
2. **El acceso que necesita la clave la trae consigo**: la sesión de una persona, la concesión de un token (§8.2) o la concesión de servicio de una tarea programada. Con cualquiera de ellas, el nivel Estricto se comporta como el Laxo: la diferencia es solo dónde se descifra.
3. **Búsqueda y filtros en el nivel Estricto**: un índice por despacho **en memoria**, que se construye al primer acceso con clave y se conserva con caducidad mientras haya sesión o concesión viva; las consultas posteriores son inmediatas. Objetivo a medir: < 2 s tras el calentamiento con 50.000 correos y 20.000 documentos (si no se cumple, índice cifrado por bloques).
4. **Lo que ocurre al entrar** (reglas, categorías, notificaciones, resumen o clasificación por IA si el despacho la tiene activada) se hace con el contenido en claro **antes de cifrar**, así que no depende del nivel ni del desbloqueo.
5. **Test de paridad** (`tests/test_paridad_niveles.py`): el mismo guion —listar, buscar por texto y por asunto, abrir, resumir con IA, herramientas MCP, endpoints de la API, exportar a PDF, portal— se ejecuta con los tres niveles y con sesión, concesión de token y concesión de servicio, y exige **resultados idénticos**. Un nivel que rompa una función no pasa la suite.
6. **Sin acceso con clave** (nadie con sesión ni concesión viva) ningún nivel descifra: se muestra el estado de «protegido» en la interfaz, en la respuesta de la API (código y mensaje claros, no vacío) y en el asistente, con instrucciones para desbloquear.

### 8.3 Qué entra cuándo (la parte que no cabe en un día)
- **Día 3 (obligatorio)**: toda escritura de documentos pasa por **una sola capa de almacenamiento** (`almacen_documentos`), ya preparada para cifrar. Así no habrá migración de formato después, aunque el cifrado se active más tarde.
- **Día 7**: primitivas (par de claves, sobre, frase y recuperación, desbloqueo en memoria) + cifrado de **documentos** de clientes y expedientes + lectura de la IA interna con sesión + registro de accesos.
- **Semana 2**: **correo cifrado** (ingreso, listados, búsqueda en memoria), **concesiones para MCP/API/Hydra**, tareas programadas con concesión de servicio, migración de lo ya guardado y panel de estado.
- Motivo: cada pieza se puede probar de extremo a extremo; el correo y las concesiones tocan IMAP, búsqueda, OAuth y MCP a la vez y merecen su propia semana en vez de hacerse deprisa.
- **Pruebas** de todo el bloque (incluido `test_paridad_niveles`, §8.2.1): ida y vuelta, clave equivocada, documento manipulado (GCM lo detecta), rotación, restauración desde copia Restic, acceso con concesión revocada, y un test que **recorre cada ruta de lectura** (web, API, MCP, IA, exportaciones, PDF, portal) y comprueba que ninguna devuelve contenido cifrado sin clave.

## 9. Calendario de la semana

| Día | Foco | Entregable verificable |
|---|---|---|
| **1 · mar 13** | Sistema de diseño: componentes base (confirmación, toasts, botón, switch/casilla, estados, formulario) + test candado con excepciones actuales | `_ds/` + `ds.css/js` + `test_sistema_diseno.py` |
| **2 · mié 14** | Selector y fecha propios; migrar correo, fiscal y ajustes; preferencia de tema/densidad en la cuenta | 0 `confirm()` y 0 botones sin clase en las pantallas migradas |
| **3 · jue 15** | **Núcleo**: contactos, expedientes, plazos (cálculo puro), tiempo facturable, registro de módulos y menú dinámico, **capa única de almacenamiento de documentos** (lista para cifrar) | Tests del núcleo; la gestoría sigue en verde |
| **4 · vie 16** | **Módulo Abogados MVP** (expediente judicial, plazos procesales, minutas, provisión, conflicto de intereses, portal) | Flujo extremo a extremo con datos de prueba |
| **5 · sáb 17** | **Módulo Inmobiliaria MVP** (inmuebles, pipeline, demandas con cruce, visitas, contratos, comisiones, portal propietario) | Flujo extremo a extremo con datos de prueba |
| **6 · dom 18** | Mejoras de gestoría (§7.1 prioritarias), informes unificados (§7.9), asistente con contexto de cliente/expediente | Vencimientos por perfil + informe mensual |
| **7 · lun 19** | Cierre: **cifrado de documentos** (primitivas, sesión desbloqueada, IA interna), seguridad/RGPD (registro de accesos, retención), rendimiento con datos grandes, accesibilidad, ayuda y traducciones ca/en/fr, `HOSTING.md`, despliegue guiado y retro | Suite completa verde + guía de despliegue |

**Si el tiempo aprieta** (en este orden se recorta): primero §7.4–7.8 que no sean críticos, luego la mitad «después del MVP» de cada módulo, nunca el sistema de diseño ni el núcleo: sin ellos los módulos nacen torcidos.

---

## 10. Decisiones

### 10.1 Tomadas (12 de octubre)
| Tema | Decisión | Consecuencia en el plan |
|---|---|---|
| Validación de dominio | Hecha por el responsable del producto | Los festivos, plazos y plantillas de cada vertical se cargan como **datos editables** a partir de lo validado (ver 10.2) |
| Cifrado de documentos | **Clave por despacho** | Cifrado «de sobre»: cada documento con su clave de datos, protegida por la clave del despacho; se descifra solo con sesión del despacho. Ver diseño en §8.1 |
| Nombre de los módulos | **Gestoría**, **Gabinete de abogados** e **Inmobiliaria** (los tres independientes y combinables) | Ids internos `gestoria`, `abogados`, `inmobiliaria`; menú, ayuda y backoffice usan estos nombres |
| Precio y empaquetado | **Cada módulo es un extra de pago**; el núcleo común va incluido | Cada módulo = una fila de `extras_guilda` con su `stripe_price_id`; sin plan nuevo. El backoffice ya los asigna y cobra |
| Alcance del cifrado y acceso de máquinas | **Documentos y correos** con la clave del despacho; **IA, MCP y API del despacho pueden leer todo** mediante concesiones, con Hydra como paso previo | Diseño de §8.1–8.2; el correo cifrado y las concesiones pasan a la semana 2 (§8.3) |
| Niveles de reserva | **Tres: Laxo, Medio y Estricto**, por despacho y cambiables; **ninguno puede quitar funciones a IA, MCP ni API** | Tabla de §8.1 y garantía con test de paridad en §8.2.1 |
| Recuperación de la clave | **Frase de paso + clave de recuperación impresa**, mostrada una sola vez | Sin ellas los documentos son irrecuperables: el aviso al activarlo debe ser explícito y exigir confirmar que se ha guardado |
| Orden de construcción | **Abogados antes que Inmobiliaria** | Como en el calendario (Día 4 y Día 5) |
| Móvil | `flutter pub get` autorizado | Entra en el Día 6 (campo 2FA, tareas compartidas, resumen semanal, ausencias) |

### 10.2 Abiertas
1. **Material de dominio**: **se deja «sin validar»** (decidido): plazos, festivos, plantillas y reglas de comisión se cargan como datos de ejemplo editables, marcados visiblemente como «sin validar» en la interfaz y en la ayuda, hasta que se sustituyan.
2. **Producción (tuyo, más adelante)**: rotar la contraseña de Documenso y crear el monitor `/health` en Uptime Kuma.
3. **Nivel por defecto de cada módulo** (propuesta, ajustable en cualquier momento): Gestoría → Laxo, Inmobiliaria → Medio, Gabinete de abogados → Estricto.

## 11. Fuera de esta semana (para no perderlo)

Integración LexNET y Cl@ve · portales inmobiliarios directos · gestión integral de alquileres · tasaciones · firma avanzada con certificado cualificado · app móvil para abogados/agentes con modo sin conexión · sincronización con la base local de escritorio (ya en «Fuera de alcance» de `HOSTING.md`) · marketplace de plantillas entre despachos · facturación electrónica obligatoria (Verifactu/FacturaE) revisada con FacturaScripts · OAuth de Gmail/Microsoft 365 (necesita registro de aplicación por tu parte).

---

## 12. Cómo se mide que ha ido bien

- **Calidad**: suite verde (hoy 2.331) + los tests nuevos de cada bloque; el candado de diseño sin excepciones en las pantallas migradas.
- **Uniformidad**: 0 `<select>`/`<button>`/`confirm()` de fábrica en pantallas migradas; 0 `style=""` fuera de la lista.
- **Modularidad**: se puede activar/desactivar cada módulo para un despacho de prueba y el menú, el asistente y el MCP cambian solos.
- **Uso real**: una persona de cada sector hace un recorrido guiado (crear cliente → expediente → plazo/visita → documento → portal) sin ayuda.
- **Operación**: despliegue documentado en `HOSTING.md`, ayuda publicada en los cuatro idiomas, copia restaurada en una prueba.
