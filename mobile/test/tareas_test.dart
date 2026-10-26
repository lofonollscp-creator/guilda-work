import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/api/cliente.dart';
import 'package:guilda_work_mobile/api/errores.dart';
import 'package:guilda_work_mobile/api/generado/modelos.g.dart';
import 'package:guilda_work_mobile/datos/cola.dart';
import 'package:guilda_work_mobile/datos/local/cola_escritura.dart';
import 'package:guilda_work_mobile/dominio/tarea.dart';
import 'package:guilda_work_mobile/funciones/tareas/tarea_detalle_screen.dart';
import 'package:guilda_work_mobile/funciones/tareas/tareas_lista_controlador.dart';
import 'package:guilda_work_mobile/funciones/tareas/tareas_repositorio.dart';
import 'package:guilda_work_mobile/funciones/tareas/tareas_vistas.dart';
import 'package:guilda_work_mobile/funciones/tareas/tareas_screen.dart';
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/nucleo/sesion.dart';
import 'package:guilda_work_mobile/services/api_client.dart' as sv;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

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

class _SesionFija extends SesionControl {
  @override
  EstadoSesion build() => const EstadoSesion(fase: FaseSesion.conSesion);
}

List<Override> _over(_RepoFalso repo) => [
      tareasRepositorioProvider.overrideWithValue(repo),
      estadoSesionProvider.overrideWith(_SesionFija.new),
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
      await t.tap(find.text('Asignadas'));
      await t.pumpAndSettle();
      await t.tap(find.text('Esperando'));
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
