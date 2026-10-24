import 'package:flutter/material.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:intl/intl.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/api/cliente.dart';
import 'package:guilda_work_mobile/api/generado/modelos.g.dart';
import 'package:guilda_work_mobile/funciones/avisos/avisos_controlador.dart';
import 'package:guilda_work_mobile/funciones/avisos/avisos_screen.dart';
import 'package:guilda_work_mobile/funciones/busqueda/busqueda_screen.dart';
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/nucleo/abrir_destino.dart';
import 'package:guilda_work_mobile/nucleo/avisos.dart';
import 'package:guilda_work_mobile/nucleo/destinos.dart';
import 'package:guilda_work_mobile/nucleo/servicios.dart';
import 'package:guilda_work_mobile/nucleo/sesion.dart';

class _Ctx implements ContextoApi {
  @override
  Future<String> servidor() async => 'https://s.test';
  @override
  Future<String?> token() async => 't';
  @override
  String? get despacho => null;
  @override
  String get idioma => 'es';
  @override
  String get versionApp => '1.0.0';
  @override
  String get plataforma => 'android';
  @override
  Future<void> alSesionExpirada() async {}
  @override
  Future<void> alRequerirActualizacion({String? urlTienda}) async {}
}

/// Cliente que no sale a la red: anota las llamadas.
class _ClienteFalso extends ClienteApi {
  final List<String> llamadas = [];
  _ClienteFalso() : super(_Ctx());
  @override
  Future<dynamic> enviar(String metodo, String ruta, {Map<String, dynamic>? consulta, Object? cuerpo, bool multipart = false, bool binario = false}) async {
    llamadas.add('$metodo $ruta');
    return null;
  }
}

class _AvisosFalso extends AvisosControlador {
  final NotificacionesRespuesta datos;
  _AvisosFalso(this.datos);
  @override
  Future<NotificacionesRespuesta> build() async => datos;
}

class _SesionFija extends SesionControl {
  @override
  EstadoSesion build() => const EstadoSesion(fase: FaseSesion.conSesion);
}

String _iso(DateTime d) => '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}T${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';

Notificacion _aviso(int id, String titulo, DateTime cuando, {bool leido = false, String tipo = 'tarea', int? destinoId = 5, String canal = 'tareas'}) => Notificacion.fromJson({
      'id': id, 'tipo': 'tarea_asignada', 'titulo': titulo, 'cuerpo': 'detalle $id', 'url': '/tareas/$id', 'creado_en': _iso(cuando),
      'leido_en': leido ? _iso(cuando) : null, 'destino': {'tipo': tipo, 'id': destinoId}, 'canal': canal,
    });

NavegadorDeAvisos _navegador(List<(Destino, String?)> abiertos) => NavegadorDeAvisos(
      haySesion: () => true,
      despachoActivo: () => null,
      despachosPropios: () => {},
      confirmarCambio: (_) async => true,
      cambiarDespacho: (_) async {},
      abrir: (d, {urlWeb}) async => abiertos.add((d, urlWeb)),
    );

Widget _app(Widget home, List<Override> overrides) => ProviderScope(
      overrides: overrides,
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('es'),
        home: home,
      ),
    );

void main() {
  setUpAll(() => initializeDateFormatting('es'));

  group('Avisos', () {
    final ahora = DateTime.now();
    final hace12Dias = ahora.subtract(const Duration(days: 12));
    NotificacionesRespuesta bandeja() => NotificacionesRespuesta(noLeidas: 2, notificaciones: [
          _aviso(1, 'Te asignan una tarea', ahora),
          _aviso(2, 'Vencimiento próximo', ahora.subtract(const Duration(days: 1)), tipo: 'vencimiento', destinoId: 41, canal: 'fiscal'),
          _aviso(3, 'Resumen semanal', hace12Dias, leido: true, canal: 'resumenes'),
        ]);

    Widget montar(NotificacionesRespuesta datos, _ClienteFalso cliente, List<(Destino, String?)> abiertos) => _app(const AvisosScreen(), [
          avisosProvider.overrideWith(() => _AvisosFalso(datos)),
          clienteApiProvider.overrideWithValue(cliente),
          estadoSesionProvider.overrideWith(_SesionFija.new),
          navegadorDeAvisosProvider.overrideWithValue(_navegador(abiertos)),
        ]);

    testWidgets('agrupa por día: hoy, ayer y fecha', (t) async {
      await t.pumpWidget(montar(bandeja(), _ClienteFalso(), []));
      await t.pumpAndSettle();
      expect(find.text('Hoy'), findsOneWidget);
      expect(find.text('Ayer'), findsOneWidget);
      // más de una semana atrás: día y mes («5 ene»), o con año si cambió el año
      expect(find.text((hace12Dias.year == ahora.year ? DateFormat.MMMd('es') : DateFormat.yMMMd('es')).format(hace12Dias)), findsOneWidget);
      expect(find.text('Te asignan una tarea'), findsOneWidget);
    });

    testWidgets('tocar un aviso abre su destino con la URL de la web de respaldo', (t) async {
      final abiertos = <(Destino, String?)>[];
      await t.pumpWidget(montar(bandeja(), _ClienteFalso(), abiertos));
      await t.pumpAndSettle();
      await t.tap(find.text('Vencimiento próximo'));
      expect((abiertos.single.$1.tipo, abiertos.single.$1.id), ('vencimiento', 41));
      expect(abiertos.single.$2, '/tareas/2');
    });

    testWidgets('«marcar todo como leído» avisa al servidor y quita el botón', (t) async {
      final cliente = _ClienteFalso();
      await t.pumpWidget(montar(bandeja(), cliente, []));
      await t.pumpAndSettle();
      await t.tap(find.byTooltip('Marcar todo como leído'));
      await t.pumpAndSettle();
      expect(cliente.llamadas, ['POST /notificaciones/leidas']);
      expect(find.byTooltip('Marcar todo como leído'), findsNothing);
    });

    testWidgets('deslizar borra el aviso', (t) async {
      final cliente = _ClienteFalso();
      await t.pumpWidget(montar(bandeja(), cliente, []));
      await t.pumpAndSettle();
      await t.drag(find.text('Te asignan una tarea'), const Offset(-600, 0));
      await t.pumpAndSettle();
      expect(cliente.llamadas, ['DELETE /notificaciones/1']);
      expect(find.text('Te asignan una tarea'), findsNothing);
      expect(find.text('Aviso eliminado'), findsOneWidget);
    });

    testWidgets('sin avisos', (t) async {
      await t.pumpWidget(montar(const NotificacionesRespuesta(noLeidas: 0, notificaciones: []), _ClienteFalso(), []));
      await t.pumpAndSettle();
      expect(find.text('No tienes avisos.'), findsOneWidget);
    });
  });

  group('Búsqueda', () {
    Widget montar(Buscador buscador, List<(Destino, String?)> abiertos) => _app(const BusquedaScreen(), [
          buscadorProvider.overrideWithValue(buscador),
          navegadorDeAvisosProvider.overrideWithValue(_navegador(abiertos)),
        ]);

    testWidgets('con menos de dos letras no busca', (t) async {
      var llamadas = 0;
      await t.pumpWidget(montar((q) async {
        llamadas++;
        return [];
      }, []));
      expect(find.text('Escribe al menos dos letras.'), findsOneWidget);
      await t.enterText(find.byType(TextField), 'a');
      await t.pump(const Duration(milliseconds: 500));
      expect(llamadas, 0);
    });

    testWidgets('busca al dejar de escribir y enseña los resultados; tocar uno abre su destino', (t) async {
      final preguntas = <String>[];
      final abiertos = <(Destino, String?)>[];
      await t.pumpWidget(montar((q) async {
        preguntas.add(q);
        return [
          ResultadoBusqueda.desdeJson({'tipo': 'tarea', 'texto': 'Llamar a Acme', 'destino': {'tipo': 'tarea', 'id': 5}, 'url': '/tareas/5'}),
          ResultadoBusqueda.desdeJson({'tipo': 'cliente_fiscal', 'texto': 'Acme SL B123', 'destino': {'tipo': 'cliente_fiscal', 'id': 9}}),
        ];
      }, abiertos));
      await t.enterText(find.byType(TextField), 'ac');
      await t.pump(const Duration(milliseconds: 100));
      await t.enterText(find.byType(TextField), 'acme');
      await t.pump(const Duration(milliseconds: 400));
      await t.pumpAndSettle();
      expect(preguntas, ['acme']); // el 'ac' se descartó: solo se busca al parar
      expect(find.text('Llamar a Acme'), findsOneWidget);
      expect(find.text('Tarea'), findsOneWidget);
      expect(find.text('Cliente'), findsOneWidget);
      await t.tap(find.text('Llamar a Acme'));
      expect((abiertos.single.$1.tipo, abiertos.single.$1.id, abiertos.single.$2), ('tarea', 5, '/tareas/5'));
    });

    testWidgets('sin resultados y con error', (t) async {
      await t.pumpWidget(montar((q) async => [], []));
      await t.enterText(find.byType(TextField), 'zzz');
      await t.pump(const Duration(milliseconds: 400));
      await t.pumpAndSettle();
      expect(find.text('Sin resultados para «zzz».'), findsOneWidget);

      await t.pumpWidget(montar((q) async => throw Exception('caído'), []));
      await t.enterText(find.byType(TextField), 'acme');
      await t.pump(const Duration(milliseconds: 400));
      await t.pumpAndSettle();
      expect(find.text('No se ha podido completar. Inténtalo de nuevo.'), findsOneWidget);
    });
  });
}
