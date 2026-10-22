# Hoja de ruta de Guilda Work

Documento vivo. Fecha del diagnóstico: 22 de octubre de 2026. Los datos de «Cómo está hoy» se comprobaron en el servidor y en el repositorio ese día; las secciones de «Visión» y «Fases» son propuesta, no hechos.

## Visión

Guilda Work gana si es **el sistema operativo de una gestoría pequeña o mediana**: clientes, expedientes, tareas, fiscal, contabilización y portal del cliente en un solo sitio, con herramientas conectadas que de verdad funcionan. No gana como catálogo de enlaces a herramientas de terceros: el servidor no puede sostener todas, y un enlace muerto resta confianza a lo que sí funciona.

Principios para decidir qué se hace:

1. **Profundizar el núcleo propio** antes que añadir herramientas conectadas.
2. **Lo que se enseña funciona**: nada en pantalla, en la app móvil o en el asistente de IA que dependa de un servicio que no corre.
3. **Primero lo que protege** (copias, seguridad, avisos), después lo que ahorra tiempo, después lo que vende.
4. **Cada cambio verificable**: pruebas automáticas, ensayo de migraciones sobre una copia de la base real y documentación en `HOSTING.md`.

## Cómo está hoy (22-oct-2026)

- **Núcleo propio**: 193 módulos de aplicación, unas 73.000 líneas y 256 ficheros de test. Lo más sólido: tareas y correo. Lo más fino en pruebas respecto a su tamaño: agenda, notas, tiquets, expedientes, certificados y contabilización (1-4 ficheros de test cada uno).
- **Herramientas conectadas**: el catálogo tiene 21 entradas; `docker-compose.yml` define 76 servicios y **solo 33 están en marcha**. Sin desplegar: EspoCRM (CRM), OpenProject, Chatwoot, Cal.com (citas), Listmonk (newsletter), Baserow (hojas), Metabase, Umami, Portainer, Paperless, Jitsi, Collabora, ntfy y ClamAV.
- **Servidor**: uno solo, 7,7 GB de memoria (unos 4 GB libres), disco al 63 %. Copia diaria de `registro.db`; la copia de los volúmenes Docker (Restic) está documentada pero sin activar.
- **Correo saliente**: `guilda.cat` tiene SPF pero no DMARC.
- **Huecos conocidos**: pruebas de navegador escritas pero sin ejecutar (falta instalar Playwright); la app móvil no se compila en el servidor; el «servicio de cliente» (alta de autónomo, nóminas mensuales…) no existe como entidad; Nextcloud pendiente de actualizar.

## Fases

### Fase 0 — Fiabilidad (1-2 semanas) · pendiente, la mayor parte la hace una persona
- Activar Restic con un backend S3 y **probar una restauración de verdad**. Decidir cuánta pérdida de datos se tolera (hoy: hasta 24 h).
- DMARC y DKIM de `guilda.cat` (registros DNS).
- Actualizar Nextcloud (rama 34 ya fijada en `docker-compose.yml`) con copia previa; activar ClamAV.
- Instalar Playwright y ejecutar `scripts/probar_navegador.sh`.
- Un vigilante que avise cuando una imagen o su PHP se quede atrás de los parches.

### Fase 1 — Honestidad del catálogo · **hecha el 22-oct-2026**
Ver el apartado «Fase 1: qué se hizo» más abajo y la sección de `HOSTING.md` «Herramientas conectadas que responden de verdad».

### Fase 2 — El núcleo del despacho (4-8 semanas)
- **Servicios de cliente**: un servicio (nóminas mensuales, alta de autónomo, declaración de la renta) que genere solo tareas, vencimientos, expediente y lista de comprobación con responsables. Une lo que ya existe (tareas recurrentes, reglas de automatización, expedientes) y es lo que más tiempo ahorra.
- **Ficha 360 del cliente**: una cronología única de correos, tareas, facturas, documentos, horas y cobros.
- **Portal del cliente como producto**: solicitudes de documentos con recordatorios automáticos, firma desde el portal, mensajes.
- **Automatizaciones**: más acciones (enviar un correo con plantilla, pedir un documento, abrir un expediente) y más disparadores (llega un correo, el cliente sube una factura, se completa una firma).

### Fase 3 — Contabilización (el mejor diferencial comercial)
- Validar el `SUENLACE.DAT` con un a3 real y calibrar la lectura de facturas con IA con facturas reales; fijar tarifas.
- Siguiente salto de valor: prerrellenar el modelo 303 desde las facturas.

### Fase 4 — Plataforma
- Verificación en dos pasos obligatoria para la dirección; cumplimiento de protección de datos (derecho al olvido, portabilidad, retención); alta de despachos sin intervención manual; métricas de uso por módulo; valorar PostgreSQL solo si la carga lo pide.

### Fase 5 — Verticales
- Abogados e inmobiliaria están construidos pero marcados como no disponibles. Decidir: lanzar con un despacho piloto o aparcar. Mantenerlos a medias cuesta mantenimiento.

## Decisiones pendientes del propietario

1. ¿Cuál es el cliente objetivo (gestoría de 2-10 personas, despacho de abogados, ambos)? Fija el orden de las fases 2 y 5.
2. ¿Qué herramientas conectadas se mantienen y cuáles se retiran? Propuesta: fuera Cal.com y Listmonk (la agenda propia y los correos con marca cubren su papel); EspoCRM solo si el CRM va a ser un producto.
3. ¿Se vende el CRM o basta el núcleo de clientes propio?
4. ¿Qué pérdida de datos es aceptable? Decide si Restic basta o hace falta un segundo servidor.
5. ¿Los verticales se lanzan con un piloto o se aparcan?
6. «Observabilidad» (Grafana) responde pero está marcada como no disponible en el catálogo: ¿se enseña al equipo o se queda interna?

## Fase 1: qué se hizo

Lo que se encontró (verificado el 22-oct-2026):

- La página web de herramientas ya escondía a mano las no desplegadas (`disponible: False`), pero **dos entradas sin marcar tampoco respondían**: OpenProject y Documentos (Paperless). Eran enlaces muertos.
- La app móvil ya enseñaba en gris lo marcado como no disponible, pero no sabía de lo caído.
- Las herramientas del asistente de IA y del MCP que hablan con esos servicios fallaban con una excepción cruda (los errores de los clientes de EspoCRM, Nextcloud, Documenso, etc. no se convertían en un error de herramienta).

Qué cambia (`app/estado_herramientas.py`):

- Una herramienta está disponible si no está marcada `disponible: False` **y** responde ahora (petición corta, en paralelo, guardada 45 s).
- La web solo enseña lo que responde (la dirección ve un aviso con las que no); la app móvil lo enseña en gris.
- El asistente de IA no se ofrece las herramientas de un servicio caído y el MCP responde con un mensaje claro; los errores de los servicios llegan al chat como error de herramienta.
- El panel de salud muestra el latido `herramientas_conectadas` con cuáles no responden.
