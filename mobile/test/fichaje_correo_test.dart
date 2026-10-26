import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/funciones/fichaje/fichaje_acciones.dart';
import 'package:guilda_work_mobile/funciones/tareas/tareas_acciones.dart' show ResultadoAccion;
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/models/models.dart';
import 'package:guilda_work_mobile/nucleo/sesion.dart';
import 'package:guilda_work_mobile/screens/correo_bandeja_screen.dart';
import 'package:guilda_work_mobile/screens/correo_mensaje_screen.dart';
import 'package:guilda_work_mobile/screens/fichaje_screen.dart';
import 'package:guilda_work_mobile/services/api_client.dart';
import 'package:guilda_work_mobile/services/session_service.dart';
import 'package:guilda_work_mobile/theme/app_theme.dart';

/// El servidor, sin servidor: solo lo que usan Fichaje y Correo.
class _ApiFalsa extends ApiClient {
  _ApiFalsa() : super(SessionService());
  String estado = 'fuera';
  List<FichajeEvento> eventos = [];
  List<Mensaje> mensajes = [];
  final List<String> pedidos = [];

  @override
  Future<(String, bool)> obtenerEstadoFichaje() async => (estado, true);
  @override
  Future<List<FichajeEvento>> listarMisFichajes({String? desde, String? hasta}) async => eventos;
  @override
  Future<ResumenSemanaFichaje> obtenerResumenSemanaFichaje() async {
    final lunes = DateTime.now().subtract(Duration(days: DateTime.now().weekday - 1));
    String f(int i) => lunes.add(Duration(days: i)).toIso8601String().substring(0, 10);
    final horas = [8.2, 7.5, 6.0, 0.0, 0.0, 0.0, 0.0];
    return ResumenSemanaFichaje(
      segundos: 21.7 * 3600 * 0 + (8.2 + 7.5 + 6.0) * 3600,
      contratados: 40 * 3600,
      diferencia: -(40 - 21.7) * 3600,
      porcentaje: 54,
      enCurso: true,
      dias: [for (var i = 0; i < 7; i++) DiaSemanaFichaje(fecha: f(i), segundos: horas[i] * 3600, hoy: i == DateTime.now().weekday - 1)],
    );
  }

  final List<String> acciones = [];
  Mensaje? abierto;

  @override
  Future<Mensaje> obtenerMensaje(int id) async => abierto!;
  @override
  Future<List<CategoriaCorreo>> listarCategoriasCorreo() async => [CategoriaCorreo(id: 1, nombre: 'Clientes', color: '#3b82f6')];
  @override
  Future<void> marcarLeido(int id, bool leido) async => acciones.add('leido:$id:$leido');
  @override
  Future<void> destacarMensaje(int id, bool destacado) async => acciones.add('destacar:$id:$destacado');

  @override
  Future<List<CuentaCorreo>> listarCuentasCorreo() async => [
        CuentaCorreo(id: 1, nombre: 'Despacho', protocolo: 'imap', host: 'h', puerto: 993, usuario: 'a'),
        CuentaCorreo(id: 2, nombre: 'Personal', protocolo: 'imap', host: 'h', puerto: 993, usuario: 'b'),
      ];
  @override
  Future<List<Carpeta>> listarCarpetas(int cuentaId) async => [Carpeta(nombre: 'INBOX', nombreVisible: 'Entrada'), Carpeta(nombre: 'Sent', nombreVisible: 'Enviados')];
  @override
  Future<List<Mensaje>> listarMensajes({required int cuentaId, String carpeta = 'INBOX', bool? noLeidos, String? q}) async {
    pedidos.add('$cuentaId:$carpeta:${noLeidos ?? '-'}:${q ?? '-'}');
    return mensajes;
  }
}

class _AccionesFalsas extends AccionesFichaje {
  final List<String> marcas;
  _AccionesFalsas(super.ref, this.marcas);
  @override
  Future<ResultadoAccion<String>> marcar(String tipo, {double? latitud, double? longitud, DateTime? ahora}) async {
    marcas.add(tipo);
    return ResultadoAccion.enviada({'entrada': 'dentro', 'pausa_inicio': 'en_pausa', 'pausa_fin': 'dentro', 'salida': 'fuera'}[tipo]!);
  }
}

class _SesionFija extends SesionControl {
  @override
  EstadoSesion build() => const EstadoSesion(fase: FaseSesion.conSesion);
}

FichajeEvento _ev(int id, String tipo, String hora) => FichajeEvento(id: id, tipo: tipo, marcaTiempo: '${DateTime.now().toIso8601String().substring(0, 10)}T$hora:00', origen: 'app');

Mensaje _msg(int id, String de, String asunto, String texto, {bool leido = true, bool destacado = false}) => Mensaje(
      id: id, cuentaId: 1, carpeta: 'INBOX', asunto: asunto, remitente: de, destinatarios: 'yo@ejemplo.com', fecha: '2026-10-24T09:30', cuerpoTexto: texto,
      leido: leido, destacado: destacado, remitenteConfiable: true, adjuntos: const [],
    );

Widget _app(Widget home, List<Override> overrides, {bool oscuro = false, GlobalKey? clave}) {
  final app = MaterialApp(
    debugShowCheckedModeBanner: false,
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    locale: const Locale('es'),
    theme: AppTheme.light,
    darkTheme: AppTheme.dark,
    themeMode: oscuro ? ThemeMode.dark : ThemeMode.light,
    home: home,
  );
  return ProviderScope(overrides: overrides, child: clave == null ? app : RepaintBoundary(key: clave, child: app));
}

void main() {
  final carpeta = Platform.environment['CAPTURAS'];

  setUpAll(() async {
    if (carpeta == null) return;
    Directory(carpeta).createSync(recursive: true);
    Future<void> fuente(String familia, List<String> rutas) async {
      final f = FontLoader(familia);
      for (final r in rutas) {
        f.addFont(Future.value(ByteData.sublistView(File(r).readAsBytesSync())));
      }
      await f.load();
    }

    await fuente('Manrope', ['assets/fonts/Manrope-Regular.ttf', 'assets/fonts/Manrope-Medium.ttf', 'assets/fonts/Manrope-SemiBold.ttf', 'assets/fonts/Manrope-Bold.ttf']);
    await fuente('Inter', ['assets/fonts/Inter-Regular.ttf', 'assets/fonts/Inter-SemiBold.ttf']);
    await fuente('MaterialIcons', ['${Platform.environment['FLUTTER_ROOT'] ?? '/home/guilda/flutter'}/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf']);
  });

  Future<void> capturar(WidgetTester t, GlobalKey clave, String nombre) async {
    final limite = t.renderObject<RenderRepaintBoundary>(find.byKey(clave));
    final bytes = await t.runAsync(() async => (await (await limite.toImage(pixelRatio: 2)).toByteData(format: ui.ImageByteFormat.png))!);
    File('$carpeta/$nombre.png').writeAsBytesSync(bytes!.buffer.asUint8List());
  }

  final usuario = Usuario(id: 1, email: 'a@b.c');

  group('Fichaje', () {
    testWidgets('solo ofrece lo que vale ahora: entrada si estás fuera; pausa y salida si estás dentro; fin de pausa y salida en pausa', (t) async {
      final marcas = <String>[];
      final api = _ApiFalsa();
      Future<void> abrir(String estado) async {
        api.estado = estado;
        await t.pumpWidget(_app(FichajeScreen(key: UniqueKey(), api: api, usuario: usuario), [estadoSesionProvider.overrideWith(_SesionFija.new), accionesFichajeProvider.overrideWith((ref) => _AccionesFalsas(ref, marcas))]));
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
      final api = _ApiFalsa()
        ..estado = 'dentro'
        ..eventos = [_ev(1, 'entrada', '08:58'), _ev(2, 'pausa_inicio', '11:00'), _ev(3, 'pausa_fin', '11:15')];
      await t.pumpWidget(_app(FichajeScreen(api: api, usuario: usuario), [estadoSesionProvider.overrideWith(_SesionFija.new), accionesFichajeProvider.overrideWith((ref) => _AccionesFalsas(ref, marcas))]));
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
      final api = _ApiFalsa()
        ..mensajes = [
          _msg(1, 'Marta Ruiz <marta@ejemplo.com>', 'Consulta sobre la renta', 'Hola, quería preguntaros por la deducción de la vivienda habitual', leido: false),
          _msg(2, 'Hacienda <no-reply@aeat.es>', 'Notificación', 'Tiene una notificación pendiente', destacado: true),
        ];
      await t.pumpWidget(_app(CorreoBandejaScreen(api: api), [estadoSesionProvider.overrideWith(_SesionFija.new)]));
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
      final api = _ApiFalsa()..abierto = _msg(5, 'Marta Ruiz <marta@ejemplo.com>', 'Consulta sobre la renta', 'Hola, quería preguntaros por la deducción de la vivienda habitual.', leido: true);
      await t.pumpWidget(_app(CorreoMensajeScreen(api: api, mensajeId: 5, carpetas: const []), [estadoSesionProvider.overrideWith(_SesionFija.new)]));
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

  group('capturas del diseño (Fichaje y Correo)', () {
    for (final oscuro in [false, true]) {
      testWidgets('captura mensaje ${oscuro ? 'oscuro' : 'claro'}', (t) async {
        if (carpeta == null) return;
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 2532);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        final api = _ApiFalsa()..abierto = _msg(5, 'Marta Ruiz <marta@ejemplo.com>', 'Consulta sobre la renta', 'Hola, quería preguntaros por la deducción de la vivienda habitual y los gastos de la reforma del año pasado. ¿Podéis decirme qué papeles necesitáis?', leido: false);
        await t.pumpWidget(_app(CorreoMensajeScreen(api: api, mensajeId: 5, carpetas: const []), [estadoSesionProvider.overrideWith(_SesionFija.new)], oscuro: oscuro, clave: clave));
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
        final api = _ApiFalsa()
          ..estado = 'dentro'
          ..eventos = [_ev(1, 'entrada', '08:58'), _ev(2, 'pausa_inicio', '11:00'), _ev(3, 'pausa_fin', '11:15')];
        await t.pumpWidget(_app(FichajeScreen(api: api, usuario: usuario), [estadoSesionProvider.overrideWith(_SesionFija.new)], oscuro: oscuro, clave: clave));
        await t.pumpAndSettle();
        await capturar(t, clave, 'fichaje_$sufijo');
      });
      testWidgets('captura correo $sufijo', (t) async {
        if (carpeta == null) return;
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 2532);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        final api = _ApiFalsa()
          ..mensajes = [
            _msg(1, 'Marta Ruiz <marta@ejemplo.com>', 'Consulta sobre la renta', 'Hola, quería preguntaros por la deducción de la vivienda habitual y los gastos de la reforma', leido: false),
            _msg(2, 'Hacienda <no-reply@aeat.es>', 'Notificación electrónica pendiente', 'Tiene una notificación pendiente de lectura en la sede', destacado: true),
            _msg(3, 'Luis Mora <luis@acme.es>', 'Facturas de septiembre', 'Adjunto las facturas del mes para que las contabilicéis'),
            _msg(4, 'Banco Norte <avisos@banconorte.es>', 'Resumen de movimientos', 'Su resumen mensual ya está disponible', leido: false),
          ];
        await t.pumpWidget(_app(CorreoBandejaScreen(api: api), [estadoSesionProvider.overrideWith(_SesionFija.new)], oscuro: oscuro, clave: clave));
        await t.pumpAndSettle();
        await capturar(t, clave, 'correo_$sufijo');
      });
    }
  });
}
