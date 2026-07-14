# Guilda Work

<p align="center">
  <img src="assets/repo-logo.png" alt="Guilda Work logo" width="420">
</p>

Registro diario de actividad organizado en **menús** (carriles independientes,
ej. "Lueira", "Guilda"): entras en un menú y ahí anotas notas, eventos
instantáneos y tareas con duración, viendo su propio registro cronológico.
Pensado para exportar los datos y que una IA (Claude, ChatGPT, un modelo
local...) los use para generar informes.

## Estado actual: Fase 1 + Fase 2 + Fase 3 completas

- Menús (internamente siguen siendo la tabla `categorias`), cada uno con su
  propia página y su propio registro cronológico.
- Crear, renombrar/cambiar color y eliminar un menú (al eliminar se borra en
  cascada todo lo registrado dentro: notas, eventos y tareas).
- Notas rápidas dentro de un menú.
- Eventos instantáneos (un clic, un único timestamp).
- Tareas con duración: iniciar / finalizar / **pausar / reanudar**, duración
  calculada automáticamente descontando el tiempo en pausa, cronómetro en
  vivo mientras está en curso (congelado mientras está pausada).
- Histórico global filtrable por fecha y menú.
- Exportación a JSON, CSV y resumen en Markdown desde el histórico.
- **Informe con IA local**: desde el histórico, envía los datos filtrados a
  un modelo corriendo en Ollama (`localhost:11434`) o LM Studio
  (`localhost:1234`) con una instrucción personalizable, y muestra el
  resultado en la propia página. Nada sale de tu máquina. Si el servicio no
  está encendido, falla con un mensaje claro en pocos segundos (timeout
  corto) sin bloquear el resto de la app.
- **Preguntar a mis datos** (modo pregunta libre, también en Histórico):
  chat con memoria contra el mismo Ollama/LM Studio, para preguntas sueltas
  o de seguimiento ("¿qué hice ayer en Lueira?", "¿y cuánto tiempo en
  total?") en vez de un informe de una sola vez. La conversación vive en el
  navegador (el servidor no la guarda); en cada pregunta se reenvían los
  datos filtrados más el historial visible de la charla.
- **Estadísticas**: tiempo total dedicado por menú (más nº de tareas,
  eventos y notas) y desglose de tiempo por día y menú, filtrable por fecha.
- **Empaquetado `.exe`**: compilado y verificado con PyInstaller (ver más
  abajo); funciona standalone sin Python instalado.
- **Botón "Cerrar programa"** (abajo del todo en el menú lateral): termina el
  servidor y el proceso por completo con un solo clic, para no dejar procesos
  colgados. Ver la sección "Cerrar la app sin dejar procesos zombis" más abajo.
- **Ventana nativa de Windows** en vez de abrir el navegador: usa WebView2
  (el motor de renderizado de Windows 11, basado en Chromium, vía la
  librería `pywebview`) para mostrar la app en una ventana propia sin barra
  de navegador. El `.exe` se compila en modo `--windowed`, así que tampoco
  aparece ninguna consola.
- **Logo propio** en la ventana, la pestaña/favicon y el icono del `.exe`.
- **Editar y eliminar** notas, eventos y tareas individualmente (✏ junto a
  cada entrada del registro y del histórico), incluyendo **ajustar
  manualmente el inicio y el fin** de una tarea con duración (por si te
  olvidas de darle a "Iniciar" a tiempo) — la duración se recalcula sola.
- **Buscador de texto** en el registro de cada menú y en el histórico global.
- **Icono en la bandeja del sistema**: al cerrar la ventana con la X, la app
  no se cierra — se oculta y sigue corriendo en la bandeja (icono junto al
  reloj). Clic para reabrirla, o usar "Cerrar" en su menú para salir de
  verdad. Si el entorno no soporta bandeja, la X cierra la app como antes
  (nunca te quedas sin forma de volver a abrirla).
- **Captura rápida**: un cuadro de texto flotante minimalista para anotar
  algo en 1-2 clics sin abrir la ventana principal, con selector de menú.
  Se abre con el atajo global **Ctrl+Alt+G** (funciona aunque la app esté en
  segundo plano), desde el icono de la bandeja, o desde "📌 Captura rápida"
  en el menú lateral. Enter guarda y cierra, Esc cancela.
- **Frases favoritas**: guarda textos que repites a menudo por menú (ej.
  "Llamada a cliente") y regístralos con un solo clic desde "Nota rápida",
  sin escribir nada. Se gestionan desde "⭐ Gestionar frases favoritas" en
  cada menú.
- **Copia de seguridad automática**: al arrancar la app, si no existe ya la
  copia de hoy, se guarda una en `data/backups/registro_AAAA-MM-DD.db`
  (usando la API de backup de SQLite, segura aunque haya algo escribiendo a
  la vez). Se conservan 30 días; las más antiguas se borran solas. Para
  restaurar una copia: cierra la app, sustituye `data/registro.db` por el
  archivo de `data/backups/` que quieras, y vuelve a abrir.
- **Tests automatizados** (`tests/`, pytest): cubren sobre todo el cálculo de
  duración al pausar/reanudar tareas (la lógica más delicada de toda la
  app), el borrado en cascada de un menú, los filtros del histórico y el
  backup. Cada test corre contra una base de datos temporal aislada — nunca
  tocan `data/registro.db`.
- **Datos de ejemplo**: `python cli.py demo` crea los menús "Lueira" y
  "Guilda" con notas, eventos, una tarea y frases favoritas, para probar o
  hacer una demo rápida sin rellenar todo a mano.
- **Gráficos en Estadísticas**: barras horizontales (SVG/CSS, sin librerías)
  junto a las tablas, tanto por menú como por día.
- **Vista "Hoy"** en el panel de inicio: registro cronológico de todos los
  menús del día actual en un solo sitio, sin tener que entrar menú por menú.
- **La IA recuerda el proveedor/modelo** (Ollama/LM Studio + nombre del
  modelo) entre visitas, tanto en el informe como en el chat — no hay que
  volver a escribirlo cada vez (se guarda en el navegador, no en el servidor).
- **Aviso de tarea olvidada**: una tarea con duración que lleva más de 4h
  activa (en curso o en pausa) se marca visualmente por si se te olvidó
  finalizarla.
- **Papelera**: eliminar un menú, una tarea/evento o una nota ya no borra
  nada de verdad — se mueve a la Papelera, desde donde se puede **restaurar**
  o **eliminar definitivamente**. Se purga sola a los 30 días. Al restaurar
  un menú, se recupera junto con lo que se borró a la vez que él (no lo que
  ya estaba en la papelera de antes). Las frases favoritas no pasan por la
  papelera (se pierden al eliminar el menú, pero son triviales de recrear).
- **Importar datos** ("⬆ Importar" en el menú lateral o desde Histórico):
  sube un JSON o CSV exportado desde esta misma app (o desde una copia de
  seguridad antigua) y se vuelve a cargar en la base — los menús que no
  existan se crean solos por nombre. Cada fila se valida por separado: lo
  que esté incompleto o inválido se omite y se cuenta aparte, sin abortar el
  resto de la importación.
- **Reordenar menús** con los botones ↑/↓ en el panel de inicio (y el orden
  se refleja también en el menú lateral). Antes salían siempre por orden
  alfabético.
- **Exportación automática nocturna**: al arrancar la app, si falta el
  resumen en Markdown del día anterior, se genera en `exports/auto/`
  (conservando 30 días). Como la app no está necesariamente abierta a
  medianoche, se comprueba en cada arranque en vez de depender de una hora
  fija — funciona igual que la copia de seguridad automática.
- **Recordatorio periódico**: cada hora, si no ha habido ninguna nota o
  tarea nueva en ese rato, un aviso en la bandeja del sistema recuerda
  anotar (con el atajo Ctrl+Alt+G). Si ya estás registrando actividad, no
  molesta — comprueba primero si ha habido movimiento reciente.

## Acceso desde un agente de IA (Claude Code, Codex CLI...)

Si tienes Claude Code o Codex CLI abierto **en esta carpeta**, ya tienen
acceso de lectura al proyecto — no hace falta usar la interfaz web ni tener
el servidor arrancado. Dos formas de consultar los datos:

```bash
# Listar los menús existentes
python cli.py menus

# Exportar todo el histórico (o filtrado) a stdout o a un archivo
python cli.py export --formato json
python cli.py export --formato md --desde 2026-07-01 --hasta 2026-07-10
python cli.py export --formato csv --menu Guilda --salida exports/guilda.csv

# Crear datos de ejemplo para pruebas/demos, y forzar una copia de seguridad
python cli.py demo
python cli.py backup
```

También pueden leer `data/registro.db` directamente con `sqlite3` (esquema
en [app/db.py](app/db.py)) para consultas que la CLI no cubra.

Si usas **ChatGPT o Claude en el navegador** (sin acceso al sistema de
archivos), la vía es la de siempre: exporta desde el Histórico de la app
(botones JSON/CSV/Markdown) y pega o sube el archivo en la conversación.

## Servidor MCP (notas, tareas, calendario y correo desde Claude/Codex)

`mcp_server.py` expone notas, tareas (con duración y estilo Outlook),
calendario y correo como *tools* MCP, para usar la app directamente desde
Claude Code, Claude Desktop o Codex CLI sin pasar por la interfaz web ni por
la CLI de solo lectura. Es un script aparte — **no se empaqueta en el
`.exe`** — así que hace falta tener Python y las dependencias del servidor
instaladas:

```bash
pip install -r requirements-mcp.txt
```

**Registrarlo en Claude Code** (desde esta misma carpeta del proyecto):

```bash
claude mcp add guilda-work -- python mcp_server.py
```

**Registrarlo en Codex CLI**: añade en tu `config.toml` de Codex (o el
equivalente que use tu instalación):

```toml
[mcp_servers.guilda-work]
command = "python"
args = ["mcp_server.py"]
cwd = "/ruta/a/ELEGANZA"
```

**Claude Desktop**: en su configuración de servidores MCP (`claude_desktop_config.json`),
añade una entrada equivalente con `command`/`args`/`cwd` apuntando a este proyecto.

Tools disponibles (27): `listar_notas`/`crear_nota`/`editar_nota`,
`listar_tareas`/`crear_tarea`/`editar_tarea`/`completar_tarea`,
`consultar_calendario`, `listar_cuentas_correo`/`sincronizar_correo`
(todas las carpetas IMAP se descubren y sincronizan solas),
`listar_carpetas_correo`/`listar_bandeja_entrada`/`leer_correo`/
`marcar_leido_correo`/`eliminar_correo`, categorías de correo propias de
Guilda Work (`listar_categorias_correo`/`crear_categoria_correo`/
`eliminar_categoria_correo`/`asignar_categoria_correo` — no se sincronizan
con el servidor), firma (`obtener_firma_correo`/`configurar_firma_correo`),
`exportar_historial`/`importar_historial`, `exportar_tareas`/`importar_tareas`
(formato `.ics`/`.csv` compatible con Outlook). **Enviar correo es la única
acción de dos pasos a propósito**: `preparar_borrador_correo` (acepta
`cc`/`bcc`) solo genera una vista previa (no envía nada); `enviar_borrador_correo`
es la que de verdad lo manda — dale a tu asistente la instrucción de
confirmar contigo el contenido antes de llamar a esa segunda tool. El `bcc`
nunca viaja como cabecera visible del mensaje enviado.

Fuera de alcance por ahora: sincronización COM en vivo con Outlook Classic
(solo hay import/export por archivo `.ics`/`.csv`) y un conector remoto para
ChatGPT (el soporte actual es MCP local vía stdio, pensado para Claude
Code/Desktop y Codex CLI).

## Zona horaria

Todos los timestamps se guardan en **hora local del sistema** (pensado para
Europe/Madrid), en formato ISO 8601 sin offset, ej: `2026-07-10T14:32:05`.

## Cómo ejecutar (desarrollo)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Esto arranca un servidor Flask en segundo plano y abre una **ventana nativa**
(WebView2) con el título "Guilda Work" — no se abre ningún navegador. La base
de datos SQLite se crea sola en `data/registro.db` la primera vez que se
ejecuta.

## Cómo correr los tests

```bash
pip install -r requirements-dev.txt
pytest
```

No hace falta que la app esté arrancada ni tocan `data/registro.db` — cada
test usa su propia base de datos temporal (ver [tests/conftest.py](tests/conftest.py)).

## Cómo generar el .exe (Windows)

Con el entorno virtual activado y `pyinstaller`/`pywebview` instalados:

```bash
pyinstaller --onefile --windowed --name "GuildaWork" ^
  --icon "assets/icon.ico" ^
  --add-data "app/templates;app/templates" ^
  --add-data "app/static;app/static" ^
  run.py
```

(`--windowed` evita que aparezca una consola detrás de la ventana; si algún
día necesitas ver los logs para depurar, quita ese flag y volverá a mostrarse.)

El ejecutable resultante queda en `dist/GuildaWork.exe`, con su propio icono.
La primera vez que se ejecuta crea una carpeta `data/registro.db` **junto al
propio .exe** (no en una carpeta temporal), así que los datos persisten entre
ejecuciones aunque muevas el `.exe` a otra ubicación — llévate la carpeta
`data/` con él si lo haces.

## Cerrar la app sin dejar procesos zombis

La **X de la ventana ya no cierra la app** — la oculta y la deja corriendo en
la bandeja del sistema (pensado para una app que quieres tener abierta todo
el día sin perder los menús/tareas activas). Para salir de verdad:
- **"Cerrar"** en el menú del icono de la bandeja (junto al reloj), o
- El botón **"⏻ Cerrar programa"** al final del menú lateral, dentro de la app.

Ambas vías terminan el proceso por completo (servidor incluido — en modo
`--onefile` de PyInstaller el `.exe` lanza un segundo proceso interno, y
ambos mueren juntos). Si el entorno no soporta bandeja del sistema (poco
habitual), la X vuelve a comportarse como un cierre normal automáticamente,
para que nunca te quedes sin forma de reabrir la app.

No hay nada que "guardar" al cerrar — cada nota, evento o tarea se escribe
en SQLite (`commit`) en el momento en que la creas, no al cerrar la app, así
que cerrar (o esconder a la bandeja) en cualquier momento es seguro.

Si alguna vez sospechas que ha quedado un proceso colgado (por ejemplo tras
un cierre forzado del sistema), en Windows puedes comprobarlo y terminarlo
con:

```bash
tasklist /FI "IMAGENAME eq GuildaWork.exe"
taskkill /F /IM GuildaWork.exe
```

## Estructura

```
app/
  main.py         # rutas Flask + arranque de la ventana nativa (pywebview)
  db.py           # esquema y acceso a SQLite
  export.py       # exportación a JSON/CSV/Markdown + resumen automático nocturno
  importador.py   # importación de JSON/CSV de vuelta a la base
  ai_local.py     # integración con Ollama / LM Studio
  rutas_tareas.py # blueprint de la pestaña Tareas (lista + calendario estilo Outlook)
  outlook_ics.py  # import/export de tareas a .ics/.csv compatibles con Outlook
  rutas_correo.py # blueprint del cliente de correo IMAP/POP3/SMTP
  correo.py       # lógica de correo (conexión, sincronización, envío HTML)
  templates/    # HTML (Jinja2)
  static/       # CSS/JS, logo.png, favicon.ico
assets/
  icon.ico      # icono del .exe (PyInstaller --icon)
data/
  registro.db   # se crea automáticamente
  backups/      # copias diarias automáticas, se crea automáticamente
exports/
  auto/         # resúmenes automáticos nocturnos (Markdown), se crea solo
tests/          # pytest — ver "Cómo correr los tests"
run.py          # punto de entrada (arranca el servidor web)
cli.py          # acceso a los datos por línea de comandos, sin servidor
mcp_server.py   # servidor MCP (notas/tareas/calendario/correo) para Claude/Codex
requirements.txt      # dependencias para ejecutar la app
requirements-dev.txt  # + pytest, para desarrollo
requirements-mcp.txt  # + mcp, solo para ejecutar mcp_server.py
```
