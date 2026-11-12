import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart' show setEquals;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:guilda_work_mobile/api/generado/modelos.g.dart';
import 'package:guilda_work_mobile/diseno/v3/v3.dart';
import 'package:guilda_work_mobile/funciones/asistente/chat_v3.dart';
import 'package:guilda_work_mobile/funciones/hoy/hoy_controlador.dart';
import 'package:guilda_work_mobile/funciones/hoy/hoy_fichaje.dart';
import 'package:guilda_work_mobile/funciones/hoy/hoy_screen.dart';
import 'package:guilda_work_mobile/funciones/propuestas/propuestas_controlador.dart';
import 'package:guilda_work_mobile/funciones/propuestas/propuestas_screen.dart';
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/models/models.dart';
import 'package:guilda_work_mobile/nucleo/servicios.dart';
import 'package:guilda_work_mobile/nucleo/sesion.dart';
import 'package:guilda_work_mobile/nucleo/shell.dart';
import 'package:guilda_work_mobile/services/theme_service.dart';
import 'package:guilda_work_mobile/theme/acento.dart';
import 'package:guilda_work_mobile/theme/app_theme.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'ayudas/pantallas.dart';

const _idiomas = ['es', 'ca', 'en', 'fr'];

Map<String, dynamic> _arb(String l) => jsonDecode(File('lib/l10n/app_$l.arb').readAsStringSync()) as Map<String, dynamic>;

/// Los `{marcadores}` de un texto traducido (sin los de plural/select, que se reescriben por idioma).
Set<String> _marcadores(String texto) {
  final plano = texto.replaceAllMapped(RegExp(r'\{(\w+), (?:plural|select),'), (m) => '{${m[1]}}');
  return {for (final m in RegExp(r'\{(\w+)\}').allMatches(plano)) m[1]!};
}

final _bandeja = BandejaHoy.fromJson({
  'total': 3,
  'urgentes': 1,
  'secciones': [
    {
      'clave': 'tareas',
      'titulo': 'Tareas',
      'total': 1,
      'elementos': [
        {'titulo': 'Presentar el modelo 303 trimestral de la sociedad Talleres Soler Hermanos y Asociados SL', 'urgencia': 'vencido', 'destino': {'tipo': 'tarea', 'id': 1}, 'acciones': ['abrir', 'completar']},
      ],
    },
  ],
});

class _HoyFijo extends HoyControlador {
  @override
  Future<EstadoHoy> build() async => EstadoHoy(_bandeja, DateTime(2026, 11, 12, 9));
}

const _larga = PropuestaIa(
    id: 1, tipo: 'mensaje_portal', origen: 'asistente', titulo: 'Pedir a Talleres Soler Hermanos y Asociados SL las facturas recibidas de octubre y noviembre', detalle: 'Faltan seis facturas del trimestre y el modelo 303 vence en menos de una semana, así que conviene reclamarlas hoy mismo.', prioridad: 'alta');

Widget _app(Widget home, {String idioma = 'es', double escala = 1, ThemeData? tema, List<Override> overrides = const []}) => ProviderScope(
      overrides: [
        estadoSesionProvider.overrideWith(SesionFija.new),
        propuestasProvider.overrideWith(() => PropuestasFalsas([_larga])),
        fichajeHoyProvider.overrideWith(() => FichajeHoyFalso([], const EstadoFichajeHoy('dentro', true, '08:58'))),
        hoyProvider.overrideWith(_HoyFijo.new),
        serviciosProvider.overrideWithValue(serviciosFalsos()),
        ...overrides,
      ],
      child: MaterialApp(
        debugShowCheckedModeBanner: false,
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: Locale(idioma),
        theme: tema ?? AppTheme.light,
        builder: (c, h) => MediaQuery(data: MediaQuery.of(c).copyWith(textScaler: TextScaler.linear(escala), disableAnimations: true), child: h!),
        home: home,
      ),
    );

GoRouter _router() => GoRouter(initialLocation: '/a', routes: [
      StatefulShellRoute.indexedStack(
        builder: (c, e, shell) => ShellApp(shell: shell),
        branches: [for (final r in ['a', 'b', 'c', 'd', 'e']) StatefulShellBranch(routes: [GoRoute(path: '/$r', builder: (c, e) => Center(child: Text('Pantalla $r')))])],
      ),
    ]);

Widget _shell({String idioma = 'es', double escala = 1, ThemeData? tema}) => ProviderScope(
      overrides: [estadoSesionProvider.overrideWith(SesionFija.new), propuestasProvider.overrideWith(() => PropuestasFalsas([_larga, _larga])), serviciosProvider.overrideWithValue(serviciosFalsos())],
      child: MaterialApp.router(
        debugShowCheckedModeBanner: false,
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: Locale(idioma),
        theme: tema ?? AppTheme.light,
        builder: (c, h) => MediaQuery(data: MediaQuery.of(c).copyWith(textScaler: TextScaler.linear(escala), disableAnimations: true), child: h!),
        routerConfig: _router(),
      ),
    );

void main() {
  group('traducciones', () {
    final es = _arb('es');
    final claves = [for (final k in es.keys) if (!k.startsWith('@') && !k.startsWith('@@')) k];

    for (final l in _idiomas.skip(1)) {
      test('$l tiene todas las claves de es, ninguna de más y ninguna vacía', () {
        final o = _arb(l);
        final propias = {for (final k in o.keys) if (!k.startsWith('@')) k};
        expect(claves.toSet().difference(propias), isEmpty, reason: 'faltan en $l');
        expect(propias.difference(claves.toSet()), isEmpty, reason: 'sobran en $l');
        expect([for (final k in claves) if ('${o[k]}'.trim().isEmpty) k], isEmpty);
      });

      test('$l usa los mismos marcadores que es en cada texto', () {
        final o = _arb(l);
        final distintos = [for (final k in claves) if (!setEquals(_marcadores('${es[k]}'), _marcadores('${o[k]}'))) '$k: ${_marcadores('${es[k]}')} ≠ ${_marcadores('${o[k]}')}'];
        expect(distintos, isEmpty);
      });
    }
  });

  group('textos largos y letra grande: nada se desborda', () {
    for (final idioma in ['ca', 'fr', 'en']) {
      for (final escala in [1.0, 2.0]) {
        final caso = '$idioma ×$escala';

        testWidgets('la barra de navegación, con el ✦ y su insignia ($caso)', (t) async {
          t.view.physicalSize = const Size(320 * 2, 640 * 2); // un móvil estrecho
          t.view.devicePixelRatio = 2;
          addTearDown(t.view.reset);
          sinVoz();
          await t.pumpWidget(_shell(idioma: idioma, escala: escala));
          await t.pumpAndSettle();
          expect(t.takeException(), isNull);
        });

        testWidgets('Hoy: mosaico, fichaje y propuestas ($caso)', (t) async {
          t.view.physicalSize = const Size(320 * 2, 1400 * 2);
          t.view.devicePixelRatio = 2;
          addTearDown(t.view.reset);
          await t.pumpWidget(_app(const HoyScreen(), idioma: idioma, escala: escala));
          await t.pumpAndSettle();
          expect(t.takeException(), isNull);
        });

        testWidgets('la bandeja de propuestas ($caso)', (t) async {
          t.view.physicalSize = const Size(320 * 2, 1400 * 2);
          t.view.devicePixelRatio = 2;
          addTearDown(t.view.reset);
          await t.pumpWidget(_app(const PropuestasScreen(), idioma: idioma, escala: escala));
          await t.pumpAndSettle();
          expect(t.takeException(), isNull);
        });

        testWidgets('tarjetas de resultado, pasos y aviso de tope ($caso)', (t) async {
          t.view.physicalSize = const Size(320 * 2, 1400 * 2);
          t.view.devicePixelRatio = 2;
          addTearDown(t.view.reset);
          await t.pumpWidget(_app(Scaffold(
            body: ListView(children: [
              TarjetasResultado(fuentes: const [IaFuente(tipo: 'vencimiento', titulo: 'Modelo 303 · Talleres Soler Hermanos y Asociados SL · primer trimestre', url: '/fiscal/vencimientos/41/editar')], alAbrir: (_) {}),
              const PasosPlegables(hechos: ['Buscando las tareas vencidas de todos los clientes', 'Leyendo el correo sin contestar'], enCurso: 'Revisando los vencimientos fiscales de esta semana'),
              const AvisoConsumoIa(consumo: ConsumoIa(usadas: 85, limite: 100)),
              const AvisoConsumoIa(consumo: ConsumoIa(usadas: 100, limite: 100)),
            ]),
          ), idioma: idioma, escala: escala));
          await t.pumpAndSettle();
          expect(t.takeException(), isNull);
        });
      }
    }
  });

  group('los ocho acentos, en claro y oscuro', () {
    for (final acento in acentos.keys) {
      for (final oscuro in [false, true]) {
        testWidgets('la barra cumple contraste y toques de 48 ($acento, ${oscuro ? 'oscuro' : 'claro'})', (t) async {
          final h = t.ensureSemantics();
          await t.pumpWidget(_shell(tema: oscuro ? AppTheme.oscuro(acento) : AppTheme.claro(acento)));
          await t.pumpAndSettle();
          await expectLater(t, meetsGuideline(textContrastGuideline));
          await expectLater(t, meetsGuideline(androidTapTargetGuideline));
          h.dispose();
        });

        testWidgets('la bandeja de propuestas cumple contraste y toques de 48 ($acento, ${oscuro ? 'oscuro' : 'claro'})', (t) async {
          final h = t.ensureSemantics();
          await t.pumpWidget(_app(const PropuestasScreen(), tema: oscuro ? AppTheme.oscuro(acento) : AppTheme.claro(acento)));
          await t.pumpAndSettle();
          await expectLater(t, meetsGuideline(textContrastGuideline));
          await expectLater(t, meetsGuideline(androidTapTargetGuideline));
          h.dispose();
        });
      }
    }
  });

  group('capturas finales', () {
    setUpAll(cargarFuentesParaCapturas);

    Future<void> foto(WidgetTester t, String nombre, Widget app, Size fisico, double dpr) async {
      final clave = GlobalKey();
      t.view.physicalSize = fisico;
      t.view.devicePixelRatio = dpr;
      addTearDown(t.view.reset);
      await t.pumpWidget(RepaintBoundary(key: clave, child: app));
      await t.pumpAndSettle();
      await capturar(t, clave, nombre);
    }

    testWidgets('Hoy en tableta, claro y oscuro', (t) async {
      if (carpetaCapturas == null) return;
      await foto(t, 'hoy_tableta_claro', _app(const HoyScreen()), const Size(1400, 900), 1);
      await foto(t, 'hoy_tableta_oscuro', _app(const HoyScreen(), tema: AppTheme.dark), const Size(1400, 900), 1);
    });

    testWidgets('Hoy en catalán con la letra al 150 %, en un móvil estrecho', (t) async {
      if (carpetaCapturas == null) return;
      await foto(t, 'hoy_ca_letra_grande', _app(const HoyScreen(), idioma: 'ca', escala: 1.5), const Size(360 * 3, 780 * 3), 3);
    });

    testWidgets('Hoy con cada acento (violeta y ámbar), en oscuro', (t) async {
      if (carpetaCapturas == null) return;
      await foto(t, 'hoy_violeta_oscuro', _app(const HoyScreen(), tema: AppTheme.oscuro('violeta')), const Size(390 * 3, 844 * 3), 3);
      await foto(t, 'hoy_ambar_claro', _app(const HoyScreen(), tema: AppTheme.claro('ambar')), const Size(390 * 3, 844 * 3), 3);
    });
  });

  group('efecto cristal (ajuste)', () {
    tearDown(() => V3.vidrioActivo.value = true);

    test('por defecto está activo; apagarlo se guarda y se recupera al abrir la app', () async {
      SharedPreferences.setMockInitialValues({});
      final tema = ThemeService();
      await tema.cargar();
      expect(tema.vidrio, isTrue);
      await tema.cambiarVidrio(false);
      expect(V3.vidrioActivo.value, isFalse);
      V3.vidrioActivo.value = true; // «reinicio»
      await ThemeService().cargar();
      expect(V3.vidrioActivo.value, isFalse);
    });

    testWidgets('con el cristal apagado la barra es opaca (sin desenfoque)', (t) async {
      Future<int> desenfoques() async {
        await t.pumpWidget(_shell());
        await t.pumpAndSettle();
        return find.byType(BackdropFilter).evaluate().length;
      }

      V3.vidrioActivo.value = true;
      final con = await desenfoques();
      V3.vidrioActivo.value = false;
      await t.pumpAndSettle();
      final sin = find.byType(BackdropFilter).evaluate().length;
      expect(con, greaterThan(sin));
    });
  });
}
