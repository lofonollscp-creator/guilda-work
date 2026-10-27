import 'package:flutter/material.dart';

import '../../nucleo/abrir_asistente.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart' show toBeginningOfSentenceCase;

import '../../api/fechas.dart';
import '../../api/generado/modelos.g.dart';
import '../../diseno/componentes.dart';
import '../../diseno/formatos.dart';
import '../../l10n/app_localizations.dart';
import '../../nucleo/abrir_destino.dart';
import '../../nucleo/destinos.dart';
import '../../nucleo/lectura_guardada.dart';
import 'avisos_controlador.dart';
import 'comunicados.dart';

/// Centro de avisos: lo que ha llegado, agrupado por día y filtrable por familia. Tocar uno lo marca leído y abre su pantalla;
/// deslizar lo borra (con «Deshacer»); «marcar todo como leído» quita la insignia.
class AvisosScreen extends ConsumerStatefulWidget {
  const AvisosScreen({super.key});

  @override
  ConsumerState<AvisosScreen> createState() => _AvisosScreenState();
}

/// Qué se enseña: todo, solo lo no leído o una familia de avisos.
sealed class _Filtro {
  const _Filtro();
}

class _Todos extends _Filtro {
  const _Todos();
}

class _SinLeer extends _Filtro {
  const _SinLeer();
}

class _DeCanal extends _Filtro {
  final NotificacionCanal canal;
  const _DeCanal(this.canal);
  @override
  bool operator ==(Object o) => o is _DeCanal && o.canal == canal;
  @override
  int get hashCode => canal.hashCode;
}

class _AvisosScreenState extends ConsumerState<AvisosScreen> {
  _Filtro _filtro = const _Todos();

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final avisos = ref.watch(avisosProvider);
    final datos = avisos.value;
    final todos = datos?.notificaciones ?? const <Notificacion>[];
    final canales = [for (final c in NotificacionCanal.values) if (c != NotificacionCanal.sinReconocer && todos.any((n) => (n.canal ?? NotificacionCanal.general) == c)) c];
    // Si el filtro elegido se queda sin avisos (se leyeron o borraron todos) se vuelve a «Todos».
    final filtro = switch (_filtro) {
      _DeCanal(:final canal) when !canales.contains(canal) => const _Todos(),
      _SinLeer() when (datos?.noLeidas ?? 0) == 0 => const _Todos(),
      final f => f,
    };
    final lista = switch (filtro) {
      _SinLeer() => [for (final n in todos) if (n.leidoEn == null) n],
      _DeCanal(:final canal) => [for (final n in todos) if ((n.canal ?? NotificacionCanal.general) == canal) n],
      _ => todos,
    };

    return Scaffold(
      appBar: AppBar(
        title: Text(t.avisosTitulo),
        actions: [
          AccionAsistente(contexto: t.avisosTitulo),
          if ((datos?.noLeidas ?? 0) > 0)
            IconButton(
              icon: const Icon(Icons.done_all),
              tooltip: t.avisosMarcarLeidos,
              onPressed: () => ref.read(avisosProvider.notifier).marcarTodosLeidos(),
            ),
        ],
      ),
      body: Column(children: [
        const AvisoDatosGuardados(prefijo: '/notificaciones'),
        const BannerComunicados(),
        if (todos.isNotEmpty) _Filtros(filtro: filtro, noLeidas: datos?.noLeidas ?? 0, canales: canales, alElegir: (f) => setState(() => _filtro = f)),
        Expanded(
          child: RefreshIndicator(
            onRefresh: () => ref.read(avisosProvider.notifier).refrescar(),
            child: datos == null
                ? (avisos.hasError ? EstadoError(error: avisos.error!, alReintentar: () => ref.read(avisosProvider.notifier).refrescar()) : const EsqueletoLista())
                : lista.isEmpty
                    ? ListView(physics: const AlwaysScrollableScrollPhysics(), children: [SizedBox(height: 420, child: EstadoVacio(icono: Icons.notifications_none, titulo: t.avisosVacio))])
                    : ListView(padding: const EdgeInsets.only(bottom: 24), children: _agrupar(context, lista)),
          ),
        ),
      ]),
    );
  }

  List<Widget> _agrupar(BuildContext context, List<Notificacion> lista) {
    String dia(Notificacion n) {
      final f = Fecha.intentar(n.creadoEn);
      return f == null ? '' : (toBeginningOfSentenceCase(context.formatos.fecha(f), Localizations.localeOf(context).languageCode) ?? '');
    }

    final salida = <Widget>[];
    String? ultimo;
    for (final n in lista) {
      final d = dia(n);
      if (d != ultimo) {
        salida.add(EtiquetaSeccion(d));
        ultimo = d;
      }
      salida.add(_Aviso(key: ValueKey('aviso-${n.id}'), aviso: n));
    }
    return salida;
  }
}

/// Una fila de píldoras: Todos · Sin leer · y las familias que tienen avisos.
class _Filtros extends StatelessWidget {
  final _Filtro filtro;
  final int noLeidas;
  final List<NotificacionCanal> canales;
  final void Function(_Filtro) alElegir;
  const _Filtros({required this.filtro, required this.noLeidas, required this.canales, required this.alElegir});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    Widget chip(String texto, bool activo, _Filtro f) => Padding(
          padding: const EdgeInsets.only(right: 8),
          child: ChoiceChip(label: Text(texto), selected: activo, onSelected: (_) => alElegir(f)),
        );
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.fromLTRB(12, 10, 4, 4),
      child: Row(children: [
        chip(t.avisosFiltroTodos, filtro is _Todos, const _Todos()),
        if (noLeidas > 0) chip('${t.avisosFiltroSinLeer} ($noLeidas)', filtro is _SinLeer, const _SinLeer()),
        for (final c in canales) chip(nombreDeCanal(t, c), filtro == _DeCanal(c), _DeCanal(c)),
      ]),
    );
  }
}

/// El nombre de la familia de avisos (el mismo que el canal de notificación de Android).
String nombreDeCanal(AppLocalizations t, NotificacionCanal c) => switch (c) {
      NotificacionCanal.tareas => t.canalTareas,
      NotificacionCanal.correo => t.canalCorreo,
      NotificacionCanal.fiscal => t.canalFiscal,
      NotificacionCanal.equipo => t.canalEquipo,
      NotificacionCanal.resumenes => t.canalResumenes,
      _ => t.canalGeneral,
    };

IconData _icono(NotificacionCanal? canal) => switch (canal) {
      NotificacionCanal.tareas => Icons.checklist,
      NotificacionCanal.correo => Icons.mail_outline,
      NotificacionCanal.fiscal => Icons.calendar_month_outlined,
      NotificacionCanal.equipo => Icons.group_outlined,
      NotificacionCanal.resumenes => Icons.summarize_outlined,
      _ => Icons.notifications_none,
    };

class _Aviso extends ConsumerWidget {
  final Notificacion aviso;
  const _Aviso({super.key, required this.aviso});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final noLeido = aviso.leidoEn == null;
    final destino = aviso.destino;
    final hora = MomentoLocal.intentar(aviso.creadoEn);
    final color = tema.colorScheme.primary;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: Dismissible(
        key: ValueKey('desliza-${aviso.id}'),
        direction: DismissDirection.endToStart,
        background: Container(
          decoration: BoxDecoration(color: tema.colorScheme.errorContainer, borderRadius: BorderRadius.circular(16)),
          alignment: Alignment.centerRight,
          padding: const EdgeInsets.only(right: 20),
          child: Icon(Icons.delete_outline, color: tema.colorScheme.onErrorContainer),
        ),
        onDismissed: (_) {
          final c = ref.read(avisosProvider.notifier);
          c.eliminar(aviso.id);
          ScaffoldMessenger.of(context)
            ..hideCurrentSnackBar()
            ..showSnackBar(SnackBar(
              content: Text(t.avisosEliminado),
              duration: AvisosControlador.plazoDeshacer,
              action: SnackBarAction(label: t.comunDeshacer, onPressed: () => c.deshacerEliminar(aviso.id)),
            ));
        },
        child: Material(
          color: noLeido ? Color.alphaBlend(color.withValues(alpha: tema.brightness == Brightness.dark ? 0.10 : 0.07), tema.colorScheme.surface) : tema.colorScheme.surface,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: BorderSide(color: tema.colorScheme.outlineVariant)),
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: () {
              if (noLeido) ref.read(avisosProvider.notifier).marcarLeido(aviso.id);
              ref.read(navegadorDeAvisosProvider).abrir(Destino(destino?.tipo ?? 'aviso', destino?.id), urlWeb: aviso.url);
            },
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                ExcludeSemantics(
                  child: CircleAvatar(
                    radius: 20,
                    backgroundColor: tema.colorScheme.onSurfaceVariant.withValues(alpha: 0.10),
                    child: Icon(_icono(aviso.canal), size: 22, color: tema.colorScheme.onSurfaceVariant),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(aviso.titulo ?? '', style: tema.textTheme.titleSmall?.copyWith(fontWeight: noLeido ? FontWeight.w700 : FontWeight.w500), maxLines: 2, overflow: TextOverflow.ellipsis),
                    if ((aviso.cuerpo ?? '').isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(aviso.cuerpo!, style: tema.textTheme.bodyMedium?.copyWith(color: tema.colorScheme.onSurfaceVariant), maxLines: 2, overflow: TextOverflow.ellipsis),
                    ],
                    if (noLeido) ...[
                      const SizedBox(height: 6),
                      Pildora(icono: Icons.fiber_manual_record, texto: t.avisosNuevo, fuerte: true),
                    ],
                  ]),
                ),
                if (hora != null) Padding(padding: const EdgeInsets.only(left: 8), child: Text(context.formatos.hora(hora.hora, hora.minuto), style: tema.textTheme.labelSmall)),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}
