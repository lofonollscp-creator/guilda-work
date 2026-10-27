import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errores.dart';
import '../../diseno/componentes.dart';
import '../../l10n/app_localizations.dart';
import '../../theme/brand_colors.dart';
import '../notas/notas_lista_controlador.dart';
import '../tareas/calendario_screen.dart' show calendarioProvider;
import '../tareas/mi_dia_screen.dart' show miDiaProvider;
import '../tareas/tablero_screen.dart' show tableroProvider;
import '../tareas/tareas_lista_controlador.dart';
import 'papelera_repositorio.dart';

/// Los días que la papelera guarda lo borrado antes de purgarlo solo.
const diasEnPapelera = 30;

/// Cuántos días le quedan a algo borrado en [borradoEn] (la hora local del servidor); 0 = se purga hoy.
int diasRestantes(String? borradoEn, {DateTime? ahora}) {
  final d = borradoEn == null ? null : DateTime.tryParse(borradoEn);
  if (d == null) return diasEnPapelera;
  return (diasEnPapelera - (ahora ?? DateTime.now()).difference(d).inDays).clamp(0, diasEnPapelera);
}

/// Lo que se ve en cada grupo de la fila de píldoras.
enum _Grupo {
  todo,
  notas,
  tareas,
  proyectos,
  fiscal;

  bool admite(ElementoPapelera e) => switch (this) {
        _Grupo.todo => true,
        _Grupo.notas => !e.fiscal && e.origen == 'nota',
        _Grupo.tareas => !e.fiscal && (e.origen == 'tarea_outlook' || e.origen == 'tarea'),
        _Grupo.proyectos => !e.fiscal && e.origen == 'menu',
        _Grupo.fiscal => e.fiscal,
      };

  String etiqueta(AppLocalizations t) => switch (this) {
        _Grupo.todo => t.busquedaFiltroTodo,
        _Grupo.notas => t.busquedaFiltroNotas,
        _Grupo.tareas => t.busquedaFiltroTareas,
        _Grupo.proyectos => t.papeleraFiltroProyectos,
        _Grupo.fiscal => t.busquedaFiltroFiscal,
      };
}

/// La papelera: lo borrado (notas, tareas, proyectos y lo del calendario fiscal) con los días que le quedan, para recuperarlo o eliminarlo para siempre.
class PapeleraScreen extends ConsumerStatefulWidget {
  const PapeleraScreen({super.key});

  @override
  ConsumerState<PapeleraScreen> createState() => _PapeleraScreenState();
}

class _PapeleraScreenState extends ConsumerState<PapeleraScreen> {
  _Grupo _grupo = _Grupo.todo;

  void _aviso(String texto) => ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(texto)));

  Future<void> _restaurar(ElementoPapelera e) async {
    final t = AppLocalizations.of(context);
    try {
      await ref.read(papeleraRepositorioProvider).restaurar(e);
    } on ApiException catch (err) {
      if (mounted) _aviso(err.mensaje);
      return;
    }
    ref.read(papeleraProvider.notifier).quitar(e);
    // Lo recuperado reaparece en su lista: las que ya estaban abiertas se vuelven a pedir.
    ref.invalidate(notasListaProvider);
    ref.invalidate(tareasListaProvider);
    ref.invalidate(tableroProvider);
    ref.invalidate(miDiaProvider);
    ref.invalidate(calendarioProvider);
    if (mounted) _aviso(t.papeleraRestaurada);
  }

  Future<void> _eliminar(ElementoPapelera e) async {
    final t = AppLocalizations.of(context);
    final seguro = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        content: Text(e.origen == 'menu' ? t.papeleraEliminarProyectoPregunta : t.papeleraEliminarPregunta),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: Text(t.comunCancelar)),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: Text(t.papeleraEliminarSiempre)),
        ],
      ),
    );
    if (seguro != true) return;
    try {
      await ref.read(papeleraRepositorioProvider).eliminarParaSiempre(e);
    } on ApiException catch (err) {
      if (mounted) _aviso(err.mensaje);
      return;
    }
    ref.read(papeleraProvider.notifier).quitar(e);
    if (mounted) _aviso(t.papeleraEliminado);
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final papelera = ref.watch(papeleraProvider);
    final todo = papelera.value;
    final grupos = [for (final g in _Grupo.values) if (g == _Grupo.todo || (todo ?? const []).any(g.admite)) g];
    final grupo = grupos.contains(_grupo) ? _grupo : _Grupo.todo;
    final visibles = [for (final e in todo ?? const <ElementoPapelera>[]) if (grupo.admite(e)) e];
    return Scaffold(
      appBar: AppBar(title: Text(t.papeleraTitulo)),
      body: RefreshIndicator(
        onRefresh: () => ref.read(papeleraProvider.notifier).refrescar(),
        child: todo == null
            ? (papelera.hasError ? EstadoError(error: papelera.error!, alReintentar: () => ref.read(papeleraProvider.notifier).refrescar()) : const EsqueletoLista())
            : todo.isEmpty
                ? ListView(physics: const AlwaysScrollableScrollPhysics(), children: [SizedBox(height: 420, child: EstadoVacio(icono: Icons.delete_outline, titulo: t.papeleraVacia, detalle: t.papeleraAyuda))])
                : ListView(padding: const EdgeInsets.only(bottom: 24), children: [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                      child: Text(t.papeleraAyuda, style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant)),
                    ),
                    if (grupos.length > 2)
                      SingleChildScrollView(
                        scrollDirection: Axis.horizontal,
                        padding: const EdgeInsets.fromLTRB(12, 8, 4, 4),
                        child: Row(children: [
                          for (final g in grupos)
                            Padding(
                              padding: const EdgeInsets.only(right: 8),
                              child: ChoiceChip(label: Text('${g.etiqueta(t)} (${todo.where(g.admite).length})'), selected: g == grupo, onSelected: (_) => setState(() => _grupo = g)),
                            ),
                        ]),
                      ),
                    for (final e in visibles) _Fila(key: ValueKey(e.clave), elemento: e, alRestaurar: () => _restaurar(e), alEliminar: () => _eliminar(e)),
                  ]),
      ),
    );
  }
}

class _Fila extends StatelessWidget {
  final ElementoPapelera elemento;
  final VoidCallback alRestaurar;
  final VoidCallback alEliminar;
  const _Fila({super.key, required this.elemento, required this.alRestaurar, required this.alEliminar});

  (IconData, String) _tipo(AppLocalizations t) => switch (elemento.origen) {
        'nota' => (Icons.sticky_note_2_outlined, t.busquedaTipoNota),
        'tarea_outlook' => (Icons.checklist, t.busquedaTipoTarea),
        'tarea' => elemento.dato.tipo == 'instantanea' ? (Icons.bolt_outlined, t.papeleraTipoEvento) : (Icons.timer_outlined, t.busquedaTipoTarea),
        'menu' => (Icons.folder_outlined, t.papeleraTipoProyecto),
        'cliente_fiscal' => (Icons.business_outlined, t.busquedaTipoCliente),
        'vencimiento_fiscal' => (Icons.calendar_month_outlined, t.busquedaTipoVencimiento),
        _ => (Icons.delete_outline, elemento.origen),
      };

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final (icono, tipo) = _tipo(t);
    final d = elemento.dato;
    final quedan = diasRestantes(d.papeleraEn);
    final texto = (d.texto ?? '').trim().split('\n').first;
    final contexto = d.categoriaNombre ?? d.clienteNombre;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: Material(
        color: tema.colorScheme.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: BorderSide(color: tema.colorScheme.outlineVariant)),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 12, 4, 8),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              ExcludeSemantics(
                child: CircleAvatar(radius: 20, backgroundColor: tema.colorScheme.onSurfaceVariant.withValues(alpha: 0.10), child: Icon(icono, size: 22, color: tema.colorScheme.onSurfaceVariant)),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(texto.isEmpty ? tipo : texto, style: tema.textTheme.titleSmall, maxLines: 2, overflow: TextOverflow.ellipsis),
                  const SizedBox(height: 6),
                  Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                    Pildora(texto: tipo),
                    if ((contexto ?? '').isNotEmpty) Pildora(icono: Icons.folder_outlined, texto: contexto!),
                    Pildora(icono: Icons.hourglass_bottom, texto: t.papeleraQuedan(quedan), fuerte: quedan <= 3, color: quedan <= 3 ? (tema.brightness == Brightness.dark ? BrandColors.warningTextDark : BrandColors.warningTextLight) : null),
                  ]),
                ]),
              ),
              if (elemento.sePuedeEliminar)
                PopupMenuButton<String>(
                  icon: const Icon(Icons.more_vert),
                  onSelected: (_) => alEliminar(),
                  itemBuilder: (_) => [PopupMenuItem(value: 'eliminar', child: Text(t.papeleraEliminarSiempre))],
                )
              else
                const SizedBox(width: 10),
            ]),
            Align(
              alignment: Alignment.centerRight,
              child: Padding(
                padding: const EdgeInsets.only(right: 8),
                child: FilledButton.tonalIcon(onPressed: alRestaurar, icon: const Icon(Icons.restore, size: 18), label: Text(t.papeleraRestaurar)),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}
