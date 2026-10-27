import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errores.dart';
import '../../diseno/adaptable.dart';
import '../../diseno/asistente.dart';
import '../../diseno/componentes.dart';
import '../../diseno/estados.dart';
import '../../diseno/formatos.dart';
import '../../theme/brand_colors.dart';
import '../../api/generado/modelos.g.dart';
import '../../l10n/app_localizations.dart';
import '../../nucleo/abrir_asistente.dart';
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
        // El asistente, siempre a mano y sin ocupar la pantalla: una barra compacta bajo la lista.
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
          child: BarraAsistente(pista: t.iaBarraHint, alPulsar: () => abrirAsistente(context, contexto: t.navInicio)),
        ),
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

class _Bandeja extends ConsumerWidget {
  final BandejaHoy bandeja;
  final bool desactualizado;
  final DateTime obtenidoEn;
  const _Bandeja({required this.bandeja, required this.desactualizado, required this.obtenidoEn});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final secciones = bandeja.secciones ?? const [];
    final cabecera = <Widget>[
      _LoSiguiente(bandeja: bandeja),
      _ResumenIa(alAbrir: () => abrirAsistente(context, consulta: t.iaHoyResumenConsulta, contexto: t.navInicio)),
      _Contadores(total: bandeja.total ?? 0, urgentes: bandeja.urgentes ?? 0),
    ];
    final aviso = desactualizado ? t.hoySinConexionDatosDe(context.formatos.hora(obtenidoEn.hour, obtenidoEn.minute)) : null;

    if (secciones.isEmpty) {
      return ListView(physics: const AlwaysScrollableScrollPhysics(), children: [
        if (aviso != null) BannerEstado(tipo: TipoBanner.sinConexion, texto: aviso),
        SizedBox(height: 420, child: EstadoVacio(icono: Icons.check_circle_outline, titulo: t.hoyTodoAlDia, detalle: t.hoyTodoAlDiaDetalle)),
      ]);
    }

    return ListView(padding: const EdgeInsets.only(bottom: 24), children: [
      if (aviso != null) BannerEstado(tipo: TipoBanner.sinConexion, texto: aviso),
      ...cabecera,
      if (esAncha(context))
        // Tableta: las secciones en dos columnas (la 1.ª, la 3.ª… a la izquierda; la 2.ª, la 4.ª… a la derecha).
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final columna in [0, 1])
              Expanded(child: Column(children: [for (var i = columna; i < secciones.length; i += 2) _Seccion(seccion: secciones[i])])),
          ]),
        )
      else
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

/// «Lo siguiente»: lo más urgente de la bandeja, con un botón para abrirlo (así sabes por dónde empezar sin recorrer toda la lista).
class _LoSiguiente extends ConsumerWidget {
  final BandejaHoy bandeja;
  const _LoSiguiente({required this.bandeja});

  ElementoHoy? _elegir() {
    final todos = [for (final s in bandeja.secciones ?? const <SeccionHoy>[]) ...(s.elementos ?? const <ElementoHoy>[])];
    for (final u in [ElementoHoyUrgencia.vencido, ElementoHoyUrgencia.hoy]) {
      for (final e in todos) {
        if (e.urgencia == u && e.destino != null) return e;
      }
    }
    return null;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final e = _elegir();
    if (e == null) return const SizedBox.shrink();
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final vencido = e.urgencia == ElementoHoyUrgencia.vencido;
    final color = vencido ? aspectoVencida.color(tema.brightness) : (tema.brightness == Brightness.dark ? BrandColors.warningTextDark : BrandColors.warningTextLight);
    final destino = e.destino!;
    final detalle = [if (e.detalle != null && e.detalle!.isNotEmpty) e.detalle!, ?context.formatos.deServidor(e.fecha)].join(' · ');
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 12, 12, 0),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: tema.colorScheme.surface, border: Border.all(color: tema.colorScheme.primary.withValues(alpha: 0.5)), borderRadius: BorderRadius.circular(18)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Pildora(icono: vencido ? Icons.error_outline : Icons.today_outlined, texto: vencido ? t.hoyUrgenciaVencido : t.hoyUrgenciaHoy, color: color, fuerte: true),
          const SizedBox(width: 8),
          Text(t.hoyLoSiguiente, style: tema.textTheme.labelMedium),
        ]),
        const SizedBox(height: 10),
        Text(e.titulo ?? '', style: tema.textTheme.titleLarge, maxLines: 3, overflow: TextOverflow.ellipsis),
        if (detalle.isNotEmpty) ...[const SizedBox(height: 4), Text(detalle, style: tema.textTheme.bodySmall, maxLines: 2, overflow: TextOverflow.ellipsis)],
        const SizedBox(height: 12),
        FilledButton(
          style: FilledButton.styleFrom(shape: const StadiumBorder(), minimumSize: const Size.fromHeight(48)),
          onPressed: () => ref.read(navegadorDeAvisosProvider).abrir(Destino(destino.tipo?.valor ?? 'aviso', destino.id), urlWeb: e.url),
          child: Text(t.hoyAbrir),
        ),
      ]),
    );
  }
}

/// Una línea para pedirle al asistente el resumen del día (él lo prepara al momento; aquí no se inventa nada).
class _ResumenIa extends StatelessWidget {
  final VoidCallback alAbrir;
  const _ResumenIa({required this.alAbrir});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final c = ColoresIa.de(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 0),
      child: Material(
        color: c.fondo,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: BorderSide(color: c.borde)),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: alAbrir,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 52),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Row(children: [
                const InsigniaIa(tamano: 26),
                const SizedBox(width: 10),
                Expanded(child: Text(t.iaHoyResumen, style: Theme.of(context).textTheme.titleSmall?.copyWith(color: c.sobreFondo, fontWeight: FontWeight.w700))),
                ExcludeSemantics(child: Icon(Icons.chevron_right, color: c.sobreFondo)),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

/// Dos números grandes: lo pendiente y lo urgente.
class _Contadores extends StatelessWidget {
  final int total;
  final int urgentes;
  const _Contadores({required this.total, required this.urgentes});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    Widget caja(int n, String etiqueta, {Color? color}) => Expanded(
          child: Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(color: tema.colorScheme.surface, border: Border.all(color: tema.colorScheme.outlineVariant), borderRadius: BorderRadius.circular(16)),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('$n', style: tema.textTheme.headlineMedium?.copyWith(color: color, fontWeight: FontWeight.w800)),
              Text(etiqueta, style: tema.textTheme.bodySmall),
            ]),
          ),
        );
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
      child: Row(children: [
        caja(total, t.hoyContadorPendientes),
        const SizedBox(width: 10),
        caja(urgentes, t.hoyContadorUrgentes, color: urgentes > 0 ? aspectoVencida.color(tema.brightness) : null),
      ]),
    );
  }
}

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
