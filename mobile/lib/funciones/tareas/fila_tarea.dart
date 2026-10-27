import 'package:flutter/material.dart';

import '../../api/generado/modelos.g.dart';
import '../../diseno/componentes.dart';
import '../../diseno/estados.dart';
import '../../diseno/formatos.dart';
import '../../theme/brand_colors.dart';
import '../../dominio/tarea.dart';
import '../../l10n/app_localizations.dart';
import 'tarea_detalle_screen.dart';
import 'textos.dart';

/// Una tarea en una lista (Lista, «Mi día», calendario): una tarjeta con la casilla redonda para completarla, el asunto, el estado y el vencimiento en píldoras,
/// y los indicadores de la web (proyecto, comentarios, checklist, «espera a…», quién la asignó). La barra de color de la izquierda marca la prioridad alta
/// (y siempre va acompañada de la palabra «Alta»). Deslizar hacia la derecha la completa (con «Deshacer»); con [alSeleccionar], la pulsación larga marca varias.
class FilaTarea extends StatelessWidget {
  final TareaOutlook tarea;
  final Future<void> Function(TareaOutlook) alCompletar;
  final bool pendiente; // hecha sin conexión, aún sin enviar
  final bool seleccionada;
  final bool enSeleccion;

  /// Marcar para una acción en lote (null = esta pantalla no tiene selección: «Mi día»).
  final VoidCallback? alSeleccionar;

  /// En tableta la ficha se abre al lado: quien lo pasa recibe el id en vez de empujar una pantalla.
  final void Function(int id)? alAbrir;

  /// La que está abierta en el panel de al lado (se rodea con el color de acento).
  final bool abierta;
  const FilaTarea({super.key, required this.tarea, required this.alCompletar, this.pendiente = false, this.seleccionada = false, this.enSeleccion = false, this.alSeleccionar, this.alAbrir, this.abierta = false});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final oscuro = tema.brightness == Brightness.dark;
    final estado = EstadoTarea.desde(tarea.estado);
    final hecha = !estado.abierta;
    final vencida = tarea.vencida == true && !hecha;
    final fecha = context.formatos.deServidor(tarea.fechaVencimiento);
    final alta = PrioridadTarea.desde(tarea.prioridad) == PrioridadTarea.alta && !hecha;
    final aspecto = vencida ? aspectoVencida : aspectoDe(estado);
    final colorAlta = oscuro ? BrandColors.warningTextDark : BrandColors.warningTextLight;
    final puedeDeslizar = !hecha && tarea.id > 0 && !enSeleccion && !pendiente;

    final tarjeta = Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: Material(
      color: seleccionada ? Color.alphaBlend(tema.colorScheme.primary.withValues(alpha: 0.18), tema.colorScheme.surface) : tema.colorScheme.surface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: BorderSide(color: seleccionada || abierta ? tema.colorScheme.primary : tema.colorScheme.outlineVariant, width: seleccionada || abierta ? 1.5 : 1)),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: tarea.id < 0
            ? null
            : (enSeleccion && alSeleccionar != null
                ? alSeleccionar
                : () => alAbrir != null ? alAbrir!(tarea.id) : Navigator.of(context).push(MaterialPageRoute(builder: (_) => TareaDetalleScreen(tareaId: tarea.id)))),
        onLongPress: tarea.id < 0 ? null : alSeleccionar,
        child: IntrinsicHeight(
          child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Container(width: 4, color: alta ? colorAlta : Colors.transparent),
            // En selección la casilla marca la tarea para la acción en lote; fuera de ella, la completa.
            Padding(
              padding: const EdgeInsets.only(left: 4, top: 2),
              child: Align(
                alignment: Alignment.topCenter,
                child: Checkbox(
                  value: enSeleccion ? seleccionada : hecha,
                  onChanged: enSeleccion && alSeleccionar != null ? (_) => alSeleccionar!() : ((hecha || tarea.id < 0) ? null : (_) => alCompletar(tarea)),
                  semanticLabel: enSeleccion ? t.tareasSeleccionar : t.hoyCompletar,
                ),
              ),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(2, 12, 12, 12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(
                    tarea.asunto ?? '',
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: tema.textTheme.titleMedium?.copyWith(decoration: hecha ? TextDecoration.lineThrough : null, color: hecha ? tema.colorScheme.outline : null),
                  ),
                  const SizedBox(height: 8),
                  // Estado = icono + etiqueta + color; lo vencido en rojo con su palabra («Vencida»): nunca solo color.
                  Wrap(spacing: 6, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
                    Pildora(icono: aspecto.icono, texto: etiquetaEstado(t, estado), color: aspectoDe(estado).color(tema.brightness)),
                    if (vencida) Pildora(icono: Icons.error_outline, texto: '${t.tareasVencida}${fecha == null ? '' : ' · $fecha'}', color: aspectoVencida.color(tema.brightness), fuerte: true)
                    else if (fecha != null) Pildora(icono: Icons.event_outlined, texto: fecha),
                    if (alta) Pildora(icono: Icons.flag_outlined, texto: etiquetaPrioridad(t, PrioridadTarea.alta), color: colorAlta, fuerte: true),
                    if ((tarea.categoriaNombre ?? '').isNotEmpty) Pildora(icono: Icons.folder_outlined, texto: tarea.categoriaNombre!),
                    if (tarea.rol == 'asignada') Pildora(icono: Icons.person_outline, texto: t.tareaRolAsignada),
                    if (tarea.rol == 'compartida') Pildora(icono: Icons.group_outlined, texto: t.tareaRolCompartida),
                    if ((tarea.bloqueos ?? 0) > 0) Pildora(icono: Icons.lock_clock_outlined, texto: t.tareaIndEspera(tarea.bloqueos!), color: oscuro ? BrandColors.warningTextDark : BrandColors.warningTextLight),
                    if ((tarea.checklistTotal ?? 0) > 0) Indicador(icono: Icons.checklist, texto: t.tareaIndChecklist(tarea.checklistHechas ?? 0, tarea.checklistTotal!)),
                    if ((tarea.nComentarios ?? 0) > 0) Indicador(icono: Icons.chat_bubble_outline, texto: t.tareaIndComentarios(tarea.nComentarios!), soloNumero: '${tarea.nComentarios}'),
                  ]),
                ]),
              ),
            ),
            if (pendiente) Padding(padding: const EdgeInsets.only(right: 12, top: 12), child: Align(alignment: Alignment.topCenter, child: Tooltip(message: t.colaTareaPendiente, child: const Icon(Icons.cloud_upload_outlined, size: 18)))),
          ]),
        ),
      ),
      ),
    );

    if (!puedeDeslizar) return tarjeta;
    return Dismissible(
      key: ValueKey('desliza_${tarea.id}'),
      direction: DismissDirection.startToEnd,
      dismissThresholds: const {DismissDirection.startToEnd: 0.4},
      // La tarea no se «quita» aquí: se completa y la pantalla ya la saca (o la deja, si el servidor lo rechaza), así que la tarjeta vuelve a su sitio.
      confirmDismiss: (_) async {
        await alCompletar(tarea);
        return false;
      },
      background: Container(
        margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        padding: const EdgeInsets.only(left: 20),
        alignment: Alignment.centerLeft,
        decoration: BoxDecoration(color: tema.colorScheme.primary, borderRadius: BorderRadius.circular(16)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.check, color: BrandColors.onAccent),
          const SizedBox(width: 8),
          Text(t.hoyCompletar, style: tema.textTheme.labelLarge?.copyWith(color: BrandColors.onAccent)),
        ]),
      ),
      child: tarjeta,
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

