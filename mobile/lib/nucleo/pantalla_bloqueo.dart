import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../funciones/pendientes/cerrar_sesion.dart';
import '../l10n/app_localizations.dart';
import 'bloqueo.dart';
import 'sesion.dart';

/// Se pone encima de toda la app mientras está bloqueada. Al aparecer pide identificarse sola; si se cancela o falla, quedan el botón de volver
/// a intentarlo y una salida (cerrar sesión) para que la persona nunca quede atrapada.
class PantallaBloqueo extends ConsumerStatefulWidget {
  const PantallaBloqueo({super.key});

  @override
  ConsumerState<PantallaBloqueo> createState() => _PantallaBloqueoState();
}

class _PantallaBloqueoState extends ConsumerState<PantallaBloqueo> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _desbloquear());
  }

  Future<void> _desbloquear() async {
    if (!mounted) return;
    await ref.read(bloqueoProvider.notifier).desbloquear(AppLocalizations.of(context).bloqueoMotivoDesbloquear);
  }

  Future<void> _cerrarSesion() async {
    if (!await confirmarCerrarSesion(ref)) return;
    await ref.read(estadoSesionProvider.notifier).cerrar();
    await ref.read(bloqueoProvider.notifier).alCerrarSesion();
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final tema = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Image.asset('assets/branding/logo.png', height: 96, excludeFromSemantics: true),
              const SizedBox(height: 16),
              Text(t.bloqueoPantallaTitulo, style: tema.textTheme.titleLarge, textAlign: TextAlign.center),
              const SizedBox(height: 24),
              FilledButton.icon(onPressed: _desbloquear, icon: const Icon(Icons.fingerprint), label: Text(t.bloqueoDesbloquear)),
              const SizedBox(height: 8),
              TextButton(onPressed: _cerrarSesion, child: Text(t.bloqueoCerrarSesion)),
            ]),
          ),
        ),
      ),
    );
  }
}

/// Una pantalla en blanco con el logotipo para tapar los datos mientras la app no tiene el foco (la captura del selector de apps).
class CubiertaPrivacidad extends StatelessWidget {
  const CubiertaPrivacidad({super.key});

  @override
  Widget build(BuildContext context) => ColoredBox(
        color: Theme.of(context).scaffoldBackgroundColor,
        child: Center(child: Image.asset('assets/branding/logo.png', height: 96, excludeFromSemantics: true)),
      );
}

/// Se ofrece activar el bloqueo (una sola vez, tras la segunda entrada): si dice que sí, se comprueba identificándose.
Future<void> ofrecerBloqueo(BuildContext context, WidgetRef ref) async {
  final t = AppLocalizations.of(context);
  final activar = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text(t.bloqueoOfertaTitulo),
      content: Text(t.bloqueoOfertaCuerpo),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: Text(t.bloqueoOfertaAhoraNo)),
        FilledButton(onPressed: () => Navigator.pop(c, true), child: Text(t.bloqueoOfertaActivar)),
      ],
    ),
  );
  final control = ref.read(bloqueoProvider.notifier);
  if (activar == true && context.mounted) {
    if (!await control.activar(AppLocalizations.of(context).bloqueoMotivoActivar)) await control.ofertaAtendida();
  } else {
    await control.ofertaAtendida();
  }
}

/// El interruptor de Ajustes.
class InterruptorBloqueo extends ConsumerWidget {
  const InterruptorBloqueo({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = AppLocalizations.of(context);
    final b = ref.watch(bloqueoProvider);
    return SwitchListTile(
      secondary: const Icon(Icons.fingerprint),
      title: Text(t.bloqueoTitulo),
      subtitle: Text(b.disponible ? t.bloqueoSubtitulo : t.bloqueoNoDisponible),
      value: b.activo,
      onChanged: b.disponible
          ? (v) => v
              ? ref.read(bloqueoProvider.notifier).activar(t.bloqueoMotivoActivar)
              : ref.read(bloqueoProvider.notifier).desactivar(t.bloqueoMotivoDesactivar)
          : null,
    );
  }
}
