/// Modelos de datos para el Dashboard y Notas/Tareas con duración (Fase 4c).
/// Reflejan los campos que ya devuelve la API de la Fase 2
/// (app/rutas_api.py), que a su vez son los mismos que usa la web
/// (app/db.py) — ver plan de la app móvil para el mapeo exacto.
class Categoria {
  final int id;
  final String nombre;
  final String? color;
  final bool favorito;

  Categoria({
    required this.id,
    required this.nombre,
    this.color,
    required this.favorito,
  });

  factory Categoria.fromJson(Map<String, dynamic> json) => Categoria(
        id: json['id'] as int,
        nombre: json['nombre'] as String,
        color: json['color'] as String?,
        favorito: (json['favorito'] as int? ?? 0) != 0,
      );
}

/// Tarea con duración en curso o en pausa (db.tareas_activas). No incluye
/// los campos de cronómetro (segundos_pausados, segundos_trabajados_congelado)
/// porque esta fase no muestra un reloj en vivo, solo el estado.
class TareaActiva {
  final int id;
  final String nombre;
  final int categoriaId;
  final String estado;

  TareaActiva({
    required this.id,
    required this.nombre,
    required this.categoriaId,
    required this.estado,
  });

  factory TareaActiva.fromJson(Map<String, dynamic> json) => TareaActiva(
        id: json['id'] as int,
        nombre: json['nombre'] as String,
        categoriaId: json['categoria_id'] as int,
        estado: json['estado'] as String,
      );
}

/// Una fila del histórico combinado de notas y tareas (db.historial).
class EntradaHistorial {
  final String origen; // 'nota' o 'tarea'
  final int id;
  final String texto;
  final String? tipo; // solo si origen == 'tarea': 'duracion' o 'instantanea'
  final String? estado;
  final String? timestamp;
  final int? duracionSegundos;
  final String? categoriaNombre;
  final String? categoriaColor;

  EntradaHistorial({
    required this.origen,
    required this.id,
    required this.texto,
    this.tipo,
    this.estado,
    this.timestamp,
    this.duracionSegundos,
    this.categoriaNombre,
    this.categoriaColor,
  });

  factory EntradaHistorial.fromJson(Map<String, dynamic> json) => EntradaHistorial(
        origen: json['origen'] as String,
        id: json['id'] as int,
        texto: json['texto'] as String,
        tipo: json['tipo'] as String?,
        estado: json['estado'] as String?,
        timestamp: json['timestamp'] as String?,
        duracionSegundos: json['duracion_segundos'] as int?,
        categoriaNombre: json['categoria_nombre'] as String?,
        categoriaColor: json['categoria_color'] as String?,
      );
}

/// Tarea "estilo Outlook" (independiente de los menús), Fase 4d — mismos
/// campos que app/templates/tarea_outlook_editar.html.
class TareaOutlook {
  final int id;
  final String asunto;
  final String? cuerpo;
  final String estado;
  final String prioridad;
  final int porcentajeCompletado;
  final String? fechaInicio;
  final String? fechaVencimiento;
  final String? categoriaOutlook;

  TareaOutlook({
    required this.id,
    required this.asunto,
    this.cuerpo,
    required this.estado,
    required this.prioridad,
    required this.porcentajeCompletado,
    this.fechaInicio,
    this.fechaVencimiento,
    this.categoriaOutlook,
  });

  factory TareaOutlook.fromJson(Map<String, dynamic> json) => TareaOutlook(
        id: json['id'] as int,
        asunto: json['asunto'] as String,
        cuerpo: json['cuerpo'] as String?,
        estado: json['estado'] as String,
        prioridad: json['prioridad'] as String,
        porcentajeCompletado: json['porcentaje_completado'] as int? ?? 0,
        fechaInicio: json['fecha_inicio'] as String?,
        fechaVencimiento: json['fecha_vencimiento'] as String?,
        categoriaOutlook: json['categoria_outlook'] as String?,
      );
}

const estadosTareaOutlook = [
  ('no_iniciada', 'No iniciada'),
  ('en_progreso', 'En progreso'),
  ('completada', 'Completada'),
  ('esperando', 'Esperando a otros'),
  ('aplazada', 'Aplazada'),
];

const prioridadesTareaOutlook = [
  ('baja', 'Baja'),
  ('normal', 'Normal'),
  ('alta', 'Alta'),
];
