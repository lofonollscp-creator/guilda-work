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

/// Una persona con la que se comparte una tarea (`GET /tareas-outlook/{id}/compartir`): `colabora` la edita y completa, `observa` solo la ve.
class ParticipanteTarea {
  final int usuarioId;
  final String nombre;
  final String rol;
  const ParticipanteTarea(this.usuarioId, this.nombre, this.rol);

  bool get colabora => rol == 'colabora';

  factory ParticipanteTarea.desdeJson(Map<String, dynamic> j) =>
      ParticipanteTarea((j['usuario_id'] as num).toInt(), (j['nombre'] ?? '').toString(), (j['rol'] ?? 'colabora').toString());
}

/// Una tarea de la que depende otra («Espera a…»).
class DependenciaTarea {
  final int id;
  final String asunto;
  final EstadoTarea estado;
  const DependenciaTarea(this.id, this.asunto, this.estado);

  factory DependenciaTarea.desdeJson(Map<String, dynamic> j) =>
      DependenciaTarea((j['id'] as num).toInt(), (j['asunto'] ?? '').toString(), EstadoTarea.desde(j['estado']?.toString()));
}

/// 90 → «1 h 30», 120 → «2 h», 45 → «45 min» (como la web).
String duracionCorta(int minutos) {
  final h = minutos ~/ 60, m = minutos % 60;
  if (h > 0 && m > 0) return '$h h ${m.toString().padLeft(2, '0')}';
  return h > 0 ? '$h h' : '$m min';
}
