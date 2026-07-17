import 'package:flutter/material.dart';

import '../services/session_service.dart';

/// Diálogo simple para cambiar la URL del servidor sin salir de la pantalla
/// de login/registro — necesario mientras el hosting (Tailscale/VPS, ver
/// HOSTING.md/CASERO.md) no esté resuelto: por defecto apunta al PC de
/// desarrollo vía el alias del emulador Android, pero cualquier servidor
/// (LAN, Tailscale, VPS) es solo cambiar este valor.
Future<void> mostrarAjustesServidor(
  BuildContext context,
  SessionService sesion,
) async {
  final controlador = TextEditingController(text: await sesion.obtenerServidor());
  if (!context.mounted) return;
  await showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('Servidor'),
      content: TextField(
        controller: controlador,
        decoration: const InputDecoration(
          labelText: 'URL base (ej. http://10.0.2.2:8000)',
        ),
        keyboardType: TextInputType.url,
        autocorrect: false,
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          onPressed: () async {
            await sesion.guardarServidor(controlador.text.trim());
            if (context.mounted) Navigator.pop(context);
          },
          child: const Text('Guardar'),
        ),
      ],
    ),
  );
}
