import 'package:flutter/material.dart';

import '../services/api_client.dart';
import 'correo_reglas_categoria_screen.dart';
import 'correo_remitentes_confiables_screen.dart';

/// Ajustes de correo en el móvil (Fase 5): punto de entrada a las dos
/// pantallas de gestión nuevas — remitentes de confianza y reglas de
/// categorización — mismo concepto que "Ajustes de correo" en la web.
class CorreoAjustesScreen extends StatelessWidget {
  final ApiClient api;

  const CorreoAjustesScreen({super.key, required this.api});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Ajustes de correo')),
      body: ListView(
        children: [
          ListTile(
            leading: const Icon(Icons.shield_outlined),
            title: const Text('Remitentes de confianza'),
            subtitle: const Text('Sus imágenes y adjuntos no se bloquean/avisan'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => CorreoRemitentesConfiablesScreen(api: api)),
            ),
          ),
          ListTile(
            leading: const Icon(Icons.rule),
            title: const Text('Reglas de categorización'),
            subtitle: const Text('Categoriza el correo entrante según el remitente'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => CorreoReglasCategoriaScreen(api: api)),
            ),
          ),
        ],
      ),
    );
  }
}
