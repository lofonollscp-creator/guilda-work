import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/diseno/v3/v3.dart';
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/theme/acento.dart';
import 'package:guilda_work_mobile/theme/app_theme.dart';

import 'ayudas/pantallas.dart';

double _contraste(Color a, Color b) {
  final la = a.computeLuminance(), lb = b.computeLuminance();
  final (claro, oscuro) = la > lb ? (la, lb) : (lb, la);
  return (claro + 0.05) / (oscuro + 0.05);
}

Widget _app(Widget hijo, {ThemeData? tema, bool sinMovimiento = false, bool altoContraste = false}) => MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: tema ?? AppTheme.light,
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('es'),
      builder: (c, h) => MediaQuery(data: MediaQuery.of(c).copyWith(disableAnimations: sinMovimiento, highContrast: altoContraste), child: h!),
      home: Scaffold(body: hijo),
    );

/// La paleta de un tema, sin montar nada.
Future<PaletaV3> _paleta(WidgetTester t, ThemeData tema) async {
  late PaletaV3 p;
  await t.pumpWidget(_app(Builder(builder: (c) {
    p = PaletaV3.de(c);
    return const SizedBox();
  }), tema: tema));
  await t.pumpAndSettle(); // MaterialApp anima el cambio de tema: hasta que termina, Theme.of devuelve el anterior
  return p;
}

void main() {
  setUpAll(cargarFuentesParaCapturas);

  group('paleta y tema v3', () {
    testWidgets('la paleta sigue al tema claro/oscuro y al acento', (t) async {
      final claro = await _paleta(t, AppTheme.light);
      final oscuro = await _paleta(t, AppTheme.dark);
      expect(claro.oscuro, isFalse);
      expect(oscuro.oscuro, isTrue);
      expect(claro.fondo, isNot(oscuro.fondo));
      final violeta = await _paleta(t, AppTheme.oscuro('violeta'));
      expect(violeta.acento, isNot(oscuro.acento));
    });

    testWidgets('el texto mantiene el contraste AA sobre cada tono de tarjeta, en los dos temas y con cada acento', (t) async {
      for (final acento in ['lima', ...acentos.keys.where((k) => k != 'lima')]) {
        for (final tema in [AppTheme.claro(acento), AppTheme.oscuro(acento)]) {
          final p = await _paleta(t, tema);
          for (final tono in TonoBento.values) {
            final fondo = TarjetaBento.fondoDe(p, tono);
            expect(_contraste(p.texto, fondo), greaterThanOrEqualTo(4.5), reason: 'texto sobre $tono (${p.oscuro ? 'oscuro' : 'claro'}, $acento)');
            final suave = p.suaveSobre(fondo);
            expect(_contraste(suave, fondo), greaterThanOrEqualTo(4.5), reason: 'texto suave sobre $tono (${p.oscuro ? 'oscuro' : 'claro'}, $acento)');
            // Sigue siendo «suave»: no se ha vuelto tan oscuro como el texto principal.
            expect(suave == p.texto, isFalse, reason: 'el texto suave no debe acabar igual que el principal ($tono, $acento)');
          }
        }
      }
    });

    test('los botones del tema son píldoras y miden al menos 48 dp', () {
      final estilo = AppTheme.light.filledButtonTheme.style!;
      expect(estilo.shape!.resolve({}), isA<StadiumBorder>());
      expect(estilo.minimumSize!.resolve({})!.height, greaterThanOrEqualTo(48));
    });
  });

  group('vidrio', () {
    testWidgets('desenfoca el fondo y cae a una superficie opaca con alto contraste o con el vidrio apagado', (t) async {
      await t.pumpWidget(_app(const Vidrio(child: Text('hola'))));
      expect(find.byType(BackdropFilter), findsOneWidget);

      await t.pumpWidget(_app(const Vidrio(child: Text('hola')), altoContraste: true));
      expect(find.byType(BackdropFilter), findsNothing);
      expect(find.text('hola'), findsOneWidget);

      await t.pumpWidget(_app(const Vidrio(opaco: true, child: Text('hola'))));
      expect(find.byType(BackdropFilter), findsNothing);

      V3.vidrioActivo.value = false;
      addTearDown(() => V3.vidrioActivo.value = true);
      await t.pumpWidget(_app(const Vidrio(child: Text('hola'))));
      expect(find.byType(BackdropFilter), findsNothing);
    });
  });

  group('movimiento', () {
    testWidgets('con «reducir movimiento» el aura, el orbe y el brillo no animan', (t) async {
      final hijos = Column(children: const [
        SizedBox(height: 120, child: Aura()),
        OrbeIa(estado: EstadoOrbe.pensando),
        Brillo(child: BloqueEsqueleto(ancho: 100)),
      ]);
      await t.pumpWidget(_app(hijos, sinMovimiento: true));
      await t.pump(const Duration(milliseconds: 50));
      expect(t.binding.hasScheduledFrame, isFalse);

      await t.pumpWidget(_app(hijos));
      await t.pump(const Duration(milliseconds: 50));
      expect(t.binding.hasScheduledFrame, isTrue);
      // Se desmontan sin dejar controladores vivos.
      await t.pumpWidget(const SizedBox());
    });
  });

  group('pulsable y tarjeta', () {
    testWidgets('responde al toque, se anuncia como botón y se hunde mientras se pulsa', (t) async {
      final semantica = t.ensureSemantics();
      var toques = 0;
      await t.pumpWidget(_app(Center(child: TarjetaBento(etiqueta: 'Abrir tarea', alPulsar: () => toques++, child: const Text('Tarea')))));
      final nodo = find.bySemanticsLabel(RegExp('Abrir tarea'));
      expect(nodo, findsOneWidget);
      expect(t.getSemantics(nodo), isSemantics(isButton: true, hasTapAction: true));

      final gesto = await t.startGesture(t.getCenter(find.text('Tarea')));
      await t.pump(V3.durCorta);
      expect(t.widget<AnimatedScale>(find.byType(AnimatedScale)).scale, lessThan(1));
      await gesto.up();
      await t.pumpAndSettle();
      expect(toques, 1);
      expect(t.widget<AnimatedScale>(find.byType(AnimatedScale)).scale, 1);
      semantica.dispose();
    });

    testWidgets('sin acción es un contenedor mudo (no es un botón)', (t) async {
      await t.pumpWidget(_app(const TarjetaBento(child: Text('Dato'))));
      expect(find.byType(InkWell), findsNothing);
    });
  });

  group('cabecera grande', () {
    testWidgets('el título se pliega al hacer scroll y la barra sigue fija', (t) async {
      await t.pumpWidget(_app(CustomScrollView(slivers: [
        const CabeceraGrande(titulo: 'Hoy', subtitulo: 'Despacho Pérez'),
        SliverList.builder(itemCount: 40, itemBuilder: (_, i) => ListTile(title: Text('fila $i'))),
      ])));
      final alto0 = t.getSize(find.byType(FlexibleSpaceBar)).height;
      await t.drag(find.byType(CustomScrollView), const Offset(0, -400));
      await t.pump();
      final alto1 = t.getSize(find.byType(FlexibleSpaceBar)).height;
      expect(alto1, lessThan(alto0));
      expect(alto1, greaterThanOrEqualTo(kToolbarHeight));
      expect(find.text('Hoy'), findsOneWidget);
      expect(find.byType(BackdropFilter), findsOneWidget);
    });
  });

  group('captura de la galería v3', () {
    for (final oscuro in [false, true]) {
      testWidgets('galería ${oscuro ? 'oscuro' : 'claro'}', (t) async {
        if (carpetaCapturas == null) return;
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 3400);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        await t.pumpWidget(RepaintBoundary(
          key: clave,
          child: MaterialApp(
            debugShowCheckedModeBanner: false,
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            locale: const Locale('es'),
            theme: AppTheme.light,
            darkTheme: AppTheme.dark,
            themeMode: oscuro ? ThemeMode.dark : ThemeMode.light,
            builder: (c, h) => MediaQuery(data: MediaQuery.of(c).copyWith(disableAnimations: true), child: h!),
            home: const _Galeria(),
          ),
        ));
        await t.pump(const Duration(milliseconds: 100));
        await capturar(t, clave, 'galeria_v3_${oscuro ? 'oscuro' : 'claro'}');
      });
    }
  });
}

/// Todo lo nuevo de la v3 en una pantalla, para revisarlo de un vistazo.
class _Galeria extends StatelessWidget {
  const _Galeria();

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final p = PaletaV3.de(context);
    Widget titulo(String s) => Padding(padding: const EdgeInsets.fromLTRB(4, 22, 4, 8), child: Text(s, style: tema.textTheme.labelMedium?.copyWith(letterSpacing: 0.8)));
    return Scaffold(
      body: CustomScrollView(slivers: [
        const CabeceraGrande(titulo: 'Sistema v3', subtitulo: 'Vidrio · aura · mosaico', acciones: [Icon(Icons.search), SizedBox(width: 12), Icon(Icons.notifications_none), SizedBox(width: 12)]),
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 32),
          sliver: SliverList(delegate: SliverChildListDelegate([
            titulo('AURA Y ORBE'),
            SizedBox(
              height: 150,
              child: Aura(
                radio: BorderRadius.circular(V3.radioL),
                intensidad: 0.9,
                child: Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: const [
                  OrbeIa(tamano: 72),
                  OrbeIa(tamano: 72, estado: EstadoOrbe.escuchando),
                  OrbeIa(tamano: 72, estado: EstadoOrbe.pensando),
                ]),
              ),
            ),
            titulo('MOSAICO'),
            const TarjetaBento(
              tono: TonoBento.acento,
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('LO SIGUIENTE'),
                SizedBox(height: 6),
                Text('Presentar el 303 de Acme SL', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
              ]),
            ),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: TarjetaBento(alPulsar: () {}, child: const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('5', style: TextStyle(fontSize: 32, fontWeight: FontWeight.w700)), Text('Pendientes')]))),
              const SizedBox(width: 12),
              Expanded(child: TarjetaBento(alPulsar: () {}, child: const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('2', style: TextStyle(fontSize: 32, fontWeight: FontWeight.w700)), Text('Urgentes')]))),
            ]),
            const SizedBox(height: 12),
            const TarjetaBento(
              tono: TonoBento.ia,
              child: Row(children: [Icon(Icons.auto_awesome), SizedBox(width: 12), Expanded(child: Text('El asistente propone: pedir la documentación a Beta SA'))]),
            ),
            titulo('VIDRIO SOBRE CONTENIDO'),
            SizedBox(
              height: 120,
              child: Stack(children: [
                Positioned.fill(child: DecoratedBox(decoration: BoxDecoration(borderRadius: BorderRadius.circular(V3.radioL), gradient: LinearGradient(colors: [p.ia.acento, p.acento])))),
                Align(
                  alignment: Alignment.bottomCenter,
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Vidrio(
                      radio: BorderRadius.circular(999),
                      sombra: true,
                      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
                      child: Row(children: [
                        const Icon(Icons.auto_awesome, size: 20),
                        const SizedBox(width: 10),
                        Expanded(child: Text('Pídeme algo…', style: tema.textTheme.bodyLarge?.copyWith(color: p.textoSuave))),
                        const Icon(Icons.mic_none),
                      ]),
                    ),
                  ),
                ),
              ]),
            ),
            titulo('CONTROLES'),
            Wrap(spacing: 12, runSpacing: 12, children: [
              FilledButton(onPressed: () {}, child: const Text('Aprobar')),
              OutlinedButton(onPressed: () {}, child: const Text('Rechazar')),
              TextButton(onPressed: () {}, child: const Text('Más tarde')),
              const Chip(label: Text('Vencido')),
              FilterChip(label: const Text('Hoy'), selected: true, onSelected: (_) {}),
            ]),
            const SizedBox(height: 12),
            const TextField(decoration: InputDecoration(labelText: 'Asunto')),
            titulo('CARGANDO'),
            const Brillo(child: Column(children: [
              BloqueEsqueleto(alto: 56, radio: 20),
              SizedBox(height: 10),
              BloqueEsqueleto(alto: 56, radio: 20),
            ])),
          ])),
        ),
      ]),
    );
  }
}
