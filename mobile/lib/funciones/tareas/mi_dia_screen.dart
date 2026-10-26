import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/generado/modelos.g.dart';
import '../../datos/cola.dart';
import '../../diseno/componentes.dart';
import '../../diseno/estados.dart';
import '../../dominio/tarea.dart';
import '../../l10n/app_localizations.dart';
import '../../nucleo/lectura_guardada.dart';
import '../../nucleo/sesion.dart';
import '../pendientes/pendientes_sheet.dart';
import 'cambio_estado.dart';
import 'fila_tarea.dart';
import 'tareas_repositorio.dart';
import 'tareas_vistas.dart';

/// «Mi día»: lo que hay que mirar hoy, en las mismas cinco secciones que la web (`GET /mi-dia`): vencidas, vencen hoy, en progreso, asignadas a mí y
/// compartidas conmigo. Se rehace al cambiar de despacho y cuando la cola sin conexión envía algo.
class MiDiaControlador extends AsyncNotifier<Map<String, List<TareaOutlook>>> {
  @override
  Future<Map<String, List<TareaOutlook>>> build() {
    ref.watch(estadoSesionProvider.select((e) => e.despacho));
    ref.listen(colaEnviadaProvider, (_, _) => refrescar());
    return ref.read(tareasRepositorioProvider).miDia();
  }

  Future<void> refrescar() async {
    final anterior = state.value;
    try {
      state = AsyncData(await ref.read(tareasRepositorioProvider).miDia());
    } catch (e, st) {
      if (anterior == null) state = AsyncError(e, st);
    }
  }

  /// Una tarea cambió de estado: si ya está completada sale de «Mi día»; si no, se actualiza donde está.
  void reemplazar(TareaOutlook nueva) {
    final actual = state.value;
    if (actual == null) return;
    final hecha = !EstadoTarea.desde(nueva.estado).abierta;
    state = AsyncData({
      for (final e in actual.entries)
        e.key: [
          for (final t in e.value)
            if (t.id != nueva.id) t else if (!hecha) nueva,
        ],
    });
    if (!hecha) return;
  }
}

final miDiaProvider = AsyncNotifierProvider<MiDiaControlador, Map<String, List<TareaOutlook>>>(MiDiaControlador.new);

class MiDiaScreen extends ConsumerStatefulWidget {
  const MiDiaScreen({super.key});

  @override
  ConsumerState<MiDiaScreen> createState() => _MiDiaScreenState();
}

class _MiDiaScreenState extends ConsumerState<MiDiaScreen> {
  static const limiteSeccion = 30; // como la web: las primeras 30 y «ver las N restantes»
  final Set<String> _expandidas = {};

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final dia = ref.watch(miDiaProvider);
    final c = ref.read(miDiaProvider.notifier);
    final titulos = {
      'vencidas': t.tareasDiaVencidas,
      'hoy': t.tareasDiaHoy,
      'en_progreso': t.tareasDiaEnProgreso,
      'asignadas': t.tareasDiaAsignadas,
      'compartidas': t.tareasDiaCompartidas,
    };
    return Scaffold(
      appBar: AppBar(title: Text(t.tareasTitulo)),
      body: Column(children: [
        const AvisoDatosGuardados(prefijo: '/mi-dia'),
        const AvisoPendientes(),
        const SubnavTareas(),
        Expanded(
          child: dia.when(
            loading: () => const EsqueletoLista(),
            error: (e, _) => EstadoError(error: e, alReintentar: c.refrescar),
            data: (secciones) {
              final total = secciones.values.fold<int>(0, (a, l) => a + l.length);
              return RefreshIndicator(
                onRefresh: c.refrescar,
                child: total == 0
                    ? ListView(physics: const AlwaysScrollableScrollPhysics(), children: [
                        SizedBox(height: 360, child: EstadoVacio(icono: Icons.task_alt, titulo: t.tareasDiaVacio)),
                      ])
                    : ListView(padding: const EdgeInsets.only(bottom: 24), children: [
                        for (final clave in seccionesMiDia)
                          if ((secciones[clave] ?? const []).isNotEmpty) _Seccion(
                            clave: clave,
                            titulo: titulos[clave]!,
                            tareas: secciones[clave]!,
                            expandida: _expandidas.contains(clave),
                            alExpandir: () => setState(() => _expandidas.add(clave)),
                          ),
                      ]),
              );
            },
          ),
        ),
      ]),
    );
  }
}

class _Seccion extends ConsumerWidget {
  final String clave;
  final String titulo;
  final List<TareaOutlook> tareas;
  final bool expandida;
  final VoidCallback alExpandir;
  const _Seccion({required this.clave, required this.titulo, required this.tareas, required this.expandida, required this.alExpandir});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final visibles = expandida ? tareas : tareas.take(_MiDiaScreenState.limiteSeccion).toList();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
        child: Row(children: [
          Text(titulo, style: tema.textTheme.titleMedium?.copyWith(color: clave == 'vencidas' ? aspectoVencida.color(tema.brightness) : null)),
          const SizedBox(width: 8),
          Badge(label: Text('${tareas.length}'), backgroundColor: tema.colorScheme.secondaryContainer, textColor: tema.colorScheme.onSecondaryContainer),
        ]),
      ),
      for (final tarea in visibles)
        FilaTarea(
          key: ValueKey('${clave}_${tarea.id}'),
          tarea: tarea,
          alCompletar: (x) async {
            await cambiarEstadoConAviso(context, ref, x, EstadoTarea.completada, alCambiar: ref.read(miDiaProvider.notifier).reemplazar);
          },
        ),
      if (tareas.length > visibles.length)
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8),
          child: TextButton(onPressed: alExpandir, child: Text(t.tareasVerRestantes(tareas.length - visibles.length))),
        ),
    ]);
  }
}
