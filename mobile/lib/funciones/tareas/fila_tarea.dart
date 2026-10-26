import 'package:flutter/material.dart';

import '../../api/generado/modelos.g.dart';
import '../../diseno/componentes.dart';
import '../../diseno/formatos.dart';
import '../../dominio/tarea.dart';
import '../../l10n/app_localizations.dart';
import 'tarea_detalle_screen.dart';
import 'textos.dart';

/// Una tarea en una lista (Lista y «Mi día»): casilla para completarla, asunto, estado, vencimiento y los mismos indicadores que la web
/// (proyecto, comentarios, checklist, «espera a…», quién la asignó). Con [alSeleccionar] admite pulsación larga para marcar varias.
class FilaTarea extends StatelessWidget {
  final TareaOutlook tarea;
  final Future<void> Function(TareaOutlook) alCompletar;
  final bool pendiente; // hecha sin conexión, aún sin enviar
  final bool seleccionada;
  final bool enSeleccion;

  /// Marcar para una acción en lote (null = esta pantalla no tiene selección: «Mi día»).
  final VoidCallback? alSeleccionar;
  const FilaTarea({super.key, required this.tarea, required this.alCompletar, this.pendiente = false, this.seleccionada = false, this.enSeleccion = false, this.alSeleccionar});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final estado = EstadoTarea.desde(tarea.estado);
    final hecha = !estado.abierta;
    final vencida = tarea.vencida == true && !hecha;
    final fecha = context.formatos.deServidor(tarea.fechaVencimiento);

    return ListTile(
      minVerticalPadding: 10,
      selected: seleccionada,
      selectedTileColor: tema.colorScheme.primaryContainer.withValues(alpha: 0.4),
      // En selección el cuadro marca la tarea para la acción en lote; fuera de ella, la completa.
      leading: Checkbox(
        value: enSeleccion ? seleccionada : hecha,
        onChanged: enSeleccion && alSeleccionar != null ? (_) => alSeleccionar!() : ((hecha || tarea.id < 0) ? null : (_) => alCompletar(tarea)),
        semanticLabel: enSeleccion ? t.tareasSeleccionar : t.hoyCompletar,
      ),
      title: Text(
        tarea.asunto ?? '',
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
        style: hecha ? TextStyle(decoration: TextDecoration.lineThrough, color: tema.colorScheme.outline) : null,
      ),
      // Estado = icono + etiqueta + color; lo vencido en rojo con su palabra («Vencida»): nunca solo color.
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Wrap(spacing: 12, runSpacing: 2, crossAxisAlignment: WrapCrossAlignment.center, children: [
          ChipEstado(estado: estado, etiqueta: etiquetaEstado(t, estado), vencida: false),
          if (vencida) ChipEstado(estado: estado, etiqueta: '${t.tareasVencida}${fecha == null ? '' : ' · $fecha'}', vencida: true)
          else if (fecha != null) Text(fecha, style: tema.textTheme.labelMedium),
          if (PrioridadTarea.desde(tarea.prioridad) == PrioridadTarea.alta) Text(etiquetaPrioridad(t, PrioridadTarea.alta), style: tema.textTheme.labelMedium?.copyWith(fontWeight: FontWeight.w700)),
          if ((tarea.categoriaNombre ?? '').isNotEmpty) Proyecto(nombre: tarea.categoriaNombre!, color: tarea.categoriaColor),
          if (tarea.rol == 'asignada') Indicador(icono: Icons.person_outline, texto: t.tareaRolAsignada),
          if (tarea.rol == 'compartida') Indicador(icono: Icons.group_outlined, texto: t.tareaRolCompartida),
          if ((tarea.bloqueos ?? 0) > 0) Indicador(icono: Icons.lock_clock_outlined, texto: t.tareaIndEspera(tarea.bloqueos!)),
          if ((tarea.checklistTotal ?? 0) > 0) Indicador(icono: Icons.checklist, texto: t.tareaIndChecklist(tarea.checklistHechas ?? 0, tarea.checklistTotal!)),
          if ((tarea.nComentarios ?? 0) > 0) Indicador(icono: Icons.chat_bubble_outline, texto: t.tareaIndComentarios(tarea.nComentarios!), soloNumero: '${tarea.nComentarios}'),
        ]),
      ),
      trailing: pendiente
          ? Tooltip(message: t.colaTareaPendiente, child: const Icon(Icons.cloud_upload_outlined, size: 18))
          : ((tarea.motivoBloqueo ?? '').isNotEmpty ? const Icon(Icons.hourglass_empty, size: 18) : null),
      onTap: tarea.id < 0
          ? null
          : (enSeleccion && alSeleccionar != null ? alSeleccionar : () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => TareaDetalleScreen(tareaId: tarea.id)))),
      onLongPress: tarea.id < 0 ? null : alSeleccionar,
    );
  }
}

/// Un dato pequeño de la fila (icono + texto). `soloNumero`: se enseña solo ese número, y el texto largo queda para el lector de pantalla.
class Indicador extends StatelessWidget {
  final IconData icono;
  final String texto;
  final String? soloNumero;
  const Indicador({required this.icono, required this.texto, this.soloNumero});

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Semantics(
      label: texto,
      excludeSemantics: true,
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(icono, size: 14, color: tema.colorScheme.outline),
        const SizedBox(width: 3),
        Text(soloNumero ?? texto, style: tema.textTheme.labelMedium),
      ]),
    );
  }
}

/// El proyecto de la tarea, con su color (si lo tiene) en un punto; el nombre va siempre escrito.
class Proyecto extends StatelessWidget {
  final String nombre;
  final String? color;
  const Proyecto({required this.nombre, this.color});

  Color? get _punto {
    final h = (color ?? '').replaceFirst('#', '');
    final v = h.length == 6 ? int.tryParse(h, radix: 16) : null;
    return v == null ? null : Color(0xFF000000 | v);
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(Icons.folder_outlined, size: 14, color: _punto ?? tema.colorScheme.outline),
      const SizedBox(width: 3),
      Flexible(child: Text(nombre, style: tema.textTheme.labelMedium, overflow: TextOverflow.ellipsis)),
    ]);
  }
}

