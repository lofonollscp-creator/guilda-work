import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/diseno/asistente.dart';

import 'ayudas/pantallas.dart';

void main() {
  testWidgets('la tarjeta del asistente: las sugerencias envían su texto y la barra abre el chat vacío', (t) async {
    final elegidas = <String>[];
    var abierto = 0;
    await t.pumpWidget(appDePantalla(
      Scaffold(body: TarjetaAsistente(titulo: 'Tu asistente', pista: 'Pregunta o pide algo…', sugerencias: const ['Uno', 'Dos'], alElegir: elegidas.add, alAbrir: () => abierto++)),
      const [],
    ));
    await t.tap(find.text('Dos'));
    await t.tap(find.text('Pregunta o pide algo…'));
    expect(elegidas, ['Dos']);
    expect(abierto, 1);
  });

  testWidgets('la barra del asistente es un botón con su texto y mide lo que un dedo', (t) async {
    final guia = t.ensureSemantics();
    await t.pumpWidget(appDePantalla(Scaffold(body: BarraAsistente(pista: 'Pregunta sobre tus tareas', alPulsar: () {})), const []));
    expect(t.getSize(find.byType(BarraAsistente)).height, greaterThanOrEqualTo(48));
    await expectLater(t, meetsGuideline(androidTapTargetGuideline));
    await expectLater(t, meetsGuideline(textContrastGuideline));
    guia.dispose();
  });
}
