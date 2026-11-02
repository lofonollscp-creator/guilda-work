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

### Lo que NO hace (todavía)
- **No usa Listmonk.** Listmonk envía a una lista entera por despacho y no permite apuntar a un segmento con las garantías de arriba; por eso el envío es propio. Tampoco hay conectores de Brevo, Mailchimp o GoHighLevel: de momento se descarga la audiencia en CSV.
- **No detecta rebotes ni mide aperturas.** Un correo rebotado se marca a mano; el envío con error queda anotado por destinatario.
- No hay editor visual de arrastrar y soltar (los bloques se ordenan editando la lista) ni versiones de plantilla.
- Los prospectos solo entran si su oportunidad no está enlazada a un cliente (al convertirse, pasan a ser cliente).

## Puesta en producción

1. **Migración 013** (ocho tablas): con el superusuario, antes de reiniciar.
   ```
   sudo bash -c 'set -a; source /etc/guilda-pg-admin.env; set +a; cd /home/guilda/guilda-work && runuser -u guilda --preserve-environment -- .venv/bin/python scripts/migrar_esquema_pg.py'
   ```
2. **Reiniciar** `guilda-work`, `guilda-work-mcp` y `guilda-backoffice`.
3. **Canal de envío propio** (solo si se va a enviar marketing): en `/etc/guilda-work.env`, `MARKETING_SMTP_HOST`, `MARKETING_SMTP_USUARIO`, `MARKETING_SMTP_CONTRASENA`, `MARKETING_SMTP_REMITENTE` y, si no es el 587, `MARKETING_SMTP_PUERTO`. **No reutilices el `PORTAL_SMTP_*`**: lleva los enlaces de acceso del portal y no debe compartir reputación con el marketing. Después, instalar `deploy/marketing-envios.service` y `.timer` (cambiar `USUARIO`) y activar el timer. Sin las variables todo funciona salvo enviar.
4. **Datos legales del despacho** (CIF y dirección fiscal): sin ellos no se generan los documentos ni se programan envíos.

## Revisión jurídica pendiente (la hace una persona, no el código)
Los cinco textos de serie, el aviso del pie y el flujo de consentimiento y baja deben revisarse con el criterio profesional del despacho (RGPD, LOPDGDD y LSSI) antes de usarlos con clientes.
