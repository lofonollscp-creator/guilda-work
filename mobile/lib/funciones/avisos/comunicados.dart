import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/generado/modelos.g.dart';
import '../../diseno/componentes.dart';
import '../../l10n/app_localizations.dart';
import '../../nucleo/servicios.dart';
import '../../nucleo/sesion.dart';

/// Los comunicados de la plataforma vigentes (`GET /comunicados`): mantenimiento, novedades, incidencias. Lo mismo que el banner de la web.
/// Si no se pueden pedir (sin red) simplemente no se enseña nada: no es motivo de error.
class ComunicadosControlador extends AsyncNotifier<List<Comunicado>> {
  @override
  Future<List<Comunicado>> build() async {
    ref.watch(estadoSesionProvider.select((e) => e.despacho));
    try {
      final crudo = await ref.read(clienteApiProvider).enviar('GET', '/comunicados');
      return [for (final c in crudo as List) Comunicado.fromJson(Map<String, dynamic>.from(c as Map))];
    } catch (_) {
      return const [];
    }
  }

  /// Cierra uno (los críticos no se pueden cerrar: el servidor los mantiene). Desaparece sin esperar.
  Future<void> cerrar(int id) async {
    final actual = state.value ?? const <Comunicado>[];
    state = AsyncData([for (final c in actual) if (c.id != id) c]);
    try {
      await ref.read(clienteApiProvider).enviar('POST', '/comunicados/$id/cerrar');
    } catch (_) {
      ref.invalidateSelf();
    }
  }
}

final comunicadosProvider = AsyncNotifierProvider<ComunicadosControlador, List<Comunicado>>(ComunicadosControlador.new);

/// Las franjas de comunicados (info / aviso / crítico). No ocupa nada si no hay.
class BannerComunicados extends ConsumerWidget {
  const BannerComunicados({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final lista = ref.watch(comunicadosProvider).value ?? const <Comunicado>[];
    if (lista.isEmpty) return const SizedBox.shrink();
    final t = AppLocalizations.of(context);
    return Column(children: [
      for (final c in lista)
        BannerEstado(
          tipo: switch (c.nivel) {
            ComunicadoNivel.critico => TipoBanner.error,
            ComunicadoNivel.aviso => TipoBanner.aviso,
            _ => TipoBanner.info,
          },
          texto: [c.titulo, c.texto].where((x) => (x ?? '').trim().isNotEmpty).join(' · '),
          accion: c.nivel == ComunicadoNivel.critico || c.id == null ? null : t.comunicadoCerrar,
          alAccionar: c.id == null ? null : () => ref.read(comunicadosProvider.notifier).cerrar(c.id!),
        ),
    ]);
  }
}
