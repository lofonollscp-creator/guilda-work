import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errores.dart';
import '../../diseno/componentes.dart';
import '../../diseno/v3/v3.dart';
import '../../l10n/app_localizations.dart';
import 'propuestas_controlador.dart';

/// «El asistente propone»: lo pendiente de aprobar, con el porqué de cada cosa y *Aprobar* / *Rechazar*. Nada se hace hasta que tú lo decides.
class PropuestasScreen extends ConsumerWidget {
  const PropuestasScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final propuestas = ref.watch(propuestasProvider);
    final lista = propuestas.value;
    return Scaffold(
      appBar: AppBar(title: Text(t.propuestasTitulo)),
      body: RefreshIndicator(
        onRefresh: () => ref.read(propuestasProvider.notifier).refrescar(),
        child: lista == null
            ? (propuestas.hasError
                ? ListView(children: [SizedBox(height: 420, child: EstadoError(error: propuestas.error!, alReintentar: () => ref.read(propuestasProvider.notifier).refrescar()))])
                : const Center(child: CircularProgressIndicator()))
            : lista.isEmpty
                ? ListView(children: [SizedBox(height: 420, child: EstadoVacio(icono: Icons.auto_awesome, titulo: t.propuestasVacioTitulo, detalle: t.propuestasVacioDetalle))])
                : ListView.builder(
                    padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
                    itemCount: lista.length + 1,
                    itemBuilder: (_, i) => i == 0
                        ? Padding(padding: const EdgeInsets.fromLTRB(4, 0, 4, 12), child: Text(t.propuestasIntro, style: Theme.of(context).textTheme.bodyMedium))
                        : Padding(padding: const EdgeInsets.only(bottom: 12), child: _TarjetaPropuesta(propuesta: lista[i - 1])),
                  ),
      ),
    );
  }
}

class _TarjetaPropuesta extends ConsumerStatefulWidget {
  final PropuestaIa propuesta;
  const _TarjetaPropuesta({required this.propuesta});

  @override
  ConsumerState<_TarjetaPropuesta> createState() => _TarjetaPropuestaState();
}

class _TarjetaPropuestaState extends ConsumerState<_TarjetaPropuesta> {
  bool _trabajando = false;

  Future<void> _resolver(bool aprobar) async {
    final t = AppLocalizations.of(context);
    final mensajero = ScaffoldMessenger.of(context);
    final p = widget.propuesta;
    if (aprobar && p.actuaFuera) {
      final seguro = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: Text(t.propuestasConfirmarTitulo),
          content: Text(t.propuestasConfirmarCuerpo),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: Text(t.comunCancelar)),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: Text(t.propuestasAprobar)),
          ],
        ),
      );
      if (seguro != true) return;
    }
    setState(() => _trabajando = true);
    try {
      final c = ref.read(propuestasProvider.notifier);
      if (aprobar) {
        await c.aprobar(p);
        Haptica.hecho();
        mensajero.showSnackBar(SnackBar(content: Text(t.propuestasAprobada)));
      } else {
        await c.rechazar(p);
        mensajero.showSnackBar(SnackBar(content: Text(t.propuestasRechazada)));
      }
    } on ApiException catch (e) {
      // 409: ya la había resuelto otra persona; la lista se pone al día.
      mensajero.showSnackBar(SnackBar(content: Text(mensajeDeError(t, e))));
      if (e.categoria == CategoriaError.conflicto) await ref.read(propuestasProvider.notifier).refrescar();
    } finally {
      if (mounted) setState(() => _trabajando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final p = widget.propuesta;
    final pa = PaletaV3.de(context);
    final fondo = TarjetaBento.fondoDe(pa, TonoBento.ia);
    return TarjetaBento(
      tono: TonoBento.ia,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 8, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
          const ExcludeSemantics(child: OrbeIa(tamano: 22)),
          Text(t.propuestasPropone, style: tema.textTheme.labelMedium?.copyWith(color: pa.suaveSobre(fondo), fontWeight: FontWeight.w700)),
          if (p.urgente) Pildora(icono: Icons.priority_high, texto: t.propuestasUrgente, color: tema.brightness == Brightness.dark ? const Color(0xFFFF8A80) : const Color(0xFFB3261E), fuerte: true),
        ]),
        const SizedBox(height: 10),
        Text(p.titulo, style: tema.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
        if (p.detalle.isNotEmpty) ...[const SizedBox(height: 4), Text(p.detalle, style: tema.textTheme.bodyMedium?.copyWith(color: pa.suaveSobre(fondo)))],
        const SizedBox(height: 14),
        Row(children: [
          Expanded(child: OutlinedButton(onPressed: _trabajando ? null : () => _resolver(false), child: Text(t.propuestasRechazar))),
          const SizedBox(width: 10),
          Expanded(child: FilledButton(onPressed: _trabajando ? null : () => _resolver(true), child: Text(t.propuestasAprobar))),
        ]),
      ]),
    );
  }
}

/// El aviso de propuestas pendientes: una tarjeta (en Hoy y en el inicio del chat) que lleva a la bandeja. No sale si no hay ninguna.
class TarjetaPropuestas extends ConsumerWidget {
  final EdgeInsetsGeometry margen;
  const TarjetaPropuestas({super.key, this.margen = const EdgeInsets.only(bottom: 12)});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final n = ref.watch(propuestasPendientesProvider);
    if (n == 0) return const SizedBox.shrink();
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    final p = PaletaV3.de(context);
    final fondo = TarjetaBento.fondoDe(p, TonoBento.ia);
    return Padding(
      padding: margen,
      child: TarjetaBento(
        tono: TonoBento.ia,
        alPulsar: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const PropuestasScreen())),
        etiqueta: '${t.propuestasHoy(n)}. ${t.propuestasHoyDetalle}',
        child: ExcludeSemantics(
          child: Row(children: [
            Icon(Icons.auto_awesome, color: p.ia.acento),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(t.propuestasHoy(n), style: tema.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800)),
                Text(t.propuestasHoyDetalle, style: tema.textTheme.bodySmall?.copyWith(color: p.suaveSobre(fondo))),
              ]),
            ),
            Icon(Icons.chevron_right, color: p.ia.acento),
          ]),
        ),
      ),
    );
  }
}
