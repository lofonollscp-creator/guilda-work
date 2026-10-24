/// Estado de una tarea tal como lo manda el servidor. Un estado nuevo que esta
/// versión de la app no conozca llega como [desconocido] y no rompe nada.
enum EstadoTarea {
  noIniciada('no_iniciada'),
  enProgreso('en_progreso'),
  esperando('esperando'),
  aplazada('aplazada'),
  enRevision('en_revision'),
  completada('completada'),
  desconocido('');

  final String valor;
  const EstadoTarea(this.valor);

  static EstadoTarea desde(String? s) => values.firstWhere((e) => e.valor == s, orElse: () => EstadoTarea.desconocido);

  /// Lo que se puede elegir a mano (`en_revision` lo gestiona el flujo de revisión).
  static const elegibles = [noIniciada, enProgreso, esperando, aplazada, completada];

  bool get abierta => this != completada;

  /// `esperando` exige decir por qué (el servidor lo rechaza si no hay motivo).
  bool get pideMotivo => this == esperando;
}

enum PrioridadTarea {
  baja('baja'),
  normal('normal'),
  alta('alta');

  final String valor;
  const PrioridadTarea(this.valor);

  static PrioridadTarea desde(String? s) => values.firstWhere((e) => e.valor == s, orElse: () => PrioridadTarea.normal);
}

/// Una subtarea tal como la manda `GET /tareas-outlook/{id}/subtareas`.
class Subtarea {
  final int id;
  final String asunto;
  final EstadoTarea estado;
  const Subtarea(this.id, this.asunto, this.estado);

  factory Subtarea.desdeJson(Map<String, dynamic> j) => Subtarea((j['id'] as num).toInt(), (j['asunto'] ?? '').toString(), EstadoTarea.desde(j['estado']?.toString()));
}
