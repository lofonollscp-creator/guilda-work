
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/api/errores.dart';
import 'package:guilda_work_mobile/api/generado/modelos.g.dart' hide Usuario;
import 'package:guilda_work_mobile/datos/cola.dart';
import 'package:guilda_work_mobile/datos/cola_procesador.dart';
import 'package:guilda_work_mobile/datos/local/cola_escritura.dart';
import 'package:guilda_work_mobile/dominio/tarea.dart';
import 'package:guilda_work_mobile/funciones/pendientes/pendientes_sheet.dart';
import 'package:guilda_work_mobile/funciones/tareas/tareas_acciones.dart';
import 'package:guilda_work_mobile/funciones/tareas/tareas_lista_controlador.dart';
import 'package:guilda_work_mobile/funciones/tareas/tareas_repositorio.dart';
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/nucleo/sesion.dart';
import 'package:guilda_work_mobile/services/api_client.dart' show Usuario;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

int _ahora = 1000000;
ColaEscritura _cola({void Function()? alCambiar}) => ColaEscritura(
      abrir: () => databaseFactoryFfi.openDatabase(inMemoryDatabasePath, options: OpenDatabaseOptions(version: 1, onCreate: ColaEscritura.crearEsquema, singleInstance: false)),
      ahoraMs: () => _ahora,
      alCambiar: alCambiar,
    );

Future<Pendiente> _encolar(ColaEscritura c, String clave, {String entidad = 'tarea:1', int usuario = 1, String despacho = '3', String ruta = '/tareas-outlook/1/transiciones', Map<String, dynamic>? cuerpo, String? localId, String desc = 'Completar'}) =>
    c.encolar(metodo: 'POST', ruta: ruta, cuerpo: cuerpo ?? {'estado': 'completada', 'version': 4}, clave: clave, usuarioId: usuario, despachoId: despacho, entidad: entidad, tipo: 'tarea.estado', descripcion: desc, localId: localId);

void main() {
  setUpAll(sqfliteFfiInit);
  setUp(() => _ahora = 1000000);

  group('ColaEscritura', () {
    test('guarda lo de cada persona y despacho por separado, en orden', () async {
      final c = _cola();
      await _encolar(c, 'a');
      await _encolar(c, 'b', entidad: 'tarea:2');
      await _encolar(c, 'c', usuario: 2);
      await _encolar(c, 'd', despacho: '8');
      expect((await c.de(1, '3')).map((p) => p.clave), ['a', 'b']);
      expect(await c.contar(1, '3'), 2);
      expect(await c.contar(2, '3'), 1);
      expect(await c.contar(1, '8'), 1);
      expect((await c.de(1, '3')).first.cuerpoMapa, {'estado': 'completada', 'version': 4});
    });

    test('máximo 200: la 201 se rechaza; avisa al llegar a 150', () async {
      final c = _cola();
      for (var i = 0; i < 149; i++) {
        await _encolar(c, 'k$i', entidad: 'tarea:$i');
      }
      expect(await c.casiLlena(), false);
      await _encolar(c, 'k149');
      expect(await c.casiLlena(), true);
      for (var i = 150; i < 200; i++) {
        await _encolar(c, 'k$i', entidad: 'tarea:$i');
      }
      await expectLater(_encolar(c, 'k200'), throwsA(isA<ColaLlena>()));
    });

    test('lo que lleva más de 14 días caduca', () async {
      final c = _cola();
      await _encolar(c, 'vieja');
      _ahora += const Duration(days: 13).inMilliseconds;
      await _encolar(c, 'nueva');
      expect(await c.purgarCaducadas(), 0);
      _ahora += const Duration(days: 2).inMilliseconds; // la vieja: 15 días; la nueva: 2
      expect(await c.purgarCaducadas(), 1);
      expect((await c.de(1, '3')).map((p) => p.clave), ['nueva']);
    });

    test('un id local se sustituye por el real en ruta, cuerpo y entidad de las demás', () async {
      final c = _cola();
      await _encolar(c, 'crea', entidad: 'tarea-nueva:x', ruta: '/tareas-outlook', localId: 'local:x');
      await _encolar(c, 'comenta', entidad: 'tarea:local:x', ruta: '/tareas-outlook/local:x/comentarios', cuerpo: {'texto': 'hola', 'ref': 'local:x'});
      await c.sustituirIdLocal('local:x', 55);
      final p = (await c.de(1, '3'))[1];
      expect(p.ruta, '/tareas-outlook/55/comentarios');
      expect(p.entidad, 'tarea:55');
      expect(p.cuerpoMapa!['ref'], '55');
    });

    test('«aplicar igualmente» cambia la versión del cuerpo y la deja lista', () async {
      final c = _cola();
      final p = await _encolar(c, 'a');
      await c.marcar(p.id, estado: EstadoPendiente.conflicto, error: 'otra persona', versionActual: 9);
      await c.reintentarConVersion(p.id, 9);
      final despues = (await c.de(1, '3')).single;
      expect(despues.estado, EstadoPendiente.pendiente);
      expect(despues.cuerpoMapa!['version'], 9);
      expect(despues.error, null);
    });

    test('lo que quedó «enviando» al cerrarse la app vuelve a pendiente; vaciar solo borra lo de esa persona', () async {
      final c = _cola();
      final a = await _encolar(c, 'a');
      await _encolar(c, 'b', usuario: 2);
      await c.marcar(a.id, estado: EstadoPendiente.enviando);
      await c.reiniciarEnviando();
      expect((await c.de(1, '3')).single.estado, EstadoPendiente.pendiente);
      await c.vaciar(1);
      expect(await c.contar(1, '3'), 0);
      expect(await c.contar(2, '3'), 1);
    });

    test('avisa de cada cambio', () async {
      var n = 0;
      final c = _cola(alCambiar: () => n++);
      final p = await _encolar(c, 'a');
      await c.marcar(p.id, estado: EstadoPendiente.enviando);
      await c.eliminar(p.id);
      expect(n, 3);
    });
  });

  group('ProcesadorCola', () {
    late ColaEscritura cola;
    late List<String> enviadas;
    late Map<String, Object> respuestas; // clave → respuesta o ApiException
    late int? usuario;
    late String? despacho;
    late ProcesadorCola proc;
    ResultadoProceso? ultimo;

    setUp(() {
      cola = _cola();
      enviadas = [];
      respuestas = {};
      usuario = 1;
      despacho = '3';
      ultimo = null;
      proc = ProcesadorCola(
        cola: cola,
        usuarioActivo: () => usuario,
        despachoActivo: () => despacho,
        ahoraMs: () => _ahora,
        alTerminar: (r) => ultimo = r,
        enviar: (p) async {
          enviadas.add('${p.clave}@${p.ruta}');
          final r = respuestas[p.clave];
          if (r is ApiException) throw r;
          return r;
        },
      );
    });

    test('envía en orden y vacía lo enviado, con la clave de cada acción', () async {
      await _encolar(cola, 'a');
      await _encolar(cola, 'b', entidad: 'tarea:2', ruta: '/tareas-outlook/2/transiciones');
      final r = await proc.procesar();
      expect(enviadas, ['a@/tareas-outlook/1/transiciones', 'b@/tareas-outlook/2/transiciones']);
      expect(r.enviadas, 2);
      expect(await cola.contar(1, '3'), 0);
      expect(ultimo?.enviadas, 2); // las listas se recargan
    });

    test('sin red: cuenta el intento, espera y corta la pasada; al volver la red sale con la MISMA clave', () async {
      await _encolar(cola, 'a');
      await _encolar(cola, 'b', entidad: 'tarea:2');
      respuestas['a'] = ApiException('sin red', esDeConexion: true);
      final r = await proc.procesar();
      expect(r.motivoDeParada, 'sin_red');
      expect(enviadas, ['a@/tareas-outlook/1/transiciones']); // b no se intenta
      var p = (await cola.de(1, '3')).first;
      expect((p.estado, p.intentos), (EstadoPendiente.pendiente, 1));
      expect(p.proximoIntentoMs, _ahora + 2000); // 1 s, 2 s, 4 s...
      // aún no toca la de la tarea 1; la otra (otra entidad) sí sale
      await proc.procesar();
      expect(enviadas, ['a@/tareas-outlook/1/transiciones', 'b@/tareas-outlook/1/transiciones']);
      // vuelve la red y llega su hora
      respuestas.remove('a');
      _ahora += 3000;
      await proc.procesar();
      expect(enviadas.where((e) => e.startsWith('a@')).length, 2);
      expect(await cola.contar(1, '3'), 0);
      expect(enviadas.length, 3);
    });

    test('conflicto: conserva la intención con la versión actual y bloquea solo lo de esa entidad', () async {
      await _encolar(cola, 'a'); // tarea:1
      await _encolar(cola, 'a2', ruta: '/tareas-outlook/1/comentarios'); // misma tarea: espera
      await _encolar(cola, 'b', entidad: 'tarea:2', ruta: '/tareas-outlook/2/transiciones'); // otra: sigue
      respuestas['a'] = ApiException('versión', codigo: 'version_obsoleta', status: 409, versionActual: 9);
      final r = await proc.procesar();
      expect(r.conflictos, 1);
      expect(enviadas.map((e) => e.split('@').first), ['a', 'b']); // a2 no salió
      final fila = (await cola.de(1, '3')).first;
      expect((fila.estado, fila.versionActual), (EstadoPendiente.conflicto, 9));
      // «aplicar igualmente» y vuelve a salir, y después sale el comentario
      await cola.reintentarConVersion(fila.id, 9);
      respuestas.remove('a');
      await proc.procesar();
      expect(enviadas.map((e) => e.split('@').first), ['a', 'b', 'a', 'a2']);
      expect(await cola.contar(1, '3'), 0);
    });

    test('una regla de negocio la rechaza y no se reintenta', () async {
      await _encolar(cola, 'a');
      respuestas['a'] = ApiException('Tiene subtareas abiertas', codigo: 'subtareas_abiertas', status: 409.compareTo(0) > 0 ? 400 : 400);
      final r = await proc.procesar();
      expect(r.rechazadas, 1);
      final p = (await cola.de(1, '3')).single;
      expect((p.estado, p.error), (EstadoPendiente.rechazada, 'Tiene subtareas abiertas'));
      await proc.procesar();
      expect(enviadas.length, 1);
    });

    test('429 espera lo que diga Retry-After; 5xx, el retroceso exponencial', () async {
      await _encolar(cola, 'a');
      await _encolar(cola, 'b', entidad: 'tarea:2');
      respuestas['a'] = ApiException('límite', status: 429, retryAfter: const Duration(seconds: 90));
      respuestas['b'] = ApiException('caído', status: 503);
      await proc.procesar();
      final filas = await cola.de(1, '3');
      expect(filas[0].proximoIntentoMs, _ahora + 90000);
      expect(filas[1].proximoIntentoMs, _ahora + 2000);
      expect(filas.every((f) => f.estado == EstadoPendiente.pendiente), true);
    });

    test('401 o 426 cortan la pasada y no pierden nada', () async {
      await _encolar(cola, 'a');
      await _encolar(cola, 'b', entidad: 'tarea:2');
      respuestas['a'] = ApiException('caducó', status: 401);
      expect((await proc.procesar()).motivoDeParada, 'sesion');
      respuestas['a'] = ApiException('actualiza', status: 426);
      expect((await proc.procesar()).motivoDeParada, 'actualizar');
      expect(await cola.contar(1, '3'), 2);
      expect(enviadas.every((e) => e.startsWith('a@')), true);
    });

    test('solo envía lo de la persona y el despacho activos', () async {
      await _encolar(cola, 'mia');
      await _encolar(cola, 'otra', usuario: 2);
      await _encolar(cola, 'otro-despacho', despacho: '8');
      await proc.procesar();
      expect(enviadas.map((e) => e.split('@').first), ['mia']);
      despacho = '8';
      await proc.procesar();
      expect(enviadas.map((e) => e.split('@').first), ['mia', 'otro-despacho']);
      usuario = null; // sin sesión: nada
      await proc.procesar();
      expect(enviadas.length, 2);
      expect(await cola.contar(2, '3'), 1);
    });

    test('lo creado sin conexión: su id real sustituye al local en lo que depende de ello', () async {
      await _encolar(cola, 'crea', entidad: 'tarea-nueva:x', ruta: '/tareas-outlook', localId: 'local:x');
      await _encolar(cola, 'comenta', entidad: 'tarea:local:x', ruta: '/tareas-outlook/local:x/comentarios');
      respuestas['crea'] = {'id': 55};
      await proc.procesar();
      expect(enviadas, ['crea@/tareas-outlook', 'comenta@/tareas-outlook/55/comentarios']);
    });

    test('no se pisa a sí mismo si se llama a la vez y un fallo raro no deja «enviando»', () async {
      await _encolar(cola, 'a');
      final p2 = ProcesadorCola(
        cola: cola, usuarioActivo: () => 1, despachoActivo: () => '3', ahoraMs: () => _ahora,
        enviar: (p) async => throw StateError('algo inesperado'),
      );
      final dos = await Future.wait([p2.procesar(), p2.procesar()]);
      expect(dos.where((r) => r.enviadas == 0).length, 2);
      final p = (await cola.de(1, '3')).single;
      expect(p.estado, EstadoPendiente.pendiente);
      expect(p.intentos, 1);
    });

    test('retroceso: 1 s, 2 s, 4 s... con tope de 5 minutos', () {
      expect([0, 1, 2, 3].map((i) => ProcesadorCola.espera(i).inSeconds), [1, 2, 4, 8]);
      expect(ProcesadorCola.espera(20).inSeconds, 300);
    });
  });

  group('tareas sin conexión', () {
    late ColaEscritura cola;
    late _RepoSinRed repo;
    late ProviderContainer c;

    setUp(() {
      cola = _cola();
      repo = _RepoSinRed();
      c = ProviderContainer(overrides: [
        colaEscrituraProvider.overrideWithValue(cola),
        tareasRepositorioProvider.overrideWithValue(repo),
        estadoSesionProvider.overrideWith(_Sesion.new),
      ]);
      addTearDown(c.dispose);
    });

    test('crear sin red: se guarda con la MISMA clave del intento y se enseña como provisional', () async {
      final r = await c.read(accionesTareasProvider).crear('Llamar a Acme', fechaVencimiento: '2026-10-30');
      expect(r.encolada, true);
      expect(r.valor!.id, lessThan(0));
      expect(r.valor!.asunto, 'Llamar a Acme');
      final p = (await cola.de(1, '3')).single;
      expect((p.metodo, p.ruta, p.tipo), ('POST', '/tareas-outlook', 'tarea.crear'));
      expect(p.cuerpoMapa, {'asunto': 'Llamar a Acme', 'fecha_vencimiento': '2026-10-30'});
      expect(p.clave, repo.claves.single); // si la primera petición sí llegó, el reenvío no duplica
      expect(p.localId, startsWith('local:'));
    });

    test('con red no se encola nada', () async {
      repo.sinRed = false;
      final r = await c.read(accionesTareasProvider).crear('Normal');
      expect(r.encolada, false);
      expect(await cola.contar(1, '3'), 0);
    });

    test('completar sin red guarda el cambio con la versión que se leyó y lo enseña hecho', () async {
      final t = TareaOutlook.fromJson({'id': 7, 'asunto': 'Preparar 303', 'estado': 'en_progreso', 'version': 4});
      final r = await c.read(accionesTareasProvider).transicionar(t, EstadoTarea.completada);
      expect(r.encolada, true);
      expect(r.valor!.estado, 'completada');
      final p = (await cola.de(1, '3')).single;
      expect((p.ruta, p.entidad), ('/tareas-outlook/7/transiciones', 'tarea:7'));
      expect(p.cuerpoMapa, {'estado': 'completada', 'version': 4});
    });

    test('un error de negocio NO se encola: se enseña', () async {
      repo.error = ApiException('Tarea bloqueada', codigo: 'tarea_bloqueada', status: 409);
      final t = TareaOutlook.fromJson({'id': 7, 'asunto': 'X', 'estado': 'en_progreso', 'version': 4});
      await expectLater(c.read(accionesTareasProvider).transicionar(t, EstadoTarea.completada), throwsA(isA<ApiException>()));
      expect(await cola.contar(1, '3'), 0);
    });

    test('comentar sin red', () async {
      expect(await c.read(accionesTareasProvider).comentar(7, 'Preparar 303', ' Listo '), true);
      final p = (await cola.de(1, '3')).single;
      expect(p.ruta, '/tareas-outlook/7/comentarios');
      expect(p.cuerpoMapa, {'texto': 'Listo'});
      expect(p.descripcion, 'Preparar 303: Listo');
    });

    test('la cola llena se avisa', () async {
      for (var i = 0; i < 200; i++) {
        await _encolar(cola, 'k$i', entidad: 'tarea:$i');
      }
      await expectLater(c.read(accionesTareasProvider).crear('Una más'), throwsA(isA<ColaLlena>()));
    });

    test('en la lista: la tarea creada sin red sale la primera, marcada pendiente, y sobrevive a recargar', () async {
      repo.paginas = [TareaOutlook.fromJson({'id': 1, 'asunto': 'Existente', 'estado': 'no_iniciada', 'version': 1})];
      c.read(tareasListaProvider);
      await Future<void>.delayed(Duration.zero);
      final n = c.read(tareasListaProvider.notifier);
      expect(await n.crear('Sin red'), true);
      var e = c.read(tareasListaProvider);
      expect(e.tareas.first.asunto, 'Sin red');
      expect(e.pendientes, contains(e.tareas.first.id));
      repo.sinRed = true;
      await n.recargar();
      e = c.read(tareasListaProvider);
      expect(e.tareas.map((t) => t.asunto), ['Sin red', 'Existente']);
      // cuando la cola envía algo, la lista se recarga con lo real
      repo.paginas = [TareaOutlook.fromJson({'id': 99, 'asunto': 'Sin red', 'estado': 'no_iniciada', 'version': 1})];
      await cola.vaciar(1); // la cola ya envió lo pendiente
      c.read(colaEnviadaProvider.notifier).avisar();
      for (var i = 0; i < 100 && c.read(tareasListaProvider).tareas.any((t) => t.id < 0); i++) {
        await Future<void>.delayed(const Duration(milliseconds: 20)); // la recarga lee SQLite de verdad
      }
      expect(c.read(tareasListaProvider).tareas.map((t) => t.id), [99]);
      expect(c.read(tareasListaProvider).pendientes, isEmpty);
    });
  });

  group('aviso de pendientes', () {
    Widget app(_ColaMemoria cola, ProcesadorCola proc) => ProviderScope(
          overrides: <Override>[
            colaEscrituraProvider.overrideWith((ref) {
              cola.alCambiar = () => ref.read(colaCambiosProvider.notifier).avisar(); // como en la app real
              return cola;
            }),
            procesadorColaProvider.overrideWithValue(proc),
            estadoSesionProvider.overrideWith(_Sesion.new),
          ],
          child: MaterialApp(
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            locale: const Locale('es'),
            home: const Scaffold(body: Column(children: [AvisoPendientes()])),
          ),
        );

    testWidgets('sin pendientes no enseña nada; con ellos, el contador y la lista con sus acciones', (t) async {
      final cola = _ColaMemoria();
      final enviadas = <String>[];
      final proc = ProcesadorCola(cola: cola, usuarioActivo: () => 1, despachoActivo: () => '3', ahoraMs: () => _ahora, enviar: (p) async {
        enviadas.add('${p.clave}:${p.cuerpoMapa?['version']}');
        return null;
      });
      await t.pumpWidget(app(cola, proc));
      await t.pumpAndSettle();
      expect(find.textContaining('pendiente'), findsNothing);

      await _encolar(cola, 'a', desc: 'Completar Preparar 303');
      final p2 = await _encolar(cola, 'b', entidad: 'tarea:2', desc: 'Llamar a Acme');
      await cola.marcar(p2.id, estado: EstadoPendiente.conflicto, error: 'Otra persona la ha cambiado', versionActual: 8);
      await t.pumpAndSettle();
      expect(find.text('2 cambios pendientes de enviar'), findsOneWidget);

      await t.tap(find.byType(AvisoPendientes));
      await t.pumpAndSettle();
      expect(find.text('Cambios sin enviar'), findsOneWidget);
      expect(find.text('Completar Preparar 303'), findsOneWidget);
      expect(find.textContaining('Alguien lo ha cambiado'), findsOneWidget);
      expect(find.text('Aplicar igualmente'), findsOneWidget); // solo en el conflicto

      await t.tap(find.text('Aplicar igualmente'));
      await t.pumpAndSettle();
      // «aplicar igualmente» la dejó lista con la versión que hay ahora y el procesador la envió
      expect(enviadas, contains('b:8'));

      expect(ProviderScope.containerOf(t.element(find.byType(AvisoPendientes))).read(numPendientesProvider), 0); // salieron las dos

      await _encolar(cola, 'c', entidad: 'tarea:3', desc: 'Otra cosa');
      await t.pumpAndSettle();
      expect(find.text('Otra cosa'), findsOneWidget);
      await t.tap(find.byTooltip('Descartar'));
      await t.pumpAndSettle();
      expect(find.text('Otra cosa'), findsNothing);
      expect(await cola.contar(1, '3'), 0);
    });
  });
}

/// La cola en memoria, para las pruebas de pantalla (con SQLite de verdad el reloj simulado de `testWidgets` no deja terminar las consultas).
class _ColaMemoria extends ColaEscritura {
  final List<Pendiente> _filas = [];
  int _sig = 1;
  _ColaMemoria() : super(abrir: () async => throw UnimplementedError());

  @override
  Future<Pendiente> encolar({required String metodo, required String ruta, Map<String, dynamic>? cuerpo, required String clave, required int usuarioId, required String despachoId, required String entidad, required String tipo, required String descripcion, String? localId}) async {
    final p = _con(Pendiente(id: _sig++, metodo: metodo, ruta: ruta, cuerpo: cuerpo == null ? null : jsonEncode(cuerpo), clave: clave, usuarioId: usuarioId, despachoId: despachoId, entidad: entidad, tipo: tipo, descripcion: descripcion, creadaEnMs: _ahora, intentos: 0, estado: EstadoPendiente.pendiente, error: null, proximoIntentoMs: 0, versionActual: null, localId: localId));
    _filas.add(p);
    alCambiar?.call();
    return p;
  }

  Pendiente _con(Pendiente p, {EstadoPendiente? estado, String? error, bool sinError = false, int? versionActual, bool sinVersion = false, String? cuerpo, int? proximo}) => Pendiente(
        id: p.id, metodo: p.metodo, ruta: p.ruta, cuerpo: cuerpo ?? p.cuerpo, clave: p.clave, usuarioId: p.usuarioId, despachoId: p.despachoId, entidad: p.entidad, tipo: p.tipo,
        descripcion: p.descripcion, creadaEnMs: p.creadaEnMs, intentos: p.intentos, estado: estado ?? p.estado, error: sinError ? null : (error ?? p.error), proximoIntentoMs: proximo ?? p.proximoIntentoMs,
        versionActual: sinVersion ? null : (versionActual ?? p.versionActual), localId: p.localId,
      );

  void _reemplazar(int id, Pendiente Function(Pendiente) f) {
    final i = _filas.indexWhere((p) => p.id == id);
    if (i >= 0) _filas[i] = f(_filas[i]);
    alCambiar?.call();
  }

  @override
  Future<List<Pendiente>> de(int usuarioId, String despachoId) async => _filas.where((p) => p.usuarioId == usuarioId && p.despachoId == despachoId).toList();
  @override
  Future<Pendiente?> uno(int id) async => _filas.where((p) => p.id == id).firstOrNull;
  @override
  Future<int> contar(int usuarioId, String despachoId) async => (await de(usuarioId, despachoId)).length;
  @override
  Future<void> marcar(int id, {EstadoPendiente? estado, int? intentos, String? error, bool borrarError = false, int? proximoIntentoMs, int? versionActual}) async =>
      _reemplazar(id, (p) => _con(p, estado: estado, error: error, sinError: borrarError, versionActual: versionActual, proximo: proximoIntentoMs));
  @override
  Future<void> reintentarConVersion(int id, int version) async {
    _reemplazar(id, (p) {
      final c = p.cuerpoMapa;
      if (c != null && c.containsKey('version')) c['version'] = version;
      return _con(p, estado: EstadoPendiente.pendiente, sinError: true, sinVersion: true, cuerpo: c == null ? null : jsonEncode(c), proximo: 0);
    });
  }

  @override
  Future<void> reintentarAhora(int id) async => _reemplazar(id, (p) => _con(p, estado: EstadoPendiente.pendiente, sinError: true, proximo: 0));
  @override
  Future<void> eliminar(int id) async {
    _filas.removeWhere((p) => p.id == id);
    alCambiar?.call();
  }

  @override
  Future<int> purgarCaducadas() async => 0;
  @override
  Future<void> reiniciarEnviando() async {}
  @override
  Future<void> sustituirIdLocal(String localId, Object idReal) async {}
}

class _Sesion extends SesionControl {
  @override
  EstadoSesion build() => EstadoSesion(fase: FaseSesion.conSesion, usuario: Usuario(id: 1, email: 'a@b.c'), despacho: '3');
}

/// Repositorio que falla por falta de red (o con el error que se le diga) y recuerda las claves de idempotencia que recibió.
class _RepoSinRed implements TareasRepositorio {
  bool sinRed = true;
  ApiException? error;
  final List<String> claves = [];
  List<TareaOutlook> paginas = [];

  void _falla(String? clave) {
    if (clave != null) claves.add(clave);
    if (error != null) throw error!;
    if (sinRed) throw ApiException('sin red', esDeConexion: true);
  }

  @override
  Future<TareaOutlook> crear({required String asunto, String? fechaVencimiento, PrioridadTarea? prioridad, String? clave}) async {
    _falla(clave);
    return TareaOutlook.fromJson({'id': 500, 'asunto': asunto, 'estado': 'no_iniciada', 'version': 1});
  }

  @override
  Future<TareaOutlook> transicionar(int id, EstadoTarea estado, {String? motivo, int? version, String? clave}) async {
    _falla(clave);
    return TareaOutlook.fromJson({'id': id, 'asunto': 'x', 'estado': estado.valor, 'version': (version ?? 0) + 1});
  }

  @override
  Future<void> comentar(int id, String texto, {String? clave}) async => _falla(clave);

  @override
  Future<List<TareaOutlook>> listar({String ambito = 'propias', String? estado, String? q, int limit = 30, int offset = 0}) async => paginas;

  @override
  dynamic noSuchMethod(Invocation invocation) => throw UnimplementedError('${invocation.memberName}');
}
