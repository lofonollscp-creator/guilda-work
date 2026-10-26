import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../l10n/app_localizations.dart';
import 'calendario_screen.dart';
import 'carga_screen.dart';
import 'mi_dia_screen.dart';
import 'tablero_screen.dart';
import 'tareas_screen.dart';

/// Las vistas de tareas, con los mismos nombres y el mismo orden que el submenú de la web: Mi día · Lista · Tablero · Calendario · Carga.
enum VistaTareas { miDia, lista, tablero, calendario, carga }

class VistaTareasControl extends Notifier<VistaTareas> {
  @override
  VistaTareas build() => VistaTareas.lista; // la web también abre en la lista

  void elegir(VistaTareas v) => state = v;
}

final vistaTareasProvider = NotifierProvider<VistaTareasControl, VistaTareas>(VistaTareasControl.new);

/// La pestaña «Tareas»: según la vista elegida enseña una u otra. Cada una lleva su barra de vistas ([SubnavTareas]).
class TareasInicio extends ConsumerWidget {
  const TareasInicio({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) => switch (ref.watch(vistaTareasProvider)) {
        VistaTareas.miDia => const MiDiaScreen(),
        VistaTareas.lista => const TareasScreen(),
        VistaTareas.tablero => const TableroScreen(),
        VistaTareas.calendario => const CalendarioScreen(),
        VistaTareas.carga => const CargaScreen(),
      };
}

/// El selector de vistas, igual que el submenú de tareas de la web. Cinco caben mal en un móvil: se desliza.
class SubnavTareas extends ConsumerWidget {
  const SubnavTareas({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final actual = ref.watch(vistaTareasProvider);
    final etiquetas = {
      VistaTareas.miDia: (t.tareasMiDia, Icons.wb_sunny_outlined),
      VistaTareas.lista: (t.tareasVistaLista, Icons.view_list_outlined),
      VistaTareas.tablero: (t.tareasVistaTablero, Icons.view_kanban_outlined),
      VistaTareas.calendario: (t.tareasCalendario, Icons.calendar_month_outlined),
      VistaTareas.carga: (t.tareasCarga, Icons.stacked_bar_chart_outlined),
    };
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
      child: Row(children: [
        for (final e in etiquetas.entries)
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: ChoiceChip(
              avatar: Icon(e.value.$2, size: 18),
              label: Text(e.value.$1),
              selected: actual == e.key,
              onSelected: (_) => ref.read(vistaTareasProvider.notifier).elegir(e.key),
            ),
          ),
      ]),
    );
  }
}
