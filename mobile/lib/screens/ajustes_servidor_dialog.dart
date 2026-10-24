import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';

import '../services/session_service.dart';

/// Diálogo simple para cambiar la URL del servidor sin salir de la pantalla
/// de login/registro — por defecto apunta a producción (guildawork.com),
/// pero para desarrollo local (LAN, Tailscale, emulador Android) es solo
/// cambiar este valor.
Future<void> mostrarAjustesServidor(
  BuildContext context,
  SessionService sesion,
) async {
  final controlador = TextEditingController(text: await sesion.obtenerServidor());
  if (!context.mounted) return;
  await showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(AppLocalizations.of(context).ajustesServidorTitulo),
      content: TextField(
        controller: controlador,
        decoration: InputDecoration(
          labelText: AppLocalizations.of(context).ajustesServidorUrlLabel,
        ),
        keyboardType: TextInputType.url,
        autocorrect: false,
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: Text(AppLocalizations.of(context).comunCancelar),
        ),
        FilledButton(
          onPressed: () async {
            await sesion.guardarServidor(controlador.text.trim());
            if (context.mounted) Navigator.pop(context);
          },
          child: Text(AppLocalizations.of(context).comunGuardar),
        ),
      ],
    ),
  );
}
