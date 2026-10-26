import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../l10n/app_localizations.dart';
import 'mi_dia_screen.dart';
import 'tablero_screen.dart';
import 'tareas_screen.dart';

/// Las vistas de tareas, con los mismos nombres y el mismo orden que la web: Mi día · Lista · Tablero.
enum VistaTareas { miDia, lista, tablero }

class VistaTareasControl extends Notifier<VistaTareas> {
  @override
  VistaTareas build() => VistaTareas.lista; // la web también abre en la lista

  void elegir(VistaTareas v) => state = v;
}

final vistaTareasProvider = NotifierProvider<VistaTareasControl, VistaTareas>(VistaTareasControl.new);

/// La pestaña «Tareas»: según la vista elegida enseña Mi día, la Lista o el Tablero. Cada una lleva su barra de vistas ([SubnavTareas]).
class TareasInicio extends ConsumerWidget {
  const TareasInicio({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) => switch (ref.watch(vistaTareasProvider)) {
        VistaTareas.miDia => const MiDiaScreen(),
        VistaTareas.lista => const TareasScreen(),
        VistaTareas.tablero => const TableroScreen(),
      };
}

/// El selector Mi día · Lista · Tablero, igual que el submenú de tareas de la web.
class SubnavTareas extends ConsumerWidget {
  const SubnavTareas({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final actual = ref.watch(vistaTareasProvider);
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
      child: SegmentedButton<VistaTareas>(
        showSelectedIcon: false,
        segments: [
          ButtonSegment(value: VistaTareas.miDia, icon: const Icon(Icons.wb_sunny_outlined, size: 18), label: Text(t.tareasMiDia, maxLines: 1, overflow: TextOverflow.ellipsis)),
          ButtonSegment(value: VistaTareas.lista, icon: const Icon(Icons.view_list_outlined, size: 18), label: Text(t.tareasVistaLista, maxLines: 1, overflow: TextOverflow.ellipsis)),
          ButtonSegment(value: VistaTareas.tablero, icon: const Icon(Icons.view_kanban_outlined, size: 18), label: Text(t.tareasVistaTablero, maxLines: 1, overflow: TextOverflow.ellipsis)),
        ],
        selected: {actual},
        onSelectionChanged: (s) => ref.read(vistaTareasProvider.notifier).elegir(s.first),
      ),
    );
  }
}
