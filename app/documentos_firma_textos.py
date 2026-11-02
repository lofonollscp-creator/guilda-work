"""Textos de serie de los documentos que se firman con Documenso desde la ficha del cliente (ver `documentos_firma.py`).

Son un PUNTO DE PARTIDA SIN VALIDAR: redacciones habituales, no asesoramiento jurídico ni un modelo oficial. Cada despacho los revisa y, si quiere, los sustituye por los suyos
(Documentos de firma → Plantillas). Formato del texto: una línea `# Título` es un epígrafe, `- ` abre una viñeta y una línea en blanco separa párrafos. Las variables van entre
llaves dobles, p. ej. `{{cliente.nombre}}`.

Variables comunes a todos los documentos: `cliente.nombre`, `cliente.nif`, `cliente.direccion`, `cliente.email`, `cliente.telefono`, `despacho.nombre`, `despacho.cif`,
`despacho.direccion`, `fecha` y `lugar`. Cada documento añade además los campos que se rellenan al generarlo (ver `PLANTILLAS`)."""
from __future__ import annotations

HOJA_ENCARGO = """# Hoja de encargo profesional
En {{lugar}}, a {{fecha}}.

# Partes
{{despacho.nombre}}, con NIF {{despacho.cif}} y domicilio en {{despacho.direccion}} (en adelante, «el despacho»).

{{cliente.nombre}}, con NIF {{cliente.nif}} y domicilio en {{cliente.direccion}} (en adelante, «el cliente»).

# 1. Objeto del encargo
El cliente encarga al despacho la prestación de los siguientes servicios profesionales:

{{servicios}}

Cualquier servicio que no figure en esta lista requerirá un encargo adicional y podrá dar lugar a honorarios adicionales, que se acordarán antes de empezar.

# 2. Obligaciones del despacho
- Prestar los servicios con la diligencia profesional exigible y dentro de los plazos legales, siempre que el cliente haya facilitado la información necesaria a tiempo.
- Guardar el secreto profesional sobre toda la información del cliente a la que tenga acceso.
- Informar al cliente de los plazos y de las obligaciones que le afecten dentro del alcance del encargo.

# 3. Obligaciones del cliente
- Facilitar al despacho, en plazo y de forma veraz y completa, la documentación y los datos necesarios.
- Revisar y, en su caso, firmar o confirmar los documentos que el despacho le remita antes de presentarlos.
- Pagar los honorarios en la forma y en los plazos pactados.

El despacho no responde de las consecuencias de datos inexactos, incompletos o facilitados fuera de plazo.

# 4. Honorarios y forma de pago
{{honorarios}}

Los importes no incluyen el IVA ni los suplidos (tasas, aranceles u otros gastos pagados por cuenta del cliente), que se facturarán aparte. El impago de dos facturas consecutivas permite al despacho suspender los servicios previo aviso.

# 5. Duración y resolución
{{vigencia}}

# 6. Protección de datos
El despacho tratará los datos personales del cliente conforme al Reglamento (UE) 2016/679 y a la Ley Orgánica 3/2018. La información sobre el tratamiento se facilita en el documento de información y consentimiento que acompaña a este encargo.

# 7. Legislación aplicable
Este encargo se rige por la legislación española. Las partes intentarán resolver cualquier discrepancia de buena fe y, si no fuera posible, se someten a los juzgados y tribunales que resulten competentes conforme a la ley.

Y en prueba de conformidad, el cliente firma esta hoja de encargo en el lugar y la fecha indicados.
"""

MANDATO_SEPA = """# Orden de domiciliación de adeudo directo SEPA
Referencia de la orden de domiciliación: {{referencia}}
Identificador del acreedor: {{acreedor_sepa}}
Nombre del acreedor: {{despacho.nombre}}
Dirección del acreedor: {{despacho.direccion}}
Tipo de pago: {{recurrencia}} · Esquema: {{esquema}}

# Datos del deudor
Nombre del deudor: {{cliente.nombre}}
NIF del deudor: {{cliente.nif}}
Dirección del deudor: {{cliente.direccion}}
Número de cuenta - IBAN: {{iban}}

{{texto_esquema}}

Fecha y lugar de la firma: {{lugar}}, {{fecha}}.

El acreedor conservará esta orden mientras dure el mandato y durante el plazo legal posterior.
"""

TEXTO_ESQUEMA_CORE = (
    "Mediante la firma de esta orden de domiciliación, el deudor autoriza (A) al acreedor a enviar instrucciones a la entidad del deudor para adeudar su cuenta y (B) a la entidad "
    "para efectuar los adeudos en su cuenta siguiendo las instrucciones del acreedor. Como parte de sus derechos, el deudor está legitimado al reembolso por su entidad en los "
    "términos y condiciones del contrato suscrito con la misma. La solicitud de reembolso deberá efectuarse dentro de las ocho semanas que siguen a la fecha de adeudo en cuenta. "
    "Puede obtener información adicional sobre sus derechos en su entidad financiera.")
TEXTO_ESQUEMA_B2B = (
    "Mediante la firma de esta orden de domiciliación, el deudor autoriza (A) al acreedor a enviar instrucciones a la entidad del deudor para adeudar su cuenta y (B) a la entidad "
    "para efectuar los adeudos en su cuenta siguiendo las instrucciones del acreedor. Este mandato está pensado únicamente para transacciones entre empresas o profesionales. El "
    "deudor no tiene derecho a que su entidad le reembolse una vez que se haya realizado el cargo en su cuenta, pero puede solicitar a su entidad que no efectúe el adeudo hasta "
    "la fecha en que este se produzca. Debe comunicar este mandato a su entidad para que lo registre antes del primer adeudo.")

AUTORIZACION_AEAT = """# Autorización de representación ante la Agencia Tributaria
En {{lugar}}, a {{fecha}}.

# Quien otorga la autorización
{{cliente.nombre}}, con NIF {{cliente.nif}} y domicilio en {{cliente.direccion}} (en adelante, «el obligado tributario»){{representante_cliente}}.

# A quién se autoriza
{{despacho.nombre}}, con NIF {{despacho.cif}} y domicilio en {{despacho.direccion}} (en adelante, «el representante»).

# Alcance de la autorización
El obligado tributario autoriza al representante para que, en su nombre y ante la Agencia Estatal de Administración Tributaria, realice los siguientes trámites:

{{alcance}}

La autorización no comprende, salvo que se indique expresamente por escrito, la renuncia a derechos, el desistimiento de procedimientos ni el cobro de cantidades por cuenta del obligado tributario.

# Vigencia
{{vigencia}}

El obligado tributario puede revocar esta autorización en cualquier momento comunicándolo al representante y, en su caso, a la Administración por los cauces que esta establezca.

# Observaciones
Esta autorización se otorga para el ejercicio de la representación voluntaria prevista en el artículo 46 de la Ley General Tributaria y, cuando el representante actúe como colaborador social, conforme a lo dispuesto en el artículo 92 de la misma ley. El representante se obliga a utilizarla solo para los fines indicados y a guardar la debida confidencialidad.

El obligado tributario declara que los datos de este documento son ciertos y que tiene capacidad para otorgar la representación.
"""

CONSENTIMIENTO_RGPD = """# Información y consentimiento sobre el tratamiento de datos personales
En {{lugar}}, a {{fecha}}.

# Responsable del tratamiento
{{despacho.nombre}}, con NIF {{despacho.cif}} y domicilio en {{despacho.direccion}}. Contacto para cuestiones de protección de datos: {{contacto_rgpd}}.

# Para qué tratamos sus datos
Tratamos los datos de {{cliente.nombre}} ({{cliente.nif}}) para prestarle los servicios profesionales contratados (contabilidad, fiscalidad, laboral u otros acordados en la hoja de encargo), cumplir las obligaciones legales que nos afectan, gestionar la facturación y mantener la relación profesional.

# Base jurídica
- La ejecución del contrato de servicios profesionales.
- El cumplimiento de obligaciones legales (fiscales, contables, de prevención del blanqueo de capitales y otras).
- Su consentimiento, para lo que se indique expresamente y se pueda retirar.

# Destinatarios
Sus datos se comunicarán a las administraciones públicas cuando la ley lo exija o el servicio lo requiera (por ejemplo, la Agencia Tributaria o la Seguridad Social) y a los proveedores que nos prestan servicios con acceso a datos (almacenamiento, correo, firma electrónica o software de gestión) bajo contrato de encargo de tratamiento. No se prevén transferencias internacionales salvo que se indique lo contrario.

# Cuánto tiempo los conservamos
Mientras dure la relación profesional y, después, durante los plazos de conservación y prescripción que establezcan las normas aplicables, bloqueados y solo a disposición de las autoridades competentes.

# Sus derechos
Puede ejercer sus derechos de acceso, rectificación, supresión, oposición, limitación del tratamiento y portabilidad escribiendo a {{contacto_rgpd}}, acompañando una copia de su documento de identidad. Si considera que no hemos tratado sus datos correctamente, puede reclamar ante la Agencia Española de Protección de Datos (www.aepd.es).

# Consentimiento
Con su firma, {{cliente.nombre}} declara haber leído esta información y consiente el tratamiento de sus datos personales para las finalidades descritas. Este consentimiento no incluye el envío de comunicaciones comerciales, que se pide por separado y es opcional.
"""

CONSENTIMIENTO_COMERCIAL = """# Consentimiento para recibir comunicaciones comerciales
En {{lugar}}, a {{fecha}}.

{{despacho.nombre}}, con NIF {{despacho.cif}} y domicilio en {{despacho.direccion}}, le pide permiso para enviarle por correo electrónico información sobre sus servicios, novedades normativas, avisos de interés y ofertas, a la dirección {{cliente.email}}.

# Sus datos y sus derechos
Este consentimiento es voluntario y independiente de la prestación de cualquier servicio: si no lo da, o lo retira más adelante, no cambia nada en su relación con el despacho. Puede retirarlo en cualquier momento, sin explicar el motivo, con el enlace de baja que incluye cada correo o escribiendo a {{contacto_rgpd}}. Retirarlo no afecta a los envíos hechos antes.

Conservaremos la constancia de este consentimiento (fecha, medio y texto aceptado) mientras sea válido y durante los plazos legales posteriores. Puede ejercer sus derechos de acceso, rectificación, supresión, oposición, limitación y portabilidad en la misma dirección y reclamar ante la Agencia Española de Protección de Datos (www.aepd.es).

# Consentimiento
Con su firma, {{cliente.nombre}} consiente recibir comunicaciones comerciales por correo electrónico de {{despacho.nombre}}.
"""
