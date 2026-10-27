import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/diseno/asistente.dart';
import 'package:guilda_work_mobile/models/models.dart';
import 'package:guilda_work_mobile/nucleo/destinos.dart';

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

  test('el archivo que va al principio del mensaje se separa del texto', () {
    final r = separarAdjuntoDelTexto('[Adjunto #12: datos.csv]\n¿Qué suman?');
    expect((r!.nombre, r.texto), ('datos.csv', '¿Qué suman?'));
    expect(separarAdjuntoDelTexto('Hola [Adjunto #1: a.txt]'), isNull);
  });

  test('las fuentes llegan como lista, y un JSON roto no rompe el mensaje', () {
    final m = IaMensaje(id: 1, rol: 'assistant', creadoEn: '', fuentesJson: '[{"tipo":"nota","titulo":"N","url":"/nota/3/editar"}]');
    expect(m.fuentes.single.titulo, 'N');
    expect(IaMensaje(id: 2, rol: 'assistant', creadoEn: '', fuentesJson: '{roto').fuentes, isEmpty);
    expect(IaMensaje(id: 3, rol: 'assistant', creadoEn: '').fuentes, isEmpty);
  });

  test('cada fuente lleva a su pantalla: tarea, nota y correo; el resto, a la web con su id', () {
    expect(destinoDeFuenteIa('tarea', '/tareas/7/editar').id, 7);
    expect(destinoDeFuenteIa('nota', '/nota/3/editar').tipo, 'nota');
    expect(destinoDeFuenteIa('correo', '/correo/?cuenta_id=1&mensaje_id=9').id, 9);
    final cliente = destinoDeFuenteIa('cliente', '/fiscal/clientes/12');
    expect((cliente.tipo, cliente.id), ('cliente', 12));
  });
}
