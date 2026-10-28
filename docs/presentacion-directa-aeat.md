# Presentación directa en la AEAT (punto 16): decisión pendiente

**Estado:** sin implementar a propósito. Antes de escribir código hay una decisión de arquitectura y de seguridad que es de la dirección del despacho, y documentación de la AEAT que aún no se ha descargado.

## Por qué no se puede «simplemente hacer»

1. **Guilda Work no custodia claves privadas, por diseño.** El módulo de certificados (`app/certificados.py`) es un inventario de control: guarda solo material público y **rechaza** cualquier `.p12`/`.pfx` o clave privada, también en las subidas de documentos. Presentar una declaración con el certificado del despacho exige firmar o autenticarse con esa clave privada. O se revierte ese principio, o la clave se queda fuera del servidor.
2. **Es una acción irreversible con efectos legales** sobre terceros (los clientes del despacho): una declaración presentada no se «deshace»; se rectifica o se complementa. No se prueba contra producción.
3. **No tenemos el protocolo.** Las posiciones, los formatos y los endpoints no se escriben de memoria (regla de la casa). Hace falta descargar la documentación técnica oficial de presentación por servicio web de la AEAT y un entorno de pruebas.

## Tres caminos

| | Qué hace | Dónde está la clave | Riesgo | Esfuerzo |
|---|---|---|---|---|
| **A. El servidor presenta** | Guilda firma y envía con el certificado del despacho | En el servidor (almacén cifrado/HSM) | **Máximo**: una brecha firma como el despacho. Exige revertir el principio actual, apoderamientos o colaboración social vigentes por cliente, custodia, rotación y auditoría reforzada | Alto |
| **B. Agente local** | Un programa en el equipo de la gestoría (o el navegador con su cliente de firma) baja el fichero revisado, presenta con el certificado instalado y devuelve a Guilda el justificante | **Nunca sale** del equipo del despacho | Medio: hay que distribuir y mantener el agente | Medio-alto |
| **C. Semiautomático (lo actual, mejorado)** | Guilda genera el fichero, la persona lo presenta en la sede o con su programa y registra el justificante; se valida su formato y se enlaza al vencimiento | En la sede / en el programa del colaborador | **Mínimo** | Bajo |

El estado actual es el C: el fichero se importa en la sede y se anota el justificante (`marcar_presentada`, que ya cierra el vencimiento del calendario). Las rectificativas ya piden el justificante de 13 cifras.

## Lo que haría falta en A o B (y no se puede probar sin la AEAT)

- **Documentación técnica oficial** de presentación por servicio web y su **entorno de pruebas**. Hay que descargarla (pendiente de permiso explícito).
- Un **certificado de pruebas** y una persona que **valide** el primer envío en preproducción.
- **Doble confirmación** de quien envía: tecleando el NIF del titular, el modelo y el periodo; el envío queda **ligado al hash del fichero exportado** (no se envía otra cosa que lo revisado).
- **Idempotencia:** un envío con respuesta dudosa nunca se reintenta solo; se consulta el estado antes de reenviar.
- **Registro íntegro** de la respuesta de la AEAT (justificante, CSV, errores) en la auditoría.
- **Permisos:** solo quien aprueba declaraciones y, además, el custodio del certificado; el certificado debe estar vigente y autorizado para ese cliente.
- **Interruptor** por despacho, apagado por defecto.
- Qué se hace con **plazos vencidos, complementarias y rectificativas**, y con los avisos del fichero.

## Lo que hace falta de la dirección

1. Elegir **A, B o C**.
2. Si es A o B: permiso para **descargar la documentación técnica de la AEAT** y acceso a un **entorno y un certificado de pruebas**.
3. Quién **valida** el primer envío en preproducción.
