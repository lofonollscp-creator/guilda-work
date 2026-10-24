import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/nucleo/bloqueo.dart';
import 'package:guilda_work_mobile/nucleo/pantalla_bloqueo.dart';
import 'package:guilda_work_mobile/nucleo/sesion.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Bio implements Biometria {
  bool hay = true;
  bool acierta = true;
  final motivos = <String>[];
  @override
  Future<bool> disponible() async => hay;
  @override
  Future<bool> autenticar(String motivo) async {
    motivos.add(motivo);
    return acierta;
  }
}

class _Sesion extends SesionControl {
  @override
  EstadoSesion build() => const EstadoSesion(fase: FaseSesion.conSesion);
}

void main() {
  late _Bio bio;
  late DateTime ahora;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    bio = _Bio();
    ahora = DateTime(2026, 10, 25, 9);
  });

  Future<ProviderContainer> montar({Map<String, Object> prefs = const {}}) async {
    SharedPreferences.setMockInitialValues(prefs);
    final c = ProviderContainer(overrides: [biometriaProvider.overrideWithValue(bio), relojProvider.overrideWithValue(() => ahora)]);
    addTearDown(c.dispose);
    c.read(bloqueoProvider);
    await c.read(bloqueoProvider.notifier).alEntrarConSesion(arranqueEnFrio: false); // espera a que carguen las preferencias
    return c;
  }

  EstadoBloqueo estado(ProviderContainer c) => c.read(bloqueoProvider);
  BloqueoControl control(ProviderContainer c) => c.read(bloqueoProvider.notifier);

  group('activar y desactivar', () {
    test('activar exige identificarse y se recuerda', () async {
      final c = await montar();
      expect(estado(c).disponible, true);
      expect(estado(c).activo, false);
      expect(await control(c).activar('motivo activar'), true);
      expect(bio.motivos, ['motivo activar']);
      expect(estado(c).activo, true);
      expect((await SharedPreferences.getInstance()).getBool('bloqueo_biometrico'), true);
    });

    test('si no se identifica, no se activa', () async {
      final c = await montar();
      bio.acierta = false;
      expect(await control(c).activar('x'), false);
      expect(estado(c).activo, false);
    });

    test('sin huella, Face ID ni código en el móvil no se puede activar', () async {
      bio.hay = false;
      final c = await montar();
      expect(estado(c).disponible, false);
      expect(await control(c).activar('x'), false);
      expect(bio.motivos, isEmpty);
    });

    test('desactivar también exige identificarse (quien coge el móvil desbloqueado no puede quitarlo)', () async {
      final c = await montar(prefs: {'bloqueo_biometrico': true});
      expect(estado(c).activo, true);
      bio.acierta = false;
      expect(await control(c).desactivar('x'), false);
      expect(estado(c).activo, true);
      bio.acierta = true;
      expect(await control(c).desactivar('x'), true);
      expect(estado(c).activo, false);
      expect((await SharedPreferences.getInstance()).getBool('bloqueo_biometrico'), false);
    });

    test('si el móvil ya no tiene ninguna protección, el bloqueo se apaga solo (no deja a nadie fuera)', () async {
      bio.hay = false;
      final c = await montar(prefs: {'bloqueo_biometrico': true});
      expect(estado(c).activo, false);
    });
  });

  group('cuándo se bloquea', () {
    test('abierta con la sesión guardada: bloqueada; acabando de escribir la contraseña: no', () async {
      final c = await montar(prefs: {'bloqueo_biometrico': true});
      await control(c).alEntrarConSesion(arranqueEnFrio: false);
      expect(estado(c).bloqueada, false);
      await control(c).alEntrarConSesion(arranqueEnFrio: true);
      expect(estado(c).bloqueada, true);
    });

    test('sin el bloqueo activado nunca se bloquea', () async {
      final c = await montar();
      await control(c).alEntrarConSesion(arranqueEnFrio: true);
      control(c).alCambiarCiclo(AppLifecycleState.paused);
      ahora = ahora.add(const Duration(hours: 1));
      control(c).alCambiarCiclo(AppLifecycleState.resumed);
      expect(estado(c).bloqueada, false);
      expect(estado(c).cubierta, false);
    });

    test('un momento en otra app no bloquea; más de 30 segundos, sí', () async {
      final c = await montar(prefs: {'bloqueo_biometrico': true});
      control(c).alCambiarCiclo(AppLifecycleState.paused);
      ahora = ahora.add(const Duration(seconds: 20));
      control(c).alCambiarCiclo(AppLifecycleState.resumed);
      expect(estado(c).bloqueada, false);

      control(c).alCambiarCiclo(AppLifecycleState.paused);
      ahora = ahora.add(const Duration(seconds: 45));
      control(c).alCambiarCiclo(AppLifecycleState.resumed);
      expect(estado(c).bloqueada, true);
    });

    test('al perder el foco se cubre (selector de apps) y al recuperarlo se descubre', () async {
      final c = await montar(prefs: {'bloqueo_biometrico': true});
      control(c).alCambiarCiclo(AppLifecycleState.inactive);
      expect(estado(c).cubierta, true);
      control(c).alCambiarCiclo(AppLifecycleState.resumed);
      expect(estado(c).cubierta, false);
      expect(estado(c).bloqueada, false);
    });

    test('mientras se identifica, la ventana del sistema (que quita el foco) no vuelve a bloquear ni a cubrir', () async {
      final c = await montar(prefs: {'bloqueo_biometrico': true});
      await control(c).alEntrarConSesion(arranqueEnFrio: true);
      final pendiente = control(c).desbloquear('x');
      control(c).alCambiarCiclo(AppLifecycleState.inactive); // el diálogo de Face ID
      expect(estado(c).cubierta, false);
      await pendiente;
      expect(estado(c).bloqueada, false);
    });
  });

  group('desbloquear', () {
    test('identificándose se desbloquea; si falla o se cancela, sigue bloqueada', () async {
      final c = await montar(prefs: {'bloqueo_biometrico': true});
      await control(c).alEntrarConSesion(arranqueEnFrio: true);
      bio.acierta = false;
      expect(await control(c).desbloquear('x'), false);
      expect(estado(c).bloqueada, true);
      bio.acierta = true;
      expect(await control(c).desbloquear('x'), true);
      expect(estado(c).bloqueada, false);
    });

    test('al cerrar sesión se quita el bloqueo (no queda nada que proteger)', () async {
      final c = await montar(prefs: {'bloqueo_biometrico': true});
      await control(c).alEntrarConSesion(arranqueEnFrio: true);
      await control(c).alCerrarSesion();
      expect(estado(c).bloqueada, false);
    });
  });

  group('la oferta', () {
    test('no en el primer inicio; sí desde el segundo; una sola vez', () async {
      final c = ProviderContainer(overrides: [biometriaProvider.overrideWithValue(bio)]);
      addTearDown(c.dispose);
      SharedPreferences.setMockInitialValues({});
      c.read(bloqueoProvider);
      await control(c).alEntrarConSesion(arranqueEnFrio: false);
      expect(estado(c).inicios, 1);
      expect(estado(c).debeOfrecer, false);
      await control(c).alEntrarConSesion(arranqueEnFrio: false);
      expect(estado(c).debeOfrecer, true);
      await control(c).ofertaAtendida();
      expect(estado(c).debeOfrecer, false);
      expect((await SharedPreferences.getInstance()).getBool('bloqueo_oferta_vista'), true);
    });

    test('no se ofrece si el móvil no puede o si ya está activado', () async {
      bio.hay = false;
      var c = await montar(prefs: {'bloqueo_inicios': 5});
      expect(estado(c).debeOfrecer, false);
      bio.hay = true;
      c = await montar(prefs: {'bloqueo_inicios': 5, 'bloqueo_biometrico': true});
      expect(estado(c).debeOfrecer, false);
    });
  });

  group('pantallas', () {
    Widget app(Widget hijo, List<Override> over) => ProviderScope(
          overrides: over,
          child: MaterialApp(
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            locale: const Locale('es'),
            home: Scaffold(body: hijo),
          ),
        );

    testWidgets('la pantalla de bloqueo pide identificarse sola y ofrece reintentar y salir', (t) async {
      SharedPreferences.setMockInitialValues({'bloqueo_biometrico': true});
      bio.acierta = false;
      await t.pumpWidget(app(const PantallaBloqueo(), [biometriaProvider.overrideWithValue(bio), estadoSesionProvider.overrideWith(_Sesion.new)]));
      await t.pumpAndSettle();
      expect(find.text('Guilda Work está bloqueada'), findsOneWidget);
      expect(bio.motivos, ['Desbloquea Guilda Work']); // lo pidió sin tocar nada
      expect(find.text('Desbloquear'), findsOneWidget);
      expect(find.text('Cerrar sesión'), findsOneWidget);
      bio.acierta = true;
      await t.tap(find.text('Desbloquear'));
      await t.pumpAndSettle();
      expect(bio.motivos.length, 2);
    });

    testWidgets('el interruptor de Ajustes activa y desactiva identificándose, y avisa si el móvil no puede', (t) async {
      SharedPreferences.setMockInitialValues({});
      await t.pumpWidget(app(const InterruptorBloqueo(), [biometriaProvider.overrideWithValue(bio)]));
      await t.pumpAndSettle();
      expect(find.text('Pide tu huella, tu cara o el código del móvil al abrir la app'), findsOneWidget);
      await t.tap(find.byType(Switch));
      await t.pumpAndSettle();
      expect(bio.motivos, ['Confirma que eres tú para activar el bloqueo']);
      expect(t.widget<Switch>(find.byType(Switch)).value, true);
      await t.tap(find.byType(Switch));
      await t.pumpAndSettle();
      expect(bio.motivos.last, 'Confirma que eres tú para desactivar el bloqueo');
      expect(t.widget<Switch>(find.byType(Switch)).value, false);
    });

    testWidgets('sin protección en el móvil, el interruptor queda apagado con la explicación', (t) async {
      SharedPreferences.setMockInitialValues({});
      bio.hay = false;
      await t.pumpWidget(app(const InterruptorBloqueo(), [biometriaProvider.overrideWithValue(bio)]));
      await t.pumpAndSettle();
      expect(find.text('Este móvil no tiene huella, Face ID ni código de bloqueo configurado'), findsOneWidget);
      expect(t.widget<Switch>(find.byType(Switch)).onChanged, isNull);
    });

    testWidgets('la oferta: «Activar» comprueba la identidad; «Ahora no» no se repite', (t) async {
      SharedPreferences.setMockInitialValues({'bloqueo_inicios': 2});
      late WidgetRef refGuardado;
      await t.pumpWidget(app(Consumer(builder: (c, ref, _) {
        refGuardado = ref;
        return TextButton(onPressed: () => ofrecerBloqueo(c, ref), child: const Text('abrir'));
      }), [biometriaProvider.overrideWithValue(bio)]));
      await t.pumpAndSettle();
      await t.tap(find.text('abrir'));
      await t.pumpAndSettle();
      expect(find.text('¿Proteger la app?'), findsOneWidget);
      await t.tap(find.text('Ahora no'));
      await t.pumpAndSettle();
      expect(bio.motivos, isEmpty);
      expect(refGuardado.read(bloqueoProvider).ofertaVista, true);

      await t.tap(find.text('abrir'));
      await t.pumpAndSettle();
      await t.tap(find.text('Activar'));
      await t.pumpAndSettle();
      expect(bio.motivos, ['Confirma que eres tú para activar el bloqueo']);
      expect(refGuardado.read(bloqueoProvider).activo, true);
    });
  });
}
