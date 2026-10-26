import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errores.dart';
import '../../api/fechas.dart';
import '../../diseno/componentes.dart';
import '../../diseno/formatos.dart';
import '../../api/generado/modelos.g.dart';
import '../../datos/local/cola_escritura.dart' show ColaLlena;
import '../../dominio/tarea.dart';
import '../../l10n/app_localizations.dart';
import '../../nucleo/lectura_guardada.dart';
import '../pendientes/pendientes_sheet.dart';
import 'fila_tarea.dart';
import 'tareas_lista_controlador.dart';
import 'tareas_repositorio.dart';
import 'tareas_vistas.dart';
import 'textos.dart';

/// La lista de tareas: ámbitos (mías, asignadas, compartidas, todas), estado, búsqueda,
/// paginación infinita y alta rápida con un campo al pie.
class TareasScreen extends ConsumerStatefulWidget {
  const TareasScreen({super.key});

  @override
  ConsumerState<TareasScreen> createState() => _TareasScreenState();
}

class _TareasScreenState extends ConsumerState<TareasScreen> {
  final _scroll = ScrollController();
  final _nueva = TextEditingController();
  final _buscar = TextEditingController();
  bool _buscando = false;
  Fecha? _fecha;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels > _scroll.position.maxScrollExtent - 300) ref.read(tareasListaProvider.notifier).masResultados();
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    _nueva.dispose();
    _buscar.dispose();
    super.dispose();
  }

  Future<void> _crear() async {
    final t = AppLocalizations.of(context);
    final texto = _nueva.text.trim();
    if (texto.isEmpty) return;
    final mensajero = ScaffoldMessenger.of(context);
    try {
      final encolada = await ref.read(tareasListaProvider.notifier).crear(texto, fechaVencimiento: _fecha?.toJson());
      _nueva.clear();
      setState(() => _fecha = null);
      if (encolada) mensajero.showSnackBar(SnackBar(content: Text(t.colaGuardada)));
    } on ColaLlena {
      mensajero.showSnackBar(SnackBar(content: Text(t.colaLlena)));
    } on ApiException catch (e) {
      mensajero.showSnackBar(SnackBar(content: Text(e.esDeConexion ? t.tareasNoSePudoCrear : e.mensaje)));
    }
  }

  Future<void> _elegirFecha() async {
    final t = AppLocalizations.of(context);
    final ahora = DateTime.now();
    final elegida = await showDatePicker(
      context: context,
      helpText: t.tareasFecha,
      initialDate: ahora,
      firstDate: DateTime(ahora.year - 1),
      lastDate: DateTime(ahora.year + 5),
    );
    if (elegida != null) setState(() => _fecha = Fecha(elegida.year, elegida.month, elegida.day));
  }

  Future<void> _completar(TareaOutlook tarea) async {
    final t = AppLocalizations.of(context);
    final mensajero = ScaffoldMessenger.of(context);
    try {
      final encolada = await ref.read(tareasListaProvider.notifier).completar(tarea);
      mensajero.hideCurrentSnackBar();
      mensajero.showSnackBar(SnackBar(
        content: Text(encolada ? t.colaGuardada : t.tareaCompletadaAviso),
        duration: const Duration(seconds: 6),
        action: SnackBarAction(label: t.comunDeshacer, onPressed: () => _deshacer(tarea, encolada)),
      ));
    } on ColaLlena {
      mensajero.showSnackBar(SnackBar(content: Text(t.colaLlena)));
    } on ApiException catch (e) {
      mensajero.showSnackBar(SnackBar(content: Text(e.mensaje)));
    }
  }

  PreferredSizeWidget _barraSeleccion(AppLocalizations t, Set<int> seleccion) {
    final c = ref.read(tareasListaProvider.notifier);
    return AppBar(
      leading: IconButton(icon: const Icon(Icons.close), tooltip: t.comunCancelar, onPressed: c.limpiarSeleccion),
      title: Text(t.tareasSeleccionadas(seleccion.length)),
      actions: [
        IconButton(icon: const Icon(Icons.select_all), tooltip: t.tareasMarcarTodas, onPressed: c.seleccionarTodas),
        IconButton(icon: const Icon(Icons.done_all), tooltip: t.tareasLoteCompletar, onPressed: () => _lote('completar')),
        PopupMenuButton<String>(
          onSelected: (v) => switch (v) {
            'estado' => _loteEstado(),
            'prioridad' => _lotePrioridad(),
            'fecha' => _loteFecha(),
            _ => _eliminarSeleccion(),
          },
          itemBuilder: (_) => [
            PopupMenuItem(value: 'estado', child: Text(t.tareasLoteEstado)),
            PopupMenuItem(value: 'prioridad', child: Text(t.tareasLotePrioridad)),
            PopupMenuItem(value: 'fecha', child: Text(t.tareasLoteVencimiento)),
            PopupMenuItem(value: 'eliminar', child: Text(t.tareasLoteEliminar)),
          ],
        ),
      ],
    );
  }

  Future<void> _lote(String accion, {String? valor}) async {
    final t = AppLocalizations.of(context);
    final mensajero = ScaffoldMessenger.of(context);
    try {
      final r = await ref.read(tareasListaProvider.notifier).accionLote(accion, valor: valor);
      mensajero.hideCurrentSnackBar();
      mensajero.showSnackBar(SnackBar(content: Text(r.fallos == 0 ? t.tareasLoteExito(r.ok) : t.tareasLoteResultado(r.ok, r.fallos))));
    } on ApiException catch (e) {
      mensajero.showSnackBar(SnackBar(content: Text(e.mensaje)));
    }
  }

  Future<T?> _elegir<T>(List<(T, String)> opciones) => showModalBottomSheet<T>(
        context: context,
        builder: (_) => SafeArea(
          child: Column(mainAxisSize: MainAxisSize.min, children: [for (final (valor, etiqueta) in opciones) ListTile(title: Text(etiqueta), onTap: () => Navigator.pop(context, valor))]),
        ),
      );

  Future<void> _loteEstado() async {
    final t = AppLocalizations.of(context);
    // «Esperando» pide un motivo: se cambia desde la ficha de cada tarea.
    final e = await _elegir<EstadoTarea>([for (final e in EstadoTarea.elegibles) if (!e.pideMotivo) (e, etiquetaEstado(t, e))]);
    if (e != null) await _lote('estado', valor: e.valor);
  }

  Future<void> _lotePrioridad() async {
    final t = AppLocalizations.of(context);
    final p = await _elegir<PrioridadTarea>([for (final p in PrioridadTarea.values) (p, etiquetaPrioridad(t, p))]);
    if (p != null) await _lote('prioridad', valor: p.valor);
  }

  Future<void> _loteFecha() async {
    final t = AppLocalizations.of(context);
    final ahora = DateTime.now();
    final f = await showDatePicker(context: context, helpText: t.tareasLoteVencimiento, initialDate: ahora, firstDate: DateTime(ahora.year - 1), lastDate: DateTime(ahora.year + 5));
    if (f != null) await _lote('fecha', valor: Fecha(f.year, f.month, f.day).toJson());
  }

  Future<void> _eliminarSeleccion() async {
    final t = AppLocalizations.of(context);
    final mensajero = ScaffoldMessenger.of(context);
    final c = ref.read(tareasListaProvider.notifier);
    final pedidas = ref.read(tareasListaProvider).seleccion.toList();
    final hechas = await c.eliminar(pedidas);
    mensajero.hideCurrentSnackBar();
    if (hechas.isEmpty) {
      mensajero.showSnackBar(SnackBar(content: Text(t.tareasNoSePudoEliminar)));
      return;
    }
    mensajero.showSnackBar(SnackBar(
      content: Text(hechas.length < pedidas.length ? '${t.tareasEliminadas(hechas.length)} · ${t.tareasNoSePudoEliminar}' : t.tareasEliminadas(hechas.length)),
      duration: const Duration(seconds: 6),
      action: SnackBarAction(
        label: t.comunDeshacer,
        onPressed: () async {
          try {
            await c.restaurar(hechas);
            mensajero.hideCurrentSnackBar();
            mensajero.showSnackBar(SnackBar(content: Text(t.tareaDeshechaAviso)));
          } on ApiException catch (e) {
            mensajero.showSnackBar(SnackBar(content: Text(e.mensaje)));
          }
        },
      ),
    ));
  }

  Future<void> _deshacer(TareaOutlook antes, bool encolada) async {
    final mensajero = ScaffoldMessenger.of(context);
    final t = AppLocalizations.of(context);
    try {
      await ref.read(tareasListaProvider.notifier).deshacerEstado(antes, encolada: encolada);
      mensajero.hideCurrentSnackBar();
      mensajero.showSnackBar(SnackBar(content: Text(t.tareaDeshechaAviso)));
    } on ColaLlena {
      mensajero.showSnackBar(SnackBar(content: Text(t.colaLlena)));
    } on ApiException catch (e) {
      mensajero.showSnackBar(SnackBar(content: Text(e.categoria == CategoriaError.conflicto ? t.tareaNoSePudoDeshacer : e.mensaje)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final estado = ref.watch(tareasListaProvider);
    final controlador = ref.read(tareasListaProvider.notifier);

    final seleccion = estado.seleccion;
    return Scaffold(
      appBar: seleccion.isNotEmpty ? _barraSeleccion(t, seleccion) : AppBar(
        title: _buscando
            ? TextField(
                controller: _buscar,
                autofocus: true,
                decoration: InputDecoration(hintText: t.tareasBuscar, border: InputBorder.none),
                textInputAction: TextInputAction.search,
                onSubmitted: controlador.buscar,
              )
            : Text(t.tareasTitulo),
        actions: [
          IconButton(
            icon: Icon(_buscando ? Icons.close : Icons.search),
            tooltip: t.tareasBuscar,
            onPressed: () {
              if (_buscando) {
                _buscar.clear();
                controlador.buscar('');
              }
              setState(() => _buscando = !_buscando);
            },
          ),
        ],
      ),
      body: Column(children: [
        const AvisoDatosGuardados(prefijo: '/tareas-outlook'),
        const AvisoPendientes(),
        const SubnavTareas(),
        _Filtros(estado: estado),
        Expanded(child: _Cuerpo(estado: estado, scroll: _scroll, alCompletar: _completar)),
        _AltaRapida(controlador: _nueva, fecha: _fecha, alElegirFecha: _elegirFecha, alQuitarFecha: () => setState(() => _fecha = null), alEnviar: _crear),
      ]),
    );
  }
}

/// Una sola fila de filtros: ámbito y estado como menús desplegables en forma de píldora, y los botones de filtros y vistas. (Antes eran tres filas de controles.)
class _Filtros extends ConsumerWidget {
  final EstadoListaTareas estado;
  const _Filtros({required this.estado});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final c = ref.read(tareasListaProvider.notifier);
    final ambitos = {'propias': t.tareasAmbitoPropias, 'asignadas': t.tareasAmbitoAsignadas, 'compartidas': t.tareasAmbitoCompartidas, 'todas': t.tareasAmbitoTodas};
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
      child: Row(children: [
        PildoraMenu<String>(
          icono: Icons.person_outline,
          texto: ambitos[estado.ambito] ?? '',
          activo: estado.ambito != 'propias',
          opciones: [for (final e in ambitos.entries) (e.key, e.value)],
          seleccionado: estado.ambito,
          alElegir: c.cambiarAmbito,
        ),
        const SizedBox(width: 8),
        PildoraMenu<EstadoTarea?>(
          icono: Icons.flag_circle_outlined,
          texto: estado.estado == null ? t.tareaEstado : etiquetaEstado(t, estado.estado!),
          activo: estado.estado != null,
          opciones: [(null, t.tareasFiltroTodas), for (final e in EstadoTarea.elegibles) (e, etiquetaEstado(t, e))],
          seleccionado: estado.estado,
          alElegir: c.cambiarEstado,
        ),
        const SizedBox(width: 8),
        PildoraBoton(
          icono: Icons.tune,
          texto: estado.filtrosActivos == 0 ? t.tareasFiltros : t.tareasFiltrosActivos(estado.filtrosActivos),
          activo: estado.filtrosActivos > 0,
          alPulsar: () => showModalBottomSheet<void>(context: context, isScrollControlled: true, showDragHandle: true, builder: (_) => const _HojaFiltros()),
        ),
        const SizedBox(width: 8),
        PildoraBoton(
          icono: Icons.bookmarks_outlined,
          texto: t.tareasVistas,
          alPulsar: () => showModalBottomSheet<void>(context: context, isScrollControlled: true, showDragHandle: true, builder: (_) => const _HojaVistas()),
        ),
      ]),
    );
  }
}

class _Cuerpo extends ConsumerWidget {
  final EstadoListaTareas estado;
  final ScrollController scroll;
  final Future<void> Function(TareaOutlook) alCompletar;
  const _Cuerpo({required this.estado, required this.scroll, required this.alCompletar});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final c = ref.read(tareasListaProvider.notifier);
    if (estado.tareas.isEmpty) {
      if (estado.cargando) return const EsqueletoLista();
      return RefreshIndicator(
        onRefresh: c.recargar,
        child: ListView(controller: scroll, physics: const AlwaysScrollableScrollPhysics(), children: [
          SizedBox(
            height: 360,
            child: estado.error != null
                ? EstadoError(error: estado.error!, alReintentar: c.recargar)
                : EstadoVacio(
                    icono: estado.busqueda.isEmpty ? Icons.task_alt : Icons.search_off,
                    titulo: estado.busqueda.isEmpty ? t.tareasVacio : t.tareasSinResultados,
                  ),
          ),
        ]),
      );
    }
    return RefreshIndicator(
      onRefresh: c.recargar,
      child: ListView.builder(
        controller: scroll,
        padding: const EdgeInsets.only(bottom: 24),
        itemCount: estado.tareas.length + (estado.cargando ? 1 : 0),
        itemBuilder: (context, i) {
          if (i >= estado.tareas.length) return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
          final tarea = estado.tareas[i];
          return FilaTarea(
            tarea: tarea,
            alCompletar: alCompletar,
            pendiente: estado.pendientes.contains(tarea.id),
            seleccionada: estado.seleccion.contains(tarea.id),
            enSeleccion: estado.seleccion.isNotEmpty,
            alSeleccionar: () => c.alternarSeleccion(tarea.id),
          );
        },
      ),
    );
  }
}

class _AltaRapida extends StatelessWidget {
  final TextEditingController controlador;
  final Fecha? fecha;
  final VoidCallback alElegirFecha;
  final VoidCallback alQuitarFecha;
  final VoidCallback alEnviar;
  const _AltaRapida({required this.controlador, required this.fecha, required this.alElegirFecha, required this.alQuitarFecha, required this.alEnviar});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    return Container(
      decoration: BoxDecoration(color: tema.colorScheme.surface, border: Border(top: BorderSide(color: tema.colorScheme.outlineVariant))),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
          child: Row(children: [
            Expanded(
              child: TextField(
                controller: controlador,
                textInputAction: TextInputAction.send,
                textCapitalization: TextCapitalization.sentences,
                decoration: InputDecoration(
                  hintText: t.tareasNuevaHint,
                  isDense: true,
                  filled: true,
                  fillColor: tema.colorScheme.surfaceContainerHighest.withValues(alpha: 0.5),
                  contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(999), borderSide: BorderSide.none),
                  enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(999), borderSide: BorderSide.none),
                ),
                onSubmitted: (_) => alEnviar(),
              ),
            ),
            const SizedBox(width: 4),
            fecha == null
                ? IconButton(icon: const Icon(Icons.event_outlined), tooltip: t.tareasFecha, onPressed: alElegirFecha)
                : InputChip(label: Text(context.formatos.fecha(fecha!)), onPressed: alElegirFecha, onDeleted: alQuitarFecha),
            IconButton.filled(icon: const Icon(Icons.arrow_upward), tooltip: t.tareasNueva, onPressed: alEnviar),
          ]),
        ),
      ),
    );
  }
}

/// Filtros como los de la web: prioridad, categoría y «ver también completadas». «Guardar como vista» los guarda con nombre (también para la web).
class _HojaFiltros extends ConsumerStatefulWidget {
  const _HojaFiltros();

  @override
  ConsumerState<_HojaFiltros> createState() => _HojaFiltrosState();
}

class _HojaFiltrosState extends ConsumerState<_HojaFiltros> {
  late PrioridadTarea? _prioridad;
  late String? _categoria;
  late bool _completadas;

  @override
  void initState() {
    super.initState();
    final e = ref.read(tareasListaProvider);
    _prioridad = e.prioridad;
    _categoria = e.categoria;
    _completadas = e.completadas;
  }

  Future<void> _aplicar() => ref.read(tareasListaProvider.notifier).cambiarFiltros(
        prioridad: _prioridad,
        quitarPrioridad: _prioridad == null,
        categoria: _categoria,
        quitarCategoria: _categoria == null,
        completadas: _completadas,
      );

  Future<void> _guardarVista() async {
    final t = AppLocalizations.of(context);
    final mensajero = ScaffoldMessenger.of(context);
    final navegador = Navigator.of(context);
    final nombre = TextEditingController();
    final elegido = await showDialog<String>(
      context: context,
      builder: (d) => AlertDialog(
        title: Text(t.tareasGuardarVista),
        content: TextField(controller: nombre, autofocus: true, decoration: InputDecoration(labelText: t.tareasVistaNombre), maxLength: 60),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d), child: Text(t.comunCancelar)),
          FilledButton(onPressed: () => Navigator.pop(d, nombre.text.trim()), child: Text(t.tareaGuardar)),
        ],
      ),
    );
    if (elegido == null || elegido.isEmpty) return;
    await _aplicar();
    try {
      await ref.read(tareasRepositorioProvider).guardarVista(elegido, ref.read(tareasListaProvider).filtrosDeVista);
      ref.invalidate(vistasTareasProvider);
      mensajero.showSnackBar(SnackBar(content: Text(t.tareasVistaGuardada)));
      navegador.pop();
    } on ApiException catch (e) {
      mensajero.showSnackBar(SnackBar(content: Text(e.categoria == CategoriaError.validacion ? t.tareasVistaNoSePudo : e.mensaje)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final categorias = ref.watch(categoriasOutlookProvider).value ?? const <String>[];
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.fromLTRB(16, 0, 16, 16 + MediaQuery.of(context).viewInsets.bottom),
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(t.tareasFiltroPrioridad, style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 8),
            Wrap(spacing: 8, children: [
              ChoiceChip(label: Text(t.tareasFiltroCualquiera), selected: _prioridad == null, onSelected: (_) => setState(() => _prioridad = null)),
              for (final p in PrioridadTarea.values) ChoiceChip(label: Text(etiquetaPrioridad(t, p)), selected: _prioridad == p, onSelected: (_) => setState(() => _prioridad = p)),
            ]),
            if (categorias.isNotEmpty) ...[
              const SizedBox(height: 16),
              Text(t.tareasFiltroCategoria, style: Theme.of(context).textTheme.titleSmall),
              const SizedBox(height: 8),
              Wrap(spacing: 8, children: [
                ChoiceChip(label: Text(t.tareasFiltroCualquiera), selected: _categoria == null, onSelected: (_) => setState(() => _categoria = null)),
                for (final c in categorias) ChoiceChip(label: Text(c), selected: _categoria == c, onSelected: (_) => setState(() => _categoria = c)),
              ]),
            ],
            const SizedBox(height: 8),
            SwitchListTile(contentPadding: EdgeInsets.zero, title: Text(t.tareasMostrarCompletadas), value: _completadas, onChanged: (v) => setState(() => _completadas = v)),
            const SizedBox(height: 8),
            Row(children: [
              TextButton(
                onPressed: () => setState(() {
                  _prioridad = null;
                  _categoria = null;
                  _completadas = false;
                }),
                child: Text(t.tareasLimpiarFiltros),
              ),
              TextButton(onPressed: _guardarVista, child: Text(t.tareasGuardarVista)),
              const Spacer(),
              FilledButton(
                onPressed: () async {
                  final navegador = Navigator.of(context);
                  await _aplicar();
                  navegador.pop();
                },
                child: Text(t.tareasAplicar),
              ),
            ]),
          ]),
        ),
      ),
    );
  }
}

/// Las vistas guardadas (propias y compartidas por el despacho): tocar una pone sus filtros.
class _HojaVistas extends ConsumerWidget {
  const _HojaVistas();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final vistas = ref.watch(vistasTareasProvider);
    return SafeArea(
      child: vistas.when(
        loading: () => const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator())),
        error: (e, _) => Padding(padding: const EdgeInsets.all(16), child: Text(e is ApiException ? e.mensaje : '$e')),
        data: (lista) => lista.isEmpty
            ? Padding(padding: const EdgeInsets.fromLTRB(24, 8, 24, 32), child: Text(t.tareasVistasVacio))
            : ListView(shrinkWrap: true, children: [
                for (final v in lista)
                  ListTile(
                    leading: const Icon(Icons.bookmark_outline),
                    title: Text(v.nombre ?? ''),
                    subtitle: v.mia == true ? null : Text('${t.tareasVistaCompartida}${(v.autor ?? '').isEmpty ? '' : ' · ${v.autor}'}'),
                    trailing: v.mia == true && v.id != null
                        ? IconButton(
                            icon: const Icon(Icons.delete_outline),
                            tooltip: t.tareasLoteEliminar,
                            onPressed: () async {
                              await ref.read(tareasRepositorioProvider).eliminarVista(v.id!);
                              ref.invalidate(vistasTareasProvider);
                            },
                          )
                        : null,
                    onTap: () {
                      Navigator.pop(context);
                      ref.read(tareasListaProvider.notifier).aplicarVista(v.filtros ?? const {});
                    },
                  ),
              ]),
      ),
    );
  }
}
