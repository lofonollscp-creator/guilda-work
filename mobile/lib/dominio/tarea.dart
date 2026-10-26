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

/// El cronómetro de una persona sobre una tarea, en marcha o en pausa.
class CronometroTarea {
  final int id;
  final bool pausado;

  /// Segundos trabajados en el momento de pedirlo (con la hora del servidor, no la del móvil); en marcha, [segundos] sigue contando desde [cargadoEn].
  final int _baseSegundos;
  final DateTime cargadoEn;
  CronometroTarea(this.id, this.pausado, this._baseSegundos, this.cargadoEn);

  int segundos([DateTime? ahora]) => pausado ? _baseSegundos : _baseSegundos + (ahora ?? DateTime.now()).difference(cargadoEn).inSeconds;
}

/// `GET /tareas-outlook/{id}/tiempo`: lo registrado por ti y por el equipo, y tu cronómetro si hay uno abierto.
class TiempoDeTarea {
  final int mioSegundos;
  final int equipoSegundos;
  final List<({String nombre, int segundos})> personas;
  final CronometroTarea? cronometro;
  const TiempoDeTarea(this.mioSegundos, this.equipoSegundos, this.personas, this.cronometro);

  static final _momento = RegExp(r'^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):?(\d{2})?');

  static DateTime? _fecha(String? s) {
    final m = s == null ? null : _momento.firstMatch(s);
    return m == null ? null : DateTime.utc(int.parse(m[1]!), int.parse(m[2]!), int.parse(m[3]!), int.parse(m[4]!), int.parse(m[5]!), int.parse(m[6] ?? '0'));
  }

  factory TiempoDeTarea.desdeJson(Map<String, dynamic> j, {DateTime? ahoraLocal}) {
    CronometroTarea? crono;
    final c = j['cronometro'];
    if (c is Map<String, dynamic>) {
      final pausado = c['estado'] == 'pausada';
      var base = (c['segundos_trabajados_congelado'] as num?)?.toInt() ?? 0;
      if (!pausado) {
        final desde = _fecha(c['inicio_en']?.toString()), ahora = _fecha(j['ahora']?.toString());
        final pausados = (c['segundos_pausados'] as num?)?.toInt() ?? 0;
        base = desde == null || ahora == null ? 0 : (ahora.difference(desde).inSeconds - pausados).clamp(0, 1 << 31);
      }
      crono = CronometroTarea((c['id'] as num).toInt(), pausado, base, ahoraLocal ?? DateTime.now());
    }
    return TiempoDeTarea(
      (j['mio_segundos'] as num?)?.toInt() ?? 0,
      (j['equipo_segundos'] as num?)?.toInt() ?? 0,
      [for (final p in (j['personas'] as List? ?? const [])) (nombre: (p['nombre'] ?? '').toString(), segundos: (p['segundos'] as num?)?.toInt() ?? 0)],
      crono,
    );
  }
}

/// Una línea de la actividad de la tarea (`GET /tareas-outlook/{id}/actividad`).
class ActividadDeTarea {
  final String autor;
  final String detalle;
  final String? cuando;
  const ActividadDeTarea(this.autor, this.detalle, this.cuando);

  factory ActividadDeTarea.desdeJson(Map<String, dynamic> j) => ActividadDeTarea((j['autor'] ?? j['usuario'] ?? '').toString(), (j['detalle'] ?? j['accion'] ?? j['tipo'] ?? '').toString(), j['creado_en']?.toString());
}

/// 3725 → «1:02:05», para el cronómetro.
String reloj(int segundos) {
  final h = segundos ~/ 3600, m = (segundos % 3600) ~/ 60, s = segundos % 60;
  String d(int n) => n.toString().padLeft(2, '0');
  return '$h:${d(m)}:${d(s)}';
}
