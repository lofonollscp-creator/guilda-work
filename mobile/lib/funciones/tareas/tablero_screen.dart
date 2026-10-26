import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/generado/modelos.g.dart';
import '../../datos/cola.dart';
import '../../diseno/componentes.dart';
import '../../diseno/formatos.dart';
import '../../dominio/tarea.dart';
import '../../l10n/app_localizations.dart';
import '../../nucleo/lectura_guardada.dart';
import '../../nucleo/sesion.dart';
import '../pendientes/pendientes_sheet.dart';
import 'cambio_estado.dart';
import 'tarea_detalle_screen.dart';
import 'tareas_repositorio.dart';
import 'tareas_vistas.dart';
import 'textos.dart';

/// El tablero: las tareas por estado (`GET /tareas-outlook/tablero`), una columna por estado como en la web y las completadas más recientes (15).
class TableroControlador extends AsyncNotifier<Map<String, List<TareaOutlook>>> {
  @override
  Future<Map<String, List<TareaOutlook>>> build() {
    ref.watch(estadoSesionProvider.select((e) => e.despacho));
    ref.listen(colaEnviadaProvider, (_, _) => refrescar());
    return ref.read(tareasRepositorioProvider).tablero();
  }

  Future<void> refrescar() async {
    final anterior = state.value;
    try {
      state = AsyncData(await ref.read(tareasRepositorioProvider).tablero());
    } catch (e, st) {
      if (anterior == null) state = AsyncError(e, st);
    }
  }

  /// La tarjeta pasa a la columna de su estado nuevo (la primera, como en el servidor para lo recién cambiado).
  void reemplazar(TareaOutlook nueva) {
    final actual = state.value;
    if (actual == null) return;
    final destino = EstadoTarea.desde(nueva.estado).valor;
    state = AsyncData({
      for (final e in actual.entries) e.key: [if (e.key == destino) nueva, for (final t in e.value) if (t.id != nueva.id) t],
    });
  }
}

final tableroProvider = AsyncNotifierProvider<TableroControlador, Map<String, List<TareaOutlook>>>(TableroControlador.new);

class TableroScreen extends ConsumerWidget {
  static const limiteColumna = 25; // como la web: 25 tarjetas por columna y «Mostrar más»
  const TableroScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final tablero = ref.watch(tableroProvider);
    final c = ref.read(tableroProvider.notifier);
    return Scaffold(
      appBar: AppBar(title: Text(t.tareasTitulo)),
      body: Column(children: [
        const AvisoDatosGuardados(prefijo: '/tareas-outlook'),
        const AvisoPendientes(),
        const SubnavTareas(),
        Expanded(
          child: tablero.when(
            loading: () => const EsqueletoLista(),
            error: (e, _) => EstadoError(error: e, alReintentar: c.refrescar),
            data: (columnas) => DefaultTabController(
              length: columnasTablero.length,
              child: Column(children: [
                TabBar(
                  isScrollable: true,
                  tabAlignment: TabAlignment.start,
                  tabs: [for (final e in columnasTablero) Tab(text: '${etiquetaEstado(t, e)} (${(columnas[e.valor] ?? const []).length})')],
                ),
                Expanded(
                  child: TabBarView(children: [for (final e in columnasTablero) _Columna(estado: e, tareas: columnas[e.valor] ?? const [])]),
                ),
              ]),
            ),
          ),
        ),
      ]),
    );
  }
}

class _Columna extends ConsumerStatefulWidget {
  final EstadoTarea estado;
  final List<TareaOutlook> tareas;
  const _Columna({required this.estado, required this.tareas});

  @override
  ConsumerState<_Columna> createState() => _ColumnaState();
}

class _ColumnaState extends ConsumerState<_Columna> {
  bool _todas = false;

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final c = ref.read(tableroProvider.notifier);
    final visibles = _todas ? widget.tareas : widget.tareas.take(TableroScreen.limiteColumna).toList();
    return RefreshIndicator(
      onRefresh: c.refrescar,
      child: widget.tareas.isEmpty
          ? ListView(physics: const AlwaysScrollableScrollPhysics(), children: [
              Padding(padding: const EdgeInsets.all(32), child: Center(child: Text(t.tableroNadaAqui, style: Theme.of(context).textTheme.bodyMedium))),
            ])
          : ListView(padding: const EdgeInsets.fromLTRB(12, 8, 12, 24), children: [
              for (final tarea in visibles) _Tarjeta(key: ValueKey('${widget.estado.valor}_${tarea.id}'), tarea: tarea),
              if (widget.tareas.length > visibles.length) TextButton(onPressed: () => setState(() => _todas = true), child: Text(t.tableroMostrarMas)),
            ]),
    );
  }
}

class _Tarjeta extends ConsumerWidget {
  final TareaOutlook tarea;
  const _Tarjeta({super.key, required this.tarea});

  Future<void> _mover(BuildContext context, WidgetRef ref, EstadoTarea nuevo) async {
    final t = AppLocalizations.of(context);
    String? motivo;
    if (nuevo.pideMotivo) {
      final c = TextEditingController();
      motivo = await showDialog<String>(
        context: context,
        builder: (d) => AlertDialog(
          title: Text(t.tareaMotivoPregunta),
          content: TextField(controller: c, autofocus: true, decoration: InputDecoration(hintText: t.tareaMotivoHint)),
          actions: [
            TextButton(onPressed: () => Navigator.pop(d), child: Text(t.comunCancelar)),
            FilledButton(onPressed: () => Navigator.pop(d, c.text.trim()), child: Text(t.tareaAceptar)),
          ],
        ),
      );
      if (motivo == null || motivo.isEmpty) return;
    }
    if (!context.mounted) return;
    await cambiarEstadoConAviso(context, ref, tarea, nuevo, alCambiar: ref.read(tableroProvider.notifier).reemplazar, motivo: motivo);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final actual = EstadoTarea.desde(tarea.estado);
    final fecha = context.formatos.deServidor(tarea.fechaVencimiento);
    final hechas = tarea.checklistHechas ?? 0;
    final total = tarea.checklistTotal ?? 0;
    final prioridad = PrioridadTarea.desde(tarea.prioridad);
    final persona = tarea.rol == 'asignada' ? tarea.creadorNombre : tarea.asignadaNombre;
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: InkWell(
        onTap: tarea.id < 0 ? null : () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => TareaDetalleScreen(tareaId: tarea.id))),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 10, 4, 10),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(tarea.asunto ?? '', style: tema.textTheme.titleSmall, maxLines: 3, overflow: TextOverflow.ellipsis),
                if (total > 0) ...[
                  const SizedBox(height: 6),
                  LinearProgressIndicator(value: hechas / total, minHeight: 4),
                  const SizedBox(height: 2),
                  Text(t.tableroPasos(hechas, total), style: tema.textTheme.labelSmall),
                ],
                const SizedBox(height: 6),
                Wrap(spacing: 10, runSpacing: 2, crossAxisAlignment: WrapCrossAlignment.center, children: [
                  if (prioridad != PrioridadTarea.normal)
                    Text(etiquetaPrioridad(t, prioridad), style: tema.textTheme.labelMedium?.copyWith(fontWeight: prioridad == PrioridadTarea.alta ? FontWeight.w700 : null)),
                  if ((tarea.categoriaNombre ?? '').isNotEmpty) Text(tarea.categoriaNombre!, style: tema.textTheme.labelMedium),
                  if (fecha != null) Text(fecha, style: tema.textTheme.labelMedium?.copyWith(color: tarea.vencida == true ? tema.colorScheme.error : null)),
                  if ((persona ?? '').isNotEmpty)
                    Row(mainAxisSize: MainAxisSize.min, children: [const Icon(Icons.person_outline, size: 14), const SizedBox(width: 2), Text(persona!, style: tema.textTheme.labelMedium)]),
                ]),
              ]),
            ),
            if (tarea.id > 0 && tarea.rol != 'compartida')
              PopupMenuButton<EstadoTarea>(
                tooltip: t.tableroMoverA,
                icon: const Icon(Icons.more_vert),
                onSelected: (e) => _mover(context, ref, e),
                itemBuilder: (_) => [
                  PopupMenuItem(enabled: false, child: Text(t.tableroMoverA, style: tema.textTheme.labelMedium)),
                  // En revisión solo se entra y se sale por el flujo de revisión (como en la web): no se ofrece como destino.
                  for (final e in columnasTablero)
                    if (e != EstadoTarea.enRevision && e != actual) PopupMenuItem(value: e, child: Text(etiquetaEstado(t, e))),
                ],
              ),
          ]),
        ),
      ),
    );
  }
}
