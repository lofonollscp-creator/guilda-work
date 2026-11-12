import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errores.dart';
import '../../diseno/adaptable.dart';
import '../../diseno/v3/v3.dart';
import '../../diseno/componentes.dart';
import '../../diseno/estados.dart';
import '../../diseno/formatos.dart';
import '../../theme/brand_colors.dart';
import '../../api/generado/modelos.g.dart';
import '../../l10n/app_localizations.dart';
import '../../nucleo/barra_v3.dart' show abrirHojaAsistente;
import '../../nucleo/abrir_destino.dart';
import '../../nucleo/destinos.dart';
import '../../nucleo/servicios.dart';
import '../../nucleo/sesion.dart';
import '../avisos/avisos_controlador.dart';
import '../avisos/avisos_screen.dart';
import '../avisos/comunicados.dart';
import '../busqueda/busqueda_screen.dart';
import '../pendientes/pendientes_sheet.dart';
import '../propuestas/propuestas_screen.dart';
import 'hoy_controlador.dart';
import 'hoy_fichaje.dart';

/// «Hoy»: la portada. Un mosaico con lo que necesita tu atención: el resumen del asistente, lo siguiente, tu fichaje y los contadores, y debajo las secciones
/// de todos los módulos del despacho activo por urgencia. Una sola petición (`GET /hoy`) más el estado del fichaje; tirar hacia abajo refresca.
class HoyScreen extends ConsumerWidget {
  const HoyScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final hoy = ref.watch(hoyProvider);
    final despacho = ref.watch(estadoSesionProvider.select((e) => e.capacidades.variosDespachos ? e.capacidades.despachoPorId(e.despacho)?.nombre : null));
    final estado = hoy.value;

    return Scaffold(
      body: RefreshIndicator(
        onRefresh: () async {
          unawaited(ref.read(avisosProvider.notifier).refrescar()); // la insignia de la campana
          ref.invalidate(comunicadosProvider);
          unawaited(ref.read(fichajeHoyProvider.notifier).refrescar());
          await ref.read(hoyProvider.notifier).refrescar();
        },
        child: CustomScrollView(
          physics: const AlwaysScrollableScrollPhysics(),
          slivers: [
            CabeceraGrande(
              titulo: t.navInicio,
              subtitulo: despacho,
              acciones: [
                IconButton(
                  icon: const Icon(Icons.search),
                  tooltip: t.busquedaTitulo,
                  onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const BusquedaScreen())),
                ),
                _Campana(sinLeer: ref.watch(avisosNoLeidosProvider)),
              ],
            ),
            const SliverToBoxAdapter(child: Column(children: [AvisoPendientes(), BannerComunicados()])),
            if (estado == null)
              SliverToBoxAdapter(child: hoy.hasError ? _Error(error: hoy.error!) : const _Cargando())
            else
              ..._bandeja(context, estado.bandeja, desactualizado: estado.desactualizado, obtenidoEn: estado.obtenidoEn),
            const SliverToBoxAdapter(child: SizedBox(height: 24)),
          ],
        ),
      ),
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

/// Mientras llega la bandeja: el mosaico en esqueleto, con su brillo.
class _Cargando extends StatelessWidget {
  const _Cargando();
  @override
  Widget build(BuildContext context) => const Padding(
        padding: EdgeInsets.fromLTRB(12, 12, 12, 0),
        child: Brillo(
          child: Column(children: [
            BloqueEsqueleto(alto: 120, radio: V3.radioM),
            SizedBox(height: 12),
            BloqueEsqueleto(alto: 150, radio: V3.radioM),
            SizedBox(height: 12),
            Row(children: [Expanded(child: BloqueEsqueleto(alto: 90, radio: V3.radioM)), SizedBox(width: 12), Expanded(child: BloqueEsqueleto(alto: 90, radio: V3.radioM))]),
          ]),
        ),
      );
}

class _Error extends ConsumerWidget {
  final Object error;
  const _Error({required this.error});

  @override
  Widget build(BuildContext context, WidgetRef ref) =>
      SizedBox(height: 420, child: EstadoError(error: error, alReintentar: () => ref.read(hoyProvider.notifier).refrescar()));
}

/// El mosaico y las secciones, como slivers.
List<Widget> _bandeja(BuildContext context, BandejaHoy bandeja, {required bool desactualizado, required DateTime obtenidoEn}) {
  final t = AppLocalizations.of(context);
  final secciones = bandeja.secciones ?? const [];
  final aviso = desactualizado ? t.hoySinConexionDatosDe(context.formatos.hora(obtenidoEn.hour, obtenidoEn.minute)) : null;
  const ia = _TarjetaIa();
  const propuestas = TarjetaPropuestas();
  final siguiente = _LoSiguiente(bandeja: bandeja);
  const fichaje = TarjetaFichajeHoy();
  final contadores = _Contadores(total: bandeja.total ?? 0, urgentes: bandeja.urgentes ?? 0);
  const hueco = SizedBox(height: 12);

  Widget mosaico() {
    if (esAncha(context)) {
      // Tableta: dos columnas (el asistente y lo siguiente a la izquierda; el fichaje y los contadores a la derecha).
      return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(child: Column(children: [ia, hueco, propuestas, siguiente])),
        const SizedBox(width: 12),
        Expanded(child: Column(children: [fichaje, hueco, contadores])),
      ]);
    }
    return Column(children: [ia, hueco, propuestas, siguiente, fichaje, hueco, contadores]);
  }

  return [
    if (aviso != null) SliverToBoxAdapter(child: BannerEstado(tipo: TipoBanner.sinConexion, texto: aviso)),
    SliverPadding(padding: const EdgeInsets.fromLTRB(12, 12, 12, 12), sliver: SliverToBoxAdapter(child: mosaico())),
    if (secciones.isEmpty)
      SliverToBoxAdapter(child: SizedBox(height: 320, child: EstadoVacio(icono: Icons.check_circle_outline, titulo: t.hoyTodoAlDia, detalle: t.hoyTodoAlDiaDetalle)))
    else if (esAncha(context))
      // Tableta: las secciones en dos columnas (la 1.ª, la 3.ª… a la izquierda; la 2.ª, la 4.ª… a la derecha).
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final columna in [0, 1])
              Expanded(child: Column(children: [for (var i = columna; i < secciones.length; i += 2) _Seccion(seccion: secciones[i])])),
          ]),
        ),
      )
    else
      SliverList.builder(itemCount: secciones.length, itemBuilder: (_, i) => _Seccion(seccion: secciones[i])),
  ];
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
      'certificados' || 'certificados_riesgo' => Icons.verified_outlined,
      _ => Icons.inbox_outlined,
    };

/// El asistente, en lo alto: el orbe y un toque para pedirle el resumen del día (él lo prepara al momento; aquí no se inventa nada).
/// Los números van en los contadores de debajo: aquí no se repiten.
class _TarjetaIa extends StatelessWidget {
  const _TarjetaIa();

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final p = PaletaV3.de(context);
    return TarjetaBento(
      tono: TonoBento.ia,
      alPulsar: () => abrirHojaAsistente(context, consulta: t.iaHoyResumenConsulta, contexto: t.navInicio),
      etiqueta: t.iaHoyResumen,
      child: ExcludeSemantics(
        child: Row(children: [
          const OrbeIa(tamano: 52),
          const SizedBox(width: 14),
          Expanded(child: Text(t.iaHoyResumen, style: tema.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800))),
          Icon(Icons.chevron_right, color: p.ia.acento),
        ]),
      ),
    );
  }
}

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
    final p = PaletaV3.de(context);
    final fondo = TarjetaBento.fondoDe(p, TonoBento.acento);
    final vencido = e.urgencia == ElementoHoyUrgencia.vencido;
    final color = vencido ? aspectoVencida.color(tema.brightness) : (tema.brightness == Brightness.dark ? BrandColors.warningTextDark : BrandColors.warningTextLight);
    final destino = e.destino!;
    final detalle = [if (e.detalle != null && e.detalle!.isNotEmpty) e.detalle!, ?context.formatos.deServidor(e.fecha)].join(' · ');
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: TarjetaBento(
        tono: TonoBento.acento,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Pildora(icono: vencido ? Icons.error_outline : Icons.today_outlined, texto: vencido ? t.hoyUrgenciaVencido : t.hoyUrgenciaHoy, color: color, fuerte: true),
            const SizedBox(width: 8),
            Text(t.hoyLoSiguiente, style: tema.textTheme.labelMedium?.copyWith(color: p.suaveSobre(fondo))),
          ]),
          const SizedBox(height: 10),
          Text(e.titulo ?? '', style: tema.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800), maxLines: 3, overflow: TextOverflow.ellipsis),
          if (detalle.isNotEmpty) ...[const SizedBox(height: 4), Text(detalle, style: tema.textTheme.bodySmall?.copyWith(color: p.suaveSobre(fondo)), maxLines: 2, overflow: TextOverflow.ellipsis)],
          const SizedBox(height: 14),
          FilledButton(
            onPressed: () => ref.read(navegadorDeAvisosProvider).abrir(Destino(destino.tipo?.valor ?? 'aviso', destino.id), urlWeb: e.url),
            child: Text(t.hoyAbrir),
          ),
        ]),
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
    final p = PaletaV3.de(context);
    Widget caja(int n, String etiqueta, {Color? color}) => Expanded(
          child: TarjetaBento(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('$n', style: tema.textTheme.headlineMedium?.copyWith(color: color, fontWeight: FontWeight.w800)),
              Text(etiqueta, style: tema.textTheme.bodySmall?.copyWith(color: p.textoSuave)),
            ]),
          ),
        );
    return Row(children: [
      caja(total, t.hoyContadorPendientes),
      const SizedBox(width: 12),
      caja(urgentes, t.hoyContadorUrgentes, color: urgentes > 0 ? aspectoVencida.color(tema.brightness) : null),
    ]);
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
