import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/api/errores.dart';
import 'package:guilda_work_mobile/api/generado/modelos.g.dart';
import 'package:guilda_work_mobile/funciones/hoy/hoy_controlador.dart';
import 'package:guilda_work_mobile/funciones/hoy/hoy_screen.dart';
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/nucleo/abrir_destino.dart';
import 'package:guilda_work_mobile/nucleo/avisos.dart';
import 'package:guilda_work_mobile/nucleo/destinos.dart';
import 'package:guilda_work_mobile/nucleo/sesion.dart';
import 'package:guilda_work_mobile/services/push_service.dart';

void main() {
  group('Destino.desdePush', () {
    test('lee el contrato nuevo: destino en JSON', () {
      final d = Destino.desdePush({'destino': jsonEncode({'tipo': 'tarea', 'id': 12}), 'tipo': 'tarea_recordatorio'});
      expect(d.tipo, 'tarea');
      expect(d.id, 12);
    });

    test('o destino_tipo / destino_id sueltos (todo llega como texto en el push)', () {
      final d = Destino.desdePush({'destino_tipo': 'vencimiento', 'destino_id': '41'});
      expect((d.tipo, d.id), ('vencimiento', 41));
    });

    test('conserva ids relacionados (cuenta_id, mensaje_id...)', () {
      final d = Destino.desdePush({'destino': '{"tipo":"correo","cuenta_id":2}'});
      expect(d.tipo, 'correo');
      expect(d.extra['cuenta_id'], 2);
    });

    test('un push antiguo (solo tipo) sigue funcionando; uno ilegible cae en «aviso»', () {
      expect(Destino.desdePush({'tipo': 'correo_nuevo'}).tipo, 'correo');
      expect(Destino.desdePush({'tipo': 'otro'}).tipo, 'aviso');
      expect(Destino.desdePush({'destino': '{roto'}).tipo, 'aviso');
      expect(Destino.desdePush({}).tipo, 'aviso');
    });
  });

  group('resolverDestino', () {
    test('lo que tiene pantalla nativa', () {
      expect(resolverDestino(const Destino('tarea', 5)), isA<AbrirTarea>().having((a) => a.id, 'id', 5));
      expect(resolverDestino(const Destino('correo', 9)), isA<AbrirCorreo>().having((a) => a.id, 'id', 9));
      expect(resolverDestino(const Destino('correo', null, {'mensaje_id': 3})), isA<AbrirCorreo>().having((a) => a.id, 'id', 3));
      expect(resolverDestino(const Destino('correo')), isA<AbrirCorreo>().having((a) => a.id, 'id', null));
      expect(resolverDestino(const Destino('vencimiento', 41)), isA<AbrirVencimiento>());
      expect(resolverDestino(const Destino('ausencia', 2)), isA<AbrirPantalla>().having((a) => a.clave, 'clave', 'ausencias'));
      expect(resolverDestino(const Destino('ausencias')), isA<AbrirPantalla>());
    });

    test('pestañas', () {
      for (final (tipo, ruta) in [('fichaje', '/fichaje'), ('turnos', '/fichaje'), ('bolsa_horas', '/fichaje'), ('hoy', '/inicio'), ('aviso', '/inicio')]) {
        expect(resolverDestino(Destino(tipo)), isA<IrAPestana>().having((a) => a.ruta, 'ruta', ruta), reason: tipo);
      }
    });

    test('sin id no se inventa una ficha', () {
      expect(resolverDestino(const Destino('tarea')), isA<IrAPestana>());
      expect(resolverDestino(const Destino('vencimiento')), isA<SoloWeb>());
    });

    test('lo que aún no tiene pantalla se ofrece en la web', () {
      for (final tipo in ['plazo', 'expediente', 'visita', 'traspaso', 'factura', 'contabilizacion', 'certificado', 'aviso_fiscal', 'algo_nuevo']) {
        expect(resolverDestino(Destino(tipo, 1)), isA<SoloWeb>(), reason: tipo);
      }
    });
  });

  group('NavegadorDeAvisos', () {
    late bool sesion;
    late String? activo;
    late bool respuesta;
    late List<String> registro;
    late NavegadorDeAvisos nav;

    setUp(() {
      sesion = true;
      activo = '3';
      respuesta = true;
      registro = [];
      nav = NavegadorDeAvisos(
        haySesion: () => sesion,
        despachoActivo: () => activo,
        despachosPropios: () => {'3', '8'},
        confirmarCambio: (id) async {
          registro.add('pregunta:$id');
          return respuesta;
        },
        cambiarDespacho: (id) async {
          registro.add('cambia:$id');
          activo = id;
        },
        abrir: (d, {urlWeb}) async => registro.add('abre:${d.tipo}:${d.id}:${urlWeb ?? '-'}'),
      );
    });

    final tarea = {'destino': '{"tipo":"tarea","id":12}', 'despacho_id': '3', 'url': '/tareas/12'};

    test('con sesión y del despacho activo, abre directamente', () async {
      await nav.abrirDesdePush(tarea);
      expect(registro, ['abre:tarea:12:/tareas/12']);
    });

    test('sin sesión lo guarda y lo abre al iniciarla', () async {
      sesion = false;
      await nav.abrirDesdePush(tarea);
      expect(registro, isEmpty);
      expect(nav.hayPendiente, true);
      await nav.aplicarPendiente(); // sigue sin sesión
      expect(registro, isEmpty);
      sesion = true;
      await nav.aplicarPendiente();
      expect(registro, ['abre:tarea:12:/tareas/12']);
      expect(nav.hayPendiente, false);
      await nav.aplicarPendiente(); // no se repite
      expect(registro.length, 1);
    });

    test('de otro despacho suyo: pregunta, cambia y abre', () async {
      await nav.abrirDesdePush({...tarea, 'despacho_id': '8'});
      expect(registro, ['pregunta:8', 'cambia:8', 'abre:tarea:12:/tareas/12']);
    });

    test('si dice que no, no cambia ni abre', () async {
      respuesta = false;
      await nav.abrirDesdePush({...tarea, 'despacho_id': '8'});
      expect(registro, ['pregunta:8']);
      expect(activo, '3');
    });

    test('un despacho que no es suyo o ausente no provoca cambio', () async {
      await nav.abrirDesdePush({...tarea, 'despacho_id': '99'});
      await nav.abrirDesdePush({'destino': '{"tipo":"tarea","id":1}'});
      expect(registro.where((e) => e.startsWith('pregunta') || e.startsWith('cambia')), isEmpty);
      expect(registro.where((e) => e.startsWith('abre')).length, 2);
    });
  });

  group('Pantalla «Hoy»', () {
    final ahora = DateTime(2026, 10, 24, 9, 5);
    // Las fechas se escriben relativas a HOY (la app dice «hoy», «ayer»...), así la prueba no depende del día en que se ejecute.
    String dia(int desplazamiento) {
      final d = DateTime.now().add(Duration(days: desplazamiento));
      return '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
    }

    BandejaHoy bandeja() => BandejaHoy.fromJson({
          'total': 3,
          'urgentes': 2,
          'secciones': [
            {
              'clave': 'tareas', 'titulo': 'Tareas', 'total': 2, 'urgentes': 1,
              'elementos': [
                {'titulo': 'Llamar a Acme', 'detalle': null, 'fecha': dia(-1), 'urgencia': 'vencido', 'destino': {'tipo': 'tarea', 'id': 5}, 'acciones': ['abrir', 'completar'], 'url': '/tareas/5'},
                {'titulo': 'Revisar contrato', 'fecha': '${dia(0)}T10:30', 'urgencia': 'hoy', 'destino': {'tipo': 'tarea', 'id': 6}, 'acciones': ['abrir', 'completar']},
              ],
            },
            {
              'clave': 'vencimientos', 'titulo': 'Vencimientos fiscales', 'total': 1, 'urgentes': 1,
              'elementos': [
                {'titulo': '303 · Talleres Soler SL', 'fecha': '${dia(0)}T00:00', 'urgencia': 'hoy', 'destino': {'tipo': 'vencimiento', 'id': 41}, 'acciones': ['abrir', 'presentar'], 'url': '/fiscal/vencimientos/41/editar'},
              ],
            },
          ],
        });

    Widget app(Future<EstadoHoy> Function() datos, List<(Destino, String?)> abiertos) => ProviderScope(
          overrides: [
            hoyProvider.overrideWith(() => _HoyFalso(datos)),
            estadoSesionProvider.overrideWith(() => _SesionFija(const EstadoSesion(fase: FaseSesion.conSesion))),
            navegadorDeAvisosProvider.overrideWithValue(NavegadorDeAvisos(
              haySesion: () => true,
              despachoActivo: () => null,
              despachosPropios: () => {},
              confirmarCambio: (_) async => true,
              cambiarDespacho: (_) async {},
              abrir: (d, {urlWeb}) async => abiertos.add((d, urlWeb)),
            )),
          ],
          child: MaterialApp(
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            locale: const Locale('es'),
            home: const HoyScreen(),
          ),
        );

    testWidgets('enseña el resumen, las secciones y los elementos con su fecha', (t) async {
      t.view.physicalSize = const Size(800, 2400); // con «Lo siguiente» arriba, el resto de la lista queda más abajo
      t.view.devicePixelRatio = 1;
      addTearDown(t.view.reset);
      await t.pumpWidget(app(() async => EstadoHoy(bandeja(), ahora), []));
      await t.pumpAndSettle();
      // Dos números grandes (pendientes y urgentes) y, arriba, lo más urgente con su botón.
      expect(find.text('Pendientes'), findsOneWidget);
      expect(find.text('Urgentes'), findsOneWidget);
      expect(find.text('3'), findsOneWidget);
      expect(find.text('Lo siguiente'), findsOneWidget);
      expect(find.text('Tareas'), findsOneWidget);
      expect(find.text('2'), findsWidgets, reason: 'la cuenta de la sección va en su píldora (y los urgentes en su contador)');
      expect(find.text('Llamar a Acme'), findsWidgets); // en «Lo siguiente» y en su sección
      expect(find.text('ayer'), findsWidgets); // fecha relativa, una sola forma de escribirla en toda la app
      expect(find.text('hoy 10:30'), findsOneWidget);
      expect(find.text('hoy'), findsOneWidget); // 00:00 no enseña hora
    });

    testWidgets('tocar un elemento abre su destino con la URL de la web como respaldo', (t) async {
      t.view.physicalSize = const Size(800, 2400); // con «Lo siguiente» arriba, el resto de la lista queda más abajo
      t.view.devicePixelRatio = 1;
      addTearDown(t.view.reset);
      final abiertos = <(Destino, String?)>[];
      await t.pumpWidget(app(() async => EstadoHoy(bandeja(), ahora), abiertos));
      await t.pumpAndSettle();
      await t.tap(find.text('303 · Talleres Soler SL').last);
      expect(abiertos.single.$1.tipo, 'vencimiento');
      expect(abiertos.single.$1.id, 41);
      expect(abiertos.single.$2, '/fiscal/vencimientos/41/editar');
    });

    testWidgets('solo las tareas se pueden completar desde la lista', (t) async {
      t.view.physicalSize = const Size(800, 2400); // con «Lo siguiente» arriba, el resto de la lista queda más abajo
      t.view.devicePixelRatio = 1;
      addTearDown(t.view.reset);
      await t.pumpWidget(app(() async => EstadoHoy(bandeja(), ahora), []));
      await t.pumpAndSettle();
      expect(find.byTooltip('Completar'), findsNWidgets(2));
    });

    testWidgets('sin nada pendiente: «Todo al día»', (t) async {
      await t.pumpWidget(app(() async => EstadoHoy(const BandejaHoy(total: 0, urgentes: 0, secciones: []), ahora), []));
      await t.pumpAndSettle();
      expect(find.text('Todo al día'), findsOneWidget);
    });

    testWidgets('si el refresco falló, avisa de que los datos son de antes', (t) async {
      await t.pumpWidget(app(() async => EstadoHoy(bandeja(), ahora, desactualizado: true), []));
      await t.pumpAndSettle();
      expect(find.text('Sin conexión · datos de las 09:05'), findsOneWidget);
      expect(find.text('Llamar a Acme'), findsWidgets);
    });

    testWidgets('sin datos y con error: mensaje y reintentar', (t) async {
      await t.pumpWidget(app(() async => throw ApiException('sin red', esDeConexion: true), []));
      await t.pumpAndSettle();
      expect(find.text('Sin conexión. Comprueba tu red e inténtalo de nuevo.'), findsOneWidget); // el texto sale de la categoría del error
      expect(find.text('Reintentar'), findsOneWidget);
    });
  });

  test('los canales de Android son los mismos que manda el servidor', () {
    expect(PushService.canales, ['tareas', 'correo', 'fiscal', 'equipo', 'resumenes', 'general']);
  });
}

class _HoyFalso extends HoyControlador {
  final Future<EstadoHoy> Function() datos;
  _HoyFalso(this.datos);
  @override
  Future<EstadoHoy> build() => datos();
}

class _SesionFija extends SesionControl {
  final EstadoSesion inicial;
  _SesionFija(this.inicial);
  @override
  EstadoSesion build() => inicial;
}
