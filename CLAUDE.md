# Proyecto: Registro Diario de Actividad (Daily Log & Task Tracker)

## Objetivo

Aplicación para Windows 11 que permita:
1. Llevar un **log cronológico** de notas libres, cada una con fecha y hora exactas de creación.
2. Gestionar **tareas con duración**: iniciar, pausar/reanudar (opcional) y finalizar, quedando registrado el tiempo total dedicado.
3. Soportar **múltiples tareas simultáneas** organizadas por categorías/ubicaciones ("lanes"), sin que una interfiera o bloquee a otra.
4. Almacenar todo en una base de datos estructurada, consultable y exportable, para que una IA (Claude, ChatGPT, etc.) pueda leer los datos posteriormente y generar informes, resúmenes y tablas.

No hace falta que sea perfecta a la primera. Empieza por una versión funcional mínima (MVP) y luego iteramos.

---

## Caso de uso ilustrativo

Esto es un ejemplo real de cómo se usaría la app en un día normal, para dejar claro qué se espera del comportamiento de categorías, eventos instantáneos y tareas con duración funcionando a la vez:

**Pestaña / categoría "Lueira" (trabajo)**
- `10:23` — Evento instantáneo: "Atendido cliente X (consulta sobre reserva)".
- `10:30` — Evento instantáneo: "Llamada a cliente Y".
- `10:45` — Evento instantáneo: "Recibido correo de cliente Z, contestado".

**Pestaña / categoría "Guilda" (propio, en paralelo, sin interferir con la anterior)**
- `10:50` — Evento instantáneo: "Avance en desarrollo de [tarea concreta]".
- `11:01` — Tarea con duración iniciada: "Proceso de [algo]".
- `11:42` — Esa misma tarea finalizada → duración calculada automáticamente: 41 minutos.

Puntos clave que se deducen de este ejemplo:
- Cada pestaña/categoría es un **carril independiente**: mientras la tarea de "Guilda" está en curso entre las 11:01 y las 11:42, se pueden seguir añadiendo eventos instantáneos en "Lueira" (o en cualquier otra categoría) sin que eso afecte al cronómetro de la tarea activa.
- La mayoría de las entradas del día a día son **eventos instantáneos** (llamadas, correos, atenciones puntuales) — deben poder registrarse en 1-2 clics, sin fricción, ya que se anotan muchas veces al día.
- Las **tareas con duración** se reservan para procesos que tienen un inicio y un fin identificable (ej. "estuve X minutos trabajando en esto"), y son las que necesitan el botón de inicio/fin.
- Al final del día o semana, se debe poder exportar (o consultar vía IA local) algo como: *"¿Qué hice hoy en Lueira?"* y obtener solo los eventos de esa categoría, o *"¿Cuánto tiempo dediqué a procesos de Guilda esta semana?"* sumando las duraciones de esa categoría.

---

## Requisitos funcionales

### 1. Log de notas
- Campo de texto libre para escribir una nota en cualquier momento.
- Al guardar, se almacena automáticamente: fecha, hora exacta (con segundos), y el texto.
- Opcional: poder asociar la nota a una tarea activa o a una categoría/ubicación.
- Listado cronológico (más reciente arriba), con filtro por fecha y por categoría.

### 2. Tareas con duración
Cada tarea tiene:
- Nombre / descripción.
- Categoría o "ubicación" (ver punto 3).
- Estado: `pendiente`, `en curso`, `pausada` (opcional en MVP), `finalizada`.
- Hora de inicio (timestamp exacto).
- Hora de fin (timestamp exacto, cuando se marca como finalizada).
- Duración calculada automáticamente (fin - inicio, restando pausas si las hay).
- Notas asociadas (opcional, vinculando entradas del log a esta tarea).

Acciones necesarias:
- Iniciar tarea nueva.
- Finalizar tarea en curso.
- (Opcional MVP+1) Pausar/reanudar tarea.
- Ver listado de tareas activas y de tareas finalizadas.

### 3. Categorías / ubicaciones simultáneas
- El usuario puede definir varias categorías (ej: "Lueira - Cliente A", "Lueira - Cliente B", "Administración", "Formación").
- Cada categoría funciona como un "carril" independiente: puede haber una tarea activa por categoría al mismo tiempo, sin que iniciar/pausar una tarea en una categoría afecte a las tareas en otras categorías.
- La interfaz debe dejar claro, de un vistazo, qué tareas están activas ahora mismo y en qué categoría.

### 4. Tipo de tarea "instantánea" (sin duración)
Además de las tareas con inicio y fin (duración), debe existir un segundo tipo de entrada:
- **Evento instantáneo**: se crea con un único timestamp (el momento de creación) y no tiene hora de fin ni duración — representa algo puntual que ocurrió en un momento concreto, no una tarea que se extiende en el tiempo.
- Comparte categoría/ubicación con las tareas normales, y aparece en el mismo listado cronológico, pero se distingue visualmente (icono o etiqueta) de las tareas con duración.
- En el modelo de datos, esto se soluciona con el campo `tipo` en la tabla `tareas` (ver esquema actualizado más abajo): si `tipo = 'instantanea'`, los campos `fin_en` y `duracion_segundos` quedan siempre NULL por diseño, no por estar pendiente de finalizar.

### 5. Base de datos y exportación para IA (en la nube y local)
- Usar una base de datos estructurada y portable — **se recomienda SQLite** (un único archivo `.db`, sin necesidad de instalar servidor de base de datos, fácil de consultar y de hacer backup).
- Debe existir una función de **exportación** que genere, a partir de un rango de fechas:
  - JSON estructurado (ideal para pegar en una conversación con una IA o subir como archivo).
  - CSV (para abrir en Excel si hace falta).
  - Opcional: un resumen en Markdown legible por humanos.
- El esquema de datos debe ser simple y autoexplicativo (nombres de campos claros) para que una IA pueda interpretarlo sin necesitar contexto adicional.
- **Compatibilidad con IAs locales (Ollama, LM Studio, etc.):** además de generar archivos exportables para pegar en un chat con Claude/ChatGPT, la app debe poder enviar los datos directamente a un modelo corriendo en local:
  - Ollama expone una API REST local por defecto en `http://localhost:11434` (endpoint `/api/generate` o `/api/chat`). LM Studio hace lo mismo en `http://localhost:1234/v1` con una API compatible con el formato de OpenAI (`/v1/chat/completions`).
  - La app debe incluir una función (puede ser un botón "Generar informe con IA local") que tome el JSON exportado, lo meta en un prompt sencillo (ej. "Resume mis actividades de esta semana agrupadas por categoría") y lo envíe por HTTP a la API local activa (Ollama o LM Studio, configurable).
  - Como no siempre habrá un modelo local corriendo, esta función debe fallar de forma clara y no bloquear el resto de la app si no encuentra el servicio en el puerto esperado (timeout corto + mensaje de error legible, no un crash).
  - No hace falta implementar esto en la Fase 1 — ver fases más abajo.

---

## Modelo de datos propuesto

```sql
-- Categorías / ubicaciones
CREATE TABLE categorias (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    color TEXT,              -- opcional, para UI
    creada_en TEXT NOT NULL  -- ISO 8601
);

-- Notas del log
CREATE TABLE notas (
    id INTEGER PRIMARY KEY,
    texto TEXT NOT NULL,
    categoria_id INTEGER,             -- puede ser NULL
    tarea_id INTEGER,                 -- puede ser NULL
    creada_en TEXT NOT NULL,          -- ISO 8601, timestamp exacto
    FOREIGN KEY (categoria_id) REFERENCES categorias(id),
    FOREIGN KEY (tarea_id) REFERENCES tareas(id)
);

-- Tareas
CREATE TABLE tareas (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    categoria_id INTEGER NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('duracion','instantanea')) DEFAULT 'duracion',
    estado TEXT NOT NULL CHECK (estado IN ('pendiente','en_curso','pausada','finalizada')),
    inicio_en TEXT,           -- ISO 8601, NULL si aún no ha empezado
    fin_en TEXT,              -- ISO 8601. Si tipo = 'instantanea', SIEMPRE NULL (por diseño)
    duracion_segundos INTEGER, -- calculado al finalizar. Si tipo = 'instantanea', SIEMPRE NULL
    FOREIGN KEY (categoria_id) REFERENCES categorias(id)
);

-- (Opcional MVP+1) Pausas dentro de una tarea, para calcular duración neta
CREATE TABLE pausas (
    id INTEGER PRIMARY KEY,
    tarea_id INTEGER NOT NULL,
    pausada_en TEXT NOT NULL,
    reanudada_en TEXT,
    FOREIGN KEY (tarea_id) REFERENCES tareas(id)
);
```

Todos los timestamps en formato **ISO 8601** (`2026-07-10T14:32:05`) para que sean fáciles de ordenar, comparar y de interpretar por cualquier IA o herramienta.

---

## Stack técnico recomendado

Dado que es para uso personal en Windows 11, sin necesidad de distribución ni instaladores complejos, se recomienda:

- **Lenguaje:** Python 3.11+
- **Base de datos:** SQLite (módulo `sqlite3`, incluido en Python — cero dependencias externas)
- **Interfaz:**
  - Opción simple: aplicación de escritorio con `tkinter` (viene incluido con Python, sin instalar nada extra) o `customtkinter` (más moderna visualmente).
  - Alternativa: pequeña app web local con Flask/FastAPI + HTML servida en `localhost`, si se prefiere una interfaz más flexible (tablas, filtros) usando el navegador.
- **Empaquetado (opcional, más adelante):** `pyinstaller` para generar un `.exe` ejecutable sin necesitar Python instalado.

Si prefieres otro stack (C#/.NET con WPF, Electron, etc.) coméntamelo, pero Python + SQLite + tkinter es la opción más rápida de desarrollar, mantener y depurar para un proyecto personal de este tipo.

---

## Estructura de carpetas sugerida

```
/
├── app/
│   ├── main.py              # punto de entrada, arranca la UI
│   ├── db.py                 # conexión y funciones CRUD sobre SQLite
│   ├── models.py              # definición de entidades (Nota, Tarea, Categoria)
│   ├── ui/
│   │   ├── main_window.py
│   │   ├── task_panel.py
│   │   └── log_panel.py
│   └── export.py             # funciones de exportación a JSON/CSV/Markdown
├── data/
│   └── registro.db           # base de datos SQLite (se crea al primer uso)
├── exports/                  # carpeta donde se guardan los JSON/CSV exportados
├── requirements.txt
└── README.md
```

---

## Fases de desarrollo (MVP primero)

**Fase 1 — MVP funcional**
1. Crear base de datos SQLite con el esquema anterior.
2. Interfaz mínima para: crear categoría, escribir nota rápida, iniciar tarea, finalizar tarea, y crear evento instantáneo (un único clic, sin necesidad de finalizarlo después).
3. Vista de "tareas activas ahora" agrupadas por categoría.
4. Vista de histórico de notas, tareas finalizadas y eventos instantáneos.

**Fase 2 — Exportación e integración con IA**
5. Botón/función para exportar rango de fechas a JSON y CSV.
6. Generar un resumen en Markdown legible (opcional).
7. Integración con IA local (Ollama / LM Studio) para generar informes directamente desde la app, según lo descrito en el punto 5 de requisitos funcionales.

**Fase 3 — Mejoras**
7. Pausar/reanudar tareas.
8. Estadísticas básicas (tiempo total por categoría, por día).
9. Empaquetado como `.exe` con PyInstaller.

---

## Notas para Claude Code

- Empieza siempre confirmando el plan de la Fase 1 antes de generar mucho código de golpe.
- Prioriza que la app **arranque y funcione** de forma simple antes de pulir la interfaz.
- Usa timestamps en UTC o con zona horaria local consistente — indícame cuál usas para no tener sorpresas al analizar los datos luego con una IA.
- El objetivo final de los exports es que yo pueda coger el JSON o CSV generado y pegarlo (o subirlo) directamente a una conversación con una IA para pedirle informes o tablas, así que cuanto más autoexplicativo sea el esquema, mejor.
- `app.config["TEMPLATES_AUTO_RELOAD"] = True` está puesto a propósito en `app/main.py`. Sin esto, con `debug=False` Jinja cachea las plantillas compiladas la primera vez y no recoge cambios en los `.html` hasta reiniciar el proceso — si al probar un cambio de plantilla no se refleja, no es un bug del código, reinicia el servidor de pruebas.

## Cómo leer los datos desde un agente de IA con acceso a esta carpeta (Claude Code, Codex CLI...)

No hace falta pasar por la interfaz web ni tener el servidor Flask arrancado.
Dos formas, de más a menos cómoda:

1. **CLI del proyecto** (recomendado): `python cli.py menus` y
   `python cli.py export --formato json|csv|md [--desde AAAA-MM-DD] [--hasta AAAA-MM-DD] [--menu <nombre_o_id>]`.
   Imprime a stdout o guarda con `--salida ruta.json`. No requiere que la app esté corriendo.
2. **Leer `data/registro.db` directamente** con `sqlite3` (Python stdlib):
   es la base de datos SQLite completa, esquema en `app/db.py`. Útil para
   consultas ad-hoc que la CLI no cubre.

Si el archivo `data/registro.db` no existe todavía, es que el usuario no ha
usado la app ninguna vez — no hay datos que leer, no es un error.
