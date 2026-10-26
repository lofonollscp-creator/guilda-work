import 'package:flutter/material.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:intl/intl.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'ayudas/pantallas.dart' as aux;
import 'package:guilda_work_mobile/api/cliente.dart';
import 'package:guilda_work_mobile/api/generado/modelos.g.dart';
import 'package:guilda_work_mobile/funciones/avisos/avisos_controlador.dart';
import 'package:guilda_work_mobile/funciones/avisos/avisos_screen.dart';
import 'package:guilda_work_mobile/funciones/avisos/comunicados.dart';
import 'package:guilda_work_mobile/funciones/busqueda/busqueda_screen.dart';
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/nucleo/abrir_destino.dart';
import 'package:guilda_work_mobile/nucleo/avisos.dart';
import 'package:guilda_work_mobile/nucleo/destinos.dart';
import 'package:guilda_work_mobile/nucleo/servicios.dart';
import 'package:guilda_work_mobile/nucleo/sesion.dart';

class _Ctx implements ContextoApi {
  @override
  int? get usuarioId => 1;
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
  /// Las escrituras (todo menos GET), en orden.
  final List<String> llamadas = [];
  NotificacionesRespuesta? bandeja;
  _ClienteFalso() : super(_Ctx());
  @override
  Future<dynamic> enviar(String metodo, String ruta, {Map<String, dynamic>? consulta, Object? cuerpo, bool multipart = false, bool binario = false}) async {
    if (metodo == 'GET') return ruta == '/notificaciones' ? bandeja?.toJson() : null;
    llamadas.add('$metodo $ruta');
    return null;
  }
}

class _ComunicadosFalso extends ComunicadosControlador {
  final List<Comunicado> lista;
  final List<int> cerrados = [];
  _ComunicadosFalso(this.lista);
  @override
  Future<List<Comunicado>> build() async => lista;
  @override
  Future<void> cerrar(int id) async {
    cerrados.add(id);
    state = AsyncData([for (final c in lista) if (c.id != id) c]);
  }
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

    Widget montar(NotificacionesRespuesta datos, _ClienteFalso cliente, List<(Destino, String?)> abiertos, {_ComunicadosFalso? comunicados}) => _app(const AvisosScreen(), [
          comunicadosProvider.overrideWith(() => comunicados ?? _ComunicadosFalso(const [])),
          clienteApiProvider.overrideWithValue(cliente..bandeja = datos),
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

    testWidgets('abrir un aviso sin leer lo marca leído (solo ese) y baja la cuenta', (t) async {
      final cliente = _ClienteFalso();
      await t.pumpWidget(montar(bandeja(), cliente, []));
      await t.pumpAndSettle();
      expect(find.text('Nuevo'), findsNWidgets(2));
      await t.tap(find.text('Te asignan una tarea'));
      await t.pumpAndSettle();
      expect(cliente.llamadas, ['POST /notificaciones/1/leida']);
      expect(find.text('Nuevo'), findsOneWidget);
      // uno ya leído no vuelve a avisar al servidor
      await t.tap(find.text('Resumen semanal'));
      expect(cliente.llamadas, ['POST /notificaciones/1/leida']);
    });

    testWidgets('las píldoras filtran por sin leer y por familia', (t) async {
      await t.pumpWidget(montar(bandeja(), _ClienteFalso(), []));
      await t.pumpAndSettle();
      expect(find.text('Resumen semanal'), findsOneWidget);
      await t.tap(find.text('Sin leer (2)'));
      await t.pumpAndSettle();
      expect(find.text('Resumen semanal'), findsNothing);
      expect(find.text('Te asignan una tarea'), findsOneWidget);
      await t.tap(find.text('Fiscal y clientes'));
      await t.pumpAndSettle();
      expect(find.text('Te asignan una tarea'), findsNothing);
      expect(find.text('Vencimiento próximo'), findsOneWidget);
      await t.tap(find.text('Todos'));
      await t.pumpAndSettle();
      expect(find.text('Resumen semanal'), findsOneWidget);
    });

    testWidgets('un comunicado se enseña, y se cierra', (t) async {
      final com = _ComunicadosFalso([const Comunicado(id: 3, titulo: 'Mantenimiento', texto: 'Esta noche', nivel: ComunicadoNivel.aviso), const Comunicado(id: 4, titulo: 'Incidencia', nivel: ComunicadoNivel.critico)]);
      await t.pumpWidget(montar(bandeja(), _ClienteFalso(), [], comunicados: com));
      await t.pumpAndSettle();
      expect(find.text('Mantenimiento · Esta noche'), findsOneWidget);
      expect(find.text('Incidencia'), findsOneWidget);
      expect(find.text('Cerrar'), findsOneWidget); // el crítico no se puede cerrar
      await t.tap(find.text('Cerrar'));
      await t.pumpAndSettle();
      expect(com.cerrados, [3]);
      expect(find.text('Mantenimiento · Esta noche'), findsNothing);
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

    testWidgets('deslizar quita el aviso y lo borra al acabar el plazo de «Deshacer»', (t) async {
      final cliente = _ClienteFalso();
      await t.pumpWidget(montar(bandeja(), cliente, []));
      await t.pumpAndSettle();
      await t.drag(find.text('Te asignan una tarea'), const Offset(-600, 0));
      await t.pumpAndSettle();
      expect(find.text('Te asignan una tarea'), findsNothing);
      expect(find.text('Aviso eliminado'), findsOneWidget);
      expect(cliente.llamadas, isEmpty); // aún se puede deshacer
      await t.pump(AvisosControlador.plazoDeshacer + const Duration(seconds: 1));
      expect(cliente.llamadas, ['DELETE /notificaciones/1']);
    });

    testWidgets('«Deshacer» devuelve el aviso y no llega a borrarlo', (t) async {
      final cliente = _ClienteFalso();
      await t.pumpWidget(montar(bandeja(), cliente, []));
      await t.pumpAndSettle();
      await t.drag(find.text('Te asignan una tarea'), const Offset(-600, 0));
      await t.pumpAndSettle();
      await t.tap(find.text('Deshacer'));
      await t.pumpAndSettle();
      expect(find.text('Te asignan una tarea'), findsOneWidget);
      await t.pump(AvisosControlador.plazoDeshacer + const Duration(seconds: 1));
      expect(cliente.llamadas, isEmpty);
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

    testWidgets('los resultados traen título, fragmento y fecha, y se filtran por tipo con píldoras', (t) async {
      await t.pumpWidget(montar((q) async => [
            ResultadoBusqueda.desdeJson({'tipo': 'mensaje', 'texto': 'Factura de octubre y más', 'titulo': 'Factura de octubre', 'fragmento': 'Adjunto la factura de Acme', 'fecha': '2026-10-20T09:30', 'destino': {'tipo': 'correo', 'id': 2}}),
            ResultadoBusqueda.desdeJson({'tipo': 'tarea', 'texto': 'Cobrar la factura', 'destino': {'tipo': 'tarea', 'id': 5}}),
            ResultadoBusqueda.desdeJson({'tipo': 'nota', 'texto': 'Factura pendiente', 'destino': {'tipo': 'nota', 'id': 6}}),
          ], []));
      await t.enterText(find.byType(TextField), 'factura');
      await t.pump(const Duration(milliseconds: 400));
      await t.pumpAndSettle();
      expect(find.text('Todo (3)'), findsOneWidget);
      expect(find.text('Adjunto la factura de Acme', findRichText: true), findsOneWidget);
      await t.tap(find.text('Tareas (1)'));
      await t.pumpAndSettle();
      expect(find.text('Cobrar la factura', findRichText: true), findsOneWidget);
      expect(find.text('Factura pendiente', findRichText: true), findsNothing);
    });

    testWidgets('lo buscado se recuerda y se repite con un toque; se puede borrar', (t) async {
      SharedPreferences.setMockInitialValues({});
      final preguntas = <String>[];
      await t.pumpWidget(montar((q) async {
        preguntas.add(q);
        return [ResultadoBusqueda.desdeJson({'tipo': 'tarea', 'texto': 'Llamar a Acme', 'destino': {'tipo': 'tarea', 'id': 5}})];
      }, []));
      await t.enterText(find.byType(TextField), 'acme');
      await t.pump(const Duration(milliseconds: 400));
      await t.pumpAndSettle();
      await t.tap(find.text('Llamar a Acme', findRichText: true));
      await t.pumpAndSettle();
      // otra visita a la pantalla: lo recuerda
      await t.pumpWidget(const SizedBox());
      await t.pumpWidget(montar((q) async {
        preguntas.add(q);
        return [];
      }, []));
      await t.pumpAndSettle();
      expect(find.text('Búsquedas recientes'), findsOneWidget);
      await t.tap(find.text('acme'));
      await t.pump(const Duration(milliseconds: 50));
      expect(preguntas, ['acme', 'acme']);
      await t.pumpWidget(const SizedBox());
      await t.pumpWidget(montar((q) async => [], []));
      await t.pumpAndSettle();
      await t.tap(find.text('Borrar'));
      await t.pumpAndSettle();
      expect(find.text('Búsquedas recientes'), findsNothing);
    });

    test('resaltar pone en negrita lo buscado, sin distinguir mayúsculas', () {
      final span = resaltar('Llamar a ACME SL', 'acme sl', const TextStyle());
      final negritas = [for (final c in span.children!.cast<TextSpan>()) if (c.style?.fontWeight == FontWeight.w800) c.text];
      expect(negritas, ['ACME', 'SL']);
      expect(resaltar('Sin nada', 'a', const TextStyle()).text, 'Sin nada'); // una letra no se resalta
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

  // Capturas con el tema y las fuentes reales: solo con CAPTURAS=<carpeta>.
  group('capturas del diseño', () {
    setUpAll(aux.cargarFuentesParaCapturas);
    for (final oscuro in [false, true]) {
      final sufijo = oscuro ? 'oscuro' : 'claro';
      testWidgets('captura avisos $sufijo', (t) async {
        if (aux.carpetaCapturas == null) return;
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 2532);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        final ahora = DateTime.now();
        final bandeja = NotificacionesRespuesta(noLeidas: 3, notificaciones: [
          _aviso(1, 'Te asignan una tarea', ahora),
          _aviso(2, 'Vence el modelo 303 de Acme SL', ahora.subtract(const Duration(hours: 3)), tipo: 'vencimiento', destinoId: 41, canal: 'fiscal'),
          _aviso(3, 'Nuevo correo de Ana Pla', ahora.subtract(const Duration(hours: 5)), canal: 'correo'),
          _aviso(4, 'Resumen semanal', ahora.subtract(const Duration(days: 1)), leido: true, canal: 'resumenes'),
          _aviso(5, 'Ausencia aprobada', ahora.subtract(const Duration(days: 12)), leido: true, canal: 'equipo'),
        ]);
        final cliente = _ClienteFalso()..bandeja = bandeja;
        await t.pumpWidget(aux.appDePantalla(const AvisosScreen(), [
          comunicadosProvider.overrideWith(() => _ComunicadosFalso(const [Comunicado(id: 1, titulo: 'Mantenimiento', texto: 'esta noche a las 2:00', nivel: ComunicadoNivel.aviso)])),
          clienteApiProvider.overrideWithValue(cliente),
          estadoSesionProvider.overrideWith(_SesionFija.new),
          navegadorDeAvisosProvider.overrideWithValue(_navegador([])),
        ], oscuro: oscuro, clave: clave));
        await t.pumpAndSettle();
        await aux.capturar(t, clave, 'avisos_$sufijo');
      });
      testWidgets('captura busqueda $sufijo', (t) async {
        if (aux.carpetaCapturas == null) return;
        SharedPreferences.setMockInitialValues({});
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 2532);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        await t.pumpWidget(aux.appDePantalla(const BusquedaScreen(), [
          buscadorProvider.overrideWithValue((q) async => [
                ResultadoBusqueda.desdeJson({'tipo': 'mensaje', 'texto': 'x', 'titulo': 'Factura de octubre de Acme', 'fragmento': 'Adjunto la factura del trimestre para que la reviséis antes del lunes', 'fecha': '2026-10-20T09:30', 'destino': {'tipo': 'correo', 'id': 2}}),
                ResultadoBusqueda.desdeJson({'tipo': 'tarea', 'texto': 'Cobrar la factura de Beta SA', 'fecha': '2026-10-25', 'destino': {'tipo': 'tarea', 'id': 5}}),
                ResultadoBusqueda.desdeJson({'tipo': 'nota', 'texto': 'Factura pendiente de confirmar', 'fecha': '2026-10-02', 'destino': {'tipo': 'nota', 'id': 6}}),
                ResultadoBusqueda.desdeJson({'tipo': 'cliente_fiscal', 'texto': 'Facturas del Norte SL B12345678', 'destino': {'tipo': 'cliente_fiscal', 'id': 9}}),
              ]),
          navegadorDeAvisosProvider.overrideWithValue(_navegador([])),
        ], oscuro: oscuro, clave: clave));
        await t.enterText(find.byType(TextField), 'factura');
        await t.pump(const Duration(milliseconds: 400));
        await t.pumpAndSettle();
        await aux.capturar(t, clave, 'busqueda_$sufijo');
      });
    }
  });
}
