import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../datos/cola.dart';
import '../../datos/local/cola_escritura.dart';
import '../../l10n/app_localizations.dart';

/// «N cambios pendientes de enviar»: aparece arriba cuando hay escrituras hechas sin conexión que aún no han llegado al servidor.
/// Tocarlo abre la lista de pendientes (reintentar, aplicar igualmente tras un conflicto, descartar).
class AvisoPendientes extends ConsumerWidget {
  const AvisoPendientes({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final n = ref.watch(numPendientesProvider);
    if (n == 0) return const SizedBox.shrink();
    final t = AppLocalizations.of(context);
    return Material(
      color: Theme.of(context).colorScheme.secondaryContainer,
      child: InkWell(
        onTap: () => showModalBottomSheet<void>(context: context, isScrollControlled: true, builder: (_) => const PendientesSheet()),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          child: Row(children: [
            const Icon(Icons.cloud_upload_outlined, size: 20),
            const SizedBox(width: 10),
            Expanded(child: Text(t.colaPendientes(n))),
            const Icon(Icons.chevron_right),
          ]),
        ),
      ),
    );
  }
}

/// La lista de lo que está sin enviar, con lo que se puede hacer con cada cosa.
class PendientesSheet extends ConsumerWidget {
  const PendientesSheet({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final pendientes = ref.watch(pendientesProvider).value ?? const <Pendiente>[];
    final cola = ref.read(colaEscrituraProvider);
    final procesador = ref.read(procesadorColaProvider);

    return SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: MediaQuery.of(context).size.height * 0.75),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(title: Text(t.colaTitulo, style: Theme.of(context).textTheme.titleMedium)),
          Flexible(
            child: ListView(shrinkWrap: true, children: [
              for (final p in pendientes)
                ListTile(
                  isThreeLine: p.error != null,
                  title: Text(p.descripcion, maxLines: 2, overflow: TextOverflow.ellipsis),
                  subtitle: Text([_estado(t, p.estado), if (p.error != null) p.error!].join('\n')),
                  trailing: Wrap(spacing: 0, children: [
                    if (p.estado == EstadoPendiente.conflicto && p.versionActual != null)
                      TextButton(
                        onPressed: () async {
                          await cola.reintentarConVersion(p.id, p.versionActual!);
                          await procesador.procesar();
                        },
                        child: Text(t.colaAplicar),
                      ),
                    if (p.estado == EstadoPendiente.pendiente)
                      IconButton(
                        icon: const Icon(Icons.refresh),
                        tooltip: t.colaReintentar,
                        onPressed: () async {
                          await cola.reintentarAhora(p.id);
                          await procesador.procesar();
                        },
                      ),
                    IconButton(icon: const Icon(Icons.delete_outline), tooltip: t.colaDescartar, onPressed: () => cola.eliminar(p.id)),
                  ]),
                ),
            ]),
          ),
        ]),
      ),
    );
  }

  String _estado(AppLocalizations t, EstadoPendiente e) => switch (e) {
        EstadoPendiente.pendiente => t.colaEstadoPendiente,
        EstadoPendiente.enviando => t.colaEstadoEnviando,
        EstadoPendiente.conflicto => t.colaEstadoConflicto,
        EstadoPendiente.rechazada => t.colaEstadoRechazada,
      };
}
