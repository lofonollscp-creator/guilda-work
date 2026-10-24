import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errores.dart';
import '../../diseno/componentes.dart';
import '../../diseno/formatos.dart';
import '../../api/generado/modelos.g.dart';
import '../../l10n/app_localizations.dart';
import '../../nucleo/abrir_destino.dart';
import '../../nucleo/destinos.dart';
import '../../nucleo/servicios.dart';
import '../../nucleo/sesion.dart';
import '../avisos/avisos_controlador.dart';
import '../avisos/avisos_screen.dart';
import '../busqueda/busqueda_screen.dart';
import '../pendientes/pendientes_sheet.dart';
import 'hoy_controlador.dart';

/// «Hoy»: lo que necesita tu atención, de todos los módulos del despacho activo,
/// por urgencia. Una sola petición (`GET /hoy`); tirar hacia abajo refresca.
class HoyScreen extends ConsumerWidget {
  const HoyScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final hoy = ref.watch(hoyProvider);
    final despacho = ref.watch(estadoSesionProvider.select((e) => e.capacidades.variosDespachos ? e.capacidades.despachoPorId(e.despacho)?.nombre : null));
    final estado = hoy.value;

    return Scaffold(
      appBar: AppBar(
        title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t.navInicio),
          if (despacho != null) Text(despacho, style: Theme.of(context).textTheme.bodySmall),
        ]),
        actions: [
          IconButton(
            icon: const Icon(Icons.search),
            tooltip: t.busquedaTitulo,
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const BusquedaScreen())),
          ),
          _Campana(sinLeer: ref.watch(avisosNoLeidosProvider)),
        ],
      ),
      body: Column(children: [
        const AvisoPendientes(),
        Expanded(child: RefreshIndicator(
        onRefresh: () async {
          unawaited(ref.read(avisosProvider.notifier).refrescar()); // la insignia de la campana
          await ref.read(hoyProvider.notifier).refrescar();
        },
        child: estado == null
            ? (hoy.hasError ? _Error(error: hoy.error!) : const _Cargando())
            : _Bandeja(bandeja: estado.bandeja, desactualizado: estado.desactualizado, obtenidoEn: estado.obtenidoEn),
        )),
      ]),
    );
  }
}

/// La campana de avisos con su insignia de sin leer.
class _Campana extends StatelessWidget {
  final int sinLeer;
  const _Campana({required this.sinLeer});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    return IconButton(
      icon: Badge(isLabelVisible: sinLeer > 0, label: Text(sinLeer > 99 ? '99+' : '$sinLeer'), child: const Icon(Icons.notifications_none)),
      tooltip: sinLeer > 0 ? t.avisosNoLeidas(sinLeer) : t.avisosTitulo,
      onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const AvisosScreen())),
    );
  }
}

class _Cargando extends StatelessWidget {
  const _Cargando();
  @override
  Widget build(BuildContext context) => const EsqueletoLista();
}

class _Error extends ConsumerWidget {
  final Object error;
  const _Error({required this.error});

  @override
  Widget build(BuildContext context, WidgetRef ref) => EstadoError(error: error, alReintentar: () => ref.read(hoyProvider.notifier).refrescar());
}

class _Bandeja extends StatelessWidget {
  final BandejaHoy bandeja;
  final bool desactualizado;
  final DateTime obtenidoEn;
  const _Bandeja({required this.bandeja, required this.desactualizado, required this.obtenidoEn});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final secciones = bandeja.secciones ?? const [];
    final aviso = desactualizado ? t.hoySinConexionDatosDe(context.formatos.hora(obtenidoEn.hour, obtenidoEn.minute)) : null;

    if (secciones.isEmpty) {
      return ListView(physics: const AlwaysScrollableScrollPhysics(), children: [
        if (aviso != null) BannerEstado(tipo: TipoBanner.sinConexion, texto: aviso),
        SizedBox(height: 420, child: EstadoVacio(icono: Icons.check_circle_outline, titulo: t.hoyTodoAlDia, detalle: t.hoyTodoAlDiaDetalle)),
      ]);
    }

    return ListView(padding: const EdgeInsets.only(bottom: 24), children: [
      if (aviso != null) BannerEstado(tipo: TipoBanner.sinConexion, texto: aviso),
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
        child: Text(
          [t.hoyResumenTotal(bandeja.total ?? 0), if ((bandeja.urgentes ?? 0) > 0) t.hoyResumenUrgentes(bandeja.urgentes!)].join(' · '),
          style: Theme.of(context).textTheme.titleMedium,
        ),
      ),
      for (final s in secciones) _Seccion(seccion: s),
    ]);
  }
}

class _Seccion extends StatelessWidget {
  final SeccionHoy seccion;
  const _Seccion({required this.seccion});

  @override
  Widget build(BuildContext context) {
    final elementos = seccion.elementos ?? const [];
    final hay = seccion.total ?? elementos.length;
    return Card(
      margin: const EdgeInsets.fromLTRB(12, 0, 12, 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
          child: Text('${seccion.titulo ?? ''}  ·  $hay', style: Theme.of(context).textTheme.titleSmall),
        ),
        for (final e in elementos) _Elemento(elemento: e),
      ]),
    );
  }
}

class _Elemento extends ConsumerWidget {
  final ElementoHoy elemento;
  const _Elemento({required this.elemento});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final urgencia = elemento.urgencia ?? ElementoHoyUrgencia.info;
    final (color, etiqueta) = switch (urgencia) {
      ElementoHoyUrgencia.vencido => (tema.colorScheme.error, t.hoyUrgenciaVencido),
      ElementoHoyUrgencia.hoy => (tema.colorScheme.tertiary, t.hoyUrgenciaHoy),
      ElementoHoyUrgencia.proximo => (tema.colorScheme.primary, t.hoyUrgenciaProximo),
      _ => (tema.colorScheme.outline, ''),
    };
    final destino = elemento.destino;
    final fecha = context.formatos.deServidor(elemento.fecha);
    final detalle = [if (elemento.detalle != null && elemento.detalle!.isNotEmpty) elemento.detalle!, ?fecha].join(' · ');
    final puedeCompletar = (elemento.acciones ?? const []).contains('completar') && destino?.tipo == DestinoHoyTipo.tarea && destino?.id != null;

    return Semantics(
      label: etiqueta.isEmpty ? null : '$etiqueta. ${elemento.titulo ?? ''}',
      child: ListTile(
        minVerticalPadding: 8,
        leading: Container(width: 6, height: 40, decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(3))),
        title: Text(elemento.titulo ?? '', maxLines: 2, overflow: TextOverflow.ellipsis),
        subtitle: detalle.isEmpty ? null : Text(detalle, maxLines: 2, overflow: TextOverflow.ellipsis),
        trailing: puedeCompletar
            ? IconButton(
                icon: const Icon(Icons.check_circle_outline),
                tooltip: t.hoyCompletar,
                onPressed: () => _completar(context, ref, destino!.id!),
              )
            : null,
        onTap: destino == null ? null : () => ref.read(navegadorDeAvisosProvider).abrir(Destino(destino.tipo?.valor ?? 'aviso', destino.id), urlWeb: elemento.url),
      ),
    );
  }

  Future<void> _completar(BuildContext context, WidgetRef ref, int tareaId) async {
    final t = AppLocalizations.of(context);
    final mensajero = ScaffoldMessenger.of(context);
    try {
      await ref.read(serviciosProvider).api.completarTareaOutlook(tareaId);
      await ref.read(hoyProvider.notifier).refrescar();
      mensajero.showSnackBar(SnackBar(content: Text(t.hoyCompletada)));
    } on ApiException catch (e) {
      mensajero.showSnackBar(SnackBar(content: Text(e.mensaje)));
    }
  }

}
