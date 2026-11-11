import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/models/models.dart';
import 'package:guilda_work_mobile/nucleo/sesion.dart';
import 'package:guilda_work_mobile/screens/ia_chat_screen.dart';
import 'package:guilda_work_mobile/services/locale_service.dart';

import 'ayudas/pantallas.dart';

/// El turno del asistente tal y como lo vive la persona: lo que se va pintando mientras llega, la confirmación, parar, el error y vaciar. Es la red de seguridad del
/// refactor del chat (`ia_chat_screen.dart` → controlador + voz + piezas): estos tests no saben cómo está hecho por dentro, solo lo que se ve.
IaEventoStream _delta(String s) => IaEventoStream(tipo: 'delta', texto: s);
IaEventoStream _mensaje(IaMensaje m) => IaEventoStream(tipo: 'mensaje', mensaje: m);
IaEventoStream _fin() => IaEventoStream(tipo: 'fin');
IaEventoStream _pendiente(String herramienta, Map<String, dynamic> args) =>
    IaEventoStream(tipo: 'pendiente', pendiente: IaPendiente(toolCallId: 'c1', herramienta: herramienta, argumentos: args));

Future<void> _abrir(WidgetTester t, ApiFalsa api, {String? consulta}) async {
  sinVoz();
  await t.pumpWidget(appDePantalla(IaChatScreen(api: api, locale: LocaleService(), consultaInicial: consulta), [estadoSesionProvider.overrideWith(SesionFija.new)]));
  await t.pumpAndSettle();
}

Future<void> _escribirYEnviar(WidgetTester t, String texto) async {
  await t.enterText(find.byType(TextField), texto);
  await t.tap(find.byTooltip('Enviar'));
  await t.pump();
}

void main() {
  group('el turno del asistente', () {
    testWidgets('lo tuyo sale al instante, la respuesta se pinta en directo y el mensaje final la sustituye', (t) async {
      final turno = StreamController<IaEventoStream>();
      final api = ApiFalsa()..flujoIa = (_) => turno.stream;
      await _abrir(t, api);

      await _escribirYEnviar(t, '¿Qué tengo hoy?');
      expect(find.text('¿Qué tengo hoy?'), findsOneWidget); // optimista: no espera al servidor
      expect(find.byTooltip('Detener respuesta'), findsOneWidget); // enviar pasa a ser detener
      expect(find.byTooltip('Enviar'), findsNothing);

      turno.add(_delta('Tienes '));
      await t.pump();
      turno.add(_delta('dos tareas'));
      await t.pump();
      expect(find.text('Tienes dos tareas'), findsOneWidget);

      turno.add(_mensaje(iaMsg(10, 'assistant', 'Tienes dos tareas.')));
      turno.add(_fin());
      await turno.close();
      await t.pumpAndSettle();

      expect(find.text('Tienes dos tareas'), findsNothing); // el texto vivo ya no está
      expect(find.textContaining('Tienes dos tareas.'), findsOneWidget); // el definitivo sí
      expect(find.byTooltip('Enviar'), findsOneWidget);
      expect(find.byTooltip('Detener respuesta'), findsNothing);
      expect(api.enviadosIa, ['¿Qué tengo hoy?']);
    });

    testWidgets('no se envía dos veces mientras responde, ni un texto vacío', (t) async {
      final turno = StreamController<IaEventoStream>();
      final api = ApiFalsa()..flujoIa = (_) => turno.stream;
      await _abrir(t, api);

      await t.tap(find.byTooltip('Enviar'));
      await t.pump();
      expect(api.enviadosIa, isEmpty); // vacío: nada

      await _escribirYEnviar(t, 'Uno');
      expect(api.enviadosIa, ['Uno']);
      // El campo queda desactivado mientras responde: no hay segundo envío posible.
      expect(t.widget<TextField>(find.byType(TextField)).enabled, isFalse);
      await turno.close();
      await t.pumpAndSettle();
    });

    testWidgets('lo que hace el asistente por detrás se muestra como pasos durante el turno y como píldora al acabar', (t) async {
      final turno = StreamController<IaEventoStream>();
      final api = ApiFalsa()..flujoIa = (_) => turno.stream;
      await _abrir(t, api);

      await _escribirYEnviar(t, 'Lista mis tareas');
      turno.add(_mensaje(iaMsg(11, 'tool', '{"ok": true}', callId: 'c1', herramienta: 'listar_tareas')));
      await t.pump();
      expect(find.byIcon(Icons.build_circle_outlined), findsNothing); // en curso: va en los pasos, no suelto
      expect(find.text('usó listar_tareas'), findsOneWidget);

      turno.add(_mensaje(iaMsg(12, 'assistant', 'Aquí las tienes.')));
      turno.add(_fin());
      await turno.close();
      await t.pumpAndSettle();
      expect(find.byIcon(Icons.build_circle_outlined), findsOneWidget); // acabado: píldora
      expect(find.textContaining('Aquí las tienes.'), findsOneWidget);
    });

    testWidgets('una acción pendiente pide confirmar y bloquea el campo; «Sí, hazlo» la confirma y sigue el turno', (t) async {
      final api = ApiFalsa()
        ..flujoIa = ((_) => Stream.fromIterable([_pendiente('crear_tarea', {'asunto': 'Llamar a Acme'}), _fin()]))
        ..flujoConfirmarIa = ((_) => Stream.fromIterable([_mensaje(iaMsg(20, 'assistant', 'Hecho, tarea creada.')), _fin()]));
      await _abrir(t, api);

      await _escribirYEnviar(t, 'Crea una tarea para llamar a Acme');
      await t.pumpAndSettle();
      expect(find.text('NUEVA TAREA'), findsOneWidget);
      expect(find.text('Llamar a Acme'), findsOneWidget);
      expect(t.widget<TextField>(find.byType(TextField)).enabled, isFalse); // hasta responder a la confirmación
      expect(find.text('Responde a la confirmación de arriba primero…'), findsOneWidget);

      await t.tap(find.text('Sí, hazlo'));
      await t.pumpAndSettle();
      expect(api.confirmadosIa, [true]);
      expect(find.text('NUEVA TAREA'), findsNothing);
      expect(find.textContaining('tarea creada'), findsOneWidget);
      expect(t.widget<TextField>(find.byType(TextField)).enabled, isTrue);
    });

    testWidgets('«No» rechaza la acción y la confirmación desaparece', (t) async {
      final api = ApiFalsa()
        ..flujoIa = ((_) => Stream.fromIterable([_pendiente('crear_tarea', {'asunto': 'X'}), _fin()]))
        ..flujoConfirmarIa = ((_) => Stream.fromIterable([_mensaje(iaMsg(21, 'assistant', 'De acuerdo, no la creo.')), _fin()]));
      await _abrir(t, api);

      await _escribirYEnviar(t, 'Crea una tarea');
      await t.pumpAndSettle();
      await t.tap(find.text('No'));
      await t.pumpAndSettle();
      expect(api.confirmadosIa, [false]);
      expect(find.text('NUEVA TAREA'), findsNothing);
      expect(find.textContaining('no la creo'), findsOneWidget);
    });

    testWidgets('la acción pendiente que quedó a medias en el historial vuelve a pedir confirmación al abrir el chat', (t) async {
      final api = ApiFalsa()
        ..chat = [
          iaMsg(1, 'user', 'Crea una nota'),
          iaMsg(2, 'assistant', 'Voy a crearla.', calls: '[{"id":"c9","function":{"name":"crear_nota","arguments":"{\\"titulo\\":\\"Ideas\\"}"}}]'),
        ];
      await _abrir(t, api);
      expect(find.text('NUEVA NOTA'), findsOneWidget);
      expect(find.text('Ideas'), findsOneWidget);
    });

    testWidgets('«Detener» deja como mensaje lo que ya se había pintado y devuelve el botón de enviar', (t) async {
      final turno = StreamController<IaEventoStream>();
      final api = ApiFalsa()..flujoIa = (_) => turno.stream;
      await _abrir(t, api);

      await _escribirYEnviar(t, 'Cuéntame mucho');
      turno.add(_delta('Te cuento un po'));
      await t.pump();
      await t.tap(find.byTooltip('Detener respuesta'));
      await t.pump();

      expect(find.byTooltip('Enviar'), findsOneWidget);
      expect(find.text('Te cuento un po'), findsOneWidget); // se queda
      // Lo que llegue después ya no se pinta.
      turno.add(_delta('co más'));
      await t.pump();
      expect(find.textContaining('co más'), findsNothing);
      // El chat ya canceló su suscripción: cerrar el controlador no se completaría nunca, así que no se espera.
      unawaited(turno.close());
      await t.pumpAndSettle();
    });

    testWidgets('un error del turno se enseña con su texto y deja volver a escribir', (t) async {
      final api = ApiFalsa()..flujoIa = ((_) => Stream.fromIterable([IaEventoStream(tipo: 'error', error: 'El modelo no responde')]));
      await _abrir(t, api);

      await _escribirYEnviar(t, 'Hola');
      await t.pumpAndSettle();
      expect(find.text('El modelo no responde'), findsOneWidget);
      expect(t.widget<TextField>(find.byType(TextField)).enabled, isTrue);
      expect(find.byTooltip('Enviar'), findsOneWidget);
    });

    testWidgets('si la conexión cae a media respuesta sale el aviso de red', (t) async {
      final api = ApiFalsa()..flujoIa = ((_) => Stream<IaEventoStream>.error(Exception('se cayó')));
      await _abrir(t, api);

      await _escribirYEnviar(t, 'Hola');
      await t.pumpAndSettle();
      expect(find.text('Sin conexión. Comprueba tu red e inténtalo de nuevo.'), findsOneWidget);
      expect(find.byTooltip('Enviar'), findsOneWidget);
    });

    testWidgets('el error de un turno se borra al empezar el siguiente', (t) async {
      var llamada = 0;
      final api = ApiFalsa()
        ..flujoIa = ((_) => llamada++ == 0
            ? Stream.fromIterable([IaEventoStream(tipo: 'error', error: 'Falló')])
            : Stream.fromIterable([_mensaje(iaMsg(30, 'assistant', 'Ahora sí.')), _fin()]));
      await _abrir(t, api);

      await _escribirYEnviar(t, 'Uno');
      await t.pumpAndSettle();
      expect(find.text('Falló'), findsOneWidget);
      await _escribirYEnviar(t, 'Dos');
      await t.pumpAndSettle();
      expect(find.text('Falló'), findsNothing);
      expect(find.textContaining('Ahora sí.'), findsOneWidget);
    });

    testWidgets('la consulta inicial se envía sola al abrir y no se repite', (t) async {
      final api = ApiFalsa()..flujoIa = ((_) => Stream.fromIterable([_mensaje(iaMsg(40, 'assistant', 'Tu resumen.')), _fin()]));
      await _abrir(t, api, consulta: '  Resume mi día  ');
      expect(api.enviadosIa, ['Resume mi día']);
      expect(find.textContaining('Tu resumen.'), findsOneWidget);
    });
  });

  group('vaciar la conversación', () {
    Future<void> vaciar(WidgetTester t) async {
      await t.tap(find.byTooltip('Más opciones'));
      await t.pumpAndSettle();
      await t.tap(find.text('Vaciar conversación'));
      await t.pumpAndSettle();
    }

    testWidgets('pide confirmar; al aceptar, borra y vuelve la pantalla de inicio', (t) async {
      final api = ApiFalsa()..chat = [iaMsg(1, 'user', 'Hola'), iaMsg(2, 'assistant', 'Buenas.')];
      await _abrir(t, api);
      expect(find.textContaining('Buenas.'), findsOneWidget);

      await vaciar(t);
      expect(find.text('¿Borrar todo el historial de esta conversación? No se puede deshacer.'), findsOneWidget);
      await t.tap(find.text('Borrar'));
      await t.pumpAndSettle();
      expect(api.vaciadosIa, 1);
      expect(find.textContaining('Buenas.'), findsNothing);
      expect(find.text('¿En qué te ayudo?'), findsOneWidget);
    });

    testWidgets('si se cancela no se borra nada', (t) async {
      final api = ApiFalsa()..chat = [iaMsg(1, 'user', 'Hola'), iaMsg(2, 'assistant', 'Buenas.')];
      await _abrir(t, api);
      await vaciar(t);
      await t.tap(find.text('Cancelar'));
      await t.pumpAndSettle();
      expect(api.vaciadosIa, 0);
      expect(find.textContaining('Buenas.'), findsOneWidget);
    });

    testWidgets('«Vaciar» no está disponible con la conversación vacía', (t) async {
      await _abrir(t, ApiFalsa());
      await t.tap(find.byTooltip('Más opciones'));
      await t.pumpAndSettle();
      final entrada = t.widget<PopupMenuItem<String>>(find.widgetWithText(PopupMenuItem<String>, 'Vaciar conversación'));
      expect(entrada.enabled, isFalse);
    });
  });
}
