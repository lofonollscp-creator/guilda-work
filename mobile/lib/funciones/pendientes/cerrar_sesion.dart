import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../datos/cola.dart';
import '../../l10n/app_localizations.dart';
import '../../nucleo/rutas.dart';
import '../../nucleo/sesion.dart';

/// Antes de cerrar sesión: si quedan cambios sin enviar, avisa de que se perderán. `true` = seguir (y, si los había, ya se han descartado).
Future<bool> confirmarCerrarSesion(WidgetRef ref) async {
  final usuario = ref.read(estadoSesionProvider).usuario;
  final pendientes = ref.read(numPendientesProvider);
  if (usuario == null || pendientes == 0) return true;
  final contexto = ref.read(routerProvider).routerDelegate.navigatorKey.currentContext;
  if (contexto == null || !contexto.mounted) return true;
  final t = AppLocalizations.of(contexto);
  final cerrar = await showDialog<bool>(
        context: contexto,
        builder: (c) => AlertDialog(
          content: Text(t.colaCerrarSesionAviso(pendientes)),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: Text(t.comunCancelar)),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: Text(t.colaCerrarSesionAccion)),
          ],
        ),
      ) ??
      false;
  if (cerrar) await ref.read(colaEscrituraProvider).vaciar(usuario.id);
  return cerrar;
}
