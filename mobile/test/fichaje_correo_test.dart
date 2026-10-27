import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:guilda_work_mobile/funciones/fichaje/fichaje_acciones.dart';
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/nucleo/paginas.dart';
import 'package:guilda_work_mobile/nucleo/sesion.dart';
import 'package:guilda_work_mobile/nucleo/shell.dart';
import 'package:guilda_work_mobile/screens/correo_bandeja_screen.dart';
import 'package:guilda_work_mobile/screens/correo_mensaje_screen.dart';
import 'package:guilda_work_mobile/screens/fichaje_screen.dart';
import 'package:guilda_work_mobile/screens/ia_chat_screen.dart';
import 'package:guilda_work_mobile/services/api_client.dart';
import 'package:guilda_work_mobile/services/locale_service.dart';
import 'package:guilda_work_mobile/theme/app_theme.dart';

import 'ayudas/pantallas.dart';

void main() {
  final carpeta = carpetaCapturas;
  setUpAll(cargarFuentesParaCapturas);

  final usuario = Usuario(id: 1, email: 'a@b.c');

  group('Fichaje', () {
    testWidgets('solo ofrece lo que vale ahora: entrada si estás fuera; pausa y salida si estás dentro; fin de pausa y salida en pausa', (t) async {
      final marcas = <String>[];
      final api = ApiFalsa();
      Future<void> abrir(String estado) async {
        api.estado = estado;
        await t.pumpWidget(appDePantalla(FichajeScreen(key: UniqueKey(), api: api, usuario: usuario), [estadoSesionProvider.overrideWith(SesionFija.new), accionesFichajeProvider.overrideWith((ref) => AccionesFalsas(ref, marcas))]));
        await t.pumpAndSettle();
      }

      await abrir('fuera');
      expect(find.text('Entrada'), findsOneWidget);
      expect(find.text('Salida'), findsNothing);
      expect(find.text('Aún no has fichado hoy'), findsOneWidget);
      await abrir('dentro');
      expect(find.text('Iniciar pausa'), findsOneWidget);
      expect(find.text('Salida'), findsOneWidget);
      expect(find.text('Entrada'), findsNothing);
      await abrir('en_pausa');
      expect(find.text('Fin de pausa'), findsOneWidget);
      expect(find.text('Salida'), findsOneWidget);
    });

    testWidgets('el estado dice desde cuándo, la línea de hoy lista las marcas y fichar manda el tipo y refresca', (t) async {
      final marcas = <String>[];
      final api = ApiFalsa()
        ..estado = 'dentro'
        ..eventos = [ev(1, 'entrada', '08:58'), ev(2, 'pausa_inicio', '11:00'), ev(3, 'pausa_fin', '11:15')];
      await t.pumpWidget(appDePantalla(FichajeScreen(api: api, usuario: usuario), [estadoSesionProvider.overrideWith(SesionFija.new), accionesFichajeProvider.overrideWith((ref) => AccionesFalsas(ref, marcas))]));
      await t.pumpAndSettle();
      expect(find.text('Dentro de jornada'), findsOneWidget);
      expect(find.text('Desde las 11:15'), findsOneWidget);
      expect(find.text('08:58'), findsOneWidget);
      expect(find.text('11:00'), findsOneWidget);
      await t.tap(find.text('Salida'));
      await t.pumpAndSettle();
      expect(marcas, ['salida']);
    });
  });

  group('Correo', () {
    testWidgets('la bandeja tiene una fila de filtros, y cada correo enseña quién, el asunto y el principio; lo no leído se marca con palabras', (t) async {
      final api = ApiFalsa()
        ..mensajes = [
          msg(1, 'Marta Ruiz <marta@ejemplo.com>', 'Consulta sobre la renta', 'Hola, quería preguntaros por la deducción de la vivienda habitual', leido: false),
          msg(2, 'Hacienda <no-reply@aeat.es>', 'Notificación', 'Tiene una notificación pendiente', destacado: true),
        ];
      await t.pumpWidget(appDePantalla(CorreoBandejaScreen(api: api), [estadoSesionProvider.overrideWith(SesionFija.new)]));
      await t.pumpAndSettle();
      expect(find.text('Marta Ruiz'), findsOneWidget);
      expect(find.text('Consulta sobre la renta'), findsOneWidget);
      expect(find.textContaining('deducción de la vivienda'), findsOneWidget);
      expect(find.byIcon(Icons.star), findsOneWidget);
      expect(find.text('M'), findsOneWidget); // la inicial en el avatar
      expect(find.text('Entrada'), findsOneWidget); // carpeta
      await t.tap(find.text('Solo no leídos'));
      await t.pumpAndSettle();
      expect(api.pedidos.last, '1:INBOX:true:-');
      await t.tap(find.text('Despacho'));
      await t.pumpAndSettle();
      await t.tap(find.text('Personal').last);
      await t.pumpAndSettle();
      expect(api.pedidos.last.startsWith('2:'), isTrue);
    });
  });

  group('Correo: leer un mensaje', () {
    testWidgets('quién escribe va arriba con su avatar; responder y reenviar están a mano; marcar y destacar son píldoras', (t) async {
      final api = ApiFalsa()..abierto = msg(5, 'Marta Ruiz <marta@ejemplo.com>', 'Consulta sobre la renta', 'Hola, quería preguntaros por la deducción de la vivienda habitual.', leido: true);
      await t.pumpWidget(appDePantalla(CorreoMensajeScreen(api: api, mensajeId: 5, carpetas: const []), [estadoSesionProvider.overrideWith(SesionFija.new)]));
      await t.pumpAndSettle();
      expect(find.text('Consulta sobre la renta'), findsOneWidget);
      expect(find.text('Marta Ruiz'), findsOneWidget);
      expect(find.text('M'), findsOneWidget);
      expect(find.text('Responder'), findsOneWidget);
      expect(find.text('Reenviar'), findsOneWidget);
      expect(find.textContaining('deducción de la vivienda'), findsOneWidget);
      await t.tap(find.text('Destacar'));
      await t.pumpAndSettle();
      expect(api.acciones, ['destacar:5:true']);
    });
  });

  group('Asistente IA', () {
    testWidgets('vacío: sugerencias como tarjetas y un toque envía', (t) async {
      sinVoz();
      final api = ApiFalsa();
      await t.pumpWidget(appDePantalla(IaChatScreen(api: api, locale: LocaleService()), [estadoSesionProvider.overrideWith(SesionFija.new)]));
      await t.pumpAndSettle();
      expect(find.text('¿Qué tengo pendiente hoy?'), findsOneWidget);
      expect(find.text('Crea una nota con lo que te dicte'), findsOneWidget);
      // En una pantalla baja la lista de tarjetas se desplaza por debajo del campo de escritura.
      await t.ensureVisible(find.text('¿Qué tengo pendiente hoy?'));
      await t.pumpAndSettle();
      await t.tap(find.text('¿Qué tengo pendiente hoy?'));
      await t.pumpAndSettle();
      expect(api.enviadosIa, ['¿Qué tengo pendiente hoy?']);
    });

    testWidgets('abierto desde otra pantalla: manda la consulta sola y dice de qué trata', (t) async {
      sinVoz();
      final api = ApiFalsa();
      await t.pumpWidget(appDePantalla(IaChatScreen(api: api, locale: LocaleService(), consultaInicial: 'Resume mi día', contexto: 'Hoy'), [estadoSesionProvider.overrideWith(SesionFija.new)]));
      await t.pumpAndSettle();
      expect(api.enviadosIa, ['Resume mi día']);
      expect(find.text('Contexto: Hoy'), findsOneWidget);
    });

    testWidgets('con la conversación empezada salen atajos encima del campo, y uno envía', (t) async {
      sinVoz();
      final api = ApiFalsa()..chat = [iaMsg(1, 'user', 'Hola'), iaMsg(2, 'assistant', 'Hola, ¿en qué te ayudo?')];
      await t.pumpWidget(appDePantalla(IaChatScreen(api: api, locale: LocaleService()), [estadoSesionProvider.overrideWith(SesionFija.new)]));
      await t.pumpAndSettle();
      await t.tap(find.text('Resume mis correos sin contestar'));
      await t.pumpAndSettle();
      expect(api.enviadosIa, ['Resume mis correos sin contestar']);
    });

    testWidgets('el aviso de que es una IA acompaña al campo de escritura', (t) async {
      sinVoz();
      await t.pumpWidget(appDePantalla(IaChatScreen(api: ApiFalsa(), locale: LocaleService()), [estadoSesionProvider.overrideWith(SesionFija.new)]));
      await t.pumpAndSettle();
      expect(find.textContaining('puede contener errores'), findsOneWidget);
      expect(find.byTooltip('Adjuntar texto o CSV (hasta 1 MB)'), findsOneWidget);
    });

    testWidgets('las respuestas citan sus fuentes y lo tuyo con un archivo lo muestra como píldora, sin la línea técnica', (t) async {
      sinVoz();
      final api = ApiFalsa()
        ..chat = [
          iaMsg(1, 'user', '[Adjunto #4: gastos.csv]\n¿Cuánto suman?'),
          iaMsg(2, 'assistant', 'Suman 120 €.', fuentes: '[{"tipo":"tarea","titulo":"Pagar a Acme","url":"/tareas/7/editar"},{"tipo":"nota","titulo":"Gastos de octubre","url":"/nota/3/editar"}]'),
        ];
      await t.pumpWidget(appDePantalla(IaChatScreen(api: api, locale: LocaleService()), [estadoSesionProvider.overrideWith(SesionFija.new)]));
      await t.pumpAndSettle();
      expect(find.text('gastos.csv'), findsOneWidget);
      expect(find.text('¿Cuánto suman?'), findsOneWidget);
      expect(find.textContaining('[Adjunto'), findsNothing);
      expect(find.text('Fuentes'), findsOneWidget);
      expect(find.text('Pagar a Acme'), findsOneWidget);
      expect(find.text('Gastos de octubre'), findsOneWidget);
    });

    testWidgets('con historial: lo tuyo a la derecha con el acento, lo del asistente en tarjeta, lo que hizo por detrás en píldora, y la acción pendiente pide confirmar', (t) async {
      sinVoz();
      final api = ApiFalsa()
        ..chat = [
          iaMsg(1, 'user', 'Crea una tarea para llamar a Acme mañana'),
          iaMsg(2, 'assistant', 'Voy a **crear** la tarea.', calls: '[{"id":"c1","function":{"name":"crear_tarea","arguments":"{\\"asunto\\":\\"Llamar a Acme\\",\\"fecha\\":\\"2026-10-27\\"}"}}]'),
        ];
      await t.pumpWidget(appDePantalla(IaChatScreen(api: api, locale: LocaleService()), [estadoSesionProvider.overrideWith(SesionFija.new)]));
      await t.pumpAndSettle();
      expect(find.text('Crea una tarea para llamar a Acme mañana'), findsOneWidget);
      expect(find.textContaining('crear la tarea'), findsOneWidget);
      expect(find.textContaining('crear_tarea'), findsWidgets);
      expect(find.text('asunto'), findsOneWidget);
      expect(find.text('Llamar a Acme'), findsOneWidget);
      expect(find.text('No'), findsOneWidget);
      expect(find.text('Sí, hazlo'), findsOneWidget);
    });

    testWidgets('lo que hizo el asistente por detrás sale como píldora, y un fallo lleva su icono', (t) async {
      sinVoz();
      final api = ApiFalsa()
        ..chat = [
          iaMsg(1, 'tool', '{"ok": true}', callId: 'c1', herramienta: 'crear_tarea'),
          iaMsg(2, 'tool', '{"error": "sin permiso"}', callId: 'c2', herramienta: 'borrar_tarea'),
        ];
      await t.pumpWidget(appDePantalla(IaChatScreen(api: api, locale: LocaleService()), [estadoSesionProvider.overrideWith(SesionFija.new)]));
      await t.pumpAndSettle();
      expect(find.byIcon(Icons.build_circle_outlined), findsOneWidget);
      expect(find.byIcon(Icons.error_outline), findsOneWidget);
    });
  });

  group('Barra inferior y «Más»', () {
    GoRouter enrutador() => GoRouter(initialLocation: '/a', routes: [
          StatefulShellRoute.indexedStack(
            builder: (c, e, shell) => ShellApp(shell: shell),
            branches: [
              for (final r in ['a', 'b', 'c', 'd', 'e'])
                StatefulShellBranch(routes: [GoRoute(path: '/$r', builder: (c, e) => Center(child: Text('Pantalla $r')))]),
            ],
          ),
        ]);

    testWidgets('en una tableta la barra pasa a un lateral con las mismas cinco etiquetas', (t) async {
      t.view.physicalSize = const Size(1000, 800);
      t.view.devicePixelRatio = 1;
      addTearDown(t.view.reset);
      await t.pumpWidget(ProviderScope(
        overrides: [estadoSesionProvider.overrideWith(SesionFija.new)],
        child: MaterialApp.router(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: const Locale('es'),
          theme: AppTheme.light,
          routerConfig: enrutador(),
        ),
      ));
      await t.pumpAndSettle();
      expect(find.byType(NavigationRail), findsOneWidget);
      expect(find.byType(NavigationBar), findsNothing);
      for (final etiqueta in ['Hoy', 'Tareas', 'Correo', 'Fichaje', 'Más']) {
        expect(find.text(etiqueta), findsOneWidget, reason: etiqueta);
      }
      await t.tap(find.text('Correo'));
      await t.pumpAndSettle();
      expect(find.text('Pantalla c'), findsOneWidget);
    });

    testWidgets('cinco destinos con su etiqueta siempre visible; tocar uno cambia de pestaña', (t) async {
      final r = enrutador();
      await t.pumpWidget(ProviderScope(
        overrides: [estadoSesionProvider.overrideWith(SesionFija.new)],
        child: MaterialApp.router(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: const Locale('es'),
          theme: AppTheme.light,
          routerConfig: r,
        ),
      ));
      await t.pumpAndSettle();
      for (final etiqueta in ['Hoy', 'Tareas', 'Correo', 'Fichaje', 'Más']) {
        expect(find.text(etiqueta), findsOneWidget, reason: etiqueta);
      }
      expect(find.text('Pantalla a'), findsOneWidget);
      await t.tap(find.text('Correo'));
      await t.pumpAndSettle();
      expect(find.text('Pantalla c'), findsOneWidget);
    });

    testWidgets('«Más» agrupa los accesos en tarjetas con su icono', (t) async {
      final paginas = PaginasApp(
        login: (_) => const SizedBox(),
        inicio: (_, _) => const SizedBox(),
        tareas: (_) => const SizedBox(),
        correo: (_) => const SizedBox(),
        fichaje: (_, _) => const SizedBox(),
        accesosMas: (_, _) => const [AccesoMas(Icons.apps, ClaveEtiqueta.herramientas, null), AccesoMas(Icons.settings_outlined, ClaveEtiqueta.ajustes, null)],
      );
      await t.pumpWidget(appDePantalla(const MasScreen(), [estadoSesionProvider.overrideWith(SesionConUsuario.new), paginasProvider.overrideWithValue(paginas)]));
      await t.pumpAndSettle();
      expect(find.text('Ajustes'), findsOneWidget);
      expect(find.byIcon(Icons.chevron_right), findsWidgets);
    });
  });

  group('capturas del diseño (Asistente y barra)', () {
    for (final oscuro in [false, true]) {
      final sufijo = oscuro ? 'oscuro' : 'claro';
      testWidgets('captura chat $sufijo', (t) async {
        if (carpeta == null) return;
        sinVoz();
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 2532);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        final api = ApiFalsa()
          ..chat = [
            iaMsg(1, 'user', '[Adjunto #4: gastos-octubre.csv]\n¿Qué tengo pendiente hoy?'),
            iaMsg(2, 'assistant', 'Tienes **2 vencimientos** y una tarea vencida: el 303 de Acme SL. ¿Quieres que la pase a mañana?', fuentes: '[{"tipo":"tarea","titulo":"Presentar modelo 303 · Acme SL","url":"/tareas/7/editar"},{"tipo":"nota","titulo":"Gastos de octubre","url":"/nota/3/editar"}]'),
            iaMsg(3, 'user', 'Sí, y crea una tarea para llamar a Acme'),
            iaMsg(4, 'tool', '{"ok": true}', callId: 'c0', herramienta: 'mover_tarea'),
            iaMsg(5, 'assistant', 'Hecho. Voy a crear la tarea.', calls: '[{"id":"c1","function":{"name":"crear_tarea","arguments":"{\\"asunto\\":\\"Llamar a Acme\\",\\"fecha_vencimiento\\":\\"2026-10-27\\"}"}}]'),
          ];
        await t.pumpWidget(appDePantalla(IaChatScreen(api: api, locale: LocaleService()), [estadoSesionProvider.overrideWith(SesionFija.new)], oscuro: oscuro, clave: clave));
        await t.pumpAndSettle();
        await capturar(t, clave, 'chat_$sufijo');
      });
      testWidgets('captura chat vacío $sufijo', (t) async {
        if (carpeta == null) return;
        sinVoz();
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 2532);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        await t.pumpWidget(appDePantalla(IaChatScreen(api: ApiFalsa(), locale: LocaleService()), [estadoSesionProvider.overrideWith(SesionFija.new)], oscuro: oscuro, clave: clave));
        await t.pumpAndSettle();
        await capturar(t, clave, 'chat_vacio_$sufijo');
      });
      testWidgets('captura más $sufijo', (t) async {
        if (carpeta == null) return;
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 2532);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        final paginas = PaginasApp(
          login: (_) => const SizedBox(),
          inicio: (_, _) => const SizedBox(),
          tareas: (_) => const SizedBox(),
          correo: (_) => const SizedBox(),
          fichaje: (_, _) => const SizedBox(),
          accesosMas: (_, _) => const [
            AccesoMas(Icons.folder_open_outlined, ClaveEtiqueta.panel, null),
            AccesoMas(Icons.apps, ClaveEtiqueta.herramientas, null),
            AccesoMas(Icons.confirmation_number_outlined, ClaveEtiqueta.tiquets, null),
            AccesoMas(Icons.smart_toy_outlined, ClaveEtiqueta.asistenteIa, null),
            AccesoMas(Icons.calendar_month_outlined, ClaveEtiqueta.fiscal, null),
            AccesoMas(Icons.settings_outlined, ClaveEtiqueta.ajustes, null),
          ],
        );
        final r = GoRouter(initialLocation: '/e', routes: [
          StatefulShellRoute.indexedStack(
            builder: (c, e, shell) => ShellApp(shell: shell),
            branches: [
              for (final x in ['a', 'b', 'c', 'd']) StatefulShellBranch(routes: [GoRoute(path: '/$x', builder: (c, e) => const SizedBox())]),
              StatefulShellBranch(routes: [GoRoute(path: '/e', builder: (c, e) => const MasScreen())]),
            ],
          ),
        ]);
        await t.pumpWidget(ProviderScope(
          overrides: [estadoSesionProvider.overrideWith(SesionConUsuario.new), paginasProvider.overrideWithValue(paginas)],
          child: RepaintBoundary(
            key: clave,
            child: MaterialApp.router(
              debugShowCheckedModeBanner: false,
              localizationsDelegates: AppLocalizations.localizationsDelegates,
              supportedLocales: AppLocalizations.supportedLocales,
              locale: const Locale('es'),
              theme: AppTheme.light,
              darkTheme: AppTheme.dark,
              themeMode: oscuro ? ThemeMode.dark : ThemeMode.light,
              routerConfig: r,
            ),
          ),
        ));
        await t.pumpAndSettle();
        await capturar(t, clave, 'mas_$sufijo');
      });
    }
  });

  group('capturas del diseño (Fichaje y Correo)', () {
    for (final oscuro in [false, true]) {
      testWidgets('captura mensaje ${oscuro ? 'oscuro' : 'claro'}', (t) async {
        if (carpeta == null) return;
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 2532);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        final api = ApiFalsa()..abierto = msg(5, 'Marta Ruiz <marta@ejemplo.com>', 'Consulta sobre la renta', 'Hola, quería preguntaros por la deducción de la vivienda habitual y los gastos de la reforma del año pasado. ¿Podéis decirme qué papeles necesitáis?', leido: false);
        await t.pumpWidget(appDePantalla(CorreoMensajeScreen(api: api, mensajeId: 5, carpetas: const []), [estadoSesionProvider.overrideWith(SesionFija.new)], oscuro: oscuro, clave: clave));
        await t.pumpAndSettle();
        await capturar(t, clave, 'mensaje_${oscuro ? 'oscuro' : 'claro'}');
      });
    }

    for (final oscuro in [false, true]) {
      final sufijo = oscuro ? 'oscuro' : 'claro';
      testWidgets('captura fichaje $sufijo', (t) async {
        if (carpeta == null) return;
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 2532);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        final api = ApiFalsa()
          ..estado = 'dentro'
          ..eventos = [ev(1, 'entrada', '08:58'), ev(2, 'pausa_inicio', '11:00'), ev(3, 'pausa_fin', '11:15')];
        await t.pumpWidget(appDePantalla(FichajeScreen(api: api, usuario: usuario), [estadoSesionProvider.overrideWith(SesionFija.new)], oscuro: oscuro, clave: clave));
        await t.pumpAndSettle();
        await capturar(t, clave, 'fichaje_$sufijo');
      });
      testWidgets('captura correo $sufijo', (t) async {
        if (carpeta == null) return;
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 2532);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        final api = ApiFalsa()
          ..mensajes = [
            msg(1, 'Marta Ruiz <marta@ejemplo.com>', 'Consulta sobre la renta', 'Hola, quería preguntaros por la deducción de la vivienda habitual y los gastos de la reforma', leido: false),
            msg(2, 'Hacienda <no-reply@aeat.es>', 'Notificación electrónica pendiente', 'Tiene una notificación pendiente de lectura en la sede', destacado: true),
            msg(3, 'Luis Mora <luis@acme.es>', 'Facturas de septiembre', 'Adjunto las facturas del mes para que las contabilicéis'),
            msg(4, 'Banco Norte <avisos@banconorte.es>', 'Resumen de movimientos', 'Su resumen mensual ya está disponible', leido: false),
          ];
        await t.pumpWidget(appDePantalla(CorreoBandejaScreen(api: api), [estadoSesionProvider.overrideWith(SesionFija.new)], oscuro: oscuro, clave: clave));
        await t.pumpAndSettle();
        await capturar(t, clave, 'correo_$sufijo');
      });
    }
  });
}
