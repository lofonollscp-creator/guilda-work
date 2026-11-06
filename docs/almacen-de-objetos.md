# Almacén de objetos para el contenido de los documentos

Los PDF, fotos y adjuntos (facturas de los clientes, justificantes, expediente, adjuntos de correo) pueden vivir **fuera de la base de datos**, en un almacenamiento compatible con S3 (AWS S3, un proveedor europeo con API S3, MinIO…) o en una carpeta del servidor. Es lo que permite conservar años de documentación (unos 27.000 PDF al año con 150 clientes y 15 facturas al mes) sin que la base crezca decenas de GB.

Código: `app/almacen_objetos.py` (capa), `scripts/migrar_a_objetos.py` (migración y mantenimiento), migración `022_almacen_de_objetos` (tabla `objetos_almacenados`).

## Cómo funciona

- Las tablas no cambian. La columna `contenido` queda **vacía** y la fila se anota en `objetos_almacenados` (clave, tamaño, SHA-256). Quien lee pasa por `almacen_objetos.contenido()`, que trae el objeto del almacén si hace falta; el resto del código no se entera.
- Lo que se guarda fuera es EXACTAMENTE lo que había en la columna: con el cifrado del despacho activo ya va sellado, y en el almacén solo hay datos ilegibles. Sin él, lo protege el cifrado del propio almacén (activa SSE en el bucket).
- Tablas incluidas: `cliente_documentos` (aquí entran las facturas del portal), `documentos`, `vencimientos_fiscales_documentos` y `correo_adjuntos`.
- Claves: `<prefijo>t<despacho>/<tabla>/<id>-<12 primeros del SHA-256>`. Cada versión de un contenido es un objeto distinto: sellar o rotar claves nunca pisa el anterior hasta que la base confirma.
- **No se pierde nada**: si el almacén falla al guardar, el contenido se queda en la base; la migración lee cada objeto de vuelta y compara su SHA-256 antes de vaciar la columna; al leer, un objeto que no coincide con su huella no se entrega.
- Con `GUILDA_OBJETOS` sin definir todo sigue como antes.

## Configuración (en `/etc/guilda-work.env`)

```
GUILDA_OBJETOS=s3                       # o «fichero» (carpeta del servidor); vacío = desactivado
GUILDA_S3_BUCKET=guilda-documentos
GUILDA_S3_ACCESS_KEY=…                  # credenciales de la APLICACIÓN: leer y escribir, sin borrar
GUILDA_S3_SECRET_KEY=…
GUILDA_S3_ENDPOINT=s3.eu-south-2.amazonaws.com   # por defecto s3.amazonaws.com; otro proveedor: su endpoint
GUILDA_S3_REGION=eu-south-2
GUILDA_S3_SECURE=1
GUILDA_S3_PREFIJO=prod/                 # opcional
GUILDA_S3_RETENCION_DIAS=2200           # opcional: bloqueo de borrado (Object Lock) ≈ 6 años
GUILDA_S3_RETENCION_MODO=GOVERNANCE     # o COMPLIANCE (irreversible hasta que venza)
# fichero:  GUILDA_OBJETOS_DIR=/var/lib/guilda-objetos   (permisos solo del servicio; entra en las copias de seguridad)
```

El dato para decidir el plazo de conservación es legal, no técnico: el Código de Comercio exige 6 años para los justificantes y la prescripción tributaria es de 4 (algunos casos llegan a 10). Confírmalo con quien lleve vuestro cumplimiento.

## Preparar el bucket (AWS S3)

1. Región de la UE (Fráncfort, Irlanda, París o España `eu-south-2`).
2. Crear el bucket **con Object Lock activado** (solo se puede al crearlo; activa también el versionado), bloqueo de acceso público total y cifrado SSE-S3 (o SSE-KMS).
3. Ciclo de vida (opcional, ahorra): pasar a *Glacier Instant Retrieval* lo que tenga más de un año (sigue siendo accesible al instante); borrar versiones antiguas no actuales a los N meses.
4. Dos usuarios IAM:
   - **aplicación**: `s3:PutObject`, `s3:GetObject`, `s3:GetObjectVersion`, `s3:ListBucket` solo sobre el bucket (si defines `GUILDA_S3_RETENCION_*` la app fija la retención por objeto y necesita además `s3:PutObjectRetention`; con la retención por defecto del bucket no hace falta) (sin `DeleteObject*`).
   - **mantenimiento** (solo para `limpiar`, sin guardarlo en el servicio): además `s3:DeleteObject` y `s3:DeleteObjectVersion`.
5. Alertas de facturación y de errores 4xx/5xx.

Con otro proveedor con API S3 el procedimiento es el mismo; comprueba que ofrece bloqueo de borrado y versionado.

## Migrar lo que ya hay

```bash
cd /home/guilda/guilda-work
set -a; . /etc/guilda-work.env; set +a
.venv/bin/python scripts/migrar_a_objetos.py estado                 # qué hay en la base y qué hay fuera
.venv/bin/python scripts/migrar_a_objetos.py migrar                 # simulación: cuenta lo que haría
.venv/bin/python scripts/migrar_a_objetos.py migrar --aplicar --tablas cliente_documentos --limite 50   # prueba pequeña
.venv/bin/python scripts/migrar_a_objetos.py verificar              # lee cada objeto y compara tamaño y SHA-256
.venv/bin/python scripts/migrar_a_objetos.py migrar --aplicar       # todo (se puede interrumpir y repetir)
.venv/bin/python scripts/migrar_a_objetos.py verificar --aplicar    # anota la fecha de verificación
```

1. Aplica la migración 022 (`scripts/migrar_esquema_pg.py`) ANTES de desplegar el código, como siempre.
2. Define las variables y reinicia: desde ese momento lo nuevo ya va al almacén.
3. Migra lo existente con el script. Un fallo del almacén detiene la migración sin dejar nada a medias (`--continuar` para seguir).
4. PostgreSQL no devuelve el espacio al sistema operativo hasta un `VACUUM FULL` de esas tablas (bloquea la tabla mientras dura: ventana de mantenimiento). Con Citus, hazlo por tabla.
5. **Marcha atrás**: `revertir --aplicar` devuelve el contenido del almacén a la base (`--borrar-objetos` borra también los objetos).

## Mantenimiento

- `limpiar --aplicar` (con las credenciales de mantenimiento): borra los objetos de filas que ya no existen (borrado de documentos, de clientes, de despachos, RGPD) y los que ningún registro menciona (subidas a medias, versiones anteriores tras sellar o rotar claves). No toca lo de menos de `--antiguedad-min` (60) minutos. Programarlo una vez a la semana. Con Object Lock, el borrado falla hasta que vence la retención: **la conservación legal prevalece sobre el borrado inmediato**; define esa regla en vuestra política de RGPD.
- `verificar` periódico (mensual) detecta objetos que faltan o difieren, y filas vaciadas sin objeto.

## Copias de seguridad y recuperación

- La base ya no contiene los bytes de los documentos: **una copia de la base sola no basta**. El almacén necesita su propia protección: versionado + Object Lock (frente a borrados y ransomware) y, si queréis, replicación a otra región o a otro proveedor.
- **Copia fuera de AWS (Restic)**: con `GUILDA_OBJETOS=s3`, `scripts/backup_objetos_restic.sh` (timer `deploy/restic-objetos.timer`, 03:40) hace un espejo incremental del bucket en `objetos-espejo`, junto al repositorio de Restic (segundo disco), y lo copia con la etiqueta `objetos` (retención 7 diarias, 4 semanales, 6 mensuales, 6 anuales). Cada objeto se comprueba contra el hash de su clave al bajarlo y el espejo nunca borra. Estado en `data/backups/restic_objetos_estado.json`. Restaurar: `restic restore latest --tag objetos --target <carpeta>` y volcar a un bucket nuevo.
- Con `GUILDA_OBJETOS=fichero`, la carpeta debe entrar en las copias de seguridad (Restic) junto con la base, y restaurarse juntas.
- La copia/restauración de UN despacho (`app/bd/despacho_copia.py`) lleva el registro (`objetos_almacenados`) pero no los objetos: al restaurar en otra base, los objetos tienen que seguir accesibles en el mismo almacén.
- Restaurar la base a un instante anterior puede dejar objetos sin registro (los recoge `limpiar`) o registros que apuntan a objetos aún presentes: nunca al revés mientras no se borre nada a mano.

## Qué NO hace

- No migra: avatares, logos, certificados, adjuntos de tiquets/notas/tareas/IA ni los lotes de exportación a3 (son pequeños o de poco volumen; la capa admite añadirlos en `TABLAS` cuando haga falta, con su lectura y escritura pasando por `contenido()` / `ofrecer()` / `preparar()`).
- No sirve los archivos con enlaces firmados: pasan siempre por la aplicación, que comprueba los permisos.
