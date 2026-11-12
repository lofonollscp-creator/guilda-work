import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/api/errores.dart';
import 'package:guilda_work_mobile/diseno/componentes.dart';
import 'package:guilda_work_mobile/funciones/asistente/chat_v3.dart';
import 'package:guilda_work_mobile/funciones/propuestas/propuestas_controlador.dart';
import 'package:guilda_work_mobile/funciones/propuestas/propuestas_screen.dart';
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/models/models.dart';
import 'package:guilda_work_mobile/nucleo/destinos.dart';
import 'package:guilda_work_mobile/nucleo/sesion.dart';
import 'package:guilda_work_mobile/screens/ia_chat_screen.dart';
import 'package:guilda_work_mobile/services/locale_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'ayudas/pantallas.dart';

const _tarea = PropuestaIa(id: 1, tipo: 'tarea', origen: 'alerta', titulo: 'Revisar el IVA de Acme SL', detalle: 'Bajan las ventas un 40 % frente al trimestre anterior', prioridad: 'alta');
const _portal = PropuestaIa(id: 2, tipo: 'mensaje_portal', origen: 'asistente', titulo: 'Pedir las facturas de octubre a Talleres Soler', detalle: '', prioridad: 'normal');

Widget _app(Widget home, List<PropuestaIa> lista, List<String> hechas, {Object? fallo}) =>
    appDePantalla(home, [estadoSesionProvider.overrideWith(SesionFija.new), propuestasProvider.overrideWith(() => PropuestasFalsas(lista, hechas, fallo))], propuestasVacias: false);

void main() {
  setUpAll(cargarFuentesParaCapturas);

  group('modelo', () {
    test('lee lo que manda el servidor y sabe si es urgente o actúa fuera', () {
      final p = PropuestaIa.desdeJson({'id': 7, 'tipo': 'peticion_portal', 'origen': 'asistente', 'titulo': 'T', 'detalle': 'D', 'cliente_id': 3, 'prioridad': 'alta', 'estado': 'pendiente', 'creada_en': '2026-11-12T09:00:00'});
      expect((p.id, p.tipo, p.urgente, p.actuaFuera), (7, 'peticion_portal', true, true));
      expect(_tarea.actuaFuera, isFalse);
      expect(PropuestaIa.desdeJson({'id': 1, 'tipo': 'tarea'}).prioridad, 'normal'); // sin prioridad, normal
    });
  });

  group('bandeja', () {
    testWidgets('lista las propuestas con su porqué; la urgente lo dice con texto', (t) async {
      await t.pumpWidget(_app(const PropuestasScreen(), [_tarea, _portal], []));
      await t.pumpAndSettle();
      expect(find.text('Revisar el IVA de Acme SL'), findsOneWidget);
      expect(find.textContaining('Bajan las ventas'), findsOneWidget);
      expect(find.text('Urgente'), findsOneWidget);
      expect(find.text('Aprobar'), findsNWidgets(2));
      expect(find.text('Rechazar'), findsNWidgets(2));
    });

    testWidgets('sin propuestas se explica y no hay botones', (t) async {
      await t.pumpWidget(_app(const PropuestasScreen(), [], []));
      await t.pumpAndSettle();
      expect(find.text('Nada que aprobar'), findsOneWidget);
      expect(find.text('Aprobar'), findsNothing);
    });

    testWidgets('aprobar una tarea la hace al momento y la quita de la lista', (t) async {
      final hechas = <String>[];
      await t.pumpWidget(_app(const PropuestasScreen(), [_tarea, _portal], hechas));
      await t.pumpAndSettle();
      await t.tap(find.text('Aprobar').first);
      await t.pumpAndSettle();
      expect(hechas, ['aprobar:1']);
      expect(find.text('Revisar el IVA de Acme SL'), findsNothing);
      expect(find.text('Hecho: propuesta aprobada'), findsOneWidget);
      expect(find.text('Pedir las facturas de octubre a Talleres Soler'), findsOneWidget);
    });

    testWidgets('rechazar la quita y avisa de que no vuelve en 30 días', (t) async {
      final hechas = <String>[];
      await t.pumpWidget(_app(const PropuestasScreen(), [_tarea], hechas));
      await t.pumpAndSettle();
      await t.tap(find.text('Rechazar'));
      await t.pumpAndSettle();
      expect(hechas, ['rechazar:1']);
      expect(find.text('Rechazada: no volverá a salir en 30 días'), findsOneWidget);
      expect(find.text('Nada que aprobar'), findsOneWidget);
    });

    testWidgets('lo que actúa hacia un cliente pide confirmar antes de aprobar; cancelar no hace nada', (t) async {
      final hechas = <String>[];
      await t.pumpWidget(_app(const PropuestasScreen(), [_portal], hechas));
      await t.pumpAndSettle();
      await t.tap(find.text('Aprobar'));
      await t.pumpAndSettle();
      expect(find.text('¿Aprobar esta propuesta?'), findsOneWidget);
      await t.tap(find.text('Cancelar'));
      await t.pumpAndSettle();
      expect(hechas, isEmpty);
      expect(find.text('Pedir las facturas de octubre a Talleres Soler'), findsOneWidget);
      await t.tap(find.text('Aprobar'));
      await t.pumpAndSettle();
      await t.tap(find.descendant(of: find.byType(AlertDialog), matching: find.text('Aprobar')));
      await t.pumpAndSettle();
      expect(hechas, ['aprobar:2']);
    });

    testWidgets('si falla (ya resuelta por otra persona) se dice y la propuesta sigue en la lista', (t) async {
      final hechas = <String>[];
      await t.pumpWidget(_app(const PropuestasScreen(), [_tarea], hechas, fallo: ApiException('ya resuelta', status: 409)));
      await t.pumpAndSettle();
      await t.tap(find.text('Aprobar'));
      await t.pumpAndSettle();
      expect(hechas, isEmpty);
      expect(find.text('Revisar el IVA de Acme SL'), findsOneWidget);
      expect(find.byType(SnackBar), findsOneWidget);
    });

    for (final oscuro in [false, true]) {
      testWidgets('captura de la bandeja ${oscuro ? 'oscuro' : 'claro'}', (t) async {
        if (carpetaCapturas == null) return;
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 2532);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        await t.pumpWidget(appDePantalla(const PropuestasScreen(), [estadoSesionProvider.overrideWith(SesionFija.new), propuestasProvider.overrideWith(() => PropuestasFalsas([_tarea, _portal]))], oscuro: oscuro, clave: clave, propuestasVacias: false));
        await t.pumpAndSettle();
        await capturar(t, clave, 'propuestas_${oscuro ? 'oscuro' : 'claro'}');
      });
    }

    testWidgets('cumple las pautas de accesibilidad', (t) async {
      final h = t.ensureSemantics();
      await t.pumpWidget(_app(const PropuestasScreen(), [_tarea, _portal], []));
      await t.pumpAndSettle();
      await expectLater(t, meetsGuideline(androidTapTargetGuideline));
      await expectLater(t, meetsGuideline(labeledTapTargetGuideline));
      h.dispose();
    });
  });

  group('tarjeta de aviso', () {
    testWidgets('con propuestas cuenta cuántas y abre la bandeja', (t) async {
      await t.pumpWidget(_app(const Scaffold(body: TarjetaPropuestas()), [_tarea, _portal], []));
      await t.pumpAndSettle();
      expect(find.text('2 propuestas del asistente'), findsOneWidget);
      await t.tap(find.text('2 propuestas del asistente'));
      await t.pumpAndSettle();
      expect(find.byType(PropuestasScreen), findsOneWidget);
    });

    testWidgets('sin propuestas no ocupa sitio ni dice nada', (t) async {
      await t.pumpWidget(_app(const Scaffold(body: TarjetaPropuestas()), [], []));
      await t.pumpAndSettle();
      expect(find.byType(TarjetaPropuestas), findsOneWidget);
      expect(find.textContaining('propuesta'), findsNothing);
    });

    test('un aviso con destino «propuesta» abre la bandeja', () {
      expect(resolverDestino(const Destino('propuesta')), isA<AbrirPantalla>().having((a) => a.clave, 'clave', 'propuestas'));
    });
  });

  group('tope de IA', () {
    test('avisa al 80 % y al agotarse; sin tope o con la IA desactivada no', () {
      expect(const ConsumoIa(usadas: 79, limite: 100).cerca, isFalse);
      expect(const ConsumoIa(usadas: 80, limite: 100).cerca, isTrue);
      expect(const ConsumoIa(usadas: 100, limite: 100).agotado, isTrue);
      expect(const ConsumoIa(usadas: 100, limite: 100).cerca, isFalse); // agotado manda sobre «cerca»
      expect(const ConsumoIa(usadas: 5000).cerca, isFalse);
      expect(const ConsumoIa(usadas: 0, limite: 0).agotado, isFalse);
      expect(ConsumoIa.desdeJson({'usadas': 40, 'limite': 50, 'pct': 80}).pct, 80);
    });

    Future<void> abrirChat(WidgetTester t, ConsumoIa consumo) async {
      sinVoz();
      SharedPreferences.setMockInitialValues({});
      await t.pumpWidget(appDePantalla(IaChatScreen(api: ApiFalsa()..consumoIa = consumo, locale: LocaleService()), [estadoSesionProvider.overrideWith(SesionFija.new)]));
      await t.pumpAndSettle();
    }

    testWidgets('cerca del tope, el chat lo dice con cifras', (t) async {
      await abrirChat(t, const ConsumoIa(usadas: 85, limite: 100));
      expect(find.text('Tu despacho lleva 85 de 100 consultas de IA este mes.'), findsOneWidget);
    });

    testWidgets('agotado, dice cuándo se renueva', (t) async {
      await abrirChat(t, const ConsumoIa(usadas: 100, limite: 100));
      expect(find.textContaining('ha agotado las consultas de IA de este mes'), findsOneWidget);
    });

    testWidgets('lejos del tope no sale nada', (t) async {
      await abrirChat(t, const ConsumoIa(usadas: 10, limite: 100));
      expect(find.byType(AvisoConsumoIa), findsOneWidget);
      expect(find.textContaining('consultas de IA'), findsNothing);
    });
  });

  group('política de acceso', () {
    test('se reconoce por su código y no por el 403 a secas', () {
      expect(ApiException('x', status: 403, codigo: 'politica_acceso').politicaAcceso, isTrue);
      expect(ApiException('x', status: 403).politicaAcceso, isFalse);
    });

    testWidgets('el 403 de la política explica qué hacer, no «no tienes permiso»', (t) async {
      late String texto;
      late String generico;
      await t.pumpWidget(MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('es'),
        home: Builder(builder: (c) {
          final l = AppLocalizations.of(c);
          texto = mensajeDeError(l, ApiException('x', status: 403, codigo: 'politica_acceso'));
          generico = mensajeDeError(l, ApiException('x', status: 403));
          return const SizedBox();
        }),
      ));
      expect(texto, contains('verificación en dos pasos'));
      expect(texto, contains('vuelve a entrar'));
      expect(generico, 'No tienes permiso para hacer esto.');
    });
  });
}
