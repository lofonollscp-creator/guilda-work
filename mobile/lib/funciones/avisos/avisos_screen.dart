import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/fechas.dart';
import '../../api/generado/modelos.g.dart';
import '../../l10n/app_localizations.dart';
import '../../nucleo/abrir_destino.dart';
import '../../nucleo/destinos.dart';
import 'avisos_controlador.dart';

/// Centro de avisos: lo que ha llegado, agrupado por día. Tocar uno abre su pantalla;
/// deslizar lo borra; «marcar todo como leído» quita la insignia.
class AvisosScreen extends ConsumerWidget {
  const AvisosScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final avisos = ref.watch(avisosProvider);
    final datos = avisos.value;
    final lista = datos?.notificaciones ?? const <Notificacion>[];

    return Scaffold(
      appBar: AppBar(
        title: Text(t.avisosTitulo),
        actions: [
          if ((datos?.noLeidas ?? 0) > 0)
            IconButton(
              icon: const Icon(Icons.done_all),
              tooltip: t.avisosMarcarLeidos,
              onPressed: () => ref.read(avisosProvider.notifier).marcarTodosLeidos(),
            ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => ref.read(avisosProvider.notifier).refrescar(),
        child: datos == null
            ? ListView(children: [
                const SizedBox(height: 160),
                Center(child: avisos.hasError ? _Reintentar(onTap: () => ref.read(avisosProvider.notifier).refrescar()) : const CircularProgressIndicator()),
              ])
            : lista.isEmpty
                ? ListView(children: [const SizedBox(height: 160), Center(child: Text(t.avisosVacio))])
                : ListView(children: _agrupar(context, ref, lista)),
      ),
    );
  }

  List<Widget> _agrupar(BuildContext context, WidgetRef ref, List<Notificacion> lista) {
    final t = AppLocalizations.of(context);
    final ahora = DateTime.now();
    final hoy = Fecha(ahora.year, ahora.month, ahora.day);
    String dia(Notificacion n) {
      final f = Fecha.intentar(n.creadoEn);
      if (f == null) return '';
      final d = f.diasHasta(hoy);
      return d == 0 ? t.hoyUrgenciaHoy : (d == 1 ? t.avisosAyer : '${f.dia.toString().padLeft(2, '0')}/${f.mes.toString().padLeft(2, '0')}/${f.anio}');
    }

    final salida = <Widget>[];
    String? ultimo;
    for (final n in lista) {
      final d = dia(n);
      if (d != ultimo) {
        salida.add(Padding(padding: const EdgeInsets.fromLTRB(16, 16, 16, 4), child: Text(d, style: Theme.of(context).textTheme.labelLarge)));
        ultimo = d;
      }
      salida.add(_Aviso(aviso: n));
    }
    return salida;
  }
}

class _Reintentar extends StatelessWidget {
  final VoidCallback onTap;
  const _Reintentar({required this.onTap});
  @override
  Widget build(BuildContext context) => FilledButton(onPressed: onTap, child: Text(AppLocalizations.of(context).arranqueReintentar));
}

class _Aviso extends ConsumerWidget {
  final Notificacion aviso;
  const _Aviso({required this.aviso});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final noLeido = aviso.leidoEn == null;
    final destino = aviso.destino;
    return Dismissible(
      key: ValueKey('aviso-${aviso.id}'),
      direction: DismissDirection.endToStart,
      background: Container(
        color: Theme.of(context).colorScheme.errorContainer,
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 20),
        child: const Icon(Icons.delete_outline),
      ),
      onDismissed: (_) {
        ref.read(avisosProvider.notifier).eliminar(aviso.id);
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t.avisosEliminado)));
      },
      child: ListTile(
        leading: Icon(_icono(aviso.canal), color: noLeido ? Theme.of(context).colorScheme.primary : null),
        title: Text(aviso.titulo ?? '', style: noLeido ? const TextStyle(fontWeight: FontWeight.w600) : null, maxLines: 2, overflow: TextOverflow.ellipsis),
        subtitle: (aviso.cuerpo ?? '').isEmpty ? null : Text(aviso.cuerpo!, maxLines: 2, overflow: TextOverflow.ellipsis),
        trailing: noLeido ? Semantics(label: t.avisosNoLeidas(1), child: const Icon(Icons.circle, size: 10)) : null,
        onTap: () => ref.read(navegadorDeAvisosProvider).abrir(Destino(destino?.tipo ?? 'aviso', destino?.id), urlWeb: aviso.url),
      ),
    );
  }

  IconData _icono(NotificacionCanal? canal) => switch (canal) {
        NotificacionCanal.tareas => Icons.checklist,
        NotificacionCanal.correo => Icons.mail_outline,
        NotificacionCanal.fiscal => Icons.calendar_month_outlined,
        NotificacionCanal.equipo => Icons.group_outlined,
        NotificacionCanal.resumenes => Icons.summarize_outlined,
        _ => Icons.notifications_none,
      };
}
