import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errores.dart';
import '../../api/fechas.dart';
import '../../api/generado/modelos.g.dart';
import '../../datos/local/cola_escritura.dart' show ColaLlena;
import '../../dominio/tarea.dart';
import '../../l10n/app_localizations.dart';
import '../pendientes/pendientes_sheet.dart';
import 'tarea_detalle_screen.dart';
import 'tareas_lista_controlador.dart';
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
      if (await ref.read(tareasListaProvider.notifier).completar(tarea)) mensajero.showSnackBar(SnackBar(content: Text(t.colaGuardada)));
    } on ColaLlena {
      mensajero.showSnackBar(SnackBar(content: Text(t.colaLlena)));
    } on ApiException catch (e) {
      mensajero.showSnackBar(SnackBar(content: Text(e.mensaje)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final estado = ref.watch(tareasListaProvider);
    final controlador = ref.read(tareasListaProvider.notifier);

    return Scaffold(
      appBar: AppBar(
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
        const AvisoPendientes(),
        _Filtros(estado: estado),
        Expanded(child: _Cuerpo(estado: estado, scroll: _scroll, alCompletar: _completar)),
        _AltaRapida(controlador: _nueva, fecha: _fecha, alElegirFecha: _elegirFecha, alQuitarFecha: () => setState(() => _fecha = null), alEnviar: _crear),
      ]),
    );
  }
}

class _Filtros extends ConsumerWidget {
  final EstadoListaTareas estado;
  const _Filtros({required this.estado});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final c = ref.read(tareasListaProvider.notifier);
    final ambitos = [('propias', t.tareasAmbitoPropias), ('asignadas', t.tareasAmbitoAsignadas), ('compartidas', t.tareasAmbitoCompartidas), ('todas', t.tareasAmbitoTodas)];
    return Column(children: [
      SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        child: Row(children: [
          for (final (clave, etiqueta) in ambitos)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(label: Text(etiqueta), selected: estado.ambito == clave, onSelected: (_) => c.cambiarAmbito(clave)),
            ),
        ]),
      ),
      SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        child: Row(children: [
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: FilterChip(label: Text(t.tareasFiltroTodas), selected: estado.estado == null, onSelected: (_) => c.cambiarEstado(null)),
          ),
          for (final e in EstadoTarea.elegibles)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: FilterChip(label: Text(etiquetaEstado(t, e)), selected: estado.estado == e, onSelected: (_) => c.cambiarEstado(e)),
            ),
        ]),
      ),
    ]);
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
      return RefreshIndicator(
        onRefresh: c.recargar,
        child: ListView(controller: scroll, children: [
          const SizedBox(height: 120),
          Center(
            child: estado.cargando
                ? const CircularProgressIndicator()
                : estado.error != null
                    ? Column(children: [
                        Text(estado.error is ApiException ? (estado.error as ApiException).mensaje : t.hoyErrorCargar),
                        const SizedBox(height: 12),
                        FilledButton(onPressed: c.recargar, child: Text(t.arranqueReintentar)),
                      ])
                    : Text(estado.busqueda.isEmpty ? t.tareasVacio : t.tareasSinResultados),
          ),
        ]),
      );
    }
    return RefreshIndicator(
      onRefresh: c.recargar,
      child: ListView.builder(
        controller: scroll,
        itemCount: estado.tareas.length + (estado.cargando ? 1 : 0),
        itemBuilder: (context, i) {
          if (i >= estado.tareas.length) return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
          return _FilaTarea(tarea: estado.tareas[i], alCompletar: alCompletar, pendiente: estado.pendientes.contains(estado.tareas[i].id));
        },
      ),
    );
  }
}

class _FilaTarea extends StatelessWidget {
  final TareaOutlook tarea;
  final Future<void> Function(TareaOutlook) alCompletar;
  final bool pendiente; // hecha sin conexión, aún sin enviar
  const _FilaTarea({required this.tarea, required this.alCompletar, required this.pendiente});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final estado = EstadoTarea.desde(tarea.estado);
    final hecha = !estado.abierta;
    final vencida = tarea.vencida == true && !hecha;
    final fecha = Fecha.intentar(tarea.fechaVencimiento);
    final detalle = [
      if (fecha != null) formatoFechaCorta(fecha),
      if (estado != EstadoTarea.noIniciada && !hecha) etiquetaEstado(t, estado),
      if (PrioridadTarea.desde(tarea.prioridad) == PrioridadTarea.alta) etiquetaPrioridad(t, PrioridadTarea.alta),
    ].join(' · ');

    return ListTile(
      leading: Checkbox(
        value: hecha,
        onChanged: (hecha || tarea.id < 0) ? null : (_) => alCompletar(tarea),
        semanticLabel: t.hoyCompletar,
      ),
      title: Text(
        tarea.asunto ?? '',
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
        style: hecha ? TextStyle(decoration: TextDecoration.lineThrough, color: tema.colorScheme.outline) : null,
      ),
      subtitle: detalle.isEmpty && !vencida
          ? null
          : Text.rich(TextSpan(children: [
              if (vencida) TextSpan(text: '${t.tareasVencida} · ', style: TextStyle(color: tema.colorScheme.error, fontWeight: FontWeight.w600)),
              TextSpan(text: detalle),
            ])),
      trailing: pendiente
          ? Tooltip(message: t.colaTareaPendiente, child: const Icon(Icons.cloud_upload_outlined, size: 18))
          : ((tarea.motivoBloqueo ?? '').isNotEmpty ? const Icon(Icons.hourglass_empty, size: 18) : null),
      onTap: tarea.id < 0 ? null : () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => TareaDetalleScreen(tareaId: tarea.id))),
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
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 4, 4, 8),
        child: Row(children: [
          Expanded(
            child: TextField(
              controller: controlador,
              textInputAction: TextInputAction.send,
              decoration: InputDecoration(hintText: t.tareasNuevaHint, isDense: true, border: const OutlineInputBorder()),
              onSubmitted: (_) => alEnviar(),
            ),
          ),
          fecha == null
              ? IconButton(icon: const Icon(Icons.event_outlined), tooltip: t.tareasFecha, onPressed: alElegirFecha)
              : InputChip(label: Text(formatoFechaCorta(fecha!)), onPressed: alElegirFecha, onDeleted: alQuitarFecha),
          IconButton(icon: const Icon(Icons.send), tooltip: t.tareasNueva, onPressed: alEnviar),
        ]),
      ),
    );
  }
}
