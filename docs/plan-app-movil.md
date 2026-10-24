# Plan de la app móvil: de la v1.0 a la plataforma completa (Flutter)

> **Estado:** borrador para decisión · **Fecha:** 2026-10-24 · **Base:** `main` en `dcfade4`, API `1.4`, PostgreSQL + Citus en producción desde hoy.
> **Alcance:** modelos Flutter, cliente de API, pantallas, arquitectura, servidor (lo que la app necesita que la API ofrezca), calidad, publicación y calendario.
> **Cómo se ha hecho:** con mediciones sobre el código real (no impresiones): análisis de `mobile/` (51 ficheros, 10.586 líneas), contrato OpenAPI vivo (376 operaciones, 149 esquemas), prueba del generador de modelos sobre respuestas reales de la API con datos sintéticos, `flutter analyze`/`flutter test`/`flutter pub outdated` en una copia aislada. Las cifras de este documento salen de ahí; las de esfuerzo son estimaciones y se marcan como tales.

> **Actualización (segunda sesión):** la experiencia de uso de la app (pantallas reales, flujos, sistema de diseño, errores, estados, pruebas de uso) y su apoyo en PostgreSQL (medidas de la API, **interbloqueos con peticiones concurrentes**, cursor de `/sync`, rendimiento) están en [`plan-ux-ui-app-y-postgresql.md`](plan-ux-ui-app-y-postgresql.md), con su impacto en este plan en su §C.

---

## 0. Resumen en una página

**Diagnóstico.** La app móvil se quedó en el producto de mediados de octubre. Hoy cubre **79 de 376 operaciones de la API (21 %)** y lee **123 de los 257 campos** de los modelos que sí tiene (48 %). Las ocho áreas nuevas de las últimas dos semanas (Hoy, comercial, contabilidad, abogados, inmobiliaria, jurídico, certificados, documentos) y todo el centro de notificaciones **no existen** en el móvil. Tareas, el corazón del producto, usa 9 de 34 campos: no sabe de versión/conflictos, bloqueos, subtareas, adjuntos, varios clientes, revisiones ni comentarios.

**Tres bloqueos antes de hablar de funciones** (están en el código, no son opinión):

1. **La versión de release de Android no tendría red**: `android/app/src/main/AndroidManifest.xml` no declara `INTERNET` (solo lo hacen `debug/` y `profile/`), ni `POST_NOTIFICATIONS` (Android 13+).
2. **No se puede firmar para tienda**: `build.gradle.kts` usa la firma de *debug* (`// TODO: Add your own signing config`), y el `applicationId` es `cat.guilda.guilda_work_mobile`.
3. **Las notificaciones push no funcionan**: no existe `google-services.json` ni `GoogleService-Info.plist`; **tampoco está el plugin `google-services` de Gradle**, ni en iOS el permiso *Push Notifications* (`aps-environment` en *entitlements*) ni `UIBackgroundModes: remote-notification`; `PushService.inicializar()` se traga el fallo y la app sigue sin push. El servidor sí emite (37 puntos de emisión y más de 30 tipos de aviso).

**Estrategia (no es una reescritura).**

| # | Decisión | Por qué |
|---|---|---|
| 1 | **Hacerla publicable primero** (Ola 0) | Sin firma, red de release y push, el resto no llega a nadie |
| 2 | **Generar los modelos y el cliente desde el OpenAPI** del servidor | Probado: 139 modelos, 26 enums y las 376 operaciones se generan y analizan con 0 problemas; 71 de 73 respuestas reales se leen sin tocar nada. Cierra la deriva para siempre |
| 3 | **Reorganizar la app alrededor de «Hoy»**, del **despacho activo** y de los **módulos activos** | Es como ya trabaja la web desde el 18-oct y donde el móvil aporta más |
| 4 | **Cinco olas de funciones**, cada una publicable | Valor temprano; la Ola 0+1 es un lanzamiento por sí sola |
| 5 | **Nativo para lo frecuente/urgente/con hardware; web dentro de la app para la larga cola** | 376 operaciones no se portan a pantallas nativas; se prioriza por uso móvil |
| 6 | **Servidor: API 1.5** con lo que la web ya tiene y la API no (Hoy, clientes, expedientes, plazos, horas, contactos, citas, despachos, capacidades) | Hay >400 herramientas MCP que ya llaman a esas funciones: es exponer, no inventar |

**Esfuerzo (estimación, ±30 %).** ~34 persona-semanas (app + servidor) más 1,5 de correcciones de UX/accesibilidad de la web (§12); con 1 persona de Flutter + 0,5 de servidor, ~23 semanas de calendario; con 2 + 0,5, ~15. **Lanzamiento mínimo útil (Olas 0+1): ~10 persona-semanas, ~7 semanas.** El cuello de botella no es escribir código: es **probar en dispositivos reales** (el servidor no compila Android/iOS), así que la Ola 0 incluye builds instalables por cada cambio.

**Barrido de UX/UI** de la web, el backoffice y la app (69+9 pantallas, escritorio y móvil, con axe-core): 27 hallazgos priorizados en §12 — lo más urgente: páginas de error sin marca y en inglés, alta de tareas que empuja la lista, y 3 tipos de fallo crítico de accesibilidad (13 elementos).

**Decisiones que necesito de ti** (detalle en §11): cuentas de tienda y alcance de publicación · proyecto Firebase · Riverpod + go_router · qué verticales importan primero en móvil · telemetría de errores · aceptar el «puente web» · nivel de tablet · versiones mínimas de SO.

**Las dos primeras semanas** (todo lo demás cuelga de esto): ver §9.

---

## 1. Punto de partida (medido el 2026-10-24)

### 1.1 La app hoy

| Medida | Valor |
|---|---|
| Versión | `1.0.0+1` · Flutter 3.44.9 / Dart 3.12.2 |
| Código | 51 ficheros, 10.586 líneas (sin los 5 ficheros de `l10n` generados) · 36 pantallas · 3 widgets propios |
| Pruebas | 3 ficheros, **15 pruebas**, 197 líneas · `flutter analyze`: 0 problemas · `flutter test`: todas pasan |
| Idiomas | es / ca / en / fr, **202 claves** por idioma; aun así quedan ~120 textos fijos en castellano en `screens/` |
| Estado | `setState` ×172, `FutureBuilder` ×22; **sin gestión de estado**, sin enrutador; cada pantalla recibe `api`, `sesion`, `sync`, `push`, `tema`, `locale` por constructor |
| Red | `ApiClient` de 1.304 líneas en un solo fichero; **sin paginación** (0 usos de `limit`/`offset`), sin `Idempotency-Key`, sin `X-Despacho`, sin `Accept-Language`, sin caché `ETag`, sin manejo de `429`/`Retry-After` |
| Sin conexión | Cola local (sqflite) **solo** para fichajes y notas rápidas |
| Seguridad | Token en `flutter_secure_storage` (bien); sin bloqueo biométrico; sin detección de despacho bloqueado (`423`) |
| Accesibilidad | 24 `tooltip`/`Semantics` en toda la app; 4 usos de `MediaQuery`/escala de texto |
| Tema | Mismos colores que la web (lima `#A6E600` / `#CCFF33`), pero radio 8 px frente a **12 px** de la web, sin Manrope/Inter, sin superficies «cristal», sin los tonos `*-text` de contraste AA |
| Nativo | Android: permisos `RECORD_AUDIO`, `ACCESS_*_LOCATION`; iOS: micrófono, voz, fotos, cámara, ubicación. Sin `INTERNET` en release, sin `POST_NOTIFICATIONS` |
| CI | `.github/workflows/mobile.yml`: `pub get` + `analyze` + `test`. No construye ni distribuye nada |
| Dependencias | 26 paquetes directos (20 con versión nueva); **muy atrasadas**: `firebase_core` 3→5, `firebase_messaging` 15→17, `flutter_local_notifications` 18→22, `geolocator` 13→14, `file_picker` 11→13, `connectivity_plus` 6→7. `matrix` 8→14 sigue declarada **sin usarse** (el chat lanza Element X) |

### 1.2 Cobertura de la API (`/api/v1`, 376 operaciones en 288 rutas)

| Área | Operaciones | En el móvil | Lo que falta (resumen) |
|---|---:|---:|---|
| fiscal | 71 | 10 | flujo de fases, documentos, mensajes con el cliente, avisos y acuse, panel, expedientes de control, traspasos, oficinas, papelera |
| tareas-outlook | 54 | 5 | detalle, estado con motivo y versión, subtareas, adjuntos, comentarios, dependencias, revisiones, clientes, recordatorios, compartir, tablero, carga, informes, vistas, cronómetro |
| correo | 44 | 19 | programados, seguimientos, plantillas, conversación, posponer, tarea/nota desde correo, lote, ajustes, firma, cuentas |
| fichaje | 27 | 12 | turnos, cuadrante, bolsa de horas, administración (resumen, corrección, integridad, exportaciones) |
| comercial | 20 | **0** | embudo, oportunidades, actividades, reuniones con acta de IA y tareas |
| ia | 18 | 7 | conversaciones múltiples, atajos, consumo, *streaming* |
| juridico | 15 | **0** | biblioteca, consultas con citas verificadas, adjuntos privados, informes |
| notas | 12 | 1 | **no hay pantalla de notas** (solo la nota rápida del inicio) |
| certificados | 11 | **0** | inventario, caducidades, riesgos, renovaciones |
| contabilidad | 9 | **0** | facturas, lectura con IA, revisión, exportación a a3 |
| abogados / inmobiliaria | 6 / 6 | **0** | vistas, provisión, partes, mensajes del enlace / visitas, cruces, resumen |
| tareas (cronómetro antiguo), categorías, proyectos, plantillas, recurrentes, reglas, checklist, companeros, mi-dia | 7+5+4+5+4+4+2+1+1 | 4 | todo salvo crear/borrar categoría y el cronómetro antiguo |
| notificaciones, comunicados, papelera, buscar, sync, documentos | 3+2+3+1+1+2 | **0** | centro de avisos, comunicados de la plataforma, papelera, búsqueda global, sincronización incremental, documentos |
| auth, perfil, tiquets, dispositivos-push, onboarding, herramientas, chat, dashboard, historial, avatar | 4+4+5+2+1+1+1+1+1+1 | 21 | (cubierto) |

### 1.3 Campos que los modelos actuales ignoran

| Modelo móvil → esquema API | Campos usados | Lo más relevante que no lee |
|---|---:|---|
| `TareaOutlook` → `TareaOutlook` | **9 / 34** | `version`, `motivo_bloqueo`, `clientes`, `tarea_padre_id`, `estimacion_min`, `asignada_a`, `comentarios_cliente`, `visible_cliente`, `vencida`, `vencimiento_id` |
| `ClienteFiscal` → `ClienteFiscal` | 7 / 23 | `email`, `oficina_id`, `pais`, `idioma`, `nif_normalizado` |
| `VencimientoFiscal` → `Vencimiento` | 9 / 24 | `fase`, `fase_motivo`, `bloqueada`, `bloqueo_motivo`, `documento_solicitado` |
| `FichajeEvento` → `Fichaje` | 5 / 14 | `hash`, `latitud`, `longitud`, `corrige_a`, `cliente_uuid` |
| `Mensaje` → `MensajeCorreoDetalle` | 15 / 27 | `cifrado`, `cifrado_nivel`, `cliente_fiscal_id`, `pospuesto_hasta`, `hilo_clave` |
| `Categoria` → `Proyecto` | 4 / 15 | `icono`, `orden`, `proy_cliente_id`, `proy_estado`, `proy_fecha_objetivo` |
| `CuentaCorreo` | 9 / 19 | firmas, `ultimo_error_sincronizacion`, TLS |
| `PerfilUsuario` | 2 / 3 | `avatar_url` |
| **Total (23 modelos comparables)** | **123 / 257 (48 %)** | |

(La comparación busca `json['campo']` en el código Dart; puede errar en unos pocos campos leídos por rutas indirectas.)

### 1.4 Lo que está bien y se conserva

- El sobre `{ok,data}` / `{ok:false,error,codigo,request_id}` ya se desempaqueta en un solo sitio (`ApiClient`).
- Cola offline con `cliente_uuid` idempotente para fichajes y notas, probada.
- `ApiException` con `codigo` y `esDeConexion`; 2FA en el login; refresco de sesión a 401.
- Marca y modo oscuro con la paleta de la web; i18n de cuatro idiomas con ARB; iconos y nombre de marca.
- Fichaje (con jornada contratada, ausencias y geolocalización opcional), calendario fiscal, IA con voz y *modo Live*, correo con reglas/remitentes: **no se tocan** salvo para adaptarlos al contrato nuevo.

---

## 2. Qué ha cambiado en la plataforma y qué toca al móvil

Relevancia móvil = cuánto sentido tiene hacerlo **en el móvil** (no en la web). Ola = dónde se planifica (§7).

| Novedad de la plataforma (fecha) | ¿API? | Móvil hoy | Relevancia | Ola |
|---|---|---|:-:|:-:|
| **Personas en varios despachos** + `X-Despacho` (23-oct, PostgreSQL) | Cabecera sí; **`/auth/me` no lista los despachos** | Ignora el despacho; siempre el principal | Alta | 0 |
| **Hoy**: bandeja única de lo que necesita cada persona, de todos los módulos (18-oct) | **No** (solo web, y `url` de pantallas web) | No existe | Alta | 1 |
| **Tareas P0** (20–22-oct): versión y `409`, motivo de bloqueo, varios clientes, subtareas, adjuntos, dependencias, revisión en cadena, informes, visibles al cliente, comentarios del cliente, recordatorios | Sí (54 ops) | 5 ops | Alta | 1 |
| **Centro de notificaciones** y comunicados de la plataforma | Sí | No existe (hay push, no bandeja) | Alta | 1 |
| Notas con adjuntos, fijadas, búsqueda | Sí | Solo crear nota rápida | Media | 1 |
| Búsqueda global (`/buscar`) y `/sync` incremental | Sí | No | Alta | 1 |
| Automatizaciones (reglas que crean tareas y avisan) | Solo MCP/web | No | Baja en móvil (editor); **sí** recibir sus avisos | 1 (avisos) |
| **Control fiscal**: fases de obligación, avisos con acuse, panel, expedientes de control, traspasos (14–23-oct) | Sí (71 ops) | Solo marcar presentado | Alta | 2 |
| **Documentos** del despacho y **cifrado por despacho** (`423 despacho_bloqueado`) | Sí (lectura) | No sabe de `423` | Media-alta | 2 |
| Certificados digitales (caducidades, riesgos, renovación) | Sí | No | Media | 2 |
| Ficha única de cliente, plantillas por tipo, oficinas, importar cartera (14–18-oct) | Parcial (`fiscal/clientes`); **núcleo (clientes, expedientes, plazos, horas) no** | Lista de clientes fiscales | Media | 2 |
| Laboral (reglas, TC/190, nóminas) | **No** | No | Baja-media | 5 (puente web) |
| **Ausencias, turnos, bolsa de horas** (13–15-oct) | Sí | Ausencias sí; turnos y bolsa no | Alta | 3 |
| **Correo C1–C6** (15-oct): contexto con clientes, tarea desde correo, contactos, programados, seguimientos, plantillas, bloqueo de remitentes, cifrado | Sí (44 ops) | 19 ops | Media | 3 |
| **Contabilidad de facturas** (19–20-oct): lectura de facturas con IA (foto/PDF), revisión, exportación a a3 | Sí | No | **Alta para cámara**; admin web | 4 |
| **Comercial**: embudo de oportunidades, reuniones con acta de IA (22–23-oct) | Sí | No | Media-alta (reuniones, dictado) | 4 |
| **Gabinete de abogados**: vistas, provisión, partes, mensajes del enlace público | Sí (solo lectura/respuesta) | No | Media | 4 |
| **Inmobiliaria**: visitas, cruces de demanda, mensajes del propietario | Sí | No | **Alta** (es trabajo de calle) | 4 |
| **Asistente jurídico**: consultas con citas verificadas, informes | Sí | No | Media | 4 |
| Portal del cliente: comentarios, archivos, antivirus | Sí (por tarea/expediente) | No | Media (avisos) | 1–2 |
| IA: conversaciones, atajos, consumo, *streaming* | Sí | Una conversación, sin atajos | Media | 1 |
| Tema y densidad **guardados en la cuenta** (11-oct) | Sí en BD; **no en `/perfil`** | Tema local | Media | 0 |
| Sistema de diseño «cristal» + Manrope (11–12-oct) | — | Mismo color, distinto aire | Media | 0 |
| API 1.4: límites 600/min, `Idempotency-Key`, `ETag`/304, `?campos=`, `X-Total-Count`, `/sync` | Sí | No usa nada de esto | Alta técnica | 0 |
| PostgreSQL + Citus, RLS (24-oct) | — (no cambia el contrato) | Sin impacto, salvo que **el despacho activo ya es obligatorio y verificado** | Info | 0 |
| Webhooks, tokens de API, auditoría | Sí | — | Baja (administración) | 5 (solo «mis dispositivos») |

---

## 3. Principios de producto (qué es el móvil y qué no)

1. **El móvil es lo que haces lejos de la mesa: ver, decidir, registrar y capturar.** No es un port de la web. Cada función entra con una pregunta: *¿qué hace una persona con el móvil en la mano que no haría delante del ordenador?* (aprobar una ausencia en el pasillo, fichar, contestar a un cliente, fotografiar una factura, dictar el acta de una reunión, ver las visitas de hoy, saber qué vence).
2. **Tres capas de profundidad**, para no portar 376 operaciones:
   - **Nativo completo**: frecuente, urgente, offline o con hardware (Hoy, Tareas, Notificaciones, Fichaje, Correo, vencimientos y avisos fiscales, IA con voz, captura con cámara, dictado).
   - **Nativo de consulta y respuesta**: ver y hacer lo mínimo (clientes, expedientes, plazos, certificados, comercial, abogados, inmobiliaria, jurídico).
   - **Web dentro de la app** (*puente web*, §4 ADR-M8): administración y configuración pesada (editor de automatizaciones, reglas fiscales/laborales, backoffice, ajustes de despacho, importar cartera, laboral, informes largos).
3. **El despacho activo y los módulos activos mandan.** La app no enseña lo que el despacho no tiene contratado ni lo que la persona no puede hacer (rol, `gestor_fichajes`, supervisor, alcance por oficina). Una sola fuente: `/auth/me` ampliado (§6, S-02).
4. **Cero reglas de negocio duplicadas.** La app no calcula vencimientos, estados permitidos ni permisos: pregunta a la API (paridad web/MCP/IA/API, ya en el plan maestro). Donde hoy hay lógica en el cliente (p. ej. `status_badge.dart`), se sustituye por lo que manda el servidor.
5. **Fuera de línea con honestidad.** Se pueden **leer** en caché y **escribir** en cola (fichar, notas, completar/crear/comentar tareas, acusar avisos, marcar leído). Nunca se promete lo que no se puede garantizar: cada elemento pendiente se ve como pendiente. Lo cifrado por despacho **no se guarda en claro** en el dispositivo.
6. **Privacidad por defecto.** Sin SDK de seguimiento de terceros; bloqueo biométrico opcional; se borra la caché al cerrar sesión o al cambiar de despacho; capturas de pantalla bloqueadas en pantallas sensibles (Android `FLAG_SECURE`, iOS cubierta en el selector de apps).
7. **Accesible y en cuatro idiomas desde la primera línea de cada pantalla** (es/ca/en/fr, escala de texto 200 %, TalkBack/VoiceOver, objetivos táctiles ≥ 48 dp, contraste AA con los tonos `*-text`).
8. **Una función solo está hecha cuando**: tiene modelo generado, pantalla con estados vacío/cargando/error/sin conexión, prueba de modelo con respuesta real, prueba de widget, traducción en 4 idiomas, accesibilidad revisada y entrada en el registro de cambios de la app.

---

## 4. Arquitectura objetivo y decisiones técnicas

No se reescribe: se **estrangula** (*strangler*). Primero se envuelve lo que existe con la base nueva (cliente, enrutador, estado, tokens de diseño) y después se sustituye módulo a módulo. Cada decisión lleva su alternativa y su coste; las que necesitan tu visto bueno están en §11.

### 4.1 Estructura de carpetas

```
mobile/lib/
  api/
    generado/          # modelos.g.dart + operaciones.g.dart   ← GENERADO del OpenAPI (nunca a mano)
    cliente.dart       # Dio + interceptores (auth, despacho, idioma, versión, idempotencia, ETag, 429)
    errores.dart       # ApiException tipada (red, auth, prohibido, bloqueado, conflicto, límite, validación)
    fechas.dart        # Fecha / MomentoLocal (el servidor emite hora local de Madrid sin zona)
  dominio/             # modelos de dominio ligeros que envuelven los DTO (enums con 'desconocido', cálculos)
  datos/               # repositorios por área (tareas, correo, fiscal, fichaje, notas, hoy, avisos…)
    local/             # drift: caché + cola de escritura genérica
  nucleo/              # sesión, despacho activo, capacidades, tema, idioma, push, conectividad, biometría
  funciones/<área>/    # pantallas, widgets y controladores (Riverpod) de cada área
  diseno/              # tokens.g.dart (GENERADO desde style.css), tema, componentes (§4.2 ADR-M5)
  l10n/                # ARB (es, ca, en, fr)
```

### 4.2 Decisiones (ADR de la app)

| ID | Decisión | Alternativa descartada | Coste / riesgo | Cómo se prueba |
|---|---|---|---|---|
| **M1** | **SDK Dart generado del OpenAPI** (`scripts/generar_sdk_dart.py`, hermano de `app/sdk_generador.py`, que ya genera Python, TypeScript y Postman). Modelos inmutables + operaciones tipadas, sin `build_runner` ni `json_serializable` | Mantener los modelos a mano (hoy: 48 % de los campos) · `openapi-generator` (Java, plantillas pesadas, no entiende nuestras `nullable`/sobres) | Hay que tratar `allOf` (2 casos), contenedores (10) y enums; el generador es nuestro y pequeño | Prototipo ya hecho (§5.2); prueba de deriva en CI: regenerar y comparar con lo versionado |
| **M2** | **Riverpod** (`flutter_riverpod`) para estado e inyección. `AsyncNotifier` por lista, `family` por id | Provider/`setState` actual · Bloc (más ceremonia) | Curva de aprendizaje; convive con pantallas antiguas mediante un adaptador (§4.3) | Pruebas de controlador sin UI |
| **M3** | **`go_router`** con `StatefulShellRoute` (barra inferior: **Hoy · Tareas · Correo · Fichaje · Más**), rutas tipadas y mapa *push → ruta*. Enlaces universales `https://app.guildawork.com/…` con `app_links` (ya es dependencia) | `Navigator.push` imperativo con `MaterialPageRoute` y el `navigatorKey` global de hoy | Servir `assetlinks.json` y `apple-app-site-association` desde Flask (S-12) | Pruebas de enrutado; abrir cada tipo de push |
| **M4** | **Drift** (SQLite tipado) para caché y **cola de escritura genérica** (`método, ruta, cuerpo, Idempotency-Key, intentos, estado`). Sustituye las dos tablas ad hoc de `SyncService` | Seguir con `sqflite` y SQL a mano · Hive/Isar (no relacional) | Generación de código (solo para la BD local); migración de la cola actual | Pruebas con `sqlite3` en memoria; simulacro de reconexión |
| **M5** | **Tokens de diseño generados** desde `app/static/style.css` (`scripts/exportar_tokens_dart.py` → `diseno/tokens.g.dart`) + Manrope/Inter incluidos en la app (ya son OFL y autoalojadas) | Copiar valores a mano (como hoy: «cualquier cambio de marca debe hacerse en LOS DOS SITIOS») | Interpretar `var()`/`color-mix`; superficies «cristal» solo en barras y hojas (rendimiento) | Prueba de deriva; *golden tests* de los componentes |
| **M6** | **Política de i18n**: ningún `Text('literal')`; ARB en 4 idiomas; *pseudo-locale* para detectar desbordes; el servidor responde en el idioma de `Accept-Language` (S-09) | Traducir «cuando haya tiempo» (hoy ~120 textos fijos) | Trabajo de barrido inicial (Ola 0) | Verificación en CI: claves iguales en los 4 ARB, marcadores iguales, sin literales |
| **M7** | **Errores tipados y reintentos seguros**: `ApiException` con `status`, `codigo`, `request_id`, `campo`, `retryAfter`; reintento automático solo para GET y POST con `Idempotency-Key`; respeta `429`/`Retry-After` | Un `catch (e) { setState(() => _error = e.toString()) }` por pantalla (hoy: 50 `catch` en pantallas) | Hay que decidir el texto/acción de cada categoría | Pruebas con `dio` simulado |
| **M8** | **Puente web**: WebView con sesión para la larga cola. Hoy el móvil usa un token Bearer y la web usa la cookie de Kratos; no comparten sesión, así que el WebView pide login aparte | Portar todo a nativo · No ofrecer nada | Requiere diseño de seguridad (S-11, *spike* de 2 días): ficha de un solo uso de 60 s que el servidor canjea por sesión web | Revisión de seguridad + prueba de caducidad/reutilización |
| **M9** | **Errores y rendimiento**: `sentry_flutter` contra **GlitchTip auto-alojado** (ya auto-alojáis Umami, Uptime Kuma, Metabase) · sin analítica de producto de terceros; la adopción se mide en servidor con `X-App-Version`/plataforma | Firebase Crashlytics (más fácil, ya añadimos Firebase para push; datos en Google) | Un servicio más que operar | Informe de prueba al provocar un fallo |
| **M10** | **Entornos con `--dart-define`**: `prod` y `staging` (con *flavors* de Android y esquemas de iOS para poder instalar ambos); servidor por defecto `https://app.guildawork.com`, y el cambio de servidor sigue oculto tras pulsación larga | Un único entorno (hoy) | Dos proyectos Firebase | Builds de ambos entornos en CI |
| **M11** | **Identificador de aplicación definitivo antes de subir nada**: propuesta `com.guildawork.app` (hoy `cat.guilda.guilda_work_mobile` / iOS `cat.guilda.guildaWorkMobile`) | Mantener el actual | Cambiarlo después de publicar es imposible; antes, gratis | — |

### 4.3 Cómo conviven lo viejo y lo nuevo (estrangulamiento)

1. **Ola 0** introduce `ProviderScope`, `go_router` y el cliente v2 **sin cambiar ninguna pantalla**: las 36 actuales se montan como rutas que reciben `api`/`sesion`/… desde los *providers* (un `PantallaLegada` adaptador).
2. Cada ola reescribe **un área completa** (pantallas + repositorio + modelos) y borra su código antiguo. `api_client.dart` adelgaza: lo que migra se elimina.
3. Al terminar la Ola 4, `api_client.dart` y `models/models.dart` desaparecen.

### 4.4 Contrato de «contexto» que debe poder leer la app (propuesta, S-02)

Se amplía `/auth/me` de forma aditiva (API 1.5; los clientes actuales lo ignoran):

```jsonc
{ "id": 7, "email": "…", "es_admin": false, "tenant_id": 3, "fichaje_geolocalizacion": true,   // lo de hoy
  "despachos":   [{"id": 3, "nombre": "Gestoría Pla", "principal": true, "rol": "miembro", "gestor_fichajes": true, "supervisor": false}],
  "modulos":     {"gestoria": true, "abogados": false, "inmobiliaria": false, "comercial": true, "contabilidad": true, "juridico": false, "certificados": true, "laboral": true},
  "permisos":    {"fichaje_admin": true, "supervisor_fiscal": false, "ver_como": false},
  "cifrado":     {"activo": true, "nivel": "medio", "desbloqueado": false},
  "apariencia":  {"tema": "sistema", "densidad": "normal", "idioma": "es"},
  "marca":       {"nombre": "Gestoría Pla", "color": "#1b6ef3", "logo_url": "…"},
  "app":         {"version_minima": "1.1.0", "version_recomendada": "1.3.0", "url_tienda": "…"} }
```

La app manda `X-Despacho: <id>` en cada petición con el despacho elegido, y `X-App-Version`/`X-App-Platform` para que el servidor pueda avisar de «actualiza».

---

## 5. Modelos Flutter y contrato

### 5.1 Situación

30 clases escritas a mano en `models/models.dart` (951 líneas) y `api_client.dart`, con `fromJson` manual y sin `toJson`. Dos problemas medibles: **leen la mitad de los campos** (§1.3) y **no se actualizan solas** cuando el servidor cambia. El servidor ya publica el contrato completo y verificado por tests (`tests/test_openapi_contrato.py`, `tests/openapi_baseline.json`).

### 5.2 Prueba de viabilidad del generador (hecha hoy; prototipo en `docs/anexos-app-movil/generar_sdk_dart_prototipo.py`)

Se hizo en dos pasadas (v1 solo modelos; **v2 con `allOf`, enums, `==`/`copyWith` y las operaciones**). Resultado de la v2:

| Comprobación | Resultado |
|---|---|
| Esquemas del OpenAPI vivo | 149 (139 con campos; los otros 10 son contenedores de lista/mapa, que las operaciones devuelven ya como `List<T>`/`Map`) |
| Modelos generados | **139**, con `fromJson`, `toJson`, `copyWith`, `==` y `hashCode` (2 con `allOf` fusionado) |
| Enums | **26**, cada uno con un valor `sinReconocer` (un estado nuevo del servidor no rompe a una app antigua) |
| Operaciones tipadas | **376 de 376** (`Future<TareaOutlook> obtenerTareaOutlook(...)`); 38 devuelven `dynamic` por ser los endpoints «sin forma» de §5.5 |
| Código generado | 5.260 líneas de modelos + 387 de operaciones; **`dart analyze`: 0 problemas** |
| Respuestas reales de la API capturadas con datos sintéticos (copia aislada, token real de prueba) | 122 intentos: **88 correctas (200)**, 16 × 404 (módulo no activado en el despacho de prueba), 15 × 403 (sin permiso), 3 × 400 (faltaban parámetros) |
| De las 88, mapeables a un modelo con nombre | 73 |
| **Leídas sin error por los modelos generados** (más `copyWith` ≡ original y `toJson`) | **71 de 73 (97 %)** |
| Las 2 que fallaron | Defectos reales del contrato, no del generador (§5.5) |

Conclusión: la estrategia M1 es viable y barata (el generador completo son ~170 líneas de Python sin dependencias). Los 15 endpoints sin modelo por referencia (`dashboard`, `mi-dia`, `tablero`, `fichaje/estado`…) devuelven objetos «sueltos» sin esquema con nombre: se resuelve nombrándolos en `openapi_catalogo.py` (S-03), lo que de paso mejora la documentación para integradores. Lo que **falta** del prototipo para ser el generador definitivo: cuerpos de petición tipados (hoy `Map<String, dynamic>`), subida *multipart* con ficheros, `Fecha`/`MomentoLocal`/`Importe` (§5.3), nombres de operación más cortos, y la prueba de deriva.

### 5.3 Reglas de generación (aprendidas en la prueba)

| Caso del contrato | Código Dart | Motivo |
|---|---|---|
| `integer` / `number` | `(x as num).toInt()` / `.toDouble()` | JSON entrega `3` o `3.0` indistintamente |
| `boolean` | `_aBool` (acepta `0/1`) | Hay campos que llegan como `1` (SQLite heredado: `activo: 1` en webhooks) |
| nulo | `T?` si `nullable: true` **o** si no está en `required` | Evita roturas por campos opcionales |
| `enum` | `enum` Dart **con valor `desconocido`** | Un estado nuevo en el servidor no rompe a una app antigua |
| `allOf` | Se fusionan las propiedades | `MensajeCorreoDetalle`, `WebhookCreado` |
| `array` de `$ref` / contenedores | `List<T>` / `typedef` | `ResultadoBusqueda`, `UsoToken`… |
| fechas (`string`) | Texto en el DTO; **tipos `Fecha`/`MomentoLocal`** en la capa de dominio | El servidor emite `AAAA-MM-DD` y `AAAA-MM-DDTHH:MM[:SS]` en hora de Madrid **sin zona**: no se usa `DateTime.parse` en pantallas (cambios de hora) |
| importes | `Importe` (céntimos enteros) en contabilidad | Evita errores de coma flotante en euros |
| nombres | `snake_case` → `camelCase`; reservadas (`default`, `in`, `is`…) llevan `_` | Ya resuelto en el prototipo |
| extra | `==`, `hashCode`, `copyWith`, `toJson` | El prototipo ya trae `toJson`; falta añadir el resto |

### 5.4 Capa de dominio: lo que **no** se genera

Los DTO son transporte. Encima, modelos de dominio pequeños con las reglas de presentación (nunca de negocio):

| Dominio | Sobre el DTO | Aporta |
|---|---|---|
| `Tarea` | `TareaOutlook` (34 campos) | `EstadoTarea` {noIniciada, enProgreso, completada, esperando, aplazada, enRevision, desconocido}, `Prioridad`, `abierta`, `bloqueada` (`motivo_bloqueo`), `versionOptimista` para `409`, `clientes` (varios), `progreso` de subtareas |
| `Obligacion` | `Vencimiento` (24) | `FaseObligacion`, indicadores `vencida`/`enRiesgo`/`bloqueada`/`presentada` **tal como los manda `/flujo`**, no recalculados |
| `ElementoHoy` | (nuevo, S-01) | `destino` tipado (`TareaDestino(id)`, `VencimientoDestino(id)`, `CorreoDestino(id)`, `VisitaDestino(id)`…) para navegar sin parsear URLs web |
| `Despacho` / `Capacidades` | `/auth/me` ampliado | Qué módulos y permisos hay; cambia de despacho |
| `Fichaje` | `Fichaje` + cola | Estado local «pendiente de enviar» |
| `Importe`, `Fecha`, `MomentoLocal` | — | Tipos de valor |
| `Pendiente<T>` | cola de escritura | Elemento optimista «pendiente / enviado / rechazado» |

### 5.5 Higiene del contrato (hallazgos de la prueba) — tarea de servidor S-03

| Hallazgo | Detalle | Arreglo |
|---|---|---|
| `GET /ia/conversaciones` | El esquema dice *lista de `ConversacionIA`*, la respuesta real es `{activa, conversaciones: []}` | Corregir el esquema en `openapi_catalogo.py` |
| `GET /ia/atajos` | `AtajoIA.id` es `integer` no nulo, pero los 6 atajos de serie devuelven `id: null` | Marcar `nullable` o devolver un id estable de serie |
| 15 endpoints «sin forma» | `dashboard`, `mi-dia`, `tablero`, `fichaje/estado`, `fichaje/resumen-semana`, `chat/config`, `tareas-outlook/carga`, `…/dependencias`, `…/tiempo`, `fiscal/modelos`, `fiscal/recordatorios`, `fiscal/clientes/{id}/resumen`, `correo/plantillas/variables`, `tokens/{id}/uso`, `webhooks/catalogo-eventos` | Darles esquema con nombre |
| Enums sin declarar | `estado`, `prioridad`, `fase`, `tipo` figuran como `string` en muchos esquemas | Declarar `enum` en el catálogo (25 ya lo están) |
| Conflictos de edición | El mismo concepto responde distinto: tareas → `409 version_obsoleta` con `version_actual`; clientes y vencimientos fiscales y expedientes de control → `412 version_obsoleta` sin ella. Otros `409` llevan `solo_por_revision`, `revision_pendiente`, `tarea_bloqueada`, `dependencia_invalida` | La app decide por `codigo`, no por el número; esquema `ConflictoDeVersion`; añadir `version_actual` también en los `412` (aditivo) |
| Prueba que lo vigile | El contrato valida respuestas de lo cubierto por tests; estos endpoints no tenían caso | Añadir al contrato **un caso por endpoint GET** (el script de captura de la prueba sirve de base) |

### 5.6 Modelos por ola (149 esquemas; asignación por el primer uso)

| Ola | Nº | Esquemas |
|---|---:|---|
| **0** Fundaciones | 5 | `Usuario`, `Sesion`, `Perfil`, `Herramienta`, `EstadoServicio` (+ nuevos: `Capacidades`, `Despacho`, `Marca`) |
| **1** Día a día | 47 | Tareas: `TareaOutlook`, `ActividadTarea`, `AdjuntoTarea`, `ChecklistItem`, `ClienteDeTarea`, `ClientesDeTarea`, `ComentarioTarea`, `ComentarioOculto`, `Companero`, `RecordatorioTarea`, `ReglaRecurrente`, `ReglaVencimiento`, `PlantillaTareas`, `RevisionTarea`, `RevisionesDeTarea`, `SubtareasDeTarea`, `TiempoTarea`, `InformeTareas`, `Tablero`, `MiDia`, `TareaConDuracion`, `Vista`, `VisibleCliente`, `ConversacionCliente`, `RespuestaAlCliente`, `ResultadoLote`, `ResultadoAdjuntos(Tarea)` · Notas: `Nota`, `AdjuntoNota` · `Proyecto`, `Historial`, `Papelera`, `Identificador`, `Tiquet` · Avisos: `Notificacion`, `NotificacionesRespuesta`, `Comunicado` · Búsqueda y sync: `ResultadoBusqueda`, `Sincronizacion` · IA: `MensajeIA`, `ConversacionIA`, `AtajoIA`, `ModeloIA`, `PreferenciasIA`, `ConsumoIA`, `RespuestaIA` · (nuevo) `ElementoHoy`, `SeccionHoy` |
| **2** Gestoría | ~36 | `ClienteFiscal`, `ClienteFiscalDetalle`, `Vencimiento`, `DocumentoVencimiento`, `MensajeVencimiento`, `FlujoObligacion`, `ConfigFlujo`, `Presentacion`, `AvisoFiscal`, `ConfigAvisosFiscales`, `MetricasAvisos`, `PanelFiscal`, `ExpedienteControl`, `DetalleExpedienteControl`, `PuntoLista`, `Traspaso`, `Oficina`, `Membresia`, `ResponsableAsignado`, `AccesoCliente`, `Concesion`, `EventoAuditoria`, `ConfigRecordatorios`, `Archivada`, `Revocada`, `Certificado`, `CertificadoRenovado`, `RiesgoCertificado`, `ConfigAvisosCertificados`, `DocumentoCliente`, `DocumentoDespacho`, `Documento`, `ResultadoSubida`, `ResultadoImportacion`, `ResultadoComentario`, `ResultadoTransicion` |
| **3** Personal y correo | 24 | `Fichaje`, `FichajeDatos`, `Integridad`, `Ausencia`, `SaldoAusencias`, `BolsaHoras`, `BolsaEquipo`, `Cuadrante`, `TurnoTipo`, `TurnoAsignado`, `CuentaCorreo`, `Carpeta`, `CategoriaCorreo`, `MensajeCorreo`, `MensajeCorreoDetalle`, `PlantillaCorreo`, `PreferenciasCorreo`, `ReglaCategoriaCorreo`, `RemitenteConfiable`, `SeguimientoCorreo`, `EnvioCorreo`, `EnvioResultado`, `DestinatarioReciente`, `ResultadoCambio` |
| **4** Negocio y verticales | ~29 | Comercial: `EmbudoComercial`, `EtapaComercial`, `OportunidadComercial(Detalle)`, `ReunionComercial`, `ConversionComercial`, `TareasCreadasDeReunion` · Contabilidad: `FacturaContable(Detalle)`, `ExportacionContable`, `ChequeoExportacion`, `ResumenContabilidad` · Abogados: `ParteAsunto`, `ProvisionAsunto`, `VistaAgenda`, `ResultadoConflicto`, `HiloMensajes` · Inmobiliaria: `InmuebleResumen`, `VisitaAgenda`, `CruceDemanda`, `ResumenAgencia` · Jurídico: `AdjuntoJuridico`, `BusquedaJuridica`, `ColeccionJuridica`, `DocumentoJuridico`, `FuenteJuridica`, `InformeJuridico(Detalle)`, `RespuestaJuridica`, `VersionJuridica` |
| **5** Plataforma | ~8 | `Token`, `TokenCreado`, `UsoToken`, `Webhook`, `WebhookCreado`, `NombreEvento`, `Error` (solo «mis dispositivos»/sesiones en móvil) |

(Como el generador crea los 149 de una vez, esta tabla no es trabajo de modelos, sino **orden de pantallas**: qué modelos se usan y se prueban en cada ola.)

### 5.7 Pruebas del contrato en el móvil

1. **Huellas (*fixtures*)**: el servidor genera `mobile/test/fixtures/api/*.json` con un guion (`scripts/capturar_fixtures_movil.py`, derivado del que se usó hoy) sobre datos sintéticos en la copia aislada. Se versionan, para que las pruebas de Dart no necesiten servidor.
2. **Prueba de lectura por fixture**: un test de Dart recorre `fixtures/` y lee cada fichero con su modelo (hoy: 71/73 a la primera).
3. **Prueba de deriva**: en el CI del servidor, regenerar el SDK y los tokens y fallar si difieren de lo versionado.
4. **Prueba de compatibilidad hacia atrás**: ampliar `openapi_baseline.json` para detectar *cambios que rompen a un cliente tipado* (campo que pasa de no nulo a nulo, enum que pierde un valor, tipo que cambia).
5. **Prueba de integración con servidor real** (Ola 1): `integration_test` de Flutter contra una instancia de demostración aislada (la que ya levanta `tests/e2e/conftest.py` con Playwright) en un emulador de Android del CI.

---

## 6. Trabajo en el servidor (API 1.5) que la app necesita

La mayoría es **exponer por REST lo que la web y el MCP ya hacen** (el MCP tiene más de 400 herramientas sobre las mismas funciones de dominio). Todo es **aditivo**: ningún campo ni ruta existente cambia, así que la app actual sigue funcionando. Cada punto lleva su prueba de contrato y entra en `api_versiones.py` como `1.5`.

| ID | Qué | Por qué lo necesita la app | Tamaño | Ola |
|---|---|---|:-:|:-:|
| **S-01** | `GET /hoy` — la bandeja de `bandeja_hoy.reunir()` con `destino` tipado (`{tipo, id}`) en lugar de la `url` web, y `acciones` permitidas por elemento | Es la pantalla inicial; hoy solo existe en HTML y con URLs de la web | M | 1 |
| **S-02** | `/auth/me` ampliado (`despachos`, `modulos`, `permisos`, `cifrado`, `apariencia`, `marca`, `app`) — §4.4 | Selector de despacho, qué menú enseñar, qué puede hacer, cifrado, «actualiza la app» | M | 0 |
| **S-03** | Higiene del contrato (§5.5): corregir `ia/conversaciones` y `ia/atajos`, dar esquema a 15 endpoints «sin forma», declarar enums, `ConflictoDeVersion`, `version_actual` también en los `412`; **un caso de contrato por GET** | Un cliente tipado no tolera lo que un cliente web permisivo sí | S | 0 |
| **S-04** | **Núcleo por REST**: `/clientes` (ficha única), `/clientes/{id}/…`, `/expedientes`, `/plazos`, `/horas`, `/contactos`, `/citas`. Nueva área de token `nucleo` en `api_areas.py` | Hoy el móvil solo ve «clientes fiscales»; la web ya tiene clientes, expedientes, plazos y horas (12-oct). Las herramientas MCP `listar_clientes_despacho`, `listar_expedientes_despacho`, `listar_plazos_despacho`, `resumen_*` existen | L | 2 |
| **S-05** | **Push estándar**: todo mensaje lleva `data = {tipo, destino:{tipo,id}, despacho_id, notificacion_id}`, título/cuerpo en el idioma de la persona, canal Android por familia, y `GET /notificaciones` con `desde`, `tipo`, `despacho`; preferencias por tipo en `/perfil` | Hoy solo viaja `tipo`/algún id suelto; al tocar un aviso la app solo sabe abrir el correo. 37 puntos de emisión, 30+ tipos (Apéndice B) | M | 1 |
| **S-06** | `/sync` con más entidades: `vencimientos`, `clientes_fiscales`, `notificaciones`, `ausencias`, `fichajes_propios` | Lectura sin conexión y arranque rápido; hoy solo notas, tareas, proyectos | M | 2 |
| **S-07** | **Cifrado desde el móvil**: `GET /seguridad/cifrado/estado` y `POST /seguridad/cifrado/desbloquear` (frase de paso → concesión ligada al token, con caducidad corta y revocable) | Con el despacho cifrado, un token creado al iniciar sesión **no tiene concesión**: documentos y correo cifrados darían `423` para siempre. Hoy solo se desbloquea desde la web | M | 2 |
| **S-08** | `POST /documentos` (multipart) a cliente o expediente; categorías | Subir desde cámara/escáner/«compartir con Guilda». Hoy solo hay lectura (2 operaciones) | M | 2 |
| **S-09** | **Mensajes de la API en el idioma de `Accept-Language`**: envolver con `gettext` los ≈220 literales de error (113 líneas con `_err(...)` y 107 con `abort(4xx)` en `rutas_api*.py`) y completar es/ca/en/fr | La app ya está en 4 idiomas; los errores salen en castellano | M | 0–1 |
| **S-10** | Versión mínima de la app: `X-App-Version` → `426 actualiza` solo si es inferior a la mínima (y campo `app` en `/auth/me`) | Poder retirar versiones rotas sin dejar a nadie colgado | S | 0 |
| **S-11** | **Puente web** (spike de 2 días + implementación): ficha de un solo uso de 60 s que el servidor canjea por sesión web en un WebView | La larga cola sin portar ~250 pantallas; hoy el WebView pide login aparte | M | 0 (spike) / 5 |
| **S-12** | Enlaces universales: `/.well-known/assetlinks.json`, `/.well-known/apple-app-site-association` y reglas para `/tareas/*`, `/correo/*`, `/fiscal/*`, `/expedientes/*` | Que un enlace de un correo de aviso abra la app en la pantalla correcta | S | 1 |
| **S-13** | `dispositivos-push` con `despacho`, `idioma`, `app_version`, `plataforma`; y «mis dispositivos» (listar/revocar sesiones del móvil) | Push en el idioma y despacho correctos; seguridad de cuenta | S | 1 / 5 |
| **S-14** | `/perfil`: `apariencia` (tema, densidad, idioma) en lectura y escritura | El tema ya vive en la cuenta (11-oct) y el móvil no lo sabe | S | 0 |
| **S-15** | **Contabilidad por archivo**: `POST /contabilidad/facturas/archivos` (multipart: `cliente_fiscal_id`, `tipo`, 1–10 archivos) sobre `facturas_contables.subir_archivos()` | Hoy se puede anotar una factura (JSON) y «leer con IA», pero **no existe forma de subir el archivo por API**: sin esto no hay captura con cámara | S | 4 |
| **S-16** | **Inmobiliaria**: `POST` de resultado de visita y nota; **Abogados**: marcar señalamiento visto | Las agendas son de solo lectura; en la calle hay que poder anotar | S | 4 |
| **S-17** | `GET /tareas-outlook` con `campos=`, `limit/offset` y `X-Total-Count` validados en todos los listados que use la app; `ETag` en detalle | Paginación e *If-None-Match* para batería y datos | S | 1 |
| **S-18** | Entorno de **demostración aislado** para pruebas de integración y revisión de tiendas (`scripts/servidor_demo.sh`, reutiliza la fixture de Playwright) con un despacho de ejemplo y usuario de revisión | Probar la app contra una API real y dar credenciales al revisor de Apple/Google | M | 0 |

**Contrato propuesto de `GET /hoy` (S-01).** Reutiliza `bandeja_hoy.reunir()`, que hoy devuelve 11 secciones (`tareas`, `correo`, `plazos`, `mensajes`, `visitas`, `vencimientos`, `traspasos`, `ausencias`, `facturas`, `contabilizacion`, `certificados`) con `url_for(...)` de la web. Se cambia la `url` por un `destino` que la app sabe abrir; las secciones de módulos no activos simplemente no vienen:

```jsonc
{ "ok": true, "data": {
    "total": 5, "urgentes": 2, "generado_en": "2026-10-24T15:10:00",
    "secciones": [
      { "clave": "vencimientos", "titulo": "Vencimientos fiscales", "total": 3, "urgentes": 2,
        "elementos": [
          { "titulo": "303 · Talleres Soler SL", "detalle": "3T", "fecha": "2026-10-16T00:00",
            "urgencia": "vencido",                                   // vencido | hoy | proximo | info
            "destino": { "tipo": "vencimiento", "id": 41 },          // tarea | correo | vencimiento | plazo | expediente | visita | traspaso | ausencia | factura | factura_contable | certificado
            "acciones": ["abrir", "presentar"] } ] } ],
    "destacados": [ /* los más urgentes de todas las secciones, mismo formato */ ] } }
```

Se mantiene la `url` web como campo opcional para el puente web, y se añade a `api_areas.py` como área `avisos`/transversal para tokens restringidos.

**Cuidado con los límites de la API** (ya existen y la app debe respetarlos): 600 peticiones/min por persona, 200 escrituras/min y 20 operaciones pesadas/min (IA, exportaciones, sincronizar un buzón, enviar correo). Una pantalla de «Hoy» que lance 12 peticiones al abrirse y se refresque con *pull-to-refresh* repetido puede rozarlos: por eso `/hoy` es **una** llamada, y la app usa `ETag`, `campos=` y `/sync`.

---

## 7. Las cinco olas (más la Ola 0)

Cada ola termina con una versión **instalable por tu equipo** (TestFlight / prueba interna de Play) y su casilla de aceptación. Esfuerzo en **persona-semanas (pw)**, trabajo tradicional; con asistencia de IA el código puede ir bastante más rápido, pero **no** la validación en dispositivos, las tiendas ni el diseño. Marcar ±30 %.

### Ola 0 — Fundaciones y «publicable» · 4 pw (3 móvil + 1 servidor)

**Objetivo:** que cualquier cambio posterior se pueda construir, instalar, probar y publicar, y que la app hable bien con la API 1.4/1.5.

| # | Tarea | Detalle |
|---|---|---|
| 0.1 | **Publicable en Android e iOS** | `INTERNET` y `POST_NOTIFICATIONS` en el manifiesto principal; firma de release (almacén de claves fuera del repositorio, en secretos del CI); `applicationId`/*bundle id* definitivos (M11); versión por `--build-name/--build-number`; icono adaptativo y pantalla de arranque; iOS: *capabilities* de Push, *Associated Domains*, `PrivacyInfo.xcprivacy`, textos de permisos revisados y justificados |
| 0.2 | **Firebase de verdad** | Proyecto; `google-services.json`/`GoogleService-Info.plist` por entorno (fuera del repositorio, en secretos del CI); plugin `com.google.gms.google-services` en Gradle; en iOS, *capability* Push (`Runner.entitlements`), `UIBackgroundModes`, clave APNs subida a Firebase; canales de Android; prueba de punta a punta (el servidor ya envía). También `android:allowBackup="false"` y reglas de copia de seguridad (§8.3) |
| 0.3 | **Dependencias** | Subir `firebase_core` 3→5, `firebase_messaging` 15→17, `flutter_local_notifications` 18→22, `geolocator` 13→14, `file_picker` 11→13, `connectivity_plus` 6→7, `flutter_secure_storage` 10→11, `open_filex`, `dio`…; **quitar `matrix`** (sin uso). **Medido en una copia aislada:** el salto resuelve con un único ajuste (`geolocator` 14 choca con `connectivity_plus` ≥ 7.3.2 por `dbus`: fijar `connectivity_plus ^7.3.1`) y deja **28 problemas de análisis en 5–6 ficheros**: el código de `matrix` (`matrix_service`, `salas_chat`, `sala_chat`, `chat_login`: se borra, ya no se usa), `push_service` (cambia la API de inicialización/mostrado de `flutter_local_notifications` 22 y `firebase_messaging` 17 marca `getToken`/`onTokenRefresh` como obsoletos) y `correo_compose_screen` (`file_picker` 13 cambia `withData`/`files`). Estimación: 1–2 días + prueba de push; `minSdk`/iOS mínimos (D8) |
| 0.4 | **CI/CD** | `mobile.yml` ampliado: analizar + probar + **construir APK/AAB firmado e IPA** y publicarlos como artefactos y en distribución interna (Firebase App Distribution/TestFlight/Play interna); *flavors* `staging`/`prod`; caché de Gradle/Pods; *runner* macOS para iOS |
| 0.5 | **SDK Dart generado + cliente v2** | Convertir el prototipo en `scripts/generar_sdk_dart.py` + prueba de deriva; `cliente.dart` con interceptores (auth, `X-Despacho`, `Accept-Language`, `X-App-Version`, `Idempotency-Key`, ETag, `429`/`Retry-After`); `ApiException` tipada (M7); `Fecha`/`MomentoLocal` |
| 0.6 | **Estado, rutas y *shell*** | Riverpod, `go_router`, barra inferior (Hoy · Tareas · Correo · Fichaje · Más), adaptador para las 36 pantallas actuales; **selector de despacho** y capacidades (S-02); pantalla «actualiza la app» (S-10) |
| 0.7 | **Sistema de diseño** | `tokens.g.dart` desde `style.css` (M5), Manrope/Inter, radios 12/10/22, tonos `*-text` AA; componentes: estado vacío / error / cargando (esqueleto) / sin conexión, hoja de acciones, diálogo de confirmación, selector con búsqueda, campo de fecha unificado, avisos tipo *toast* con «deshacer»; tema y densidad desde la cuenta (S-14) |
| 0.8 | **i18n** | Barrido de los ~120 textos fijos a ARB (4 idiomas); verificación en CI (M6); `Accept-Language` |
| 0.9 | **Cola de escritura genérica** (drift) | Migra la cola de fichajes/notas; `Pendiente<T>`; reintentos con `Idempotency-Key`; indicador «N pendientes» |
| 0.10 | **Seguridad base** | Bloqueo biométrico opcional, `FLAG_SECURE`/cubierta en el selector de apps, borrado de caché al cerrar sesión o cambiar de despacho, almacenamiento seguro con accesibilidad `first_unlock` |
| 0.11 | **Cumplimiento de tiendas** | Borrado de cuenta dentro de la app (Apple 5.1.1(v)) — o decidir quitar el registro público (D10); política de privacidad enlazada; ficha de seguridad de datos de Google; credenciales de revisión sobre la demo (S-18) |

**Servidor:** S-02, S-03, S-09 (inicio), S-10, S-13, S-14, S-18 · **Spike:** S-11.
**Aceptación:** build firmado instalable desde el CI en un Android y un iPhone reales · login con 2FA, fichaje (también sin conexión), calendario fiscal y correo funcionan **igual que hoy** sobre el cliente nuevo · un push de prueba llega y abre la pantalla correcta · cambio de despacho sin mezclar datos · `analyze`, pruebas y comprobaciones de deriva/i18n en verde · cero literales en `screens/`.

### Ola 1 — El día a día: Hoy, Tareas, Avisos, Notas, Búsqueda, IA · 6 pw (4,5 móvil + 1,5 servidor)

**Objetivo:** que una persona del despacho resuelva con el móvil la mayor parte de su jornada. **Cierra el lanzamiento mínimo (Ola 0+1).**

| # | Pantalla / función | Modelos | Notas de diseño |
|---|---|---|---|
| 1.1 | **Hoy** (pantalla inicial) | `ElementoHoy`, `SeccionHoy` | Secciones por urgencia (vencido · hoy · próximo), «destacados», acción rápida por elemento (completar, posponer, abrir), insignia de pendientes, *pull-to-refresh*, caché con la hora de la última actualización |
| 1.2 | **Tareas — lista y filtros** | `TareaOutlook`, `Vista`, `Proyecto`, `Companero` | Ámbitos (propias · asignadas · compartidas · todas), estado, prioridad, cliente, fechas, búsqueda, **vistas guardadas** (propias y compartidas), paginación infinita, selección múltiple (lote ≤ 200) |
| 1.3 | **Tareas — tablero, calendario, Mi día, carga** | `Tablero`, `MiDia`, `InformeTareas` | Tablero por estado con arrastrar entre columnas; calendario (ya existe); Mi día; carga de equipo según permisos |
| 1.4 | **Tarea — detalle completo** | `TareaOutlook`, `ChecklistItem`, `SubtareasDeTarea`, `ComentarioTarea`, `AdjuntoTarea`, `ClientesDeTarea`, `RevisionesDeTarea`, `RecordatorioTarea`, `ActividadTarea`, `TiempoTarea` | Cabecera con estado y **motivo de bloqueo**; cambio de estado por `/transiciones` con `version` → conflicto `409` con diálogo «alguien la ha editado: ver cambios / sobrescribir»; subtareas (la padre no se cierra con subtareas abiertas); adjuntos con cámara/galería/archivo, progreso y vista previa; comentarios con @menciones; dependencias (bloqueada = no empezar); varios clientes con principal; recordatorios (atajos «un día antes…»); compartir (colabora/observa); **revisión en cadena** (pedir, aprobar, pedir cambios); visible al cliente + **conversaciones con el cliente** (ocultar comentario); cronómetro vinculado |
| 1.5 | **Crear rápido** | — | Un campo, voz opcional, prioridad, cliente, fecha («mañana», «el viernes»); plantillas y recurrentes (aplicar) |
| 1.6 | **Avisos** (centro de notificaciones) | `Notificacion`, `Comunicado` | Bandeja agrupada por día, marcar leídas, borrar, filtros por tipo; **insignia en la barra**; comunicados críticos fijos; preferencias por tipo y «no molestar»; mapa *tipo → pantalla* (Apéndice B) |
| 1.7 | **Notas** | `Nota`, `AdjuntoNota` | Lista, fijar, búsqueda, editor, adjuntos (imágenes/PDF), «nota desde correo»; nota rápida del inicio se mantiene |
| 1.8 | **Búsqueda global** | `ResultadoBusqueda` | Notas, tareas y correo en una barra; recientes; resultados que navegan por `destino` |
| 1.9 | **Asistente de IA** | `ConversacionIA`, `MensajeIA`, `AtajoIA`, `ConsumoIA`, `PreferenciasIA` | Varias conversaciones, atajos, respuesta en *streaming*, confirmación de acciones con campos legibles, consumo del mes, **«preguntar a la IA sobre esto»** desde tarea/cliente/vencimiento (contexto de ficha); dictado y lectura en voz alta se conservan |
| 1.10 | **Papelera** | `Papelera` | Restaurar / eliminar definitivamente |
| 1.11 | **Sin conexión de tareas y notas** | — | Arranque desde caché; `/sync` incremental por cursor; cola: crear, completar, cambiar estado, comentar, fijar nota |
| 1.12 | **Enlaces universales y push con destino** | — | Cada push y cada enlace del correo de aviso abre la pantalla exacta |

**Servidor:** S-01, S-05, S-12, S-17, resto de S-09.
**Pruebas propias de la ola:** conflicto de versión simulado (dos clientes); subida de adjunto con corte de red; cola sin conexión → reconexión sin duplicados (`Idempotency-Key`); 429 con `Retry-After`; deep link por cada tipo de push que emite Tareas/Correo/Fiscal.
**Aceptación:** una persona de prueba completa un día entero de tareas desde el móvil (crear, asignar, comentar con adjunto, pedir revisión, completar, ver lo de Hoy) · arranque en frío ≤ 2,5 s en un Android de gama media · sin pérdida de datos en 20 ciclos de pérdida/recuperación de red · **Beta cerrada** a tu equipo.

### Ola 2 — Gestoría: fiscal, clientes, documentos, certificados · 6 pw (4 móvil + 2 servidor)

**Objetivo:** que la gestoría lleve **su control fiscal** desde el móvil, y consulte cualquier cliente en la calle.

| # | Pantalla / función | Modelos | Notas |
|---|---|---|---|
| 2.1 | **Panel fiscal** («qué mirar hoy») | `PanelFiscal` | Vencidas, próximas 7 días, bloqueadas, por revisar; filtro por oficina/persona según alcance |
| 2.2 | **Obligación (vencimiento) con flujo** | `Vencimiento`, `FlujoObligacion`, `Presentacion`, `DocumentoVencimiento`, `MensajeVencimiento` | Fase y transición con motivo, bloqueo con motivo, **justificante con cámara** (≤ 8 MB), constancia PDF, documentos que sube el cliente desde su portal, **mensajes con el cliente** (notifica por correo), conflicto `412` por `codigo` |
| 2.3 | **Avisos fiscales con acuse** | `AvisoFiscal`, `ConfigAvisosFiscales` | Notificación accionable **«Lo llevo»** (acuse con nota) desde la propia notificación; métricas solo dirección |
| 2.4 | **Expedientes de control** | `ExpedienteControl`, `DetalleExpedienteControl`, `PuntoLista` | Lista, ficha, lista de comprobación (marcar hecho), comentarios con @menciones, estado, revisor ≠ responsable |
| 2.5 | **Traspasos** | `Traspaso` | Aceptar / rechazar (motivo obligatorio) / cancelar |
| 2.6 | **Clientes — ficha única** | `ClienteFiscalDetalle` + núcleo (S-04) | Buscar, llamar, escribir, abrir en mapa; pestañas Datos · Contactos · Tareas · Vencimientos · Documentos · Resumen; alta y edición con control de versión; oficina y responsable |
| 2.7 | **Expedientes y plazos del núcleo** | (S-04) | Lista y ficha ligera; **plazos** próximos y festivos |
| 2.8 | **Documentos** | `DocumentoCliente`, `DocumentoDespacho` | Listar, ver (PDF/imagen), descargar, **subir** desde cámara/escáner/«compartir con Guilda» (S-08); si hay `423` → pantalla de **desbloqueo** (S-07) |
| 2.9 | **Certificados** | `Certificado`, `RiesgoCertificado` | Inventario por caducidad, riesgos de obligaciones sin cobertura, «comprobar ahora», abrir renovación y marcar renovado |
| 2.10 | **Calendario fiscal** (existente) | `Vencimiento` | Se adapta al modelo nuevo; vista por oficina |

**Servidor:** S-04, S-06, S-07, S-08.
**Sin conexión:** lectura en caché de clientes, vencimientos, avisos; escritura en cola: marcar presentado, acuse, comentario, nota de expediente.
**Aceptación:** un gestor recorre su semana fiscal (panel → obligación → justificante con foto → mensaje al cliente → presentada) sin abrir la web · un despacho con cifrado activado puede desbloquear y leer un documento · un cliente nuevo se da de alta en el móvil sin duplicar NIF.

### Ola 3 — Personal y correo · 5 pw (4 móvil + 1 servidor)

| # | Pantalla / función | Modelos | Notas |
|---|---|---|---|
| 3.1 | **Fichaje** (rediseño menor) | `Fichaje`, `FichajeDatos` | Estado, jornada, resumen semanal, geolocalización opcional (ya está); `hash` e integridad visibles para quien gestiona |
| 3.2 | **Turnos y cuadrante** | `TurnoAsignado`, `TurnoTipo`, `Cuadrante` | Mis turnos 2 semanas; cuadrante del despacho (gestores); **push «tu cuadrante ha cambiado»** |
| 3.3 | **Bolsa de horas** | `BolsaHoras`, `BolsaEquipo` | Mi saldo por mes y ajustes; la del equipo para quien gestiona |
| 3.4 | **Ausencias** (completar) | `Ausencia`, `SaldoAusencias` | Pedir, cancelar, **aprobar en equipo desde la notificación**, calendario de ausencias del equipo |
| 3.5 | **Avisos de fichaje** | — | «Salida olvidada» (`fichaje_salida_olvidada`) con corrección en dos toques |
| 3.6 | **Correo — bandeja** | `MensajeCorreo`, `Carpeta`, `CuentaCorreo` | Filtros destacados/no leídos/todas las carpetas, acciones por lote, posponer, categorías y reglas, bloqueo de remitentes; `cifrado` y `423` |
| 3.7 | **Correo — lectura** | `MensajeCorreoDetalle`, `HiloMensajes` | Conversación; **contexto** (cliente, vencimientos, tareas del cliente); **crear tarea / nota desde el correo**; adjuntos |
| 3.8 | **Correo — redactar** | `PlantillaCorreo`, `EnvioCorreo`, `DestinatarioReciente` | Autoguardado de borradores, plantillas con variables del cliente, firma e identidades, contactos con autocompletado, **programar envío**, «avísame si no responde» (`SeguimientoCorreo`), cancelar envío |
| 3.9 | **Notificación de correo accionable** | — | Archivar / marcar leído / responder rápido desde la notificación |
| 3.10 | **Acceso rápido al fichaje** | — | Acciones del icono (*App Shortcuts*) «Fichar entrada/salida» |

**Servidor:** pequeño (la mayoría ya está en la API); S-05 completo para estos tipos.
**Aceptación:** una persona ficha, pide y recibe aprobación de una ausencia y consulta su bolsa sin web · contesta un correo de un cliente creando de paso la tarea desde el propio mensaje · el correo programado sale a su hora y se puede cancelar.

### Ola 4 — Negocio y verticales · 8 pw (5 móvil + 3 de servidor y pruebas)

Los cinco bloques son **independientes** y se pueden reordenar o activar por despacho (los gobiernan `modulos` de S-02). Orden recomendado según valor móvil (D4):

| # | Bloque | Pantallas (nativo) | Servidor | pw |
|---|---|---|---|:-:|
| 4.1 | **Contabilidad — captura** | Cámara/galería/PDF → **subir** → «leer con IA» → pantalla de **revisión** (imagen a un lado, datos al otro; cuadre de IVA; avisos) → revisada; resumen por cliente; exportación solo web | S-15 | 1,5 |
| 4.2 | **Inmobiliaria** | Resumen de agencia, **agenda de visitas** (hoy/semana) con llamar y mapa, inmuebles (lista/ficha), **cruces de demanda**, mensajes del propietario (responder), anotar resultado de visita | S-16 | 2 |
| 4.3 | **Comercial** | Embudo por etapas, oportunidades (ficha, actividades rápidas, mover/ganar/perder con motivo, convertir en cliente), **reuniones con acta**: dictado/transcripción en el dispositivo, aviso de grabación, acta con IA, crear tareas desde el acta | — | 2 |
| 4.4 | **Abogados** | Señalamientos (30 días) con recordatorio, **provisión de fondos**, partes del asunto, **comprobar conflicto**, mensajes del enlace público (responder) | — | 1,5 |
| 4.5 | **Asistente jurídico** | Consulta con **citas verificadas** (fuente, versión, fecha), informes guardados y su revisión, adjuntos privados con estado de extracción | — | 1 |

**Aceptación por bloque:** el flujo de campo completo sin web (p. ej. 4.1: foto → factura revisada y lista para exportar en < 2 min; 4.2: visitas de hoy → llamar → anotar resultado).

### Ola 5 — Plataforma y pulido · 5 pw

| # | Tarea |
|---|---|
| 5.1 | **Tablet y plegables**: `NavigationRail`, lista-detalle en dos paneles, horizontal |
| 5.2 | **Widgets de inicio** (Android/iOS): «Fichar», «Hoy» (3 elementos), «Próximo vencimiento»; **compartir hacia Guilda** (foto/PDF → tarea, expediente o factura) |
| 5.3 | **Puente web completo** (S-11 implementado): Laboral, reglas fiscales/laborales, automatizaciones, importar cartera, ajustes de despacho, informes largos |
| 5.4 | **Cuenta y seguridad**: mis dispositivos, cerrar sesión remota, 2FA (alta vía puente), borrar cuenta |
| 5.5 | **Accesibilidad**: auditoría completa con TalkBack/VoiceOver y escala 200 %; guías de contraste y objetivos en pruebas de widget |
| 5.6 | **Rendimiento**: perfilado, tamaño de la app (≤ 40 MB arm64), arranque, memoria, batería (sin sondeos; push + `/sync`) |
| 5.7 | **Sincronización en segundo plano** limitada (WorkManager / BGTaskScheduler) para vaciar la cola |
| 5.8 | **Observabilidad** (GlitchTip), paneles de adopción en servidor |
| 5.9 | **Tiendas**: fichas, capturas por idioma, vídeo, textos legales, revisión final |
| 5.10 | **Ayuda contextual en la app** reutilizando `ayuda.py` y la documentación |

---

## 8. Calidad: cómo sabremos que está bien

### 8.1 Pirámide de pruebas

| Nivel | Qué cubre | Dónde corre | Meta |
|---|---|---|---|
| **Modelos y contrato** | Lectura de cada *fixture* real con su modelo; deriva del SDK y de los tokens; compatibilidad hacia atrás del contrato | CI del servidor y del móvil | 100 % de los GET con caso; fallo si algo deriva |
| **Unitarias** | Repositorios, controladores, cola de escritura, errores, fechas/importes | `flutter test` | ≥ 80 % en `api/`, `datos/`, `dominio/` |
| **Widget** | Cada pantalla en sus **cuatro estados** (vacío, cargando, error, sin conexión) + datos; modo claro/oscuro × escala de texto 1,0 y 2,0; *goldens* de los componentes base | `flutter test` | Una por pantalla nueva |
| **Accesibilidad automática** | `androidTapTargetGuideline`, `labeledTapTargetGuideline`, `textContrastGuideline` en cada widget test | `flutter test` | 0 incumplimientos |
| **Integración** (`integration_test`) | Flujos reales contra la **demo aislada** (S-18) en un emulador | CI (Linux con KVM) | 12 flujos (abajo) |
| **Manual guiado** | TalkBack/VoiceOver, notificaciones reales, cámara, geolocalización, tiendas | Dispositivos reales | Lista por ola |

**Los 12 flujos de integración:** (1) login con 2FA · (2) fichar sin red → reconectar sin duplicados · (3) crear, asignar y completar una tarea · (4) conflicto de versión con diálogo · (5) comentar con adjunto · (6) abrir un push → pantalla correcta · (7) cambiar de despacho sin mezclar datos · (8) `423` → desbloqueo → documento · (9) factura por cámara → revisión · (10) enviar un correo programado y cancelarlo · (11) pedir y aprobar una ausencia · (12) vencimiento → justificante → mensaje al cliente → presentada.

### 8.2 Presupuestos de rendimiento (se miden en cada ola)

| Medida | Meta | Cómo |
|---|---|---|
| Arranque en frío hasta «Hoy» con datos en caché | ≤ 2,5 s (Android de gama media) | `flutter drive --profile` + trazas |
| Peticiones al abrir una pantalla | ≤ 3 (Hoy: **1**) | Registro del cliente |
| Fotogramas lentos al desplazar listas | < 1 % | DevTools |
| Tamaño de descarga (arm64) | ≤ 40 MB | `flutter build apk --analyze-size` |
| Peticiones por minuto en uso intenso | < 40 % del límite (600/min) | Contador del interceptor |
| Batería | Sin sondeos en segundo plano | Revisión de código |

### 8.3 Seguridad (guía OWASP MASVS nivel 1 como mínimo)

- **Almacenamiento:** token en Keychain/Keystore; ni contraseñas ni frase de paso en disco; sin contenido cifrado por despacho en caché (solo metadatos); caché separada por `despacho_id` y borrada al cerrar sesión/cambiar de despacho; copias de seguridad del SO excluidas para BD y cola.
- **Red:** solo HTTPS (`usesCleartextTraffic=false`, ATS por defecto); *certificate pinning* **opcional** (decisión D6 ampliada: riesgo de bloqueo si se rota el certificado de Let's Encrypt; recomendación: fijar la clave pública con respaldo).
- **Plataforma:** `FLAG_SECURE` en pantallas sensibles, cubierta en el selector de apps, bloqueo biométrico, enlaces universales verificados (no `guildawork://` abierto).
- **Cuenta:** 2FA ya admitido en el login; cierre de sesión remoto; token por dispositivo con nombre; límites y `Retry-After` respetados.
- **Cadena de suministro:** `flutter pub outdated` trimestral, `dependabot` para `pub`, `gradle` y `cocoapods`; sin SDK de seguimiento.
- **Revisión:** una pasada de revisión de seguridad antes de la beta (Ola 1) y otra antes de publicar (Ola 5), incluido el puente web (S-11).

### 8.4 Matriz de dispositivos

Android 8 (API 26) a 15 · iOS 15 a la última · móvil pequeño 360×640, grande 412×915, tablet 10", plegable · idioma del sistema en es/ca/en/fr · modo oscuro · escala de texto 200 % · sin red / red lenta / red intermitente.

---

## 9. Las dos primeras semanas (lo que desbloquea todo lo demás)

**Semana 1 — «instalable en tu móvil el día 2»**

| Día | Hecho |
|---|---|
| 1 | Decisiones D1, D2, D8, D9 (§11). Abrir cuentas: Apple Developer (puede tardar días; con organización pide D-U-N-S), Google Play Console, Firebase. Crear el proyecto Firebase con apps `prod`/`staging` |
| 1–2 | `INTERNET` + `POST_NOTIFICATIONS`, firma de release, identificador definitivo, versión; CI que **construye un APK firmado** y lo deja como artefacto → **primer APK instalable** |
| 2–3 | Subir dependencias (Firebase 3→5…), quitar `matrix`, `analyze` + 15 pruebas en verde; iOS: *capabilities*, claves APNs, primer IPA a TestFlight |
| 3–4 | Servidor: S-02 (`/auth/me` ampliado), S-03 (higiene del contrato), S-10, S-14 y su prueba de contrato |
| 4–5 | `scripts/generar_sdk_dart.py` (del prototipo) + prueba de deriva + `scripts/capturar_fixtures_movil.py` + test de lectura por fixture en Dart |

**Semana 2 — «la base nueva con la app de siempre dentro»**

| Día | Hecho |
|---|---|
| 6–7 | `cliente.dart` v2 (auth, despacho, idioma, versión, `Idempotency-Key`, ETag, 429) + `ApiException` tipada; las 36 pantallas actuales ya hablan con él (adaptador) |
| 7–8 | Riverpod + `go_router` + barra inferior + selector de despacho + «actualiza la app» |
| 8–9 | `tokens.g.dart` + fuentes + componentes base (estados vacío/error/cargando/sin red) |
| 9–10 | Barrido de i18n (~120 textos) + verificación en CI; push de prueba de punta a punta; **primera beta interna** (TestFlight + prueba interna de Play) |

Al final de la semana 2: la app hace **lo mismo que hoy**, pero publicable, instalable, con el contrato generado y lista para recibir las pantallas de la Ola 1.

---

## 10. Calendario, esfuerzo y riesgos

### 10.1 Esfuerzo

| Ola | Contenido | pw móvil | pw servidor | pw total |
|---|---|---:|---:|---:|
| 0 | Fundaciones y publicable | 3 | 1 | 4 |
| 1 | Hoy, Tareas, Avisos, Notas, Búsqueda, IA | 4,5 | 1,5 | 6 |
| 2 | Gestoría: fiscal, clientes, documentos, certificados | 4 | 2 | 6 |
| 3 | Personal y correo | 4 | 1 | 5 |
| 4 | Negocio y verticales | 5 | 3 | 8 |
| 5 | Plataforma y pulido | 4 | 1 | 5 |
| W | Correcciones de UX/accesibilidad de la web (§12; en paralelo a la Ola 0) | 0 | 1,5 | 1,5 |
| | **Total** | **24,5** | **11** | **35,5** |

Con **1 persona de Flutter + 0,5 de servidor** (secuencial): ~23 semanas. Con **2 + 0,5** (Olas 2 y 3 en paralelo, Ola 4 por bloques): ~15 semanas. **Lanzamiento mínimo (Olas 0+1): 10 pw → ~7 semanas con 1,5 personas.** Con asistencia de IA para el código el calendario puede acortarse (tu ritmo de estas semanas lo demuestra), pero tres cosas no se aceleran: **probar en dispositivos**, **las revisiones de tienda (1–7 días por envío)** y **el diseño de UX validado con uso real**.

### 10.2 Calendario orientativo (1,5 personas; las semanas son de calendario)

```
Sem  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23
Ola0 ████████                                                       ← APK instalable día 2 · beta interna sem 2
Ola1       ██████████████                                           ← MVP: BETA CERRADA (fin sem 7-8)
Ola2                         ██████████████                         ← S-04 (núcleo) empieza sem 6 en servidor
Ola3                                       ██████████               ← parte puede solaparse con Ola 2
Ola4                                                 ██████████████ ← por bloques, según demanda (D4)
Ola5                                                         ████████
Tiendas        │ cuentas y fichas desde sem 1      │ pública tras Ola 2 (D1)
```

### 10.3 Camino crítico

`cuentas de tienda (D1)` → `firma y Firebase` → `CI con builds` → `SDK generado + cliente v2` → `shell Riverpod/go_router` → **Ola 1**. El servidor (S-01, S-05) debe estar listo **antes** de las pantallas de Hoy y Avisos: se adelanta en la semana 3–4. S-04 (núcleo por REST) es el mayor trabajo de servidor y bloquea la Ola 2: empezarlo hacia la semana 6.

### 10.4 Riesgos

| # | Riesgo | Prob. | Impacto | Mitigación |
|---|---|:-:|:-:|---|
| R1 | No se puede compilar ni probar la app en este servidor (sin Android SDK/Xcode) y cada iteración depende de tu móvil | Alta | Alto | CI que genera APK/IPA por cada cambio y los distribuye; emulador en CI para integración; builds `staging` instalables junto a producción |
| R2 | Cuentas de Apple/Google tardan o piden verificación de organización | Media | Alto | Abrirlas el día 1 (D1); mientras, distribución interna |
| R3 | Rechazo de tienda (borrado de cuenta, funcionalidad mínima, credenciales de revisión, etiquetas de privacidad) | Media | Medio | Ola 0.11; demo de revisión (S-18); textos de permisos revisados |
| R4 | Deriva entre contrato y app | Alta (hoy ocurre) | Alto | SDK generado + deriva en CI + *fixtures* + compatibilidad hacia atrás |
| R5 | Cifrado por despacho: un token sin concesión da `423` en documentos y correo | Alta | Medio | S-07 (desbloqueo desde la app), pantallas de «protegido», nada cifrado en caché |
| R6 | Límites de la API (600/min, 200 escrituras/min) con muchas pantallas | Media | Medio | `/hoy` en una llamada, `ETag`, `campos=`, `/sync`, cola con ritmo |
| R7 | Alcance desbordado (376 operaciones) | Alta | Alto | Tres capas (nativo / consulta / web); olas con criterio de aceptación; Ola 4 por bloques |
| R8 | El puente web abre una vía de sesión nueva | Media | Alto | *Spike* + revisión de seguridad antes de implementar; alternativa: login en el WebView (ya funciona) |
| R9 | Migrar a Riverpod/`go_router` rompe pantallas antiguas | Media | Medio | Adaptador `PantallaLegada`; prueba de humo por pantalla; migrar por áreas |
| R10 | Saltos grandes de dependencias (Firebase 3→5, Gradle, iOS) | Media | Medio | Ya medido (tarea 0.3): 1 conflicto de resolución y 28 avisos en 5–6 ficheros; rama dedicada con las 15 pruebas como red de seguridad; probar el push en dispositivo antes de seguir |
| R11 | Datos de otro despacho en caché al cambiar | Baja | **Muy alto** | Clave de caché con `despacho_id`, borrado al cambiar, prueba de integración (flujo 7) |
| R12 | Horas locales sin zona + cambios de hora | Media | Medio | Tipos `Fecha`/`MomentoLocal`; sin `DateTime.parse` en pantallas; pruebas en los dos cambios de hora |
| R13 | Fatiga de notificaciones | Media | Medio | Preferencias por tipo, agrupación, «no molestar» (ya existe), resúmenes diarios |
| R14 | Registro público desde la app crea cuentas sin despacho y sin verificar correo (`/auth/registro`) | Media | Medio | D10: quitarlo de la app o alinearlo con el alta web |
| R15 | Rendimiento de la API tras el corte a PostgreSQL | Baja | Medio | Medir con `pg_stat_statements` el p95 de los endpoints que usa la app; presupuestos de §8.2 |

### 10.5 Métricas de éxito (se miran desde la Ola 1)

Adopción (% de personas activas con la app a 30 días) · % de fichajes hechos desde el móvil · tareas completadas desde el móvil · sesiones libres de fallos ≥ 99,5 % · tiempo hasta «Hoy» · errores de API por 1.000 peticiones (< 5) · valoración en tiendas ≥ 4,5 · tickets de soporte «móvil» por semana.

---

## 11. Decisiones que necesito de ti

| # | Decisión | Mi recomendación |
|---|---|---|
| **D1** | **Publicación**: tiendas públicas, o distribución privada (TestFlight + prueba cerrada de Play) | Privada hasta terminar la Ola 2; pública después. **Abrir las cuentas ya** (Apple puede pedir D-U-N-S) |
| **D2** | **Firebase**: ¿tuyo o de la organización?, ¿un proyecto con dos apps (prod/staging)? | Un proyecto, dos apps, a nombre de la organización |
| **D3** | **Riverpod + go_router + drift** (M2–M4) | Sí; si prefieres otra opción (Bloc, `auto_route`, sqflite) lo cambio en la Ola 0, después es caro |
| **D4** | **Orden de los verticales** (Ola 4) | Contabilidad (cámara) → Inmobiliaria (visitas) → Comercial (reuniones/dictado) → Abogados → Jurídico; dime qué clientes reales mandan |
| **D5** | **Telemetría de errores**: GlitchTip auto-alojado o Crashlytics | GlitchTip (datos en vuestra infraestructura, SDK de Sentry) |
| **D6** | **Puente web**: aprobar el *spike* S-11 y la revisión de seguridad. Y *certificate pinning*: ¿sí/no? | Spike sí; pinning con clave pública y respaldo, solo en `prod` |
| **D7** | **Tablet**: ¿desde ya o en la Ola 5? | Diseño adaptable desde la Ola 0 (sin anchos fijos); optimizar en la Ola 5 |
| **D8** | **Versiones mínimas**: Android 8 (API 26) e iOS 15 | Sí (las versiones recientes de Firebase exigen iOS 15; confirmarlo en la tarea 0.3) |
| **D9** | **Identificador de la app**: `com.guildawork.app` (iOS/Android) | Sí, **antes** de subir nada a una tienda |
| **D10** | **Registro público desde la app** (`/auth/registro`: crea cuenta sin despacho, sin verificar correo) | Quitarlo de la app: el alta es por invitación de un despacho; dejar «solicitar acceso». Evita además el requisito de borrado de cuenta propio de las altas abiertas |
| **D11** | **Fondo/estética**: ¿adoptar el «cristal» de la web en el móvil o una versión sobria? | Tokens iguales y superficies sobrias; «cristal» solo en barras y hojas (coste de rendimiento) |
| **D12** | **Idioma de las respuestas del asistente y de los avisos**: el de la cuenta | Sí |

---

---

## 12. Barrido de UX/UI (web, backoffice y app móvil)

**Método (24-oct, copia aislada, nada de producción):** instancia de la app con un despacho de ejemplo (6 clientes, tareas, vencimientos, notas) y la del backoffice con una cuenta de prueba; Chromium (Playwright) recorrió **69 pantallas de la app y 9 del backoffice, en escritorio (1366×800) y móvil (390×844)**, midiendo desbordes, errores de JavaScript, estructura (`h1`, idioma), tamaño de objetivos táctiles y **accesibilidad con axe-core 4.10 (WCAG 2.0/2.1/2.2 A-AA + buenas prácticas)**; además se revisaron capturas a mano. Capturas de referencia en `docs/ux-barrido-2026-10-24/`. El Chrome conectado a la sesión no respondió, así que **no se revisó producción con datos reales**: lo medido son las plantillas y el CSS que sí corren en producción.

### 12.1 Lo que está bien (conviene no romperlo)

- **0 desbordes horizontales** en 138 cargas (69 pantallas × 2 anchos) y **0 errores de JavaScript**; un único `h1` por página; `lang="es"` correcto; ninguna carga > 2,5 s con datos de ejemplo.
- Navegación consistente (carril de iconos, «+ Nuevo», «Hoy», fichaje en la barra superior), modo oscuro y claro, densidad, selector con búsqueda.
- Backoffice: lenguaje visual coherente (oscuro), 0 errores, 0 desbordes, buscador global `Ctrl K`.

### 12.2 Hallazgos priorizados (web de la app)

| ID | Sev. | Hallazgo (evidencia) | Propuesta | Tamaño |
|---|:-:|---|---|:-:|
| **UX-01** | Alta | **Las páginas 403/404 son las de Werkzeug**: sin marca, en inglés, `lang="en"`, sin zona principal («Not Found / The requested URL was not found…»). Además, un **módulo no contratado responde 404 desnudo** (en la prueba: `/comercial/`, `/contabilidad/`, `/abogados/`, `/inmobiliaria/`, `/juridico/`) y `/fichaje/admin` sin permiso da un 403 igual | Página de error propia (marca, idioma de la persona, «volver», «¿falta algo? Este módulo no está activo en tu despacho · contactar»), con `main` y `h1` | S |
| **UX-02** | Alta | **Tareas (lista): el alta y los filtros empujan la lista fuera de pantalla.** En móvil, **más de 1.000 px** de formularios antes de la primera tarea (4 filtros + 10 controles de alta); en escritorio, 10 controles apretados en dos filas | Alta de una línea (asunto) con «Más opciones» plegable; filtros en una fila de *chips* plegable; en móvil, botón flotante «+» que abre una hoja | M |
| **UX-03** | Media | **Fila de tarea sobrecargada**: dos casillas distintas (seleccionar y completar), botón de texto «Cronómetro» en cada fila, y en móvil la «✕» queda huérfana en otra línea | Una sola casilla visible (la de selección aparece al activar el modo lote); cronómetro y borrar en un menú «⋯» / gesto lateral en móvil | M |
| **UX-04** | Media | **Fechas**: «Vence 2026-10-22» y «2026-10-28» en Hoy, Tareas y Calendario fiscal (formato técnico); los `datetime-local` nativos dependen del idioma del navegador y quedan sin etiqueta visible (axe: 14 casos) | Fechas relativas y localizadas («ayer», «mié 28 oct»); aplicar el selector propio (`ds_fecha`) también al alta de tareas | S–M |
| **UX-05** | Media | **Calendario fiscal · Vencimientos**: agrupa por cliente con una cabecera por **un** vencimiento, ordena por cliente (los **vencidos quedan al final**), dobla las pestañas (Clientes/Vencimientos… y Lista/Calendario) y reserva ~30 % de ancho a un panel vacío («Pulsa un vencimiento…») | Orden por urgencia por defecto, agrupación opcional, panel de ficha rápida colapsado hasta elegir, una sola fila de pestañas | M |
| **UX-06** | Media | **Inicio en móvil: 3.541 px de scroll y 11 bloques apilados** (primeros pasos, estadísticas, nota rápida, nueva tarea, proyectos, **formulario de crear proyecto con rejilla de iconos**, vencimientos, hoy, **asistente de IA incrustado con un gran vacío**) | Móvil: «Necesita tu atención» + accesos; el resto plegado; la IA en su panel flotante; crear proyecto en una hoja | M |
| **UX-07** | Media | **Hoy (escritorio)**: dos tarjetas y ~60 % de pantalla vacía; sin acciones rápidas (completar, posponer); sin estado «todo al día»; fechas técnicas | Acciones en línea, estado vacío positivo, secciones en columna única adaptable; es el modelo de la pantalla «Hoy» de la app (Ola 1) | M |
| **UX-08** | Media | **Accesibilidad (axe, 138 cargas)** — *críticas*: `aria-pressed` sobre un enlace («Solo los míos», Avisos fiscales, 10 nodos); `select` sin nombre (`cliente_fiscal_id`, 2); separador de correo sin `aria-valuenow`. *Graves*: **contraste** en las etiquetas del calendario fiscal (`.cal-chip-fiscal`, 15 nodos); controles que solo llevan `title` (14); barras de progreso sin nombre (onboarding, 2); regiones con scroll sin acceso por teclado (tablas de carga; 4); objetivos < 24 px (10, p. ej. «favorito»); logo de Altcha `aria-hidden` enfocable. *Moderadas*: `aside#rail-principal` repetido (13 nodos en 11 páginas) y páginas sin `main`. *Menores*: 8 `th` vacíos | Corregir las críticas y graves (1–2 días) y **añadir axe a `tests/e2e`** para que no vuelva | S–M |
| **UX-09** | Baja | **Objetivos táctiles**: en móvil, **353 de 888 controles (40 %) miden < 40 px** (iconos «✎», «✕», favorito, chips); la guía mínima de WCAG 2.2 es 24 px y las de Apple/Google 44/48 | Mínimo 44 px de zona pulsable en móvil (relleno, no icono más grande) | M |
| **UX-10** | Baja | **Texto muy pequeño**: mínimo 9,2 px en escritorio (chips/etiquetas) y 9,9 px en móvil | Suelo de 12 px | S |
| **UX-11** | Baja | **Pestañas con desborde sin pista** en móvil (Tareas: «Carga…» cortada) | Degradado en el borde o menú «Más» | S |
| **UX-25** | Media | **Barra superior en móvil críptica**: «2 para hoy» y «Fuera de jornada · Fichar» se reducen a un sol con borde rojo, un punto y un libro, **sin texto**; no se ve si estás fichado ni qué significan (axe no lo detecta porque llevan `title`, pero un lector de pantalla y una persona nueva sí lo notan) | En móvil, el estado de fichaje como píldora con texto corto («En jornada 3 h 12») y el contador de «Hoy» con número; el libro (ayuda) pasa al menú | S |
| **UX-26** | Media | **Estados vacíos solo con texto, sin acción**: Correo sin cuenta («Ninguna cuenta tiene datos de SMTP configurados todavía») y Fichaje en el primer uso («rellena tu nombre y DNI/NIE» → lleva a otra pantalla); gran área en blanco y lenguaje técnico | Ilustración o icono + una frase en lenguaje llano + **botón principal** («Conectar mi correo», «Completar mis datos aquí» con el formulario en la misma tarjeta) | S |
| **UX-27** | Baja | **Centro de Ajustes en móvil**: ~25 tarjetas en una columna de 2.900 px y las etiquetas de valor se truncan («Toda…», «0 dis…», «0 cu…») | Agrupar en secciones plegables y dar a la etiqueta su propia línea | S |

### 12.3 Hallazgos del backoffice

| ID | Sev. | Hallazgo | Propuesta | Tamaño |
|---|:-:|---|---|:-:|
| **UX-12** | Media | **Ficha de tenant con cinco formularios independientes, cada uno con su «Guardar»** (nombre, límite de IA, datos fiscales, geolocalización…) y 2.376 px de alto en móvil; no queda claro qué está sin guardar | Guardado por sección con estado «sin guardar», o autoguardado con confirmación; secciones plegables | M |
| **UX-13** | Media | **Dashboard**: tarjetas repetidas (ARR aparece dos veces: «ARR» y «Facturación anual (ARR)»; MRR en dos sitios) y muchas a 0; «Salud de la cartera» sin explicar qué significa cada cubo | 4 indicadores clave + «lo que requiere acción» (pagos fallidos, webhooks, tenants en riesgo); definiciones en ayuda contextual | M |
| **UX-14** | Media | **La barra lateral recorta «Leads…» a 800 px de alto** sin indicio de scroll | Degradado/sombra de desplazamiento; secciones plegables | S |
| **UX-15** | Baja | **No está pensado para táctil**: 299 de 335 controles < 40 px también en móvil (herramienta interna, pero «ver como»/soporte se usa desde el móvil) | Mínimo 44 px en el modo estrecho | M |
| **UX-16** | Baja | Axe: contraste de los avatares (color arbitrario por tenant), barras de progreso sin nombre, `th` vacíos, tablas con scroll sin teclado, `aside` repetido | Elegir texto blanco/negro según el color, nombrar las barras | S |

### 12.4 Hallazgos de la app móvil (Flutter), por lectura del código

| ID | Sev. | Hallazgo (conteo en `mobile/lib`) | Propuesta (ola) |
|---|:-:|---|---|
| **UX-17** | Alta | **Errores en crudo**: 80 sitios enseñan `e.toString()` / `snapshot.error` al usuario («Error al cargar: DioException…») | `ApiException` tipada con mensaje y acción por categoría (0, M7) |
| **UX-18** | Alta | **La pantalla inicial es la de «proyectos» antiguos** (el botón «+» crea un proyecto) y no hay «Hoy»; la rejilla de 8 accesos de 3 columnas | «Hoy» + barra inferior (0, 1) |
| **UX-19** | Media | **Sin navegación persistente**: todo es `push`; para cambiar de sección hay que volver al inicio | `StatefulShellRoute` (0) |
| **UX-20** | Media | **28 indicadores de carga circulares y 0 esqueletos**; sin transiciones ni hápticos | Esqueletos y estados vacíos con acción (0) |
| **UX-21** | Media | **Sin «deshacer»** (0 `SnackBarAction`) tras borrar o completar; 16 diálogos de confirmación bloqueantes | *Toast* con deshacer en lugar de diálogos para lo reversible (0) |
| **UX-22** | Media | **Teclado y autocompletado**: `autofillHints`/`textInputAction` en 1 sitio; 6 `keyboardType` en toda la app (login sin gestor de contraseñas fluido, formularios sin «siguiente») | Revisión de formularios (0) |
| **UX-23** | Media | **~120 textos fijos en castellano** y 16 colores `Colors.*` directos que rompen el tema oscuro | i18n y tokens (0) |
| **UX-24** | Baja | Accesibilidad: 24 `tooltip`/`Semantics` y apenas pruebas de escala de texto | Guías de accesibilidad en pruebas de widget (§8.1) |

### 12.5 Cómo se enlaza con el resto del plan

- **UX-01, 04, 08, 10** son correcciones de servidor/plantillas de 1–3 días que mejoran **a la vez** la web y las vistas en el puente web de la app (los *WebView* heredan sus problemas); se proponen como **«Ola W»**, en paralelo a la Ola 0, ~1,5 pw.
- **UX-02, 03, 06, 07** se resuelven una vez para la web y se reutilizan como **diseño de referencia** de las pantallas móviles de la Ola 1 (Hoy y Tareas).
- **UX-17 a 23** quedan dentro de la Ola 0 (cliente v2, sistema de diseño, i18n).
- Añadir **axe-core al CI** (`tests/e2e`) y el **barrido de este documento como guion repetible** (`scripts/barrido_ux.py`) para medir mejora en cada ola.

### 12.6 Límites de este barrido

Una sola persona con rol de dirección y un despacho pequeño; módulos de negocio desactivados (comercial, contabilidad, abogados, inmobiliaria, jurídico) no se pudieron ver; el correo sin cuenta conectada; contraste calculado por axe (no se midió manualmente el modo oscuro); sin pruebas con lector de pantalla real ni con datos de volumen; no se validó producción.

---

## 13. Diseños de detalle que condicionan el resto

Son las decisiones que, si se toman tarde, obligan a rehacer pantallas. Se cierran en la Ola 0 (sobre papel) y se implementan en la Ola 1.

### 13.1 Sin conexión y sincronización

**Escritura (cola genérica, drift).** Cada acción pendiente guarda: `método`, `ruta`, `cuerpo`, `Idempotency-Key`, `despacho_id`, `entidad` y `clave_de_orden`, `creada_en`, `intentos`, `estado` (`pendiente` · `enviando` · `conflicto` · `rechazada`).

| Acción | Orden / conflicto | Regla |
|---|---|---|
| Fichaje | **Estricto**, en orden de pulsación; el servidor valida la secuencia por orden de llegada, no por hora (ya es así) | Error de negocio → se descarta con aviso («no se pudo registrar tu salida de las 14:02: ya estabas fuera»), nunca en silencio como hoy |
| Nota rápida / crear tarea | Sin conflicto; `cliente_uuid`/`Idempotency-Key` evita duplicados | Una tarea creada sin conexión recibe un id local `local:<uuid>` y las acciones que dependan de ella (comentar, adjuntar) esperan a que exista y se reescriben al id real |
| Cambiar estado / completar | Usa `version`; si el servidor responde `409 version_obsoleta` la acción pasa a `conflicto` y **se conserva la intención** | Hoja «Alguien la ha cambiado: ver cambios · aplicar igualmente · descartar» |
| Comentarios | Solo añaden: sin conflicto | FIFO por tarea |
| Acusar aviso, marcar leído, fijar nota | Idempotentes; gana la última | — |
| Adjuntos | Se envían los últimos y de uno en uno; no se reanudan (15 MB máx.) | Reintento completo con progreso visible |
| Edición larga de texto (nota, acta, correo) | Borrador local siempre; envío al volver la red | Para el correo: «programar» no está disponible sin red |

**Reglas de la cola:** reintento con espera exponencial (1 s → 5 min) solo ante red, `429`, `5xx`; los `4xx` de negocio no se reintentan, salvo `409`/`412` (conflicto); un `401` detiene la cola y pide volver a entrar sin perder nada; un `423` pausa lo que dependa del cifrado; **caducidad de 14 días** con aviso previo; **máximo 200 pendientes** (avisa al llegar a 150); FIFO dentro de una misma entidad, en paralelo entre entidades; se vacía al cerrar sesión **solo tras avisar** de lo pendiente.

**Lectura.** Estados de dato visibles: «actualizado hace 2 min», «sin conexión · datos del lunes 09:14». TTL por entidad (Hoy 2 min en línea; sin límite sin conexión); `/sync` por cursor para tareas, notas y proyectos (S-06 añade vencimientos y clientes); `ETag`/`304` en el resto; la caché se clava a `despacho_id`; techo de 50 MB con purga por antigüedad.

**Lo que nunca se guarda en el dispositivo:** contenido de correo o documentos de despachos con cifrado activo, adjuntos descargados (solo en la caché temporal del sistema, borrada al cerrar sesión), la frase de paso, contraseñas. Los metadatos (asunto, remitente) del correo cifrado **tampoco** si el nivel es *Estricto*.

### 13.2 Avisos y enlaces profundos

1. El servidor envía notificación + `data = {tipo, destino:{tipo,id}, despacho_id, notificacion_id}` (S-05).
2. **Con la app abierta** se muestra un aviso dentro de la app (no del sistema) y se suma a la bandeja.
3. **Al tocar** una notificación o un enlace universal: si no hay sesión → login → destino; si es de **otro despacho** → «Este aviso es de Inmobiliaria Costa. ¿Cambiar de despacho?» (sin confirmar si no hay cola pendiente); si el elemento ya no existe (`404`) → pantalla «Ya no está disponible» con botón a Hoy.
4. **Acciones en la propia notificación** (Android *actions* / iOS *categories*): «Lo llevo», «Aprobar», «Completar», «Archivar». Se ejecutan en segundo plano con el token y la cola (idempotentes); el resultado se confirma con una notificación breve y se refleja en la bandeja. Hace falta un manejador de segundo plano (`@pragma('vm:entry-point')`).
5. **Canales de Android** por familia (Tareas, Correo, Fiscal, Equipo, Resúmenes) para que cada persona silencie lo que quiera; las preferencias por tipo viajan al servidor (`/perfil`) para que **el servidor no envíe** lo desactivado (ahorra batería y cuota).

### 13.3 Despacho activo

`despachoActivo` es un *provider* persistido; todas las peticiones llevan `X-Despacho`. **Al cambiar:** se cancelan las peticiones en vuelo, se invalidan todos los providers, se carga la caché de ese despacho (o se vacía si no hay), se recarga `/auth/me` (módulos y permisos cambian) y se vuelve a Hoy. El push se registra **por dispositivo**, no por despacho: el servidor decide a qué personas y despachos avisa y el destino lleva `despacho_id`. Una persona con un solo despacho **no ve el selector**.

### 13.4 Cifrado por despacho desde el móvil (S-07)

1. La app pide un recurso cifrado → `423 despacho_bloqueado`.
2. Hoja «Documentos protegidos»: explica por qué y pide la **frase de paso**.
3. `POST /seguridad/cifrado/desbloquear` crea una **concesión ligada a este token** con caducidad corta (por defecto 12 h; la fija el despacho); la frase **no se guarda, no se registra y no sale del cuerpo de esa petición**.
4. La app reintenta lo que falló. La biometría del móvil solo desbloquea **la app**, nunca la frase (guardarla anularía el modelo de cifrado).
5. Cerrar sesión, «mis dispositivos → revocar» o perder el móvil revocan token y concesión (efecto inmediato, como ya hace el servidor al borrar la envoltura).
6. Revisión de seguridad específica antes de publicar: límite de intentos, no reutilizar la concesión entre dispositivos, auditoría de cada desbloqueo.

### 13.5 Despliegue por fases y retirada

| Canal | Quién | Cuándo |
|---|---|---|
| **Interno** (Firebase App Distribution / pruebas internas) | Tu equipo | Desde la semana 1 (cada cambio construido por el CI) |
| **Beta cerrada** (TestFlight / prueba cerrada de Play) | Equipo + 3–5 despachos piloto | Fin de la Ola 1 |
| **Producción por fases** (liberación gradual de Play; *phased release* de iOS) | 5 % → 25 % → 100 % en 7–10 días | Tras la Ola 2 (D1) |

**Banderas:** los módulos que ve cada despacho ya salen de `modulos` (S-02); las funciones nuevas en prueba se activan por despacho con `app.flags` en la misma respuesta, sin nueva versión. **Versión mínima:** `426` + pantalla «Actualiza» (S-10); se retira una versión solo si hay otra publicada que la sustituye. **Notas de versión** en los cuatro idiomas. **Soporte:** botón «Enviar diagnóstico» (versión, plataforma, `request_id` del último error, estado de la cola, **sin datos de clientes**) que abre un tiquet.

### 13.6 Costes recurrentes (estimación; comprobar precios vigentes)

| Concepto | Orden de magnitud |
|---|---|
| Apple Developer Program | ≈ 99 USD/año (con organización: D-U-N-S) |
| Google Play Console | ≈ 25 USD, pago único |
| Firebase (FCM, App Distribution) | 0 € para este volumen |
| GlitchTip (D5) | En el VPS actual (un contenedor más; ≈ 1 GB de RAM) |
| GitHub Actions | Revisar el cupo: los minutos de **macOS** (necesarios para iOS) cuentan ×10 en repositorios privados; limitar iOS a *tags* y a ramas de integración |
| Servidor | Sin coste nuevo previsto; vigilar el límite de 600 peticiones/min y el p95 tras el corte a PostgreSQL |

---

## Apéndice A — Operaciones de la API que el móvil no usa hoy (297 de 376)

Generado cruzando `GET /api/v1/openapi.json` con las llamadas de `api_client.dart`. Sirve para trazar cada operación a una ola.

<details><summary><b>fiscal</b> — 61 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /fiscal/auditoria` | Eventos de auditoría del despacho (solo de anexado), los más recientes primero. Solo la direcci |
| `GET /fiscal/avisos` | Avisos fiscales visibles para quien consulta. Filtros: `estado` (`abierta` por defecto, `acusad |
| `GET /fiscal/avisos/config` | Cómo avisa el despacho: `activo`, `dias_antes` (obligaciones), `dias_certificados`, `escalar_ho |
| `PUT /fiscal/avisos/config` | Solo la dirección. Lo que no envíes se mantiene. Ejemplo: `{"activo": true, "dias_antes": [7, 3 |
| `GET /fiscal/avisos/metricas` | Solo la dirección: sin atender, tiempo mediano hasta el acuse (con su muestra), escalados, fall |
| `POST /fiscal/avisos/{alerta_id}/acuse` | «Lo he visto, lo llevo». Cuerpo opcional: `{"nota": "Lo presento mañana"}`. La alerta deja de r |
| `GET /fiscal/clientes/por-referencia/{referencia}` | Cliente fiscal por referencia |
| `PUT /fiscal/clientes/por-referencia/{referencia}` | Crea o actualiza el cliente fiscal con esa `referencia_externa` (cuerpo como POST/PUT /fiscal/c |
| `GET /fiscal/clientes/{cliente_id}/accesos` | Registro de quién ha visto o tocado el expediente (auditoría y RGPD). Solo supervisores del des |
| `GET /fiscal/clientes/{cliente_id}/concesiones` | Listar concesiones api |
| `POST /fiscal/clientes/{cliente_id}/concesiones` | Comparte el cliente con otra oficina (`oficina_id`) o con una persona (`usuario_id`): `{"usuari |
| `GET /fiscal/clientes/{cliente_id}/documentos` | Expediente del cliente (metadatos, sin contenido) |
| `POST /fiscal/clientes/{cliente_id}/documentos` | Multipart: uno o varios `archivo` (hasta 10, 15 MB cada uno) y `categoria` opcional |
| `DELETE /fiscal/clientes/{cliente_id}/documentos/{documento_id}` | Eliminar documento cliente |
| `GET /fiscal/clientes/{cliente_id}/documentos/{documento_id}` | Descargar documento cliente |
| `PUT /fiscal/clientes/{cliente_id}/oficina` | Fija la oficina principal del cliente: `{"oficina_id": 3}` (`null` la quita). La dirección, o q |
| `PUT /fiscal/clientes/{cliente_id}/responsable` | Fija quién lleva el cliente sin traspaso (dirección o coordinación de su oficina). Cuerpo: `{"r |
| `GET /fiscal/clientes/{cliente_id}/resumen` | Vista ligera: modelos, vencimientos pendientes y los próximos |
| `GET /fiscal/clientes/{cliente_id}/tareas` | Las tareas del cliente que la persona puede ver (principal o vinculado), con contadores abierta |
| `DELETE /fiscal/concesiones/{concesion_id}` | Revocar concesion api |
| `GET /fiscal/expedientes` | Expedientes de control (campaña, obligación, renovación, requerimiento o incidencia) visibles p |
| `POST /fiscal/expedientes` | Abre un expediente. Cuerpo: `{"cliente_fiscal_id": 12, "tipo": "control_requerimiento", "titulo |
| `POST /fiscal/expedientes/lista/{punto_id}/hecho` | Marca un punto como hecho (por defecto) o lo reabre con `{"hecho": false}`. Nota opcional: `{"n |
| `GET /fiscal/expedientes/{expediente_id}` | Ficha completa: datos de control, lista de comprobación, documentos con sus versiones y los pun |
| `PUT /fiscal/expedientes/{expediente_id}` | Datos de control: `prioridad`, `fecha_objetivo` (`null` la quita), `revisor_id` (distinto del r |
| `POST /fiscal/expedientes/{expediente_id}/comentarios` | Añade un comentario a la cronología. No puede llevar contraseñas, claves ni números de tarjeta  |
| `POST /fiscal/expedientes/{expediente_id}/estado` | Cambia el estado: `abierto`, `en_curso`, `pendiente_cliente`, `pendiente_tercero`, `en_revision |
| `POST /fiscal/expedientes/{expediente_id}/lista` | Añade un punto a la lista de comprobación: `{"texto": "Llamar al cliente", "obligatorio": true, |
| `GET /fiscal/flujo` | Cómo trabaja el despacho las obligaciones: `flujo_estricto` (revisión y aprobación obligatorias |
| `PUT /fiscal/flujo` | Solo la dirección del despacho. Cuerpo: `{"flujo_estricto": true, "exigir_justificante": false} |
| `GET /fiscal/membresias` | Roles con alcance del despacho (coordinador, gestor, revisor fiscal, auditor). Solo la direcció |
| `POST /fiscal/membresias` | Da un rol con alcance: `{"usuario_id": 7, "rol": "gestor", "alcance": "oficina", "alcance_id":  |
| `DELETE /fiscal/membresias/{membresia_id}` | Revocar membresia api |
| `GET /fiscal/modelos` | Modelos fiscales por país (`pais`, por defecto el de tus clientes: ES) |
| `GET /fiscal/oficinas` | Oficinas del despacho con el número de clientes y de personas de cada una |
| `POST /fiscal/oficinas` | Solo la dirección. Cuerpo: `{"nombre": "Girona"}`. Al crear la primera oficina el despacho empi |
| `POST /fiscal/oficinas/{oficina_id}/archivar` | Solo la dirección; la oficina no puede tener clientes (reasígnalos antes) |
| `GET /fiscal/panel` | Qué mirar hoy y cómo va el despacho, en el ámbito de quien consulta: vencidas, próximas (7 días |
| `GET /fiscal/papelera` | Clientes y vencimientos borrados (recuperables) |
| `POST /fiscal/papelera/{tipo}/{item_id}/restaurar` | `tipo`: `cliente_fiscal` / `vencimiento_fiscal` |
| `GET /fiscal/recordatorios` | Cuándo y cómo se recuerda a los clientes sus vencimientos: días de aviso antes/después, aviso a |
| `PUT /fiscal/recordatorios` | Cuerpo: `dias_antes` (lista, 0-60), `dias_despues` (lista, 1-30), `avisar_equipo`, `asunto` y ` |
| `GET /fiscal/traspasos` | Traspasos de clientes visibles para quien consulta. Filtro opcional `estado`: `pendiente`, `ace |
| `POST /fiscal/traspasos` | Propone pasar un cliente a otra persona: `{"cliente_id": 12, "a_usuario_id": 5, "a_oficina_id": |
| `POST /fiscal/traspasos/{traspaso_id}/aceptar` | Quien lo recibe (o la dirección). Cambia el responsable y, si se indicó, la oficina; si el rece |
| `POST /fiscal/traspasos/{traspaso_id}/cancelar` | Quien lo propuso, el responsable actual o la dirección |
| `POST /fiscal/traspasos/{traspaso_id}/rechazar` | Quien lo recibe (o la dirección). Cuerpo: `{"motivo": "Estoy de baja esa semana"}` (obligatorio |
| `POST /fiscal/vencimientos` | Alta de un vencimiento a mano: `cliente_id`, `modelo`, `periodo`, `fecha_limite` (YYYY-MM-DD);  |
| `POST /fiscal/vencimientos/generar-masivo` | Genera los vencimientos del año (`anio`, por defecto el actual) de TODOS los clientes que tiene |
| `GET /fiscal/vencimientos/propuestas` | Vista previa, sin crear nada: `cliente_id` (obligatorio), `modelos` (separados por comas; por d |
| `GET /fiscal/vencimientos/{vencimiento_id}` | Detalle con el estado de lo que tiene dentro: documentos, mensajes sin leer del cliente y si ti |
| `PUT /fiscal/vencimientos/{vencimiento_id}/bloqueo` | Marca o quita el bloqueo (indicador, no fase): `{"bloqueada": true, "motivo": "Esperando los ex |
| `POST /fiscal/vencimientos/{vencimiento_id}/constancia` | (Re)genera la constancia de presentación en PDF (no sustituye al justificante oficial) |
| `GET /fiscal/vencimientos/{vencimiento_id}/documentos` | Lo que ha subido el cliente desde el portal (`origen: cliente`), la constancia (`constancia`) y |
| `GET /fiscal/vencimientos/{vencimiento_id}/documentos/{documento_id}` | Descargar documento vencimiento |
| `POST /fiscal/vencimientos/{vencimiento_id}/expediente` | Abre el expediente de una obligación, o devuelve el que ya hay abierto (200 con `nuevo: false`) |
| `GET /fiscal/vencimientos/{vencimiento_id}/flujo` | Fase de trabajo de la obligación, sus indicadores (`vencida`, `en_riesgo`, `bloqueada`, `presen |
| `POST /fiscal/vencimientos/{vencimiento_id}/justificante` | Multipart, campo `justificante`: imagen o PDF de hasta 8 MB. Visible para el cliente en su port |
| `GET /fiscal/vencimientos/{vencimiento_id}/mensajes` | Conversación con el cliente sobre este vencimiento (`autor`: `cliente` / `empleado`) |
| `POST /fiscal/vencimientos/{vencimiento_id}/mensajes` | Cuerpo: `{"texto": "..."}`. Se guarda como mensaje del equipo y se avisa al cliente por correo, |
| `POST /fiscal/vencimientos/{vencimiento_id}/transiciones` | Mueve la obligación de fase. Cuerpo: `{"destino": "presentada", "motivo": "...", "presentacion" |

</details>

<details><summary><b>tareas-outlook</b> — 49 operaciones</summary>

| Operación | Resumen |
|---|---|
| `DELETE /tareas-outlook/adjuntos/{adjunto_id}` | Eliminar adjunto de tarea |
| `GET /tareas-outlook/adjuntos/{adjunto_id}` | Descarga el archivo (`?ver=1` lo muestra en línea solo si es una imagen) |
| `GET /tareas-outlook/carga` | Plan de la semana por persona del despacho (horas estimadas por día frente a su capacidad). `se |
| `POST /tareas-outlook/cliente-comentarios/{comentario_id}/ocultar` | Moderación: oculta un comentario del cliente (no se borra: queda en la base y en la auditoría,  |
| `GET /tareas-outlook/informe` | Abiertas, vencidas y completadas por persona y por cliente, tasa en plazo, tiempo medio de cier |
| `POST /tareas-outlook/lote` | Una acción sobre varias tareas (máx. 200), cada una con sus permisos. Cuerpo: `{"ids": [..], "a |
| `GET /tareas-outlook/por-referencia/{referencia}` | Tarea por referencia |
| `PUT /tareas-outlook/por-referencia/{referencia}` | Crea o actualiza la tarea con esa `referencia_externa` (cuerpo como POST/PUT /tareas-outlook) |
| `DELETE /tareas-outlook/recordatorios/{recordatorio_id}` | Eliminar recordatorio |
| `POST /tareas-outlook/recordatorios/{recordatorio_id}/posponer` | Cuerpo: `{"opcion": "..."}` (las mismas que ofrece la web al posponer) |
| `GET /tareas-outlook/tablero` | Tareas pendientes y recientes agrupadas por estado (propias y asignadas) |
| `GET /tareas-outlook/vistas` | Vistas (filtros con nombre) propias y las compartidas por tu despacho |
| `POST /tareas-outlook/vistas` | Cuerpo: `{"nombre": "...", "filtros": {"estado": "en_progreso", ...}, "compartida": false}`. Mi |
| `DELETE /tareas-outlook/vistas/{vista_id}` | Eliminar vista |
| `GET /tareas-outlook/{tarea_id}` | Detalle de una tarea (propia o asignada) con su checklist |
| `GET /tareas-outlook/{tarea_id}/actividad` | Actividad de tarea |
| `GET /tareas-outlook/{tarea_id}/adjuntos` | Metadatos de los archivos adjuntos (sin el contenido) |
| `POST /tareas-outlook/{tarea_id}/adjuntos` | Multipart, uno o varios `adjunto`. PDF, imágenes, texto, CSV y documentos de Office o LibreOffi |
| `POST /tareas-outlook/{tarea_id}/asignar` | Cuerpo: `{"companero_id": 5}`; sin él (o `null`) la desasigna. Solo compañeros del mismo despac |
| `GET /tareas-outlook/{tarea_id}/checklist` | Listar checklist |
| `POST /tareas-outlook/{tarea_id}/checklist` | Agregar item checklist |
| `GET /tareas-outlook/{tarea_id}/clientes` | Clientes de la tarea |
| `PUT /tareas-outlook/{tarea_id}/clientes` | Cuerpo: `{"cliente_ids": [3, 8], "principal_id": 3, "version": 4}`. Sustituye los vinculados; l |
| `GET /tareas-outlook/{tarea_id}/comentarios` | Listar comentarios |
| `POST /tareas-outlook/{tarea_id}/comentarios` | Cuerpo: `{"texto": "..."}` (@menciones a compañeros del despacho las notifican). Lo puede hacer |
| `DELETE /tareas-outlook/{tarea_id}/comentarios/{comentario_id}` | Eliminar comentario |
| `GET /tareas-outlook/{tarea_id}/compartir` | Listar participantes |
| `POST /tareas-outlook/{tarea_id}/compartir` | Solo el dueño. Cuerpo: `{"usuario_id": n, "rol": "colabora"/"observa"}` (compañeros del mismo d |
| `DELETE /tareas-outlook/{tarea_id}/compartir/{usuario_id}` | El dueño quita a un participante; un participante puede salirse él mismo |
| `GET /tareas-outlook/{tarea_id}/conversaciones-cliente` | Una conversación por cliente vinculado que haya escrito o a quien se haya contestado. Los mensa |
| `POST /tareas-outlook/{tarea_id}/conversaciones-cliente` | Cuerpo: `{"cliente_fiscal_id": 12, "texto": "…"}` (hasta 1.000 caracteres). Contesta al cliente |
| `POST /tareas-outlook/{tarea_id}/cronometro/iniciar` | Empieza a contar tiempo sobre esta tarea (crea la tarea con duración enlazada). `proyecto_id` s |
| `GET /tareas-outlook/{tarea_id}/dependencias` | Tareas de las que depende esta y si está bloqueada (no se puede empezar ni completar hasta que  |
| `POST /tareas-outlook/{tarea_id}/dependencias` | Cuerpo: `{"depende_de_id": n}`. 409 si crearía un ciclo |
| `DELETE /tareas-outlook/{tarea_id}/dependencias/{depende_de_id}` | Quitar dependencia |
| `POST /tareas-outlook/{tarea_id}/estado` | Cuerpo: `{"estado": "no_iniciada/en_progreso/completada/esperando/aplazada"}`. 409 si la tarea  |
| `POST /tareas-outlook/{tarea_id}/mover` | Reasigna y/o cambia el día. Cuerpo: `{"persona_id": n/null, "fecha": "YYYY-MM-DD"/null}` (cualq |
| `GET /tareas-outlook/{tarea_id}/recordatorios` | Listar recordatorios |
| `POST /tareas-outlook/{tarea_id}/recordatorios` | Cuerpo: `{"avisar_en": "2026-11-01T09:00"}` o `{"atajo": "<clave relativa al vencimiento>"}`; ` |
| `POST /tareas-outlook/{tarea_id}/restaurar` | Saca una tarea de la papelera |
| `GET /tareas-outlook/{tarea_id}/revision` | La revisión pendiente (si la hay) y las últimas resueltas |
| `POST /tareas-outlook/{tarea_id}/revision` | Cuerpo: `{"revisor_id": 7, "nota": "Mira el cálculo del IVA"}` o, con varias personas, `{"revis |
| `POST /tareas-outlook/{tarea_id}/revision/cancelar` | Cancelar revision de la tarea |
| `POST /tareas-outlook/{tarea_id}/revision/resolver` | El voto de un revisor designado (cada uno vota una vez). Cuerpo: `{"decision": "aprobar" / "cam |
| `GET /tareas-outlook/{tarea_id}/subtareas` | Las subtareas (un nivel) con su progreso. La tarea padre no se puede completar mientras tenga s |
| `POST /tareas-outlook/{tarea_id}/subtareas` | Cuerpo: `{"asunto": "Pedir el certificado", "fecha_vencimiento": "2026-10-30", "asignada_a": 7} |
| `GET /tareas-outlook/{tarea_id}/tiempo` | Tiempo registrado en la tarea (tuyo y del equipo) |
| `POST /tareas-outlook/{tarea_id}/transiciones` | Cuerpo: `{"estado": "esperando", "motivo": "Falta el certificado", "version": 4}`. `esperando`  |
| `PUT /tareas-outlook/{tarea_id}/visible-cliente` | Cuerpo: `{"visible": true, "comentarios": false}`. Enseña (o deja de enseñar) la tarea al clien |

</details>

<details><summary><b>correo</b> — 25 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /correo/ajustes` | Obtener ajustes correo |
| `POST /correo/ajustes` | Guardar ajustes correo |
| `POST /correo/categorias` | Crear categoria correo |
| `DELETE /correo/categorias/{categoria_id}` | Eliminar categoria correo |
| `POST /correo/cuentas` | Crear cuenta correo |
| `DELETE /correo/cuentas/{cuenta_id}` | Eliminar cuenta correo |
| `POST /correo/cuentas/{cuenta_id}/sincronizar` | Sincronizar cuenta correo |
| `GET /correo/envios/{envio_id}` | Estado de un envío (`pendiente`, `enviado`, `cancelado`, `error`...) |
| `POST /correo/envios/{envio_id}/cancelar` | Cancela un envío programado que aún no ha salido (409 si ya se envió). Con `{"como_borrador": t |
| `POST /correo/firma` | Guardar firma correo |
| `POST /correo/mensajes/lote/{accion}` | Mismo patrón que las rutas de selección múltiple de rutas_correo.py: |
| `GET /correo/mensajes/{mensaje_id}/conversacion` | Conversacion correo |
| `POST /correo/mensajes/{mensaje_id}/nota` | Nota desde correo |
| `POST /correo/mensajes/{mensaje_id}/posponer` | Posponer mensaje correo |
| `POST /correo/mensajes/{mensaje_id}/tarea` | Crea una tarea vinculada al correo (y a su cliente fiscal). Cuerpo opcional: `fecha_vencimiento |
| `GET /correo/plantillas` | Listar plantillas |
| `POST /correo/plantillas` | Cuerpo: `nombre`, `asunto` (opcional), `cuerpo` (HTML, admite `{{variables}}`), `modelo` (opcio |
| `GET /correo/plantillas/variables` | Variables `{{...}}` que se pueden usar en una plantilla |
| `DELETE /correo/plantillas/{plantilla_id}` | Eliminar plantilla |
| `GET /correo/plantillas/{plantilla_id}` | La plantilla. Con `?cliente_fiscal_id=` (de tu despacho) devuelve además `renderizada`: asunto  |
| `PUT /correo/plantillas/{plantilla_id}` | Cambia cualquier subconjunto de `nombre`, `asunto`, `cuerpo` y `modelo` |
| `GET /correo/programados` | Listar programados |
| `DELETE /correo/programados/{envio_id}` | Cancela y descarta un envío programado (con sus adjuntos). Para conservarlo como borrador: `POS |
| `GET /correo/seguimientos` | Correos con «avísame si no responde». `todos=1` incluye los ya cerrados |
| `DELETE /correo/seguimientos/{seguimiento_id}` | Cancelar seguimiento |

</details>

<details><summary><b>comercial</b> — 20 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /comercial/embudo` | Lo abierto por etapa (número, importe y previsión ponderada), lo ganado y perdido en el periodo |
| `GET /comercial/etapas` | Las etapas del embudo del despacho, en orden, con su probabilidad de cierre. `ganada` y `perdid |
| `GET /comercial/oportunidades` | Oportunidades que puedes ver. Filtros: `estado` (`abierta` por defecto, `ganada`, `perdida` o ` |
| `POST /comercial/oportunidades` | Apunta una oportunidad. Cuerpo: `{"titulo": "...", "cliente_id": 12}` o, para un prospecto, `{" |
| `DELETE /comercial/oportunidades/{oportunidad_id}` | Manda la oportunidad a la papelera (no se borra de forma definitiva) |
| `GET /comercial/oportunidades/{oportunidad_id}` | Una oportunidad con su cronología (actividades y reuniones, de la más reciente a la más antigua |
| `PATCH /comercial/oportunidades/{oportunidad_id}` | Cambia los campos que se envíen: `titulo`, `contacto_nombre`, `contacto_email`, `contacto_telef |
| `POST /comercial/oportunidades/{oportunidad_id}/actividades` | Anota una actividad: `{"tipo": "llamada", "asunto": "Primera llamada", "texto": "...", "fecha": |
| `POST /comercial/oportunidades/{oportunidad_id}/convertir` | Convierte el prospecto en cliente: `{"gestion_fiscal": false, "nif": "B12345678", "ganar": true |
| `PUT /comercial/oportunidades/{oportunidad_id}/etapa` | Cambia de etapa: `{"etapa": "propuesta"}`. Pasarla a `perdida` exige `motivo`; `ganada` y `perd |
| `GET /comercial/reuniones` | Reuniones que puedes ver (una interna solo la ven quien la creó y la dirección). Filtros: `clie |
| `POST /comercial/reuniones` | Crea una reunión: `{"titulo": "Revisión trimestral", "plantilla": "cliente", "cliente_id": 12,  |
| `DELETE /comercial/reuniones/{reunion_id}` | Manda la reunión a la papelera |
| `GET /comercial/reuniones/{reunion_id}` | Una reunión con sus notas y su acta (`resumen`, `decisiones`, `tareas`, `proximos_pasos`). Nunc |
| `PATCH /comercial/reuniones/{reunion_id}` | Cambia los campos que se envíen: `titulo`, `fecha` (AAAA-MM-DD), `plantilla`, `participantes`,  |
| `POST /comercial/reuniones/{reunion_id}/acta` | Redacta el acta con la IA del propio usuario a partir de las notas y la transcripción. Sustituy |
| `PUT /comercial/reuniones/{reunion_id}/acta` | Guarda el acta escrita o corregida a mano: `{"resumen": "...", "decisiones": ["..."], "proximos |
| `POST /comercial/reuniones/{reunion_id}/tareas` | Crea tareas a partir del acta, solo las que se elijan: `{"tareas": [{"indice": 0, "responsable_ |
| `DELETE /comercial/reuniones/{reunion_id}/transcripcion` | Borra la transcripción guardada; las notas y el acta se quedan |
| `PUT /comercial/reuniones/{reunion_id}/transcripcion` | Guarda (o sustituye) la transcripción: `{"texto": "...", "aviso_grabacion": true}`. Exige `avis |

</details>

<details><summary><b>fichaje</b> — 15 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /fichaje/admin/exportar.csv` | Registro horario diario en CSV (`desde`, `hasta`, `usuario_id`; un administrador global añade ` |
| `GET /fichaje/admin/exportar.json` | Detalle crudo por evento con el hash de cada fila (interoperable, para Inspección de Trabajo) |
| `GET /fichaje/admin/exportar.pdf` | Fichaje admin pdf |
| `GET /fichaje/admin/resumen` | Horas trabajadas por trabajador del despacho en el periodo (`desde`, `hasta`: YYYY-MM-DD) y lo  |
| `GET /fichaje/admin/usuarios/{usuario_id}` | Datos laborales y fichajes de un trabajador (incluidas las correcciones, que son filas nuevas c |
| `POST /fichaje/admin/usuarios/{usuario_id}/corregir` | Corrección auditable de un olvido (p. ej. una salida sin fichar). Cuerpo: `tipo` (entrada/pausa |
| `GET /fichaje/admin/verificar-integridad` | Comprueba la cadena de hashes del registro horario y dice si está íntegra o en qué fila se romp |
| `GET /fichaje/bolsa-horas` | Tu bolsa de horas: lo trabajado frente a lo que tocaba según tu jornada (las ausencias aprobada |
| `POST /fichaje/bolsa-horas/ajustes` | Solo quien gestiona el fichaje. Cuerpo: `{"usuario_id": 7, "minutos": 90, "motivo": "Horas extr |
| `GET /fichaje/bolsa-horas/equipo` | Solo quien gestiona el fichaje: la bolsa de cada persona del despacho, de quien más debe a quie |
| `GET /fichaje/turnos` | Tus turnos entre `desde` y `hasta` (AAAA-MM-DD; por defecto, las próximas dos semanas) |
| `POST /fichaje/turnos/asignar` | Solo quien gestiona el fichaje. Cuerpo: `{"usuario_id": 7, "fecha": "2026-11-02", "turno_id": 3 |
| `GET /fichaje/turnos/cuadrante` | El cuadrante de todo el despacho entre `desde` y `hasta` (como mucho 62 días; por defecto, la s |
| `GET /fichaje/turnos/tipos` | Los turnos que existen en el despacho (nombre, horario, color y horas) |
| `POST /fichaje/turnos/tipos` | Solo quien gestiona el fichaje. Cuerpo: `{"nombre": "Mañana", "inicio": "08:00", "fin": "15:00" |

</details>

<details><summary><b>juridico</b> — 15 operaciones</summary>

| Operación | Resumen |
|---|---|
| `POST /juridico/adjuntos` | Sube un adjunto privado (multipart, campo `archivo`; opcionales `cliente_id` y `expediente_id`) |
| `DELETE /juridico/adjuntos/{adjunto_id}` | Borra el adjunto con su texto extraído e índice |
| `GET /juridico/adjuntos/{adjunto_id}/estado` | Estado de la extracción (`pendiente`, `lista`, `fallida`) y su retención. No devuelve el texto |
| `GET /juridico/admin/fuentes` | Diagnóstico de cada fuente: estado, habilitación, política vigente, cobertura, últimas ejecucio |
| `POST /juridico/buscar` | Busca en la biblioteca (identificadores exactos + texto + similitud si hay embeddings). Cuerpo: |
| `GET /juridico/colecciones` | Colecciones con su cobertura REAL para tu despacho: fuentes usables, documentos, fechas, última |
| `POST /juridico/conversaciones` | Crea una conversación privada: `{"cliente_id": 12, "expediente_id": 7, "titulo": "..."}` (todo  |
| `POST /juridico/conversaciones/{conversacion_id}/ejecuciones` | Lanza una consulta: `{"pregunta": "...", "colecciones": [...], "materia", "territorio", "fecha_ |
| `GET /juridico/documentos/{documento_id}` | Metadatos de un documento, sus versiones y sus relaciones documentadas. 404 si su fuente no est |
| `GET /juridico/documentos/{documento_id}/versiones/{version_id}` | Texto de una versión con sus localizadores. `fecha_juridica` (AAAA-MM-DD) limita los fragmentos |
| `GET /juridico/ejecuciones/{ejecucion_id}` | El resultado guardado de una consulta (solo para quien la lanzó) |
| `POST /juridico/ejecuciones/{ejecucion_id}/informe` | Guarda una instantánea de la consulta respondida en el expediente/cliente de su conversación: ` |
| `GET /juridico/informes` | Informes que puedes ver. Filtros: `expediente_id`, `cliente_id`. Paginación opcional `limit`/`o |
| `GET /juridico/informes/{informe_id}` | Un informe con su instantánea (consulta, respuesta y citas con su versión y fecha de captura) |
| `PATCH /juridico/informes/{informe_id}/revision` | Registra la revisión: `{"decision": "revisado" / "archivado", "nota": "..."}`. `revisado` solo  |

</details>

<details><summary><b>certificados</b> — 11 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /certificados` | Inventario de certificados del despacho (los más próximos a caducar primero). Filtros: `q` (tit |
| `POST /certificados` | Apunta un certificado **sin archivo**: `{"cliente_fiscal_id": 12, "tipo": "fnmt_persona_fisica" |
| `GET /certificados/avisos-cliente` | Cómo informa el despacho a sus clientes de la caducidad de su certificado: `avisar_cliente`, `m |
| `PUT /certificados/avisos-cliente` | Solo la dirección del despacho. Cuerpo: `{"avisar_cliente": true, "mostrar_en_portal": true, "d |
| `POST /certificados/importar` | Importa un certificado **público** (PEM o DER) en `contenido_base64`. Nunca se aceptan claves p |
| `GET /certificados/riesgos` | Obligaciones pendientes (próximos `dias`, 90 por defecto) cuya cobertura con certificado no est |
| `GET /certificados/{certificado_id}` | Obtener certificado api |
| `PUT /certificados/{certificado_id}` | Corrige un certificado (los campos que no envíes no cambian): `cliente_fiscal_id`, `custodio_id |
| `POST /certificados/{certificado_id}/comprobar` | Comprueba ahora la cadena de confianza y la revocación (OCSP y CRL) del certificado y anota los |
| `POST /certificados/{certificado_id}/renovaciones` | Abre la renovación del certificado (solo puede haber una en curso; 409 si ya la hay). Cuerpo op |
| `POST /certificados/{certificado_id}/renovado` | «Ya está renovado»: `{"nueva_caducidad": "2031-03-31", "emitido": "2027-03-31", "serie": "...", |

</details>

<details><summary><b>ia</b> — 11 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /ia/atajos` | Atajos de prompts: los 6 de serie (sin id) y los propios del usuario |
| `POST /ia/atajos` | Crear atajo ia |
| `DELETE /ia/atajos/{atajo_id}` | Eliminar atajo ia |
| `POST /ia/confirmar/stream` | Confirmar ia stream |
| `GET /ia/consumo` | Consultas de IA usadas este mes por el despacho y su tope (`ilimitado` si no hay). Sin despacho |
| `GET /ia/conversaciones` | Listar conversaciones ia |
| `POST /ia/conversaciones` | Crear conversacion ia |
| `DELETE /ia/conversaciones/{conversacion_id}` | Eliminar conversacion ia |
| `POST /ia/conversaciones/{conversacion_id}/activar` | Activar conversacion ia |
| `POST /ia/conversaciones/{conversacion_id}/renombrar` | Renombrar conversacion ia |
| `POST /ia/mensaje/stream` | Enviar mensaje ia stream |

</details>

<details><summary><b>notas</b> — 11 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /notas` | Notas propias, fijadas primero. Filtros: `proyecto_id`, `q`. Paginación `limit`/`offset` hecha  |
| `DELETE /notas/adjuntos/{adjunto_id}` | Eliminar adjunto nota |
| `GET /notas/adjuntos/{adjunto_id}` | Descarga el archivo (`?ver=1` lo muestra en línea si es una imagen) |
| `GET /notas/por-referencia/{referencia}` | Nota por referencia |
| `PUT /notas/por-referencia/{referencia}` | Crea o actualiza la nota con esa `referencia_externa` (cuerpo como POST/PUT /notas). 201 si la  |
| `DELETE /notas/{nota_id}` | Eliminar nota |
| `GET /notas/{nota_id}` | Obtener nota |
| `PUT /notas/{nota_id}` | Editar nota |
| `GET /notas/{nota_id}/adjuntos` | Adjuntos de la nota (metadatos, sin el contenido) |
| `POST /notas/{nota_id}/adjuntos` | Multipart, uno o varios `adjunto`. Imágenes (png, jpeg, gif, webp), PDF, texto y CSV; 5 MB cada |
| `POST /notas/{nota_id}/fijar` | Cuerpo: `{"fijada": true/false}` (por defecto true) |

</details>

<details><summary><b>webhooks</b> — 10 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /webhooks` | Listar webhooks |
| `POST /webhooks` | Cuerpo: `{"url": "https://...", "eventos": ["tarea.completada", ...]}`. La URL debe ser https y |
| `GET /webhooks/catalogo-eventos` | Eventos a los que se puede suscribir un webhook |
| `POST /webhooks/entregas/{cola_id}/reintentar` | Reintentar entrega |
| `DELETE /webhooks/{webhook_id}` | Borrar webhook |
| `GET /webhooks/{webhook_id}` | Obtener webhook |
| `PUT /webhooks/{webhook_id}` | Cambia `url`, `eventos` y/o `activo` (cualquier subconjunto) |
| `GET /webhooks/{webhook_id}/entregas` | Últimos intentos de entrega y lo que sigue en cola (pendiente/fallido) de este webhook |
| `POST /webhooks/{webhook_id}/probar` | Encola un evento `ping` firmado como cualquier otro; mira el resultado en `/entregas` |
| `POST /webhooks/{webhook_id}/rotar-secreto` | Secreto nuevo; el anterior deja de valer al instante. Se devuelve solo esta vez |

</details>

<details><summary><b>contabilidad</b> — 9 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /contabilidad/clientes/{cliente_fiscal_id}/comprobar` | Pre-chequeo de lo que saldría ahora en el SUENLACE.DAT del cliente (`trimestre` opcional): erro |
| `POST /contabilidad/clientes/{cliente_fiscal_id}/exportar` | Genera el SUENLACE.DAT con las facturas revisadas del cliente (`trimestre` opcional), las marca |
| `GET /contabilidad/facturas` | Facturas anotadas (las más recientes primero). Filtros: `cliente_fiscal_id`, `estado` (pendient |
| `POST /contabilidad/facturas` | Anota una factura (queda pendiente de revisar). Cuerpo: `cliente_fiscal_id`, `tipo`, `fecha`, ` |
| `GET /contabilidad/facturas/{factura_id}` | Una factura entera: datos, líneas de IVA (importes en euros), subcuenta del tercero, lo que imp |
| `POST /contabilidad/facturas/{factura_id}/estado` | Cambia el estado: `revisada` (solo si no tiene problemas), `pendiente` (reabrir) o `descartada` |
| `POST /contabilidad/facturas/{factura_id}/leer` | Lee con IA el archivo de la factura y rellena sus datos (queda pendiente de revisar). Usa el mo |
| `GET /contabilidad/lotes/{lote_id}/fichero` | El SUENLACE.DAT de un lote ya generado, como descarga (registros de 512 bytes) |
| `GET /contabilidad/resumen` | Qué espera, cliente por cliente: por revisar, por leer con IA y revisadas listas para exportar |

</details>

<details><summary><b>abogados</b> — 6 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /abogados/conflictos` | Conflicto de intereses de una persona o empresa (`nombre`, `nif` opcional). `como=cliente` (por |
| `GET /abogados/expedientes/{expediente_id}/mensajes` | Mensajes que el cliente ha escrito desde su enlace público y las respuestas del despacho (sin m |
| `POST /abogados/expedientes/{expediente_id}/mensajes` | Contesta al cliente en el hilo de su enlace público (`texto`, hasta 2000 caracteres). 400 si no |
| `GET /abogados/expedientes/{expediente_id}/partes` | Partes del asunto (cliente, contraparte, letrados, procuradores…) con rol y NIF |
| `GET /abogados/expedientes/{expediente_id}/provision` | La cuenta del cliente en un asunto: provisiones, suplidos, honorarios, devoluciones y saldo (en |
| `GET /abogados/vistas` | Señalamientos previstos (vistas, juicios, comparecencias) en los próximos `dias` días (30 por d |

</details>

<details><summary><b>inmobiliaria</b> — 6 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /inmobiliaria/demandas/{demanda_id}/cruces` | Inmuebles en comercialización que encajan con la demanda, de 0 a 100 puntos (`minimo`, 50 por d |
| `GET /inmobiliaria/inmuebles` | Inmuebles de la agencia (cada uno es una operación de venta o alquiler). Filtros: `operacion` ( |
| `GET /inmobiliaria/inmuebles/{expediente_id}/mensajes` | Mensajes que el propietario ha escrito desde su enlace público y las respuestas de la agencia ( |
| `POST /inmobiliaria/inmuebles/{expediente_id}/mensajes` | Contesta al propietario en el hilo de su enlace público (`texto`, hasta 2000 caracteres). 400 s |
| `GET /inmobiliaria/resumen` | Panel de la agencia: inmuebles activos por fase, visitas de hoy y de la semana, ofertas abierta |
| `GET /inmobiliaria/visitas` | Visitas previstas desde hoy en los próximos `dias` días (7 por defecto, máximo 60) |

</details>

<details><summary><b>tareas</b> — 6 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /tareas` | Tareas con cronómetro. Filtros: `desde`, `hasta` (YYYY-MM-DD), `proyecto_id`; paginación `limit |
| `DELETE /tareas/{tarea_id}` | Eliminar tarea |
| `PUT /tareas/{tarea_id}` | Editar tarea |
| `POST /tareas/{tarea_id}/finalizar` | Finalizar tarea |
| `POST /tareas/{tarea_id}/pausar` | Pausar tarea |
| `POST /tareas/{tarea_id}/reanudar` | Reanudar tarea |

</details>

<details><summary><b>tareas-plantillas</b> — 5 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /tareas-plantillas` | Listar plantillas tareas |
| `POST /tareas-plantillas` | Cuerpo: `{"nombre", "descripcion", "items": ["tarea 1", ...] (o texto con una por línea), "comp |
| `DELETE /tareas-plantillas/{plantilla_id}` | Eliminar plantilla tareas |
| `PUT /tareas-plantillas/{plantilla_id}` | Editar plantilla tareas |
| `POST /tareas-plantillas/{plantilla_id}/aplicar` | Crea las tareas de la plantilla. Cuerpo: `fecha_inicio`, `proyecto_id` / `nuevo_proyecto`, `cli |

</details>

<details><summary><b>proyectos</b> — 4 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /proyectos` | Listar proyectos |
| `POST /proyectos` | Crear proyecto |
| `DELETE /proyectos/{proyecto_id}` | Lo manda a la papelera (recuperable), no lo borra |
| `PUT /proyectos/{proyecto_id}` | Renombrar proyecto |

</details>

<details><summary><b>tareas-recurrentes</b> — 4 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /tareas-recurrentes` | Listar recurrentes |
| `POST /tareas-recurrentes` | Cuerpo: `asunto`, `periodicidad` (diaria/laborables/semanal/mensual/trimestral/anual), `dia` (s |
| `DELETE /tareas-recurrentes/{regla_id}` | Eliminar recurrente |
| `POST /tareas-recurrentes/{regla_id}/alternar` | Alternar recurrente |

</details>

<details><summary><b>tareas-reglas-vencimiento</b> — 4 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /tareas-reglas-vencimiento` | Reglas «una tarea por cada vencimiento del modelo X» |
| `POST /tareas-reglas-vencimiento` | Cuerpo: `modelo` (p. ej. 303), `asunto` (admite {cliente}, {modelo}, {periodo}), `crear_dias_an |
| `DELETE /tareas-reglas-vencimiento/{regla_id}` | Eliminar regla vencimiento |
| `POST /tareas-reglas-vencimiento/{regla_id}/alternar` | Alternar regla vencimiento |

</details>

<details><summary><b>tokens</b> — 4 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /tokens` | Tokens de acceso del usuario (nunca el token ni su hash) |
| `POST /tokens` | Crea otro token (p. ej. para una integración). Cuerpo: `nombre`; `permisos` (`completo` / `solo |
| `DELETE /tokens/{token_id}` | Revocar token |
| `GET /tokens/{token_id}/uso` | Llamadas y errores por día de uno de tus tokens (`dias`, 1-90, por defecto 30) |

</details>

<details><summary><b>notificaciones</b> — 3 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /notificaciones` | Últimas notificaciones (`limit`, máx. 100, por defecto 30) y cuántas hay sin leer (cabecera y c |
| `POST /notificaciones/leidas` | Marcar notificaciones leidas |
| `DELETE /notificaciones/{notificacion_id}` | Eliminar notificacion |

</details>

<details><summary><b>papelera</b> — 3 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /papelera` | Papelera |
| `POST /papelera/{tipo}/{item_id}/eliminar-definitivamente` | Eliminar definitivamente de papelera |
| `POST /papelera/{tipo}/{item_id}/restaurar` | Restaurar de papelera |

</details>

<details><summary><b>categorias</b> — 2 operaciones</summary>

| Operación | Resumen |
|---|---|
| `POST /categorias/reordenar` | Reordenar categorias |
| `POST /categorias/{categoria_id}/favorito` | Alternar favorito categoria |

</details>

<details><summary><b>checklist</b> — 2 operaciones</summary>

| Operación | Resumen |
|---|---|
| `DELETE /checklist/{item_id}` | Eliminar item checklist |
| `POST /checklist/{item_id}/alternar` | Alternar item checklist |

</details>

<details><summary><b>comunicados</b> — 2 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /comunicados` | Avisos vigentes publicados por Guilda para este usuario (los críticos no se pueden cerrar) |
| `POST /comunicados/{comunicado_id}/cerrar` | Cerrar comunicado |

</details>

<details><summary><b>documentos</b> — 2 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /documentos` | Metadatos (sin contenido) de los documentos de un cliente (`cliente_id`) o de un expediente (`e |
| `GET /documentos/{documento_id}/contenido` | Descarga el contenido. 423 `despacho_bloqueado` si está cifrado y no hay clave disponible para  |

</details>

<details><summary><b>buscar</b> — 1 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /buscar` | Búsqueda en notas, tareas y correo. Parámetros: `q` (obligatorio), `limit` (1-20, por defecto 8 |

</details>

<details><summary><b>companeros</b> — 1 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /companeros` | Compañeros del despacho a quienes se puede asignar una tarea |

</details>

<details><summary><b>export</b> — 1 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /export` | Exportar |

</details>

<details><summary><b>health</b> — 1 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /health` | Comprobación de vida para monitores externos (Uptime Kuma, balanceadores). Sin token y sin dato |

</details>

<details><summary><b>mi-dia</b> — 1 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /mi-dia` | «Mi día»: tareas vencidas, de hoy, en curso y asignadas |

</details>

<details><summary><b>openapi.json</b> — 1 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /openapi.json` | Documento OpenAPI 3.0 de toda esta API, generado por introspección |

</details>

<details><summary><b>sync</b> — 1 operaciones</summary>

| Operación | Resumen |
|---|---|
| `GET /sync` | Cambios desde un cursor, para no volver a descargarlo todo |

</details>


---

## Apéndice B — Avisos del servidor → pantalla de destino (S-05)

El servidor emite 37 avisos de 30+ tipos con `datos` irregulares (a veces solo `tipo`). La app necesita un destino único por aviso:

| `tipo` (servidor) | Origen | Destino en la app | Acción en la notificación |
|---|---|---|---|
| `tarea_asignada`, `tarea_compartida`, `tarea_comentario`, `tarea_desbloqueada`, `tarea_recordatorio`, `revision_tarea` | tareas | Tarea `{tarea_id}` | Completar · Posponer (recordatorio) · Aprobar (revisión) |
| `portal_comentario_tarea` | portal del cliente | Tarea → conversaciones con el cliente | Responder |
| `correo_nuevo`, `correo_equipo`, `correo_sin_respuesta`, `correo_envio_fallido` | correo | Mensaje `{mensaje_id}` / cuenta `{cuenta_id}` | Marcar leído · Archivar · Responder |
| `vencimiento_fiscal`, `obligacion` | fiscal | Obligación `{vencimiento_id}` | Abrir |
| `aviso_fiscal` | avisos | Aviso `{alerta_id}` | **Lo llevo** (acuse) |
| `traspaso` | traspasos | Traspasos | Aceptar · Rechazar |
| `expediente`, `mencion` | control fiscal | Expediente `{expediente_id}` | Abrir |
| `ausencia` | ausencias | Ausencias (equipo) | **Aprobar** · Rechazar |
| `turno` | turnos | Mis turnos | Abrir |
| `bolsa_horas` | bolsa de horas | Mi bolsa | Abrir |
| `fichaje_salida_olvidada` | fichaje | Fichaje (corregir) | Corregir |
| `certificado` | certificados | Certificado `{certificado_id}` | Abrir |
| `portal_mensaje_nuevo`, `portal_sin_documentos` | portal / abogados / inmobiliaria / contabilidad | Hilo del enlace o factura `{id}` | Responder |
| `resumen_diario`, `resumen_ia_semanal` | resúmenes | Hoy / IA | Abrir |
| `automatizacion`, `automatizacion_fallo` | automatizaciones | Aviso (el detalle abre el puente web) | Abrir |
| `tiquet_asignado` | tiquets | Tiquet `{tiquet_id}` | Abrir |
| `nota_compartida` | notas | Nota `{nota_id}` | Abrir |
| `antivirus` | portal | Aviso | — |
| `prueba` | ajustes | (se ignora) | — |

---

## Apéndice C — Cómo reproducir las mediciones de este documento

Los tres scripts de la prueba están en `docs/anexos-app-movil/` (son prototipos, no código de producción; se promueven al repositorio en la Ola 0 como `scripts/generar_sdk_dart.py`, `scripts/capturar_fixtures_movil.py` y `scripts/barrido_ux.py`).

```bash
# 1. Contrato vivo, en copia aislada (no toca datos reales): un script que haga
#    app.test_client().get("/api/v1/openapi.json") y lo guarde
scripts/probar.sh --ejecutar <script>

# 2. Capturas reales con datos sintéticos (siembra un despacho, crea un token y recorre los GET)
scripts/probar.sh --ejecutar docs/anexos-app-movil/capturar_respuestas_api_prototipo.py

# 3. Generador del SDK Dart y su análisis (Dart 3.12)
python3 docs/anexos-app-movil/generar_sdk_dart_prototipo.py openapi.json lib/modelos.dart lib/operaciones.dart
dart analyze && dart test            # con un test que lea cada captura con su modelo

# 4. Estado de la app móvil (en una copia en un directorio temporal)
flutter pub get && flutter analyze && flutter test && flutter pub outdated --no-dev-dependencies

# 5. Barrido de UX/UI (Playwright + axe-core, en una copia aislada con las fixtures de tests/e2e)
GUILDA_E2E=1 UX_SALIDA=<carpeta> UX_AXE=<axe.min.js> pytest tests/e2e/barrido_ux_prototipo.py
```
