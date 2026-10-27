import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/api/errores.dart';
import 'package:guilda_work_mobile/api/generado/modelos.g.dart';
import 'package:guilda_work_mobile/funciones/papelera/papelera_repositorio.dart';
import 'package:guilda_work_mobile/funciones/papelera/papelera_screen.dart';
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/nucleo/sesion.dart';
import 'package:guilda_work_mobile/services/api_client.dart' as sv;
import 'package:guilda_work_mobile/theme/app_theme.dart';

import 'ayudas/pantallas.dart' as aux;

String _hace(int dias) => DateTime.now().subtract(Duration(days: dias, minutes: 5)).toIso8601String().substring(0, 19);

Papelera _p(String origen, int id, String texto, {int dias = 1, String? categoria, String? tipo, String? cliente}) =>
    Papelera.fromJson({'origen': origen, 'id': id, 'texto': texto, 'papelera_en': _hace(dias), 'categoria_nombre': categoria, 'tipo': tipo, 'cliente_nombre': cliente});

class _RepoFalso implements PapeleraRepositorio {
  final List<String> registro = [];
  List<Papelera> propia = [];
  List<Papelera> fiscal = [];
  ApiException? falla;

  @override
  Future<List<ElementoPapelera>> listar({bool conFiscal = false}) async {
    registro.add('listar:$conFiscal');
    return [for (final p in propia) ElementoPapelera(p), if (conFiscal) for (final p in fiscal) ElementoPapelera(p, fiscal: true)];
  }

  @override
  Future<void> restaurar(ElementoPapelera e) async {
    if (falla != null) throw falla!;
    registro.add('restaurar:${e.fiscal ? 'fiscal:' : ''}${e.origen}:${e.id}');
  }

  @override
  Future<void> eliminarParaSiempre(ElementoPapelera e) async => registro.add('eliminar:${e.origen}:${e.id}');
}

class _Sesion extends SesionControl {
  final bool despacho;
  _Sesion(this.despacho);
  @override
  EstadoSesion build() => EstadoSesion(fase: FaseSesion.conSesion, usuario: sv.Usuario(id: 1, email: 'a@b.c', tenantId: despacho ? 3 : null));
}

List<Override> _over(_RepoFalso repo, {bool despacho = false}) => [
      papeleraRepositorioProvider.overrideWithValue(repo),
      estadoSesionProvider.overrideWith(() => _Sesion(despacho)),
    ];

Widget _app(Widget home, List<Override> overrides, {bool oscuro = false}) => ProviderScope(
      key: UniqueKey(),
      overrides: overrides,
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        locale: const Locale('es'),
        theme: AppTheme.light,
        darkTheme: AppTheme.dark,
        themeMode: oscuro ? ThemeMode.dark : ThemeMode.light,
        home: home,
      ),
    );

_RepoFalso _repo() => _RepoFalso()
  ..propia = [
    _p('nota', 1, 'Reunión del lunes', dias: 2),
    _p('tarea_outlook', 2, 'Presentar el 303', dias: 28, categoria: 'IVA'),
    _p('menu', 3, 'Proyecto viejo', dias: 5),
    _p('tarea', 4, 'Llamada', dias: 1, tipo: 'instantanea', categoria: 'Agenda'),
  ]
  ..fiscal = [_p('vencimiento_fiscal', 9, '303 2026-T3', dias: 3, cliente: 'Acme SL')];

void main() {
  test('los días que quedan se cuentan desde el borrado, sin pasar de 30 ni bajar de 0', () {
    final ahora = DateTime(2026, 10, 27, 12);
    expect(diasRestantes('2026-10-27T10:00:00', ahora: ahora), 30);
    expect(diasRestantes('2026-10-17T10:00:00', ahora: ahora), 20);
    expect(diasRestantes('2026-09-01T10:00:00', ahora: ahora), 0);
    expect(diasRestantes(null, ahora: ahora), 30);
    expect(diasRestantes('basura', ahora: ahora), 30);
  });

  testWidgets('enseña cada cosa con su tipo, su contexto y los días que le quedan', (t) async {
    await t.pumpWidget(_app(const PapeleraScreen(), _over(_repo())));
    await t.pumpAndSettle();
    expect(find.text('Reunión del lunes'), findsOneWidget);
    expect(find.text('Quedan 2 días'), findsOneWidget); // la tarea borrada hace 28
    expect(find.text('Quedan 28 días'), findsOneWidget); // la nota borrada hace 2
    expect(find.text('IVA'), findsOneWidget);
    expect(find.text('Proyecto'), findsOneWidget);
    expect(find.text('Evento'), findsOneWidget);
    expect(find.textContaining('Lo que borras se queda aquí 30 días'), findsOneWidget);
  });

  testWidgets('sin despacho no se pide lo fiscal; con despacho sí', (t) async {
    final r = _repo();
    await t.pumpWidget(_app(const PapeleraScreen(), _over(r)));
    await t.pumpAndSettle();
    expect(r.registro, ['listar:false']);
    expect(find.text('303 2026-T3', skipOffstage: false), findsNothing);
    final r2 = _repo();
    await t.pumpWidget(_app(const PapeleraScreen(), _over(r2, despacho: true)));
    await t.pumpAndSettle();
    expect(r2.registro, ['listar:true']);
    expect(find.text('303 2026-T3', skipOffstage: false), findsOneWidget);
    expect(find.text('Acme SL', skipOffstage: false), findsOneWidget);
  });

  testWidgets('las píldoras filtran por tipo', (t) async {
    await t.pumpWidget(_app(const PapeleraScreen(), _over(_repo(), despacho: true)));
    await t.pumpAndSettle();
    expect(find.text('Todo (5)'), findsOneWidget);
    await t.tap(find.text('Tareas (2)'));
    await t.pumpAndSettle();
    expect(find.text('Presentar el 303'), findsOneWidget);
    expect(find.text('Reunión del lunes'), findsNothing);
    await t.ensureVisible(find.text('Fiscal (1)'));
    await t.tap(find.text('Fiscal (1)'));
    await t.pumpAndSettle();
    expect(find.text('303 2026-T3'), findsOneWidget);
    expect(find.text('Presentar el 303'), findsNothing);
  });

  testWidgets('restaurar la quita de la lista y avisa; si falla, se queda y dice por qué', (t) async {
    final r = _repo();
    await t.pumpWidget(_app(const PapeleraScreen(), _over(r)));
    await t.pumpAndSettle();
    r.falla = ApiException('Sin permiso', status: 403);
    await t.tap(find.text('Restaurar').first);
    await t.pumpAndSettle();
    expect(find.text('Sin permiso'), findsOneWidget);
    expect(find.text('Reunión del lunes'), findsOneWidget);
    r.falla = null;
    await t.tap(find.text('Restaurar').first);
    await t.pumpAndSettle();
    expect(r.registro, contains('restaurar:nota:1'));
    expect(find.text('Reunión del lunes'), findsNothing);
    expect(find.text('Recuperado'), findsOneWidget);
  });

  testWidgets('restaurar algo fiscal usa su propia papelera', (t) async {
    final r = _repo();
    await t.pumpWidget(_app(const PapeleraScreen(), _over(r, despacho: true)));
    await t.pumpAndSettle();
    await t.ensureVisible(find.text('Fiscal (1)'));
    await t.tap(find.text('Fiscal (1)'));
    await t.pumpAndSettle();
    await t.tap(find.text('Restaurar'));
    await t.pumpAndSettle();
    expect(r.registro, contains('restaurar:fiscal:vencimiento_fiscal:9'));
  });

  testWidgets('eliminar para siempre pide confirmación (más fuerte en un proyecto) y no existe para lo fiscal', (t) async {
    final r = _repo();
    await t.pumpWidget(_app(const PapeleraScreen(), _over(r, despacho: true)));
    await t.pumpAndSettle();
    expect(find.byType(PopupMenuButton<String>), findsNWidgets(4)); // el fiscal no lleva menú
    await t.tap(find.byType(PopupMenuButton<String>).at(2)); // el proyecto
    await t.pumpAndSettle();
    await t.tap(find.text('Eliminar para siempre'));
    await t.pumpAndSettle();
    expect(find.textContaining('todo lo que contiene'), findsOneWidget);
    await t.tap(find.text('Cancelar'));
    await t.pumpAndSettle();
    expect(r.registro.where((x) => x.startsWith('eliminar')), isEmpty);
    await t.tap(find.byType(PopupMenuButton<String>).at(2));
    await t.pumpAndSettle();
    await t.tap(find.text('Eliminar para siempre'));
    await t.pumpAndSettle();
    await t.tap(find.widgetWithText(FilledButton, 'Eliminar para siempre'));
    await t.pumpAndSettle();
    expect(r.registro, contains('eliminar:menu:3'));
    expect(find.text('Proyecto viejo'), findsNothing);
  });

  testWidgets('vacía: lo dice', (t) async {
    await t.pumpWidget(_app(const PapeleraScreen(), _over(_RepoFalso())));
    await t.pumpAndSettle();
    expect(find.text('La papelera está vacía.'), findsOneWidget);
  });

  for (final oscuro in [false, true]) {
    testWidgets('cumple las pautas de accesibilidad (${oscuro ? 'oscuro' : 'claro'})', (t) async {
      final h = t.ensureSemantics();
      await t.pumpWidget(_app(const PapeleraScreen(), _over(_repo(), despacho: true), oscuro: oscuro));
      await t.pumpAndSettle();
      await expectLater(t, meetsGuideline(androidTapTargetGuideline));
      await expectLater(t, meetsGuideline(labeledTapTargetGuideline));
      await expectLater(t, meetsGuideline(textContrastGuideline));
      h.dispose();
    });
  }

  group('capturas del diseño', () {
    setUpAll(aux.cargarFuentesParaCapturas);
    for (final oscuro in [false, true]) {
      testWidgets('captura papelera ${oscuro ? 'oscuro' : 'claro'}', (t) async {
        if (aux.carpetaCapturas == null) return;
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 2532);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        await t.pumpWidget(aux.appDePantalla(const PapeleraScreen(), _over(_repo(), despacho: true), oscuro: oscuro, clave: clave));
        await t.pumpAndSettle();
        await aux.capturar(t, clave, 'papelera_${oscuro ? 'oscuro' : 'claro'}');
      });
    }
  });
}
