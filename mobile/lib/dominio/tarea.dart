import '../api/generado/modelos.g.dart' show TareaOutlook;

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

/// El voto de una persona en una revisión.
class VotoRevision {
  final int revisorId;
  final String revisor;
  final String estado; // pendiente | aprobado | cambios
  final String? nota;
  const VotoRevision(this.revisorId, this.revisor, this.estado, this.nota);

  factory VotoRevision.desdeJson(Map<String, dynamic> j) =>
      VotoRevision((j['revisor_id'] as num).toInt(), (j['revisor'] ?? '').toString(), (j['estado'] ?? 'pendiente').toString(), j['nota']?.toString());
}

/// Una revisión (pendiente o ya resuelta): quién la pidió, a quién, en qué modo y cómo van los votos.
class RevisionDeTarea {
  final int id;
  final String estado; // pendiente | aprobada | cambios | cancelada
  final String modo; // todos | cualquiera | cadena
  final int? solicitadaPor;
  final String? notaSolicitud;
  final String? notaResolucion;
  final int? turno;
  final List<int> puedenVotar;
  final List<VotoRevision> votos;
  final int aprobados;
  const RevisionDeTarea(this.id, this.estado, this.modo, this.solicitadaPor, this.notaSolicitud, this.notaResolucion, this.turno, this.puedenVotar, this.votos, this.aprobados);

  bool get pendiente => estado == 'pendiente';

  factory RevisionDeTarea.desdeJson(Map<String, dynamic> j) => RevisionDeTarea(
        (j['id'] as num).toInt(),
        (j['estado'] ?? 'pendiente').toString(),
        (j['modo'] ?? 'todos').toString(),
        (j['solicitada_por'] as num?)?.toInt(),
        j['nota_solicitud']?.toString(),
        j['nota_resolucion']?.toString(),
        (j['turno'] as num?)?.toInt(),
        [for (final x in (j['pueden_votar'] as List? ?? const [])) (x as num).toInt()],
        [for (final v in (j['votos'] as List? ?? const [])) VotoRevision.desdeJson(v as Map<String, dynamic>)],
        (j['aprobados'] as num?)?.toInt() ?? 0,
      );
}

class RevisionesDeLaTarea {
  final RevisionDeTarea? pendiente;
  final List<RevisionDeTarea> resueltas;
  const RevisionesDeLaTarea(this.pendiente, this.resueltas);

  factory RevisionesDeLaTarea.desdeJson(Map<String, dynamic> j) {
    final todas = [for (final r in (j['historial'] as List? ?? const [])) RevisionDeTarea.desdeJson(r as Map<String, dynamic>)];
    final p = j['pendiente'];
    return RevisionesDeLaTarea(p is Map<String, dynamic> ? RevisionDeTarea.desdeJson(p) : null, [for (final r in todas) if (!r.pendiente) r]);
  }
}

/// Un mensaje de la conversación con un cliente (lo del cliente es contenido externo: solo se enseña, nunca se interpreta).
class MensajeCliente {
  final int id;
  final bool delCliente;
  final String? usuario;
  final String texto;
  final String? creadoEn;
  final bool oculto;
  const MensajeCliente(this.id, this.delCliente, this.usuario, this.texto, this.creadoEn, this.oculto);

  factory MensajeCliente.desdeJson(Map<String, dynamic> j) =>
      MensajeCliente((j['id'] as num).toInt(), j['origen'] == 'cliente', j['usuario']?.toString(), (j['texto'] ?? '').toString(), j['creado_en']?.toString(), j['oculto'] == true);
}

class ConversacionConCliente {
  final int clienteId;
  final String cliente;
  final int sinLeer;
  final List<MensajeCliente> mensajes;
  const ConversacionConCliente(this.clienteId, this.cliente, this.sinLeer, this.mensajes);

  factory ConversacionConCliente.desdeJson(Map<String, dynamic> j) => ConversacionConCliente(
        (j['cliente_fiscal_id'] as num).toInt(),
        (j['cliente'] ?? '').toString(),
        (j['sin_leer'] as num?)?.toInt() ?? 0,
        [for (final m in (j['mensajes'] as List? ?? const [])) MensajeCliente.desdeJson(m as Map<String, dynamic>)],
      );
}

// ---- Calendario y carga ----

class VencimientoDelDia {
  final int id;
  final String modelo;
  final String cliente;
  final String? periodo;
  final bool presentado;
  const VencimientoDelDia(this.id, this.modelo, this.cliente, this.periodo, this.presentado);

  factory VencimientoDelDia.desdeJson(Map<String, dynamic> j) =>
      VencimientoDelDia((j['id'] as num).toInt(), (j['modelo'] ?? '').toString(), (j['cliente_nombre'] ?? '').toString(), j['periodo']?.toString(), j['estado'] == 'presentado');
}

class CitaDelDia {
  final String? inicio;
  final String titulo;
  const CitaDelDia(this.inicio, this.titulo);

  factory CitaDelDia.desdeJson(Map<String, dynamic> j) => CitaDelDia(j['inicio']?.toString(), (j['titulo'] ?? '').toString());
}

/// Un día del calendario de tareas: lo mismo que enseña la web (tareas, vencimientos fiscales, citas y horas fichadas).
class DiaCalendario {
  final String fecha; // AAAA-MM-DD
  final bool esHoy;
  final bool esMesActual;
  final List<TareaOutlook> tareas;
  final List<VencimientoDelDia> vencimientos;
  final List<CitaDelDia> citas;
  final int fichadoSegundos;
  const DiaCalendario(this.fecha, this.esHoy, this.esMesActual, this.tareas, this.vencimientos, this.citas, this.fichadoSegundos);

  bool get vacio => tareas.isEmpty && vencimientos.isEmpty && citas.isEmpty && fichadoSegundos == 0;
}

class CalendarioDeTareas {
  final String vista;
  final String fecha;
  final List<DiaCalendario> dias;
  final String? avisoCitas;
  const CalendarioDeTareas(this.vista, this.fecha, this.dias, this.avisoCitas);
}

class TareaDeCarga {
  final int id;
  final String asunto;
  final int? estimacionMin;
  final String prioridad;
  const TareaDeCarga(this.id, this.asunto, this.estimacionMin, this.prioridad);
}

/// Un día (o «atrasadas» / «sin fecha») de una persona en el plan de carga: minutos estimados y las tareas (las primeras; `mas` son las que no caben).
class CeldaDeCarga {
  final int minutos;
  final int n;
  final int sinEstimar;
  final int mas;
  final List<TareaDeCarga> tareas;
  const CeldaDeCarga(this.minutos, this.n, this.sinEstimar, this.mas, this.tareas);

  static const vacia = CeldaDeCarga(0, 0, 0, 0, []);

  factory CeldaDeCarga.desdeJson(Map<String, dynamic>? j) => j == null
      ? vacia
      : CeldaDeCarga(
          (j['min'] as num?)?.toInt() ?? 0,
          (j['n'] as num?)?.toInt() ?? 0,
          (j['sin_estimar'] as num?)?.toInt() ?? 0,
          (j['mas'] as num?)?.toInt() ?? 0,
          [for (final t in (j['tareas'] as List? ?? const [])) TareaDeCarga((t['id'] as num).toInt(), (t['asunto'] ?? '').toString(), (t['estimacion_min'] as num?)?.toInt(), (t['prioridad'] ?? 'normal').toString())],
        );

  /// Como la web: rojo si pasa de la capacidad, ámbar desde el 70 %, verde por debajo; sin capacidad (fin de semana, atrasadas, sin fecha) no hay nivel.
  NivelCarga nivel(int capacidadMin) {
    if (capacidadMin <= 0 || minutos <= 0) return NivelCarga.ninguno;
    if (minutos > capacidadMin) return NivelCarga.rojo;
    return minutos >= capacidadMin * 0.7 ? NivelCarga.ambar : NivelCarga.verde;
  }
}

enum NivelCarga { ninguno, verde, ambar, rojo }

class PersonaDeCarga {
  final int id;
  final String nombre;
  final bool yo;
  final int capacidadDiaMin;
  final int semanaMin;
  final int capacidadSemanaMin;
  final Map<String, CeldaDeCarga> dias;
  final CeldaDeCarga atrasadas;
  final CeldaDeCarga sinFecha;
  const PersonaDeCarga(this.id, this.nombre, this.yo, this.capacidadDiaMin, this.semanaMin, this.capacidadSemanaMin, this.dias, this.atrasadas, this.sinFecha);

  factory PersonaDeCarga.desdeJson(Map<String, dynamic> j) => PersonaDeCarga(
        (j['id'] as num).toInt(),
        (j['nombre'] ?? '').toString(),
        j['yo'] == true,
        (j['capacidad_dia_min'] as num?)?.toInt() ?? 0,
        (j['semana_min'] as num?)?.toInt() ?? 0,
        (j['capacidad_semana_min'] as num?)?.toInt() ?? 0,
        {for (final e in (j['dias'] as Map? ?? const {}).entries) e.key.toString(): CeldaDeCarga.desdeJson(e.value as Map<String, dynamic>?)},
        CeldaDeCarga.desdeJson(j['atrasadas'] as Map<String, dynamic>?),
        CeldaDeCarga.desdeJson(j['sin_fecha'] as Map<String, dynamic>?),
      );
}

class CargaSemanal {
  final String lunes;
  final List<String> dias; // los siete días, AAAA-MM-DD
  final List<PersonaDeCarga> personas;
  const CargaSemanal(this.lunes, this.dias, this.personas);

  factory CargaSemanal.desdeJson(Map<String, dynamic> j) => CargaSemanal(
        (j['lunes'] ?? '').toString(),
        [for (final d in (j['dias'] as List? ?? const [])) d.toString().substring(0, 10)],
        [for (final p in (j['personas'] as List? ?? const [])) PersonaDeCarga.desdeJson(p as Map<String, dynamic>)],
      );
}
