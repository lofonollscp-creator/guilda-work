import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/nucleo/sesion.dart';
import 'package:guilda_work_mobile/screens/correo_bandeja_screen.dart';
import 'package:guilda_work_mobile/screens/fichaje_screen.dart';
import 'package:guilda_work_mobile/screens/ia_chat_screen.dart';
import 'package:guilda_work_mobile/services/api_client.dart';
import 'package:guilda_work_mobile/services/locale_service.dart';

import 'ayudas/pantallas.dart';

/// Las pautas de accesibilidad de Flutter sobre las pantallas principales: zonas táctiles de al menos 48 dp, todo lo que se toca tiene nombre para el
/// lector de pantalla y el texto contrasta con su fondo. Y un tablet no rompe nada.
void main() {
  final usuario = Usuario(id: 1, email: 'a@b.c');

  Future<void> pautas(WidgetTester t, String nombre) async {
    final semantica = t.ensureSemantics();
    await expectLater(t, meetsGuideline(androidTapTargetGuideline), reason: '$nombre: zonas táctiles');
    await expectLater(t, meetsGuideline(labeledTapTargetGuideline), reason: '$nombre: nombre para el lector de pantalla');
    await expectLater(t, meetsGuideline(textContrastGuideline), reason: '$nombre: contraste del texto');
    semantica.dispose();
  }

  for (final oscuro in [false, true]) {
    final tema = oscuro ? 'oscuro' : 'claro';
    group('pautas de accesibilidad ($tema)', () {
      testWidgets('Fichaje', (t) async {
        final api = ApiFalsa()
          ..estado = 'dentro'
          ..eventos = [ev(1, 'entrada', '08:58'), ev(2, 'pausa_inicio', '11:00')];
        await t.pumpWidget(appDePantalla(FichajeScreen(api: api, usuario: usuario), [estadoSesionProvider.overrideWith(SesionFija.new)], oscuro: oscuro));
        await t.pumpAndSettle();
        await pautas(t, 'Fichaje');
      });

      testWidgets('Bandeja de correo', (t) async {
        final api = ApiFalsa()..mensajes = [msg(1, 'Marta Ruiz <marta@ejemplo.com>', 'Consulta', 'Hola', leido: false), msg(2, 'Hacienda <a@aeat.es>', 'Aviso', 'Texto', destacado: true)];
        await t.pumpWidget(appDePantalla(CorreoBandejaScreen(api: api), [estadoSesionProvider.overrideWith(SesionFija.new)], oscuro: oscuro));
        await t.pumpAndSettle();
        await pautas(t, 'Correo');
      });

      testWidgets('Asistente IA', (t) async {
        sinVoz();
        await t.pumpWidget(appDePantalla(IaChatScreen(api: ApiFalsa()..chat = [iaMsg(1, 'user', 'Hola'), iaMsg(2, 'assistant', 'Hola, ¿en qué te ayudo?')], locale: LocaleService()), [estadoSesionProvider.overrideWith(SesionFija.new)], oscuro: oscuro));
        await t.pumpAndSettle();
        await pautas(t, 'Asistente IA');
      });
    });
  }
}
