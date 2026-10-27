import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:guilda_work_mobile/api/errores.dart';
import 'package:guilda_work_mobile/api/generado/modelos.g.dart';
import 'package:guilda_work_mobile/funciones/notas/nota_screen.dart';
import 'package:guilda_work_mobile/funciones/notas/notas_acciones.dart';
import 'package:guilda_work_mobile/funciones/notas/notas_repositorio.dart';
import 'package:guilda_work_mobile/funciones/notas/notas_screen.dart';
import 'package:guilda_work_mobile/funciones/notas/texto_nota.dart';
import 'package:guilda_work_mobile/funciones/tareas/tareas_repositorio.dart' show companerosProvider;
import 'package:guilda_work_mobile/l10n/app_localizations.dart';
import 'package:guilda_work_mobile/nucleo/destinos.dart';
import 'package:guilda_work_mobile/nucleo/sesion.dart';
import 'package:guilda_work_mobile/services/api_client.dart' as sv;
import 'package:guilda_work_mobile/theme/app_theme.dart';

import 'ayudas/pantallas.dart' as aux;
import 'package:guilda_work_mobile/nucleo/servicios.dart';
import 'package:guilda_work_mobile/screens/ia_chat_screen.dart';

Nota _nota(int id, {String? titulo, String texto = 'Texto', bool fijada = false, String rol = 'dueno', int participantes = 0, int adjuntos = 0, String? proyecto, String? dueno, List<Map<String, dynamic>> gente = const []}) => Nota.fromJson({
      'id': id, 'usuario_id': rol == 'dueno' ? 1 : 2, 'titulo': titulo, 'texto': texto, 'fijada': fijada ? 1 : 0, 'creada_en': '2026-10-20T09:30', 'rol': rol, 'n_participantes': participantes, 'n_adjuntos': adjuntos,
      'categoria_nombre': proyecto, 'dueno_nombre': dueno ?? 'Yo', if (gente.isNotEmpty) 'participantes': gente,
    });

class _RepoFalso implements NotasRepositorio {
  final List<String> registro = [];
  List<Nota> notas = [];
  Map<int, Nota> detalle = {};
  List<AdjuntoNota> adj = [];
  List<Proyecto> proy = [];
  ApiException? falloAlEliminar;

  @override
  Future<List<Nota>> listar({AmbitoNotas ambito = AmbitoNotas.todas, String? q, int? proyectoId, int limit = 30, int offset = 0}) async {
    registro.add('listar:${ambito.name}:${q ?? ''}:${proyectoId ?? ''}:$offset');
    return notas;
  }

  @override
  Future<Nota> obtener(int id) async => detalle[id] ?? notas.firstWhere((n) => n.id == id);
  @override
  Future<Nota> editar(int id, {String? texto, String? titulo, bool? fijada}) async {
    registro.add('editar:$id:${texto ?? '-'}:${titulo ?? '-'}');
    return detalle[id]!;
  }

  @override
  Future<Nota> fijar(int id, bool fijada) async {
    registro.add('fijar:$id:$fijada');
    final n = (detalle[id] ?? notas.firstWhere((n) => n.id == id));
    return Nota.fromJson({...n.toJson(), 'fijada': fijada ? 1 : 0});
  }

  @override
  Future<void> eliminar(int id) async {
    registro.add('eliminar:$id');
    if (falloAlEliminar != null) throw falloAlEliminar!;
  }

  @override
  Future<void> restaurar(int id) async => registro.add('restaurar:$id');
  @override
  Future<List<Proyecto>> proyectos() async => proy;
  @override
  Future<List<ParticipanteNota>> compartir(int id, int usuarioId, String rol) async {
    registro.add('compartir:$id:$usuarioId:$rol');
    return [];
  }

  @override
  Future<void> dejarDeCompartir(int id, int usuarioId) async => registro.add('dejar:$id:$usuarioId');
  @override
  Future<List<AdjuntoNota>> adjuntos(int id) async => adj;
  @override
  Future<void> subirAdjunto(int id, MultipartFile archivo) async {}
  @override
  Future<List<int>> descargarAdjunto(int adjuntoId) async => [];
  @override
  Future<void> eliminarAdjunto(int adjuntoId) async => registro.add('quitar-adjunto:$adjuntoId');
}

class _AccionesFalsas implements AccionesNotas {
  final List<String> registro;
  Nota? resultado;
  _AccionesFalsas(this.registro, {this.resultado});
  @override
  Future<({Nota? nota, bool encolada})> crearNota(String texto, {String? titulo, int? categoriaId, DateTime? ahora}) async {
    registro.add('crear:${titulo ?? '-'}:$texto');
    return (nota: resultado, encolada: resultado == null);
  }

  @override
  Future<bool> crear(String texto, {int? categoriaId, DateTime? ahora}) async => (await crearNota(texto)).encolada;
}

class _Sesion extends SesionControl {
  @override
  EstadoSesion build() => EstadoSesion(fase: FaseSesion.conSesion, usuario: sv.Usuario(id: 1, email: 'a@b.c'));
}

List<Override> _over(_RepoFalso repo, {_AccionesFalsas? acciones, List<Companero> companeros = const []}) => [
      notasRepositorioProvider.overrideWithValue(repo),
      if (acciones != null) accionesNotasProvider.overrideWithValue(acciones),
      companerosProvider.overrideWith((ref) async => companeros),
      estadoSesionProvider.overrideWith(_Sesion.new),
    ];

/// La pantalla se abre desde otra (como en la app): así los avisos que deja al cerrarse tienen dónde verse.
Widget _desde(Widget pantalla) => Builder(builder: (c) => Scaffold(body: Center(child: ElevatedButton(onPressed: () => Navigator.of(c).push(MaterialPageRoute(builder: (_) => pantalla)), child: const Text('abrir')))));

Widget _app(Widget home, List<Override> overrides, {bool oscuro = false}) => ProviderScope(
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

void main() {
  group('texto de la nota (el mismo subconjunto de Markdown que la web)', () {
    test('negrita, cursiva y enlaces; la dirección suelta no se come la puntuación', () {
      final t = trozosDeNota('Hola **mundo** y *tú*, mira [la web](https://a.es/x) o https://b.es/y.');
      expect([for (final x in t) (x.tipo, x.texto)], [
        (TrozoNota.texto, 'Hola '),
        (TrozoNota.negrita, 'mundo'),
        (TrozoNota.texto, ' y '),
        (TrozoNota.cursiva, 'tú'),
        (TrozoNota.texto, ', mira '),
        (TrozoNota.enlace, 'la web'),
        (TrozoNota.texto, ' o '),
        (TrozoNota.enlace, 'https://b.es/y'),
        (TrozoNota.texto, '.'),
      ]);
      expect(t[5].url, 'https://a.es/x');
    });

    test('un asterisco dentro de una dirección no es cursiva ni 2*3 una nota en cursiva', () {
      expect(trozosDeNota('https://a.es/*x*/y').single.tipo, TrozoNota.enlace);
      expect(trozosDeNota('2*3 y 4*5').every((x) => x.tipo == TrozoNota.texto), isTrue);
    });

    test('listas con guion, asterisco y números; los renglones seguidos son un párrafo', () {
      final b = bloquesDeNota('Primero\nsigue\n\n- uno\n* dos\n3. tres');
      expect([for (final x in b) (x.item, x.texto)], [(null, 'Primero\nsigue'), ('•', 'uno'), ('•', 'dos'), ('3.', 'tres')]);
    });

    test('el texto plano de la lista no lleva marcas', () {
      expect(textoPlanoDeNota('**Ojo** con [esto](https://a.es)\n- uno\n- dos'), 'Ojo con esto · uno · dos');
    });

    testWidgets('se pinta con negrita y sin HTML a la vista', (t) async {
      await t.pumpWidget(_app(const Scaffold(body: TextoNota('Dame **negrita** y <b>no</b>')), const []));
      final rica = t.widget<RichText>(find.byType(RichText).last);
      final trozos = <TextSpan>[];
      rica.text.visitChildren((s) {
        if (s is TextSpan && s.text != null) trozos.add(s);
        return true;
      });
      expect(trozos.any((s) => s.text == 'negrita' && s.style?.fontWeight == FontWeight.w800), isTrue);
      expect(trozos.map((s) => s.text).join(), contains('<b>no</b>'));
    });
  });

  test('una nota se abre desde un aviso o una búsqueda', () {
    expect(resolverDestino(const Destino('nota', 7)), isA<AbrirNota>().having((a) => a.id, 'id', 7));
    expect(resolverDestino(const Destino('nota')), isA<AbrirPantalla>().having((a) => a.clave, 'clave', 'notas'));
  });

  group('lista de notas', () {
    _RepoFalso repo() => _RepoFalso()
      ..notas = [
        _nota(1, titulo: 'Reunión del lunes', texto: 'Llevar **el informe** y las cuentas', fijada: true, proyecto: 'Acme', participantes: 2, adjuntos: 1),
        _nota(2, texto: 'Primera línea\nsegunda línea de la nota'),
        _nota(3, titulo: 'De Ana', texto: 'Para ti', rol: 'colabora', dueno: 'Ana Pla'),
      ]
      ..proy = [Proyecto.fromJson({'id': 5, 'nombre': 'Acme'})];

    testWidgets('en una tableta el asistente va en un panel junto a la lista; se cierra y la chispa lo reabre', (t) async {
      t.view.physicalSize = const Size(1400, 800);
      t.view.devicePixelRatio = 1;
      addTearDown(t.view.reset);
      await t.pumpWidget(_app(const NotasScreen(), [..._over(repo()), serviciosProvider.overrideWithValue(aux.serviciosFalsos())]));
      await t.pumpAndSettle();
      expect(find.byType(IaChatScreen), findsOneWidget);
      expect(find.text('Contexto: Notas'), findsOneWidget);
      expect(find.text('Reunión del lunes'), findsOneWidget);
      await t.tap(find.byTooltip('Ocultar el asistente'));
      await t.pumpAndSettle();
      expect(find.byType(IaChatScreen), findsNothing);
      await t.tap(find.byTooltip('Preguntar al asistente'));
      await t.pumpAndSettle();
      expect(find.byType(IaChatScreen), findsOneWidget);
    });

    testWidgets('en una tableta la nota se abre al lado de la lista, sin empujar otra pantalla', (t) async {
      t.view.physicalSize = const Size(1000, 800);
      t.view.devicePixelRatio = 1;
      addTearDown(t.view.reset);
      await t.pumpWidget(_app(const NotasScreen(), _over(repo())));
      await t.pumpAndSettle();
      expect(find.text('Elige una nota para verla.'), findsOneWidget);
      await t.tap(find.text('Reunión del lunes'));
      await t.pumpAndSettle();
      expect(find.text('Elige una nota para verla.'), findsNothing);
      expect(find.byType(NotaScreen), findsOneWidget);
      expect(find.text('Reunión del lunes'), findsWidgets); // la lista sigue a la vista
      expect(t.takeException(), isNull);
    });

    testWidgets('captura tableta_notas', (t) async {
      if (aux.carpetaCapturas == null) return;
      await aux.cargarFuentesParaCapturas();
      final clave = GlobalKey();
      t.view.physicalSize = const Size(1640, 1180);
      t.view.devicePixelRatio = 1;
      addTearDown(t.view.reset);
      await t.pumpWidget(RepaintBoundary(key: clave, child: _app(const NotasScreen(), [..._over(repo()), serviciosProvider.overrideWithValue(aux.serviciosFalsos())])));
      await t.pumpAndSettle();
      await t.tap(find.text('Reunión del lunes'));
      await t.pumpAndSettle();
      await aux.capturar(t, clave, 'tableta_notas');
    });

    testWidgets('en el móvil no hay panel: la chispa abre el chat aparte', (t) async {
      await t.pumpWidget(_app(const NotasScreen(), _over(repo())));
      await t.pumpAndSettle();
      expect(find.byType(IaChatScreen), findsNothing);
      expect(find.byTooltip('Preguntar al asistente'), findsOneWidget);
    });

    testWidgets('enseña título, principio sin marcas y lo que la distingue', (t) async {
      await t.pumpWidget(_app(const NotasScreen(), _over(repo())));
      await t.pumpAndSettle();
      expect(find.text('Reunión del lunes'), findsOneWidget);
      expect(find.text('Llevar el informe y las cuentas'), findsOneWidget); // sin los asteriscos
      expect(find.text('Fijada'), findsOneWidget);
      expect(find.text('Compartida'), findsOneWidget);
      expect(find.text('De Ana Pla'), findsOneWidget);
      // sin título, la primera línea hace de título y el resto de principio
      expect(find.text('Primera línea'), findsOneWidget);
      expect(find.text('segunda línea de la nota'), findsOneWidget);
    });

    testWidgets('sin notas, un estado vacío que invita a escribir la primera', (t) async {
      await t.pumpWidget(_app(const NotasScreen(), _over(_RepoFalso())));
      await t.pumpAndSettle();
      expect(find.text('Todavía no tienes notas.'), findsOneWidget);
      expect(find.text('Nueva nota'), findsOneWidget);
    });

    testWidgets('el ámbito y el proyecto vuelven a pedir la lista con ese filtro', (t) async {
      final r = repo();
      await t.pumpWidget(_app(const NotasScreen(), _over(r)));
      await t.pumpAndSettle();
      await t.tap(find.text('Todas'));
      await t.pumpAndSettle();
      await t.tap(find.text('Compartidas conmigo').last);
      await t.pumpAndSettle();
      await t.tap(find.text('Todos los proyectos'));
      await t.pumpAndSettle();
      await t.tap(find.text('Acme').last);
      await t.pumpAndSettle();
      expect(r.registro.last, 'listar:compartidas::5:0');
    });

    testWidgets('buscar manda el texto al servidor', (t) async {
      final r = repo();
      await t.pumpWidget(_app(const NotasScreen(), _over(r)));
      await t.pumpAndSettle();
      await t.tap(find.byTooltip('Buscar notas'));
      await t.pumpAndSettle();
      await t.enterText(find.byType(TextField), 'informe');
      await t.testTextInput.receiveAction(TextInputAction.search);
      await t.pumpAndSettle();
      expect(r.registro.last, 'listar:todas:informe::0');
    });

    testWidgets('deslizar borra a la papelera y «Deshacer» la recupera', (t) async {
      final r = repo();
      await t.pumpWidget(_app(const NotasScreen(), _over(r)));
      await t.pumpAndSettle();
      await t.drag(find.text('Reunión del lunes'), const Offset(-600, 0));
      await t.pumpAndSettle();
      expect(r.registro, contains('eliminar:1'));
      expect(find.text('Nota eliminada'), findsOneWidget);
      expect(find.text('Reunión del lunes'), findsNothing);
      await t.tap(find.text('Deshacer'));
      await t.pumpAndSettle();
      expect(r.registro, contains('restaurar:1'));
      expect(find.text('Nota recuperada'), findsOneWidget);
    });

    testWidgets('una nota compartida conmigo no se desliza ni se borra desde la lista', (t) async {
      final r = repo();
      await t.pumpWidget(_app(const NotasScreen(), _over(r)));
      await t.pumpAndSettle();
      await t.drag(find.text('De Ana'), const Offset(-600, 0));
      await t.pumpAndSettle();
      expect(r.registro.where((x) => x.startsWith('eliminar')), isEmpty);
      expect(find.text('De Ana'), findsOneWidget);
    });

    testWidgets('fijar desde el menú de la tarjeta', (t) async {
      final r = repo();
      await t.pumpWidget(_app(const NotasScreen(), _over(r)));
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.more_vert).at(1)); // la segunda: no fijada
      await t.pumpAndSettle();
      await t.tap(find.text('Fijar arriba'));
      await t.pumpAndSettle();
      expect(r.registro, contains('fijar:2:true'));
    });
  });

  group('una nota', () {
    _RepoFalso conNota(Nota n, {List<AdjuntoNota> adjuntos = const []}) => _RepoFalso()
      ..detalle = {n.id: n}
      ..adj = adjuntos;

    testWidgets('se lee con su formato, su proyecto y con quién está compartida', (t) async {
      final n = _nota(1, titulo: 'Plan', texto: 'Hola **mundo**\n- uno', proyecto: 'Acme', participantes: 1, gente: [
        {'usuario_id': 2, 'nombre': 'Ana Pla', 'rol': 'observa'}
      ]);
      await t.pumpWidget(_app(const NotaScreen(notaId: 1), _over(conNota(n))));
      await t.pumpAndSettle();
      expect(find.text('Plan'), findsOneWidget);
      expect(find.text('Acme'), findsOneWidget);
      expect(find.text('Ana Pla'), findsOneWidget);
      expect(find.text('Solo lectura'), findsOneWidget);
      expect(find.text('Hola mundo', findRichText: true), findsOneWidget);
      expect(find.byTooltip('Editar nota'), findsOneWidget);
    });

    testWidgets('quien solo observa la lee sin poder editarla y puede salirse', (t) async {
      final r = conNota(_nota(1, texto: 'Ajena', rol: 'observa', dueno: 'Ana Pla'));
      await t.pumpWidget(_app(const NotaScreen(notaId: 1), _over(r)));
      await t.pumpAndSettle();
      expect(find.text('Compartida por Ana Pla'), findsOneWidget);
      expect(find.byTooltip('Editar nota'), findsNothing);
      expect(find.text('Adjuntos'), findsNothing);
      await t.tap(find.text('Salir de la nota'));
      await t.pumpAndSettle();
      await t.tap(find.text('Salir de la nota').last);
      await t.pumpAndSettle();
      expect(r.registro.where((x) => x.startsWith('dejar')), ['dejar:1:1']);
    });

    testWidgets('un colaborador edita pero no fija ni borra', (t) async {
      final r = conNota(_nota(1, texto: 'Compartida', rol: 'colabora', dueno: 'Ana Pla'));
      await t.pumpWidget(_app(const NotaScreen(notaId: 1), _over(r)));
      await t.pumpAndSettle();
      expect(find.byTooltip('Editar nota'), findsOneWidget);
      expect(find.byType(PopupMenuButton<String>), findsNothing);
    });

    testWidgets('editar y guardar manda texto y título', (t) async {
      final r = conNota(_nota(1, titulo: 'Plan', texto: 'Antes'));
      await t.pumpWidget(_app(const NotaScreen(notaId: 1), _over(r)));
      await t.pumpAndSettle();
      await t.tap(find.byTooltip('Editar nota'));
      await t.pumpAndSettle();
      expect(find.widgetWithText(FilledButton, 'Guardar').evaluate().isNotEmpty, isTrue);
      await t.enterText(find.widgetWithText(TextField, 'Antes'), 'Después');
      await t.pump();
      await t.tap(find.text('Guardar'));
      await t.pumpAndSettle();
      expect(r.registro, contains('editar:1:Después:Plan'));
    });

    testWidgets('al cerrar con cambios sin guardar pregunta antes de descartarlos', (t) async {
      final r = conNota(_nota(1, texto: 'Antes'));
      await t.pumpWidget(_app(const NotaScreen(notaId: 1), _over(r)));
      await t.pumpAndSettle();
      await t.tap(find.byTooltip('Editar nota'));
      await t.pumpAndSettle();
      await t.enterText(find.widgetWithText(TextField, 'Antes'), 'Distinto');
      await t.pump();
      await t.tap(find.byTooltip('Cancelar'));
      await t.pumpAndSettle();
      expect(find.text('¿Descartar los cambios?'), findsOneWidget);
      await t.tap(find.text('Seguir editando'));
      await t.pumpAndSettle();
      expect(find.text('Guardar'), findsOneWidget); // sigue editando
      await t.tap(find.byTooltip('Cancelar'));
      await t.pumpAndSettle();
      await t.tap(find.text('Descartar'));
      await t.pumpAndSettle();
      expect(find.byTooltip('Editar nota'), findsOneWidget);
      expect(find.text('Antes', findRichText: true), findsOneWidget);
    });

    testWidgets('la barra de formato envuelve lo seleccionado y añade guiones a una lista', (t) async {
      final r = conNota(_nota(1, texto: 'importante'));
      await t.pumpWidget(_app(const NotaScreen(notaId: 1), _over(r)));
      await t.pumpAndSettle();
      await t.tap(find.byTooltip('Editar nota'));
      await t.pumpAndSettle();
      final campo = find.widgetWithText(TextField, 'importante');
      t.widget<TextField>(campo).controller!.selection = const TextSelection(baseOffset: 0, extentOffset: 10);
      await t.tap(find.byTooltip('Negrita'));
      await t.pump();
      expect(t.widget<TextField>(find.byType(TextField).last).controller!.text, '**importante**');
      await t.tap(find.byTooltip('Lista'));
      await t.pump();
      expect(t.widget<TextField>(find.byType(TextField).last).controller!.text, '- **importante**');
    });

    testWidgets('una nota nueva: guardar espera a que haya algo escrito y la crea', (t) async {
      final registro = <String>[];
      final r = _RepoFalso();
      await t.pumpWidget(_app(_desde(const NotaScreen()), _over(r, acciones: _AccionesFalsas(registro, resultado: _nota(9)))));
      await t.tap(find.text('abrir'));
      await t.pumpAndSettle();
      expect(t.widget<FilledButton>(find.widgetWithText(FilledButton, 'Guardar')).onPressed, isNull);
      await t.enterText(find.widgetWithText(TextField, 'Título (opcional)'), 'Ideas');
      await t.enterText(find.byType(TextField).last, 'Una **gran** idea');
      await t.pump();
      await t.tap(find.text('Guardar'));
      await t.pumpAndSettle();
      expect(registro, ['crear:Ideas:Una **gran** idea']);
      expect(find.text('Nota guardada'), findsOneWidget);
    });

    testWidgets('sin conexión la nueva queda en la cola y se avisa', (t) async {
      final registro = <String>[];
      await t.pumpWidget(_app(_desde(const NotaScreen()), _over(_RepoFalso(), acciones: _AccionesFalsas(registro))));
      await t.tap(find.text('abrir'));
      await t.pumpAndSettle();
      await t.enterText(find.byType(TextField).last, 'Apunte');
      await t.pump();
      await t.tap(find.text('Guardar'));
      await t.pumpAndSettle();
      expect(registro, ['crear::Apunte']);
      expect(find.text('Sin conexión: la nota se enviará al volver la red.'), findsOneWidget);
    });

    testWidgets('el dueño comparte con un compañero eligiendo qué podrá hacer', (t) async {
      final r = conNota(_nota(1, texto: 'Mía'));
      await t.pumpWidget(_app(const NotaScreen(notaId: 1), _over(r, companeros: [Companero.fromJson({'id': 1, 'nombre': 'Yo'}), Companero.fromJson({'id': 4, 'nombre': 'Luis Mir'})])));
      await t.pumpAndSettle();
      await t.ensureVisible(find.text('Compartir con…'));
      await t.tap(find.text('Compartir con…'));
      await t.pumpAndSettle();
      expect(find.text('Yo'), findsNothing); // no se ofrece a sí mismo
      await t.tap(find.text('Luis Mir'));
      await t.pumpAndSettle();
      await t.tap(find.text('Puede editar'));
      await t.pumpAndSettle();
      expect(r.registro, contains('compartir:1:4:colabora'));
    });

    testWidgets('borrar desde la nota la manda a la papelera', (t) async {
      final r = conNota(_nota(1, texto: 'Adiós'));
      await t.pumpWidget(_app(const NotaScreen(notaId: 1), _over(r)));
      await t.pumpAndSettle();
      await t.tap(find.byType(PopupMenuButton<String>));
      await t.pumpAndSettle();
      await t.tap(find.text('Eliminar nota'));
      await t.pumpAndSettle();
      expect(r.registro, contains('eliminar:1'));
    });
  });

  group('accesibilidad', () {
    for (final oscuro in [false, true]) {
      testWidgets('la lista de notas cumple las pautas (${oscuro ? 'oscuro' : 'claro'})', (t) async {
        final h = t.ensureSemantics();
        final r = _RepoFalso()..notas = [_nota(1, titulo: 'Reunión', texto: 'Cuerpo', fijada: true, proyecto: 'Acme'), _nota(2, texto: 'Otra')];
        await t.pumpWidget(_app(const NotasScreen(), _over(r), oscuro: oscuro));
        await t.pumpAndSettle();
        await expectLater(t, meetsGuideline(androidTapTargetGuideline));
        await expectLater(t, meetsGuideline(labeledTapTargetGuideline));
        await expectLater(t, meetsGuideline(textContrastGuideline));
        h.dispose();
      });
    }
  });

  // Capturas con el tema y las fuentes reales: solo con CAPTURAS=<carpeta>.
  group('capturas del diseño', () {
    setUpAll(aux.cargarFuentesParaCapturas);
    for (final oscuro in [false, true]) {
      final sufijo = oscuro ? 'oscuro' : 'claro';
      testWidgets('captura notas $sufijo', (t) async {
        if (aux.carpetaCapturas == null) return;
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 2532);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        final r = _RepoFalso()
          ..notas = [
            _nota(1, titulo: 'Reunión del lunes con Acme', texto: 'Llevar **el informe** del trimestre y las cuentas', fijada: true, proyecto: 'Acme', participantes: 2, adjuntos: 1),
            _nota(2, texto: 'Llamar a la gestoría\nconfirmar el plazo del modelo 303'),
            _nota(3, titulo: 'Criterios de contabilización', texto: 'Para ti, de parte de Ana', rol: 'colabora', dueno: 'Ana Pla'),
            _nota(4, texto: 'Pedir presupuesto del seguro\n- oficina\n- coche', proyecto: 'Administración'),
          ]
          ..proy = [Proyecto.fromJson({'id': 5, 'nombre': 'Acme'})];
        await t.pumpWidget(aux.appDePantalla(const NotasScreen(), _over(r), oscuro: oscuro, clave: clave));
        await t.pumpAndSettle();
        await aux.capturar(t, clave, 'notas_$sufijo');
      });
      testWidgets('captura nota $sufijo', (t) async {
        if (aux.carpetaCapturas == null) return;
        final clave = GlobalKey();
        t.view.physicalSize = const Size(1170, 2532);
        t.view.devicePixelRatio = 3;
        addTearDown(t.view.reset);
        final n = _nota(1, titulo: 'Reunión del lunes con Acme', texto: 'Llevar **el informe** del trimestre y las cuentas.\n\nPuntos:\n- cuadrar el IVA\n- revisar la *tesorería*\n- ver [el portal](https://app.guildawork.com)', proyecto: 'Acme', participantes: 1, gente: [
          {'usuario_id': 2, 'nombre': 'Ana Pla', 'rol': 'colabora'}
        ]);
        final r = _RepoFalso()
          ..detalle = {1: n}
          ..adj = [AdjuntoNota.fromJson({'id': 1, 'nombre': 'cuentas-t3.pdf', 'tamano': 245760})];
        await t.pumpWidget(aux.appDePantalla(const NotaScreen(notaId: 1), _over(r), oscuro: oscuro, clave: clave));
        await t.pumpAndSettle();
        await aux.capturar(t, clave, 'nota_$sufijo');
      });
    }
  });
}
