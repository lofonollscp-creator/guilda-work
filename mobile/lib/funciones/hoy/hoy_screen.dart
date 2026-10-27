import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errores.dart';
import '../../diseno/componentes.dart';
import '../../diseno/estados.dart';
import '../../diseno/formatos.dart';
import '../../theme/brand_colors.dart';
import '../../api/generado/modelos.g.dart';
import '../../l10n/app_localizations.dart';
import '../../nucleo/abrir_destino.dart';
import '../../nucleo/destinos.dart';
import '../../nucleo/servicios.dart';
import '../../nucleo/sesion.dart';
import '../avisos/avisos_controlador.dart';
import '../avisos/avisos_screen.dart';
import '../avisos/comunicados.dart';
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
        const BannerComunicados(),
        Expanded(child: RefreshIndicator(
        onRefresh: () async {
          unawaited(ref.read(avisosProvider.notifier).refrescar()); // la insignia de la campana
          ref.invalidate(comunicadosProvider);
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

IconData _iconoDeSeccion(String? clave) => switch (clave) {
      'tareas' => Icons.checklist,
      'correo' => Icons.mail_outline,
      'plazos' => Icons.gavel,
      'vencimientos' => Icons.account_balance_outlined,
      'mensajes' => Icons.forum_outlined,
      'visitas' => Icons.home_work_outlined,
      'traspasos' => Icons.swap_horiz,
      'ausencias' => Icons.beach_access_outlined,
      'facturas' || 'contabilizacion' => Icons.receipt_long_outlined,
      'certificados' => Icons.verified_outlined,
      _ => Icons.inbox_outlined,
    };

class _Seccion extends StatelessWidget {
  final SeccionHoy seccion;
  const _Seccion({required this.seccion});

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final elementos = seccion.elementos ?? const [];
    final hay = seccion.total ?? elementos.length;
    return Card(
      margin: const EdgeInsets.fromLTRB(12, 0, 12, 12),
      clipBehavior: Clip.antiAlias,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 4),
          child: Row(children: [
            Icon(_iconoDeSeccion(seccion.clave), size: 20, color: tema.colorScheme.onSurfaceVariant),
            const SizedBox(width: 8),
            Expanded(child: Text(seccion.titulo ?? '', style: tema.textTheme.titleSmall)),
            Pildora(texto: '$hay'),
          ]),
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
    final oscuro = tema.brightness == Brightness.dark;
    final urgencia = elemento.urgencia ?? ElementoHoyUrgencia.info;
    // La urgencia va escrita en una píldora (y no solo en el color de una barra): quien no distingue colores también la lee.
    final (color, etiqueta, icono) = switch (urgencia) {
      ElementoHoyUrgencia.vencido => (aspectoVencida.color(tema.brightness), t.hoyUrgenciaVencido, Icons.error_outline),
      ElementoHoyUrgencia.hoy => (oscuro ? BrandColors.warningTextDark : BrandColors.warningTextLight, t.hoyUrgenciaHoy, Icons.today_outlined),
      ElementoHoyUrgencia.proximo => (null, t.hoyUrgenciaProximo, Icons.date_range_outlined),
      _ => (null, '', Icons.circle),
    };
    final destino = elemento.destino;
    final fecha = context.formatos.deServidor(elemento.fecha);
    final detalle = [if (elemento.detalle != null && elemento.detalle!.isNotEmpty) elemento.detalle!, ?fecha].join(' · ');
    final puedeCompletar = (elemento.acciones ?? const []).contains('completar') && destino?.tipo == DestinoHoyTipo.tarea && destino?.id != null;

    return Semantics(
      label: etiqueta.isEmpty ? null : '$etiqueta. ${elemento.titulo ?? ''}',
      child: ListTile(
        minVerticalPadding: 8,
        title: Text(elemento.titulo ?? '', maxLines: 2, overflow: TextOverflow.ellipsis, style: tema.textTheme.titleMedium),
        subtitle: (etiqueta.isEmpty && detalle.isEmpty)
            ? null
            : Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                  if (etiqueta.isNotEmpty) Pildora(icono: icono, texto: etiqueta, color: color, fuerte: color != null),
                  if (detalle.isNotEmpty) Text(detalle, style: tema.textTheme.bodySmall, maxLines: 2, overflow: TextOverflow.ellipsis),
                ]),
              ),
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
