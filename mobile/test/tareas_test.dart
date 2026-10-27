import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/api/cliente.dart';
import 'package:guilda_work_mobile/api/errores.dart';
import 'package:guilda_work_mobile/api/fechas.dart';
import 'package:guilda_work_mobile/api/generado/modelos.g.dart';
import 'package:guilda_work_mobile/datos/cola.dart';
import 'package:guilda_work_mobile/datos/local/cola_escritura.dart';
import 'package:guilda_work_mobile/dominio/tarea.dart';
import 'package:guilda_work_mobile/funciones/tareas/tarea_detalle_screen.dart';
import 'package:guilda_work_mobile/funciones/tareas/tareas_lista_controlador.dart';
import 'package:guilda_work_mobile/funciones/hoy/hoy_controlador.dart';
import 'package:guilda_work_mobile/funciones/hoy/hoy_screen.dart';
import 'package:guilda_work_mobile/funciones/tareas/calendario_screen.dart';
import 'package:guilda_work_mobile/funciones/tareas/tareas_repositorio.dart';
import 'package:guilda_work_mobile/funciones/tareas/tareas_vistas.dart';
import 'package:guilda_work_mobile/funciones/tareas/tareas_screen.dart';
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/nucleo/servicios.dart';
import 'package:guilda_work_mobile/screens/ia_chat_screen.dart';
import 'package:guilda_work_mobile/nucleo/sesion.dart';
import 'package:guilda_work_mobile/theme/app_theme.dart';
import 'package:guilda_work_mobile/services/api_client.dart' as sv;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'ayudas/pantallas.dart' show serviciosFalsos;

// ---------- servidor falso para el repositorio ----------

class _Ctx implements ContextoApi {
  @override
  int? get usuarioId => 1;
  @override
  Future<String> servidor() async => 'https://s.test';
  @override
  Future<String?> token() async => 't';
  @override
  String? get despacho => null;
  @override
  String get idioma => 'es';
  @override
  String get versionApp => '1.0.0';
  @override
  String get plataforma => 'android';
  @override
  Future<void> alSesionExpirada() async {}
  @override
  Future<void> alRequerirActualizacion({String? urlTienda}) async {}
}

class _Llamada {
  final String metodo, ruta;
  final Map<String, dynamic>? consulta;
  final Object? cuerpo;
  final bool multipart;
  _Llamada(this.metodo, this.ruta, this.consulta, this.cuerpo, this.multipart);
}

class _ClienteFalso extends ClienteApi {
  final llamadas = <_Llamada>[];
  final Map<String, dynamic> respuestas;
  _ClienteFalso(this.respuestas) : super(_Ctx());
  @override
  Future<dynamic> enviar(String metodo, String ruta, {Map<String, dynamic>? consulta, Object? cuerpo, bool multipart = false, bool binario = false}) async {
    llamadas.add(_Llamada(metodo, ruta, consulta, cuerpo, multipart));
    return respuestas['$metodo $ruta'];
  }
}

Map<String, dynamic> _t(int id, {String estado = 'no_iniciada', int version = 1, String? fecha, bool vencida = false, String? motivo, String prioridad = 'normal'}) => {
      'id': id, 'asunto': 'Tarea $id', 'estado': estado, 'version': version, 'prioridad': prioridad, 'fecha_vencimiento': fecha, 'vencida': vencida, 'motivo_bloqueo': motivo,
    };

// ---------- repositorio falso para controlador y pantallas ----------

class _RepoFalso implements TareasRepositorio {
  final List<String> registro = [];
  List<TareaOutlook> Function(String ambito, String? estado, String? q, int offset) paginas = (a, e, q, o) => [];
  Future<TareaOutlook> Function(int id, EstadoTarea estado, String? motivo, int? version)? alTransicionar;
  Map<int, TareaOutlook> tareas = {};
  List<Subtarea> subs = [];
  List<ChecklistItem> check = [];
  List<ComentarioTarea> coments = [];
  List<AdjuntoTarea> adjs = [];

  @override
  Future<List<TareaOutlook>> listar({String ambito = 'propias', String? estado, String? q, int limit = 30, int offset = 0, String? prioridad, String? categoria, bool? soloAbiertas}) async {
    registro.add('listar:$ambito:${estado ?? '-'}:${(q == null || q.isEmpty) ? '-' : q}:$offset');
    filtrosVistos.add('${prioridad ?? '-'}|${categoria ?? '-'}|${soloAbiertas ?? '-'}');
    return paginas(ambito, estado, q, offset);
  }

  final List<String> filtrosVistos = [];

  // --- ficha completa ---
  List<Companero> gente = const [Companero(id: 7, nombre: 'Luis Mora'), Companero(id: 8, nombre: 'Sol Pérez')];
  List<Proyecto> misProyectos = const [Proyecto(id: 3, nombre: 'IVA'), Proyecto(id: 4, nombre: 'Laboral')];
  List<ClienteFiscal> misClientes = const [ClienteFiscal(id: 11, nombre: 'Acme SL'), ClienteFiscal(id: 12, nombre: 'Beta SA')];
  List<ParticipanteTarea> participantesFalsos = [];
  List<DependenciaTarea> esperas = [];
  List<RecordatorioTarea> recordatoriosFalsos = [];
  Object? falloAlAsignar;
  Object? falloAlEditar;

  @override
  Future<TareaOutlook> editarFicha(int id,
      {String? asunto, String? cuerpo, PrioridadTarea? prioridad, String? estimacion, String? categoriaOutlook, int? porcentaje, String? fechaInicio, bool quitarInicio = false, String? fechaVencimiento, bool quitarVencimiento = false}) async {
    if (falloAlEditar != null) throw falloAlEditar!;
    registro.add('ficha:$id:${[if (asunto != null) 'asunto=$asunto', if (cuerpo != null) 'cuerpo=$cuerpo', if (prioridad != null) 'prio=${prioridad.valor}', if (estimacion != null) 'est=$estimacion', if (categoriaOutlook != null) 'cat=$categoriaOutlook', if (fechaVencimiento != null) 'venc=$fechaVencimiento', if (quitarVencimiento) 'venc=-', if (fechaInicio != null) 'ini=$fechaInicio', if (quitarInicio) 'ini=-'].join(',')}');
    return tareas[id] ?? TareaOutlook.fromJson(_t(id));
  }

  CalendarioDeTareas calendarioFalso = const CalendarioDeTareas('mes', '', [], null);
  CargaSemanal cargaFalsa = const CargaSemanal('', [], []);
  final List<String> vistasPedidas = [];

  @override
  Future<CalendarioDeTareas> calendario(String vista, Fecha fecha) async {
    vistasPedidas.add('$vista:${fecha.toJson()}');
    return calendarioFalso;
  }

  @override
  Future<CargaSemanal> carga(Fecha semana) async {
    vistasPedidas.add('carga:${semana.toJson()}');
    return cargaFalsa;
  }

  @override
  Future<void> mover(int id, {bool cambiarPersona = false, int? personaId, bool cambiarFecha = false, String? fecha}) async =>
      registro.add('mover:$id:${cambiarPersona ? 'p=${personaId ?? '-'}' : ''}:${cambiarFecha ? 'f=${fecha ?? '-'}' : ''}');

  RevisionesDeLaTarea revisionesFalsas = const RevisionesDeLaTarea(null, []);
  List<ConversacionConCliente> conversacionesFalsas = [];
  List<(int, String)> respuestasCliente = [];

  @override
  Future<RevisionesDeLaTarea> revisiones(int id) async => revisionesFalsas;
  @override
  Future<void> pedirRevision(int id, List<int> revisores, {String modo = 'todos', String? nota}) async {
    registro.add('revision:$id:${revisores.join(',')}:$modo:${nota ?? '-'}');
    revisionesFalsas = RevisionesDeLaTarea(
      RevisionDeTarea(1, 'pendiente', modo, 1, nota, null, null, revisores, [for (final r in revisores) VotoRevision(r, gente.firstWhere((g) => g.id == r).nombre ?? '', 'pendiente', null)], 0),
      const [],
    );
  }

  @override
  Future<void> votarRevision(int id, String decision, {String? nota}) async {
    registro.add('voto:$id:$decision:${nota ?? '-'}');
    revisionesFalsas = const RevisionesDeLaTarea(null, []);
  }

  @override
  Future<void> retirarRevision(int id) async {
    registro.add('retirar:$id');
    revisionesFalsas = const RevisionesDeLaTarea(null, []);
  }

  @override
  Future<List<ConversacionConCliente>> conversacionesConClientes(int id, {bool marcarLeidos = false}) async {
    if (marcarLeidos) registro.add('leidos:$id');
    return conversacionesFalsas;
  }

  @override
  Future<void> responderAlCliente(int id, int clienteId, String texto) async {
    registro.add('responder:$id:$clienteId:$texto');
    conversacionesFalsas = [
      ConversacionConCliente(clienteId, 'Acme SL', 0, [...conversacionesFalsas.expand((c) => c.mensajes), MensajeCliente(99, false, 'Yo', texto, '2026-10-26T10:00', false)]),
    ];
  }

  @override
  Future<void> ocultarComentarioDeCliente(int comentarioId) async {
    registro.add('ocultar:$comentarioId');
    conversacionesFalsas = [
      for (final c in conversacionesFalsas) ConversacionConCliente(c.clienteId, c.cliente, 0, [for (final m in c.mensajes) m.id == comentarioId ? MensajeCliente(m.id, true, null, '', m.creadoEn, true) : m]),
    ];
  }

  TiempoDeTarea tiempoFalso = const TiempoDeTarea(0, 0, [], null);
  List<ActividadDeTarea> actividadFalsa = const [];

  @override
  Future<TiempoDeTarea> tiempo(int id) async => tiempoFalso;
  @override
  Future<int> iniciarCronometro(int id, {int? proyectoId}) async {
    registro.add('crono:$id:${proyectoId ?? '-'}');
    tiempoFalso = TiempoDeTarea(0, 0, const [], CronometroTarea(90, false, 0, DateTime.now()));
    return 90;
  }

  @override
  Future<void> pausarCronometro(int cronometroId) async {
    registro.add('pausa:$cronometroId');
    tiempoFalso = TiempoDeTarea(0, 0, const [], CronometroTarea(cronometroId, true, 125, DateTime.now()));
  }

  @override
  Future<void> reanudarCronometro(int cronometroId) async {
    registro.add('reanuda:$cronometroId');
    tiempoFalso = TiempoDeTarea(0, 0, const [], CronometroTarea(cronometroId, false, 125, DateTime.now()));
  }

  @override
  Future<void> finalizarCronometro(int cronometroId) async {
    registro.add('finaliza:$cronometroId');
    tiempoFalso = const TiempoDeTarea(180, 180, [(nombre: 'Yo', segundos: 180)], null);
  }

  @override
  Future<List<ActividadDeTarea>> actividad(int id) async => actividadFalsa;
  @override
  Future<void> visibleParaCliente(int id, {required bool visible, bool? comentarios}) async => registro.add('portal:$id:$visible:${comentarios ?? '-'}');

  @override
  Future<List<Companero>> companeros() async => gente;
  @override
  Future<List<Proyecto>> proyectos() async => misProyectos;
  @override
  Future<List<ClienteFiscal>> clientesFiscales() async => misClientes;
  @override
  Future<void> asignar(int id, int? companeroId) async {
    if (falloAlAsignar != null) throw falloAlAsignar!;
    registro.add('asignar:$id:${companeroId ?? '-'}');
  }

  @override
  Future<({int ok, int fallos})> moverAProyecto(int id, int? proyectoId) async {
    registro.add('proyecto:$id:${proyectoId ?? '-'}');
    return (ok: 1, fallos: 0);
  }

  @override
  Future<void> fijarCliente(int id, int? clienteId, {List<int> otros = const []}) async => registro.add('cliente:$id:${clienteId ?? '-'}:${otros.join(',')}');
  @override
  Future<List<ParticipanteTarea>> participantes(int id) async => participantesFalsos;
  @override
  Future<void> compartir(int id, int usuarioId, String rol) async {
    registro.add('compartir:$id:$usuarioId:$rol');
    participantesFalsos = [...participantesFalsos, ParticipanteTarea(usuarioId, gente.firstWhere((g) => g.id == usuarioId).nombre ?? '', rol)];
  }

  @override
  Future<void> dejarDeCompartir(int id, int usuarioId) async {
    registro.add('descompartir:$id:$usuarioId');
    participantesFalsos = [for (final p in participantesFalsos) if (p.usuarioId != usuarioId) p];
  }

  @override
  Future<({bool bloqueada, List<DependenciaTarea> esperaA})> dependencias(int id) async => (bloqueada: esperas.any((d) => d.estado.abierta), esperaA: esperas);
  @override
  Future<void> esperaA(int id, int dependeDeId) async {
    registro.add('espera:$id:$dependeDeId');
    esperas = [...esperas, DependenciaTarea(dependeDeId, 'Tarea $dependeDeId', EstadoTarea.noIniciada)];
  }

  @override
  Future<void> quitarEspera(int id, int dependeDeId) async {
    registro.add('quitarEspera:$id:$dependeDeId');
    esperas = [for (final d in esperas) if (d.id != dependeDeId) d];
  }

  @override
  Future<List<RecordatorioTarea>> recordatorios(int id) async => recordatoriosFalsos;
  @override
  Future<void> anadirRecordatorio(int id, {String? avisarEn, String? atajo, List<String> canales = const ['app']}) async {
    registro.add('recordar:$id:${atajo ?? avisarEn}:${canales.join('+')}');
    recordatoriosFalsos = [...recordatoriosFalsos, RecordatorioTarea(id: 50, avisarEn: avisarEn ?? '2026-10-30T09:00', canales: canales.join(','))];
  }

  @override
  Future<void> quitarRecordatorio(int recordatorioId) async {
    registro.add('quitarRecordatorio:$recordatorioId');
    recordatoriosFalsos = [];
  }

  @override
  Future<void> posponerRecordatorio(int recordatorioId, String opcion) async => registro.add('posponer:$recordatorioId:$opcion');

  Map<String, List<TareaOutlook>> diaFalso = {};
  Map<String, List<TareaOutlook>> tableroFalso = {};

  @override
  Future<Map<String, List<TareaOutlook>>> miDia() async => {for (final s in seccionesMiDia) s: diaFalso[s] ?? []};

  @override
  Future<Map<String, List<TareaOutlook>>> tablero({int recientes = 15}) async => {for (final e in columnasTablero) e.valor: tableroFalso[e.valor] ?? []};
  List<Vista> vistasGuardadas = [];
  ({int ok, int fallos}) resultadoLote = (ok: 0, fallos: 0);
  Set<int> noEliminables = {};

  @override
  Future<void> eliminar(int id) async {
    if (noEliminables.contains(id)) throw ApiException('No es tuya', status: 403);
    registro.add('eliminar:$id');
  }

  @override
  Future<void> restaurar(int id) async => registro.add('restaurar:$id');
  @override
  Future<({int ok, int fallos})> lote(List<int> ids, String accion, {String? valor}) async {
    registro.add('lote:$accion:${valor ?? '-'}:${ids.join(',')}');
    return resultadoLote;
  }

  @override
  Future<List<Vista>> vistas() async => vistasGuardadas;
  @override
  Future<Vista> guardarVista(String nombre, Map<String, String> filtros) async {
    registro.add('vista:$nombre:${(filtros.entries.map((e) => '${e.key}=${e.value}').toList()..sort()).join('&')}');
    return Vista(id: 1, nombre: nombre, filtros: filtros, mia: true);
  }

  @override
  Future<void> eliminarVista(int id) async => registro.add('quitarVista:$id');
  @override
  Future<List<String>> categoriasOutlook() async => ['Fiscal', 'Laboral'];

  @override
  Future<TareaOutlook> obtener(int id) async {
    registro.add('obtener:$id');
    return tareas[id]!;
  }

  @override
  Future<TareaOutlook> crear({required String asunto, String? fechaVencimiento, PrioridadTarea? prioridad, String? clave, bool textoLibre = false}) async {
    registro.add('crear:$asunto:${fechaVencimiento ?? '-'}');
    return TareaOutlook.fromJson(_t(999, estado: 'no_iniciada')..['asunto'] = asunto);
  }

  @override
  Future<TareaOutlook> transicionar(int id, EstadoTarea estado, {String? motivo, int? version, String? clave}) async {
    registro.add('transicionar:$id:${estado.valor}:${motivo ?? '-'}:${version ?? '-'}');
    if (alTransicionar != null) return alTransicionar!(id, estado, motivo, version);
    return TareaOutlook.fromJson(_t(id, estado: estado.valor, version: (version ?? 0) + 1, motivo: motivo));
  }

  @override
  Future<TareaOutlook> editar(int id, {String? asunto, String? cuerpo, PrioridadTarea? prioridad, String? fechaVencimiento}) async => tareas[id]!;
  @override
  Future<({List<Subtarea> subtareas, int hechas})> subtareas(int id) async => (subtareas: subs, hechas: subs.where((s) => !s.estado.abierta).length);
  @override
  Future<void> crearSubtarea(int id, String asunto) async => registro.add('subtarea:$id:$asunto');
  @override
  Future<List<ChecklistItem>> checklist(int id) async => check;
  @override
  Future<void> alternarItem(int itemId) async => registro.add('alternar:$itemId');
  @override
  Future<void> agregarItem(int id, String texto) async => registro.add('punto:$id:$texto');
  @override
  Future<List<ComentarioTarea>> comentarios(int id) async => coments;
  @override
  Future<void> comentar(int id, String texto, {String? clave}) async => registro.add('comentar:$id:$texto');
  @override
  Future<List<AdjuntoTarea>> adjuntos(int id) async => adjs;
  @override
  Future<void> subirAdjunto(int id, MultipartFile archivo) async => registro.add('subir:$id');
  @override
  Future<List<int>> descargarAdjunto(int adjuntoId) async => [1, 2, 3];
  @override
  Future<void> eliminarAdjunto(int adjuntoId) async => registro.add('quitar:$adjuntoId');
}

class _SesionConUsuario extends SesionControl {
  @override
  EstadoSesion build() => EstadoSesion(fase: FaseSesion.conSesion, usuario: sv.Usuario(id: 1, email: 'a@b.c'));
}

class _HoyFalso extends HoyControlador {
  @override
  Future<EstadoHoy> build() async => EstadoHoy(
        BandejaHoy.fromJson({
          'total': 5,
          'urgentes': 2,
          'secciones': [
            {
              'clave': 'tareas', 'titulo': 'Tareas', 'total': 2, 'urgentes': 1,
              'elementos': [
                {'titulo': 'Presentar el 303 de Acme SL', 'detalle': null, 'url': '/tareas/1', 'urgencia': 'vencido', 'fecha': '2026-10-25', 'destino': {'tipo': 'tarea', 'id': 1}, 'acciones': ['abrir', 'completar']},
                {'titulo': 'Llamar a la gestoría laboral', 'detalle': 'Asignada a ti', 'url': '/tareas/4', 'urgencia': 'info', 'fecha': null, 'destino': {'tipo': 'tarea', 'id': 4}, 'acciones': ['abrir', 'completar']},
              ],
            },
            {
              'clave': 'vencimientos', 'titulo': 'Vencimientos fiscales', 'total': 2, 'urgentes': 1,
              'elementos': [
                {'titulo': '303 · Acme SL', 'detalle': null, 'url': '/fiscal', 'urgencia': 'hoy', 'fecha': '2026-10-26', 'destino': {'tipo': 'vencimiento', 'id': 9}, 'acciones': ['abrir', 'presentar']},
                {'titulo': '111 · Beta SA', 'detalle': null, 'url': '/fiscal', 'urgencia': 'proximo', 'fecha': '2026-10-30', 'destino': {'tipo': 'vencimiento', 'id': 10}, 'acciones': ['abrir']},
              ],
            },
            {
              'clave': 'correo', 'titulo': 'Correos sin contestar', 'total': 1, 'urgentes': 0,
              'elementos': [
                {'titulo': 'Consulta sobre la renta', 'detalle': 'Marta Ruiz', 'url': '/correo/1', 'urgencia': 'info', 'fecha': '2026-10-24', 'destino': {'tipo': 'correo', 'id': 3}, 'acciones': ['abrir']},
              ],
            },
          ],
          'destacados': [],
        }),
        DateTime.now(),
      );
}

class _SesionFija extends SesionControl {
  @override
  EstadoSesion build() => const EstadoSesion(fase: FaseSesion.conSesion);
}

List<Override> _over(_RepoFalso repo, {bool conUsuario = false}) => [
      tareasRepositorioProvider.overrideWithValue(repo),
      estadoSesionProvider.overrideWith(conUsuario ? _SesionConUsuario.new : _SesionFija.new),
      serviciosProvider.overrideWithValue(serviciosFalsos()),
    ];

Widget _app(Widget home, List<Override> overrides) => ProviderScope(
      overrides: overrides,
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('es'),
        home: home,
      ),
    );

TareaOutlook _tarea(int id, {String estado = 'no_iniciada', int version = 1, String? fecha, bool vencida = false, String? motivo, String prioridad = 'normal'}) =>
    TareaOutlook.fromJson(_t(id, estado: estado, version: version, fecha: fecha, vencida: vencida, motivo: motivo, prioridad: prioridad));

ApiException _conflicto(int actual) => ApiException('Otra persona la ha cambiado', codigo: 'version_obsoleta', status: 409, versionActual: actual);

void main() {
  group('dominio', () {
    test('TiempoDeTarea calcula con la hora del servidor, no con la del móvil', () {
      final ahoraLocal = DateTime(2030, 1, 1, 12);
      final marcha = TiempoDeTarea.desdeJson({'ahora': '2026-10-26T10:10:00', 'cronometro': {'id': 4, 'estado': 'en_curso', 'inicio_en': '2026-10-26T10:00:00', 'segundos_pausados': 60}}, ahoraLocal: ahoraLocal);
      expect(marcha.cronometro!.segundos(ahoraLocal), 540);
      expect(marcha.cronometro!.segundos(ahoraLocal.add(const Duration(seconds: 30))), 570, reason: 'sigue contando con el reloj del móvil desde que se pidió');
      final pausa = TiempoDeTarea.desdeJson({'cronometro': {'id': 4, 'estado': 'pausada', 'segundos_trabajados_congelado': 125}}, ahoraLocal: ahoraLocal);
      expect(pausa.cronometro!.segundos(ahoraLocal.add(const Duration(hours: 1))), 125);
      expect(reloj(3725), '1:02:05');
    });

    test('duracionCorta como la web', () {
      expect([duracionCorta(90), duracionCorta(120), duracionCorta(45), duracionCorta(65)], ['1 h 30', '2 h', '45 min', '1 h 05']);
    });

    test('un estado nuevo del servidor no rompe a una app antigua', () {
      expect(EstadoTarea.desde('en_progreso'), EstadoTarea.enProgreso);
      expect(EstadoTarea.desde('algo_nuevo'), EstadoTarea.desconocido);
      expect(EstadoTarea.desde(null), EstadoTarea.desconocido);
      expect(EstadoTarea.completada.abierta, false);
      expect(EstadoTarea.esperando.pideMotivo, true);
      expect(EstadoTarea.elegibles, isNot(contains(EstadoTarea.enRevision))); // lo gestiona el flujo de revisión
    });

    test('subtarea desde la API', () {
      final s = Subtarea.desdeJson({'id': 4, 'asunto': 'Pedir certificado', 'estado': 'completada'});
      expect((s.id, s.asunto, s.estado.abierta), (4, 'Pedir certificado', false));
    });
  });

  group('TareasRepositorio (lo que viaja por la red)', () {
    test('listar pasa ámbito, estado, búsqueda y paginación; sin texto no manda q', () async {
      final c = _ClienteFalso({'GET /tareas-outlook': [_t(1), _t(2)]});
      final r = await TareasRepositorio(c).listar(ambito: 'asignadas', estado: 'esperando', q: '  acme ', limit: 30, offset: 60);
      expect(r.map((t) => t.id), [1, 2]);
      expect(c.llamadas.single.consulta, {'ambito': 'asignadas', 'estado': 'esperando', 'q': 'acme', 'limit': 30, 'offset': 60});
      await TareasRepositorio(c).listar(q: '  ');
      expect(c.llamadas.last.consulta!.containsKey('q'), false);
    });

    test('crear manda asunto limpio y fecha; editar solo lo que cambia', () async {
      final c = _ClienteFalso({'POST /tareas-outlook': _t(7), 'PUT /tareas-outlook/7': _t(7)});
      final repo = TareasRepositorio(c);
      await repo.crear(asunto: ' Llamar ', fechaVencimiento: '2026-10-30', prioridad: PrioridadTarea.alta);
      expect(c.llamadas.last.cuerpo, {'asunto': 'Llamar', 'fecha_vencimiento': '2026-10-30', 'prioridad': 'alta'});
      await repo.editar(7, asunto: 'Nuevo');
      expect(c.llamadas.last.cuerpo, {'asunto': 'Nuevo'});
    });

    test('transicionar lleva estado, motivo y versión (para detectar conflictos)', () async {
      final c = _ClienteFalso({'POST /tareas-outlook/7/transiciones': _t(7, estado: 'esperando')});
      await TareasRepositorio(c).transicionar(7, EstadoTarea.esperando, motivo: 'Falta el certificado', version: 4);
      expect(c.llamadas.single.cuerpo, {'estado': 'esperando', 'motivo': 'Falta el certificado', 'version': 4});
      await TareasRepositorio(c).transicionar(7, EstadoTarea.completada);
      expect(c.llamadas.last.cuerpo, {'estado': 'completada'});
    });

    test('subtareas, checklist y comentarios', () async {
      final c = _ClienteFalso({
        'GET /tareas-outlook/7/subtareas': {'subtareas': [{'id': 8, 'asunto': 'A', 'estado': 'completada'}, {'id': 9, 'asunto': 'B', 'estado': 'no_iniciada'}], 'progreso': {}},
        'POST /tareas-outlook/7/subtareas': _t(10),
        'POST /tareas-outlook/7/checklist': {'id': 1},
        'POST /checklist/3/alternar': null,
        'POST /tareas-outlook/7/comentarios': {'id': 1, 'tarea_id': 7},
      });
      final repo = TareasRepositorio(c);
      final s = await repo.subtareas(7);
      expect((s.subtareas.length, s.hechas), (2, 1));
      await repo.crearSubtarea(7, ' Pedir ');
      expect(c.llamadas.last.cuerpo, {'asunto': 'Pedir'});
      await repo.agregarItem(7, ' Revisar IVA ');
      expect(c.llamadas.last.cuerpo, {'texto': 'Revisar IVA'});
      await repo.alternarItem(3);
      expect(c.llamadas.last.ruta, '/checklist/3/alternar');
      await repo.comentar(7, ' hola @ana ');
      expect(c.llamadas.last.cuerpo, {'texto': 'hola @ana'});
    });

    test('un adjunto sube como multipart en el campo «adjunto»', () async {
      final c = _ClienteFalso({'POST /tareas-outlook/7/adjuntos': <dynamic>[]});
      await TareasRepositorio(c).subirAdjunto(7, MultipartFile.fromBytes([1, 2, 3], filename: 'foto.jpg'));
      final ll = c.llamadas.single;
      expect(ll.multipart, true);
      expect((ll.cuerpo as Map).keys, ['adjunto']);
    });
  });

  group('lista (controlador)', () {
    ProviderContainer montar(_RepoFalso repo) {
      final c = ProviderContainer(overrides: _over(repo));
      addTearDown(c.dispose);
      return c;
    }

    Future<void> asentar() => Future<void>.delayed(Duration.zero);

    test('carga la primera página y pide más al llegar al final', () async {
      final repo = _RepoFalso()
        ..paginas = (a, e, q, o) => o == 0 ? [for (var i = 1; i <= 30; i++) _tarea(i)] : [for (var i = 31; i <= 35; i++) _tarea(i)];
      final c = montar(repo);
      c.read(tareasListaProvider);
      await asentar();
      expect(c.read(tareasListaProvider).tareas.length, 30);
      expect(c.read(tareasListaProvider).hayMas, true);
      await c.read(tareasListaProvider.notifier).masResultados();
      expect(c.read(tareasListaProvider).tareas.length, 35);
      expect(c.read(tareasListaProvider).hayMas, false); // página corta: no hay más
      expect(repo.registro, ['listar:propias:-:-:0', 'listar:propias:-:-:30']);
      await c.read(tareasListaProvider.notifier).masResultados(); // ya no pide
      expect(repo.registro.length, 2);
    });

    test('cambiar ámbito, estado o búsqueda vuelve a empezar con ese filtro', () async {
      final repo = _RepoFalso()..paginas = (a, e, q, o) => [_tarea(1)];
      final c = montar(repo);
      c.read(tareasListaProvider);
      await asentar();
      final n = c.read(tareasListaProvider.notifier);
      await n.cambiarAmbito('asignadas');
      await n.cambiarEstado(EstadoTarea.esperando);
      await n.buscar('  acme ');
      expect(repo.registro.last, 'listar:asignadas:esperando:acme:0');
      await n.cambiarEstado(null);
      expect(repo.registro.last, 'listar:asignadas:-:acme:0');
    });

    test('completar usa la versión y reemplaza la fila; un conflicto refresca esa tarea y relanza', () async {
      final repo = _RepoFalso()
        ..paginas = ((a, e, q, o) => [_tarea(1, version: 3), _tarea(2, version: 5)])
        ..tareas = {2: _tarea(2, estado: 'en_progreso', version: 6)};
      final c = montar(repo);
      c.read(tareasListaProvider);
      await asentar();
      final n = c.read(tareasListaProvider.notifier);
      await n.completar(c.read(tareasListaProvider).tareas[0]);
      expect(repo.registro, contains('transicionar:1:completada:-:3'));
      expect(c.read(tareasListaProvider).tareas[0].estado, 'completada');

      repo.alTransicionar = (id, e, m, v) async => throw _conflicto(6);
      await expectLater(n.completar(c.read(tareasListaProvider).tareas[1]), throwsA(isA<ApiException>()));
      expect(c.read(tareasListaProvider).tareas[1].estado, 'en_progreso'); // se enseña lo que hay ahora
    });

    test('deshacer una finalización ya enviada vuelve al estado anterior con la versión de ahora', () async {
      final repo = _RepoFalso()..paginas = ((a, e, q, o) => [_tarea(1, estado: 'en_progreso', version: 3)]);
      final c = montar(repo);
      c.read(tareasListaProvider);
      await asentar();
      final n = c.read(tareasListaProvider.notifier);
      final antes = c.read(tareasListaProvider).tareas[0];
      await n.completar(antes);
      expect(c.read(tareasListaProvider).tareas[0].estado, 'completada');
      await n.deshacerEstado(antes, encolada: false);
      expect(repo.registro, containsAllInOrder(['transicionar:1:completada:-:3', 'transicionar:1:en_progreso:-:4']));
      expect(c.read(tareasListaProvider).tareas[0].estado, 'en_progreso');
    });

    test('deshacer un conflicto no pisa nada: relanza y deja lo que hay', () async {
      final repo = _RepoFalso()..paginas = ((a, e, q, o) => [_tarea(1, version: 3)]);
      final c = montar(repo);
      c.read(tareasListaProvider);
      await asentar();
      final n = c.read(tareasListaProvider.notifier);
      final antes = c.read(tareasListaProvider).tareas[0];
      await n.completar(antes);
      repo.alTransicionar = (id, e, m, v) async => throw _conflicto(9);
      await expectLater(n.deshacerEstado(antes, encolada: false), throwsA(isA<ApiException>()));
      expect(c.read(tareasListaProvider).tareas[0].estado, 'completada');
    });

    test('deshacer algo que sigue en la cola solo lo retira de la cola, sin hablar con el servidor', () async {
      sqfliteFfiInit();
      final cola = ColaEscritura(abrir: () => databaseFactoryFfi.openDatabase(inMemoryDatabasePath, options: OpenDatabaseOptions(version: 1, onCreate: ColaEscritura.crearEsquema, singleInstance: false)));
      await cola.encolar(metodo: 'POST', ruta: '/tareas-outlook/1/transiciones', cuerpo: {'estado': 'completada', 'version': 3}, clave: 'k1', usuarioId: 1, despachoId: '0', entidad: 'tarea:1', tipo: 'tarea.estado', descripcion: 'Completar');
      final repo = _RepoFalso()..paginas = ((a, e, q, o) => [_tarea(1, version: 3)]);
      final c = ProviderContainer(overrides: [tareasRepositorioProvider.overrideWithValue(repo), estadoSesionProvider.overrideWith(_SesionConUsuario.new), colaEscrituraProvider.overrideWithValue(cola)]);
      addTearDown(c.dispose);
      c.read(tareasListaProvider);
      while (c.read(tareasListaProvider).cargando || c.read(tareasListaProvider).tareas.isEmpty) {
        await Future<void>.delayed(const Duration(milliseconds: 10)); // la lista lee también la cola (SQLite de verdad)
      }
      expect(c.read(tareasListaProvider).tareas[0].estado, 'completada', reason: 'la lista enseña lo pendiente como hecho');
      final antes = _tarea(1, version: 3);
      expect(await cola.contar(1, '0'), 1);
      await c.read(tareasListaProvider.notifier).deshacerEstado(antes, encolada: true);
      expect(await cola.contar(1, '0'), 0);
      expect(repo.registro.where((r) => r.startsWith('transicionar')), isEmpty);
      expect(c.read(tareasListaProvider).tareas[0].estado, 'no_iniciada');
    });

    test('por defecto oculta las completadas (como la web) y los filtros nuevos viajan al servidor', () async {
      final repo = _RepoFalso()..paginas = (a, e, q, o) => [_tarea(1)];
      final c = montar(repo);
      c.read(tareasListaProvider);
      await asentar();
      expect(repo.filtrosVistos.last, '-|-|true');
      final n = c.read(tareasListaProvider.notifier);
      await n.cambiarFiltros(prioridad: PrioridadTarea.alta, categoria: 'Fiscal', completadas: true);
      expect(repo.filtrosVistos.last, 'alta|Fiscal|false');
      expect(c.read(tareasListaProvider).filtrosActivos, 3);
      await n.limpiarFiltros();
      expect(repo.filtrosVistos.last, '-|-|true');
      expect(c.read(tareasListaProvider).filtrosActivos, 0);
    });

    test('una vista guardada pone los mismos filtros que en la web, y los filtros actuales se guardan con las mismas claves', () async {
      final repo = _RepoFalso()..paginas = (a, e, q, o) => [_tarea(1)];
      final c = montar(repo);
      c.read(tareasListaProvider);
      await asentar();
      final n = c.read(tareasListaProvider.notifier);
      await n.aplicarVista({'vista': 'mias', 'estado': 'en_progreso', 'prioridad': 'alta', 'q': 'iva', 'completadas': '1'});
      expect(repo.registro.last, 'listar:propias:en_progreso:iva:0');
      expect(repo.filtrosVistos.last, 'alta|-|false');
      expect(c.read(tareasListaProvider).filtrosDeVista, {'vista': 'mias', 'estado': 'en_progreso', 'prioridad': 'alta', 'q': 'iva', 'completadas': '1'});
      await n.aplicarVista({}); // sin «vista» = mías y asignadas a mí, como en la web
      expect(c.read(tareasListaProvider).ambito, 'todas');
      expect(c.read(tareasListaProvider).filtrosDeVista, isEmpty);
    });

    test('selección múltiple: acción en lote sobre las marcadas, y lo creado sin conexión no se puede marcar', () async {
      final repo = _RepoFalso()
        ..paginas = ((a, e, q, o) => [_tarea(1), _tarea(2), _tarea(3)])
        ..resultadoLote = (ok: 2, fallos: 0);
      final c = montar(repo);
      c.read(tareasListaProvider);
      await asentar();
      final n = c.read(tareasListaProvider.notifier);
      n.alternarSeleccion(1);
      n.alternarSeleccion(3);
      n.alternarSeleccion(-5);
      expect(c.read(tareasListaProvider).seleccion, {1, 3});
      n.alternarSeleccion(3);
      n.alternarSeleccion(2);
      final r = await n.accionLote('prioridad', valor: 'alta');
      expect(r.ok, 2);
      expect(repo.registro, contains('lote:prioridad:alta:1,2'));
      expect(c.read(tareasListaProvider).seleccion, isEmpty);
      expect(repo.registro.last, startsWith('listar:'), reason: 'tras la acción se vuelve a pedir la lista');
      n.seleccionarTodas();
      expect(c.read(tareasListaProvider).seleccion, {1, 2, 3});
      n.limpiarSeleccion();
      expect(c.read(tareasListaProvider).seleccion, isEmpty);
    });

    test('eliminar manda a la papelera solo lo que se puede, quita esas filas y se puede restaurar', () async {
      final repo = _RepoFalso()
        ..paginas = ((a, e, q, o) => [_tarea(1), _tarea(2)])
        ..noEliminables = {2};
      final c = montar(repo);
      c.read(tareasListaProvider);
      await asentar();
      final n = c.read(tareasListaProvider.notifier);
      final hechas = await n.eliminar([1, 2]);
      expect(hechas, [1]);
      expect(c.read(tareasListaProvider).tareas.map((t) => t.id), [2]);
      await n.restaurar(hechas);
      expect(repo.registro, containsAllInOrder(['eliminar:1', 'restaurar:1']));
      expect(c.read(tareasListaProvider).tareas.map((t) => t.id), [1, 2], reason: 'tras restaurar vuelve a pedirse la lista');
    });

    test('una tarea nueva entra la primera, salvo en ámbitos ajenos o con otro filtro de estado', () async {
      final repo = _RepoFalso()..paginas = (a, e, q, o) => [_tarea(1)];
      final c = montar(repo);
      c.read(tareasListaProvider);
      await asentar();
      final n = c.read(tareasListaProvider.notifier);
      await n.crear('Llamar', fechaVencimiento: '2026-10-30');
      expect(c.read(tareasListaProvider).tareas.first.id, 999);
      expect(repo.registro, contains('crear:Llamar:2026-10-30'));
      await n.cambiarEstado(EstadoTarea.completada);
      await n.crear('Otra');
      expect(c.read(tareasListaProvider).tareas.any((t) => t.id == 999), false);
    });

    test('un error sin datos queda en el estado para poder reintentar', () async {
      final repo = _RepoFalso()..paginas = (a, e, q, o) => throw ApiException('sin red', esDeConexion: true);
      final c = montar(repo);
      c.read(tareasListaProvider);
      await asentar();
      expect(c.read(tareasListaProvider).error, isA<ApiException>());
      expect(c.read(tareasListaProvider).cargando, false);
    });
  });

  group('pantalla de lista', () {
    testWidgets('enseña las tareas con fecha, estado y vencida; completar desde la casilla', (t) async {
      final repo = _RepoFalso()
        ..paginas = (a, e, q, o) => [
              _tarea(1, fecha: '2026-10-20', vencida: true, prioridad: 'alta'),
              _tarea(2, estado: 'en_progreso', fecha: '2026-10-28'),
              _tarea(3, estado: 'completada'),
            ];
      await t.pumpWidget(_app(const TareasScreen(), _over(repo)));
      await t.pumpAndSettle();
      expect(find.text('Tarea 1'), findsOneWidget);
      expect(find.textContaining('Vencida'), findsOneWidget);
      expect(find.textContaining('En curso'), findsWidgets);
      await t.tap(find.byType(Checkbox).first);
      await t.pumpAndSettle();
      expect(repo.registro, contains('transicionar:1:completada:-:1'));
    });

    testWidgets('con la letra al 160 % (accesibilidad) las pantallas de tareas no se desbordan', (t) async {
      final repo = _RepoFalso()
        ..paginas = ((a, e, q, o) => [TareaOutlook.fromJson({..._t(1, fecha: '2026-10-20', vencida: true, prioridad: 'alta'), 'asunto': 'Presentar el modelo 303 trimestral de Acme Sociedad Limitada', 'categoria_nombre': 'IVA y otros impuestos indirectos', 'n_comentarios': 3, 'checklist_total': 4, 'checklist_hechas': 2, 'rol': 'asignada'})])
        ..diaFalso = {'vencidas': [TareaOutlook.fromJson({..._t(1, vencida: true), 'asunto': 'Presentar el modelo 303 trimestral de Acme Sociedad Limitada'})]};
      await t.binding.setSurfaceSize(const Size(360, 780)); // un móvil pequeño
      addTearDown(() => t.binding.setSurfaceSize(null));
      await t.pumpWidget(ProviderScope(
        overrides: _over(repo),
        child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: const Locale('es'),
          theme: AppTheme.light,
          builder: (c, h) => MediaQuery(data: MediaQuery.of(c).copyWith(textScaler: const TextScaler.linear(1.6)), child: h!),
          home: const TareasInicio(),
        ),
      ));
      await t.pumpAndSettle();
      expect(t.takeException(), isNull, reason: 'Lista');
      await t.tap(find.text('Mi día'));
      await t.pumpAndSettle();
      expect(t.takeException(), isNull, reason: 'Mi día');
      await t.tap(find.text('Tablero'));
      await t.pumpAndSettle();
      expect(t.takeException(), isNull, reason: 'Tablero');
    });

    testWidgets('cada fila enseña lo mismo que la web: proyecto, comentarios, checklist, espera y quién la asignó', (t) async {
      final repo = _RepoFalso()
        ..paginas = (a, e, q, o) => [
              TareaOutlook.fromJson({..._t(1), 'categoria_nombre': 'IVA', 'n_comentarios': 3, 'checklist_total': 4, 'checklist_hechas': 1, 'bloqueos': 2, 'rol': 'asignada'}),
            ];
      await t.pumpWidget(_app(const TareasScreen(), _over(repo)));
      await t.pumpAndSettle();
      expect(find.text('IVA'), findsOneWidget);
      expect(find.text('Lista 1/4'), findsOneWidget);
      expect(find.text('Espera a 2 tareas'), findsOneWidget);
      expect(find.text('Asignada a ti'), findsOneWidget);
      expect(find.text('3'), findsOneWidget); // el número; «3 comentarios» va como etiqueta para el lector de pantalla
    });

    testWidgets('pulsación larga marca, aparece la barra de selección y «Completar» manda el lote', (t) async {
      final repo = _RepoFalso()
        ..paginas = ((a, e, q, o) => [_tarea(1), _tarea(2)])
        ..resultadoLote = (ok: 2, fallos: 0);
      await t.pumpWidget(_app(const TareasScreen(), _over(repo)));
      await t.pumpAndSettle();
      await t.longPress(find.text('Tarea 1'));
      await t.pumpAndSettle();
      expect(find.text('1 seleccionada'), findsOneWidget);
      await t.tap(find.text('Tarea 2')); // en selección, tocar marca en vez de abrir
      await t.pumpAndSettle();
      expect(find.text('2 seleccionadas'), findsOneWidget);
      await t.tap(find.byTooltip('Completar'));
      await t.pumpAndSettle();
      expect(repo.registro, contains('lote:completar:-:1,2'));
      expect(find.text('2 tareas actualizadas'), findsOneWidget);
      expect(find.textContaining('seleccionada'), findsNothing);
    });

    testWidgets('el panel de filtros aplica prioridad y «ver completadas», y las vistas guardadas se pueden elegir', (t) async {
      final repo = _RepoFalso()
        ..paginas = ((a, e, q, o) => [_tarea(1)])
        ..vistasGuardadas = [const Vista(id: 7, nombre: 'Mis vencidas de IVA', filtros: {'prioridad': 'alta', 'vista': 'mias'}, mia: true)];
      await t.pumpWidget(_app(const TareasScreen(), _over(repo)));
      await t.pumpAndSettle();
      await t.tap(find.text('Filtros'));
      await t.pumpAndSettle();
      await t.tap(find.text('Alta'));
      await t.tap(find.text('Ver también completadas'));
      await t.tap(find.text('Aplicar'));
      await t.pumpAndSettle();
      expect(repo.filtrosVistos.last, 'alta|-|false');
      expect(find.text('Filtros (2)'), findsOneWidget);
      await t.tap(find.text('Vistas guardadas'));
      await t.pumpAndSettle();
      await t.tap(find.text('Mis vencidas de IVA'));
      await t.pumpAndSettle();
      expect(repo.filtrosVistos.last, 'alta|-|true');
      expect(find.text('Filtros (1)'), findsOneWidget, reason: 'la vista solo pedía prioridad alta, sin completadas');
    });

    testWidgets('si no se puede completar, enseña el motivo del servidor', (t) async {
      final repo = _RepoFalso()
        ..paginas = ((a, e, q, o) => [_tarea(1)])
        ..alTransicionar = (id, e, m, v) async => throw ApiException('Tiene subtareas abiertas', codigo: 'subtareas_abiertas', status: 409);
      await t.pumpWidget(_app(const TareasScreen(), _over(repo)));
      await t.pumpAndSettle();
      await t.tap(find.byType(Checkbox).first);
      await t.pumpAndSettle();
      expect(find.text('Tiene subtareas abiertas'), findsOneWidget);
    });

    testWidgets('los filtros recargan; el alta rápida crea con la fecha elegida', (t) async {
      final repo = _RepoFalso()..paginas = (a, e, q, o) => [];
      await t.pumpWidget(_app(const TareasScreen(), _over(repo)));
      await t.pumpAndSettle();
      expect(find.text('No hay tareas aquí.'), findsOneWidget);
      await t.tap(find.text('Mías')); // el ámbito y el estado son menús desplegables en forma de píldora
      await t.pumpAndSettle();
      await t.tap(find.text('Asignadas').last);
      await t.pumpAndSettle();
      await t.tap(find.text('Estado'));
      await t.pumpAndSettle();
      await t.tap(find.text('Esperando').last);
      await t.pumpAndSettle();
      expect(repo.registro.last, 'listar:asignadas:esperando:-:0');
      await t.enterText(find.byType(TextField), 'Preparar el 303');
      await t.tap(find.byTooltip('Nueva tarea'));
      await t.pumpAndSettle();
      expect(repo.registro.last, 'crear:Preparar el 303:-');
    });
  });

  group('Mi día y tablero', () {
    testWidgets('la pestaña abre en la lista y el selector cambia entre Mi día, Lista y Tablero', (t) async {
      final repo = _RepoFalso()..paginas = ((a, e, q, o) => [_tarea(1)]);
      await t.pumpWidget(_app(const TareasInicio(), _over(repo)));
      await t.pumpAndSettle();
      expect(find.text('Tarea 1'), findsOneWidget);
      await t.tap(find.text('Mi día'));
      await t.pumpAndSettle();
      expect(find.text('No tienes nada pendiente para hoy. Buen momento para adelantar trabajo.'), findsOneWidget);
      await t.tap(find.text('Tablero'));
      await t.pumpAndSettle();
      expect(find.text('Nada aquí'), findsOneWidget);
      await t.tap(find.text('Lista'));
      await t.pumpAndSettle();
      expect(find.text('Tarea 1'), findsOneWidget);
    });

    testWidgets('«Mi día» enseña las secciones de la web con su cuenta; completar saca la tarea y se puede deshacer', (t) async {
      final repo = _RepoFalso()
        ..diaFalso = {
          'vencidas': [_tarea(1, fecha: '2026-10-20', vencida: true)],
          'hoy': [_tarea(2, fecha: '2026-10-26')],
          'asignadas': [for (var i = 3; i < 36; i++) _tarea(i)],
        };
      await t.pumpWidget(_app(const TareasInicio(), _over(repo)));
      await t.pumpAndSettle();
      await t.tap(find.text('Mi día'));
      await t.pumpAndSettle();
      expect(find.text('Vencidas'), findsOneWidget);
      expect(find.text('Vencen hoy'), findsOneWidget);
      expect(find.text('Asignadas a mí'), findsOneWidget);
      expect(find.text('En progreso'), findsNothing, reason: 'las secciones vacías no salen');
      expect(find.text('Compartidas conmigo'), findsNothing);
      expect(find.text('Tarea 1'), findsOneWidget);
      await t.tap(find.byType(Checkbox).first);
      await t.pumpAndSettle();
      expect(repo.registro, contains('transicionar:1:completada:-:1'));
      expect(find.text('Tarea 1'), findsNothing);
      expect(find.text('Tarea completada'), findsOneWidget);
      await t.tap(find.text('Deshacer'));
      await t.pumpAndSettle();
      expect(repo.registro.last, startsWith('transicionar:1:no_iniciada'));
    });

    testWidgets('«Mi día» corta cada sección en 30 y ofrece ver las restantes', (t) async {
      final repo = _RepoFalso()..diaFalso = {'asignadas': [for (var i = 1; i <= 35; i++) _tarea(i)]};
      await t.pumpWidget(_app(const TareasInicio(), _over(repo)));
      await t.pumpAndSettle();
      await t.tap(find.text('Mi día'));
      await t.pumpAndSettle();
      expect(find.text('Ver las 5 restantes'), findsOneWidget);
      await t.ensureVisible(find.text('Ver las 5 restantes'));
      await t.pumpAndSettle();
      await t.tap(find.text('Ver las 5 restantes'));
      await t.pumpAndSettle();
      expect(find.text('Ver las 5 restantes'), findsNothing);
    });

    testWidgets('el tablero tiene una columna por estado con su cuenta; mover una tarjeta la pasa a otra columna y no ofrece «En revisión»', (t) async {
      final repo = _RepoFalso()
        ..tableroFalso = {
          'no_iniciada': [_tarea(1), _tarea(2)],
          'en_progreso': [_tarea(3, estado: 'en_progreso')],
        };
      await t.pumpWidget(_app(const TareasInicio(), _over(repo)));
      await t.pumpAndSettle();
      await t.tap(find.text('Tablero'));
      await t.pumpAndSettle();
      expect(find.text('Sin empezar (2)'), findsOneWidget);
      expect(find.text('En curso (1)'), findsOneWidget);
      await t.tap(find.byTooltip('Mover a').first);
      await t.pumpAndSettle();
      expect(find.text('En revisión'), findsNothing);
      await t.tap(find.text('Completada').last);
      await t.pumpAndSettle();
      expect(repo.registro, contains('transicionar:1:completada:-:1'));
      expect(find.text('Sin empezar (1)'), findsOneWidget);
      expect(find.text('Completada (1)'), findsOneWidget);
    });
  });

  // Capturas de las pantallas con el tema y las fuentes reales (para mirar el diseño sin un móvil): solo con CAPTURAS=<carpeta>.
  group('capturas del diseño', () {
    final carpeta = Platform.environment['CAPTURAS'];

    setUpAll(() async {
      if (carpeta == null) return;
      Directory(carpeta).createSync(recursive: true);
      Future<void> fuente(String familia, List<String> rutas) async {
        final f = FontLoader(familia);
        for (final r in rutas) {
          f.addFont(Future.value(ByteData.sublistView(File(r).readAsBytesSync())));
        }
        await f.load();
      }

      await fuente('Manrope', ['assets/fonts/Manrope-Regular.ttf', 'assets/fonts/Manrope-Medium.ttf', 'assets/fonts/Manrope-SemiBold.ttf', 'assets/fonts/Manrope-Bold.ttf']);
      await fuente('Inter', ['assets/fonts/Inter-Regular.ttf', 'assets/fonts/Inter-SemiBold.ttf']);
      final sdk = Platform.environment['FLUTTER_ROOT'] ?? '/home/guilda/flutter';
      await fuente('MaterialIcons', ['$sdk/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf']);
    });

    Widget conTema(Widget home, List<Override> overrides, {required bool oscuro, required GlobalKey clave}) => ProviderScope(
          overrides: overrides,
          child: RepaintBoundary(
            key: clave,
            child: MaterialApp(
              debugShowCheckedModeBanner: false,
              localizationsDelegates: AppLocalizations.localizationsDelegates,
              supportedLocales: AppLocalizations.supportedLocales,
              locale: const Locale('es'),
              theme: AppTheme.light,
              darkTheme: AppTheme.dark,
              themeMode: oscuro ? ThemeMode.dark : ThemeMode.light,
              home: home,
            ),
          ),
        );

    Future<void> capturar(WidgetTester t, GlobalKey clave, String nombre) async {
      final limite = t.renderObject<RenderRepaintBoundary>(find.byKey(clave));
      final bytes = await t.runAsync(() async {
        final img = await limite.toImage(pixelRatio: 2);
        return (await img.toByteData(format: ui.ImageByteFormat.png))!;
      });
      File('$carpeta/$nombre.png').writeAsBytesSync(bytes!.buffer.asUint8List());
    }

    String iso(DateTime d) => '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

    _RepoFalso repoDeEjemplo() {
      final hoy = DateTime.now();
      final ayer = iso(hoy.subtract(const Duration(days: 1)));
      final tareas = [
        TareaOutlook.fromJson({..._t(1, fecha: ayer, vencida: true, prioridad: 'alta'), 'asunto': 'Presentar el 303 de Acme SL', 'categoria_nombre': 'IVA', 'n_comentarios': 3, 'checklist_total': 4, 'checklist_hechas': 2}),
        TareaOutlook.fromJson({..._t(2, estado: 'en_progreso', fecha: iso(hoy)), 'asunto': 'Conciliar el banco de octubre', 'categoria_nombre': 'Contabilidad', 'rol': 'asignada'}),
        TareaOutlook.fromJson({..._t(3, estado: 'esperando', motivo: 'Falta la factura'), 'asunto': 'Declaración de la renta de Beta SA', 'bloqueos': 1}),
        TareaOutlook.fromJson({..._t(4, fecha: iso(hoy.add(const Duration(days: 3)))), 'asunto': 'Llamar a la gestoría laboral'}),
        TareaOutlook.fromJson({..._t(5, estado: 'completada'), 'asunto': 'Enviar el modelo 130'}),
      ];
      return _RepoFalso()
        ..paginas = ((a, e, q, o) => tareas)
        ..diaFalso = {'vencidas': [tareas[0]], 'hoy': [tareas[1]], 'en_progreso': [], 'asignadas': [tareas[3]], 'compartidas': []}
        ..tableroFalso = {'no_iniciada': [tareas[0], tareas[3]], 'en_progreso': [tareas[1]], 'esperando': [tareas[2]], 'completada': [tareas[4]]}
        ..tareas = {1: tareas[0]}
        ..subs = const [Subtarea(8, 'Pedir certificado', EstadoTarea.completada), Subtarea(9, 'Revisar el IVA', EstadoTarea.noIniciada)]
        ..check = [ChecklistItem.fromJson({'id': 3, 'texto': 'Comprobar el NIF', 'hecha': 1}), ChecklistItem.fromJson({'id': 4, 'texto': 'Cuadrar con contabilidad', 'hecha': 0})]
        ..coments = [ComentarioTarea.fromJson({'id': 1, 'texto': 'Ya tengo los datos del banco', 'creado_en': '2026-10-24T09:30'})];
    }

    for (final (nombre, vista, abrir) in [('tableta_lista', VistaTareas.lista, true), ('tableta_tablero', VistaTareas.tablero, false)]) {
      testWidgets('captura $nombre', (t) async {
        if (carpeta == null) return;
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1640, 1180); // ancho: con lista, ficha y el panel del asistente
        t.view.devicePixelRatio = 1;
        addTearDown(t.view.reset);
        await t.pumpWidget(conTema(const TareasInicio(), _over(repoDeEjemplo()), oscuro: false, clave: clave));
        await t.pumpAndSettle();
        final ref = ProviderScope.containerOf(t.element(find.byType(TareasInicio)));
        ref.read(vistaTareasProvider.notifier).elegir(vista);
        await t.pumpAndSettle();
        if (abrir) {
          ref.read(tareaAbiertaProvider.notifier).abrir(1);
          await t.pumpAndSettle();
        }
        await capturar(t, clave, nombre);
      });
    }

    for (final oscuro in [false, true]) {
      final sufijo = oscuro ? 'oscuro' : 'claro';
      for (final (nombre, vista) in [('lista', VistaTareas.lista), ('mi_dia', VistaTareas.miDia), ('tablero', VistaTareas.tablero)]) {
        testWidgets('captura $nombre $sufijo', (t) async {
          if (carpeta == null) return;
          final clave = GlobalKey();
          t.view.physicalSize = const Size(1170, 2532);
          t.view.devicePixelRatio = 3;
          addTearDown(t.view.reset);
          final repo = repoDeEjemplo();
          await t.pumpWidget(conTema(const TareasInicio(), _over(repo), oscuro: oscuro, clave: clave));
          await t.pumpAndSettle();
          final ref = ProviderScope.containerOf(t.element(find.byType(TareasInicio)));
          ref.read(vistaTareasProvider.notifier).elegir(vista);
          await t.pumpAndSettle();
          await capturar(t, clave, '${nombre}_$sufijo');
        });
      }
      testWidgets('captura lista violeta $sufijo', (t) async {
        if (carpeta == null) return;
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 2532);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        await t.pumpWidget(ProviderScope(
          overrides: _over(repoDeEjemplo()),
          child: RepaintBoundary(
            key: clave,
            child: MaterialApp(
              debugShowCheckedModeBanner: false,
              localizationsDelegates: AppLocalizations.localizationsDelegates,
              supportedLocales: AppLocalizations.supportedLocales,
              locale: const Locale('es'),
              theme: AppTheme.claro('violeta'),
              darkTheme: AppTheme.oscuro('violeta'),
              themeMode: oscuro ? ThemeMode.dark : ThemeMode.light,
              home: const TareasInicio(),
            ),
          ),
        ));
        await t.pumpAndSettle();
        await capturar(t, clave, 'lista_violeta_$sufijo');
      });
      testWidgets('captura hoy $sufijo', (t) async {
        if (carpeta == null) return;
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 2532);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        await t.pumpWidget(conTema(const HoyScreen(), [..._over(_RepoFalso()), hoyProvider.overrideWith(_HoyFalso.new)], oscuro: oscuro, clave: clave));
        await t.pumpAndSettle();
        await capturar(t, clave, 'hoy_$sufijo');
      });
      testWidgets('captura ficha $sufijo', (t) async {
        if (carpeta == null) return;
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 3400);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        await t.pumpWidget(conTema(const TareaDetalleScreen(tareaId: 1), _over(repoDeEjemplo()), oscuro: oscuro, clave: clave));
        await t.pumpAndSettle();
        await capturar(t, clave, 'ficha_$sufijo');
      });
    }
  });

  group('accesibilidad de las tareas', () {
    for (final oscuro in [false, true]) {
      for (final (nombre, vista) in [('Lista', VistaTareas.lista), ('Mi día', VistaTareas.miDia), ('Tablero', VistaTareas.tablero)]) {
        testWidgets('$nombre (${oscuro ? 'oscuro' : 'claro'}): zonas táctiles, nombres para el lector de pantalla y contraste', (t) async {
          final hoy = DateTime.now();
          final tareas = [
            TareaOutlook.fromJson({..._t(1, vencida: true, prioridad: 'alta', fecha: '${hoy.year}-${hoy.month.toString().padLeft(2, '0')}-${hoy.day.toString().padLeft(2, '0')}'), 'asunto': 'Presentar el 303', 'categoria_nombre': 'IVA', 'n_comentarios': 2, 'checklist_total': 3, 'checklist_hechas': 1}),
            TareaOutlook.fromJson({..._t(2, estado: 'en_progreso'), 'asunto': 'Conciliar el banco', 'rol': 'asignada'}),
          ];
          final repo = _RepoFalso()
            ..paginas = ((a, e, q, o) => tareas)
            ..diaFalso = {'vencidas': [tareas[0]], 'asignadas': [tareas[1]]}
            ..tableroFalso = {'no_iniciada': [tareas[0]], 'en_progreso': [tareas[1]]};
          await t.pumpWidget(ProviderScope(
            overrides: _over(repo),
            child: MaterialApp(
              localizationsDelegates: AppLocalizations.localizationsDelegates,
              supportedLocales: AppLocalizations.supportedLocales,
              locale: const Locale('es'),
              theme: AppTheme.light,
              darkTheme: AppTheme.dark,
              themeMode: oscuro ? ThemeMode.dark : ThemeMode.light,
              home: const TareasInicio(),
            ),
          ));
          await t.pumpAndSettle();
          ProviderScope.containerOf(t.element(find.byType(TareasInicio))).read(vistaTareasProvider.notifier).elegir(vista);
          await t.pumpAndSettle();
          final semantica = t.ensureSemantics();
          await expectLater(t, meetsGuideline(androidTapTargetGuideline), reason: 'zonas táctiles');
          await expectLater(t, meetsGuideline(labeledTapTargetGuideline), reason: 'nombre para el lector de pantalla');
          await expectLater(t, meetsGuideline(textContrastGuideline), reason: 'contraste del texto');
          semantica.dispose();
        });
      }
    }

    testWidgets('en una tableta la Lista abre la ficha al lado, sin empujar otra pantalla', (t) async {
      final repo = _RepoFalso()..paginas = ((a, e, q, o) => [_tarea(7), _tarea(8)]);
      t.view.physicalSize = const Size(1100, 800);
      t.view.devicePixelRatio = 1;
      addTearDown(t.view.reset);
      await t.pumpWidget(_app(const TareasInicio(), _over(repo)));
      await t.pumpAndSettle();
      expect(find.text('Elige una tarea para ver su ficha.'), findsOneWidget);
      await t.tap(find.text('Tarea 7'));
      await t.pumpAndSettle();
      expect(find.text('Elige una tarea para ver su ficha.'), findsNothing);
      expect(find.byType(TareaDetalleScreen), findsOneWidget);
      // La lista sigue a la vista junto a la ficha.
      expect(find.text('Tarea 8'), findsOneWidget);
      expect(t.takeException(), isNull);
    });

    testWidgets('en una tableta ancha el asistente va en un tercer panel, sabe qué tarea hay abierta y se cierra y reabre', (t) async {
      final repo = _RepoFalso()..paginas = ((a, e, q, o) => [_tarea(7), _tarea(8)]);
      t.view.physicalSize = const Size(1400, 800);
      t.view.devicePixelRatio = 1;
      addTearDown(t.view.reset);
      await t.pumpWidget(_app(const TareasInicio(), _over(repo)));
      await t.pumpAndSettle();
      expect(find.byType(IaChatScreen), findsOneWidget);
      expect(find.text('Contexto: Tareas'), findsOneWidget);
      await t.tap(find.text('Tarea 7'));
      await t.pumpAndSettle();
      expect(find.text('Contexto: Tarea'), findsOneWidget);
      await t.tap(find.byTooltip('Ocultar el asistente'));
      await t.pumpAndSettle();
      expect(find.byType(IaChatScreen), findsNothing);
      await t.tap(find.byTooltip('Preguntar al asistente').first);
      await t.pumpAndSettle();
      expect(find.byType(IaChatScreen), findsOneWidget);
      expect(t.takeException(), isNull);
    });

    testWidgets('en una tableta de menos de 1280 no cabe el panel: la chispa de la barra abre el chat aparte', (t) async {
      final repo = _RepoFalso()..paginas = ((a, e, q, o) => [_tarea(7)]);
      t.view.physicalSize = const Size(1000, 800);
      t.view.devicePixelRatio = 1;
      addTearDown(t.view.reset);
      await t.pumpWidget(_app(const TareasInicio(), _over(repo)));
      await t.pumpAndSettle();
      expect(find.byType(IaChatScreen), findsNothing);
      expect(find.byTooltip('Preguntar al asistente'), findsOneWidget);
    });

    testWidgets('en una tableta el Tablero muestra todas las columnas a la vez', (t) async {
      final repo = _RepoFalso()..tableroFalso = {'no_iniciada': [_tarea(1)], 'en_progreso': [_tarea(2)]};
      t.view.physicalSize = const Size(1100, 800);
      t.view.devicePixelRatio = 1;
      addTearDown(t.view.reset);
      await t.pumpWidget(_app(const TareasInicio(), _over(repo)));
      await t.pumpAndSettle();
      await t.tap(find.text('Tablero'));
      await t.pumpAndSettle();
      expect(find.byType(TabBar), findsNothing);
      expect(find.text('Tarea 1'), findsOneWidget);
      expect(find.text('Tarea 2'), findsOneWidget);
      expect(t.takeException(), isNull);
    });

    testWidgets('en una tableta (820 × 1180) ninguna vista de tareas se desborda', (t) async {
      final repo = _RepoFalso()
        ..paginas = ((a, e, q, o) => [_tarea(1, fecha: '2026-10-20', vencida: true, prioridad: 'alta'), _tarea(2)])
        ..diaFalso = {'vencidas': [_tarea(1)]}
        ..tableroFalso = {'no_iniciada': [_tarea(1)]};
      t.view.physicalSize = const Size(820, 1180);
      t.view.devicePixelRatio = 1;
      addTearDown(t.view.reset);
      await t.pumpWidget(_app(const TareasInicio(), _over(repo)));
      await t.pumpAndSettle();
      for (final vista in ['Mi día', 'Tablero', 'Calendario', 'Carga', 'Lista']) {
        await t.tap(find.text(vista));
        await t.pumpAndSettle();
        expect(t.takeException(), isNull, reason: vista);
      }
    });
  });

  group('Calendario y Carga', () {
    String iso(DateTime d) => '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

    /// Siete días que empiezan hoy; hoy lleva una tarea, un vencimiento fiscal, una cita y horas fichadas; mañana, otra tarea.
    CalendarioDeTareas semanaDeEjemplo(String vista) {
      final hoy = DateTime.now();
      return CalendarioDeTareas(vista, iso(hoy), [
        for (var i = 0; i < 7; i++)
          DiaCalendario(
            iso(hoy.add(Duration(days: i))),
            i == 0,
            true,
            i == 0 ? [_tarea(31, fecha: iso(hoy))] : (i == 1 ? [_tarea(32)] : []),
            i == 0 ? const [VencimientoDelDia(9, '303', 'Acme SL', '3T 2026', false)] : const [],
            i == 0 ? const [CitaDelDia('2026-10-26T10:30:00', 'Reunión con Acme')] : const [],
            i == 0 ? 5400 : 0,
          ),
      ], null);
    }

    Future<void> abrirCalendario(WidgetTester t, _RepoFalso repo) async {
      await t.binding.setSurfaceSize(const Size(800, 2400));
      addTearDown(() => t.binding.setSurfaceSize(null));
      await t.pumpWidget(_app(const TareasInicio(), _over(repo)));
      await t.pumpAndSettle();
      await t.tap(find.text('Calendario'));
      await t.pumpAndSettle();
    }

    testWidgets('el calendario enseña lo mismo que la web del día de hoy: tarea, vencimiento fiscal, cita y horas fichadas, y las capas se apagan', (t) async {
      final repo = _RepoFalso()..calendarioFalso = semanaDeEjemplo('mes');
      await abrirCalendario(t, repo);
      expect(repo.vistasPedidas.first, startsWith('mes:'));
      expect(find.text('Tarea 31'), findsOneWidget);
      expect(find.text('303 · Acme SL'), findsOneWidget);
      expect(find.text('Reunión con Acme'), findsOneWidget);
      expect(find.text('10:30'), findsOneWidget);
      expect(find.text('1 h 30 fichadas'), findsOneWidget);
      await t.tap(find.widgetWithText(FilterChip, 'Tareas'));
      await t.pumpAndSettle();
      expect(find.text('Tarea 31'), findsNothing);
      expect(find.text('303 · Acme SL'), findsOneWidget);
      await t.tap(find.widgetWithText(FilterChip, 'Vencimientos fiscales'));
      await t.pumpAndSettle();
      expect(find.text('303 · Acme SL'), findsNothing);
    });

    testWidgets('elegir otro día del mes enseña su agenda; completar una tarea desde ahí pasa por el aviso con «Deshacer»', (t) async {
      final repo = _RepoFalso()..calendarioFalso = semanaDeEjemplo('mes');
      await abrirCalendario(t, repo);
      final manana = DateTime.now().add(const Duration(days: 1));
      await t.tap(find.text('${manana.day}').first);
      await t.pumpAndSettle();
      expect(find.text('Tarea 32'), findsOneWidget);
      expect(find.text('Tarea 31'), findsNothing);
      await t.tap(find.byType(Checkbox).first);
      await t.pumpAndSettle();
      expect(repo.registro, contains('transicionar:32:completada:-:1'));
      expect(find.text('Deshacer'), findsOneWidget);
    });

    testWidgets('navegar y cambiar de vista pide al servidor el rango que toca', (t) async {
      final repo = _RepoFalso()..calendarioFalso = semanaDeEjemplo('mes');
      await abrirCalendario(t, repo);
      await t.tap(find.byTooltip('Siguiente'));
      await t.pumpAndSettle();
      expect(repo.vistasPedidas.last, startsWith('mes:'));
      expect(repo.vistasPedidas.last, isNot(repo.vistasPedidas.first));
      await t.tap(find.byIcon(Icons.view_agenda_outlined));
      await t.pumpAndSettle();
      await t.tap(find.text('Semana laboral'));
      await t.pumpAndSettle();
      expect(repo.vistasPedidas.last, startsWith('semana_laboral:'));
      await t.tap(find.text('Hoy'));
      await t.pumpAndSettle();
      expect(repo.vistasPedidas.last, 'semana_laboral:${iso(DateTime.now())}');
    });

    test('el mes se mueve sin pasarse de día (31 de enero + 1 mes = 28 de febrero)', () async {
      final repo = _RepoFalso()..calendarioFalso = semanaDeEjemplo('mes');
      final c = ProviderContainer(overrides: _over(repo));
      addTearDown(c.dispose);
      await c.read(calendarioProvider.future);
      final n = c.read(calendarioProvider.notifier);
      await n.irA(const Fecha(2027, 1, 31));
      await n.paso(1);
      expect(n.ancla, const Fecha(2027, 2, 28));
      await n.paso(-1);
      expect(n.ancla.mes, 1);
    });

    test('el nivel de carga es el de la web: rojo por encima de la jornada, ámbar desde el 70 %, verde por debajo', () {
      const dia = 480;
      expect(const CeldaDeCarga(500, 1, 0, 0, []).nivel(dia), NivelCarga.rojo);
      expect(const CeldaDeCarga(340, 1, 0, 0, []).nivel(dia), NivelCarga.ambar);
      expect(const CeldaDeCarga(120, 1, 0, 0, []).nivel(dia), NivelCarga.verde);
      expect(const CeldaDeCarga(500, 1, 0, 0, []).nivel(0), NivelCarga.ninguno, reason: 'fin de semana o atrasadas: sin nivel');
      expect(CeldaDeCarga.vacia.nivel(dia), NivelCarga.ninguno);
    });

    CargaSemanal cargaDeEjemplo() {
      final lunes = DateTime.now().subtract(Duration(days: DateTime.now().weekday - 1));
      final dias = [for (var i = 0; i < 7; i++) iso(lunes.add(Duration(days: i)))];
      return CargaSemanal(dias.first, dias, [
        PersonaDeCarga(1, 'Yo', true, 480, 600, 2400, {
          dias[1]: const CeldaDeCarga(600, 2, 0, 0, [TareaDeCarga(5, 'Cerrar el IVA', 360, 'alta'), TareaDeCarga(6, 'Llamar a Acme', 240, 'normal')]),
        }, const CeldaDeCarga(60, 1, 0, 0, [TareaDeCarga(7, 'Atrasada de ayer', 60, 'normal')]), CeldaDeCarga.vacia),
        PersonaDeCarga(8, 'Sol Pérez', false, 480, 0, 2400, const {}, CeldaDeCarga.vacia, const CeldaDeCarga(0, 1, 1, 0, [TareaDeCarga(9, 'Sin fecha ni horas', null, 'baja')])),
      ]);
    }

    Future<void> abrirCarga(WidgetTester t, _RepoFalso repo) async {
      await t.binding.setSurfaceSize(const Size(800, 2000));
      addTearDown(() => t.binding.setSurfaceSize(null));
      await t.pumpWidget(_app(const TareasInicio(), _over(repo)));
      await t.pumpAndSettle();
      await t.tap(find.text('Carga'));
      await t.pumpAndSettle();
    }

    testWidgets('la carga enseña a cada persona con sus horas por día frente a la jornada, atrasadas y sin fecha', (t) async {
      final repo = _RepoFalso()..cargaFalsa = cargaDeEjemplo();
      await abrirCarga(t, repo);
      expect(find.text('Yo (tú)'), findsOneWidget);
      expect(find.text('Sol Pérez'), findsOneWidget);
      expect(find.text('Semana: 10 h / 40 h'), findsOneWidget);
      expect(find.text('10 h'), findsOneWidget, reason: 'el martes: 600 min');
      expect(find.text('Atrasadas'), findsOneWidget);
      expect(find.text('Sin fecha'), findsOneWidget);
      expect(find.text('1 sin estimar'), findsOneWidget);
      expect(repo.vistasPedidas.last, startsWith('carga:'));
    });

    testWidgets('una celda lista sus tareas; desde ahí se reasigna a otra persona y se quita la fecha', (t) async {
      final repo = _RepoFalso()..cargaFalsa = cargaDeEjemplo();
      await abrirCarga(t, repo);
      await t.tap(find.text('10 h'));
      await t.pumpAndSettle();
      expect(find.text('Cerrar el IVA'), findsOneWidget);
      await t.tap(find.byIcon(Icons.more_vert).first);
      await t.pumpAndSettle();
      await t.tap(find.text('Reasignar a…'));
      await t.pumpAndSettle();
      await t.tap(find.text('Sol Pérez').last);
      await t.pumpAndSettle();
      expect(repo.registro, contains('mover:5:p=8:'));
      expect(find.text('Tarea movida'), findsOneWidget);
      await t.tap(find.text('10 h'));
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.more_vert).first);
      await t.pumpAndSettle();
      await t.tap(find.text('Quitar la fecha'));
      await t.pumpAndSettle();
      expect(repo.registro, contains('mover:5::f=-'));
    });
  });

  group('detalle', () {
    _RepoFalso repoConTarea({String estado = 'en_progreso', int version = 4}) => _RepoFalso()
      ..tareas = {7: _tarea(7, estado: estado, version: version, fecha: '2026-10-30')}
      ..subs = const [Subtarea(8, 'Pedir certificado', EstadoTarea.completada), Subtarea(9, 'Revisar IVA', EstadoTarea.noIniciada)]
      ..check = [ChecklistItem.fromJson({'id': 3, 'texto': 'Comprobar NIF', 'hecha': 0})]
      ..coments = [ComentarioTarea.fromJson({'id': 1, 'texto': 'Ya lo tengo', 'creado_en': '2026-10-24T09:30'})]
      ..adjs = [AdjuntoTarea.fromJson({'id': 5, 'nombre_archivo': 'factura.pdf', 'tamano_bytes': 2048})];

    testWidgets('enseña todo: estado, fecha, subtareas con progreso, comprobación, comentarios y adjuntos', (t) async {
      await t.binding.setSurfaceSize(const Size(800, 3000)); // que quepa todo sin desplazar
      addTearDown(() => t.binding.setSurfaceSize(null));
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repoConTarea())));
      await t.pumpAndSettle();
      expect(find.text('Tarea 7'), findsOneWidget);
      expect(find.text('Estado: En curso'), findsOneWidget);
      expect(find.text('Subtareas · 1/2'), findsOneWidget);
      expect(find.text('Pedir certificado'), findsOneWidget);
      expect(find.text('Comprobar NIF'), findsOneWidget);
      expect(find.text('Ya lo tengo'), findsOneWidget);
      expect(find.textContaining('09:30'), findsOneWidget); // la fecha sale con el formateo único («hoy 09:30», «sáb 24 oct 09:30»...)
      expect(find.text('factura.pdf'), findsOneWidget);
      expect(find.text('2 KB'), findsOneWidget);
    });

    testWidgets('la cabecera enseña proyecto, cliente, quién la tiene y la estimación como la web', (t) async {
      final repo = repoConTarea()
        ..tareas = {
          7: TareaOutlook.fromJson({
            ..._t(7, estado: 'en_progreso', version: 4),
            'categoria_nombre': 'IVA',
            'asignada_a': 7,
            'estimacion_min': 90,
            'clientes': [
              {'id': 11, 'nombre': 'Acme SL', 'principal': true},
              {'id': 12, 'nombre': 'Beta SA', 'principal': false},
            ],
          }),
        };
      await t.binding.setSurfaceSize(const Size(800, 3000));
      addTearDown(() => t.binding.setSurfaceSize(null));
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repo)));
      await t.pumpAndSettle();
      expect(find.text('IVA'), findsOneWidget);
      expect(find.text('Acme SL +1'), findsOneWidget);
      expect(find.text('Asignada a Luis Mora'), findsOneWidget);
      expect(find.text('Estimada: 1 h 30'), findsOneWidget);
    });

    testWidgets('«Espera a»: se añade otra tarea (con el aviso del servidor si crea un ciclo) y se quita', (t) async {
      final repo = repoConTarea()..paginas = ((a, e, q, o) => [_tarea(21), _tarea(22), _tarea(7)]);
      await t.binding.setSurfaceSize(const Size(800, 3000));
      addTearDown(() => t.binding.setSurfaceSize(null));
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repo)));
      await t.pumpAndSettle();
      expect(find.text('No espera a ninguna tarea.'), findsOneWidget);
      await t.tap(find.text('Esperar a otra tarea'));
      await t.pumpAndSettle();
      expect(find.text('Tarea 7'), findsOneWidget, reason: 'solo el título de la ficha: la propia tarea no se ofrece como espera');
      await t.tap(find.text('Tarea 21'));
      await t.pumpAndSettle();
      expect(repo.registro, contains('espera:7:21'));
      expect(find.text('Tarea 21'), findsOneWidget);
      await t.tap(find.byTooltip('Quitar').first);
      await t.pumpAndSettle();
      expect(repo.registro, contains('quitarEspera:7:21'));
    });

    testWidgets('«Compartida con»: se comparte con un rol y se deja de compartir', (t) async {
      final repo = repoConTarea();
      await t.binding.setSurfaceSize(const Size(800, 3000));
      addTearDown(() => t.binding.setSurfaceSize(null));
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repo)));
      await t.pumpAndSettle();
      expect(find.text('No está compartida con nadie.'), findsOneWidget);
      await t.tap(find.text('Compartir con…'));
      await t.pumpAndSettle();
      await t.tap(find.byTooltip('Compartir con…').last);
      await t.pumpAndSettle();
      await t.tap(find.text('Solo lectura'));
      await t.pumpAndSettle();
      expect(repo.registro, contains('compartir:7:8:observa'));
      expect(find.text('Sol Pérez'), findsOneWidget);
      await t.tap(find.byTooltip('Quitar').first);
      await t.pumpAndSettle();
      expect(repo.registro, contains('descompartir:7:8'));
    });

    testWidgets('«Tiempo dedicado»: inicia (pidiendo proyecto si no tiene), pausa, reanuda y para el cronómetro', (t) async {
      final repo = repoConTarea();
      await t.binding.setSurfaceSize(const Size(800, 3000));
      addTearDown(() => t.binding.setSurfaceSize(null));
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repo)));
      await t.pumpAndSettle();
      expect(find.text('Todavía no has registrado tiempo en esta tarea.'), findsOneWidget);
      await t.ensureVisible(find.text('Iniciar el cronómetro'));
      await t.tap(find.text('Iniciar el cronómetro'));
      await t.pumpAndSettle();
      expect(find.text('¿En qué proyecto registras el tiempo?'), findsOneWidget);
      await t.tap(find.text('Laboral'));
      await t.pumpAndSettle();
      expect(repo.registro, contains('crono:7:4'));
      expect(find.text('Cronómetro en marcha'), findsOneWidget);
      await t.tap(find.text('Pausar'));
      await t.pumpAndSettle();
      expect(find.text('Cronómetro en pausa'), findsOneWidget);
      expect(find.text('0:02:05'), findsOneWidget, reason: 'en pausa enseña lo trabajado hasta pausar');
      await t.tap(find.text('Reanudar'));
      await t.pumpAndSettle();
      await t.tap(find.text('Parar y guardar'));
      await t.pumpAndSettle();
      expect(repo.registro, containsAllInOrder(['crono:7:4', 'pausa:90', 'reanuda:90', 'finaliza:90']));
      expect(find.text('Registrado hasta ahora: 3 min'), findsOneWidget);
    });

    testWidgets('«Actividad» se pide al abrirla', (t) async {
      final repo = repoConTarea()..actividadFalsa = const [ActividadDeTarea('Sol Pérez', 'Cambió el estado a En curso', '2026-10-24T09:30')];
      await t.binding.setSurfaceSize(const Size(800, 3400));
      addTearDown(() => t.binding.setSurfaceSize(null));
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repo)));
      await t.pumpAndSettle();
      expect(find.text('Cambió el estado a En curso'), findsNothing);
      await t.ensureVisible(find.text('Actividad'));
      await t.tap(find.text('Actividad'));
      await t.pumpAndSettle();
      expect(find.text('Cambió el estado a En curso'), findsOneWidget);
    });

    testWidgets('el editor guarda otros clientes y la visibilidad en el portal, y sin cliente no hay portal', (t) async {
      final repo = repoConTarea();
      await t.binding.setSurfaceSize(const Size(800, 3400));
      addTearDown(() => t.binding.setSurfaceSize(null));
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repo)));
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.edit_outlined));
      await t.pumpAndSettle();
      expect(find.text('Enseñar esta tarea al cliente en su portal'), findsNothing);
      await t.tap(find.text('Sin cliente'));
      await t.pumpAndSettle();
      await t.tap(find.text('Acme SL'));
      await t.pumpAndSettle();
      await t.tap(find.widgetWithText(FilterChip, 'Beta SA'));
      await t.tap(find.text('Enseñar esta tarea al cliente en su portal'));
      await t.pumpAndSettle();
      await t.tap(find.text('Permitir que el cliente escriba comentarios en esta tarea'));
      await t.pumpAndSettle();
      await t.tap(find.text('Guardar'));
      await t.pumpAndSettle();
      expect(repo.registro, containsAll(['cliente:7:11:12', 'portal:7:true:true']));
    });

    testWidgets('«Revisión»: se pide a varias personas en cadena, vota quien le toca y se puede retirar', (t) async {
      final repo = repoConTarea();
      await t.binding.setSurfaceSize(const Size(800, 3400));
      addTearDown(() => t.binding.setSurfaceSize(null));
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repo)));
      await t.pumpAndSettle();
      expect(find.text('No hay ninguna revisión pendiente.'), findsOneWidget);
      await t.ensureVisible(find.text('Pedir revisión'));
      await t.tap(find.text('Pedir revisión'));
      await t.pumpAndSettle();
      await t.tap(find.text('Sol Pérez'));
      await t.tap(find.text('Luis Mora'));
      await t.tap(find.text('Aprueban uno tras otro, en el orden indicado.'));
      await t.pumpAndSettle();
      await t.tap(find.text('Pedir revisión').last);
      await t.pumpAndSettle();
      expect(repo.registro, contains('revision:7:8,7:cadena:-'));
      expect(find.text('La revisan 2 personas.'), findsOneWidget);
      expect(find.text('Mientras esté pendiente, la tarea no se puede completar.'), findsOneWidget);
      await t.ensureVisible(find.text('Retirar la petición'));
      await t.tap(find.text('Retirar la petición'));
      await t.pumpAndSettle();
      expect(repo.registro, contains('retirar:7'));
      expect(find.text('No hay ninguna revisión pendiente.'), findsOneWidget);
    });

    testWidgets('«Revisión»: quien tiene el voto aprueba o pide cambios con su nota', (t) async {
      final repo = repoConTarea()
        ..revisionesFalsas = const RevisionesDeLaTarea(
          RevisionDeTarea(1, 'pendiente', 'todos', 9, 'Mira el IVA', null, null, [1], [VotoRevision(1, 'Yo', 'pendiente', null)], 0),
          [RevisionDeTarea(0, 'cambios', 'todos', 9, null, 'Falta el 303', null, [], [VotoRevision(1, 'Yo', 'cambios', 'Falta el 303')], 0)],
        );
      await t.binding.setSurfaceSize(const Size(800, 3400));
      addTearDown(() => t.binding.setSurfaceSize(null));
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repo, conUsuario: true)));
      await t.pumpAndSettle();
      expect(find.text('«Mira el IVA»'), findsOneWidget);
      expect(find.text('Cambios pedidos'), findsOneWidget);
      await t.ensureVisible(find.text('Pedir cambios'));
      await t.enterText(find.widgetWithText(TextField, 'Comentario (obligatorio si pides cambios)'), 'Revisa el modelo');
      await t.tap(find.text('Pedir cambios'));
      await t.pumpAndSettle();
      expect(repo.registro, contains('voto:7:cambios:Revisa el modelo'));
    });

    testWidgets('«Conversación con el cliente»: se ve lo del cliente, se contesta y se oculta un comentario', (t) async {
      final repo = repoConTarea()
        ..tareas = {
          7: TareaOutlook.fromJson({
            ..._t(7, estado: 'en_progreso', version: 4),
            'visible_cliente': 1,
            'comentarios_cliente': 1,
            'clientes': [
              {'id': 11, 'nombre': 'Acme SL', 'principal': true},
            ],
          }),
        }
        ..conversacionesFalsas = [
          ConversacionConCliente(11, 'Acme SL', 1, [MensajeCliente(5, true, null, 'Os mando la factura mañana', '2026-10-25T09:00', false)]),
        ];
      await t.binding.setSurfaceSize(const Size(800, 3800));
      addTearDown(() => t.binding.setSurfaceSize(null));
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repo)));
      await t.pumpAndSettle();
      expect(find.textContaining('Conversación con el cliente · 1 nuevo'), findsOneWidget);
      expect(find.text('Os mando la factura mañana'), findsOneWidget);
      expect(repo.registro, contains('leidos:7'));
      await t.ensureVisible(find.byTooltip('Ocultar este comentario al cliente'));
      await t.enterText(find.widgetWithText(TextField, 'Respuesta para el cliente (la verá en su portal y le llegará un correo)'), 'Perfecto, gracias');
      await t.tap(find.text('Contestar al cliente'));
      await t.pumpAndSettle();
      expect(repo.registro, contains('responder:7:11:Perfecto, gracias'));
      await t.tap(find.byTooltip('Ocultar este comentario al cliente'));
      await t.pumpAndSettle();
      expect(repo.registro, contains('ocultar:5'));
      expect(find.text('Comentario oculto'), findsOneWidget);
    });

    testWidgets('«Recordatorios»: uno relativo al vencimiento, con sus canales, y quitarlo', (t) async {
      final repo = repoConTarea();
      await t.binding.setSurfaceSize(const Size(800, 3000));
      addTearDown(() => t.binding.setSurfaceSize(null));
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repo)));
      await t.pumpAndSettle();
      expect(find.text('No tienes recordatorios en esta tarea.'), findsOneWidget);
      await t.ensureVisible(find.text('Añadir recordatorio'));
      await t.tap(find.text('Añadir recordatorio'));
      await t.pumpAndSettle();
      await t.tap(find.text('1 día antes del vencimiento'));
      await t.pumpAndSettle();
      await t.tap(find.text('Correo'));
      await t.pumpAndSettle();
      await t.tap(find.text('Añadir recordatorio').last);
      await t.pumpAndSettle();
      expect(repo.registro, contains('recordar:7:1d_antes:app+correo'));
      expect(find.textContaining('Pendiente'), findsOneWidget);
    });

    testWidgets('el editor manda solo lo que cambia, cada cosa a su operación, y avisa de lo que no se pudo', (t) async {
      final repo = repoConTarea()..falloAlAsignar = ApiException('No puedes asignar a esa persona', status: 403);
      await t.binding.setSurfaceSize(const Size(800, 3000));
      addTearDown(() => t.binding.setSurfaceSize(null));
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repo)));
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.edit_outlined));
      await t.pumpAndSettle();
      await t.enterText(find.widgetWithText(TextField, 'Estimación'), '1h30');
      await t.tap(find.text('Alta'));
      await t.tap(find.text('Sin proyecto'));
      await t.pumpAndSettle();
      await t.tap(find.text('Laboral'));
      await t.pumpAndSettle();
      await t.tap(find.text('Sin cliente'));
      await t.pumpAndSettle();
      await t.tap(find.text('Beta SA'));
      await t.pumpAndSettle();
      await t.tap(find.text('Sin asignar'));
      await t.pumpAndSettle();
      await t.tap(find.text('Sol Pérez'));
      await t.pumpAndSettle();
      await t.tap(find.text('Guardar'));
      await t.pumpAndSettle();
      expect(repo.registro, contains('ficha:7:prio=alta,est=1h30'));
      expect(repo.registro, containsAll(['proyecto:7:4', 'cliente:7:12:']));
      expect(find.textContaining('Se guardó lo demás'), findsOneWidget);
      expect(find.textContaining('No puedes asignar a esa persona'), findsOneWidget);
    });

    testWidgets('cerrar el selector sin elegir no borra el proyecto, y quitar una fecha manda el borrado', (t) async {
      final repo = repoConTarea()..tareas = {7: TareaOutlook.fromJson({..._t(7, estado: 'en_progreso', version: 4, fecha: '2026-10-30'), 'categoria_id': 3})};
      await t.binding.setSurfaceSize(const Size(800, 3000));
      addTearDown(() => t.binding.setSurfaceSize(null));
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repo)));
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.edit_outlined));
      await t.pumpAndSettle();
      await t.tap(find.text('IVA')); // proyecto actual
      await t.pumpAndSettle();
      await t.tapAt(const Offset(10, 10)); // cierra el panel sin elegir
      await t.pumpAndSettle();
      expect(find.text('IVA'), findsOneWidget);
      await t.tap(find.byTooltip('Quitar').first);
      await t.pumpAndSettle();
      await t.tap(find.text('Guardar'));
      await t.pumpAndSettle();
      expect(repo.registro, contains('ficha:7:venc=-'));
      expect(repo.registro.where((r) => r.startsWith('proyecto')), isEmpty);
    });

    testWidgets('cambiar el estado manda la versión que se leyó', (t) async {
      final repo = repoConTarea();
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repo)));
      await t.pumpAndSettle();
      await t.tap(find.text('Estado: En curso'));
      await t.pumpAndSettle();
      await t.tap(find.text('Aplazada'));
      await t.pumpAndSettle();
      expect(repo.registro, contains('transicionar:7:aplazada:-:4'));
    });

    testWidgets('«esperando» pide el motivo y lo manda', (t) async {
      final repo = repoConTarea();
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repo)));
      await t.pumpAndSettle();
      await t.tap(find.text('Estado: En curso'));
      await t.pumpAndSettle();
      await t.tap(find.text('Esperando'));
      await t.pumpAndSettle();
      expect(find.text('¿Por qué queda en espera?'), findsOneWidget);
      await t.enterText(find.byType(TextField).last, 'Falta el certificado');
      await t.tap(find.text('Aceptar'));
      await t.pumpAndSettle();
      expect(repo.registro, contains('transicionar:7:esperando:Falta el certificado:4'));
    });

    testWidgets('conflicto: «aplicar igualmente» reintenta con la versión que hay ahora', (t) async {
      final repo = repoConTarea();
      var intento = 0;
      repo.alTransicionar = (id, e, m, v) async {
        intento++;
        if (intento == 1) throw _conflicto(9);
        return _tarea(id, estado: e.valor, version: 10);
      };
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repo)));
      await t.pumpAndSettle();
      await t.tap(find.text('Estado: En curso'));
      await t.pumpAndSettle();
      await t.tap(find.text('Aplazada'));
      await t.pumpAndSettle();
      expect(find.text('Alguien la ha cambiado'), findsOneWidget);
      await t.tap(find.text('Aplicar igualmente'));
      await t.pumpAndSettle();
      expect(repo.registro.where((r) => r.startsWith('transicionar')).toList(), ['transicionar:7:aplazada:-:4', 'transicionar:7:aplazada:-:9']);
      expect(find.text('Estado: Aplazada'), findsOneWidget);
    });

    testWidgets('conflicto: «ver los cambios» vuelve a cargar la tarea sin aplicar nada', (t) async {
      final repo = repoConTarea();
      repo.alTransicionar = (id, e, m, v) async => throw _conflicto(9);
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repo)));
      await t.pumpAndSettle();
      await t.tap(find.text('Estado: En curso'));
      await t.pumpAndSettle();
      await t.tap(find.text('Aplazada'));
      await t.pumpAndSettle();
      repo.tareas[7] = _tarea(7, estado: 'esperando', version: 9, motivo: 'Cambiada por otra persona');
      await t.tap(find.text('Ver los cambios'));
      await t.pumpAndSettle();
      expect(repo.registro.where((r) => r.startsWith('transicionar')).length, 1);
      expect(find.text('Estado: Esperando'), findsOneWidget);
      expect(find.text('Cambiada por otra persona'), findsOneWidget);
    });

    testWidgets('un error de negocio (tarea bloqueada) se enseña tal cual', (t) async {
      final repo = repoConTarea();
      repo.alTransicionar = (id, e, m, v) async => throw ApiException('La tarea está bloqueada por otra', codigo: 'tarea_bloqueada', status: 409);
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repo)));
      await t.pumpAndSettle();
      await t.tap(find.text('Estado: En curso'));
      await t.pumpAndSettle();
      await t.tap(find.text('Aplazada'));
      await t.pumpAndSettle();
      expect(find.text('La tarea está bloqueada por otra'), findsOneWidget);
    });

    testWidgets('marcar una subtarea la completa; añadir una subtarea y un comentario los manda', (t) async {
      final repo = repoConTarea();
      await t.pumpWidget(_app(const TareaDetalleScreen(tareaId: 7), _over(repo)));
      await t.pumpAndSettle();
      await t.tap(find.widgetWithText(CheckboxListTile, 'Revisar IVA'));
      await t.pumpAndSettle();
      expect(repo.registro, contains('transicionar:9:completada:-:-'));
      await t.enterText(find.widgetWithText(TextField, 'Añadir subtarea'), 'Enviar al cliente');
      await t.tap(find.byTooltip('Añadir subtarea'));
      await t.pumpAndSettle();
      expect(repo.registro, contains('subtarea:7:Enviar al cliente'));
      await t.scrollUntilVisible(find.widgetWithText(TextField, 'Escribe un comentario'), 300, scrollable: find.byType(Scrollable).first);
      await t.enterText(find.widgetWithText(TextField, 'Escribe un comentario'), 'Listo @ana');
      await t.tap(find.byTooltip('Escribe un comentario'));
      await t.pumpAndSettle();
      expect(repo.registro, contains('comentar:7:Listo @ana'));
    });
  });
}
