# RGPD en Guilda Work: qué hace el código y qué queda por hacer a una persona

> Este documento es un **registro técnico y organizativo**, no un dictamen jurídico. El software puede aplicar medidas (minimización, retención, derechos, seguridad), pero que Guilda Work «cumpla el RGPD» depende también de contratos, decisiones del despacho y procedimientos que solo una persona responsable puede firmar. Lo que requiere esa decisión está en [Pendiente de una persona](#pendiente-de-una-persona). Revisarlo con asesoría jurídica antes de darlo por bueno.

## 1. Quién es quién

| Datos | Responsable | Encargado | Base |
|---|---|---|---|
| Cuenta de quien usa la plataforma (correo, contraseña cifrada, ajustes) | Guilda Assessors Historics, S.L. | — | Ejecución del contrato (art. 6.1.b) |
| Datos de trabajo del despacho: clientes, expedientes, correo, facturas, tareas, documentos | **El despacho** | Guilda (art. 28) | Los que fije cada despacho |
| Datos de los clientes finales que el despacho carga (nóminas, NIF, IBAN…) | El despacho | Guilda (art. 28) | Los del despacho (contrato, obligación legal) |
| Formulario de contacto de la web | Guilda | — | Consentimiento (art. 6.1.a) |

Como Guilda es **encargada** de los datos del despacho, hace falta un **contrato de encargo (art. 28.3)** con cada despacho. Plantilla pendiente: ver más abajo.

## 2. Medidas técnicas ya implementadas

| Principio / derecho | Medida | Dónde |
|---|---|---|
| Minimización y protección desde el diseño (arts. 5.1.c, 25) | Antes de enviar texto al modelo de IA se sustituyen nombres, NIF/NIE/CIF, IBAN, tarjeta, teléfono, correo y direcciones por etiquetas reversibles (Presidio + spaCy). Si el detector falla, **no se envía nada**. | `app/anonimizar.py`, `app/ia_asistente.py` |
| Limitación del plazo de conservación (art. 5.1.e) | Borrado diario: conversaciones de IA a 365 días, avisos leídos a 180 y no leídos a 365, accesos de portal, errores del servidor | `app/retencion.py`, `app/db.py` |
| Acceso y portabilidad de la persona usuaria (arts. 15, 20) | «Mis datos y privacidad»: descarga JSON de su cuenta, fichajes, ausencias, avisos, dispositivos y conversaciones de IA (sin secretos) | `app/rgpd_persona.py`, `/cuenta/privacidad/` |
| Supresión de la persona usuaria (art. 17) | Solicitud de baja registrada, aviso a la dirección, plazo de un mes; borrado inmediato de historial de IA y dispositivos | `app/rgpd_persona.py` |
| Acceso y portabilidad de los clientes del despacho | Exportación JSON de toda la ficha del cliente | `app/rgpd.py`, `/seguridad/clientes/<id>/exportar.json` |
| Supresión de datos de clientes | Papelera con vaciado y constancia | `app/rgpd.py` |
| Responsabilidad proactiva (art. 5.2) | Registro de exportaciones, vaciados y solicitudes (`registro_rgpd`), auditoría con cadena de hashes | `app/rgpd.py`, `app/auditoria.py` |
| Seguridad (art. 32) | Contraseñas cifradas, Kratos/Hydra, aislamiento por despacho (PostgreSQL RLS + Citus), cifrado opcional de documentos, copias cifradas (restic), CSP y cabeceras, limitación de intentos | varios |
| Transparencia (arts. 12-14) | Política de privacidad y de cookies en la web; nota sobre IA en el asistente; textos de «Mis datos» | `/var/www/landing`, `app/templates/` |
| Sin terceros de seguimiento | Sin analítica, sin fuentes ni scripts de CDN: todo se sirve desde el propio dominio. El service worker solo guarda estáticos | verificado |

## 3. Encargados y destinatarios (subencargados)

Solo cuando el módulo o la persona lo usan:

| Proveedor | Para qué | Datos | Notas |
|---|---|---|---|
| Proveedor de modelos de IA (OpenRouter y el modelo elegido) | Respuestas del asistente | Texto de la consulta **con datos personales sustituidos por etiquetas**. Imágenes y PDF leídos con IA **no** se pueden proteger así | Clave propia de la persona o del despacho; revisar la política de retención/entrenamiento del modelo elegido y las transferencias fuera del EEE |
| Google Firebase Cloud Messaging | Avisos en la app móvil | Título y texto del aviso | Transferencia a EE. UU. (marco de privacidad UE-EE. UU.); valorar avisos genéricos |
| Servicios de push de navegador (Google, Apple, Mozilla, Microsoft) | Avisos en la webapp | Carga **cifrada** extremo a extremo con la clave del navegador | Solo si la persona activa los avisos |
| Brevo | Envío de campañas de marketing | Correo y nombre de los destinatarios | Solo con el módulo de marketing; exige consentimientos y bajas (ya existen) |
| Stripe | Cobro de la suscripción | Datos de facturación | Responsable propio |
| Google / Microsoft (OAuth de correo) | Conectar buzones que la persona elige | Correo del buzón | Lo inicia la persona |

El alojamiento es propio, en servidores de la UE.

## 4. Conservación

| Dato | Plazo | Fuente |
|---|---|---|
| Conversaciones con IA | 365 días desde la última actividad (`GUILDA_RETENCION_IA_DIAS`) | `app/retencion.py` |
| Avisos de la campana | 180 días leídos / 365 sin leer | `app/retencion.py` |
| Registro de accesos del portal | 730 días | `app/db.py` |
| Registro horario (fichajes) | **4 años** (obligación legal, RDL 8/2019); no se borra al pedir la baja | ley |
| Facturas y libros fiscales | 4-6 años según norma | ley / despacho |
| Documentos y expedientes del despacho | Los que decida el despacho; vaciado de papelera a su cargo | `app/rgpd.py` |
| Copias de seguridad | Según `scripts/backup_restic.sh`; un dato borrado desaparece de las copias al rotar | operaciones |

## 5. Derechos: cómo se atienden

1. **Persona usuaria** → ella misma, en *Ajustes → Mis datos y privacidad*. La baja de cuenta se registra y la dirección del despacho la gestiona en el plazo de **un mes** (art. 12.3, prorrogable dos meses si es compleja, avisando).
2. **Cliente del despacho** → el despacho (responsable) usa la exportación y la papelera. Guilda, como encargada, **asiste al despacho** y no responde directamente salvo instrucción.
3. **Rectificación, oposición, limitación** → por correo a gestio@guilda.cat; se anotan en `registro_rgpd`.
4. Reclamación: Agencia Española de Protección de Datos (aepd.es).

## 6. Brechas de seguridad (art. 33-34)

Procedimiento mínimo (adoptar y ensayar):

1. Quien detecte el incidente avisa a gestio@guilda.cat y a la dirección técnica de inmediato.
2. Contener (rotar claves, revocar sesiones, aislar el servicio), conservar logs y anotar fecha y hora de conocimiento.
3. Evaluar riesgo para las personas. Si lo hay, **notificar a la AEPD en 72 horas** desde que se tuvo constancia. Si el riesgo es alto, avisar a las personas afectadas.
4. Como encargada, **avisar al despacho responsable sin dilación** (art. 33.2).
5. Documentar siempre (hechos, efectos, medidas), aunque no se notifique.

## 7. Evaluación de impacto (EIPD) y asistente de IA

El asistente jurídico y el de datos tratan información de alto riesgo (secreto profesional, datos fiscales y laborales) con una tecnología nueva y encargados fuera del EEE: **conviene hacer una EIPD (art. 35)** antes de usarlos con datos reales de terceros. El asistente es una **ayuda, no decide** (no hay decisiones automatizadas del art. 22): toda acción que modifica datos se muestra y se confirma, y las respuestas llevan sus fuentes.

Límites conocidos de la protección de datos en IA: el reconocimiento de nombres es estadístico (puede dejar pasar un nombre poco común o enmascarar de más); no cubre imágenes ni PDF; no detecta números de la Seguridad Social ni datos de salud en texto libre.

## Pendiente de una persona

Esto no lo puede resolver el código:

- [ ] **Contrato de encargo (art. 28)** con cada despacho cliente, y la **lista de subencargados** comunicada a ellos.
- [ ] **Registro de actividades de tratamiento (art. 30)** propio de Guilda (modelo: tabla de las secciones 1-4) y que cada despacho haga el suyo.
- [ ] **Contratos de encargo con los proveedores** de la sección 3 (DPA) y comprobar transferencias fuera del EEE y garantías (cláusulas tipo / marco UE-EE. UU.).
- [ ] Elegir **modelos de IA con retención cero y sin entrenamiento** y dejarlo por escrito.
- [ ] **EIPD** del asistente de IA y del asistente jurídico (sección 7).
- [ ] Valorar si hace falta **Delegado de Protección de Datos** (tratamiento a gran escala de datos de terceros).
- [ ] Ensayar el **procedimiento de brechas** (sección 6) y fijar quién notifica.
- [ ] Revisar con asesoría jurídica la **política de privacidad** y los textos de «Mis datos».
- [ ] Decidir la política de retención de **cada despacho** (papelera, expedientes cerrados).
- [ ] Confirmar la **rotación de copias de seguridad** respecto al derecho de supresión.
