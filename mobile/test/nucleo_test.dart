import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/nucleo/capacidades.dart';
import 'package:guilda_work_mobile/nucleo/paginas.dart';
import 'package:guilda_work_mobile/nucleo/rutas.dart';
import 'package:guilda_work_mobile/nucleo/servicios.dart';
import 'package:guilda_work_mobile/nucleo/sesion.dart';
import 'package:guilda_work_mobile/nucleo/version.dart';
import 'package:guilda_work_mobile/services/api_client.dart';
import 'package:shared_preferences/shared_preferences.dart';

final _usuario = Usuario(id: 1, email: 'a@b.c');
const _cap2 = Capacidades(despachos: [
  Despacho(id: '3', nombre: 'Gestoría Pla', principal: true),
  Despacho(id: '8', nombre: 'Inmobiliaria Costa'),
]);

/// La sesión con un estado fijo (sin pedir nada al servidor); el resto de métodos son los reales.
class _SesionFija extends SesionControl {
  final EstadoSesion inicial;
  _SesionFija(this.inicial);
  @override
  EstadoSesion build() => inicial;
}

PaginasApp _paginasFalsas() => PaginasApp(
      login: (_) => const Scaffold(body: Text('LOGIN')),
      inicio: (_, _) => const Scaffold(body: Text('INICIO')),
      tareas: (_) => const Scaffold(body: Text('TAREAS')),
      correo: (_) => const Scaffold(body: Text('CORREO')),
      fichaje: (_, _) => const Scaffold(body: Text('FICHAJE')),
      accesosMas: (_, _) => [AccesoMas(Icons.settings, ClaveEtiqueta.ajustes, (_) => const Scaffold(body: Text('AJUSTES')))],
    );

Widget _app(EstadoSesion estado, {ProviderContainer? contenedor}) => UncontrolledProviderScope(
      container: contenedor ?? _contenedor(estado),
      child: Consumer(
        builder: (context, ref, _) => MaterialApp.router(
          routerConfig: ref.watch(routerProvider),
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: const Locale('es'),
        ),
      ),
    );

ProviderContainer _contenedor(EstadoSesion estado) => ProviderContainer(overrides: [
      estadoSesionProvider.overrideWith(() => _SesionFija(estado)),
      paginasProvider.overrideWithValue(_paginasFalsas()),
      serviciosProvider.overrideWithValue(Servicios.reales()),
    ]);

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('redirigir', () {
    test('arrancando → arranque; sin sesión → login; con sesión → inicio', () {
      expect(redirigir(const EstadoSesion(), rutaInicio), rutaArranque);
      expect(redirigir(const EstadoSesion(), rutaArranque), null);
      expect(redirigir(const EstadoSesion(fase: FaseSesion.sinSesion), rutaTareas), rutaLogin);
      expect(redirigir(const EstadoSesion(fase: FaseSesion.sinSesion), rutaLogin), null);
      final con = EstadoSesion(fase: FaseSesion.conSesion, usuario: _usuario);
      expect(redirigir(con, rutaLogin), rutaInicio);
      expect(redirigir(con, rutaArranque), rutaInicio);
      expect(redirigir(con, rutaCorreo), null);
    });

    test('una versión no admitida gana a todo', () {
      for (final f in FaseSesion.values) {
        final e = EstadoSesion(fase: f, actualizar: true);
        expect(redirigir(e, rutaLogin), rutaActualizar);
        expect(redirigir(e, rutaActualizar), null);
      }
    });
  });

  group('Capacidades', () {
    test('lee despachos, módulos, permisos y versión mínima', () {
      final c = Capacidades.desdeJson({
        'despachos': [
          {'id': 3, 'nombre': 'Pla', 'principal': true},
          {'id': 8, 'nombre': 'Costa'},
        ],
        'modulos': {'gestoria': true, 'abogados': false},
        'permisos': {'fichaje_admin': true},
        'app': {'version_minima': '1.1.0', 'url_tienda': 'https://tienda'},
      });
      expect(c.variosDespachos, true);
      expect(c.despachoPrincipal!.id, '3');
      expect(c.despachoPorId('8')!.nombre, 'Costa');
      expect(c.modulo('gestoria'), true);
      expect(c.modulo('abogados'), false);
      expect(c.modulo('inexistente'), false);
      expect(c.permiso('fichaje_admin'), true);
      expect(c.app.versionMinima, '1.1.0');
    });

    test('un servidor anterior a 1.5 (sin nada de esto) deja la app como siempre', () {
      final c = Capacidades.desdeJson({'id': 1, 'email': 'a@b.c'});
      expect(c.variosDespachos, false);
      expect(c.despachoPrincipal, null);
      expect(c.modulo('lo_que_sea'), true);
      expect(c.app.versionMinima, null);
    });
  });

  test('compararVersiones', () {
    expect(compararVersiones('1.0.0', '1.1.0') < 0, true);
    expect(compararVersiones('1.10.0', '1.9.9') > 0, true);
    expect(compararVersiones('1.2', '1.2.0'), 0);
    expect(compararVersiones('1.2.3+45', '1.2.3'), 0);
  });

  group('Barra inferior', () {
    testWidgets('empieza en Inicio y cada pestaña conserva su pantalla', (t) async {
      await t.pumpWidget(_app(EstadoSesion(fase: FaseSesion.conSesion, usuario: _usuario)));
      await t.pumpAndSettle();
      expect(find.text('INICIO'), findsOneWidget);
      for (final e in ['Inicio', 'Tareas', 'Correo', 'Fichaje', 'Más']) {
        expect(find.text(e), findsWidgets);
      }
      await t.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('Tareas')));
      await t.pumpAndSettle();
      expect(find.text('TAREAS'), findsOneWidget);
      await t.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('Fichaje')));
      await t.pumpAndSettle();
      expect(find.text('FICHAJE'), findsOneWidget);
    });

    testWidgets('sin sesión muestra el login y sin barra', (t) async {
      await t.pumpWidget(_app(const EstadoSesion(fase: FaseSesion.sinSesion)));
      await t.pumpAndSettle();
      expect(find.text('LOGIN'), findsOneWidget);
      expect(find.byType(NavigationBar), findsNothing);
    });

    testWidgets('versión no admitida enseña «Actualiza la app»', (t) async {
      await t.pumpWidget(_app(EstadoSesion(fase: FaseSesion.conSesion, usuario: _usuario, actualizar: true)));
      await t.pumpAndSettle();
      expect(find.text('Actualiza la app'), findsOneWidget);
      expect(find.byType(NavigationBar), findsNothing);
    });

    testWidgets('con un solo despacho «Más» no enseña el selector', (t) async {
      await t.pumpWidget(_app(EstadoSesion(fase: FaseSesion.conSesion, usuario: _usuario)));
      await t.pumpAndSettle();
      await t.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('Más')));
      await t.pumpAndSettle();
      expect(find.text('Despacho activo'), findsNothing);
      expect(find.text('Ajustes'), findsOneWidget);
    });

    testWidgets('cambiar de despacho guarda la elección y recarga la app desde Inicio', (t) async {
      final contenedor = _contenedor(EstadoSesion(fase: FaseSesion.conSesion, usuario: _usuario, capacidades: _cap2, despacho: '3'));
      await t.pumpWidget(_app(const EstadoSesion(), contenedor: contenedor));
      await t.pumpAndSettle();
      await t.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('Más')));
      await t.pumpAndSettle();
      expect(find.text('Gestoría Pla'), findsOneWidget);
      await t.tap(find.text('Despacho activo'));
      await t.pumpAndSettle();
      await t.tap(find.text('Inmobiliaria Costa'));
      await t.pumpAndSettle();
      expect(contenedor.read(estadoSesionProvider).despacho, '8');
      expect((await SharedPreferences.getInstance()).getString('despacho_activo'), '8');
      expect(contenedor.read(serviciosProvider).api.despacho, '8');
      // el enrutador se rehízo: vuelve a Inicio, sin la pantalla «Más» del despacho anterior
      expect(find.text('INICIO'), findsOneWidget);
    });
  });

  test('cambiarDespacho ignora un despacho que no es de la persona', () async {
    final c = _contenedor(EstadoSesion(fase: FaseSesion.conSesion, usuario: _usuario, capacidades: _cap2, despacho: '3'));
    addTearDown(c.dispose);
    await c.read(estadoSesionProvider.notifier).cambiarDespacho('999');
    expect(c.read(estadoSesionProvider).despacho, '3');
  });

  test('requerirActualizacion y cerrar', () async {
    final c = _contenedor(EstadoSesion(fase: FaseSesion.conSesion, usuario: _usuario, despacho: '3'));
    addTearDown(c.dispose);
    c.read(estadoSesionProvider.notifier).requerirActualizacion();
    expect(c.read(estadoSesionProvider).actualizar, true);
    await c.read(estadoSesionProvider.notifier).cerrar();
    expect(c.read(estadoSesionProvider).fase, FaseSesion.sinSesion);
    expect(c.read(estadoSesionProvider).despacho, null);
  });
}
