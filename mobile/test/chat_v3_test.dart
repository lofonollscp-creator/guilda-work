import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/funciones/asistente/chat_v3.dart';
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/models/models.dart';
import 'package:guilda_work_mobile/theme/app_theme.dart';

Widget _app(Widget hijo, {bool sinMovimiento = false}) => MaterialApp(
      theme: AppTheme.light,
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('es'),
      builder: (c, h) => MediaQuery(data: MediaQuery.of(c).copyWith(disableAnimations: sinMovimiento), child: h!),
      home: Scaffold(body: Padding(padding: const EdgeInsets.all(16), child: hijo)),
    );

void main() {
  group('tarjetas de resultado', () {
    const fuentes = [
      IaFuente(tipo: 'tarea', titulo: 'Presentar el 303', url: '/tareas/7/editar'),
      IaFuente(tipo: 'correo', titulo: 'Factura de marzo', url: '/correo/?mensaje_id=9'),
      IaFuente(tipo: 'otro', titulo: 'Algo raro', url: '/x'),
    ];

    testWidgets('una tarjeta por fuente, con su tipo y título, y el toque la abre', (t) async {
      final abiertas = <String>[];
      await t.pumpWidget(_app(TarjetasResultado(fuentes: fuentes, alAbrir: (f) => abiertas.add(f.titulo))));
      expect(find.text('Presentar el 303'), findsOneWidget);
      expect(find.text('Tareas'), findsOneWidget);
      expect(find.text('Correo'), findsOneWidget);
      await t.tap(find.text('Factura de marzo'));
      expect(abiertas, ['Factura de marzo']);
    });

    testWidgets('lo que no tiene tipo conocido no pinta una etiqueta vacía', (t) async {
      await t.pumpWidget(_app(TarjetasResultado(fuentes: [fuentes.last], alAbrir: (_) {})));
      expect(find.text('Algo raro'), findsOneWidget);
      expect(find.text(''), findsNothing);
    });

    testWidgets('sin fuentes no ocupa sitio', (t) async {
      await t.pumpWidget(_app(TarjetasResultado(fuentes: const [], alAbrir: (_) {})));
      expect(t.getSize(find.byType(TarjetasResultado)), Size.zero);
    });

    testWidgets('se anuncia como botón con su tipo y título', (t) async {
      final h = t.ensureSemantics();
      await t.pumpWidget(_app(TarjetasResultado(fuentes: [fuentes.first], alAbrir: (_) {})));
      expect(find.bySemanticsLabel('Tareas: Presentar el 303'), findsOneWidget);
      h.dispose();
    });
  });

  group('pasos plegables', () {
    testWidgets('plegados por defecto: dicen cuántos son y un toque los muestra', (t) async {
      await t.pumpWidget(_app(const PasosPlegables(hechos: ['Buscando tareas', 'Leyendo correo'])));
      expect(find.text('Pensando…'), findsOneWidget);
      expect(find.textContaining('2 pasos'), findsOneWidget);
      expect(find.text('Buscando tareas'), findsNothing);
      await t.tap(find.textContaining('2 pasos'));
      await t.pump();
      expect(find.text('Buscando tareas'), findsOneWidget);
      expect(find.text('Leyendo correo'), findsOneWidget);
      await t.tap(find.textContaining('2 pasos'));
      await t.pump();
      expect(find.text('Buscando tareas'), findsNothing);
    });

    testWidgets('sin pasos solo muestra que piensa, sin contador ni flecha', (t) async {
      await t.pumpWidget(_app(const PasosPlegables(hechos: [])));
      expect(find.text('Pensando…'), findsOneWidget);
      expect(find.textContaining('paso'), findsNothing);
      expect(find.byIcon(Icons.expand_more), findsNothing);
    });
  });

  group('texto en directo', () {
    testWidgets('muestra lo recibido y el cursor, que late salvo con «reducir movimiento»', (t) async {
      List<InlineSpan> construir(BuildContext _, String x) => [TextSpan(text: x)];
      await t.pumpWidget(_app(TextoVivo(texto: 'Hola, tienes', construir: construir)));
      expect(find.textContaining('Hola, tienes', findRichText: true), findsOneWidget);
      await t.pump(const Duration(milliseconds: 300));
      expect(t.binding.hasScheduledFrame, isTrue); // anima

      await t.pumpWidget(_app(TextoVivo(texto: 'Hola, tienes', construir: construir), sinMovimiento: true));
      await t.pump();
      await t.pump(const Duration(seconds: 1));
      expect(t.binding.hasScheduledFrame, isFalse); // quieto
    });
  });
}
