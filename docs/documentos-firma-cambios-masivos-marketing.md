# Documentos para firmar, cambios en lote y marketing del Comercial

Tres piezas nacidas de revisar otra plataforma de reservas (noviembre de 2026). Aquí está lo que hace cada una, lo que NO hace, y lo que hay que hacer para ponerlas en producción.

## 1. Documentos prehechos para firmar con Documenso (`app/documentos_firma.py`)

Desde la ficha del cliente, pestaña **Documentos → Documentos para firmar**: se elige un documento, se rellenan sus datos, se revisa el borrador y se envía a firmar.

| Documento | Para qué | Datos que pide |
|---|---|---|
| Hoja de encargo profesional | Servicios, honorarios y obligaciones de cada parte | servicios, honorarios, duración |
| Orden de domiciliación SEPA | Cobrar honorarios por adeudo directo | IBAN (con dígitos de control), esquema CORE/B2B, tipo de pago, identificador del acreedor |
| Autorización de representación ante la AEAT | El cliente autoriza al despacho a actuar ante la Agencia Tributaria | trámites, vigencia, quién firma por una sociedad |
| Información y consentimiento RGPD | Cómo se tratan sus datos | correo de derechos |
| Consentimiento de comunicaciones comerciales | Permiso aparte y opcional para enviarle marketing | correo para retirarlo |

El quinto no estaba en el encargo: el RGPD exige que el consentimiento de marketing sea **separado** del que se da para prestar el servicio, así que no se mezcla con el tercero. Al firmarse queda registrado como consentimiento de marketing, con el documento firmado como prueba (ver 3).

- **Texto de serie sin validar.** Son redacciones habituales, no asesoramiento jurídico ni un modelo oficial (en la AEAT, el apoderamiento formal sigue siendo el de la Sede o el procedimiento de colaboración social). La dirección del despacho puede sustituir cada texto por el suyo (**Textos** en la misma sección) con las mismas variables, y volver al de serie cuando quiera.
- **Lo que se firma es lo que se revisó.** El borrador guarda el texto exacto y la huella SHA-256 del PDF; cambiarlo obliga a crear otro. El PDF es determinista.
- **Enviar a firma es una acción externa**: pide confirmación en pantalla y solo existe si el despacho tiene su token de Documenso. Sin él se puede descargar el PDF.
- **Al firmarse** se guarda el PDF firmado en los documentos del cliente (categoría «Firmados»). El estado se consulta con «Comprobar si está firmado» (no hay webhook todavía).
- Si falta algo imprescindible (NIF, dirección del cliente; CIF o dirección fiscal del despacho; correo para el consentimiento comercial) no se genera y se dice qué falta.
- El hueco de la firma lo deja libre el propio PDF y el campo de Documenso se coloca ahí (última página).

## 2. Cambios en lote con «proponer → confirmar → deshacer» (`app/comercial_masivo.py`)

En **Comercial → Lista** se marcan oportunidades y se elige: cambiar de etapa, cambiar de responsable, posponer el cierre previsto o enviar a la papelera.

1. **Proponer no cambia nada.** Enseña cuántas cambiarían, cuáles se omiten y por qué (ya está en esa etapa, ya es suya, no tiene cierre previsto…).
2. **Confirmar.** Solo quien propuso, dentro de una hora. La papelera pide además escribir el recuento («3 oportunidades»). Si una oportunidad cambió entre la propuesta y la confirmación, se omite: no se pisa el trabajo de otra persona. Cada cambio pasa por las funciones de `comercial.py`, así que conserva su cronología, su auditoría y sus automatizaciones.
3. **Deshacer durante 90 días.** Devuelve cada oportunidad a su estado anterior, salvo las que se hayan vuelto a cambiar después. Historial en **Cambios en lote**.

**Asistente de IA.** Tres herramientas nuevas: `comercial_proponer_cambio_masivo` (solo prepara, sin confirmación), `comercial_aplicar_cambio_masivo` y `comercial_deshacer_cambio_masivo` (siempre piden confirmación, también en modo autónomo). La tarjeta de confirmación enseña ahora un **resumen** de lo que va a pasar (campo opcional `resumen` en la acción pendiente; las apps que no lo conocen siguen funcionando). Si el cambio manda oportunidades a la papelera, el asistente **no lo ejecuta**: la persona lo confirma en pantalla escribiendo el recuento.

## 3. Marketing del Comercial (`app/marketing.py`)

**Comercial → Marketing**: consentimientos, grupos, plantillas y envíos.

- **Consentimientos** (`marketing_contactos`): uno por despacho y correo, con cuándo, por qué vía y con qué prueba. Se registran solos al firmarse el consentimiento comercial, o a mano con una constancia escrita (formulario, verbal, importación). **Sin prueba no se registra.** Una baja prevalece siempre; un correo que rebotó no se reactiva por esta vía.
- **Filtros que se aplican siempre**: con consentimiento vigente, con correo válido, nunca bajas ni rebotados, un envío por correo aunque lo compartan varios clientes, solo el correo de la ficha del cliente (nunca sus contactos o familiares) y sin clientes en la papelera.
- **Grupos** por reglas (clientes y/o prospectos; tipo, etiquetas, origen, idioma, responsable, etapa). La audiencia se recalcula en cada envío y muestra por qué se excluye a cada uno. Se puede descargar en CSV para usarla en otra herramienta.
- **Plantillas** por bloques (título, texto, botón con enlace https, imagen, divisor) con variables `{{nombre}}`, `{{email}}`, `{{empresa}}`. El enlace de baja y los datos del despacho se añaden **siempre** al pie y no se pueden quitar. Todo el texto va escapado. Vista previa en un marco aislado.
- **Ayuda de IA** (redactar, reescribir, asuntos, mejorar): solo recibe el texto de la plantilla y lo que escribe la persona, nunca datos de clientes; es un borrador que se revisa. Usa el modelo y la clave de la propia persona (como las actas).
- **Enviar**: solo la dirección del despacho programa, tras ver el recuento y escribirlo. Se puede enviar una prueba a una dirección propia. La lista se congela al programar, pero **antes de cada correo se vuelve a comprobar** el consentimiento: quien se dé de baja entre medias no lo recibe.
- **Baja de un clic** sin iniciar sesión (`/baja/<token>`, token firmado). Cada correo lleva las cabeceras `List-Unsubscribe` y `List-Unsubscribe-Post` (RFC 8058).

### Rebotes
- **En el momento del envío:** si el servidor de destino rechaza el buzón con un error 5xx, ese correo queda como **rebotado** y no se le vuelve a escribir.
- **Después, por informe de entrega:** `scripts/procesar_rebotes.py` (timer cada 15 minutos) lee un buzón por IMAP (`MARKETING_IMAP_*`), interpreta los informes de entrega (RFC 3464) y los asigna al despacho y al envío por el último correo que salió hacia esa dirección. Para que los informes lleguen a ese buzón, el remitente (`MARKETING_SMTP_REMITENTE`) o el de retorno (`MARKETING_SMTP_RETORNO`) debe ser una dirección cuyo buzón lea ese IMAP.
- **Duros** (5.x.x, el buzón no existe) y **quejas**: rebotado al instante. **Blandos** (4.x.x, buzón lleno, servidor caído): rebotado al repetirse 3 veces en 30 días.
- Las respuestas automáticas y los mensajes que no son informes de entrega se ignoran. La dirección puede **reactivar** un correo rebotado con un motivo (queda en la auditoría). Pantalla: Marketing → Consentimientos → Rebotes recientes.

### Canales de Brevo y Mailchimp (Marketing → Canales de envío)
- Cada despacho usa **su propia cuenta**: clave de la API, remitente (verificado en el proveedor) y, en Mailchimp, la audiencia. Solo la dirección los configura; la clave no vuelve a mostrarse (solo sus 4 últimas cifras) y cualquier cambio exige volver a **probar la conexión**.
- Guilda decide la audiencia y sube **solo a quien tiene consentimiento**: en Brevo, a una lista nueva por envío; en Mailchimp, a la audiencia y a un segmento estático por envío. La campaña usa el HTML de Guilda con las etiquetas del proveedor para el nombre y el enlace de baja, y se envía.
- **Un envío por proveedor no se reintenta solo**: si algo falla se cancela con el motivo, porque el proveedor podría haber enviado ya y repetirlo duplicaría correos a clientes.
- Las **bajas** y los **rebotes** de cada proveedor se traen de vuelta (mismo timer que los rebotes) y se aplican al registro de consentimientos.
- Hasta 2.000 destinatarios por envío (se suben de uno en uno); para más, usar el CSV de la audiencia en la propia herramienta.
- **Importante:** las llamadas siguen la documentación oficial de Brevo v3 y Mailchimp Marketing 3.0 y están probadas contra un transporte simulado, **no contra cuentas reales**. Antes del primer envío real: «Probar conexión» y un envío pequeño a un grupo de prueba.

### Editor visual de plantillas
En la plantilla, los bloques se **arrastran** para reordenarlos (o con los botones ↑ ↓, que también funcionan con teclado y en el móvil), se añaden desde una paleta, se quitan, y a la derecha hay una **vista previa en vivo** que pide el HTML al servidor (el mismo código que arma el correo real). Si el script no carga, sigue funcionando el formulario de siempre. No se ha podido probar en un navegador en este entorno: conviene comprobarlo a mano en Chrome, Safari y móvil.

### Aviso automático de firma de Documenso
- **Webhook** `POST /webhooks/documenso`: en Documenso, Ajustes → Webhooks, URL `https://<tu dominio>/webhooks/documenso`, evento de documento completado (y rechazado) y un **secreto**; el mismo texto en `DOCUMENSO_WEBHOOK_SECRET`. Documenso lo manda tal cual en la cabecera `X-Documenso-Secret`; sin la variable el endpoint no acepta nada. **El contenido del aviso no se da por bueno**: solo sirve para saber qué documento es, y el estado se pregunta a la API de Documenso. Por eso no importa cómo se llame el evento.
- Al firmarse o rechazarse: se anota, se guarda el PDF firmado y se **avisa a quien creó el documento** (en la app y por push).
- **Respaldo:** `scripts/sincronizar_firmas.py` (timer cada 30 minutos) repasa los pendientes por si algún aviso se perdió.

### Lo que NO hace (todavía)
- **No usa Listmonk** (envía a una lista entera por despacho; no permite apuntar a un segmento con las garantías de arriba).
- No mide aperturas ni clics en el canal propio (los proveedores sí, en su panel).
- Los prospectos solo entran si su oportunidad no está enlazada a un cliente.
- El editor no tiene bloques de varias columnas ni versiones de plantilla.

## Puesta en producción

1. **Migraciones 013 y 014** (diez tablas y tres columnas): con el superusuario, antes de reiniciar.
   ```
   sudo bash -c 'set -a; source /etc/guilda-pg-admin.env; set +a; cd /home/guilda/guilda-work && runuser -u guilda --preserve-environment -- .venv/bin/python scripts/migrar_esquema_pg.py'
   ```
2. **Reiniciar** `guilda-work`, `guilda-work-mcp` y `guilda-backoffice`.
3. **Firmas de Documenso:** `DOCUMENSO_WEBHOOK_SECRET` en `/etc/guilda-work.env`, el webhook en Documenso, y el timer de respaldo (`deploy/sincronizar-firmas.service` y `.timer`).
4. **Marketing por el canal propio:** `MARKETING_SMTP_HOST`, `MARKETING_SMTP_USUARIO`, `MARKETING_SMTP_CONTRASENA`, `MARKETING_SMTP_REMITENTE` (y `MARKETING_SMTP_PUERTO`, `MARKETING_SMTP_RETORNO` si hacen falta) y el timer `deploy/marketing-envios.*`. **No reutilices el `PORTAL_SMTP_*`.** Rebotes: `MARKETING_IMAP_HOST`, `MARKETING_IMAP_USUARIO`, `MARKETING_IMAP_CONTRASENA` (y `MARKETING_IMAP_PUERTO`, `MARKETING_IMAP_CARPETA`) y el timer `deploy/procesar-rebotes.*`.
5. **Marketing por Brevo o Mailchimp:** nada en el servidor; la dirección configura la clave en Marketing → Canales de envío y prueba la conexión. El timer de rebotes también trae sus bajas.
6. **Datos legales del despacho** (CIF y dirección fiscal): sin ellos no se generan los documentos ni se programan envíos.

## Revisión jurídica pendiente (la hace una persona, no el código)
Los cinco textos de serie, el aviso del pie y el flujo de consentimiento y baja deben revisarse con el criterio profesional del despacho (RGPD, LOPDGDD y LSSI) antes de usarlos con clientes.
