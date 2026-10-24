import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/api/errores.dart';
import 'package:guilda_work_mobile/api/fechas.dart';
import 'package:guilda_work_mobile/diseno/componentes.dart';
import 'package:guilda_work_mobile/diseno/estados.dart';
import 'package:guilda_work_mobile/diseno/formatos.dart';
import 'package:guilda_work_mobile/diseno/tokens.g.dart';
import 'package:guilda_work_mobile/dominio/tarea.dart';
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/theme/app_theme.dart';
import 'package:guilda_work_mobile/theme/brand_colors.dart';
import 'package:intl/date_symbol_data_local.dart';

double _contraste(Color a, Color b) {
  final la = a.computeLuminance(), lb = b.computeLuminance();
  final (claro, oscuro) = la > lb ? (la, lb) : (lb, la);
  return (claro + 0.05) / (oscuro + 0.05);
}

Widget _app(Widget hijo, {ThemeData? tema, Locale locale = const Locale('es')}) => MaterialApp(
      theme: tema ?? AppTheme.light,
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: locale,
      home: Scaffold(body: hijo),
    );

void main() {
  setUpAll(() async {
    for (final l in ['es', 'ca', 'en', 'fr']) {
      await initializeDateFormatting(l);
    }
  });

  group('tokens y tema', () {
    test('BrandColors sale de los tokens generados de la web (una sola fuente)', () {
      expect(BrandColors.primaryLight, TokensClaro.primary);
      expect(BrandColors.bgDark, TokensOscuro.bg);
      expect(BrandColors.radius, 12.0);
      expect(BrandColors.radiusSmall, 10.0);
      expect(BrandColors.radiusLarge, 22.0);
    });

    test('Manrope en todo el texto, con Inter de respaldo; títulos 20–28 y cuerpo 15–16', () {
      final t = AppTheme.light.textTheme;
      expect(t.bodyMedium!.fontFamily, 'Manrope');
      expect(t.bodyMedium!.fontFamilyFallback, ['Inter']);
      expect(t.titleLarge!.fontFamily, 'Manrope');
      expect([t.headlineLarge!.fontSize, t.headlineMedium!.fontSize, t.titleLarge!.fontSize], [28, 24, 20]);
      expect([t.bodyLarge!.fontSize, t.bodyMedium!.fontSize], [16, 15]);
    });

    test('las cifras usan números tabulares (se alinean)', () {
      final c = AppTheme.cifra(fontSize: 20);
      expect(c.fontFamily, 'Manrope');
      expect(c.fontFeatures, contains(const FontFeature.tabularFigures()));
    });

    test('el texto de los botones de texto cumple AA en claro (el lima sobre blanco daba 1,5:1)', () {
      final fg = AppTheme.light.textButtonTheme.style!.foregroundColor!.resolve({})!;
      expect(_contraste(fg, TokensClaro.surface), greaterThanOrEqualTo(4.5));
      expect(_contraste(TokensClaro.primary, TokensClaro.surface), lessThan(3)); // y por eso no se usa como texto
    });

    test('objetivos táctiles de al menos 48 dp', () {
      expect(AppTheme.light.filledButtonTheme.style!.minimumSize!.resolve({})!.height, greaterThanOrEqualTo(48));
      expect(AppTheme.light.textButtonTheme.style!.minimumSize!.resolve({})!.height, greaterThanOrEqualTo(48));
    });
  });

  group('estado de la tarea: color + icono + etiqueta, y legible en los dos temas', () {
    for (final e in EstadoTarea.values) {
      for (final (nombre, brillo, superficie) in [('claro', Brightness.light, TokensClaro.surface), ('oscuro', Brightness.dark, TokensOscuro.surface)]) {
        test('${e.name} en $nombre tiene contraste AA', () {
          expect(_contraste(aspectoDe(e).color(brillo), superficie), greaterThanOrEqualTo(4.5), reason: e.name);
        });
      }
    }

    test('«vencida» (rojo) también', () {
      expect(_contraste(aspectoVencida.color(Brightness.light), TokensClaro.surface), greaterThanOrEqualTo(4.5));
      expect(_contraste(aspectoVencida.color(Brightness.dark), TokensOscuro.surface), greaterThanOrEqualTo(4.5));
    });

    test('cada estado tiene un icono distinto (no solo se distingue por el color)', () {
      final iconos = EstadoTarea.values.where((e) => e != EstadoTarea.desconocido).map((e) => aspectoDe(e).icono).toSet();
      expect(iconos.length, EstadoTarea.values.length - 1);
    });
  });

  group('Formatos: una sola forma de escribir fechas', () {
    Future<Formatos> formatos(WidgetTester t, {String idioma = 'es'}) async {
      late Formatos f;
      await t.pumpWidget(_app(Builder(builder: (c) {
        f = Formatos(AppLocalizations.of(c), idioma: idioma, hoy: () => const Fecha(2026, 10, 24));
        return const SizedBox();
      }), locale: Locale(idioma)));
      return f;
    }

    testWidgets('hoy, ayer, mañana; el día de la semana cerca; la fecha lejos; el año si no es este', (t) async {
      final f = await formatos(t);
      expect(f.fecha(const Fecha(2026, 10, 24)), 'hoy');
      expect(f.fecha(const Fecha(2026, 10, 23)), 'ayer');
      expect(f.fecha(const Fecha(2026, 10, 25)), 'mañana');
      expect(f.fecha(const Fecha(2026, 10, 28)), 'mié 28 oct');
      expect(f.fecha(const Fecha(2026, 11, 20)), '20 nov');
      expect(f.fecha(const Fecha(2027, 1, 5)), '5 ene 2027');
    });

    testWidgets('la hora siempre HH:mm; a las 00:00 no se enseña', (t) async {
      final f = await formatos(t);
      expect(f.hora(9, 5), '09:05');
      expect(f.momento(MomentoLocal.parse('2026-10-24T09:05')), 'hoy 09:05');
      expect(f.momento(MomentoLocal.parse('2026-10-24T00:00')), 'hoy');
      expect(f.deServidor('2026-10-23'), 'ayer');
      expect(f.deServidor('2026-10-23T18:30'), 'ayer 18:30');
      expect(f.deServidor('mañana'), null);
    });

    testWidgets('en los cuatro idiomas', (t) async {
      for (final (idioma, hoy, manana) in [('ca', 'avui', 'demà'), ('en', 'today', 'tomorrow'), ('fr', "aujourd'hui", 'demain')]) {
        final f = await formatos(t, idioma: idioma);
        expect(f.fecha(const Fecha(2026, 10, 24)), hoy);
        expect(f.fecha(const Fecha(2026, 10, 25)), manana);
      }
    });

    test('nombre del remitente en vez de «Nombre <correo>»', () {
      expect(nombreDeRemitente('Ana Pla <ana@gestoria.com>'), 'Ana Pla');
      expect(nombreDeRemitente('"Pla, Ana" <ana@gestoria.com>'), 'Pla, Ana');
      expect(nombreDeRemitente('<ana@gestoria.com>'), 'ana@gestoria.com');
      expect(nombreDeRemitente('ana@gestoria.com'), 'ana@gestoria.com');
      expect(nombreDeRemitente('  Hacienda  '), 'Hacienda');
    });
  });

  group('mensajes de error por categoría', () {
    testWidgets('cada categoría dice algo claro y propio; validación enseña el mensaje del servidor', (t) async {
      late AppLocalizations l;
      await t.pumpWidget(_app(Builder(builder: (c) {
        l = AppLocalizations.of(c);
        return const SizedBox();
      })));
      String m(ApiException e) => mensajeDeError(l, e);
      expect(m(ApiException('x', esDeConexion: true)), l.errRed);
      expect(m(ApiException('x', status: 401)), l.errAutenticacion);
      expect(m(ApiException('x', status: 403)), l.errProhibido);
      expect(m(ApiException('x', status: 404)), l.errNoEncontrado);
      expect(m(ApiException('x', status: 423, codigo: 'despacho_bloqueado')), l.errBloqueado);
      expect(m(ApiException('x', status: 409, codigo: 'version_obsoleta')), l.errConflicto);
      expect(m(ApiException('NIF no válido', status: 400)), 'NIF no válido');
      expect(m(ApiException('x', status: 429)), l.errLimite);
      expect(m(ApiException('x', status: 426)), l.errActualizar);
      expect(m(ApiException('x', status: 503)), l.errServidor);
      expect(mensajeDeError(l, StateError('raro')), l.errDesconocido);
      // nunca el texto técnico de una excepción cualquiera
      expect(mensajeDeError(l, Exception('DioException [connection error]...')), isNot(contains('Dio')));
    });
  });

  group('componentes', () {
    testWidgets('EstadoError: mensaje claro, código de soporte y salida (reintentar)', (t) async {
      var reintentos = 0;
      await t.pumpWidget(_app(EstadoError(error: ApiException('x', status: 503, requestId: 'abc123'), alReintentar: () => reintentos++)));
      expect(find.text('Algo ha fallado en el servidor. Inténtalo de nuevo en un momento.'), findsOneWidget);
      expect(find.text('Código de soporte: abc123'), findsOneWidget);
      await t.tap(find.text('Reintentar'));
      expect(reintentos, 1);
    });

    testWidgets('EstadoVacio con una sola acción', (t) async {
      var pulsado = false;
      await t.pumpWidget(_app(EstadoVacio(icono: Icons.mail_outline, titulo: 'Sin correo', detalle: 'Conecta tu cuenta', accion: 'Conectar', alAccionar: () => pulsado = true)));
      await t.tap(find.text('Conectar'));
      expect(pulsado, true);
    });

    testWidgets('el esqueleto se pinta y respeta «reducir movimiento»', (t) async {
      await t.pumpWidget(MediaQuery(data: const MediaQueryData(disableAnimations: true), child: _app(const EsqueletoLista(filas: 3))));
      await t.pump(const Duration(milliseconds: 100));
      expect(find.byType(EsqueletoLista), findsOneWidget);
      expect(t.hasRunningAnimations, false); // quieto, sin bucle de animación
    });

    testWidgets('BannerEstado: icono + texto + acción', (t) async {
      var pulsado = false;
      await t.pumpWidget(_app(BannerEstado(tipo: TipoBanner.sinConexion, texto: 'Sin conexión', accion: 'Reintentar', alAccionar: () => pulsado = true)));
      expect(find.byIcon(Icons.cloud_off_outlined), findsOneWidget);
      await t.tap(find.text('Reintentar'));
      expect(pulsado, true);
    });

    testWidgets('ChipEstado: icono, etiqueta y color del estado', (t) async {
      await t.pumpWidget(_app(const ChipEstado(estado: EstadoTarea.esperando, etiqueta: 'Esperando')));
      expect(find.byIcon(Icons.schedule), findsOneWidget);
      expect(find.text('Esperando'), findsOneWidget);
    });
  });
}
