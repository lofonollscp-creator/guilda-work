import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../l10n/app_localizations.dart';
import 'sesion.dart';

/// «Actualiza la app»: el servidor contestó 426 o la versión es menor que la
/// mínima que anuncia (S-10 del plan). Bloquea el resto de la app.
class ActualizarScreen extends ConsumerWidget {
  const ActualizarScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final url = ref.watch(estadoSesionProvider.select((e) => e.urlTienda));
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.system_update_outlined, size: 56),
              const SizedBox(height: 16),
              Text(t.actualizarTitulo, style: Theme.of(context).textTheme.titleLarge, textAlign: TextAlign.center),
              const SizedBox(height: 8),
              Text(t.actualizarCuerpo, textAlign: TextAlign.center),
              if (url != null) ...[
                const SizedBox(height: 24),
                FilledButton(
                  onPressed: () => launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication),
                  child: Text(t.actualizarBoton),
                ),
              ],
            ]),
          ),
        ),
      ),
    );
  }
}
