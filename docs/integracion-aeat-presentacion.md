# Integración de presentación telemática AEAT en Guilda Work

Estado: **versión 2** del borrador del 6 de noviembre de 2026 · Fecha: 6 de noviembre de 2026
Qué cambia respecto al borrador: se han leído las especificaciones oficiales (§3), se han cotejado con el código real (§4), se han cerrado casi todos los **[VERIFICAR]** y aparece un **conflicto de arquitectura** que hay que decidir antes de escribir la presentación real (§5.1). Lo que sigue **[VERIFICAR]** queda indicado con el modo de cerrarlo.

> No es asesoramiento fiscal ni jurídico. Fuente principal: *Especificaciones de los servicios de Presentación Directa, Consulta de Declaraciones Presentadas y Validación de Impresión*, **versión 30** (AEAT, Departamento de Informática Tributaria). El PDF del modelo 303 para colaboradores (`IVA303-CoordColabora_7.02`) está escaneado y no se pudo leer en texto; su contenido útil (el diseño de registro) ya está en el repositorio como `DR303e26v101` (ver `docs/fiscal-vias-aeat.md`).

---

## 1. Objetivo

Permitir que Guilda Work presente en la AEAT, desde la aplicación, las declaraciones de IVA de los clientes fiscales (empezando por el modelo 303), con el certificado del presentador (colaborador social), y guarde el justificante.

| Fase | Contenido | Estado real |
|---|---|---|
| 1 | Modelo 303: generar, validar, presentar, guardar justificante | Generar y validar contra el simulador: **hecho** (§4). Presentar: **pendiente** |
| 2 | Consulta de declaraciones presentadas (conciliación) | Pendiente (el servicio existe, §3.3) |
| 3 | Modelo 390 | El motor y el fichero **ya existen** (§4); falta presentarlo |
| 4 | Otros modelos (111, 115, 130/131…) | Motores y ficheros **ya existen**; todos están en la lista de modelos admitidos (§3.5) |

Fuera de alcance: Verifactu/Fiskaly (otro asunto: registra facturas, no presenta autoliquidaciones) y haciendas forales.

---

## 2. Requisitos legales y operativos (previos al desarrollo)

Decidido: se presenta **con el certificado del colaborador social** y un único certificado de presentación por presentador (organización).

- La respuesta de la AEAT incluye `TipoRepresentacion` con tres valores posibles: «Nombre propio», «Apoderado» o «Colaborador». Confirma que el servicio distingue la calidad en la que se presenta **a partir del certificado**, sin que el fichero lo indique. **[Cerrado]**
- Con colaboración social no hay otro «certificado especial»: es el certificado habitual del colaborador, reconocido como tal al darse de alta en el censo. Si presentan empleados, cada uno es colaboración social **delegada**.
- Conservar el **mandato escrito** del cliente: la AEAT puede exigir acreditar la representación.
- **Pendiente [VERIFICAR] con la entidad del alta o el CAID** (Centro de Atención a Integradores y Desarrolladores de la AEAT): que el alta cubre la presentación **por servicio web** y no solo por el formulario de la Sede.
- **Pago.** La especificación admite en el envío el campo `NRC` para las declaraciones **a ingresar (tipo I)**: es decir, existe la vía de ingresar antes y enviar el NRC. El borrador decía que, con colaboración social, un 303 a ingresar «solo se puede presentar con domiciliación»; eso procede de la ayuda técnica de la Sede para el formulario y **no consta en esta especificación**. **[VERIFICAR]** qué vías de pago admite el colaborador por envío directo. Además, la cuenta de domiciliación debe pertenecer al declarante (consta para el 210, **no verificado para el 303**), y si la cuenta es de una entidad **no colaboradora** de la AEAT pueden generarse comisiones a cargo del contribuyente (§1.3 de la especificación, nota de la forma de pago U).

---

## 3. Lo que dice la especificación oficial (v30)

### 3.1 Autenticación y «firma no criptográfica»

- El envío directo **no lleva firma criptográfica del fichero; de hecho se rechaza**. Lo que identifica al presentador es la **autenticación de cliente con certificado electrónico en la conexión TLS** (la AEAT lo llama «Firma No Criptográfica»).
- El titular del certificado de esa conexión es el **presentador**. Los programas de la AEAT comprueban que `FIRNIF` coincide con el NIF del certificado; si no, abortan.
- El propio envío **supone la aceptación de los datos por el presentador**: la aplicación debe garantizar, por sus medios, que se le muestran los datos y da su conformidad antes de enviar. Debe mostrarse al usuario el NIF del declarante contrastado con los datos de la declaración.

Consecuencia: **no hace falta firmar nada con la clave; hace falta que la clave pueda abrir una conexión TLS de cliente**. Esto condiciona el diseño (§5.1).

### 3.2 Presentación directa

| | |
|---|---|
| Producción | `https://www1.agenciatributaria.gob.es/wlpl/PFTW-PICW/PresBasicaDos` |
| Pruebas | `https://prewww1.aeat.es/wlpl/PFTW-PICW/PresBasicaDos` |
| Método y formato | `POST`, `Content-Type: application/json;charset=UTF-8` |
| Cuerpo | `MODELO`, `EJERCICIO`, `PERIODO`, `NRC` (solo tipo I; si no, vacío), `IDI` (ES, EN, VA, GL, CA), `F01` (fichero plano completo del diseño de registro), `FIR` = `FirmaBasica`, `FIRNIF`, `FIRNOMBRE` |
| `F01` | Sin CRLF ni tabuladores; solo caracteres de la tabla ISO-8859-1 admitida (§3.6) |
| Respuesta correcta | JSON con `CodigoSeguroVerificacion` (CSV, 16), `Fecha`, `Hora`, `Expediente`, `NIFPresentador`, `TipoRepresentacion`, `NIFDeclarante`, `Modelo`, `Ejercicio`, `Periodo`, `Justificante` (13 cifras), `NRCPago`, `ImporteAIngresar`, `FormaPago`, `urlPdf` y listas `avisos` y `advertencias` |
| Respuesta con error | `{"respuesta":{"errores":["E00 - Error. Código de error: …"]}}`, hasta 100 errores. Una respuesta correcta **nunca** trae errores y la de error **nunca** trae CSV ni `urlPdf` |
| Justificante | A efectos de la AEAT **no es la respuesta sino el PDF** que se descarga de `urlPdf` |
| Anulación | **No es posible anular declaraciones ya grabadas**: se rectifican o complementan |

Formas de pago (`FormaPago`): I a ingresar · U domiciliación · G ingreso a anotar en CCT · N negativa/cuota cero · D solicitud de devolución · R renuncia a la devolución · V devolución con anotación en CCT · C a compensar · B a deducir (el resto según modelo).

### 3.3 Consulta de declaraciones presentadas

- `POST` (formulario `application/x-www-form-urlencoded`) a `https://www1.agenciatributaria.gob.es/wlpl/SCEJ-MANT/ConsultaExt`, con certificado.
- Variables, en este orden: `NIF`, `ANR` (nombre o razón social), `MOD`, `EJF`, `PER`, `FED`/`FEH` (AAAAMMDD), `HOD`/`HOH` (HHMM). Obligatorias: NIF, ANR, MOD, EJF.
- Respuesta en **XML**, máximo **100** declaraciones, con el XSD publicado en `…/EEDD/General/consultas.xsd` (**sin leer todavía**).
- Es la herramienta para el caso de respuesta dudosa (§6, paso 7).

### 3.4 Validación e impresión (sin certificado)

- `ServValiDos` (el antiguo `ServVali` solo vale hasta ejercicio 2024): `POST` JSON a `https://prewww2.aeat.es/wlpl/PFTW-PICW/ServValiDos` con `MODELO`, `EJERCICIO`, `PERIODO`, `FIC` (o `F01`), `IDI` y, opcional, `SINVL` (sin validar: solo imprime).
- Devuelve `{"RESPUESTA":{"AVISOS":[…],"PDF":["<base64>"]}}` o `{"respuesta":{"errores":[…]}}`.
- **La especificación dice que el servicio de validación no requiere autenticación y se presta desde el entorno de pruebas.** Es decir, se puede validar un fichero **sin certificado y sin custodiar ninguna clave**. Ojo: lo que se envía son datos de la declaración (ver §8, datos reales en pruebas). **[VERIFICAR]** que `ServValiDos` en concreto no pide certificado (el párrafo de la especificación se refiere a `ServVali`).
- Es complementario al simulador del formulario web que ya se usa (`docs/fiscal-vias-aeat.md`, §4d a §4f).

### 3.5 Modelos admitidos por el servicio de presentación

005, 030, 036, 100, **111, 115**, 117, 123, 124, 126, 128, **130, 131**, 151, 200, 202, 210, 211, 213, 216, 222, 232, 237, 242, **303**, 308, 309, 319, 322, 353, **390**, 490, 576, 604, 695, 696, 714, 780, 781, 792, 793, VEG, 20A y 22A. **No** admitidos: 006 y 568, ni ninguna declaración informativa (el 190, p. ej., queda fuera: se presenta por otra vía). Para validación e impresión el listado es el mismo salvo 005, 030, 036 y VEG.

### 3.6 Juego de caracteres

Solo los caracteres visibles de ISO-8859-1 de la tabla de la especificación (blanco, `& ' ( ) + , - . / 0-9 : ; A-Z a-z _ # @ " · º ª`, ñ, ç, vocales con acento agudo, grave, diéresis o circunflejo, y algunas letras latinas más). Nuestro exportador del 303 emite **solo ASCII**, así que queda dentro.

### 3.7 Entorno de pruebas para externos

- Operativo **solo en días laborables de 8:00 a 15:00**.
- Requiere internet y **firmar con certificado electrónico de usuario** (no se menciona un certificado de pruebas aparte). **[VERIFICAR]** con el CAID si sirve el certificado real del colaborador y qué datos pueden usarse.
- Los certificados del servidor son de **otra autoridad** que en producción: el cliente debe poder confiar en una u otra según el entorno.
- Si una presentación de prueba **tiene éxito, las siguientes deben ser complementarias** del mismo NIF/modelo/periodo.
- El PDF puede no estar disponible y, si lo está, lleva marca de agua. Los logs de errores se borran a diario: cualquier consulta al soporte se hace el mismo día.
- Hay que cuidar de **no usar nunca las URL de pruebas con usuarios finales**, ni las de producción para pruebas.

---

## 4. Estado real de Guilda Work (comprobado en el código, 6-nov-2026)

El borrador suponía menos de lo que hay. **Ya existe** (`app/fiscal_modelos/`, `app/fiscal_nucleo.py`):

- Motores y ficheros oficiales de **303** (`motor_303`, `fichero_303`, `exportador_303` con el diseño `DR303e26v101`), **390** (`motor_390`, `fichero_390`), **130/131** y **111/115** (`motor_130`, `motor_131`, `fichero_131`, `motor_retenciones`, `fichero_retenciones`).
- El 303 generado se probó contra el **simulador público** de la AEAT: importa sin errores, el validador detecta incoherencias a propósito y coincide con el calculado por la AEAT a partir de los libros (23 escenarios de libros y 11 ficheros especiales; `docs/fiscal-vias-aeat.md`). Lo que **no** acredita aceptación real hasta el piloto.
- Declaraciones con estados `borrador → revisada → exportada → presentada | anulada` (con trigger que impide cambiar casillas ya revisadas), instantáneas con hash, `fiscal_artefactos` (con hash) y auditoría de las descargas.
- `marcar_presentada(...)` ya anota **justificante de 13 cifras, CSV y fecha** y cierra el vencimiento del calendario; la rectificativa ya exige el justificante original.
- Módulo de certificados: **inventario de control sin custodia**; rechaza cualquier `.p12`/`.pfx` o clave privada, incluso en las subidas de documentos.

**No existe**: ningún cliente HTTP hacia la AEAT, ni almacén del justificante PDF, ni tabla de mandatos de presentación, ni la consulta de presentadas.

Por tanto el trabajo es **una capa fina**: el contenido de `F01` es el mismo fichero plano que ya genera `fichero_303` (una línea, ASCII, sin CRLF).

---

## 5. Arquitectura propuesta

### 5.1 Decisión que bloquea el resto: dónde vive la clave

El borrador decidió «presenta el servidor con el certificado del colaborador». Eso **choca con un principio vigente**: Guilda Work no custodia claves privadas (`docs/presentacion-directa-aeat.md`, caminos A/B/C; esa decisión sigue abierta). Como la especificación exige **TLS de cliente** (no una firma del fichero), la clave tiene que estar disponible en el momento de la conexión. Tres formas de resolverlo, de menor a mayor riesgo:

| | Cómo | Dónde está la clave | Riesgo | Esfuerzo |
|---|---|---|---|---|
| **B. Agente local** | Un programa en el equipo del despacho (o de quien tenga el certificado) descarga el `F01` ya revisado y confirmado, abre el TLS con su certificado y devuelve el justificante a Guilda | Nunca sale del equipo | Medio (hay que distribuir y mantener el agente; se pierde la presentación sin humano delante) | Medio |
| **A2. Servicio de presentación aislado** | Un servicio **aparte** (otro contenedor/usuario del sistema, sin acceso a la base de datos) que guarda la clave y solo acepta una orden por presentación firmada por la aplicación, ligada al hash del `F01`, el NIF, el modelo y el periodo. Si es posible, clave en HSM/KMS o token | En ese servicio | Medio-alto: una brecha de la aplicación no basta para presentar lo que se quiera, pero el servicio sí tiene la clave | Alto |
| **A1. El propio servidor** (lo que decía el borrador) | La aplicación guarda el certificado cifrado y abre ella la conexión | En la aplicación | **Máximo**: una brecha de la aplicación firma como el despacho. Obliga a revertir el principio de no custodia | Medio |

**Recomendación:** empezar el piloto con **B** (mismo certificado, la clave no se mueve, se aprende el flujo real con 1–2 clientes propios) y, si el volumen lo pide, construir **A2** reutilizando todo lo demás. Descartar **A1** salvo decisión expresa de la dirección. El cambio de B a A2 solo afecta a *quién abre la conexión TLS*; el resto (payload, confirmaciones, estados, justificantes, conciliación) es común.

### 5.2 Componentes

```
[Revisor] ──▶ Guilda Work UI
                  │
                  ▼
        Servicio de declaraciones (303)
          1. revisada (casillas congeladas, hash)
          2. F01 = fichero plano del exportador existente
          3. Validar (ServValiDos) → avisos / errores
          4. Confirmación humana (NIF, modelo, periodo, importe, hash)
          5. Presentar (agente B o servicio A2) con el certificado
          6. Guardar respuesta bruta + PDF del justificante (hash)
          7. presentada (+ vencimiento cerrado)
                  │
                  ▼
        AEAT (pre → producción)
```

1. **Constructor de petición** (`aeat_presentacion.py`, ya escrito en esta versión, sin red): arma el JSON del §3.2, comprueba el juego de caracteres y la ausencia de CRLF/tabuladores, calcula el hash que liga la orden al fichero revisado e interpreta las respuestas (correcta, error, dudosa).
2. **Cliente de validación** (sin certificado) contra `ServValiDos` en pruebas.
3. **Ejecutor de la presentación** (B o A2): lo único que cambia según §5.1.
4. **Almacén de justificantes**: PDF descargado de `urlPdf` y respuesta JSON bruta, con hash, en `fiscal_artefactos`.
5. **Conciliador**: `ConsultaExt` para respuestas dudosas y revisión periódica.

---

## 6. Flujo de presentación del 303

1. El revisor deja la declaración en `revisada`.
2. Comprobaciones previas automáticas: perfil fiscal sin bloqueos; mandato vigente del cliente; certificado del presentador vigente y que su NIF es el esperado; si hay IBAN, que es del declarante; modo (pruebas/producción) coherente con el despacho.
3. Se genera el `F01` y se **valida** con `ServValiDos`. Los **avisos** no impiden presentar; los **errores** sí (vuelve a `revisada` con los errores visibles).
4. **Confirmación explícita** de una persona autorizada, tecleando NIF del declarante, modelo y periodo, y mostrando importe y forma de pago. El envío queda ligado al **hash del `F01`** revisado: no se envía otra cosa.
5. Presentación. Se guarda siempre la respuesta bruta y el PDF.
6. Éxito (hay CSV, justificante y `urlPdf`): `presentada` con justificante de 13 cifras, CSV, expediente, fecha/hora, presentador y `TipoRepresentacion`.
7. Fallo o respuesta ambigua (tiempo agotado, JSON ilegible, corte): **no se reintenta a ciegas**. Primero `ConsultaExt` por NIF, modelo, ejercicio, periodo y rango horario del intento. Si consta, se recupera; si no, se permite reintentar.
8. Como no se puede anular lo grabado, un error detectado después se corrige con **complementaria o rectificativa**, con referencia al justificante original. La rectificativa ya existe en el módulo; el servicio admite enviar el fichero de la complementaria como cualquier otro. **[VERIFICAR]** campos del diseño para la complementaria.

Estados nuevos sugeridos: `validada → presentando → presentada`, con `error_validacion`, `error_envio` y `pendiente_conciliacion`.

---

## 7. Modelo de datos (sugerido)

Sobre `fiscal_declaraciones` (o tabla hija `fiscal_presentaciones`, una fila por intento):

- `entorno` (pruebas | produccion), `hash_f01`, `payload_enviado` (inmutable), `respuesta_aeat` (bruta).
- `justificante` (13), `csv` (16), `expediente`, `fecha_presentacion`, `tipo_representacion`, `forma_pago`, `importe_a_ingresar`.
- `presentador_nif`, `presentador_certificado_id`, `usuario_confirmo_id`, `confirmado_en`.
- `intentos` (fecha, resultado, correlación). Justificante PDF y respuesta en `fiscal_artefactos` con su hash.

Tabla de **mandatos** por cliente fiscal: tipo (colaboración social | apoderamiento), documento, fecha, vigencia, modelos cubiertos. Interruptor por despacho, **apagado por defecto**.

Toda tabla nueva exige una migración numerada (`app/bd/migraciones/LEEME.md`) con sus variantes multitenant y Citus, como la 019.

---

## 8. Seguridad y cumplimiento

- La custodia de la clave es el punto más crítico: ver §5.1. En B nunca sale del equipo; en A2 solo vive en un servicio aislado; no se escribe en registros ni en copias.
- Caducidad del certificado: reutilizar `riesgos_de_certificados`. Al renovar, actualizar el censo de colaboradores para no interrumpir presentaciones. Bloquear si está caducado o no coincide con el esperado.
- Registrar **qué persona** confirmó cada presentación, aunque la conexión sea con el certificado del colaborador. Permisos por rol y doble confirmación en producción.
- Auditoría completa: quién, cuándo, qué declaración, qué hash, resultado.
- **Entornos separados** y a prueba de error: la URL de producción nunca se usa con datos de prueba ni la de pruebas con envíos reales (la AEAT lo advierte expresamente).
- **Datos reales en pruebas.** La validación y el entorno de pruebas reciben datos de la declaración y están fuera de nuestra infraestructura. Hasta aclarar con el CAID qué se permite, usar **datos ficticios** (los NIF y ficheros de `/home/guilda/muestras-303/`), nunca clientes reales. **[VERIFICAR]**
- RGPD: Guilda actúa como encargada del tratamiento; revisar el contrato y la base legal. Plazos de conservación de justificantes y mandatos: consultar a la asesoría jurídica.

---

## 9. Pruebas

1. Unitarias, **sin red**, con respuestas de ejemplo de la especificación (hecho en esta versión para el constructor y el intérprete).
2. Validación con `ServValiDos` y datos ficticios, con los 23 + 11 casos del simulador.
3. Pruebas de presentación en `prewww1` (laborables 8–15 h): primera presentación y siguientes **como complementarias**.
4. Idempotencia: simular tiempos agotados y comprobar que, antes de reenviar, se consulta lo presentado.
5. Seguridad: acceso a la clave, permisos, auditoría y comprobación de que el hash enviado es el revisado.
6. Piloto: 1–2 clientes propios, un trimestre, contraste con la presentación manual en la Sede.

---

## 10. Modelo 390 (fase 3)

El motor y el fichero del 390 **ya existen** en el repositorio y el 390 está en la lista de modelos admitidos (§3.5). Falta: presentarlo con el mismo flujo, contrastar `DR390` con el validador y decidir el calendario (enero). **[VERIFICAR]** las condiciones de presentación del ejercicio 2026 en la especificación específica del 390.

---

## 11. Plan de trabajo

| Paso | Descripción | Estado |
|---|---|---|
| 0 | Alta como colaborador social y certificado | **Pendiente (Jorge)** |
| 1 | Leer especificaciones y cerrar los [VERIFICAR] | **Hecho** (queda lo marcado en §12) |
| 2 | Decidir dónde vive la clave (§5.1) | **Pendiente (decisión)** |
| 3 | Constructor de petición + intérprete de respuestas (sin red) | **Hecho** (`app/aeat_presentacion.py`, tests) |
| 3b | Validación con `ServValiDos` y datos ficticios | Pendiente (necesita visto bueno, §8) |
| 4 | Ejecutor de la presentación (agente B o servicio A2) en pruebas | Pendiente (depende de 0 y 2) |
| 5 | UI de confirmación, estados, errores y almacén de justificantes | Pendiente (migración nueva) |
| 6 | Conciliación con `ConsultaExt` (leer `consultas.xsd`) | Pendiente |
| 7 | Piloto en producción con clientes propios | Pendiente |
| 8 | 390 y otros modelos | Pendiente |

---

## 12. Preguntas abiertas

1. **¿A, B o A2 (§5.1)?** Es la que desbloquea el paso 4.
2. ¿Qué entidad hace el alta de colaboración social y cubre el envío directo por servicio web (no solo el formulario)? Consultar a la entidad y al CAID.
3. ¿Sirve el certificado real del colaborador en `prewww1`, y qué datos se pueden usar? (§3.7 y §8)
4. ¿Qué vías de pago admite el colaborador por envío directo en un 303 a ingresar (NRC vs. domiciliación)? (§2)
5. ¿Exige la AEAT homologación o declaración responsable del software? **La especificación v30 no la menciona**; se resuelve preguntándolo al CAID.
6. Mandato SEPA y autorización de domiciliación del cliente: cómo se recogen y custodian.
7. Complementarias y rectificativas en la primera versión: ¿solo la rectificativa que ya existe, o también la complementaria?
8. ¿Se consigna a Guilda como entidad desarrolladora en los campos de versión y NIF del programa del fichero (hoy en blanco)? (Pendiente desde `docs/fiscal-vias-aeat.md` §5)

---

## 13. Referencias

- Especificaciones de servicios (PDF, v30): https://www.agenciatributaria.es/static_files/AEAT_Desarrolladores/EEDD/General/EspecificacionesServiciosDeclaracionesAEAT_ES.pdf
- XSD de la consulta de declaraciones presentadas: https://www.agenciatributaria.es/static_files/AEAT_Desarrolladores/EEDD/General/consultas.xsd
- Documentación para desarrolladores: https://www.agenciatributaria.es/AEAT.desarrolladores/Desarrolladores/_menu_/Documentacion/Documentacion.html
- Modelo 303 para software comercial (PDF, escaneado): https://www.agenciatributaria.es/static_files/AEAT_Desarrolladores/EEDD/IVA/Mod_303/IVA303-CoordColabora_7.02.pdf
- Formas de presentación del 303: https://sede.agenciatributaria.gob.es/Sede/iva/presentar-declaracion-iva-modelo-303/formas-presentacion-modelo-303.html
- Colaboradores sociales (ayuda técnica): https://sede.agenciatributaria.gob.es/Sede/ayuda/consultas-informaticas/colaboracion-social-ayuda-tecnica/presentacion-declaraciones-colaboradores-sociales_.html
- Internas: `docs/fiscal-vias-aeat.md` (vías, simulador, evidencias) y `docs/presentacion-directa-aeat.md` (decisión sobre la clave).
