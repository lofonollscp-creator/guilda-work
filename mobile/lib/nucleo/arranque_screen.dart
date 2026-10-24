import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import 'sesion.dart';

/// Mientras se comprueba la sesión guardada. Sin red no se cierra la sesión:
/// se ofrece reintentar.
class ArranqueScreen extends ConsumerWidget {
  const ArranqueScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final sinConexion = ref.watch(estadoSesionProvider.select((e) => e.sinConexion));
    return Scaffold(
      body: Center(
        child: sinConexion
            ? Padding(
                padding: const EdgeInsets.all(24),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  const Icon(Icons.cloud_off_outlined, size: 48),
                  const SizedBox(height: 12),
                  Text(t.arranqueSinConexion, textAlign: TextAlign.center),
                  const SizedBox(height: 16),
                  FilledButton(
                    onPressed: () => ref.read(estadoSesionProvider.notifier).arrancar(),
                    child: Text(t.arranqueReintentar),
                  ),
                ]),
              )
            : const CircularProgressIndicator(),
      ),
    );
  }
}
