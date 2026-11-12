# App móvil v3: el asistente de IA como centro de la aplicación

> Plan, no código. Nada de esto está hecho todavía. Parte de lo medido el 2026-11-12 sobre `mobile/` (Flutter 3.44, Riverpod, go_router, ~33 000 líneas, 118 ficheros en `lib/`) y sobre los cambios recientes del servidor.

## 1. Punto de partida

**Lo que hay**
- Barra inferior de 5 pestañas: Inicio · Tareas · Correo · Fichaje · Más (`lib/nucleo/shell.dart`). Tableta: raíl lateral.
- El asistente es **una pantalla que se empuja encima** (`abrirAsistente` → `IaChatScreen`, 1 081 líneas). Se llega por una barra en Hoy, una chispa en las barras de cada pantalla o desde «Más». Tiene streaming, voz, pasos, fuentes, confirmación con vista previa, conversaciones anteriores y panel lateral en tableta.
- Diseño: tokens generados desde la web (`tokens.g.dart`), tema construido a mano (`theme/app_theme.dart`), Manrope, acento lima, violeta propio para la IA (`diseno/asistente.dart`). Es correcto y accesible, pero **sobrio**: Material estándar, tarjetas planas, filos finos, sin profundidad ni movimiento propio.
- Hay tests de diseño, accesibilidad, i18n (es/ca/en/fr), cola sin conexión y asistente (`mobile/test/`).

**Lo que ha cambiado en el servidor y la app no aprovecha**
- Bandeja de **propuestas** del asistente (`/api/v1/propuestas`: listar, aprobar, rechazar; eventos `propuesta.creada/resuelta`). Está en el SDK generado, pero ninguna pantalla la usa.
- **Política de acceso** del despacho (segundo factor o passkey con fecha límite; pasada la fecha, la app móvil también se cierra). Hay que comprobar qué recibe la app y mostrar el aviso con los días que quedan.
- Avisos de **tope mensual de IA** (80 % / 100 %) y de fallo sostenido del proveedor.
- «**Preguntar a tus datos**» con fuentes citadas, atajos de IA, lectura de facturas por capas y herramientas nuevas del asistente (`ia_herramientas.py`, 1 843 líneas).

**El problema de fondo**: el asistente puede hacer casi todo lo que hace la app, pero en el móvil está a dos toques y en una pantalla aparte. El móvil sigue organizado por módulos, no por intención.

## 2. Idea de producto

> **No abres un módulo: le dices a Guilda lo que necesitas, y la app te lleva, te lo enseña o lo hace.**

1. **El asistente siempre está a mano.** Un botón central destacado en la barra y una barra de entrada («Pídeme algo…») que sube desde cualquier pantalla con el contexto de lo que estás viendo.
2. **Coordina, no solo responde.** Las respuestas llevan **tarjetas vivas** (tarea, correo, fichaje, vencimiento, ausencia, propuesta) con sus botones: completar, responder, fichar, aprobar. Tocar una tarjeta abre la pantalla nativa correspondiente (`resolverDestino` ya existe).
3. **Hoy es la portada del asistente**: un resumen del día que el asistente redacta («Tienes 3 vencimientos esta semana; el 303 de Ferrer vence el jueves»), con «Lo siguiente», las propuestas pendientes y accesos rápidos.
4. **Lo que cambia datos se confirma.** Se mantiene la confirmación con vista previa, el modo seguro y el aviso de cautela fiscal que ya existen. Nada se hace a escondidas.
5. **Las pantallas de módulo siguen ahí** (Tareas, Correo, Fichaje…) para trabajar con calma o sin IA. El asistente las acelera, no las sustituye.

## 3. Navegación nueva

```
┌────────────────────────────────────────┐
│   (contenido de la pestaña)            │
│                                        │
│  ┌──────────────────────────────────┐  │  ← barra del asistente (flota sobre
│  │ ✦  Pídeme algo…            🎤   │  │    la barra, con el contexto)
│  └──────────────────────────────────┘  │
│   Hoy   Tareas    ( ✦ )    Correo  Más │  ← barra flotante tipo píldora
└────────────────────────────────────────┘
```

- **Pestañas**: Hoy · Tareas · **✦ Asistente (centro, grande)** · Correo · Más.
- **Fichaje** sale de la barra: pasa a una **tarjeta fija en Hoy** (entrada/salida de un toque, con el cronómetro) y a un comando del asistente («ficha mi entrada»). Sigue accesible desde «Más».
- Tocar ✦ abre el **chat a pantalla completa** con animación de expansión. Tocar la barra flotante lo abre **como hoja** (altura media → completa), conservando la pantalla de debajo.
- **Tableta**: raíl lateral con ✦ arriba y el panel del asistente permanente, como ahora pero con el diseño nuevo.
- Los avisos y enlaces profundos (`Destino`) se mantienen tal cual.

*Decisión que necesito de ti:* ver §8.

## 4. Diseño visual («muy moderno»)

Principio: **oscuro primero, con profundidad y movimiento con sentido**, sin perder el lima de marca ni el violeta propio del asistente.

| Área | Hoy | v3 |
|---|---|---|
| Superficies | Planas, filo de 1 px | Capas con elevación suave, **vidrio esmerilado** (barra, hojas, cabeceras) y degradados muy sutiles |
| Identidad de la IA | Insignia violeta fija | **Aura** viva (degradado violeta→lima que respira) tras el botón central y el saludo; **orbe** al escuchar y al pensar |
| Radios | 10–22 | 16 / 24 / 32, píldoras en controles |
| Cabeceras | AppBar estándar | **Títulos grandes que se pliegan** al hacer scroll, con fondo de vidrio |
| Hoy | Lista por secciones | **Mosaico (bento)**: resumen de IA, siguiente cosa, fichaje, contadores, propuestas |
| Chat | Burbujas | Mensajes sin burbuja para la IA (texto limpio a ancho de lectura), burbuja solo para ti; **tarjetas** de acción; texto que aparece con cursor suave; pasos plegables |
| Movimiento | Material por defecto | Muelles cortos (≤ 300 ms), transiciones compartidas entre tarjeta y pantalla, **háptica** en acciones, esqueletos con brillo |
| Tipografía | Manrope 11–28 | Misma familia; escala con más contraste (títulos 32/28, cifras grandes tabulares en fichaje y contadores) |
| Iconos | Material | Mismo set, trazo de 1.75 y tamaños coherentes |

Reglas que no se rompen: contraste AA en claro y oscuro (hay `accesibilidad_test.dart`), «reducir movimiento» apaga aura/muelles, objetivos táctiles ≥ 48 dp, textos largos en ca/fr sin desbordes, ancho máximo de lectura.

Los **tokens** de color siguen saliendo de `app/static/style.css` (`scripts/exportar_tokens_dart.py`). Lo nuevo (vidrio, aura, elevaciones, curvas) va en un fichero propio de la app (`diseno/tokens_v3.dart`) y se documenta; si la web quiere adoptarlo, se sube después a la hoja de estilos.

## 5. Asistente como coordinador

**Capacidades nuevas en la app** (el servidor casi todo lo tiene ya):

1. **Tarjetas de resultado** dentro del chat. Se construyen a partir de los eventos del stream y de las herramientas que usó el asistente (`IaEventoStream`): tarea, correo, nota, fichaje, vencimiento, ausencia, cliente. Cada una con 1–2 acciones y toque para abrir la ficha.
2. **Bandeja de propuestas** (`/propuestas`): tarjetas «El asistente propone…» con *Aprobar* / *Rechazar* (silencia 30 días), en Hoy y como filtro en el chat. Insignia en ✦ con el número pendiente. Push de `propuesta.creada` hacia esa bandeja.
3. **Contexto automático**: la barra flotante envía qué pantalla/elemento estás viendo (`contextoIa`, ya existe); se muestra como una píldora quitable («Hablando de: Tarea #7»).
4. **Comandos de un toque** por pestaña (atajos de IA del servidor + sugerencias fijas): «Resume mi día», «Qué vence esta semana», «Responde a este correo», «Ficha mi entrada».
5. **Voz de primera clase**: mantener pulsado el micro desde la barra flotante, dictado con orbe, lectura en voz alta (ya hay STT/TTS en `ia_chat_screen.dart`; se extraen a un servicio).
6. **Presupuesto y estado de la IA**: aviso discreto si el despacho está cerca del tope o el proveedor falla, con lenguaje claro.
7. **Sin conexión**: el asistente se desactiva con un mensaje honesto y las acciones de siempre siguen en la cola.

**Refactor necesario**: `ia_chat_screen.dart` (1 081 líneas, estado en un `StatefulWidget`) se parte en un controlador Riverpod (`funciones/asistente/asistente_controlador.dart`), servicio de voz, lista de mensajes, barra de entrada y tarjetas. Es el cambio con más riesgo; se hace antes de pintar nada nuevo y con los tests de `asistente_test.dart` como red.

## 6. Plan por fases

Cada fase termina con tests en verde, capturas antes/después y un commit propio. La app no se despliega sola: la compilación del APK/IPA y la publicación en tiendas las haces tú.

| Fase | Contenido | Entregable |
|---|---|---|
| **0. Base** | `flutter analyze` + `flutter test` de partida; comprobar que el SDK Dart está al día con la API (regenerar si no); capturas «antes» con `flutter build web` + Chrome; verificar qué recibe la app con la política de acceso | Línea base medida |
| **1. Sistema de diseño v3** | `tokens_v3`, tema (botones, campos, hojas, chips, barras), primitivas: `Vidrio`, `Aura`, `Orbe`, `TarjetaBento`, `CabeceraGrande`, esqueleto con brillo, háptica y curvas | Galería de componentes + `diseno_test` ampliado |
| **2. Cáscara y navegación** | Nueva barra flotante con ✦ central, barra del asistente persistente con contexto, hoja del asistente, raíl de tableta, fichaje fuera de la barra | `shell.dart` nuevo, rutas y enlaces profundos intactos |
| **3. Asistente v3** | Controlador Riverpod, chat rediseñado, tarjetas de resultado, voz extraída, píldora de contexto, comandos | Chat nuevo con los tests actuales pasando |
| **4. Hoy v3** | Mosaico: resumen de IA, siguiente cosa, tarjeta de fichaje, contadores, propuestas, comunicados, certificados | Portada nueva |
| **5. Propuestas y novedades del servidor** | Bandeja de propuestas, insignia, push; aviso de política de acceso; aviso de tope de IA | Funciones nuevas con tests |
| **6. Resto de pantallas** | Tareas, Correo, Fichaje, Más y Ajustes heredan el tema nuevo; retoques puntuales (cabeceras grandes, tarjetas, vacíos) | Coherencia visual |
| **7. Calidad y cierre** | es/ca/en/fr en todo lo nuevo, a11y, reducir movimiento, textos largos, tableta, modo oscuro/claro y los 6 acentos; notas de versión | Informe y capturas finales |

**Orden de riesgo**: 0 → 1 → 3 (refactor sin cambiar la cara) → 2 → 4 → 5 → 6 → 7. Así lo difícil se hace con la app aún conocida y la cara nueva se pone encima de una base probada.

## 7. Qué puedo verificar aquí y qué no

- **Sí**: `flutter analyze`, `flutter test` (incluidas pruebas de widgets), compilación web y capturas en Chrome a anchos de móvil y tableta, contraste y desbordes, textos en los 4 idiomas.
- **No**: probar en un móvil real (háptica, voz, biometría, push, rendimiento de vidrio en gama baja) ni compilar el APK/IPA sin SDK de Android/Xcode. Te dejaré una lista de comprobación corta para ese paso. El desenfoque de vidrio se pone con un modo de reserva (superficie opaca) para móviles lentos.

## 8. Decisiones que necesito de ti

1. **Navegación** (mi recomendación: A)
   - **A.** Botón ✦ **central** en la barra + barra de entrada flotante. El asistente es un destino y está siempre a un toque.
   - **B.** El **asistente es la portada** (se abre la app y estás en el chat, con Hoy debajo). Más radical, menos módulos a la vista.
2. **Fichaje**: salir de la barra a una tarjeta fija en Hoy (recomendado) o conservarlo como pestaña.
3. **Aura violeta→lima** viva tras el botón central: sí (recomendado) o solo violeta fijo.
4. **Alcance**: ¿todo el plan, o primero las fases 0–4 y revisamos con capturas antes de seguir?

## 9. Riesgos

- Refactor del chat (fase 3): se mitiga con los tests actuales y haciéndolo antes del cambio visual.
- Tamaño del cambio: 118 ficheros de `lib/`; por eso el tema nuevo actúa por herencia y solo se tocan pantallas en la fase 6.
- Rendimiento del vidrio y del aura en móviles de gama baja: modo de reserva y «reducir movimiento».
- Idiomas: cada texto nuevo se escribe en los cuatro `.arb` en el mismo cambio, no después.
- Sin dispositivo real aquí: la última comprobación es tuya.

## 10. Fase 0 — resultado (2026-11-12)

Decisiones aprobadas: botón ✦ central en la barra + barra de entrada flotante; fichaje fuera de la barra (tarjeta fija en Hoy); aura violeta→lima viva; ejecución por fases con revisión de capturas tras la 4.

**Línea base medida**
- `flutter analyze`: 5 avisos de estilo (`info`), ningún error ni aviso serio (`fila_tarea.dart` ×2, `tareas_lista_controlador.dart`, 2 imports innecesarios en tests).
- `flutter test`: **382 pruebas, todas en verde** (≈ 1 min).
- SDK Dart: **al día** con la API (`generar_sdk_dart.py --comprobar`). Las propuestas ya están en el SDK; ninguna pantalla las usa.
- Capturas «antes»: 47 PNG en `docs/ux-app-movil-v3/antes/` (móvil claro/oscuro y tableta), con las fuentes y el tema reales. Se regeneran con `CAPTURAS=<carpeta> flutter test <ficheros de test>`.
- Política de acceso: con el despacho exigiendo segundo factor o passkey y fecha vencida, la API responde **403 con código `politica_acceso`** (`rutas_api.py:316`) y el texto «Tu despacho exige verificación en dos pasos o una passkey. Actívala desde la web… y vuelve a entrar». La app hoy lo trata como un error de «prohibido» genérico: hay que darle pantalla propia (fase 5). El aviso previo con los días que quedan lo da la web, no la API móvil: a decidir en la fase 5 si hace falta un campo en `GET /hoy` o en el perfil.

**Notas de entorno (para quien repita esto)**
- Flutter se ejecuta como `guilda` con `su - guilda` (con `su guilda` a secas hereda `HOME=/root` y falla al leer `.pub-cache`).
- `flutter pub get` reescribe 5 ficheros generados de escritorio (`mobile/linux|macos|windows/...`); no son del móvil, se revierten con `git restore` sobre esas rutas.
- Esta máquina no tiene emulador: las capturas salen de los tests de widgets, no de un dispositivo.

## 11. Fase 1 — resultado (2026-11-12)

**Hecho: el sistema de diseño v3, sin tocar ninguna pantalla.** Todo importable con `import 'diseno/v3/v3.dart'`.

| Pieza | Fichero | Qué es |
|---|---|---|
| Tokens y paleta | `diseno/v3/tokens_v3.dart` | `V3` (radios 16/24/32, tiempos ≤ 420 ms, curvas, muelle), `Haptica` (seleccion / toque / hecho / aviso), `PaletaV3` derivada del tema vigente (sigue al claro/oscuro y al acento) y `suaveSobre(fondo)` para el texto secundario sobre fondos teñidos |
| Vidrio | `diseno/v3/vidrio.dart` | Superficie esmerilada. Cae a opaca con alto contraste, con `V3.vidrioActivo = false` (Ajustes lo usará para móviles lentos) o con `opaco: true` |
| Aura y orbe | `diseno/v3/aura.dart` | `Aura` (manchas violeta/acento a la deriva) y `OrbeIa` (reposo / escuchando / pensando) |
| Mosaico y táctil | `diseno/v3/bento.dart` | `TarjetaBento` (neutro, acento, IA) y `Pulsable` (se hunde un 3 % y vibra suave; conserva onda, foco y semántica de botón) |
| Cabecera y carga | `diseno/v3/cabecera_brillo.dart` | `CabeceraGrande` (título que se pliega, con vidrio), `Brillo` y `BloqueEsqueleto` |

**Tema (`theme/app_theme.dart`)**: botones en píldora de 52 dp, tarjetas a 24, campos a 16, hojas y diálogos a 28, barra superior sin tinte al hacer scroll, snackbars flotantes, transiciones de página modernas en Android (`FadeForwards`) y capas de superficie (`surfaceContainer*`). Las constantes de `BrandColors` no cambian.

**Calidad**
- `flutter test`: **392 pruebas en verde** (382 + 10 nuevas en `test/diseno_v3_test.dart`), incluidas las de accesibilidad de todas las pantallas en claro y oscuro con el tema nuevo.
- `flutter analyze`: los mismos 5 avisos de siempre, ninguno en código nuevo.
- Las 10 pruebas nuevas cubren: paleta por tema y acento; **contraste AA ≥ 4,5:1 de texto y texto suave sobre cada tono de tarjeta, en claro y oscuro y con los 8 acentos**; botones en píldora ≥ 48 dp; vidrio con sus tres reservas opacas; «reducir movimiento» (aura, orbe y brillo no programan fotogramas); toque, semántica de botón y hundimiento de `Pulsable`; plegado de la cabecera.
- Hallazgo del contraste: el gris secundario (4,83:1 sobre blanco) pierde margen con cualquier velo de color. Se redujo el velo del acento en claro y se añadió `suaveSobre` para el texto secundario dentro de tarjetas teñidas.

**Capturas** (`docs/ux-app-movil-v3/fase1/`): `galeria_v3_claro/oscuro.png` (todo lo nuevo en una pantalla) y 7 pantallas reales con el tema nuevo. Cambian poco: Hoy, Tareas, etc. usan sus propios contenedores y no heredan las tarjetas del tema; se rediseñan en las fases 4 y 6.

**Pendiente de esta fase, a propósito**: el conmutador de vidrio en Ajustes y el modo de reserva para gama baja se enchufan en la fase 7 (la pieza ya lo respeta). `suaveSobre` se aplicará dentro de `TarjetaBento` en la fase 4 cuando haya texto secundario real dentro.

## 12. Fase 3 (primera mitad) — refactor del chat, sin cambiar su cara (2026-11-12)

**Hecho: `ia_chat_screen.dart` pasa de 1 081 líneas con todo mezclado a una pantalla de 288 y cinco piezas con una sola responsabilidad.** Es el cambio de más riesgo del plan, hecho antes de pintar nada nuevo.

| Pieza | Líneas | Responsabilidad |
|---|---|---|
| `screens/ia_chat_screen.dart` | 288 | Solo la piel: barra, menú, selector de archivos, portapapeles y diálogos. Mismo constructor que antes (`api`, `locale`, `consultaInicial`, `contexto`, `contextoIa`, `alCerrar`): ninguno de sus 9 usos cambia |
| `funciones/asistente/asistente_controlador.dart` | 421 | La conversación: historial, envío, streaming, confirmación, parar, vaciar, archivos y contexto. Sin `BuildContext` |
| `funciones/asistente/servicio_voz.dart` | 205 | La voz: cola de frases, troceo por frases completas y bucle del modo «Live». Sin chat |
| `funciones/asistente/motor_voz.dart` | 127 | La frontera con los plugins nativos (`speech_to_text`, `flutter_tts`) como interfaz; incluye el arreglo del audio de iOS tal cual |
| `funciones/asistente/chat_cuerpo.dart` | 303 | Lo que se ve de la conversación: inicio, mensajes y burbujas |
| `funciones/asistente/chat_entrada.dart` | 138 | Campo de escritura, adjunto pendiente y atajos |

**Desviación del plan, a propósito.** El plan decía «controlador Riverpod». El controlador es un `ChangeNotifier` que recibe `api` y los textos por constructor. Motivo: los 9 sitios que abren el chat (y ~25 pruebas) le pasan `api` directamente, sin `serviciosProvider`; un `Notifier` global habría obligado a reescribirlos todos en esta misma fase. En la fase 2, cuando la barra flotante y el chat tengan que compartir conversación, se expone con un `Provider` y `IaChatScreen` aceptará un controlador ya creado; el controlador no cambia.

**Cómo se comprobó que no cambia nada visible**
1. Antes de tocar nada, 14 pruebas de caracterización (`test/asistente_flujo_test.dart`) del turno completo: texto en directo, mensaje definitivo, pasos de herramientas, confirmar/rechazar, acción pendiente recuperada del historial, parar, error del servidor, caída de red, vaciar. **Pasaron contra el código antiguo y contra el nuevo, sin cambiar una línea.**
2. Capturas del chat (conversación e inicio, claro y oscuro) del commit anterior frente al refactor: **idénticas byte a byte**.
3. 35 pruebas de unidad nuevas (`test/asistente_controlador_test.dart`) que antes eran imposibles: contexto del primer mensaje, adjuntos, ciclo de vida de los eventos, historial roto, y la voz entera con un motor falso (cola, troceo, silencio, «Live» y su bucle de re-escucha).
4. `flutter test`: **441 en verde** (392 + 14 + 35). `analyze`: los mismos 5 avisos de siempre.

**Fallo que ya existía y que el refactor deja arreglado.** Si se paraba una respuesta y se enviaba otra enseguida, el bucle del turno anterior seguía vivo (la marca «detenido» se reiniciaba con el turno nuevo y solo se comprobaba al llegar otro evento): la cola de la respuesta vieja se mezclaba con la nueva y, al salir, cerraba el turno nuevo. Ahora cada turno lleva su número y uno parado no puede tocar al siguiente. Hay una prueba que **falla si se quita el arreglo** (comprobado por mutación).

**Qué falta de la fase 3** (la mitad visible):
- Rediseño del chat con la v3 (mensajes del asistente sin burbuja, burbuja solo para ti, texto con cursor suave, pasos plegables, orbe al pensar/escuchar).
- Tarjetas de resultado dentro del chat (tarea, correo, nota, fichaje, vencimiento) con sus botones y toque para abrir la ficha.
- Píldora de contexto quitable con el estilo nuevo y comandos de un toque por pantalla.

## 13. Fase 3 (segunda mitad) — la cara nueva del chat (2026-11-12)

**Hecho.** Capturas en `docs/ux-app-movil-v3/fase3/` (conversación e inicio, claro y oscuro).

| Cambio | Dónde |
|---|---|
| **Tarjetas de resultado**: cada tarea, nota, correo o vencimiento que cita el asistente sale como tarjeta con su icono y tipo; un toque abre la ficha real (mismo camino que antes, `destinoDeFuenteIa`). Se anuncia como un botón «Tareas: título». Sustituyen al desplegable «N fuentes» | `funciones/asistente/chat_v3.dart` (`TarjetasResultado`) |
| **Texto en directo con cursor suave**: un punto que respira al final de la respuesta que llega; quieto con «reducir movimiento» | `TextoVivo` |
| **Pasos plegables**: mientras responde, el orbe pensando y «N pasos» que se despliegan con un toque (antes iban siempre abiertos) | `PasosPlegables` |
| **Inicio**: orbe grande centrado y sugerencias como tarjetas sueltas (antes, una lista en una sola caja) | `chat_cuerpo.dart` |
| **Burbuja tuya** con esquinas más suaves; **píldora de contexto** con chispa y filo violeta | `chat_cuerpo.dart`, `ia_chat_screen.dart` |

**Sin backend.** Las tarjetas salen de las fuentes que ya manda el servidor (`tipo`, `titulo`, `url`). Con eso cada tarjeta tiene una sola acción: abrir. Los botones propios por tarjeta (completar una tarea, archivar un correo) necesitan que el servidor mande datos estructurados del resultado; queda anotado para la fase 5.

**Textos nuevos** (es, ca, en, fr): `iaPasosN`, `iaTipoVencimiento`. El resto reutiliza claves existentes.

**Pruebas:** 448 en verde (7 nuevas en `test/chat_v3_test.dart`: tarjetas, etiqueta vacía, semántica, pasos plegados, cursor con y sin movimiento). Se actualizaron 3 pruebas que fijaban el diseño anterior (pasos siempre visibles, fuentes plegadas, texto en directo como `Text` plano). Efecto colateral: el orbe del inicio anima sin parar y `pumpAndSettle` no termina; `appDePantalla` ahora corre con «reducir movimiento» y dos pruebas de tableta lo activan a mano. `analyze`: los mismos 5 avisos.

**Se quitó** código muerto: `FuentesPlegables` y `PasosRespuesta`.

**Pendiente de la fase 3:** los comandos de un toque ya existen por tipo de contexto (correo, tarea, nota); extenderlos por pantalla (Fichaje, Más) llega con la barra nueva de la fase 2.

## 14. Fase 2 — cáscara y navegación (2026-11-12)

**Hecho.** Capturas en `docs/ux-app-movil-v3/fase2/` (claro y oscuro).

| Cambio | Dónde |
|---|---|
| **Barra inferior v3**: píldora de vidrio con Hoy · Tareas · **✦** · Correo · Más. Etiqueta siempre visible, pestaña activa con una cápsula de acento, vibración suave al cambiar | `nucleo/barra_v3.dart` (`BarraNavegacion`) |
| **Botón ✦ central**: círculo violeta con el aura viva detrás; abre el chat a pantalla completa con el contexto de la pestaña | `_BotonAsistente` |
| **«✦ Pídeme algo…»**: barra que flota sobre la de navegación; un toque sube el chat **como hoja** (90 % de alto, la pantalla sigue debajo) con el teclado ya listo | `BarraPideme`, `abrirHojaAsistente`, `IaChatScreen(enfocar:)` |
| **Fichaje sale de la barra**: sigue accesible desde «Más» (primera fila); su enlace profundo `/fichaje` y los avisos que llevan allí no cambian. La tarjeta fija en Hoy llega en la fase 4 | `shell.dart` |
| **Tableta**: el raíl conserva las cinco pestañas y gana el ✦ arriba | `shell.dart` |

**Contexto automático.** Desde Tareas y Correo la hoja y el ✦ abren el chat con «Contexto: Tareas / Correo» (píldora quitable de la fase 3). Hoy y Más no llevan contexto.

**Desviaciones respecto al plan, a propósito**
- **Sin `Provider` del controlador.** El plan lo pedía para compartir la conversación entre la barra y el chat. No hace falta: la conversación la guarda el servidor y cada apertura la recarga, así que la hoja y la pantalla completa ya enseñan lo mismo. El controlador no cambia. Coste: una recarga del historial al abrir.
- **Hoja de altura fija (90 %)**, no «media → completa» arrastrable: el chat tiene su propia lista desplazable y anidarla en una hoja arrastrable pelea con el scroll. Se cierra arrastrando hacia abajo o con su aspa.
- **La barra «Pídeme algo…» abre la hoja, no es un campo editable** en la propia barra: así el teclado no empuja la barra de navegación ni tapa el contenido. El micro de la barra aún no dicta (llega con la voz de primera clase, fase 7).
- **Sin vidrio con desenfoque real tras la barra**: la barra va en `bottomNavigationBar` (no solapa el contenido, no hace falta reservar espacio). Si en la fase 7 se prefiere que el contenido pase por debajo, es un cambio local.

**Accesibilidad.** Un test de pautas (toques de 48 dp, etiquetas, contraste) sobre la barra y otro de semántica (seleccionada, botón, acción de tocar). Este último cazó un fallo real: al excluir la semántica interna los botones perdían la acción de tocar para un lector de pantalla; arreglado con `onTap` en el nodo.

**Pruebas:** 454 en verde (13 sobre la barra, 6 de ellas nuevas). Se actualizaron las de «Barra inferior» (cuatro destinos más el ✦, Fichaje por «Más») y dos ayudas de test corren con «reducir movimiento» porque el aura anima sin parar. `analyze`: los mismos 5 avisos.

**Texto nuevo** (es, ca, en, fr): `iaPideme`.

## 15. Fase 4 — Hoy como mosaico (2026-11-12)

**Hecho.** Capturas en `docs/ux-app-movil-v3/fase4/` (`hoy_claro.png`, `hoy_oscuro.png`). **Aquí toca revisar el diseño juntos** (acordado en §8).

| Bloque | Qué es |
|---|---|
| **Cabecera grande** | «Hoy» (y el despacho debajo si hay varios) que se pliega al desplazar; búsqueda y campana a la derecha |
| **Tarjeta del asistente** | Orbe + «Pídele un resumen de tu día». Un toque sube el chat como hoja con la consulta ya enviada. No repite números: están en los contadores |
| **Lo siguiente** | Lo más urgente (vencido, si no de hoy) con su botón «Abrir». Tarjeta con tinte de acento |
| **Tarjeta de fichaje** | Tu estado (dentro / en pausa / fuera), desde cuándo y **el botón que toca ahora**: Entrada, o Pausa + Salida, o Fin de pausa + Salida. Fichar es un toque, sin salir de Hoy. Sin red se encola igual que en la pantalla de Fichaje y el estado se adelanta. Tocar la tarjeta abre el Fichaje completo. Si faltan los datos de fichaje se explica y se quitan los botones |
| **Contadores** | Pendientes y urgentes, como dos fichas |
| **Secciones** | Las de siempre (tareas, correo, plazos, vencimientos…), debajo; en tableta, en dos columnas, y el mosaico también en dos |
| **Carga** | Esqueleto del mosaico con su brillo, en vez de la lista gris |

**Cambios de fondo**
- `funciones/hoy/hoy_fichaje.dart`: `FichajeHoyControlador` (estado + `marcar`) y `TarjetaFichajeHoy`. Si no se puede leer el estado (sin red, sin permiso) la tarjeta se apaga y Hoy sigue funcionando.
- La **ubicación opcional** de fichar se extrajo a `ubicacionOpcionalFichaje()` (`fichaje_acciones.dart`): la usan la pantalla de Fichaje y la tarjeta, con el mismo criterio (solo si el despacho la activa; nunca bloquea fichar).
- Se quitó la barra del asistente que Hoy tenía bajo la lista: la nueva «Pídeme algo…» de la barra inferior la sustituye.

**Lo que NO entra, a propósito**
- **El resumen no está redactado por la IA.** El plan lo imaginaba («Tienes 3 vencimientos…»). Hacerlo bien pide un endpoint que lo genere y lo cachee en el servidor (coste y latencia al abrir la app); no existe. La tarjeta pide el resumen al asistente al tocarla, que es lo que ya hacía. Si se quiere, es una tarea de backend aparte.
- **Propuestas, comunicados y certificados en el mosaico.** Los comunicados ya salen en su banner sobre el mosaico. Las propuestas llegan con su bandeja en la fase 5 (tarjeta + pantalla a la vez); los certificados ya salen como sección de la bandeja.

**Pruebas:** 459 en verde (6 nuevas sobre Hoy: estado y fichar la entrada de un toque, en pausa, sin datos, tarjeta del asistente, pautas de accesibilidad). Las de Hoy y las capturas usan un `FichajeHoyFalso` y «reducir movimiento» (el orbe anima sin parar). `analyze`: los mismos 5 avisos.

## 16. Fase 5 — propuestas y novedades del servidor (2026-11-12)

**Hecho.** Capturas en `docs/ux-app-movil-v3/fase5/`. Todo se apoya en endpoints que el servidor ya tenía; no se ha tocado el backend.

| Novedad | Cómo se ve |
|---|---|
| **Bandeja de propuestas** (`GET /propuestas`, `POST …/aprobar` y `…/rechazar`) | Pantalla «El asistente propone»: una tarjeta por propuesta con su porqué, etiqueta «Urgente» escrita (no solo color) y *Rechazar* / *Aprobar*. Las urgentes primero (lo ordena el servidor). Aprobar crea la tarea al momento; rechazar avisa de que no vuelve en 30 días |
| **Confirmación en lo que sale fuera** | Las propuestas de tipo `peticion_portal`, `mensaje_portal` y `cuenta_tercero` actúan hacia un cliente: antes de aprobar pide confirmar. Solo `tarea` se aprueba directo |
| **Dónde se ve que hay propuestas** | Insignia con el número en el ✦ de la barra; tarjeta «N propuestas del asistente» en Hoy y en el inicio del chat; fila en ninguna parte más (no hace falta). Sin propuestas, nada de eso sale |
| **Política de acceso** (403 `politica_acceso` al entrar) | Antes se leía como «No tienes permiso» (la categoría genérica de 403). Ahora dice lo que pasa y qué hacer («Tu despacho exige verificación en dos pasos o una passkey. Actívala desde la web…») y la pantalla de acceso ofrece **Abrir la web de Guilda** |
| **Tope de IA** (`GET /ia/consumo`) | Aviso discreto encima del campo del chat: al 80 % «Tu despacho lleva 85 de 100 consultas de IA este mes» y, agotado, «…ha agotado las consultas de IA de este mes. Se renuevan el día 1». Sin tope, con la IA desactivada o lejos del límite no sale nada. Se relee al acabar cada turno |

**Cambios de fondo:** `funciones/propuestas/` (controlador + pantalla + tarjeta), `ApiException.politicaAcceso`, `ConsumoIa` (modelo y `ApiClient.obtenerConsumoIa`), `AvisoConsumoIa`, el destino `propuesta` → bandeja (para avisos futuros). Textos nuevos en es, ca, en y fr.

**No entra, a propósito**
- **Push de `propuesta.creada`.** Ese evento del servidor (`app/eventos.py`) es para flujos externos (chat, webhooks), no para el push del móvil; no existe aviso push de propuestas. Hasta que el servidor lo emita, la insignia se actualiza al abrir la app y al tirar para refrescar. Si se quiere el push, es una tarea de backend.
- **Estado del proveedor de IA** («el proveedor falla»): el servidor no expone un estado aparte. Si falla un turno, ya se enseña el error del turno.
- **Aprobar sin red:** no se encola (a diferencia de fichar): ejecuta algo en el servidor y hace falta ver su resultado.

**Pruebas:** 476 en verde (19 nuevas en `test/propuestas_test.dart`: modelo, bandeja, aprobar y rechazar, confirmación, conflicto 409, accesibilidad, tarjeta, tope de IA con cifras, política de acceso). Un test de accesibilidad del chat ahora simula las preferencias (antes pasaba por casualidad de tiempos). `analyze`: los mismos 5 avisos.

## 17. Fase 6 — resto de pantallas (2026-11-12)

**Qué se encontró.** Con el tema de la fase 1 y las tarjetas/botones heredados, Tareas, Correo, Fichaje, Ajustes y Ausencias ya se veían coherentes (capturas «antes» en `docs/ux-app-movil-v3/fase6/antes/`). No hacía falta rediseñarlas una a una; se hicieron los retoques que sí daban coherencia, y no más:

| Retoque | Dónde |
|---|---|
| **Fichaje**: la tarjeta de estado pasa a `TarjetaBento` y los botones a píldora (como los de Hoy), con vibración al fichar | `screens/fichaje_screen.dart` |
| **Más**: cabecera grande como Hoy y una fila «El asistente propone» con su cuenta cuando hay propuestas | `nucleo/shell.dart` |
| **Vacíos y errores de toda la app**: el icono va en un círculo suave en vez de suelto | `diseno/componentes.dart` (`EstadoVacio`, que usa `EstadoError`) |
| **Tareas sin barras apiladas**: Tareas ya tiene su «Nueva tarea…» abajo; ahí no se pinta «Pídeme algo…» (el ✦ sigue). En el resto de pestañas sí | `nucleo/shell.dart` |

**Decidido no hacer**
- **Cabeceras grandes plegables en Tareas, Correo y Fichaje.** Tareas lleva pestañas y filtros pegados a la cabecera y Correo, una búsqueda; una cabecera de 132 dp les quitaría altura útil en móviles pequeños a cambio de poco. Hoy y Más (listas cortas, sin controles arriba) sí la llevan.
- **Rehacer las filas de tarea y de correo.** Ya usan las pastillas de estado y las tarjetas del tema; cambiarlas sería gusto, no coherencia.

**Pruebas:** 481 en verde (5 nuevas o ampliadas: «Pídeme algo…» no se apila en Tareas, «Más» con y sin propuestas). Las capturas de «Más» y de las pantallas que viven dentro de la barra funcionan ahora también en modo captura (el aura animaba sin parar y `pumpAndSettle` no terminaba). `analyze`: los mismos 5 avisos.

## 18. Fase 7 — calidad y cierre (2026-11-12)

**Resultado: la v3 está terminada en código.** Capturas en `docs/ux-app-movil-v3/fase7/`; notas de versión en `docs/notas-version-app-movil-v3.md`.

**Lo que se comprobó, con tests (`test/calidad_v3_test.dart`)**

| Comprobación | Resultado |
|---|---|
| **Traducciones**: ca, en y fr tienen exactamente las claves de es, ninguna vacía, y los mismos marcadores (`{n}`, `{hora}`…) en cada texto | Pasa, todas las claves (también las anteriores a la v3) |
| **Textos largos y letra al doble** en catalán, francés e inglés, en un móvil de 320 dp de ancho: barra con insignia, Hoy completo, bandeja de propuestas, tarjetas de resultado, pasos y avisos de tope | **Encontró 5 desbordes reales**, ya corregidos (ver abajo). Ahora pasa |
| **Los ocho acentos × claro y oscuro**: contraste AA y toques de 48 dp en la barra y en la bandeja | Pasa los 32 casos |
| **Efecto cristal**: por defecto activo, el ajuste se guarda y se recupera, y apagado la barra pierde su desenfoque | Pasa |

**Desbordes corregidos** (solo aparecían con letra muy grande): la cabecera plegada de Hoy y Más (su título ahora limita la escala a ×1,2; el resto sigue la del sistema), la fila «Lo siguiente» de Hoy, la cabecera de cada tarjeta de propuesta, y el contador de pasos del asistente. Ahora esas filas se parten en líneas (`Wrap`) o recortan con puntos suspensivos.

**Ajuste nuevo:** *Ajustes → Apariencia → Efecto cristal* (`ThemeService.cambiarVidrio`, guardado en el móvil). Es la salida para móviles modestos: apagado, las barras son opacas y no hay desenfoque.

**Lo que no se hizo, a propósito**
- **Detección automática de móvil lento.** Sin datos reales de dispositivos sería adivinar; el interruptor lo resuelve y se puede decidir con tu uso.
- **Medir fotogramas en un dispositivo real.** Este entorno no tiene móvil ni emulador; el barrido de rendimiento (aura y orbe animados, desenfoque) es lo primero que debe probar quien compile el APK/IPA.
- **Compilar y publicar.** El APK/IPA y la tienda siguen siendo tuyos.

**Pendiente conocido, menor:** la captura de «tableta_notas» (solo con `CAPTURAS=…`) no termina porque el panel del chat anima sin parar y su test usa `pumpAndSettle`; los tests normales no se ven afectados.

**Estado final de la v3:** fases 0–7 hechas; 548 tests; `analyze` con los 5 avisos anteriores a este trabajo; SDK Dart al día con la API.
